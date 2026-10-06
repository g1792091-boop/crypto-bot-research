"""5년 조합 시험: the 5-year backtest of COMBINATIONS of the 36 locked strategies, generated offline and committed as
one JSON for the dashboard (paperbot/dash/more/combo5y.py serves it; screens/combo-5y.js draws it). Read-only research:
nothing here trades, touches a database or edits a research / trading file (they are imported, never changed).

    python -m paperbot.dash.tools.combo5y --signals <signal cache dir> --out paperbot/dash/data/combo5y.json \
        [--work <checkpoint dir>] [--procs 2]

``--signals``: the lab's 5-year cache (sig_<tf>_<COIN>.npz: ts, o, h, l, c, v, atr, s__<strategy>; built and checked by
paperbot/agents/labdata.py). ``--work``: checkpoints (every finished job is a file; a killed run resumes from them; a
run with other settings uses another sub folder). At most 2 worker processes.

What (every choice is fixed here, before looking at any combination result):

0. PARITY. The research's per-strategy accounts (research/paper_rules/out_binance/accounts.csv, k = 2 ATR, windows is
   2021-08-01..2024-07-01 and cf 2024-07-01..2026-09-30, $1,000, the tier-walk sizing; the same numbers are
   research/strategy_profiles/out_binance/cards.json account_is / account_cf) are recomputed with this pipeline's own
   calls (rules_bt.simulate on the same cache) and compared cell by cell. The v4 numbers below then differ ONLY by
   the run's rules: $5,000, the quality_v1 leverage rule, Korea-time monthly accounts.
1. ACCOUNTS (a). Every strategy x timeframe (15m / 30m / 1h / 4h: config.V3_TRADE_TFS; 5m was removed for the 36) is
   one paper account under the paper v4 rules: rules_bt.simulate (next-bar entry + slippage, 2 x ATR14 stop, the
   stepped profit lock, one position at a time over the six coins in coin priority, fees, funding, liquidation, bust
   under $10) with $5,000 and the quality_v1 leverage rule, applied the way research/power/power.py's
   ``leverage_rule`` shim applies it (rules_bt's size_position swapped, only while the block runs, for the run's
   quality_v1 tiers), except that a strategy signal's group is its REAL entry-quality group: its strength features
   (research/entry_study/strength_defs, hash-checked, through paperbot/entry_marks.strength_module) scored against
   paperbot/quality_edges.json as paperbot/levrule.quality_group does live (mean quintile >= 4 -> "best": 50x / 50%,
   then 40x / 40%; else "normal": 30x / 30%, then 20x / 20%). Coin flips draw "best" with config.V3_P_BEST
   (levrule.coin_flip_best, the live draw). Each KST calendar month 2021-08 .. 2026-09 is a FRESH $5,000 account
   (the 30-day paper run's own shape: a bust ends that month only; a position open at the month's end is closed at
   its last bar). Per month: the return; per account: best / worst / median month, the share of months above 0, the
   month distribution; plus the same strategy run as ONE account for the whole 5 years (compounding, bust stops it).
2. PORTFOLIOS (b). Unit = one strategy = its four timeframe accounts summed ($20,000). Daily (KST) P&L of the monthly
   accounts. agents/synergy.py's own functions: score = total P&L / max drawdown ($) of the summed curve, every pair
   and triple, a beam of 200 for 4 and 5; the multiple-testing guard: the same search on day-shuffled P&L
   (``SHUFFLES`` runs, each unit's days permuted on their own) and on ``FLIP_GROUPS`` groups of 36 coin-flip units
   (RANDOM_k on the same four timeframes at the median strategy signal rate, the same rules). Walk-forward by KST
   calendar year: the best combination of year N (searched on year N only) scored on year N+1 alone, against the
   median and 75th percentile of EVERY 2-5 combination's year N+1 score. The 36 x 36 daily P&L correlation, its
   clusters (>= 0.7, agents/meetings.corr_clusters), the correlation on either one's worst 5% days, the co-loss
   ratio (days both lost / days either lost). The top 10 with their monthly curve, drawdown, return, winning-month
   share and diversification ratio (members' own max drawdowns added up / the combination's). The search runs twice:
   over all 36 (as specified) and, added AFTER seeing the first run, over the strategies with at least
   ``MIN_UNIT_TRADES`` closed trades in the 62 monthly accounts (every strategy loses under these rules, so a strategy
   that hardly trades wins the score by doing nothing; the JSON and the page say so).
3. MERGED SIGNAL RULES (c). On the cached signal arrays, no look-ahead (a signal on bar t is known at its close, the
   entry is bar t + 1): AND (A and B, same coin and side, within k bars: k = 0, 1, 3), FILTER (A only when B's latest
   signal within N bars, B's own bar t included, is on the same side: N = 4, 16), VOTE (at least K of the 36 on the
   same side on the bar: K = 2, 3, 4, 5, 6, 8), MTF (the same strategy: a lower-timeframe signal only when the latest
   signal on a CLOSED higher-timeframe bar is on the same side; 'state' = any age, 'recent' = within the last 3
   closed higher bars). Every signal is one trade on its own (labtests.signal_outcomes: the house exits, no account,
   no position limit) at the "normal" leverage (a new rule has no strength definition, so it would trade "normal"
   live, like DeepSeek), measured as P&L on equity per trade (net ROE x margin share). Per trial: one-sided p of
   mean > 0 with week-clustered errors; Benjamini-Hochberg at 5% over EVERY trial; survivors must also beat a
   shuffle null (the partner's signals circularly shifted in time, ``NULL_RUNS`` runs, rank p <= 0.05); the top 15
   by t with their means in 2021-22 / 2023-24 / 2025-26.
4. ONE SHARED ACCOUNT (d). The top 5 portfolios (of each search) as one account fed by all members' signals on all four timeframes:
   capital = the separate accounts' total, one position per coin (a signal on a coin already held is skipped: same
   side, or an opposite-signal conflict, counted), each position sized like one paper account (equity / number of
   member accounts), monthly like (1); against the separate accounts.
5. METHODS: periods, sizing, costs, trial counts, and the caveat: the 36 were themselves chosen on 5-year data, so
   these numbers flatter them (설명용, 판정 아님, 사전 등록 연구 아님).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import sys
import time
import zlib
from dataclasses import replace
from multiprocessing import get_context
from typing import Callable, Optional

import numpy as np

from . import combo5y_core as K

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RULES_DIR = os.path.join(ROOT, "research", "paper_rules")
ACCOUNTS_CSV = os.path.join(RULES_DIR, "out_binance", "accounts.csv")
SUMMARY_JSON = os.path.join(RULES_DIR, "out_binance", "summary.json")
CARDS_JSON = os.path.join(ROOT, "research", "strategy_profiles", "out_binance", "cards.json")
OUT_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "combo5y.json")

VERSION = 1
LABEL = "설명용, 판정 아님"
FIRST, LAST = "2021-08", "2026-09"               # KST months (the research's 5-year span, periods 1 + 2)
TFS = ("15m", "30m", "1h", "4h")                  # config.V3_TRADE_TFS (checked at run time)
K_STOP = 2.0                                      # config.V3_STOP_ATR (checked at run time)
INITIAL = 5000.0                                  # config.V3_INITIAL (checked at run time)
FLIP_GROUPS = 4                                   # groups of 36 coin-flip units (seeds 1..144)
UNITS_PER_GROUP = 36
SHUFFLES = 100                                    # day-shuffled searches
NULL_RUNS = 39                                    # circular shifts per merged-rule null (rank p floor 0.025)
MIN_TRADES = 100                                  # a merged rule with fewer trades is counted but not tested
FDR = 0.05
AND_K = (0, 1, 3)
FILTER_N = (4, 16)
VOTE_K = (2, 3, 4, 5, 6, 8)
MTF_PAIRS = (("15m", "30m"), ("15m", "1h"), ("15m", "4h"), ("30m", "1h"), ("30m", "4h"), ("1h", "4h"))
MTF_AGE = {"state": None, "recent": 2}
WIN3 = (("2021-22", "2021-08", "2023-01"), ("2023-24", "2023-01", "2025-01"), ("2025-26", "2025-01", "2026-10"))
TOP_PORT, TOP_SHARED, TOP_MERGED = 10, 5, 15
MIN_UNIT_TRADES = 62                              # the 'active' search: at least one closed trade a month on average
SEED = 20261006
ELAPSED_DAYS = 31
MAX_PROCS = 2


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- engines (imported read-only)
def _rb():
    if RULES_DIR not in sys.path:
        sys.path.insert(0, RULES_DIR)
    import rules_bt as RB  # noqa: PLC0415  (research/paper_rules/rules_bt.py, unchanged)
    return RB


def _lib():
    from paperbot import sweepsig
    return sweepsig.lib()


def v4_size_settings(RB):
    """rules_bt's settings with the run's quality_v1 tiers (research/power/power.py ``leverage_rule``)."""
    from paperbot.config import V3_BEST_FALLS_TO_NORMAL, V3_QUALITY_TIERS
    return replace(RB.SETTINGS, leverage_rule="quality_v1", tiers=V3_QUALITY_TIERS, max_margin_frac=0.50,
                   best_falls_to_normal=V3_BEST_FALLS_TO_NORMAL)


@contextlib.contextmanager
def v4_rules(RB, group_of: Callable[[int, float, float], str], initial: float = INITIAL):
    """rules_bt.simulate under the run's rules while the block runs (rules_bt.py itself is unchanged): its
    size_position takes the quality_v1 chain of the signal's own group (``group_of(side, fill, atr)``), and its
    accounts start with ``initial``."""
    s = v4_size_settings(RB)
    real, old = RB.size_position, RB.INITIAL

    def sized(_settings, equity, side, entry, stop, _requested, brackets, **kw):
        return real(s, equity, side, entry, stop, group_of(int(side), float(entry), float(kw.get("atr"))),
                    brackets, **kw)

    RB.size_position, RB.INITIAL = sized, float(initial)
    try:
        yield
    finally:
        RB.size_position, RB.INITIAL = real, old


class GroupBook:
    """The leverage group of each signal, keyed the way rules_bt.simulate calls size_position: (side, fill, atr) with
    fill = next open x (1 + side x slippage) computed with the same numpy operations, so the keys are bit-equal.
    ``flip``: (seed, tf) of a coin-flip account: its group is drawn on use with levrule.coin_flip_best."""

    def __init__(self, slip: float, flip: Optional[tuple] = None):
        self.slip, self.flip = slip, flip
        self.d: dict = {}
        self.miss = self.collide = 0

    def add(self, b: dict, coin: str, idx: np.ndarray, side: np.ndarray, best: Optional[np.ndarray]) -> None:
        idx = np.asarray(idx, np.int64)
        keep = idx + 1 < len(b["o"])
        idx, side = idx[keep], np.asarray(side, np.int64)[keep]
        fill = b["o"][idx + 1] * (1 + side * self.slip)
        atr = b["atr"][idx]
        if best is None:                                      # coin flip: draw later, on use
            close = (b["ts"][idx] // 1_000_000 + K.TF_MS[self.flip[1]]).tolist()
            vals = [(coin, c) for c in close]
        else:
            vals = ["best" if x else "normal" for x in np.asarray(best, bool)[keep].tolist()]
        for key, v in zip(zip(side.tolist(), fill.tolist(), atr.tolist()), vals):
            if key in self.d and self.d[key] != v:
                self.collide += 1
                v = "normal"
            self.d[key] = v

    def __call__(self, side: int, fill: float, atr: float) -> str:
        v = self.d.get((side, fill, atr))
        if v is None:
            self.miss += 1
            return "normal"
        if isinstance(v, tuple):
            from paperbot.levrule import coin_flip_best
            v = "best" if coin_flip_best(self.flip[0], self.flip[1], v[0] + "T", int(v[1])) else "normal"
            self.d[(side, fill, atr)] = v
        return v


def normal_sizer(RB, k_stop: float = K_STOP, equity: float = INITIAL):
    """research/strategy_profiles/profiles.py ``_sizer`` with the run's quality_v1 tiers, group "normal" (30x / 30%,
    then 20x / 20%): (side, ATR / price) -> (leverage, liquidation distance)."""
    from paperbot.sizing import size_position
    s = v4_size_settings(RB)
    cache: dict = {}

    def lev_liq(side: int, atr_frac: float):
        key = (side, float(f"{atr_frac:.4g}"))
        if key not in cache:
            raw = 100.0
            a = key[1] * raw
            fill = raw * (1 + side * RB.SETTINGS.slippage_frac)
            d = size_position(s, equity, side, fill, raw - side * k_stop * a, "normal", RB.BRACKETS, atr=a,
                              min_notional=RB.MIN_NOTIONAL)
            cache[key] = (d.leverage, side * (fill - d.liq_price) / fill) if d.ok else (0, np.nan)
        return cache[key]
    return lev_liq


# ---------------------------------------------------------------- the cache (one copy per worker process)
_DATA: dict = {}


def load_tf(sig_dir: str, tf: str) -> dict:
    """{coin: {ts (ns), ms, o, h, l, c, v, atr, s__*}} of one timeframe (kept for the worker's later jobs)."""
    key = (os.path.abspath(sig_dir), tf)
    if key not in _DATA:
        RB = _rb()
        out = {}
        for c in RB.COINS:
            with np.load(os.path.join(sig_dir, f"sig_{tf}_{c}.npz")) as z:
                d = {k: z[k] for k in z.files}
            d["ms"] = d["ts"] // 1_000_000
            out[c] = d
        _DATA[key] = out
    return _DATA[key]


def strategy_names() -> list[str]:
    from paperbot.sigservice import strategy_names as sn
    return sn(_lib())


def month_list() -> list[dict]:
    return K.months(FIRST, LAST)


def _span_ns() -> tuple[int, int]:
    mons = month_list()
    return mons[0]["start"] * 1_000_000, mons[-1]["end"] * 1_000_000


def flip_rate(D: dict, names: list, tf: str, warmup: int) -> float:
    """Median over the 36 of signals per coin-bar on the 5-year span (rules_bt._tf_job's rule, on the whole span)."""
    s0, s1 = _span_ns()
    rates = []
    for nm in names:
        tot = bars_n = 0
        for c, d in D.items():
            lo, n_end = K.bounds_in(d["ts"], s0, s1, warmup)
            tot += int(np.count_nonzero(d["s__" + nm][lo:max(lo, n_end - 1)]))
            bars_n += max(0, n_end - 1 - lo)
        rates.append(tot / max(bars_n, 1))
    return float(np.median(rates))


# ---------------------------------------------------------------- stage 1: entry-quality groups
def group_job(args) -> str:
    tf, name, sig_dir, work = args
    path = os.path.join(work, "groups", f"{tf}_{name}.npz")
    if os.path.exists(path):
        return path
    import pandas as pd
    from paperbot import entry_marks as EM
    from paperbot.levrule import edges
    D = load_tf(sig_dir, tf)
    cell = edges().get(f"{name}|{tf}")
    S = EM.strength_module(name)
    out = {}
    for coin, d in D.items():
        sig = d["s__" + name]
        idx = np.flatnonzero(sig)
        best = np.zeros(len(idx), bool)
        if len(idx) and S is not None and cell:
            df = pd.DataFrame({"ts": pd.to_datetime(d["ts"], utc=True), "open": d["o"], "high": d["h"], "low": d["l"],
                               "close": d["c"], "volume": d["v"]})
            with EM._contained():
                st = S.strength(df, tf)
            side = sig[idx]
            vals = {f["name"]: np.where(side > 0, np.asarray(st[f["name"]][0], float)[idx],
                                        np.asarray(st[f["name"]][1], float)[idx]) for f in S.FEATURES}
            best = K.quality_best(vals, cell)
        out[f"{coin}_idx"] = idx.astype(np.int64)
        out[f"{coin}_best"] = best
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **out)
    os.replace(tmp, path)
    return path


