"""Parity of the flexible-exit study's kernel with the league's rule engine (PREREG_EXITFLEX.md sections 3-5 and 11.4
item 13), trade for trade, on SYNTHETIC multi-coin data only.

    python -m pytest -q tests/test_exitflex_league_parity.py

The two sides, fed the same bars and the same signals:

  study   research/exitflex/kernel_x.py ``simulate`` -> ``account_x`` (numba): 1m arrays per coin, chart bars built from
          the 1m bars by the study's own ``run.build_frame``, the account of section 4 over six coins.
  league  ``candleague.runner.League.advance`` -> ``rulex.chunk_rule`` (chart records and signals per UTC day, from 5m
          klines), ``rulex.replay_day`` (the aligned 1m steps of the six coins), ``RuleEngine`` / ``RuleLadderEngine``
          (the rule exit) and the plain engines of ``candleague.exits`` (the E0 twins), one SQLite database, and a run
          that stops and restarts from the database in the middle of open positions (``audit_restored`` runs on each
          restart and must find the stored rule state equal to its recomputation).

World: six coins, 62 days of 1m bars (a 52-day warm-up, then the 10 judged days), a seeded random walk with jumps, open
gaps, wick spikes, crashes of 3-8% at an open, a mark price that differs from the last price, 8-hourly funding, and what a real
feed does to ONE coin while the others trade: missing minutes (random ones, the last minute of a bin, the minute at a chart
close), short outages, an outage that swallows a whole bar after a signal, and halts (flat bars without volume in the league's
feed, no minute in the study's data, one of them on a funding settlement). Signals are a fixed function of (coin, timeframe,
bar open time), long or short, never both on one bar, with a "best"/"normal" leverage group. Every family F1-F10 of the 82
study ids (F7h included) runs in both modes (and with q15) at quarter and live size, with the E0 twins, on a 1h pick; subsets run
on 15m, 30m and 4h picks (one with a stop so wide that signals are rejected), on a stepped-lock exit, and as coin-flip accounts.
Negative controls run the same data through a league as it was before this test (the union of the coins' minutes, checks dropped
while a signal waits, halts kept as minutes, no memory of each coin's last minute across a restart) and must show a difference.

Compared per trade: coin, side, entry time and price, exit time and price (not a liquidation's), reason, leverage,
the wallet change (equity after the trade) to 1e-9 of the wallet; per account: the number of trades, the final wallet
and the position still open at the end. The test prints only pass or fail: the data are made up and no figure is a
result. Readings the league follows because the pre-registration says so are in ``rulex.replay_day`` (the coin's own
minutes: a minute missing for one coin does not move that coin's fills and checks).

Not covered, because the league side has no such rule yet: F11 (the strategies' own exits) and F12 (all at once).
"""

from __future__ import annotations

import bisect
import copy
import datetime as dt
import json
import os
import shutil
import sys
from dataclasses import replace

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "research", "exitflex"), os.path.join(ROOT, "research", "fullgrid")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

pytest.importorskip("numba")

import data_x as DX  # noqa: E402
import kernel_x as KX  # noqa: E402
from candleague import league as L  # noqa: E402
from candleague import rulex as RX  # noqa: E402
from candleague import runner as RN  # noqa: E402
from paperbot import paramshadow as PS  # noqa: E402
from paperbot import sweepsig  # noqa: E402
from paperbot.engine import PaperEngine  # noqa: E402
from paperbot.models import Bar, Signal  # noqa: E402