def load_groups(work: str, tf: str, name: str) -> dict:
    with np.load(os.path.join(work, "groups", f"{tf}_{name}.npz")) as z:
        return {k: z[k] for k in z.files}


# ---------------------------------------------------------------- stage 2: accounts
def _book_for(RB, D: dict, unit: str, tf: str, work: str, sg: dict) -> GroupBook:
    slip = RB.SETTINGS.slippage_frac
    if unit.startswith("RANDOM_"):
        book = GroupBook(slip, flip=(int(unit.split("_")[1]), tf))
        for c in RB.COINS:
            idx = np.flatnonzero(sg[c])
            book.add(D[c], c, idx, sg[c][idx], None)
        return book
    book = GroupBook(slip)
    g = load_groups(work, tf, unit)
    for c in RB.COINS:
        idx = g[f"{c}_idx"]
        book.add(D[c], c, idx, sg[c][idx], g[f"{c}_best"])
    return book


def _signals(RB, L, D: dict, unit: str, tf: str, rate: float) -> dict:
    if unit.startswith("RANDOM_"):
        bars = {c: {k: D[c][k] for k in ("ts", "o", "h", "l", "c", "atr")} for c in RB.COINS}
        return RB.random_signals(bars, None, rate, int(unit.split("_")[1]), tf, L)
    return {c: D[c]["s__" + unit] for c in RB.COINS}


def account_job(args) -> str:
    """One strategy (or coin flip) on one timeframe: the 62 monthly v4 accounts, the 5-year single account, and (for
    the parity check) the research windows under the research's own rules and under the v4 rules."""
    tf, unit, sig_dir, work, rate, ref_rate = args
    path = os.path.join(work, "acct", f"{tf}_{unit}.npz")
    if os.path.exists(path):
        return path
    RB, L = _rb(), _lib()
    D = load_tf(sig_dir, tf)
    bars = {c: {k: D[c][k] for k in ("ts", "o", "h", "l", "c", "atr")} for c in RB.COINS}
    sg = _signals(RB, L, D, unit, tf, rate)
    book = _book_for(RB, D, unit, tf, work, sg)
    warm = L.warmup_bars(tf)
    mons = month_list()
    d0 = int(K.kst_day(mons[0]["start"]))
    nd = int(K.kst_day(mons[-1]["end"])) - d0
    daily = np.zeros(nd)
    mrow = {k: np.zeros(len(mons)) for k in ("pnl", "trades", "wins", "liq", "bust", "mdd")}

    def run(bounds: dict, keep: bool = True) -> dict:
        with v4_rules(RB, book):
            return RB.simulate(bars, sg, bounds, K_STOP, tf, L, keep_trades=keep)

    def book_daily(r: dict, into: np.ndarray) -> float:
        tt = r["trade_table"]
        if not len(tt):
            return 0.0
        pnl = K.trade_pnl(tt["R"].to_numpy(float), tt["margin_frac"].to_numpy(float), INITIAL)
        coins = tt["coin"].to_numpy(int)
        ex = tt["exit_j"].to_numpy(int)
        ms = np.array([D[RB.COINS[c]]["ms"][j] for c, j in zip(coins, ex)], dtype=np.int64)
        K.daily_add(into, K.kst_day(ms) - d0, pnl)
        return float(pnl.sum())

    for j, m in enumerate(mons):
        bounds = {c: K.bounds_in(D[c]["ts"], m["start"] * 1_000_000, m["end"] * 1_000_000, warm) for c in RB.COINS}
        r = run(bounds)
        tot = book_daily(r, daily)
        if abs(tot - (r["final"] - INITIAL)) > 1e-6 * max(1.0, INITIAL):
            raise AssertionError(f"{tf} {unit} {m['label']}: trade P&L {tot} != final {r['final'] - INITIAL}")
        tt = r["trade_table"]
        mrow["pnl"][j] = r["final"] - INITIAL
        mrow["trades"][j] = r["trades"]
        mrow["wins"][j] = int((tt["R"] > 0).sum()) if len(tt) else 0
        mrow["liq"][j] = r["liquidations"]
        mrow["bust"][j] = float(bool(r["bust"]))
        mrow["mdd"][j] = r["max_dd"]
    s0, s1 = _span_ns()
    whole = {c: K.bounds_in(D[c]["ts"], s0, s1, warm) for c in RB.COINS}
    one_daily = np.zeros(nd)
    r1 = run(whole)
    book_daily(r1, one_daily)
    tt1 = r1["trade_table"]
    one = np.array([r1["final"], r1["max_dd"], float(bool(r1["bust"])), float(r1["bust_ts"] or 0) / 1e6, r1["trades"],
                    float((tt1["R"] > 0).sum()) if len(tt1) else 0.0, r1["liquidations"]])
    # parity: the research windows, (a) exactly as the research ran them, (b) under the v4 rules
    par = np.full((2, 2, 2), np.nan)                       # [research | v4][is | cf][final, trades]
    if unit in strategy_names() or unit in ("RANDOM_1", "RANDOM_2", "RANDOM_3"):
        sg_ref = sg if not unit.startswith("RANDOM_") else _signals(RB, L, D, unit, tf, ref_rate)
        for wi, w in enumerate(("is", "cf")):
            bw = {c: RB.window_bounds(L, bars[c], tf, w) for c in RB.COINS}
            r = RB.simulate(bars, sg_ref, bw, K_STOP, tf, L)
            par[0, wi] = (r["final"], r["trades"])
            if not unit.startswith("RANDOM_"):
                r = run(bw, keep=False)
                par[1, wi] = (r["final"], r["trades"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, daily=daily, one_daily=one_daily, one=one, par=par,
                        miss=np.array([book.miss, book.collide, len(book.d)]),
                        **{f"m_{k}": v for k, v in mrow.items()})
    os.replace(tmp, path)
    return path


def load_acct(work: str, tf: str, unit: str) -> dict:
    with np.load(os.path.join(work, "acct", f"{tf}_{unit}.npz")) as z:
        return {k: z[k] for k in z.files}


# ---------------------------------------------------------------- stage 3: per-signal outcomes on every bar
def outcome_job(args) -> str:
    """Every bar of one coin and timeframe, long and short, as one trade alone (labtests.signal_outcomes, the house
    exits) at the "normal" leverage: P&L on equity (net ROE x margin share) or NaN when not sized / not closed."""
    tf, coin, sig_dir, work = args
    path = os.path.join(work, "out", f"{tf}_{coin}.npz")
    if os.path.exists(path):
        return path
    from paperbot.agents import labtests as LT
    RB, L = _rb(), _lib()
    d = load_tf(sig_dir, tf)[coin]
    b = {k: d[k] for k in ("ts", "o", "h", "l", "c", "atr")}
    s0, s1 = _span_ns()
    lo, n_end = K.bounds_in(d["ts"], s0, s1, L.warmup_bars(tf))
    n = len(d["ts"])
    sizer = normal_sizer(RB)
    out = {"lo": np.array([lo]), "n_end": np.array([n_end])}
    for side, key in ((1, "eq_long"), (-1, "eq_short")):
        sg = np.zeros(n, np.int8)
        sg[lo:max(lo, n_end - 1)] = side
        r = LT.signal_outcomes(b, sg, lo, n_end, tf, k_stop=K_STOP, sizer=sizer)
        eq = np.full(n, np.nan, np.float32)
        ok = r["done"]
        eq[r["idx"][ok]] = (r["roe"][ok] * r["lev"][ok] / 100.0).astype(np.float32)
        out[key] = eq
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **out)
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- stage 4: merged rules
class TfSet:
    """One timeframe's signals (per coin, per strategy: long / short / any indexes) and outcomes."""

    def __init__(self, sig_dir: str, work: str, tf: str, names: list):
        RB = _rb()
        self.tf, self.names, self.coins = tf, names, RB.COINS
        D = load_tf(sig_dir, tf)
        self.ts = {c: D[c]["ms"] for c in self.coins}
        self.n = {c: len(D[c]["ms"]) for c in self.coins}
        self.sig = {c: {nm: D[c]["s__" + nm] for nm in names} for c in self.coins}
        self.idx = {c: {nm: (K.sig_idx(self.sig[c][nm], 1), K.sig_idx(self.sig[c][nm], -1)) for nm in names}
                    for c in self.coins}
        self.any = {c: {nm: K.nonzero_with_side(self.sig[c][nm]) for nm in names} for c in self.coins}
        mons = month_list()
        w_edges = [K.kst_month_start(int(a[:4]), int(a[5:])) for _l, a, _b in WIN3] + \
                  [K.kst_month_start(int(WIN3[-1][2][:4]), int(WIN3[-1][2][5:]))]
        self.eq, self.lo, self.hi, self.week, self.win = {}, {}, {}, {}, {}
        for c in self.coins:
            with np.load(os.path.join(work, "out", f"{tf}_{c}.npz")) as z:
                self.eq[c] = (z["eq_long"], z["eq_short"])
                self.lo[c], self.hi[c] = int(z["lo"][0]), int(z["n_end"][0]) - 1
            ms = self.ts[c]
            self.week[c] = ((K.kst_day(ms) + 3) // 7).astype(np.int64)      # Monday weeks (KST)
            self.win[c] = np.searchsorted(np.asarray(w_edges[1:-1], np.int64), ms, side="right").astype(np.int8)
        self.months = mons

    def gather(self, entries: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """entries {coin: (long idx, short idx)} -> (P&L on equity per trade, week, window) inside the span."""
        vs, ws, ns = [], [], []
        for c, (il, is_) in entries.items():
            lo, hi = self.lo[c], self.hi[c]
            for side, ix in ((0, il), (1, is_)):
                ix = ix[(ix >= lo) & (ix < hi)]
                v = self.eq[c][side][ix]
                ok = np.isfinite(v)
                vs.append(v[ok].astype(float))
                ws.append(self.week[c][ix[ok]])
                ns.append(self.win[c][ix[ok]])
        if not vs:
            return np.zeros(0), np.zeros(0, np.int64), np.zeros(0, np.int8)
        return np.concatenate(vs), np.concatenate(ws), np.concatenate(ns)


def stats_row(v: np.ndarray, w: np.ndarray, win: np.ndarray) -> dict:
    n = len(v)
    out = {"n": n, "mean": float(v.mean()) if n else None, "win": float((v > 0).mean()) if n else None,
           "t": None, "p": None}
    if n >= MIN_TRADES:
        out["t"], out["p"] = K.cluster_t(v, w)
    out["w"] = [[int((win == i).sum()), float(v[win == i].mean()) if (win == i).any() else None] for i in range(3)]
    return out


def entries_and(T: TfSet, a: str, b: str, k: int, off: Optional[float] = None) -> dict:
    out = {}
    for c in T.coins:
        pair = []
        for s in (0, 1):
            ib = T.idx[c][b][s]
            if off is not None:
                ib = K.shift_idx(ib, int(off * T.n[c]), T.n[c])
            pair.append(K.and_idx(T.idx[c][a][s], ib, k))
        out[c] = K.drop_conflicts(*pair)
    return out


def entries_filter(T: TfSet, a: str, b: str, nb: int, off: Optional[float] = None) -> dict:
    out = {}
    for c in T.coins:
        ib, bs = T.any[c][b]
        if off is not None:
            sh = int(off * T.n[c])
            o = np.argsort((ib + sh) % T.n[c], kind="stable")
            ib, bs = ((ib + sh) % T.n[c])[o], bs[o]
        out[c] = (K.filter_idx(T.idx[c][a][0], 1, ib, bs, nb), K.filter_idx(T.idx[c][a][1], -1, ib, bs, nb))
    return out


def entries_vote(T: TfSet, kk: int, offs: Optional[np.ndarray] = None) -> dict:
    out = {}
    for c in T.coins:
        rows = []
        for j, nm in enumerate(T.names):
            x = T.sig[c][nm]
            rows.append(np.roll(x, int(offs[j] * T.n[c])) if offs is not None else x)
        v = K.vote_sides(np.vstack(rows), kk)
        out[c] = (K.sig_idx(v, 1), K.sig_idx(v, -1))
    return out


def entries_mtf(T: TfSet, H: TfSet, name: str, age: Optional[int], off: Optional[float] = None) -> dict:
    out = {}
    for c in T.coins:
        lc = K.closed_higher(T.ts[c], T.tf, H.ts[c], H.tf)
        ih, hs = H.any[c][name]
        if off is not None:
            sh = int(off * H.n[c])
            o = np.argsort((ih + sh) % H.n[c], kind="stable")
            ih, hs = ((ih + sh) % H.n[c])[o], hs[o]
        out[c] = (K.mtf_idx(T.idx[c][name][0], 1, lc, ih, hs, age), K.mtf_idx(T.idx[c][name][1], -1, lc, ih, hs, age))
    return out


def build_entries(key: str, sets: dict, off=None) -> dict:
    fam, *p = key.split("|")
    if fam == "AND":
        a, b, k, tf = p
        return entries_and(sets[tf], a, b, int(k), off)
    if fam == "FILTER":
        a, b, nb, tf = p
        return entries_filter(sets[tf], a, b, int(nb), off)
    if fam == "VOTE":
        kk, tf = p
        return entries_vote(sets[tf], int(kk), off)
    if fam == "MTF":
        name, lo, hi, age = p
        return entries_mtf(sets[lo], sets[hi], name, MTF_AGE[age], off)
    if fam == "ONE":
        name, tf = p
        T = sets[tf]
        return {c: T.idx[c][name] for c in T.coins}
    raise ValueError(key)


def trial_keys(names: list) -> list[str]:
    keys = []
    for tf in TFS:
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                keys += [f"AND|{a}|{b}|{k}|{tf}" for k in AND_K]
        for a in names:
            for b in names:
                if a != b:
                    keys += [f"FILTER|{a}|{b}|{nb}|{tf}" for nb in FILTER_N]
        keys += [f"VOTE|{kk}|{tf}" for kk in VOTE_K]
    for lo, hi in MTF_PAIRS:
        for nm in names:
            keys += [f"MTF|{nm}|{lo}|{hi}|{age}" for age in MTF_AGE]
    return keys


def _tfs_of(key: str) -> tuple:
    fam, *p = key.split("|")
    return (p[1], p[2]) if fam == "MTF" else (p[-1],)


_SETS: dict = {}


def _sets(sig_dir: str, work: str, names: list, tfs) -> dict:
    for tf in tfs:
        if tf not in _SETS:
            _SETS[tf] = TfSet(sig_dir, work, tf, names)
    return _SETS


def trials_job(args) -> str:
    """Every trial whose timeframes are ``tfs`` (keys in order): its statistics, in one checkpoint file."""
    tag, keys, sig_dir, work, names = args
    path = os.path.join(work, "trials", f"{tag}.json")
    if os.path.exists(path):
        return path
    tfs = sorted({t for k in keys for t in _tfs_of(k)})
    S = _sets(sig_dir, work, names, tfs)
    rows = {}
    for k in keys:
        rows[k] = stats_row(*S[_tfs_of(k)[0]].gather(build_entries(k, S)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        json.dump(rows, fh)
    os.replace(path + ".tmp", path)
    return path


def null_job(args) -> str:
    """The shuffle null of the given trials: the partner moved in time (circular shift), NULL_RUNS runs each."""
    tag, keys, sig_dir, work, names, reals = args
    path = os.path.join(work, "nulls", f"{tag}.json")
    if os.path.exists(path):
        return path
    tfs = sorted({t for k in keys for t in _tfs_of(k)})
    S = _sets(sig_dir, work, names, tfs)
    rows = {}
    for k in keys:
        rng = np.random.default_rng([SEED, zlib.crc32(k.encode())])
        means = []
        for _ in range(NULL_RUNS):
            off = rng.uniform(0.1, 0.9, size=len(names)) if k.startswith("VOTE") else float(rng.uniform(0.1, 0.9))
            v, _w, _n = S[_tfs_of(k)[0]].gather(build_entries(k, S, off))
            means.append(float(v.mean()) if len(v) else None)
        rp = K.rank_p(reals[k], [m for m in means if m is not None])
        rows[k] = {"null_median": K.r4(float(np.median([m for m in means if m is not None])), 6)
                   if any(m is not None for m in means) else None, "rank_p": rp,
                   "null_p95": K.r4(float(np.quantile([m for m in means if m is not None], 0.95)), 6)
                   if any(m is not None for m in means) else None}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        json.dump(rows, fh)
    os.replace(path + ".tmp", path)
    return path


# ---------------------------------------------------------------- stage 6: one shared account
_ZERO: dict = {}


def shared_job(args) -> str:
    """The shared account of one portfolio (its members' signals on every timeframe), month by month."""
    rank, members, sig_dir, work = args
    path = os.path.join(work, "shared", f"{rank}_{hashlib.sha1('|'.join(members).encode()).hexdigest()[:8]}.json")
    if os.path.exists(path):
        return path
    RB, L = _rb(), _lib()
    data = {tf: load_tf(sig_dir, tf) for tf in TFS}
    bars = {tf: {c: {k: data[tf][c][k] for k in ("ts", "o", "h", "l", "c", "atr")} for c in RB.COINS} for tf in TFS}
    groups = {(tf, m): load_groups(work, tf, m) for tf in TFS for m in members}
    mons = month_list()
    d0 = int(K.kst_day(mons[0]["start"]))
    daily = np.zeros(int(K.kst_day(mons[-1]["end"])) - d0)
    accounts = len(members) * len(TFS)
    tot = {k: 0 for k in ("signals", "entries", "same", "conflict", "refused", "wins")}
    bust_months = 0
    month_pnl = []
    for m in mons:
        bnd = {tf: {c: K.bounds_in(data[tf][c]["ts"], m["start"] * 1_000_000, m["end"] * 1_000_000,
                                   L.warmup_bars(tf)) for c in RB.COINS} for tf in TFS}
        cands = []
        for mi, mem in enumerate(members):
            for ti, tf in enumerate(TFS):
                g = groups[(tf, mem)]
                for pi, c in enumerate(RB.COINS):
                    lo, ne = bnd[tf][c]
                    idx, best = g[f"{c}_idx"], g[f"{c}_best"]
                    sel = (idx >= lo) & (idx < ne - 1)
                    sig = data[tf][c]["s__" + mem]
                    for i, b in zip(idx[sel].tolist(), best[sel].tolist()):
                        t = int(data[tf][c]["ms"][i]) + K.TF_MS[tf]
                        side = int(sig[i])
                        cands.append((t, pi, ti, mi, c, side, (tf, c, i, side, "best" if b else "normal", ne)))
        cands.sort(key=lambda x: x[:4])

        def trade(payload, eq_share):
            tf, c, i, side, grp, ne = payload
            z = _ZERO.setdefault((tf, c), np.zeros(len(data[tf][c]["ts"]), np.int8))
            z[i] = side
            try:
                with v4_rules(RB, lambda *_a: grp, initial=eq_share):
                    r = RB.simulate(bars[tf], {c: z}, {c: (i, ne)}, K_STOP, tf, L, keep_trades=True)
            finally:
                z[i] = 0
            tt = r["trade_table"]
            if not len(tt):
                return None
            row = tt.iloc[0]
            ex_open = int(data[tf][c]["ms"][int(row["exit_j"])])
            return ex_open + K.TF_MS[tf], float(row["R"]) * float(row["margin_frac"]) * eq_share, ex_open

        res = K.shared_month(cands, trade, INITIAL * accounts, accounts)
        for bt, pnl in res["booked"]:
            K.daily_add(daily, np.array([int(K.kst_day(bt)) - d0]), np.array([pnl]))
        for k in tot:
            tot[k] += res[k]
        bust_months += int(res["bust"])
        month_pnl.append(res["final"] - INITIAL * accounts)
    out = {"members": members, "accounts": accounts, "capital": INITIAL * accounts, "month_pnl": month_pnl,
           "daily": daily.tolist(), "bust_months": bust_months, **tot}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        json.dump(out, fh)
    os.replace(path + ".tmp", path)
    return path


# ---------------------------------------------------------------- the run
def params() -> dict:
    return {"version": VERSION, "first": FIRST, "last": LAST, "tfs": TFS, "k": K_STOP, "initial": INITIAL,
            "flip_groups": FLIP_GROUPS, "shuffles": SHUFFLES, "null_runs": NULL_RUNS, "min_trades": MIN_TRADES,
            "fdr": FDR, "and_k": AND_K, "filter_n": FILTER_N, "vote_k": VOTE_K, "mtf": MTF_PAIRS,
            "mtf_age": MTF_AGE, "seed": SEED}


def _pool_map(fn, jobs: list, procs: int, what: str) -> list:
    if not jobs:
        return []
    t0 = time.time()
    out = []
    if procs <= 1:
        for j, x in enumerate(jobs, 1):
            out.append(fn(x))
            if j % 20 == 0:
                log(f"{what} {j}/{len(jobs)}")
    else:
        with get_context("fork").Pool(procs) as p:
            for j, x in enumerate(p.imap(fn, jobs), 1):
                out.append(x)
                if j % 20 == 0 or j == len(jobs):
                    log(f"{what} {j}/{len(jobs)} ({time.time() - t0:.0f}s)")
    return out


def stage_timings(work: str, now: dict) -> dict:
    """Seconds per stage of the run that really computed it: a resumed stage (its checkpoints already there) takes
    ~0 s now, so the first computing run's time is kept (work/timings.json) and reported."""
    path = os.path.join(work, "timings.json")
    try:
        with open(path) as fh:
            old = json.load(fh)
    except (OSError, ValueError):
        old = {}
    out = {k: max(float(now.get(k) or 0.0), float(old.get(k) or 0.0)) for k in set(now) | set(old) if k != "total_s"}
    out["total_s"] = round(sum(v for k, v in out.items() if k != "total_s"), 1)
    with open(path, "w") as fh:
        json.dump(out, fh)
    return out


def check_config() -> dict:
    from paperbot.config import V3_INITIAL, V3_STOP_ATR, V3_TRADE_TFS, v4_settings
    s = v4_settings()
    assert tuple(V3_TRADE_TFS) == TFS and float(V3_STOP_ATR) == K_STOP and float(V3_INITIAL) == INITIAL
    RB = _rb()
    assert float(s.bust_below) == float(RB.BUST_BELOW), (s.bust_below, RB.BUST_BELOW)
    assert (s.taker_fee, s.slippage_frac, s.liq_buffer_atr_mult) == (RB.SETTINGS.taker_fee, RB.SETTINGS.slippage_frac,
                                                                    RB.SETTINGS.liq_buffer_atr_mult)
    return {"taker_fee": s.taker_fee, "slippage": s.slippage_frac, "funding_8h": RB.FUNDING_8H,
            "bust_below": s.bust_below, "liq_buffer_atr": s.liq_buffer_atr_mult}


def run(sig_dir: str, out: str, work: str, procs: int = 2) -> dict:
    procs = max(1, min(int(procs), MAX_PROCS))
    t_start = time.time()
    cfg = check_config()
    sig = hashlib.sha256(json.dumps(params(), sort_keys=True, default=list).encode()).hexdigest()[:10]
    work = os.path.join(os.path.abspath(work), sig)
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "params.json"), "w") as fh:
        json.dump(params(), fh, default=list)
    names = strategy_names()
    L = _lib()
    timings = {}
    rates = {}
    for tf in TFS:
        rates[tf] = flip_rate(load_tf(sig_dir, tf), names, tf, L.warmup_bars(tf))
    with open(SUMMARY_JSON) as fh:
        ref_rates = json.load(fh)["random_rate"]
    _DATA.clear()                                   # the workers load their own copies
    log("rates", rates)

    t = time.time()
    _pool_map(group_job, [(tf, nm, sig_dir, work) for tf in TFS for nm in names], procs, "groups")
    timings["groups_s"] = round(time.time() - t, 1)

    t = time.time()
    flips = [f"RANDOM_{k}" for k in range(1, FLIP_GROUPS * UNITS_PER_GROUP + 1)]
    jobs = [(tf, u, sig_dir, work, rates[tf], ref_rates.get(tf)) for tf in TFS for u in names + flips]
    _pool_map(account_job, jobs, procs, "accounts")
    timings["accounts_s"] = round(time.time() - t, 1)

    t = time.time()
    RB = _rb()
    _pool_map(outcome_job, [(tf, c, sig_dir, work) for tf in TFS for c in RB.COINS], procs, "outcomes")
    timings["outcomes_s"] = round(time.time() - t, 1)

    t = time.time()
    keys = trial_keys(names)
    by: dict = {}
    for k in keys:
        by.setdefault("_".join(_tfs_of(k)), []).append(k)
    chunks = []
    for tag, ks in sorted(by.items()):
        for j in range(0, len(ks), 1500):
            chunks.append((f"{tag}_{j // 1500}", ks[j:j + 1500], sig_dir, work, names))
    rows: dict = {}
    for p in _pool_map(trials_job, chunks, procs, "trials"):
        with open(p) as fh:
            rows.update(json.load(fh))
    singles = {}
    S1 = None
    for tf in TFS:
        S1 = _sets(sig_dir, work, names, (tf,))
        for nm in names:
            singles[f"ONE|{nm}|{tf}"] = stats_row(*S1[tf].gather(build_entries(f"ONE|{nm}|{tf}", S1)))
    _SETS.clear()
    _DATA.clear()
    tested = [k for k in keys if rows[k]["p"] is not None]
    passed = dict(zip(tested, K.bh([rows[k]["p"] for k in tested], FDR)))
    single_tested = [k for k in singles if singles[k]["p"] is not None]
    single_pass = dict(zip(single_tested, K.bh([singles[k]["p"] for k in single_tested], FDR)))
    by_t = sorted(tested, key=lambda k: -rows[k]["t"])
    to_null = sorted(set([k for k in tested if passed[k]] + by_t[:TOP_MERGED]))
    nb: dict = {}
    for k in to_null:
        nb.setdefault("_".join(_tfs_of(k)), []).append(k)
    nchunks = [(f"{tag}_{len(ks)}_{hashlib.sha1('|'.join(ks).encode()).hexdigest()[:8]}", ks, sig_dir, work, names,
                {k: rows[k]["mean"] for k in ks}) for tag, ks in sorted(nb.items())]
    nulls: dict = {}
    for p in _pool_map(null_job, nchunks, procs, "nulls"):
        with open(p) as fh:
            nulls.update(json.load(fh))
    _SETS.clear()
    _DATA.clear()
    timings["merged_s"] = round(time.time() - t, 1)

    t = time.time()
    port = portfolio(work, names, flips)
    timings["portfolio_s"] = round(time.time() - t, 1)

    t = time.time()
    sjobs = [(f"{v}_{i}", c["units"], sig_dir, work) for v in ("all", "active")
             for i, c in enumerate(port[v]["top"][:TOP_SHARED])]
    shared: dict = {"all": [], "active": []}
    for (tag, *_r), p in zip(sjobs, _pool_map(shared_job, sjobs, procs, "shared")):
        with open(p) as fh:
            shared[tag.split("_")[0]].append(json.load(fh))
    timings["shared_s"] = round(time.time() - t, 1)
    timings["total_s"] = round(time.time() - t_start, 1)
    timings = stage_timings(work, timings)

    doc = assemble(work, names, flips, rates, ref_rates, cfg, rows, passed, nulls, singles, single_pass, port, shared,
                   timings, sig_dir)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(out + ".tmp", out)
    log(f"wrote {out} ({os.path.getsize(out) / 1e6:.2f} MB) in {timings['total_s']}s")
    return doc


# ---------------------------------------------------------------- portfolios
def unit_daily(work: str, unit: str, key: str = "daily") -> np.ndarray:
    return np.sum([load_acct(work, tf, unit)[key] for tf in TFS], axis=0)


def unit_trades(work: str, unit: str) -> int:
    return int(sum(load_acct(work, tf, unit)["m_trades"].sum() for tf in TFS))


def search_variant(U: np.ndarray, units: list, F: np.ndarray, flips: list, mons: list, d0: int, sl: list) -> dict:
    """agents/synergy's search, its two guards and the calendar-year walk-forward on the units ``units`` (rows of U);
    the coin-flip groups use as many coin-flip units as there are units, so both searches have the same size."""
    from paperbot.agents import synergy as SY
    n = len(units)
    cap = np.full(n, INITIAL * len(TFS))
    best = SY.search(U, cap, keep=TOP_PORT)
    real = best[0][0]
    log(f"portfolio[{n}]: day shuffles")
    null = SY.shuffled_bests(U, cap, runs=SHUFFLES, seed=SEED)
    log(f"portfolio[{n}]: coin-flip groups")
    flip_best = []
    for g in range(FLIP_GROUPS):
        a = g * UNITS_PER_GROUP
        fb = SY.search(F[a:a + n], cap, keep=1)
        flip_best.append({"group": g + 1, "score": fb[0][0], "units": [flips[a + i] for i in fb[0][1]]})
    log(f"portfolio[{n}]: walk-forward")
    years = K.year_slices(mons, d0)
    srch = (lambda UU, cc: SY.search(UU, cc, keep=1))
    wf = K.walk_forward(U, cap, years, srch, SY.curve_numbers)
    wf_flip = K.walk_forward(F[:n], cap, years, srch, SY.curve_numbers)
    for rows in (wf, wf_flip):
        for r in rows:
            r["months_next"] = sum(1 for m in mons if m["label"].startswith(str(r["test_year"])))
            r["mean_month_next"] = r["return_next"] / max(1, r["months_next"])
    top = []
    for sc, combo in best:
        c = list(combo)
        row = U[c].sum(axis=0)
        capc = float(cap[c].sum())
        tot, ddu, ddp, _ = SY.curve_numbers(row[None, :], np.array([capc]))
        mm = K.month_sums(row, sl)
        top.append({"units": [units[i] for i in c], "k": len(c), "score": float(sc), "pnl": float(tot[0]),
                    "capital": capc, "mean_month": float(mm.mean() / capc), "dd_usd": float(ddu[0]),
                    "dd_peak": float(ddp[0]), "win_months": float((mm > 0).mean()),
                    "div": SY.diversification(U, cap, combo), "month_pnl": mm.tolist()})
    return {"units": units, "top": top, "real": real, "null": null.tolist(), "flip_best": flip_best, "wf": wf,
            "wf_flip": wf_flip}


def portfolio(work: str, names: list, flips: list) -> dict:
    """Both searches: ``all`` (the 36, as specified: agents/synergy's search over every strategy) and ``active`` (only
    the strategies with at least MIN_UNIT_TRADES closed trades in the 62 monthly accounts: a strategy that never
    trades never loses, so with every strategy losing it wins the score by doing nothing), plus the correlation map
    and the coin-flip band (shared by both)."""
    from paperbot.agents.meetings import corr_clusters
    mons = month_list()
    d0 = int(K.kst_day(mons[0]["start"]))
    sl = K.month_day_slices(mons, d0)
    U = np.vstack([unit_daily(work, s) for s in names])
    F = np.vstack([unit_daily(work, f) for f in flips])
    trades = {s: unit_trades(work, s) for s in names}
    active = [s for s in names if trades[s] >= MIN_UNIT_TRADES]
    log("portfolio: search (all 36)")
    v_all = search_variant(U, names, F, flips, mons, d0, sl)
    log(f"portfolio: search (active {len(active)})")
    ix = [names.index(s) for s in active]
    v_act = search_variant(U[ix], active, F, flips, mons, d0, sl)
    log("portfolio: correlation")
    C = K.corr_matrix(U)
    T = K.tail_corr(U, 0.05)
    CL = K.coloss(U)
    pairs = [(float(C[i, j]), names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))
             if np.isfinite(C[i, j])]
    clusters = corr_clusters(names, pairs, 0.7)
    unit_month = {s: K.month_sums(U[i], sl) for i, s in enumerate(names)}
    # coin-flip band per combination size: random size-k groups of coin-flip units (every flip group pooled)
    rng = np.random.default_rng(SEED)
    FM = np.vstack([K.month_sums(F[i], sl) for i in range(len(F))])
    band = {}
    for k in range(2, 6):
        picks = np.array([rng.choice(len(F), size=k, replace=False) for _ in range(2000)])
        cum = np.cumsum(FM[picks].sum(axis=1), axis=1) / (k * INITIAL * len(TFS))
        band[str(k)] = {q: np.quantile(cum, p, axis=0).tolist() for q, p in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))}
    return {"all": v_all, "active": v_act, "trades": trades, "corr": C, "tail": T, "coloss": CL, "clusters": clusters,
            "unit_month": unit_month, "flip_band": band, "flip_month": FM}