K = KX.K
R = DX.fg()
MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
SYMS = DX.SYMBOLS
P0 = {"BTCUSDT": 30_000.0, "ETHUSDT": 1_900.0, "SOLUSDT": 60.0, "DOGEUSDT": 0.09, "LTCUSDT": 75.0, "BCHUSDT": 240.0}
D_START = int(dt.datetime(2023, 9, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)       # the data's first minute
WARM_DAYS, SPAN_DAYS = 52, 10                                                          # 4h picks need 50 days of bars
T_START = D_START + WARM_DAYS * DAY                                                    # the league's start
T_END = T_START + SPAN_DAYS * DAY                                                      # exclusive end of the data
N_MIN = (WARM_DAYS + SPAN_DAYS) * 1440
LAST_SIGNAL_CLOSE = T_END - 8 * HOUR
SLIP = 0.0002
WALLET_TOL = 1e-9                  # of the wallet before the trade (PREREG 11.4 item 13)
PRICE_TOL = 1e-10                  # relative
EX = R.exchange(DX.EXCHANGE, False)
LIB = sweepsig.lib()
BRACKETS, SPECS, _EXSRC = RN.load_exchange(RN.EXCHANGE_FILE, SYMS)


# ====================================================================================================== synthetic bars
def synth_coin(seed, price0, vol=0.0007, jump_p=0.0015, open_gap_p=0.0006, spike_p=0.002, drop=0.0015, extra_missing=(),
               crashes=()):
    """One coin of 1m arrays in data.py's layout: a random walk, jumps, open gaps, wick spikes, ``crashes`` (minute, factor):
    the price opens at the factor times the previous close and stays there, a mark price that differs from the last price,
    8-hourly funding (``fund`` as data.py puts it, on the minute or the next one present; ``rawf`` as the exchange reports it),
    missing minutes (random ones and ``extra_missing``)."""
    rng = np.random.default_rng(seed)
    n = N_MIN
    ts = D_START + np.arange(n, dtype=np.int64) * MIN
    ret = rng.normal(0, vol, n)
    ret = np.where(rng.random(n) < jump_p, rng.normal(0, 8 * vol, n), ret)
    c = price0 * np.exp(np.cumsum(ret))
    for m, g in crashes:
        c[m:] *= g
    o = np.r_[price0, c[:-1]]
    o = np.where(rng.random(n) < open_gap_p, o * (1 + rng.normal(0, 0.012, n)), o)
    span = np.abs(rng.normal(0, 0.4 * vol, n))
    span = np.where(rng.random(n) < spike_p, span * 12, span)
    h, lo = np.maximum(o, c) * (1 + span), np.minimum(o, c) * (1 - span)
    mo, mc = o * (1 + rng.normal(0, 1e-4, n)), c * (1 + rng.normal(0, 1e-4, n))
    mh = np.maximum.reduce([mo, mc, h * (1 + rng.normal(0, 1e-4, n))])
    ml = np.minimum.reduce([mo, mc, lo * (1 + rng.normal(0, 1e-4, n))])
    fund_full = np.zeros(n)
    fm = (ts // MIN) % 480 == 0
    fund_full[fm] = rng.normal(1e-4, 1.2e-4, int(fm.sum()))
    v = rng.uniform(1, 5, n)
    keep = rng.random(n) > drop
    for m in extra_missing:
        keep[m] = False
    keep[:10] = True
    keep[-10:] = True
    fund = np.zeros(n)                 # a settlement whose minute is missing is paid at the next minute present (data.py)
    kept = np.flatnonzero(keep)
    for j in np.flatnonzero(fund_full != 0.0):
        fund[kept[np.searchsorted(kept, j)]] += fund_full[j]
    return {"ts": ts[keep], "o": o[keep], "h": h[keep], "l": lo[keep], "c": c[keep], "v": v[keep], "mo": mo[keep],
            "mh": mh[keep], "ml": ml[keep], "mc": mc[keep], "fund": fund[keep],
            "rawf": np.c_[ts[fm], fund_full[fm]]}        # the settlements at their own minutes (the league's feed)


def build_coins(seed=7):
    """Six coins; each loses, inside the judged days, the last minute of some hour bins (the minute before a chart close),
    the minute at some closes, a few outages of 2-4 minutes, three crashes of 3-8% at an open, halts (8-22 minutes, one at a funding settlement, that the league's feed carries as flat bars
    without volume and the study's data does not have) and, for each timeframe, the minutes from the last minute of two
    signal bars up to the last minute of the NEXT bar (the entry is then delayed past the first check close: PREREG 5.1
    "if j <= e, then j = e + 1"), besides the random misses, while the others trade."""
    rng = np.random.default_rng(seed)
    coins, base = {}, WARM_DAYS * 1440
    for i, s in enumerate(SYMS):
        extra = [base + int(rng.integers(2, SPAN_DAYS * 24 - 9)) * 60 - 1 for _ in range(14)]
        extra += [base + int(rng.integers(2, SPAN_DAYS * 24 - 9)) * 60 for _ in range(8)]
        for _ in range(4):
            a = base + int(rng.integers(300, SPAN_DAYS * 1440 - 600))
            extra.extend(range(a, a + int(rng.integers(2, 5))))
        for tf, tfm in L.TF_MS.items():
            opens = np.arange(T_START + 3 * HOUR, LAST_SIGNAL_CLOSE - 2 * tfm, tfm)
            lo, sh = flags(s, tf, opens)
            closes = (opens + tfm)[lo | sh]
            for c in rng.choice(closes, size=min(2, len(closes)), replace=False):
                a = (int(c) - MIN - D_START) // MIN
                extra.extend(range(a, a + tfm // MIN))             # [C - 1 min, C + tf - 1 min)
        crashes = [(base + int(rng.integers(600, SPAN_DAYS * 1440 - 600)), 1 + rng.choice([-1, 1]) * rng.uniform(0.03, 0.08))
                   for _ in range(3)]
        halts = []                                              # minutes without trades: the archive has flat bars there, data.py drops them
        for _ in range(3):
            a = base + int(rng.integers(600, SPAN_DAYS * 1440 - 600))
            halts.extend(range(a, a + int(rng.integers(8, 23))))
        for tf, tfm in L.TF_MS.items():                         # a halt around two signal bars' closes of each timeframe
            opens = np.arange(T_START + 3 * HOUR, LAST_SIGNAL_CLOSE - 2 * tfm, tfm)
            lo, sh = flags(s, tf, opens)
            closes = (opens + tfm)[lo | sh]
            for c in rng.choice(closes, size=min(2, len(closes)), replace=False):
                a = (int(c) - D_START) // MIN
                halts.extend(range(a - 2, a + 4))
        if i in (0, 3):                                         # a halt that starts at a funding settlement
            a = base + 480 * int(rng.integers(3, SPAN_DAYS * 3 - 3))
            halts.extend(range(a, a + int(rng.integers(3, 7))))
        coins[s] = synth_coin(seed * 100 + i, P0[s], extra_missing=extra + halts, crashes=crashes)
        coins[s]["halts"] = D_START + np.array(sorted(set(halts)), np.int64) * MIN
    return coins


def to_5m(d):
    """5m klines (the league's source) of the minutes with trades: a bin with no minute is absent, a bin that lies wholly in a halt
    is a flat bar without volume at the last price, as the exchange reports an interval without trades."""
    b = d["ts"] // 300_000
    st = np.r_[0, np.flatnonzero(np.diff(b)) + 1]
    en = np.r_[st[1:], len(b)]
    t5, o5, h5, l5, c5, v5 = (b[st] * 300_000, d["o"][st], np.maximum.reduceat(d["h"], st), np.minimum.reduceat(d["l"], st),
                              d["c"][en - 1], np.add.reduceat(d["v"], st))
    halts = d.get("halts")
    if halts is not None and len(halts):
        cnt = np.bincount((halts // 300_000 - halts[0] // 300_000).astype(np.int64))
        flat = [(halts[0] // 300_000 + k) * 300_000 for k in np.flatnonzero(cnt == 5)]
        flat = [t for t in flat if t not in set(t5.tolist())]
        if flat:
            last = np.array([d["c"][max(int(np.searchsorted(d["ts"], t)) - 1, 0)] for t in flat])
            t5 = np.r_[t5, flat]
            o5, h5, l5, c5 = (np.r_[x, last] for x in (o5, h5, l5, c5))
            v5 = np.r_[v5, np.zeros(len(flat))]
            order = np.argsort(t5, kind="stable")
            t5, o5, h5, l5, c5, v5 = (x[order] for x in (t5, o5, h5, l5, c5, v5))
    return t5, o5, h5, l5, c5, v5


def build_steps(coins):
    """The league's aligned 1m steps of the judged days, as the exchange's feed gives them: [(t, {coin: Bar}, {coin: funding})]
    over the union of the coins' minutes, a halted minute a flat bar without volume, every settlement at its own minute."""
    by, fund = {}, {}
    for s, d in coins.items():
        sel = (d["ts"] >= T_START) & (d["ts"] < T_END)
        ts, o, h, l, c, v, mo, mh, ml, mc = (d[k][sel] for k in ("ts", "o", "h", "l", "c", "v", "mo", "mh", "ml", "mc"))
        for j in range(len(ts)):
            t = int(ts[j])
            by.setdefault(t, {})[s] = Bar(s, t, t + MIN - 1, float(o[j]), float(h[j]), float(l[j]), float(c[j]), mark_open=float(mo[j]),
                                          mark_high=float(mh[j]), mark_low=float(ml[j]), mark_close=float(mc[j]), volume=float(v[j]))
        for t in d["halts"]:
            if T_START <= t < T_END:
                px = float(d["c"][int(np.searchsorted(d["ts"], t)) - 1])
                by.setdefault(int(t), {})[s] = Bar(s, int(t), int(t) + MIN - 1, px, px, px, px, mark_open=px, mark_high=px, mark_low=px,
                                                   mark_close=px, volume=0.0)
        for t, rate in d["rawf"]:
            if T_START <= t < T_END and rate != 0.0:
                fund.setdefault(int(t), {})[s] = float(rate)
    times = sorted(by)
    return times, [(t, by[t], fund.get(t, {})) for t in times]


def make_fetch(times, steps):
    def fetch(_rest, symbols, a, b):
        i, j = bisect.bisect_left(times, a), bisect.bisect_left(times, b)
        return [(t, {s: bar for s, bar in bars.items() if s in symbols}, fund) for t, bars, fund in steps[i:j]]
    return fetch


# ====================================================================================================== synthetic signals
def _mix(x):
    with np.errstate(over="ignore"):                  # splitmix64 wraps modulo 2^64
        x = x + np.uint64(0x9E3779B97F4A7C15)
        z = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return z ^ (z >> np.uint64(31))


def u01(sym: str, tf_ms: int, open_ms, salt: int):
    key = (np.asarray(open_ms, np.int64) // MIN).astype(np.uint64) * np.uint64(64) + np.uint64(SYMS.index(sym) * 8 + salt)
    base = _mix(np.uint64(tf_ms) * np.uint64(1_000_003) + np.uint64(12345))
    return (_mix(key ^ base) >> np.uint64(11)).astype(float) / 9007199254740992.0


P_SIDE = {"15m": 0.03, "30m": 0.04, "1h": 0.06, "4h": 0.12}


def flags(sym: str, tf: str, open_ms):
    """(long, short) per chart bar: a function of (coin, timeframe, bar open) only, so both sides see the same signals
    whatever window they build their bars from. Never both; none before the judged days or in the last 8 hours."""
    open_ms = np.asarray(open_ms, np.int64)
    tfm = L.TF_MS[tf]
    u, p = u01(sym, tfm, open_ms, 0), P_SIDE[tf]
    ok = (open_ms >= T_START) & (open_ms + tfm <= LAST_SIGNAL_CLOSE)
    return (u < p) & ok, (u >= p) & (u < 2 * p) & ok


def best_flags(sym: str, tf: str, open_ms):
    tfm = L.TF_MS[tf]
    return u01(sym, tfm, open_ms, 1) < 0.45, u01(sym, tfm, open_ms, 2) < 0.45


def open_ms_of(df):
    return (df["ts"].astype("int64") // 1_000_000).to_numpy(np.int64)


class Prov:
    """The study's provider: its own chart bars (``run.build_frame`` on the 1m arrays), the synthetic flags, the vendor
    ATR14 and EMA, period ids (the judged days are the select period; the first 300 bars are warm-up)."""

    def __init__(self, data_dir):
        self.data_dir, self._fr = data_dir, {}

    def frame(self, sym, tf):
        if (sym, tf) not in self._fr:
            self._fr[(sym, tf)] = R.build_frame(self.data_dir, sym, tf)
        return self._fr[(sym, tf)]

    def signals(self, pick, sym):
        return flags(sym, pick["tf"], open_ms_of(self.frame(sym, pick["tf"])[0]))

    def best(self, pick, sym):
        return best_flags(sym, pick["tf"], open_ms_of(self.frame(sym, pick["tf"])[0]))

    def atr(self, df):
        return R._vendor_fg().atr(df, 14).to_numpy(float)

    def ema(self, df, n):
        return R._vendor_fg().ema(df["close"], n).to_numpy(float)

    def period_ids(self, close_ms):
        pid = np.full(len(close_ms), -1, np.int8)
        lo, hi = DX.PERIOD_MS["select"]
        pid[(close_ms >= lo) & (close_ms < hi)] = 0
        pid[:DX.WARMUP_BARS] = -1
        return pid


def make_pick(tf, exit_name):
    return {"id": f"core-SYN-{tf}-1", "kind": "core", "pool": "core", "name": "SYN", "tf": tf, "combo": {}, "exit": exit_name,
            "exit_index": [e[0] for e in K.EXITS].index(exit_name), "rank": 1}


class Stub:
    """``League.strategies`` for the synthetic world: the same flags, no strength module."""

    def signals(self, acct, df, sym, frames_btc):
        return flags(sym, acct["tf"], open_ms_of(df))

    def strength(self, name):
        return None


def with_leverage_group(orig):
    """``rulex.chunk_rule`` plus the signal's leverage group ("best" / "normal", the study's ``best`` column) in
    ``meta["lev_group"]``, which the engine's sizing reads first (levrule.signal_group)."""
    def wrapped(lib, source, accts, symbols, start, end, run_start, strategies=None, log=lambda s: None):
        by_close, notes = orig(lib, source, accts, symbols, start, end, run_start, strategies, log)
        for items in by_close.values():
            for _aid, o in items:
                if isinstance(o, Signal):
                    bl, bs = best_flags(o.symbol, o.timeframe, [o.ts + 1 - L.TF_MS[o.timeframe]])
                    o.meta["lev_group"] = "best" if (bl[0] if o.side > 0 else bs[0]) else "normal"
        return by_close, notes
    return wrapped


# ====================================================================================================== combos
ALL_IDS = RX.study_ids()                                                                    # the 82 ids of F1-F10 (F7h included)
SUBSET = ["F1.w2.a", "F1.w3.b", "F1.w5.a.q15", "F1.w2.b.q15", "F2.n10.a", "F2.n20.b", "F3.a", "F3.b", "F4.m1.5.a", "F4.m2.b",
          "F4.m3.a.q15", "F4.m1.5.b.q15", "F5.P1.g50.a", "F5.P1.5.g25.b", "F5.P2.g25.a", "F6.w2.d0", "F6.w3.d0.5", "F7.N12.a",
          "F7.N24.b", "F7h.H4.a", "F7h.H8.b", "F7h.H16.a", "F8.w2.P1.a", "F8.w3.P2.b", "F9.a", "F9.b.q15", "F10.N6.a", "F10.N12.b"]
FLIPS = ["F1.w3.a", "F2.n20.a", "F3.a", "F4.m2.a", "F5.P1.g50.b", "F7.N12.b", "F9.a.q15", "F10.N6.a"]
SIZES = (0.25, 1.0)
# name: (timeframe, the pick's own exit, rule ids, coin-flip rule ids)
COMBOS = {
    "1h": ("1h", "tp1.5R|2", ALL_IDS, FLIPS),
    "15m": ("15m", "tp2R|3", SUBSET, ()),
    "30m": ("30m", "roe50|4", SUBSET, ()),
    "4h": ("4h", "tp2R|1", SUBSET, ()),
    "4h-wide": ("4h", "tp3R|1.5", SUBSET, ()),                  # a wide stop: signals that no size fits are rejected
    "1h-ladder": ("1h", "ladder_tp2R|2", SUBSET, ()),
}
RESTORE_RULES = ["F1.w3.a", "F1.w2.b.q15", "F2.n20.b", "F3.a", "F4.m2.a", "F4.m1.5.b.q15", "F5.P1.g50.a", "F6.w3.d0.5", "F7.N12.a",
                 "F8.w3.P1.b", "F9.a.q15", "F10.N6.b"]
# restarts: some at an hour boundary (a record or a signal is waiting in the engine), some in the middle of an hour
RESTART_AT = [T_START + x for x in (5 * HOUR, 27 * HOUR + 10 * 60_000, 2 * DAY + 19 * HOUR, 3 * DAY + 7 * HOUR + 35 * 60_000,
                                    5 * DAY, 7 * DAY + 13 * HOUR + 55 * 60_000, 9 * DAY + 2 * HOUR)]


def account(rid: str, size: float, tf: str, exit_: str, flip: bool = False) -> dict:
    parsed = dict(RX.NO_RULE) if rid == "E0" else RX.parse_rule(rid)
    aid = f"{rid}@{size:g}" + ("@flip" if flip else "")
    role = RX.ROLE_FLIP if flip else (RX.ROLE_RULE if size < 1 else RX.ROLE_LIVE)
    return {"id": aid, "kind": "core", "name": "SYN", "tf": tf, "combo": {}, "exit": exit_, "role": role, "size": size,
            "rule": parsed, "source": {}}


class Played:
    """What a league run left: trades per account (from the database), open positions, wallets, the restart census."""

    def __init__(self):
        self.trades, self.open, self.wallet, self.restarts, self.open_at_restart, self.queued_at_restart = {}, {}, {}, 0, 0, 0
        self.pending_at_restart = 0


class World:
    def __init__(self, folder, mp):
        self.folder = str(folder)
        self.coins = build_coins()
        write = os.path.join(self.folder, "1m")
        os.makedirs(write, exist_ok=True)
        for sym, d in self.coins.items():
            np.savez(os.path.join(write, f"{sym}.npz"), **{k: v for k, v in d.items() if k not in ("rawf", "halts")})
        self.mk = DX.Market.from_arrays([self.coins[s] for s in SYMS], EX, symbols=SYMS)
        self.prov = Prov(self.folder)
        self.source = PS.FrameSource({s: to_5m(self.coins[s]) for s in SYMS})
        times, steps = build_steps(self.coins)
        self.fetch = make_fetch(times, steps)
        self._pd, self._study, self._league = {}, {}, {}
        mp.setattr(L, "Strategies", Stub)
        mp.setattr(RX, "chunk_rule", with_leverage_group(RX.chunk_rule))
        KX.warm_up(self.mk)

    # ---- the study
    def pdata(self, tf, exit_):
        if tf not in self._pd:
            self._pd[tf] = DX.PickData(self.mk, make_pick(tf, exit_), self.prov)
        pd = copy.copy(self._pd[tf])                  # same chart arrays and offered signals, this combo's exit
        pd.pick = make_pick(tf, exit_)
        return pd

    def offered(self, tf, exit_, flip_id=None):
        pd = self.pdata(tf, exit_)
        off = pd.offered("select", self.mk)
        if flip_id is None:
            return pd, off
        side = np.array([L.flip_side(flip_id, int(c)) for c in off["close"]], np.int64)
        ix = off["tp_idx"]
        off2 = dict(off)
        off2["side"] = side
        off2["best"] = np.where(side > 0, pd.best_l[ix], pd.best_s[ix]).astype(np.bool_)
        return pd, off2

    def study(self, name, rid, size, flip=False):
        key = (name, rid, size, flip)
        if key not in self._study:
            tf, exit_, _ids, _flips = COMBOS[name]
            aid = account(rid, size, tf, exit_, flip)["id"]
            pd, off = self.offered(tf, exit_, aid if flip else None)
            v = KX.E0 if rid == "E0" else KX.variant_by_id(rid)
            res = KX.simulate(self.mk, pd, v, scale=size, period="select", force_end=False, offered=off)
            self._study[key] = (res, off)
        return self._study[key]

    def fill_price(self, c, entry_ts, side):
        ts = self.mk.ts(c)
        j = int(np.searchsorted(ts, entry_ts))
        assert ts[j] == entry_ts
        return float(self.mk.cat["o"][self.mk.starts[c] + j]) * (1 + side * SLIP)

    def study_rows(self, res, off):
        rows = []
        for k in np.flatnonzero(res.status == 1):
            c, side = int(off["coin"][k]), int(off["side"][k])
            rows.append({"sym": SYMS[c], "coin": c, "side": side, "close": int(off["close"][k]), "entry_time": int(res.entry_ts[k]),
                         "exit_time": int(res.exit_ts[k]),
                         "reason": KX.REASON_NAMES[int(res.reason[k])], "lev": int(res.lev[k]), "pnl": float(res.pnl[k]),
                         "xpx": float(res.xpx[k]), "entry_price": self.fill_price(c, int(res.entry_ts[k]), side)})
        return rows

    # ---- the league
    def league_run(self, name, rules=None, sizes=SIZES, flips=None, restarts=(), tag=""):
        key = (name, tag)
        if key in self._league:
            return self._league[key]
        tf, exit_, ids, flip_ids = COMBOS[name]
        rules = list(ids if rules is None else rules) + ["E0"]
        flips = list(flip_ids if flips is None else flips)
        accts = [account(r, s, tf, exit_) for r in rules for s in sizes] + [account(r, 0.25, tf, exit_, True) for r in flips]
        db = os.path.join(self.folder, f"league_{name}{tag}.db")
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(db + ext):
                os.remove(db + ext)
        out = Played()

        def make():
            lg = RN.League(RN.open_db(db), accts, BRACKETS, SPECS, LIB, self.source, self.fetch, SYMS, start_ms=T_START,
                           log=lambda s: None)
            assert lg.restore_notes == [], lg.restore_notes
            return lg
        lg = make()
        for t in restarts:
            lg.advance(t)
            lg.conn.close()
            lg = make()
            out.restarts += 1
            for a in accts:
                e = lg.engines[a["id"]]
                if e.position is not None:
                    out.open_at_restart += 1
                    out.queued_at_restart += bool(e.position.signal.meta.get("rx", {}).get("q"))
                out.pending_at_restart += bool(e.pending)
        lg.advance(T_END)
        for aid, d in lg.conn.execute("SELECT account, data FROM trades ORDER BY account, exit_time, rowid"):
            out.trades.setdefault(aid, []).append(json.loads(d))
        for a in accts:
            e = lg.engines[a["id"]]
            out.wallet[a["id"]] = e.wallet
            out.open[a["id"]] = None if e.position is None else (e.position.symbol, e.position.side, e.position.entry_time,
                                                                 e.position.entry_price)
        lg.conn.close()
        self._league[key] = out
        return out

    def close(self):
        shutil.rmtree(self.folder, ignore_errors=True)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    w = World(tmp_path_factory.mktemp("exfx_parity"), mp)
    yield w
    w.close()
    mp.undo()


# ====================================================================================================== the comparison
def close_to(a, b, rel=PRICE_TOL):
    return abs(a - b) <= rel * max(abs(a), abs(b), 1e-300)


def compare_account(w, res, off, played, aid, label):
    """Every trade of the study's account equals the league account's; returns the number of trades compared."""
    rows = w.study_rows(res, off)
    closed = [r for r in rows if r["reason"] != "OPEN"]
    trades = played.trades.get(aid, [])
    assert len(closed) == len(trades), (label, "trades", len(closed), len(trades),
                                        [(r["sym"], r["entry_time"], r["reason"]) for r in closed][:3],
                                        [(t["symbol"], t["entry_time"], t["exit_reason"]) for t in trades][:3])
    wallet = 5000.0
    for i, (a, b) in enumerate(zip(closed, trades)):
        got = (b["symbol"], b["side"], b["entry_time"], b["exit_time"] // MIN * MIN, b["exit_reason"], b["leverage"])
        want = (a["sym"], a["side"], a["entry_time"], a["exit_time"], a["reason"], a["lev"])
        assert got == want, (label, i, "league", got, "study", want)
        assert close_to(b["entry_price"], a["entry_price"]), (label, i, "entry price", b["entry_price"], a["entry_price"])
        if a["reason"] != "LIQ":
            assert close_to(b["exit_price"], a["xpx"]), (label, i, "exit price", b["exit_price"], a["xpx"])
        change = b["equity_after"] - wallet
        assert abs(change - a["pnl"]) <= WALLET_TOL * wallet, (label, i, "wallet change", change, a["pnl"])
        assert abs(b["pnl"] - a["pnl"]) <= WALLET_TOL * wallet, (label, i, "pnl", b["pnl"], a["pnl"])
        wallet = b["equity_after"]
    assert abs(played.wallet[aid] - float(res.wallet)) <= WALLET_TOL * max(wallet, 1.0), (label, "final wallet", played.wallet[aid], float(res.wallet))
    opened = [r for r in rows if r["reason"] == "OPEN"]
    assert len(opened) <= 1
    have = played.open[aid]
    if opened:
        o = opened[0]
        assert have is not None and have[:3] == (o["sym"], o["side"], o["entry_time"]) and close_to(have[3], o["entry_price"]), \
            (label, "open position", have, o)
    else:
        assert have is None, (label, "open position in the league only", have)
    return len(closed)


# ====================================================================================================== tests
RULE_CASES = [(n, r) for n, (_tf, _e, ids, _f) in COMBOS.items() for r in list(ids) + ["E0"]]


@pytest.mark.parametrize("name,rid", RULE_CASES, ids=[f"{n}-{r}" for n, r in RULE_CASES])
def test_trade_for_trade_at_both_sizes(world, name, rid):
    """The league's rule account (one League.advance over the whole span) equals the study's kernel account: quarter and
    live size, mode a (the pick's own take-profit stays) and mode b (none), the rule's own q15 schedule."""
    played = world.league_run(name)
    for size in SIZES:
        res, off = world.study(name, rid, size)
        compare_account(world, res, off, played, account(rid, size, COMBOS[name][0], COMBOS[name][1])["id"], f"{name} {rid} {size:g}")


FLIP_CASES = [r for r in FLIPS]


@pytest.mark.parametrize("rid", FLIP_CASES)
def test_coin_flip_accounts_equal_the_kernel_with_the_flipped_sides(world, rid):
    """A coin-flip account takes the pick's signal bars with a side seeded by its id and the bar's close (PREREG 11.2)."""
    played = world.league_run("1h")
    tf, exit_ = COMBOS["1h"][:2]
    res, off = world.study("1h", rid, 0.25, flip=True)
    assert set(np.unique(off["side"])) == {-1, 1}
    compare_account(world, res, off, played, account(rid, 0.25, tf, exit_, True)["id"], f"flip {rid}")


def restarts_at_a_missing_minute(world, n=3):
    """Hour closes at which a signal of the 1h pick waits for a minute that its coin is missing (the minute before the close, or
    the close minute): a restart exactly there keeps a waiting signal across the stop, and it must still fill where the study's
    kernel puts it, so the league's last minute present per coin must survive the restart too."""
    pd, off = world.offered("1h", COMBOS["1h"][1])
    out = []
    for k in range(len(off["coin"])):
        ts = world.mk.ts(int(off["coin"][k]))
        close = int(off["close"][k])
        has_c = bool(ts[min(np.searchsorted(ts, close), len(ts) - 1)] == close)
        has_p = bool(ts[min(np.searchsorted(ts, close - MIN), len(ts) - 1)] == close - MIN)
        if (not has_c or not has_p) and T_START + 6 * HOUR < close < T_END - 12 * HOUR and all(abs(close - x) > 5 * HOUR for x in out):
            out.append(close)
    return sorted(out)[:n]


def test_the_run_stops_and_restores_in_the_middle_of_open_positions_and_gives_the_same_trades(world):
    """The league stopped and reopened from its database ten times (the rule state of each open position is checked against
    its recomputation from the bars by audit_restored, which must find nothing to correct; three restarts sit at a minute that
    a coin with a waiting signal is missing) equals the study's accounts."""
    at_gap = restarts_at_a_missing_minute(world)
    assert len(at_gap) == 3, at_gap
    restarts = sorted(set(RESTART_AT) | set(at_gap))
    played = world.league_run("1h", rules=RESTORE_RULES, sizes=(0.25,), flips=("F7.N12.b", "F9.a.q15"), restarts=restarts, tag="-restore")
    assert played.restarts == len(restarts) == 10
    assert played.open_at_restart >= 40 and played.queued_at_restart >= 15 and played.pending_at_restart >= 10, \
        (played.open_at_restart, played.queued_at_restart, played.pending_at_restart)
    tf, exit_ = COMBOS["1h"][:2]
    n = 0
    for rid in RESTORE_RULES + ["E0"]:
        res, off = world.study("1h", rid, 0.25)
        n += compare_account(world, res, off, played, account(rid, 0.25, tf, exit_)["id"], f"restore {rid}")
    for rid in ("F7.N12.b", "F9.a.q15"):
        res, off = world.study("1h", rid, 0.25, flip=True)
        n += compare_account(world, res, off, played, account(rid, 0.25, tf, exit_, True)["id"], f"restore flip {rid}")
    assert n >= 100, n


def test_the_world_exercises_what_the_comparison_is_for(world):
    """Harness sanity (a pass here says the parity runs above were not vacuous): trades of every family close by a RULE exit,
    the take-profit, stop and rule reasons occur, longs and shorts, several leverages, signals that no size fits are rejected;
    fills and checks are moved by a minute that is missing for one coin only, in each of the two ways (the close minute
    itself, the minute before it), entries are delayed past the first check close of their position, and positions are held
    across a funding settlement that falls on a halted minute of their coin."""
    fam_rule = {}
    reasons, sides, levs = set(), set(), set()
    shifted_fill = shifted_check = delayed = rejected = carried = 0
    # settlements that fall on a minute the coin has no trades in: data.py pays them at the coin's next minute present
    due = {}
    for sym, d in world.coins.items():
        halted = set(d["halts"].tolist())
        for t, rate in d["rawf"]:
            if int(t) in halted and rate != 0.0 and T_START <= t < T_END:
                due.setdefault(sym, []).append(int(d["ts"][int(np.searchsorted(d["ts"], t))]))
    assert sum(len(v) for v in due.values()) >= 2, due
    for name, (tf, exit_, ids, _f) in COMBOS.items():
        tfm = L.TF_MS[tf]
        for rid in ids:
            res, off = world.study(name, rid, 0.25)
            rejected += int((res.status == 2).sum())
            for r in world.study_rows(res, off):
                carried += any(r["entry_time"] < t <= r["exit_time"] for t in due.get(r["sym"], ()))
                reasons.add(r["reason"])
                sides.add(r["side"])
                levs.add(r["lev"])
                if r["reason"] == "RULE":
                    fam_rule[rid.split(".")[0]] = fam_rule.get(rid.split(".")[0], 0) + 1
                    shifted_check += r["exit_time"] % tfm != 0 and tf in ("1h", "4h") and not rid.endswith("q15")
                shifted_fill += r["entry_time"] % tfm != 0
                delayed += r["entry_time"] - r["close"] >= tfm
    assert set(fam_rule) == {f"F{i}" for i in range(1, 11)} | {"F7h"}, fam_rule
    assert {"RULE", "SL", "TP"} <= reasons and sides == {-1, 1} and len(levs) >= 3 and rejected >= 5, (reasons, sides, levs, rejected)
    assert shifted_fill >= 3 and shifted_check >= 3 and delayed >= 3 and carried >= 3, (shifted_fill, shifted_check, delayed, carried)
    # missing minutes of one coin while the others trade, in both ways
    a_only = b_only = 0
    pd, off = world.offered("1h", "tp1.5R|2")
    for k in range(len(off["coin"])):
        ts = world.mk.ts(int(off["coin"][k]))
        close = int(off["close"][k])
        has_c = bool(ts[min(np.searchsorted(ts, close), len(ts) - 1)] == close)
        has_p = bool(ts[min(np.searchsorted(ts, close - MIN), len(ts) - 1)] == close - MIN)
        a_only += has_p and not has_c
        b_only += has_c and not has_p
    assert a_only >= 1 and b_only >= 1, (a_only, b_only)


CONTROL_RULES = ["F1.w2.a", "F2.n10.a", "F3.a", "F4.m1.5.a", "F5.P1.g50.a", "F7.N12.a", "F9.a", "F10.N6.a"]


def accounts_that_differ(world, name, played, rules, size=0.25):
    tf, exit_ = COMBOS[name][:2]
    bad = []
    for rid in list(rules) + ["E0"]:
        res, off = world.study(name, rid, size)
        try:
            compare_account(world, res, off, played, account(rid, size, tf, exit_)["id"], rid)
        except AssertionError:
            bad.append(rid)
    return bad


def test_negative_control_the_comparison_catches_a_league_that_reads_the_union_of_the_coins_minutes(world):
    """paramshadow.replay_day (the union of the coins' minutes: a signal whose coin has no bar at its minute is rejected, one whose
    close minute is the coin's first goes a minute early, a check likewise) is the league as it was: the same data must now
    show a difference, or the parity test above could not tell the two replays apart."""
    def union_of_minutes(engines, active, by_close, steps, brackets, seen, fund_wait=None, stats=None, last_close=None):
        PS.replay_day(engines, active, by_close, steps, brackets)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(RX, "replay_day", union_of_minutes)
        played = world.league_run("1h", rules=CONTROL_RULES, sizes=(0.25,), flips=(), tag="-ctl-union")
    bad = accounts_that_differ(world, "1h", played, CONTROL_RULES)
    assert len(bad) >= 3, bad


def test_negative_control_the_comparison_catches_checks_dropped_while_a_signal_waits_for_its_minute(world):
    """A chart record that reaches the engine while the coin has a signal waiting (the coin's minutes were missing for a bar) used
    to be dropped; the first check was then a bar late. With that old ``submit`` the same data must show a difference."""
    def submit_dropping_early_records(self, signal):
        if isinstance(signal, RX.RuleClose):
            p = self.position
            if p is not None and self.rx_rule is not None and signal.d["sym"] == p.symbol:
                rx = p.signal.meta.get("rx")
                if rx is not None and signal.d["t"] > rx["c0"]:
                    rx["q"].append(dict(signal.d))
            return
        PaperEngine.submit(self, signal)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(RX.RuleMixin, "submit", submit_dropping_early_records)
        played = world.league_run("1h", rules=CONTROL_RULES, sizes=(0.25,), flips=(), tag="-ctl-early")
    bad = accounts_that_differ(world, "1h", played, CONTROL_RULES)
    assert len(bad) >= 1, bad


def test_negative_control_the_comparison_catches_halted_minutes_kept_as_minutes(world):
    """The exchange's flat bars without volume (a halt) are no minutes for the study (data.py drops them). A league that stepped on
    them, still on each coin's own minutes, must show a difference on the same data."""
    real = RX.replay_day

    def halted_minutes_kept(engines, active, by_close, steps, brackets, seen, fund_wait=None, stats=None, last_close=None):
        steps = [(t, {s: replace(b, volume=None) for s, b in bars.items()}, fund) for t, bars, fund in steps]
        real(engines, active, by_close, steps, brackets, seen, fund_wait, stats, last_close)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(RX, "replay_day", halted_minutes_kept)
        played = world.league_run("1h", rules=CONTROL_RULES, sizes=(0.25,), flips=(), tag="-ctl-flat")
    bad = accounts_that_differ(world, "1h", played, CONTROL_RULES)
    assert len(bad) >= 1, bad


def test_negative_control_the_restart_test_catches_a_league_that_forgets_each_coins_last_minute(world):
    """The league keeps {coin: last minute present} in its database. Reopened without it, a signal that waits across a restart for a
    coin that was missing a minute fills a minute early: the restarts at a missing minute must then show a difference."""
    restarts = sorted(set(RESTART_AT) | set(restarts_at_a_missing_minute(world)))
    got = RN._get
    with pytest.MonkeyPatch.context() as m:
        m.setattr(RN, "_get", lambda conn, k: None if k == "seen" else got(conn, k))
        played = world.league_run("1h", rules=RESTORE_RULES, sizes=(0.25,), flips=(), restarts=restarts, tag="-ctl-seen")
    bad = accounts_that_differ(world, "1h", played, RESTORE_RULES)
    assert len(bad) >= 1, bad


def test_the_rule_league_places_a_plain_account_next_to_it_where_the_study_does(world):
    """The twins (the pick's own exit) are the plain engines of candleague.exits and sit in the same League as the rule
    accounts: their trades are the study's E0, with and without a minute missing for one coin."""
    played = world.league_run("1h")
    tf, exit_ = COMBOS["1h"][:2]
    n = 0
    for size in SIZES:
        res, off = world.study("1h", "E0", size)
        n += compare_account(world, res, off, played, account("E0", size, tf, exit_)["id"], f"E0 {size:g}")
    assert n >= 10