# ---------------------------------------------------------------- the JSON
def _tri(M: np.ndarray, nd: int = 3) -> list:
    """The upper triangle (i < j) row by row, rounded (None for NaN)."""
    n = len(M)
    return [K.r4(M[i, j], nd) for i in range(n) for j in range(i + 1, n)]


def _stats(m: np.ndarray) -> dict:
    return {k: (K.r4(v) if isinstance(v, float) else v) for k, v in K.month_stats(m.tolist()).items()}


def assemble(work, names, flips, rates, ref_rates, cfg, rows, passed, nulls, singles, single_pass, port, shared,
             timings, sig_dir) -> dict:
    import pandas as pd
    from paperbot.agents.roster3 import STRATEGY_KO
    mons = month_list()
    d0 = int(K.kst_day(mons[0]["start"]))
    sl = K.month_day_slices(mons, d0)
    cap1 = INITIAL
    per = {}
    misses = collides = looked = 0
    for s in names:
        tfrows = {}
        sum_daily = np.zeros(sl[-1][1])
        sum_one = np.zeros(sl[-1][1])
        agg = {k: 0.0 for k in ("trades", "wins", "liq", "bust")}
        for tf in TFS:
            a = load_acct(work, tf, s)
            misses += int(a["miss"][0])
            collides += int(a["miss"][1])
            looked += int(a["miss"][2])
            sum_daily += a["daily"]
            sum_one += a["one_daily"]
            m = a["m_pnl"] / cap1
            one = a["one"]
            tr = int(a["m_trades"].sum())
            tfrows[tf] = {"m": [K.r4(x) for x in m], **_stats(m),
                          "trades": tr, "win_rate": K.r4(a["m_wins"].sum() / tr) if tr else None,
                          "liq": int(a["m_liq"].sum()), "bust_months": int(a["m_bust"].sum()),
                          "one": {"multiple": K.r4(one[0] / INITIAL), "mdd": K.r4(one[1]), "bust": bool(one[2]),
                                  "bust_ms": int(one[3]) if one[2] else None, "trades": int(one[4]),
                                  "win_rate": K.r4(one[5] / one[4]) if one[4] else None}}
            for k, src in (("trades", "m_trades"), ("wins", "m_wins"), ("liq", "m_liq"), ("bust", "m_bust")):
                agg[k] += float(a[src].sum())
        capS = cap1 * len(TFS)
        m = K.month_sums(sum_daily, sl) / capS
        el = K.elapsed_matrix(sum_daily, sl, ELAPSED_DAYS) / capS
        one_curve = capS + np.cumsum(sum_one)
        dd_usd, dd_pk = K.curve_mdd(sum_one, capS)
        per[s] = {"m": [K.r4(x) for x in m], **_stats(m), "trades": int(agg["trades"]),
                  "win_rate": K.r4(agg["wins"] / agg["trades"]) if agg["trades"] else None, "liq": int(agg["liq"]),
                  "bust_months": int(agg["bust"]),
                  "elapsed_bp": [[int(round(x * 10_000)) for x in row] for row in el],
                  "one": {"multiple": K.r4(one_curve[-1] / capS), "mdd": K.r4(dd_pk)},
                  "tfs": tfrows}
    # coin flips: the pooled monthly distribution of a 4-timeframe coin-flip unit, and per timeframe
    FM = port["flip_month"] / (cap1 * len(TFS))
    flip_tf = {}
    for tf in TFS:
        v = np.concatenate([load_acct(work, tf, f)["m_pnl"] / cap1 for f in flips])
        flip_tf[tf] = _stats(v)
    flips_out = {"units": len(flips), "seeds": [1, len(flips)], "rate": {tf: K.r4(r, 6) for tf, r in rates.items()},
                 "unit_months": _stats(FM.ravel()), "tfs": flip_tf,
                 "median_month": [K.r4(x) for x in np.median(FM, axis=0)]}
    # parity
    acc = pd.read_csv(ACCOUNTS_CSV)
    acc = acc[(acc["k"] == K_STOP) & acc["tf"].isin(TFS)]
    with open(CARDS_JSON) as fh:
        cards = {c["strategy"]: {r["tf"]: r for r in c["rows"]} for c in json.load(fh)["cards"]}
    n = same_final = same_trades = card_same = card_cells = 0
    card_blank = []
    worst = 0.0
    v4_vs = []
    for _i, r in acc.iterrows():
        a = load_acct(work, r["tf"], r["strategy"])
        wi = 0 if r["window"] == "is" else 1
        fin, trd = a["par"][0, wi]
        n += 1
        diff = abs(fin - r["final"])
        worst = max(worst, diff)
        same_final += int(diff <= 1e-6 * max(1.0, abs(r["final"])))
        same_trades += int(int(trd) == int(r["trades"]))
        if not str(r["strategy"]).startswith("RANDOM_"):
            cr = cards.get(r["strategy"], {}).get(r["tf"], {})
            cv = cr.get("account_is" if wi == 0 else "account_cf")
            if cv is None:                     # a card row without account numbers (a strategy that never signals)
                card_blank.append(f"{r['strategy']}@{r['tf']} {r['window']}")
            else:
                card_cells += 1
                card_same += int(abs(cv - fin) <= 1e-6 * max(1.0, abs(cv)))
            v4f = a["par"][1, wi][0]
            v4_vs.append((r["final"] / 1000.0, v4f / INITIAL, bool(r["bust"]), v4f < 10.0))
    v4a = np.array([x[:2] for x in v4_vs])
    parity = {
        "cells": n, "same_final": same_final, "same_trades": same_trades, "max_abs_diff": K.r4(worst, 9),
        "cards_cells": card_cells, "cards_same": card_same, "cards_blank": len(card_blank),
        "cards_blank_why": (f"{', '.join(sorted({x.split('@')[0] for x in card_blank}))}: 5년 동안 신호가 없어 카드에 계좌 숫자가 없음 "
                            "(이 생성기도 그 칸은 거래 0건, 잔고 그대로)") if card_blank else None,
        "agree": bool(n and same_final == n and same_trades == n and card_same == card_cells),
        "what": ("research/paper_rules/out_binance/accounts.csv (k 2 ATR, windows is / cf, 15m-4h, the 36 and RANDOM_1-3) "
                 "와 strategy_profiles/out_binance/cards.json account_is / account_cf 를 이 생성기의 rules_bt.simulate 호출로 "
                 "같은 캐시에서 다시 계산해 칸마다 비교"),
        "v4_same_windows": {
            "median_multiple_research": K.r4(float(np.median(v4a[:, 0]))),
            "median_multiple_v4": K.r4(float(np.median(v4a[:, 1]))),
            "bust_research": int(sum(x[2] for x in v4_vs)), "bust_v4": int(sum(x[3] for x in v4_vs)),
            "why": ("같은 신호·같은 창에서 v4 규칙으로 바꾸면 달라지는 것: 시작 $5,000(연구 $1,000), 레버리지 규칙 quality_v1(진입 강도 "
                    "'best'만 50배·50% → 40배·40%, 나머지 30배·30% → 20배·20%; 연구는 모든 신호가 50배부터)")},
    }
    # groups sanity: share of strategy signals that are "best" per timeframe (config.V3_P_BEST is the live share)
    from paperbot.config import V3_P_BEST
    best_share = {}
    for tf in TFS:
        tot = b = 0
        for s in names:
            g = load_groups(work, tf, s)
            for c in _rb().COINS:
                tot += len(g[f"{c}_idx"])
                b += int(g[f"{c}_best"].sum())
        best_share[tf] = {"signals": tot, "best": b, "share": K.r4(b / tot if tot else 0), "p_best_config": V3_P_BEST[tf]}
    # merged rules
    keys = list(rows)
    fam_count: dict = {}
    for k in keys:
        f = k.split("|")[0]
        d = fam_count.setdefault(f, {"trials": 0, "tested": 0, "bh": 0, "both": 0})
        d["trials"] += 1
        d["tested"] += int(rows[k]["p"] is not None)
        d["bh"] += int(passed.get(k, False))
        d["both"] += int(passed.get(k, False) and (nulls.get(k, {}).get("rank_p") or 1) <= 0.05)
    tested = [k for k in keys if rows[k]["p"] is not None]
    by_t = sorted(tested, key=lambda k: -rows[k]["t"])

    def comp(k):
        fam, *p = k.split("|")
        if fam in ("AND", "FILTER"):
            return [singles.get(f"ONE|{p[0]}|{p[3]}"), singles.get(f"ONE|{p[1]}|{p[3]}")]
        if fam == "MTF":
            return [singles.get(f"ONE|{p[0]}|{p[1]}")]
        return []

    def mrow(k):
        r = rows[k]
        nl = nulls.get(k, {})
        fam, *p = k.split("|")
        return {"key": k, "family": fam, "parts": p, "n": r["n"], "mean": K.r4(r["mean"], 6), "win": K.r4(r["win"]),
                "t": K.r4(r["t"], 3), "p": K.r4(r["p"], 6), "bh": bool(passed.get(k, False)),
                "null_rank_p": K.r4(nl.get("rank_p"), 4), "null_median": nl.get("null_median"),
                "shuffle_pass": bool((nl.get("rank_p") or 1) <= 0.05),
                "w": [[x[0], K.r4(x[1], 6)] for x in r["w"]],
                "consistent": bool(all(x[0] > 0 and x[1] is not None and x[1] > 0 for x in r["w"])),
                "alone": [{"n": c["n"], "mean": K.r4(c["mean"], 6)} if c else None for c in comp(k)]}
    survivors = [k for k in tested if passed.get(k) and (nulls.get(k, {}).get("rank_p") or 1) <= 0.05]
    merged = {
        "trials": len(keys), "tested": len(tested), "bh_pass": int(sum(passed.values())),
        "both_pass": len(survivors), "families": fam_count,
        "top": [mrow(k) for k in by_t[:TOP_MERGED]],
        "survivors": [mrow(k) for k in sorted(survivors, key=lambda k: -rows[k]["t"])[:TOP_MERGED]],
        "singles": {"cells": len(singles), "tested": len(single_tested_keys(singles)), "bh_pass": int(sum(single_pass.values())),
                    "positive_mean": int(sum(1 for v in singles.values() if v["mean"] is not None and v["mean"] > 0))},
        "min_trades": MIN_TRADES, "fdr": FDR, "null_runs": NULL_RUNS,
        "params": {"and_k": list(AND_K), "filter_n": list(FILTER_N), "vote_k": list(VOTE_K),
                   "mtf": [list(x) for x in MTF_PAIRS], "mtf_age": {k: v for k, v in MTF_AGE.items()}},
        "windows": [w[0] for w in WIN3],
    }
    # portfolios: the specified search over all 36 and the same search over the strategies that trade
    trades_of = port["trades"]

    def fl(x):
        return {k: (K.r4(v) if isinstance(v, float) else v) for k, v in x.items()}

    def variant(v: dict) -> dict:
        real = v["real"]
        null = np.asarray(v["null"])
        return {
            "units": v["units"],
            "top": [{**fl({k: x for k, x in t.items() if k != "month_pnl"}),
                     "pnl": K.r4(t["pnl"], 0), "capital": t["capital"], "dd_usd": K.r4(t["dd_usd"], 0),
                     "div": K.r4(t["div"], 3), "trades": int(sum(trades_of[u] for u in t["units"])),
                     "curve": [K.r4(x) for x in np.cumsum(t["month_pnl"]) / t["capital"]]} for t in v["top"]],
            "shuffled_days": {"runs": int(len(null)), "real_best": K.r4(real, 3),
                              "null_median": K.r4(float(np.median(null)), 3),
                              "null_p90": K.r4(float(np.quantile(null, 0.9)), 3), "rank_p": K.r4(K.rank_p(real, null), 3)},
            "coin_flips": {"groups": [{"group": g["group"], "score": K.r4(g["score"], 3)} for g in v["flip_best"]],
                           "beat_real": int(sum(1 for g in v["flip_best"] if g["score"] >= real)),
                           "units_per_group": len(v["units"])},
            "walk_forward": [{**fl({k: x for k, x in w.items() if k != "combo"}),
                              "units": [v["units"][i] for i in w["combo"]]} for w in v["wf"]],
            "walk_forward_flips": [fl({k: x for k, x in w.items() if k != "combo"}) for w in v["wf_flip"]],
        }
    quiet = sorted((s for s in names if trades_of[s] < MIN_UNIT_TRADES), key=lambda s: trades_of[s])
    portfolio_out = {
        "unit": "매매법 1개 = 15분·30분·1시간·4시간 계좌 4개의 합 ($20,000)",
        "all": variant(port["all"]), "active": variant(port["active"]),
        "active_rule": {"min_trades": MIN_UNIT_TRADES, "left_out": [{"strategy": s, "trades": trades_of[s]} for s in quiet],
                        "why": ("36개 모두 이 규칙에서 5년 동안 돈을 잃어서, 거의 거래하지 않는 매매법이 '잃지 않아서' 1위가 됩니다. "
                                f"그래서 5년 동안 거래가 {MIN_UNIT_TRADES}건(평균 한 달 1건) 이상인 매매법만으로 같은 탐색을 한 번 더 "
                                "했습니다 (이 기준은 결과를 본 뒤에 정한 것)")},
        "trades": {s: trades_of[s] for s in names},
        "corr": {"r": _tri(port["corr"]), "tail": _tri(port["tail"]), "coloss": _tri(port["coloss"]),
                 "clusters": port["clusters"], "tail_share": 0.05},
        "unit_curves": {s: [K.r4(x) for x in np.cumsum(v) / (INITIAL * len(TFS))] for s, v in port["unit_month"].items()},
        "flip_band": {k: {q: [K.r4(x) for x in v] for q, v in b.items()} for k, b in port["flip_band"].items()},
        "search": {"exhaustive": "2·3개 전부", "beam": 200, "kmin": 2, "kmax": 5,
                   "score": "총손익 ÷ 최대 낙폭($), 낙폭 바닥 = 자본의 0.5% (agents/synergy.py)"},
    }

    def shared_rows(items: list) -> list:
        out = []
        for sh in items:
            mem = sh["members"]
            sep_daily = np.sum([unit_daily(work, u) for u in mem], axis=0)
            sd = np.asarray(sh["daily"])
            capc = sh["capital"]
            sm, pm = K.month_sums(sep_daily, sl), np.asarray(sh["month_pnl"])

            def side_numbers(daily, mm, trades):
                dd_u, dd_p = K.curve_mdd(daily, capc)
                return {"pnl": K.r4(float(daily.sum()), 0), "mean_month": K.r4(float(mm.mean() / capc)),
                        "win_months": K.r4(float((mm > 0).mean())), "dd_usd": K.r4(dd_u, 0), "dd_peak": K.r4(dd_p),
                        "trades": int(trades), "curve": [K.r4(x) for x in np.cumsum(mm) / capc]}
            sep_trades = sum(int(load_acct(work, tf, u)["m_trades"].sum()) for tf in TFS for u in mem)
            out.append({"units": mem, "capital": capc, "accounts": sh["accounts"],
                        "separate": side_numbers(sep_daily, sm, sep_trades),
                        "shared": {**side_numbers(sd, pm, sh["entries"]), "signals": sh["signals"],
                                   "same_side_skipped": sh["same"], "conflicts": sh["conflict"],
                                   "refused": sh["refused"], "bust_months": sh["bust_months"]}})
        return out
    shared_out = {"all": shared_rows(shared["all"]), "active": shared_rows(shared["active"])}
    import subprocess
    try:
        head = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        head = None
    labdata = None
    try:
        with open(os.path.join(sig_dir, "labdata_manifest.json")) as fh:
            man = json.load(fh)
        labdata = {"checked_utc": man.get("checked_utc"),
                   "identical": sum(1 for r in man.get("files", {}).values() if r.get("status") == "identical"),
                   "files": len(man.get("files", {}))}
    except (OSError, ValueError):
        pass
    methods = {
        "label": LABEL,
        "period": {"first": FIRST, "last": LAST, "months": len(mons), "tz": "KST",
                   "partial_last": "2026-09: 자료가 9/30 08:45(한국 시간)까지라 마지막 달은 하루 조금 모자람"},
        "accounts": ("매달 1일(한국 시간)에 계좌마다 $5,000로 새로 시작하는 모의 계좌 (지금 30일 실험과 같은 모양). 파산하면 그 달만 끝, "
                     "달 끝에 열린 포지션은 그 달 마지막 봉 종가로 닫음. '5년 한 계좌'는 같은 계좌를 5년 내내 이어서 굴린 것"),
        "sizing": ("v4 규칙 그대로: 2 ATR 손절, 계단식 수익 잠금, 계좌당 포지션 1개(코인 우선순위), 진입 강도 'best' 신호만 50배·증거금 50% → "
                   "40배·40%, 나머지 30배·30% → 20배·20%, 손절까지 손실 15% 이하. 'best' 여부는 신호마다 실제 진입 강도 점수로 "
                   "(paperbot/levrule.py와 같은 계산), 동전 봇은 설정의 확률로 뽑음"),
        "best_share": best_share,
        "costs": {**cfg, "words": "수수료 0.05%(시장가)·슬리피지 0.02% 양쪽, 펀딩 8시간마다 0.01%(양방향 모두 냄), 청산·파산 반영"},
        "merged_sizing": ("합친 규칙은 모두 '보통' 배수(30배·30% → 20배·20%)로: 새 규칙에는 진입 강도 정의가 없어 실제로 돌리면 이렇게 됨. "
                          "신호마다 거래 한 건(계좌·포지션 제한 없음), 결과 = 거래 한 건이 계좌에 남긴 손익 %"),
        "trials": {"merged": len(keys), "merged_tested": len(tested), "portfolio_shuffles": SHUFFLES,
                   "coin_flip_groups": FLIP_GROUPS, "coin_flip_units": len(flips),
                   "portfolio_combos_searched": "2·3개 조합 전부(630 + 7,140) + 4·5개는 상위 200개에서 하나씩 늘려 봄",
                   "portfolio_searches": (f"두 번: 36개 전부(명세 그대로), 5년 거래 {MIN_UNIT_TRADES}건 이상인 "
                                          f"{len(port['active']['units'])}개만 (결과를 본 뒤 더한 것)")},
        "caveat": ("이 36개는 바로 이 5년 자료를 보고 고른 매매법입니다. 그래서 여기 숫자는 실제보다 좋게 나오기 쉽습니다 (선택 편향). "
                   "설명용이며 판정이 아니고, 미리 등록한 연구도 아닙니다. 지난 5년이 앞으로를 약속하지 않습니다."),
        "data": {"signals": "Binance USD-M 선물 5년 캐시 (paperbot/agents/labdata.py로 만들고 연구 캐시와 대조)",
                 "labdata": labdata, "group_lookup": {"looked_up": looked, "missed": misses, "collisions": collides}},
        "timings": timings, "git_head": head,
        "generator": "python -m paperbot.dash.tools.combo5y --signals <dir> --out paperbot/dash/data/combo5y.json",
    }
    return {"version": VERSION, "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "label": LABEL, "months": [m["label"] for m in mons], "month_start_ms": [m["start"] for m in mons],
            "strategies": names, "names": {s: STRATEGY_KO.get(s, s) for s in names}, "tfs": list(TFS),
            "initial": INITIAL, "per": per, "flips": flips_out, "parity": parity, "portfolio": portfolio_out,
            "merged": merged, "shared": shared_out, "methods": methods}


def single_tested_keys(singles: dict) -> list:
    return [k for k, v in singles.items() if v["p"] is not None]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m paperbot.dash.tools.combo5y", description=__doc__.split("\n")[0])
    ap.add_argument("--signals", required=True, help="the 5-year signal cache (sig_<tf>_<COIN>.npz)")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--work", default=os.environ.get("COMBO5Y_WORK") or os.path.join(os.getcwd(), ".combo5y_work"),
                    help="checkpoint folder (a restart resumes from it)")
    ap.add_argument("--procs", type=int, default=2)
    a = ap.parse_args(argv)
    run(a.signals, a.out, a.work, a.procs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
