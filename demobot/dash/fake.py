"""A complete, realistic FAKE snapshot folder for developing and testing the demo lab dashboard (never the real bot).

    python -m demobot.dash.fake OUTDIR [--past5y DIR] [--seed 7] [--phase live|warm] [--empty] [--views 40]

Writes every file of demobot/CONTRACT.md sections 4, 7 and 8: status (with the dead-man ping), home (with the goal
line, the market now and the measured cost), accounts (each line with its stop-rule twin and its P&L parts),
acct/<id> for the 48 accounts plus two neutral private ones (curves, stop-rule curves, stop events, trades with the
measured cost, the maker fills' through_bps, the regime at entry, fee, notional), trades, judge (confirmation periods,
candidates, stop-rule columns), views, costs, regime, backup, watch, bars/<COIN>.npz (15m bars from 7 days before the
live start), rank_<STRAT>_<tf>.npz for the 3 strategies x 2 timeframes with the exact shapes (grid.NEXIT exits),
rank_meta and, with --past5y, a fake past5y_<STRAT>_<tf>.npz per strategy and timeframe into that folder. Round 4
part A (fake_live.py): positions, calendar, signals_now, dataq, timeline, export/<id>.csv.gz, acct "daily" and home
"equity_total" / "pnl_total". Round 4 part B (CONTRACT 9.5-9.7): analysis.json, vs5y.json (against the fake 5-year numbers, written or not), the fixed accounts'
combo / exit_i and the judge rows' n / mean_R / luck_lim / boot_low. CONTRACT 9.11: each accounts.json line's "spark" (30
equity values from the live start to now) and "pnl_pct_24h" (the line's P&L % one day before), as the engine's report.py.

The trades are played on the fake bars (entries at bar opens, stops k x ATR14, the exits' rules), so a trade chart
shows them where they happened. The default clock is about six weeks into the run (2026-11-23), long enough for the
stories of section 8.1: one line confirmed ("실전 후보"), one whose confirmation failed, one still confirming.
Deterministic (seeded); the numbers are made up and only shaped like the engine's. --empty writes only status.json
(the first minutes of a warm-up).
"""
from __future__ import annotations

import argparse
import bisect
import datetime
import heapq
import json
import math
import os
import re
import sys

import numpy as np

from .. import grid

UTC = datetime.timezone.utc
FIXED_NOW_MS = int(datetime.datetime(2026, 11, 23, 5, 15, tzinfo=UTC).timestamp() * 1000)
NOW_MS = FIXED_NOW_MS          # build(now_ms=...) moves it (the module's functions read this one clock)
DAY = 86_400_000
HOUR = 3_600_000
LIVE_DAYS = 44.3              # the live start falls on 10/10 morning (KST) with the default clock
SEED_USD = 1000.0
TAKER, SLIP, FUND8 = 0.0005, 0.0002, 0.0001
PRICE = {"BTCUSD": 112_400.0, "ETHUSD": 4_120.0, "SOLUSD": 211.0, "DOGEUSD": 0.2412, "LTCUSD": 104.6,
         "BCHUSD": 561.0, "XRPUSD": 2.61}
ATR_PCT = {"15m": 0.0035, "30m": 0.005}
TF_KO = {"15m": "15분", "30m": "30분"}
TF_MS = {"15m": 15 * 60_000, "30m": 30 * 60_000}
SHORTS = ("S2", "N02", "N04")
KIND_KO = {"fixed": "고정", "adaptive": "자동 교체", "friend": "친구 규칙", "flip": "동전 던지기", "private": "비공개 매매법"}
PERIODS = ("2020", "2021-23", "2024-26", "2020-03", "2022-05", "2022-11")
HOUSE_KO = grid.exit_ko(0)
M15 = 15 * 60_000
MAKER = 0.0002
RUIN = 0.1                    # a wallet below 10% of the seed is ruined and restarts at the seed
LOOK = 12                     # a skilled entry knows the direction of the next LOOK 15m bars (fake edge)
CAP_BARS = 288                # a trade that has not exited after 72 h is closed at the bar's close ("time")
DEADLINE_MS = int(datetime.datetime(2026, 12, 31, 15, 0, tzinfo=UTC).timestamp() * 1000)   # 12/31 24:00 KST
SIZES = [500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000]
ASSUMED_BPS = SLIP * 1e4
COST_LOG_DAYS = 6.0           # the order book log starts this many days after the live start
TRENDS = ("up", "down", "range")
VOLS = ("high", "normal", "low")
TREND_KO = {"up": "상승 추세", "down": "하락 추세", "range": "횡보"}
VOL_KO = {"high": "변동 큼", "normal": "보통", "low": "변동 작음"}
SIGMA = {"BTCUSD": 0.0016, "ETHUSD": 0.0021, "SOLUSD": 0.0029, "DOGEUSD": 0.0032, "LTCUSD": 0.0025, "BCHUSD": 0.0027,
         "XRPUSD": 0.0028}    # 15m log-return size per coin (BTC's 15m ATR comes out near 0.25%)
VOL_MULT = {"high": 1.7, "normal": 1.0, "low": 0.62}
# simplified Binance brackets: (notional up to, max leverage); the entry check refuses a notional the leverage's tier
# does not allow (CONTRACT 1: "bracket max leverage"), which also keeps a lucky line's compounding in bounds
BRACKETS = {"BTCUSD": [(5e4, 125), (6e5, 100), (3e6, 75), (1.2e7, 50), (7e7, 25)],
            "ETHUSD": [(5e4, 125), (5e5, 100), (2e6, 75), (1e7, 50), (5e7, 25)],
            "SOLUSD": [(5e4, 75), (2.5e5, 50), (1e6, 25), (5e6, 20)],
            "DOGEUSD": [(5e4, 75), (2.5e5, 50), (1e6, 25), (3e6, 20)],
            "XRPUSD": [(5e4, 75), (2.5e5, 50), (1e6, 25), (3e6, 20)],
            "LTCUSD": [(1e4, 75), (5e4, 50), (2.5e5, 25), (1e6, 20)],
            "BCHUSD": [(1e4, 75), (5e4, 50), (2.5e5, 25), (1e6, 20)]}
MAX_NOTIONAL = {(c, L): max([cap for cap, lev in tiers if lev >= L] or [0.0]) for c, tiers in BRACKETS.items()
                for L in (20, 30, 40, 50)}
FUND_RATE = {"BTCUSD": 0.0001, "ETHUSD": 0.00008, "SOLUSD": 0.00012, "DOGEUSD": 0.00015, "LTCUSD": 0.00005,
             "BCHUSD": 0.00009, "XRPUSD": 0.0001}     # per 8 h, + = longs pay


def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))    # dumps: the fast C encoder
    os.replace(tmp, path)


def _write_npz(path: str, compress: bool = True, **arrays) -> None:
    tmp = path + ".tmp.npz"
    (np.savez_compressed if compress else np.savez)(tmp, **arrays)
    os.replace(tmp, path)


def _r(x, nd=4):
    return None if x is None or not math.isfinite(x) else round(float(x), nd)


def _kst(ms: int) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone(datetime.timedelta(hours=9))).strftime("%m/%d %H:%M")


def coin_ko(c: str) -> str:
    return grid.coin_ko(c)


# ---------------------------------------------------------------- the 48 accounts (+ 2 private)
def account_specs() -> list:
    out = []

    def add(aid, kind, sub, short, tf, name, rule_ko, combo=None):
        strat = grid.LONG.get(short)
        out.append({"id": aid, "kind": kind, "sub": sub, "short": short, "strategy": strat, "tf": tf, "name": name,
                    "rule_ko": rule_ko, "combo": combo})

    for s in SHORTS:
        for tf in grid.TFS:
            c = grid.default_combo(grid.LONG[s])
            add(f"fx-def-{s}-{tf}", "fixed", "default", s, tf, f"{s} 기본값 · {TF_KO[tf]}",
                f"기본값 그대로 ({grid.combo_label(grid.LONG[s], c)})", c)
    for s in ("S2", "N04"):
        for tf in grid.TFS:
            c = grid.friend_combo(grid.LONG[s])
            add(f"fx-fr-{s}-{tf}", "fixed", "friend", s, tf, f"{s} 친구 값 · {TF_KO[tf]}",
                f"친구가 쓰는 값 그대로 ({grid.combo_label(grid.LONG[s], c)})", c)
    for s in SHORTS:
        for tf in grid.TFS:
            c = grid.PICK[(grid.LONG[s], tf)]
            add(f"fx-pk-{s}-{tf}", "fixed", "pick", s, tf, f"{s} 5년 1등 값 · {TF_KO[tf]}",
                f"5년 연구의 1등 값 그대로 ({grid.combo_label(grid.LONG[s], c)})", c)
    adaptive = {"r26": ("자동 · 5거래마다(26주)", "닫힌 거래 5건마다, 최근 26주 주변 평균 1등 설정으로 바꿈 (코인 모두 함께)"),
                "r4": ("자동 · 5거래마다(4주)", "닫힌 거래 5건마다, 최근 4주 주변 평균 1등 설정으로 바꿈 (코인 모두 함께)"),
                "r26c": ("자동 · 코인별(26주)", "닫힌 거래 5건마다, 코인마다 그 코인의 최근 26주 1등 설정으로 바꿈"),
                "wk": ("자동 · 매주(26주)", "매주 월요일 09:00, 최근 26주 주변 평균 1등 설정으로 바꿈 (코인 모두 함께)")}
    for sub, (nm, rule) in adaptive.items():
        for s in SHORTS:
            for tf in grid.TFS:
                add(f"ad-{sub}-{s}-{tf}", "adaptive", sub, s, tf, f"{s} {nm} · {TF_KO[tf]}", rule)
    for s in SHORTS:
        for tf in grid.TFS:
            add(f"fr-{s}-{tf}", "friend", "rule", s, tf, f"{s} 친구 규칙 · 매주 · {TF_KO[tf]}",
                "매주 월요일, 코인·배수마다 지난 26주에 돈을 번 (설정 × 청산) 중 낙폭이 가장 작은 것을 일주일 돌림")
    for tf in grid.TFS:
        add(f"cf-{tf}", "flip", "flip", None, tf, f"동전 던지기 · {TF_KO[tf]}",
            "아무 봉에서 아무 방향으로 들어가고 사다리로 나감 (운 비교용)")
    # private plug-ins (CONTRACT 7.2): neutral names only, never a real plug-in's name or rules
    for i, tf in enumerate(grid.TFS, 1):
        add(f"pv-p{i}-{tf}", "private", f"p{i}", None, tf, f"비공개 {i} · {TF_KO[tf]}",
            f"서버에만 있는 매매법 {i} (규칙은 공개하지 않습니다)")
    return out


def _label(strat, c) -> str:
    return grid.combo_label(strat, int(c))


def _percoin_ko(pairs) -> str:
    return f"코인별 {len(pairs)}개 (" + ", ".join(f"{coin_ko(k)} {v}" for k, v in pairs) + ")"


# ---------------------------------------------------------------- the market: 15m bars and regimes (CONTRACT 8.5, 8.6)
class Market:
    """Fake 15m bars of the 7 coins from 7 days before the live start to now, driven by a regime schedule (trend
    and volatility segments of 1.5-5 days, mostly shared by the coins), so the candles, the regime labels and the
    trades drawn on them agree. The last close of each coin is PRICE[coin]."""

    def __init__(self, rng, live_start):
        self.t0 = (live_start - 7 * DAY) // M15 * M15
        self.ts = np.arange(self.t0, NOW_MS, M15, dtype=np.int64)        # closed bars only (the last one closes at now)
        N = len(self.ts)
        self.bars, self.trend, self.vol, self.atr, self.history = {}, {}, {}, {}, {}
        seg = []                                                            # the market's schedule: (start, trend, vol)
        i, prev = 0, None
        while i < N:
            while True:
                tr = TRENDS[int(rng.choice(3, p=(0.33, 0.30, 0.37)))]
                vo = VOLS[int(rng.choice(3, p=(0.25, 0.50, 0.25)))]
                if (tr, vo) != prev:
                    break
            seg.append((i, tr, vo))
            prev = (tr, vo)
            i += int(rng.integers(144, 480))
        zm = rng.standard_t(5, N) * 0.78
        for coin in grid.COINS:
            tcode = np.zeros(N, np.int8)
            vcode = np.zeros(N, np.int8)
            pts = []
            for k, (s0, tr, vo) in enumerate(seg):
                s = 0 if k == 0 else int(np.clip(s0 + rng.integers(-16, 17), 1, N - 1))
                if rng.random() > 0.75:
                    tr = TRENDS[int(rng.integers(3))]
                if rng.random() > 0.8:
                    vo = VOLS[int(rng.integers(3))]
                tcode[s:] = TRENDS.index(tr)
                vcode[s:] = VOLS.index(vo)
            for j in range(N):
                if j == 0 or tcode[j] != tcode[j - 1] or vcode[j] != vcode[j - 1]:
                    pts.append([int(self.ts[j]), TRENDS[tcode[j]], VOLS[vcode[j]]])
            sig = SIGMA[coin] * np.array([VOL_MULT[v] for v in VOLS])[vcode]
            drift = np.array([0.085, -0.085, 0.0])[tcode] * sig
            zi = rng.standard_t(5, N) * 0.78
            r = drift + sig * (0.65 * zm + 0.76 * zi)
            lc = np.cumsum(r)
            c = np.exp(lc - lc[-1]) * PRICE[coin]
            o = np.concatenate([[c[0] * math.exp(-r[0])], c[:-1]])
            wick = np.abs(rng.normal(0, 0.42, (2, N))) * sig
            h = np.maximum(o, c) * np.exp(wick[0])
            low = np.minimum(o, c) * np.exp(-wick[1])
            pc = np.concatenate([[o[0]], c[:-1]])
            tr_ = np.maximum(h - low, np.maximum(np.abs(h - pc), np.abs(low - pc)))
            atr = np.convolve(tr_, np.ones(14) / 14, mode="full")[:N]
            atr[:14] = atr[14]
            self.bars[coin] = {"o": o, "h": h, "l": low, "c": c}
            self.trend[coin], self.vol[coin] = tcode, vcode
            self.atr[coin] = atr / c                                       # ATR14 / close (a ratio)
            self.history[coin] = pts

    def idx(self, t_ms: int) -> int:
        return int((t_ms - self.t0) // M15)

    def regime_at(self, coin, entry_ms):
        """(trend, vol) of the last closed bar before an entry (None before the first bar)."""
        i = self.idx(entry_ms) - 1
        if i < 0:
            return None, None
        return TRENDS[self.trend[coin][i]], VOLS[self.vol[coin][i]]

    def now_rows(self, rng):
        out = []
        for coin in grid.COINS:
            tr, vo = TRENDS[self.trend[coin][-1]], VOLS[self.vol[coin][-1]]
            slope = {"up": float(rng.uniform(0.6, 2.1)), "down": -float(rng.uniform(0.6, 2.1)),
                     "range": float(rng.uniform(-0.45, 0.45))}[tr]
            out.append({"coin": coin, "trend": tr, "vol": vo, "slope": _r(slope, 3),
                        "atr_pct": _r(float(self.atr[coin][-1]) * 100, 4), "since_ms": self.history[coin][-1][0]})
        return out

    def write(self, outdir):
        os.makedirs(os.path.join(outdir, "bars"), exist_ok=True)
        for coin, b in self.bars.items():
            _write_npz(os.path.join(outdir, "bars", f"{coin}.npz"), compress=False, ts=self.ts.copy(), o=b["o"],
                       h=b["h"], l=b["l"], c=b["c"])


def exit_mode(ex):
    """(mode, target R, stop distance in ATR) of an exit index (None: the private plug-ins' own exit)."""
    if ex is None:
        return "tpsl", 1.5, 1.5
    if ex == 0:
        return "house", None, 2.0
    if grid.is_tpsl(ex):
        tp, k = grid.TPSL_CFG[ex - 1]
        return "tpsl", tp, k
    return "half", 1.5, 2.0


def _first(mask):
    j = int(np.argmax(mask)) if mask.size else 0
    return j if mask.size and mask[j] else None


def outcome(mk, coin, i, side, ex, tf, fill=None):
    """One trade on the fake bars: entry at bar i's open (plus 2 bps slippage, or a limit fill), stop k x ATR14,
    the exit's rule bar by bar (the stop first when one bar touches both), a 72 h cap; open when the bars end."""
    b = mk.bars[coin]
    o, hh, ll, cc = b["o"], b["h"], b["l"], b["c"]
    N = len(o)
    mode, tp, k = exit_mode(ex)
    fill = float(o[i] * (1 + side * SLIP)) if fill is None else float(fill)
    atr = float(mk.atr[coin][i - 1]) * fill * (1.41 if tf == "30m" else 1.0)
    dist = k * atr
    stop = fill - side * dist
    end = min(N, i + CAP_BARS)
    hi, lo, op = hh[i:end], ll[i:end], o[i:end]
    if side > 0:
        fav, adv, opn = (hi - fill) / dist, (lo - fill) / dist, (op - fill) / dist
    else:
        fav, adv, opn = (fill - lo) / dist, (fill - hi) / dist, (fill - op) / dist
    j, xR, reason = None, None, None
    if mode == "house":                                      # the ladder: 1R -> break-even, 2R -> +1R, 3R -> +2R ...
        best = np.concatenate([[0.0], np.maximum.accumulate(fav)[:-1]])
        rung = np.floor(np.maximum(best, 0.0))
        stopR = np.where(rung >= 2, rung - 1, np.where(rung >= 1, 0.0, -1.0))
        j = _first(adv <= stopR)
        if j is not None:
            xR = float(min(stopR[j], opn[j]))
            reason = "stop" if stopR[j] < 0 else "lock"
    if mode == "tpsl":
        js, jt = _first(adv <= -1.0), _first(fav >= tp)
        if js is not None and (jt is None or js <= jt):
            j, xR, reason = js, float(min(-1.0, opn[js])), "stop"
        elif jt is not None:
            j, xR, reason = jt, float(max(tp, opn[jt])), "tp"
    half = None                                              # half mode: the bar where the first half was taken
    rest = None                                              # half mode: R of the second half at its exit
    if mode == "half":                                       # half at 1R, stop to break-even, the rest at 1.5R
        js, ja = _first(adv <= -1.0), _first(fav >= 1.0)
        if js is not None and (ja is None or js <= ja):
            j, xR, reason = js, float(min(-1.0, opn[js])), "stop"
        elif ja is not None:
            half = ja
            if fav[ja] >= tp:
                j, rest, reason = ja, tp, "tp"
            else:
                jb, jt = _first(adv[ja + 1:] <= 0.0), _first(fav[ja + 1:] >= tp)
                if jb is not None and (jt is None or jb <= jt):
                    j, rest, reason = ja + 1 + jb, 0.0, "lock"
                elif jt is not None:
                    j, rest, reason = ja + 1 + jt, tp, "tp"
    out = {"fill": fill, "stop": stop, "dist": dist, "d": dist / fill, "tp": tp if mode == "tpsl" else None}
    if j is None:
        if end >= N:                                         # still running at the last bar: open
            out.update(open=True, mark=float(cc[-1]), exit_ms=None, exit=None, reason="open",
                       mae=float(max(0.0, -adv.min()) * out["d"]) if adv.size else 0.0)
            return out
        j = end - 1 - i
        reason = "time"
        if half is not None:
            rest = float(side * (cc[i + j] - fill) / dist)
        else:
            xR = float(side * (cc[i + j] - fill) / dist)
    if rest is not None:                                     # the price of the second half's exit; R of the whole
        exit_px = fill + side * rest * dist
        xR = 0.5 * 1.0 + 0.5 * rest
    else:
        exit_px = fill + side * xR * dist
    out.update(open=False, exit_ms=int(mk.ts[i + j] + M15), exit=float(exit_px), Rg=float(xR), reason=reason,
               mae=float(max(0.0, -adv[: j + 1].min()) * out["d"]), mark=None)
    return out


# ---------------------------------------------------------------- order book costs (CONTRACT 8.3)
class CostModel:
    """Fake order book cost curves per coin and tick since depth logging began: half the spread plus an impact that
    grows with the order size; wider in volatile stretches; sizes past the 500 levels are null."""
    HALF = {"BTCUSD": 0.06, "ETHUSD": 0.11, "SOLUSD": 0.33, "DOGEUSD": 0.5, "LTCUSD": 1.05, "BCHUSD": 1.35, "XRPUSD": 0.42}
    IMP = {"BTCUSD": 0.07, "ETHUSD": 0.13, "SOLUSD": 0.55, "DOGEUSD": 0.75, "LTCUSD": 2.1, "BCHUSD": 2.7, "XRPUSD": 0.62}
    COVER = {"BTCUSD": 9e6, "ETHUSD": 6e6, "SOLUSD": 1.6e6, "DOGEUSD": 1.2e6, "LTCUSD": 2.3e5, "BCHUSD": 1.5e5,
             "XRPUSD": 1.4e6}

    def __init__(self, rng, mk, since_ms):
        self.mk, self.since = mk, since_ms
        self.ticks = np.arange(since_ms, NOW_MS, M15, dtype=np.int64)
        n = len(self.ticks)
        self.state = {}
        for coin in grid.COINS:
            vi = mk.vol[coin][np.clip(((self.ticks - mk.t0) // M15).astype(int) - 1, 0, len(mk.ts) - 1)]
            vf = np.array([1.6, 1.0, 0.8])[vi]
            half = self.HALF[coin] * vf * rng.lognormal(0, 0.28, n)
            imp = self.IMP[coin] * vf * rng.lognormal(0, 0.35, n)
            skew = rng.normal(0, 0.06, n)
            cover = self.COVER[coin] * rng.lognormal(0, 0.3, n)
            self.state[coin] = (half, imp, skew, cover)

    def k(self, t_ms):
        if t_ms < self.since:
            return None
        return int(min(len(self.ticks) - 1, (t_ms - self.since) // M15))

    def cost(self, coin, k, size, side):
        half, imp, skew, cover = self.state[coin]
        if size > cover[k]:
            return None
        return float(half[k] + imp[k] * (1 + side * skew[k]) * (size / 10_000.0) ** 0.75)

    def snapshot(self):
        coins, series = [], []
        i10 = SIZES.index(10_000)
        sz = (np.array(SIZES, float) / 10_000.0) ** 0.75
        for coin in grid.COINS:
            half, imp, skew, cover = self.state[coin]
            n = len(self.ticks)
            mat = {}
            for s in (1, -1):
                m = half[:, None] + (imp * (1 + s * skew))[:, None] * sz[None, :]
                mat[s] = np.where(np.array(SIZES, float)[None, :] > cover[:, None], np.nan, m)
            def stat(m, f):
                out = []
                for c in range(len(SIZES)):
                    v = m[:, c][np.isfinite(m[:, c])]
                    out.append(_r(float(f(v)), 3) if v.size >= n / 2 else None)
                return out
            last = {s: [None if not np.isfinite(x) else _r(float(x), 3) for x in mat[s][-1]] for s in (1, -1)}
            coins.append({"coin": coin, "n": n, "last_ms": int(self.ticks[-1]),
                          "spread_bps": {"last": _r(2 * half[-1], 3), "median": _r(float(np.median(2 * half)), 3)},
                          "buy_bps": {"median": stat(mat[1], np.median), "p90": stat(mat[1], lambda v: np.percentile(v, 90)),
                                      "last": last[1]},
                          "sell_bps": {"median": stat(mat[-1], np.median),
                                       "p90": stat(mat[-1], lambda v: np.percentile(v, 90)), "last": last[-1]}})
            pts = [[int(t), _r(2 * half[k], 3), _r(float(mat[1][k, i10]), 3)] for k, t in enumerate(self.ticks)]
            series.append({"coin": coin, "points": _down(pts, 800)})
        return coins, series


def _down(points, limit):
    if len(points) <= limit:
        return points
    step = len(points) / (limit - 1)
    idx = sorted({int(i * step) for i in range(limit - 1)} | {len(points) - 1})
    return [points[i] for i in idx]


SPARK_N = 30


def spark_of(curve) -> dict:
    """CONTRACT 9.11, as the engine's report._spark: 30 equity values sampled evenly from the live start to now (the last
    point at or before each step) and the P&L % one day before the curve's last point (null without a point that old)."""
    if not curve:
        return {"spark": [], "pnl_pct_24h": None}
    t = np.asarray([c[0] for c in curve], np.int64)
    v = np.asarray([c[1] for c in curve], float)
    steps = np.linspace(t[0], t[-1], SPARK_N).astype(np.int64)
    i = np.clip(np.searchsorted(t, steps, side="right") - 1, 0, len(v) - 1)
    j = int(np.searchsorted(t, t[-1] - DAY, side="right")) - 1
    ago = _r((float(v[j]) - SEED_USD) / SEED_USD * 100, 2) if j >= 0 else None
    return {"spark": [_r(float(x), 2) for x in v[i]], "pnl_pct_24h": ago}


# ---------------------------------------------------------------- stop rules (CONTRACT 8.2; same as the engine's)
def kst_day(t_ms: int) -> int:
    return (int(t_ms) + 9 * HOUR) // DAY


class StopRules:
    HALT, DAYLOSS, STREAK, PAUSE_MS = 0.80, 0.05, 5, 24 * HOUR

    def __init__(self, L):
        self.L = L
        self.halted_ms, self.pause_until, self.day, self.day_start_W = None, -1, None, SEED_USD
        self.day_pnl, self.day_block_until, self.streak = 0.0, -1, 0
        self.blocked = self.day_pauses = self.streak_pauses = 0
        self.events = []

    def _roll(self, t, W):
        d = kst_day(t)
        if d != self.day:
            self.day, self.day_start_W, self.day_pnl = d, W, 0.0

    def on_close(self, t, pnl, W_before, W_after):
        self._roll(t, W_before)
        self.day_pnl += pnl
        self.streak = self.streak + 1 if pnl < 0 else 0
        if self.streak >= self.STREAK:
            self.streak = 0
            self.pause_until = max(self.pause_until, t + self.PAUSE_MS)
            self.streak_pauses += 1
            self.events.append({"t_ms": int(t), "L": self.L, "what": "streak", "until_ms": int(self.pause_until),
                                "wallet": _r(W_after, 2)})
        if self.day_block_until < t and self.day_pnl <= -self.DAYLOSS * self.day_start_W:
            self.day_block_until = (self.day + 1) * DAY - 9 * HOUR
            self.day_pauses += 1
            self.events.append({"t_ms": int(t), "L": self.L, "what": "day", "until_ms": int(self.day_block_until),
                                "wallet": _r(W_after, 2)})
        if self.halted_ms is None and W_after <= self.HALT * SEED_USD:
            self.halted_ms = int(t)
            self.events.append({"t_ms": int(t), "L": self.L, "what": "halt", "until_ms": None, "wallet": _r(W_after, 2)})

    def block(self, t, W):
        self._roll(t, W)
        if self.halted_ms is not None or t < self.pause_until or t < self.day_block_until:
            self.blocked += 1
            return True
        return False


# ---------------------------------------------------------------- the accounts
# a few accounts get a (fake) edge, so the confirmation stories of CONTRACT 8.1 all appear: (from day, to day, share of
# entries that pick the side of the next 3 h move; negative = the wrong side). Everything else is close to luck.
SKILL = {
    "fx-pk-S2-15m": {"n": 420, "p": [(0, 99, 0.66)]},                          # passes early, confirmed: 실전 후보
    "ad-r26-N04-15m": {"n": 420, "p": [(0, 19, 0.62), (19, 99, -0.25)]},      # passes early, then fails its check
    "ad-r4-S2-15m": {"n": 380, "p": [(0, 15, 0.0), (15, 99, 0.6)]},           # passes later: still confirming
}


class _Acct:
    """One fake account: entries shared by its four leverage lines (the friend rule: an exit per coin and line),
    the lines simulated like the engine (wallet, one position per coin, margin cap, entry check, ruin restart), and the
    same lines again under the stop rules."""

    def __init__(self, spec, rng, live_start, mk, cm):
        self.spec, self.rng, self.live_start, self.mk, self.cm = spec, rng, live_start, mk, cm
        strat = spec["strategy"]
        self.settings_now, self.decisions = [], []
        self.line_setting = {}
        r = rng
        if spec["kind"] == "flip":
            self.setting_ko = "무작위 진입"
            self.settings_now = [{"coin": "ALL", "L": None, "setting_ko": "무작위 진입", "exit_ko": HOUSE_KO}]
        elif spec["kind"] == "private":
            self.setting_ko = "비공개 설정"
            self.settings_now = [{"coin": "ALL", "L": None, "setting_ko": "비공개 설정", "exit_ko": "비공개 청산"}]
        elif spec["kind"] == "fixed":
            self.setting_ko = _label(strat, spec["combo"])
            self.settings_now = [{"coin": "ALL", "L": None, "setting_ko": self.setting_ko, "exit_ko": HOUSE_KO}]
        elif spec["sub"] == "r26c":
            pairs = [(c, _label(strat, r.integers(grid.NCOMBO[strat]))) for c in grid.COINS]
            self.setting_ko = _percoin_ko(pairs)
            self.settings_now = [{"coin": c, "L": None, "setting_ko": v, "exit_ko": HOUSE_KO} for c, v in pairs]
        elif spec["kind"] == "friend":
            rows, by_l = [], {}
            self.exit_of = {}
            for L in grid.LEVS:
                pairs = []
                for c in grid.COINS:
                    lab = _label(strat, r.integers(grid.NCOMBO[strat]))
                    ei = int(r.integers(grid.NEXIT))
                    ex = grid.exit_ko(ei)
                    self.exit_of[(L, c)] = ei
                    rows.append({"coin": c, "L": L, "setting_ko": lab, "exit_ko": ex})
                    pairs.append((c, f"{lab} · {ex}"))
                by_l[str(L)] = _percoin_ko(pairs)
            self.settings_now, self.line_setting = rows, by_l
            self.setting_ko = "코인·배수마다 따로 (28개)"
        else:
            self.setting_ko = _label(strat, r.integers(grid.NCOMBO[strat]))
            self.settings_now = [{"coin": "ALL", "L": None, "setting_ko": self.setting_ko, "exit_ko": HOUSE_KO}]
        self._entries()
        self._lines()
        self._decisions()

    def _skill(self, day):
        for d0, d1, p in SKILL.get(self.spec["id"], {}).get("p", [(0, 99, self.edge)]):
            if d0 <= day < d1:
                return p
        return 0.0

    def _entries(self):
        r, spec, mk = self.rng, self.spec, self.mk
        tf = spec["tf"]
        step = TF_MS[tf]
        days = (NOW_MS - self.live_start) / DAY
        sk = SKILL.get(spec["id"], {})
        n = sk.get("n") or int((r.integers(150, 330) if tf == "15m" else r.integers(80, 190)) * days / 44.3)
        if spec["kind"] == "flip":
            n = int(n * 1.3)
        self.edge = float(np.clip(r.normal(0.0, 0.03), -0.06, 0.06)) if spec["kind"] != "flip" else 0.0
        lo = -(-self.live_start // step) * step
        sig = np.sort(r.uniform(lo, NOW_MS - step - M15, n)).astype(np.int64) // step * step
        look = LOOK if tf == "15m" else 2 * LOOK
        self.entries = []
        for t in sig:
            coin = grid.COINS[int(r.integers(len(grid.COINS)))]
            entry_ms = int(t) + step
            i = mk.idx(entry_ms)
            if i < 15 or i >= len(mk.ts):
                continue
            trend, vol = mk.regime_at(coin, entry_ms)
            p = self._skill((entry_ms - self.live_start) / DAY) * (0.45 if trend == "range" else 1.25)
            p = float(np.clip(p, -0.95, 0.95))
            side = 1 if r.random() < 0.5 else -1
            if r.random() < abs(p):
                c = mk.bars[coin]["c"]
                move = c[min(len(c) - 1, i + look)] - mk.bars[coin]["o"][i]
                side = (1 if move >= 0 else -1) * (1 if p > 0 else -1)
            e = {"coin": coin, "side": side, "signal_ms": int(t), "entry_ms": entry_ms, "i": i, "trend": trend,
                 "vol": vol, "maker": spec["kind"] == "private", "fill": None, "through_bps": None}
            if e["maker"]:                                    # a limit at or past the low (long) / high (short)
                b = mk.bars[coin]
                tb = float(r.uniform(0, 1)) if r.random() < 0.2 else 1 + float(r.exponential(9))
                if side > 0:
                    lim = min(b["l"][i] * (1 + tb / 1e4), b["o"][i] * (1 - 1e-4))
                    lim = max(lim, b["l"][i])
                    e["through_bps"] = (lim - b["l"][i]) / lim * 1e4
                else:
                    lim = max(b["h"][i] * (1 - tb / 1e4), b["o"][i] * (1 + 1e-4))
                    lim = min(lim, b["h"][i])
                    e["through_bps"] = (b["h"][i] - lim) / lim * 1e4
                e["fill"] = lim
            self.entries.append(e)
        self._out = {}

    def exit_for(self, L, coin):
        if self.spec["kind"] == "private":
            return None
        if self.spec["kind"] == "friend":
            return self.exit_of[(L, coin)]
        return 0

    def outcome(self, k, ex):
        key = (k, ex)
        if key not in self._out:
            e = self.entries[k]
            self._out[key] = outcome(self.mk, e["coin"], e["i"], e["side"], ex, self.spec["tf"], e["fill"])
        return self._out[key]

    def sim(self, L, rules=None):
        """One leverage line (CONTRACT 1 sizing; the engine's simulate_line in small)."""
        spec = self.spec
        tf = spec["tf"]
        W = peak = SEED_USD
        heap, trades, seq = [], [], 0
        curve = [[self.live_start, SEED_USD]]
        st = {"trades": 0, "wins": 0, "liqs": 0, "skipped": 0, "ruins": 0, "worst": 0, "max_dd": 0.0, "sumR": 0.0}
        streak = 0
        busy = {c: -1 for c in grid.COINS}
        used = {c: 0.0 for c in grid.COINS}
        buf = 1.0 / L - 0.004
        flip = spec["kind"] == "flip"

        def close_until(t):
            nonlocal W, peak, streak
            while heap and heap[0][0] <= t:
                x_ms, _s, pnl, margin, tr = heapq.heappop(heap)
                W0 = W
                W += pnl
                if rules is not None:
                    rules.on_close(x_ms, pnl, W0, W)
                used[tr["coin"]] -= margin
                tr["status"] = "closed"
                st["trades"] += 1
                st["wins"] += pnl > 0
                st["liqs"] += tr["reason"] == "liq"
                st["sumR"] += tr["R"]
                streak = streak + 1 if pnl < 0 else 0
                st["worst"] = max(st["worst"], streak)
                curve.append([x_ms, _r(W, 2)])
                peak = max(peak, W)
                st["max_dd"] = max(st["max_dd"], 1 - W / peak)
                if W < RUIN * SEED_USD:
                    st["ruins"] += 1
                    tr["ruin"] = True
                    W = peak = SEED_USD
                    curve.append([x_ms, SEED_USD])

        for k, e in enumerate(self.entries):
            close_until(e["entry_ms"])
            coin, side = e["coin"], e["side"]
            if busy[coin] >= e["entry_ms"]:
                st["skipped"] += 1
                continue
            ex = self.exit_for(L, coin)
            o = self.outcome(k, ex)
            if rules is not None and rules.block(e["entry_ms"], W):
                continue
            margin = W * L / 100.0
            if (o["d"] > 0.9 * buf or sum(used.values()) + margin > W + 1e-9
                    or margin * L > MAX_NOTIONAL[(coin, L)]):
                st["skipped"] += 1
                continue
            notional = margin * L
            fill = o["fill"]
            fee_in = notional * (MAKER if e["maker"] else TAKER + SLIP)
            fund = 0.0
            if o["open"]:
                pnl = side * (o["mark"] - fill) / fill * notional - fee_in
                fee, reason, exit_ms, exit_px = fee_in, "open", None, None
            elif o["mae"] >= buf:
                reason, exit_ms = "liq", o["exit_ms"]
                exit_px = fill * (1 - side * buf)
                pnl, fee = -margin, notional * (TAKER + SLIP)
            else:
                reason, exit_ms, exit_px = o["reason"], o["exit_ms"], o["exit"]
                fee = fee_in + notional * (TAKER + SLIP)
                fund = -side * notional * FUND_RATE[coin] * (exit_ms - e["entry_ms"]) / (8 * HOUR)
                pnl = o["Rg"] * o["d"] * notional - fee + fund
            R = pnl / (notional * o["d"])
            if spec["kind"] == "friend":
                setting = self.settings_now[grid.LEVS.index(L) * 7 + grid.COINS.index(coin)]["setting_ko"]
                exit_ko = grid.exit_ko(ex)
            elif spec["sub"] == "r26c":                       # per coin: that coin's own setting
                row = next((x for x in self.settings_now if x["coin"] == coin), self.settings_now[0])
                setting, exit_ko = row["setting_ko"], row["exit_ko"]
            else:
                setting, exit_ko = self.setting_ko, self.settings_now[0]["exit_ko"]
            tr = {"key": f"{coin}|{tf}|{e['signal_ms']}|{side}|{L}", "L": L, "coin": coin, "side": side,
                  "signal_ms": e["signal_ms"], "entry_ms": e["entry_ms"], "entry": _r(fill, 6), "stop": _r(o["stop"], 6),
                  "exit_ms": exit_ms, "exit": _r(exit_px, 6) if exit_px is not None else None,
                  "status": "open" if reason == "open" else "closed", "reason": reason, "pnl": _r(pnl, 2),
                  "roe": _r(pnl / margin, 4), "R": _r(R, 3), "margin": _r(margin, 2), "funding": _r(fund, 2),
                  "fee": _r(fee, 2), "notional": _r(notional, 2), "maker": e["maker"],
                  "setting_ko": "무작위 진입" if flip else setting, "exit_ko": exit_ko,
                  "cost_bps": None, "through_bps": _r(e["through_bps"], 2) if e["maker"] else None,
                  "trend": e["trend"], "vol": e["vol"], "_d": o["d"]}
            if not e["maker"]:
                kk = self.cm.k(e["entry_ms"])
                if kk is not None:
                    c = self.cm.cost(coin, kk, notional, side)
                    tr["cost_bps"] = _r(c, 3) if c is not None else None
            trades.append(tr)
            seq += 1
            if reason == "open":
                busy[coin] = 2 ** 62
                tr["_unreal"] = pnl
            else:
                busy[coin] = exit_ms - 1
                heapq.heappush(heap, (exit_ms, seq, pnl, margin, tr))
            used[coin] += margin
        close_until(NOW_MS)
        unreal = sum(t.get("_unreal", 0.0) for t in trades if t["status"] == "open")
        equity = W + unreal
        curve.append([NOW_MS, _r(equity, 2)])
        closed = [t for t in trades if t["status"] == "closed"]
        n = st["trades"]
        today0 = (NOW_MS + 9 * HOUR) // DAY * DAY - 9 * HOUR
        total = sum(t["pnl"] for t in closed) + unreal
        fees = sum(t["fee"] for t in closed)
        fund = sum(t["funding"] for t in closed)
        line = {"equity": _r(equity, 2), "wallet": _r(W, 2), "pnl": _r(total, 2), "pnl_pct": _r(total / SEED_USD * 100, 2),
                "today_pnl": _r(sum(t["pnl"] for t in closed if t["exit_ms"] >= today0), 2),
                "trades": n, "wins": st["wins"], "win_rate": _r(st["wins"] / n, 4) if n else None,
                "mean_R": _r(st["sumR"] / n, 3) if n else None, "max_dd": _r(st["max_dd"], 4),
                "open": len(trades) - len(closed), "liqs": st["liqs"], "skipped": st["skipped"],
                "worst_streak": st["worst"], "ruined": st["ruins"] > 0, "ruins": st["ruins"],
                "setting_ko": self.line_setting.get(str(L), self.setting_ko),
                "parts": {"gross": _r(sum(t["pnl"] for t in closed) - fund + fees, 2), "fees": _r(fees, 2),
                          "funding": _r(fund, 2), "open": _r(unreal, 2)}}
        line.update(spark_of(curve))                           # CONTRACT 9.11: the ranking row's small line
        return {"line": line, "trades": trades, "curve": _down(curve, 800)}

    def _lines(self):
        self.lines, self.curves, self.curves_stops, self.sims, self.ssims = {}, {}, {}, {}, {}
        events, all_trades = [], []
        for L in grid.LEVS:
            sim = self.sim(L)
            rules = StopRules(L)
            ssim = self.sim(L, rules)
            sl = ssim["line"]
            sim["line"]["stops"] = {"equity": sl["equity"], "pnl": sl["pnl"], "pnl_pct": sl["pnl_pct"],
                                    "max_dd": sl["max_dd"], "trades": sl["trades"], "mean_R": sl["mean_R"],
                                    "blocked": rules.blocked, "halted_ms": rules.halted_ms,
                                    "day_pauses": rules.day_pauses, "streak_pauses": rules.streak_pauses}
            self.lines[str(L)] = sim["line"]
            self.curves[str(L)] = sim["curve"]
            self.curves_stops[str(L)] = ssim["curve"]
            self.sims[L], self.ssims[L] = sim, ssim
            events += rules.events
            all_trades += sim["trades"]
        self.stop_events = sorted(events, key=lambda x: (x["t_ms"], x["L"]), reverse=True)[:200]
        all_trades.sort(key=lambda t: (t["exit_ms"] or NOW_MS + 1, t["entry_ms"], t["L"]), reverse=True)
        self.trades = [{k: v for k, v in t.items() if not k.startswith("_")} for t in all_trades[:600]]

    def _decisions(self):
        r, spec = self.rng, self.spec
        if spec["kind"] in ("fixed", "flip", "private"):
            return
        strat = spec["strategy"]
        win = "4주" if spec["sub"] == "r4" else "26주"
        closed = sorted({t["exit_ms"] for t in self.sims[20]["trades"] if t["status"] == "closed"})
        if spec["sub"] in ("r26", "r4", "r26c"):
            times = closed[4::5]
        else:                                                  # Mondays 00:00 UTC since the live start
            first = self.live_start - (self.live_start - 4 * DAY) % (7 * DAY) + 7 * DAY
            times = list(range(first, NOW_MS, 7 * DAY))
        prev = {}
        for t in times:
            if spec["kind"] == "friend":
                for L in grid.LEVS:
                    for c in grid.COINS:
                        to = f"{_label(strat, r.integers(grid.NCOMBO[strat]))} · {grid.exit_ko(int(r.integers(grid.NEXIT)))}"
                        self.decisions.append({"t_ms": int(t), "coin": c, "L": L,
                                               "from_ko": prev.get((c, L), "처음"), "to_ko": to,
                                               "why_ko": f"지난 26주 {L}배 수익 + 낙폭 최소 ({_r(float(r.uniform(4, 30)), 1)}%)"})
                        prev[(c, L)] = to
                continue
            coins = grid.COINS if spec["sub"] == "r26c" else ("ALL",)
            for c in coins:
                if spec["sub"] == "r26c" and r.random() < 0.6:
                    continue
                to = _label(strat, r.integers(grid.NCOMBO[strat]))
                n = int(r.integers(300, 2400) if win == "26주" else r.integers(40, 300))
                self.decisions.append({"t_ms": int(t), "coin": c, "L": None, "from_ko": prev.get(c, self.setting_ko),
                                       "to_ko": to, "why_ko": f"최근 {win} 주변 평균 1등 ({_r(float(r.normal(-0.04, 0.05)), 3):+.3f}R, {n:,}건)".replace("-", "−")})
                prev[c] = to
        self.decisions = self.decisions[-400:]
        self.decisions.sort(key=lambda d: d["t_ms"], reverse=True)

    def row(self) -> dict:
        s = self.spec
        return {"id": s["id"], "kind": s["kind"], "sub": s["sub"], "name": s["name"], "strategy": s["strategy"],
                "short": s["short"], "tf": s["tf"], "rule_ko": s["rule_ko"], "setting_ko": self.setting_ko,
                "lines": self.lines, "switches": len(self.decisions),
                "last_switch_ms": self.decisions[0]["t_ms"] if self.decisions else None,
                # CONTRACT 9.7: the fixed accounts' combo index and exit (the house exit); null for every other kind
                "combo": s["combo"] if s["kind"] == "fixed" else None, "exit_i": 0 if s["kind"] == "fixed" else None}

    def detail(self) -> dict:
        return {**self.row(), "generated_ms": NOW_MS, "curves": self.curves, "curves_stops": self.curves_stops,
                "stop_events": self.stop_events, "trades": self.trades, "decisions": self.decisions[:200],
                "settings_now": self.settings_now}


# ---------------------------------------------------------------- ranking arrays
def _exit_arrays():
    """Per exit of grid.EXITS (read at call time: 13 or 14 exits, CONTRACT 7.1): the payoff of a win in R, the stop
    distance in ATR, and a trade-count factor (faster exits: more trades)."""
    X, K, NF = [], [], []
    for name in grid.EXITS:
        m = re.fullmatch(r"tp([\d.]+)R_sl([\d.]+)atr", name)
        if name == "house":
            x, k, nf = 1.6, 2.0, 1.0
        elif m:
            x, k = float(m.group(1)), float(m.group(2))
            nf = 1.3 - 0.12 * x - 0.04 * k
        else:                                    # e.g. half1R_be_1.5R: half at 1R, the rest at 1.5R or break-even
            x, k, nf = 1.0, 2.0, 1.1
        X.append(x)
        K.append(k)
        NF.append(nf)
    return np.array(X), np.array(K), np.array(NF)


def _combo_shape(strat):
    C = grid.NCOMBO[strat]
    t = np.array([grid.combo_tuple(strat, c) for c in range(C)], float)
    u = t / (np.array(grid.SHAPE[strat], float) - 1)
    return C, u


def fake_rank(strat, tf, rng, live_start):
    EXIT_X, EXIT_K, EXIT_NF = _exit_arrays()
    C, u = _combo_shape(strat)
    W, E, S = len(grid.WINDOWS), grid.NEXIT, len(grid.SCOPES)
    edge = (0.03 * np.sin(2.4 * u[:, 0] + 0.6) * np.cos(1.9 * u[:, 1] - 0.4) + 0.025 * (u[:, 2] - 0.5)
            + (0.015 * np.cos(3.0 * u[:, 3]) if u.shape[1] > 3 else 0.0) + {"S2": 0.0, "N02": -0.01, "N04": 0.005}[grid.SHORT[strat]]
            + (0.01 if tf == "30m" else 0.0))
    sig = 1.7 / (1 + 1.3 * u[:, 1]) * (1 + 0.35 * (1 - u[:, 0]))
    whip0 = np.clip(0.06 + 0.42 * (1 - u[:, 1]) * (0.65 + 0.35 * (1 - u[:, 0])), 0.02, 0.8)
    bars_day = 96 if tf == "15m" else 48
    days = np.array([(NOW_MS - live_start) / DAY, 182.0, 28.0])
    p0 = 0.006 if tf == "15m" else 0.0085
    coinf = np.array([1.0, 1.05, 1.15, 1.1, 0.95, 0.9, 1.05])
    atr = ATR_PCT[tf]
    cost = 2 * (TAKER + SLIP) / (EXIT_K * atr) + FUND8 * 1.5                 # (E,) cost in R per trade
    rate = (days[:, None, None, None] * bars_day * p0 * EXIT_NF[None, :, None, None] * coinf[None, None, :, None]
            * sig[None, None, None, :])
    n = rng.poisson(rate).astype(np.float64)                                 # (W,E,7,C)
    g = (edge[None, None, None, :] + rng.normal(0, 0.03, (W, 1, 7, 1)) + rng.normal(0, 0.02, (W, E, 7, C))
         + 0.012 * (EXIT_K[None, :, None, None] - 2))
    x = EXIT_X[None, :, None, None]
    p = np.clip((1 + g) / (1 + x), 0.03, 0.97)
    wins = rng.binomial(n.astype(np.int64), p).astype(np.float64)
    costb = cost[None, :, None, None]
    aw = np.where(wins > 0, x * rng.uniform(0.9, 1.05, n.shape) - costb, np.nan)
    aw = np.where(np.arange(E)[None, :, None, None] == 0, rng.lognormal(0.5, 0.15, n.shape) - costb, aw)
    aw = np.where(wins > 0, aw, np.nan)
    al = np.where(n - wins > 0, rng.uniform(0.93, 1.03, n.shape) + costb, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_R = np.where(n > 0, (wins * np.nan_to_num(aw) - (n - wins) * np.nan_to_num(al)) / np.where(n > 0, n, 1), np.nan)
    mean_G = np.where(n > 0, mean_R + costb + rng.normal(0, 0.004, n.shape), np.nan)
    mdd = np.where(n > 0, np.sqrt(n) * 1.25 * rng.uniform(0.7, 1.4, n.shape) + np.maximum(0, -np.nan_to_num(mean_R)) * n * 0.55, 0.0)
    whip = np.clip(whip0[None, None, None, :] + rng.normal(0, 0.03, n.shape), 0.0, 0.95)
    opn = (rng.random((1, E, 7, C)) < 0.12).astype(np.float64).repeat(W, 0)
    nsig = n + opn + rng.poisson(n * 0.12)
    # pooled scope
    N = n.sum(2)
    Wn = wins.sum(2)
    with np.errstate(invalid="ignore", divide="ignore"):
        mR = np.where(N > 0, np.nansum(n * np.nan_to_num(mean_R), 2) / np.where(N > 0, N, 1), np.nan)
        mG = np.where(N > 0, np.nansum(n * np.nan_to_num(mean_G), 2) / np.where(N > 0, N, 1), np.nan)
        AW = np.where(Wn > 0, np.nansum(wins * np.nan_to_num(aw), 2) / np.where(Wn > 0, Wn, 1), np.nan)
        L_ = N - Wn
        AL = np.where(L_ > 0, np.nansum((n - wins) * np.nan_to_num(al), 2) / np.where(L_ > 0, L_, 1), np.nan)
        WH = np.where(nsig.sum(2) > 0, (whip * nsig).sum(2) / np.maximum(nsig.sum(2), 1), whip.mean(2))
    MDD = np.sqrt((mdd ** 2).sum(2)) * 1.15
    stats = np.full((W, E, S, C, 11), np.nan, np.float64)
    for k, (pool, per) in enumerate(((N, n), (Wn, wins), (mR, mean_R), (mG, mean_G), (MDD, mdd), (WH, whip),
                                     (AW, aw), (AL, al))):
        stats[:, :, 0, :, k] = pool
        stats[:, :, 1:, :, k] = per
    stats[:, :, 0, :, 9] = opn.sum(2)
    stats[:, :, 1:, :, 9] = opn
    stats[:, :, 0, :, 10] = nsig.sum(2)
    stats[:, :, 1:, :, 10] = nsig
    scale = 1.0 if tf == "15m" else 0.5
    min_n = np.array([[int(30 * scale) or 15, 8], [int(300 * scale), int(50 * scale)], [int(60 * scale), 12]], np.int32)
    # plateau: grid.plateau for every (window, exit, scope) at once (one matrix product instead of 312 calls)
    M = grid.neighbour_matrix(strat)
    nn = stats[..., 0].reshape(-1, C).T                                    # (C, W*E*S)
    mm = stats[..., 2].reshape(-1, C).T
    num = M @ np.where(nn >= 1, np.nan_to_num(mm), 0.0).astype(np.float32)
    den = M @ (nn >= 1).astype(np.float32)
    with np.errstate(invalid="ignore", divide="ignore"):
        sc = (num / den).T.reshape(W, E, S, C)
    need = np.where(np.arange(S)[None, :] == 0, min_n[:, :1], min_n[:, 1:])[:, None, :, None]    # (W,1,S,1)
    stats[..., 8] = np.where(stats[..., 0] >= need, sc, np.nan)
    luck = np.zeros((W, E, S), np.float32)
    for w in range(W):
        for e in range(E):
            for s in range(S):
                nn1 = stats[w, e, s, :, 0]
                med = float(np.median(nn1[nn1 > 0])) if (nn1 > 0).any() else 1.0
                luck[w, e, s] = -cost[e] + 2.9 * 1.25 * (EXIT_X[e] ** 0.5) / math.sqrt(max(med, 1.0)) * 0.7
    bounds = np.array([[live_start, NOW_MS], [NOW_MS - 182 * DAY, NOW_MS], [NOW_MS - 28 * DAY, NOW_MS]], np.int64)
    return {"stats": stats.astype(np.float32), "luck95": luck, "min_n": min_n, "bounds_ms": bounds,
            "generated_ms": np.int64(NOW_MS - 40_000)}


def fake_past(strat, tf, rng):
    EXIT_X, EXIT_K, EXIT_NF = _exit_arrays()
    C, u = _combo_shape(strat)
    P, S = len(PERIODS), len(grid.SCOPES)
    edge = 0.03 * np.sin(2.4 * u[:, 0] + 0.6) * np.cos(1.9 * u[:, 1] - 0.4) + 0.025 * (u[:, 2] - 0.5)
    years = np.array([1.0, 3.0, 2.75, 1 / 12, 1 / 12, 1 / 12])
    base = (700 if tf == "15m" else 420) * years
    n = rng.poisson(base[:, None, None, None] * EXIT_NF[None, :, None, None] * np.where(np.arange(S) == 0, 7, 1)[None, None, :, None]
                    * (1.7 / (1 + 1.3 * u[:, 1]))[None, None, None, :]).astype(np.float64)
    cost = 2 * (TAKER + SLIP) / (EXIT_K * ATR_PCT[tf])
    mean = (edge[None, None, None, :] - cost[None, :, None, None] + rng.normal(0, 0.05, (P, 1, S, 1))
            + rng.normal(0, 0.6, n.shape) / np.sqrt(np.maximum(n, 1)))
    x = EXIT_X[None, :, None, None]
    wr = np.clip((1 + mean + cost[None, :, None, None]) / (1 + x) + rng.normal(0, 0.02, n.shape), 0.02, 0.98)
    out = np.stack([n, np.where(n > 0, wr, np.nan), np.where(n > 0, mean, np.nan)], -1)
    out[3:, 1:] = np.nan                                     # crash months: only the house exit was computed
    return {"stats": out.astype(np.float32)}


# ---------------------------------------------------------------- the view log (CONTRACT 7.3)
VIEW_MEMOS = ("4시간 저항대 다시 시험, 거래량 줄어듦", "펀딩 과열이라 숏 쪽", "주말이라 얕게만", "어제 고점 돌파 실패",
              "<b>태그</b>도 글자로 보여야 합니다", "", "", "1시간 다이버전스", "CME 갭 메우기 기대", "발표 전이라 짧게",
              "지지선 세 번째 터치", "")
VIEW_RULES_KO = (
    "기준 가격 = 관점 시각 다음 15분봉의 시가",
    "방향: 4시간 · 24시간 · 48시간 뒤 15분 종가가 말한 방향으로 움직였으면 맞힘",
    "도달: 48시간 안에 15분봉이 가장 가까운 구간 끝을 건드렸나",
    "구간 바로 진입: 가장 가까운 구간 끝에 지정가 (메이커 0.02%)",
    "15분 종가 확인 진입: 구간을 건드린 뒤 15분 종가가 다시 그 끝의 진입 쪽에서 닫히면 시장가 (수수료 0.05% + 슬리피지 0.02%)",
    "손절: 적은 값, 없으면 가장 먼 구간에서 0.3% 밖 · 목표: 적은 값 (첫째에서 절반), 없으면 1R 절반 · 본전 · 2R",
    "들어간 뒤 48시간이면 정리 · 48시간 안에 못 들어가면 놓침 · 잔고 %는 20배, 두 분 규칙(증거금 20%)",
    "판정은 끝난 관점 30개부터: 방향 적중률이 50%보다 높고 (한쪽 이항검정 p < 0.05), 진입 방식의 평균 R > 0이며 주 단위 부트스트랩 하한도 > 0",
)
VIEW_COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
VIEW_COIN_P = (0.36, 0.24, 0.16, 0.09, 0.07, 0.04, 0.04)


def _binom_p(hit: int, n: int) -> float:
    """One-sided P(X >= hit) for X ~ Binomial(n, 1/2)."""
    return sum(math.comb(n, k) for k in range(hit, n + 1)) / 2 ** n


def _follow(rng, mode, view, zone_edge, stop, age_ms, reach_ms):
    """One follow mode's result (touch: a limit at the zone edge; confirm: a later close back on the trade side)."""
    out = {"status": "waiting", "entry_ms": None, "entry": None, "stop": None, "exit_ms": None, "R": None,
           "wallet20_pct": None, "legs_ko": ""}
    if reach_ms is None or (mode == "confirm" and rng.random() < 0.3):
        out["status"] = "missed" if age_ms >= 48 * HOUR else "waiting"
        return out
    entry_ms = reach_ms + (0 if mode == "touch" else int(rng.integers(1, 8)) * 15 * 60_000)
    if entry_ms > NOW_MS:
        return out
    side = view["side"]
    entry = zone_edge * (1 + side * (0 if mode == "touch" else float(rng.uniform(0.0005, 0.002))))
    dist = abs(entry - stop) / entry
    out.update(entry_ms=int(entry_ms), entry=_r(entry, 6), stop=_r(stop, 6))
    hold = float(rng.uniform(1, 40)) * HOUR
    if entry_ms + hold > NOW_MS:
        out["status"] = "open"
        out["legs_ko"] = "들어가 있음"
        return out
    u = rng.random()
    if u < 0.45:
        R, legs = -1.0 - (0.06 if mode == "confirm" else 0.03), "손절"
    elif u < 0.7:
        R, legs = 0.5 - 0.05, "절반 1R 익절 → 나머지 본전"
    elif u < 0.9:
        R, legs = 1.5 - 0.06, "절반 1R 익절 → 나머지 2R 익절"
    else:
        R, legs = float(rng.normal(0.1, 0.5)), "48시간 시간 정리"
    out.update(status="closed", exit_ms=int(entry_ms + hold), R=_r(R, 3), wallet20_pct=_r(R * dist * 4 * 100, 2),
               legs_ko=legs)
    return out


def fake_views(rng, n: int = 40) -> dict:
    views = []
    times = np.sort(rng.uniform(NOW_MS - 21 * DAY, NOW_MS - 20 * 60_000, n)).astype(np.int64)
    for i, t in enumerate(times, 1):
        t = int(t) // 60_000 * 60_000
        coin = str(rng.choice(VIEW_COINS, p=VIEW_COIN_P))
        side = 1 if rng.random() < 0.5 else -1
        px = PRICE[coin] * float(np.exp(rng.normal(0, 0.02)))
        step = px * float(rng.uniform(0.002, 0.005))
        dec = 1 if px > 1000 else 2 if px > 10 else 4
        rd = lambda x: round(x, dec)                                   # noqa: E731
        zones = {}
        for k, (lab, mult) in enumerate((("A", 1), ("B", 2), ("C", 3))):
            if lab != "B" and rng.random() < 0.35:
                zones[lab] = None
                continue
            near = px - side * mult * step
            width = 0.0 if lab == "C" and rng.random() < 0.5 else step * float(rng.uniform(0.15, 0.4))
            lo, hi = (near - width, near) if side > 0 else (near, near + width)
            zones[lab] = [rd(lo), rd(hi)]
        live = [z for z in zones.values() if z]
        nearest = max(z[1] for z in live) if side > 0 else min(z[0] for z in live)
        farthest = min(z[0] for z in live) if side > 0 else max(z[1] for z in live)
        given_stop = rng.random() < 0.7
        stop = rd(farthest * (1 - side * float(rng.uniform(0.003, 0.006)))) if given_stop else None
        stop_used = stop if stop is not None else farthest * (1 - side * 0.003)
        targets = [rd(px + side * 2 * step), rd(px + side * 4 * step)] if rng.random() < 0.5 else []
        age = NOW_MS - t
        cancelled = rng.random() < 0.05
        status = "cancelled" if cancelled else "done" if age >= 48 * HOUR else "watching"
        dirs = {}
        for hkey, hh in (("4h", 4), ("24h", 24), ("48h", 48)):
            dirs[hkey] = None if cancelled or age < hh * HOUR else _r(float(rng.normal(0.06, 0.55) * math.sqrt(hh / 4)), 2)
        reach_ms = None
        if not cancelled and rng.random() < 0.68:
            reach_ms = t + int(float(rng.uniform(0.25, 30)) * HOUR) // (15 * 60_000) * (15 * 60_000)
            if reach_ms > NOW_MS:
                reach_ms = None
        reached = None if cancelled or (reach_ms is None and age < 48 * HOUR) else reach_ms is not None
        view = {"id": i, "t_ms": t, "entered_ms": t + int(rng.integers(5, 90)) * 1000, "coin": coin, "side": side,
                "zones": zones, "stop": stop, "targets": targets, "memo": str(VIEW_MEMOS[i % len(VIEW_MEMOS)]),
                "status": status, "ref_price": _r(px, 6), "dir": dirs, "reached": reached, "reached_ms": reach_ms}
        if cancelled:
            view["follow"] = {m: {"status": "missed", "entry_ms": None, "entry": None, "stop": None, "exit_ms": None,
                                  "R": None, "wallet20_pct": None, "legs_ko": "취소됨"} for m in ("touch", "confirm")}
        else:
            view["follow"] = {m: _follow(rng, m, view, nearest, stop_used, age, reach_ms) for m in ("touch", "confirm")}
        views.append(view)
    views.reverse()                                                  # newest first
    live_views = [v for v in views if v["status"] != "cancelled"]
    done = [v for v in live_views if v["status"] == "done"]
    summ_dir = {}
    for hkey in ("4h", "24h", "48h"):
        vals = [v["dir"][hkey] for v in live_views if v["dir"][hkey] is not None]
        hit = sum(1 for x in vals if x > 0)
        summ_dir[hkey] = {"n": len(vals), "hit": hit, "rate": _r(hit / len(vals), 4) if vals else None,
                          "p": _r(_binom_p(hit, len(vals)), 4) if len(vals) >= 10 else None}
    reached = [v["reached"] for v in done if v["reached"] is not None]
    follow = {}
    for m in ("touch", "confirm"):
        fs = [v["follow"][m] for v in live_views]
        rs = [f["R"] for f in fs if f["status"] == "closed"]
        w = 1.0
        for f in fs:
            if f["status"] == "closed":
                w *= 1 + f["wallet20_pct"] / 100
        mean = float(np.mean(rs)) if rs else None
        follow[m] = {"n": len(fs), "entered": sum(1 for f in fs if f["entry_ms"] is not None),
                     "mean_R": _r(mean, 3) if rs else None,
                     "win_rate": _r(sum(1 for x in rs if x > 0) / len(rs), 4) if rs else None,
                     "sum_R": _r(float(np.sum(rs)), 3) if rs else 0.0,
                     "ci_low": _r(mean - 1.8 * float(np.std(rs)) / math.sqrt(len(rs)), 3) if len(rs) >= 5 else None,
                     "wallet20_pct": _r((w - 1) * 100, 2)}
    need = 30
    if len(done) < need:
        verdict = f"표본 부족 ({len(done)}/{need})"
    else:
        d24 = summ_dir["24h"]
        verdict = (f"방향 24시간 적중 {d24['rate'] * 100:.1f}% (p {d24['p']:.2f}) · 바로 진입 평균 "
                   f"{follow['touch']['mean_R']:+.3f}R · 확인 진입 평균 {follow['confirm']['mean_R']:+.3f}R: "
                   "아직 실력이라 말하기 어렵습니다").replace("-", "−")
    return {"generated_ms": NOW_MS, "rules_ko": list(VIEW_RULES_KO),
            "summary": {"n": len(live_views), "n_done": len(done), "need": need, "verdict_ko": verdict, "dir": summ_dir,
                        "reached_rate": _r(sum(reached) / len(reached), 4) if reached else None, "follow": follow},
            "views": views[:300]}


# ---------------------------------------------------------------- the other files
OURS_KO = ["실시간 거래 100건 이상", "평균 R (수수료 후) 0보다 큼", "운 기준선 위", "최대 낙폭 35% 이하", "파산 없음"]
STOP_RULES_KO = ["계좌 -20%: 새 진입 영구 정지", "하루 -5%: 그날 새 진입 정지", "5연패: 24시간 새 진입 쉼"]
CONFIRM_MIN, CONFIRM_MAX, CONFIRM_N = 28 * DAY, 56 * DAY, 20


def ours_checks(n, mR, dd_ratio, ruined, luck) -> list:
    dd = dd_ratio * 100
    return [{"name_ko": OURS_KO[0], "ok": n >= 100, "value_ko": f"{n}건"},
            {"name_ko": OURS_KO[1], "ok": bool(mR is not None and mR > 0),
             "value_ko": "—" if mR is None else f"{mR:+.3f}R".replace("-", "−")},
            {"name_ko": OURS_KO[2], "ok": bool(mR is not None and mR > luck),
             "value_ko": "—" if mR is None else f"{mR:+.3f}R (기준 {luck:+.3f}R)".replace("-", "−")},
            {"name_ko": OURS_KO[3], "ok": dd <= 35, "value_ko": f"{dd:.1f}%"},
            {"name_ko": OURS_KO[4], "ok": not ruined, "value_ko": "파산" if ruined else "없음"}]


WEEK = 7 * DAY
MONDAY0 = 4 * DAY             # 1970-01-05 00:00 UTC, a Monday (the engine's week blocks)


def flip_pools(accts) -> dict:
    """(tf, L) -> (mean R, sd R) of the coin-flip account's closed trades (the engine's judge._flip_pool)."""
    out = {}
    for a in accts:
        if a.spec["kind"] != "flip":
            continue
        for L in grid.LEVS:
            r = np.array([t["R"] for t in a.sims[L]["trades"] if t["status"] == "closed"], float)
            out[(a.spec["tf"], L)] = (float(r.mean()), float(r.std())) if len(r) >= 30 else (None, None)
    return out


def line_numbers(a, L, pools) -> dict:
    """CONTRACT 9.7: the numbers behind the engine's checks 1, 2 and 5 of one line: closed trades, mean R, the
    coin-flip 95% limit for that many trades (mean + 1.645 sd / sqrt(n) of the same timeframe's flips at the same
    leverage) and the week-block bootstrap 2.5% lower bound of the mean R (the engine's accounts.boot_low)."""
    closed = [t for t in a.sims[L]["trades"] if t["status"] == "closed"]
    n = len(closed)
    mean = sum(t["R"] for t in closed) / n if n else None
    mu, sd = pools.get((a.spec["tf"], L), (None, None))
    lim = mu + 1.645 * sd / math.sqrt(n) if mu is not None and n >= 2 else None
    low = None
    if n >= 10:
        wk = {}
        for t in closed:
            w = (t["entry_ms"] - MONDAY0) // WEEK
            k, s = wk.get(w, (0, 0.0))
            wk[w] = (k + 1, s + t["R"])
        arr = np.array(list(wk.values()), float)
        if len(arr) >= 2:
            idx = np.random.default_rng(0).integers(0, len(arr), size=(1000, len(arr)))
            low = float(np.percentile(arr[idx, 1].sum(1) / arr[idx, 0].sum(1), 2.5))
    return {"n": n, "mean_R": _r(mean, 4), "luck_lim": _r(lim, 4), "boot_low": _r(low, 4), "robust": robust_block(closed)}


def robust_block(closed) -> dict:
    """CONTRACT 9.10 "버티는 수익인가": does a line's profit hold up? The share of the profit in the 5 best trades, the
    first and second half of its closed trades (by exit time), how many coins made money, the longest losing streak,
    the worst KST day, and the engine's plain warning flags (the same rules and words as demobot/judge.robust)."""
    tr = sorted(closed, key=lambda t: t["exit_ms"])
    n = len(tr)
    pnl = sum(t["pnl"] for t in tr)
    top5 = sum(sorted((t["pnl"] for t in tr), reverse=True)[:5])
    share = top5 / pnl if pnl > 0 else None
    k = n // 2
    first, second = tr[:k], tr[k:]
    mean = lambda xs: sum(t["R"] for t in xs) / len(xs) if xs else None          # noqa: E731
    by_coin = {}
    for t in tr:
        by_coin[t["coin"]] = by_coin.get(t["coin"], 0.0) + t["pnl"]
    streak = worst = 0
    for t in tr:
        streak = streak + 1 if t["pnl"] < 0 else 0
        worst = max(worst, streak)
    days = {}
    for t in tr:
        d = datetime.datetime.fromtimestamp((t["exit_ms"] - 1) / 1000, datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y-%m-%d")
        days[d] = days.get(d, 0.0) + t["pnl"]
    wd = min(days.items(), key=lambda kv: kv[1]) if days else None
    f_R, s_R = mean(first), mean(second)
    up = sum(1 for v in by_coin.values() if v > 0)
    flags = []
    if share is not None and share >= 0.7:
        flags.append("수익의 70% 이상이 거래 5건에서 나옴")
    if f_R is not None and s_R is not None and s_R < f_R - 0.2 and s_R < 0:
        flags.append("뒤 절반이 앞 절반보다 크게 나쁨")
    if n and up <= 2:
        flags.append("번 코인이 7개 중 2개 이하")
    if worst >= 10:
        flags.append(f"연속 손실 {worst}번")
    return {"n": n, "pnl": _r(pnl, 2), "top5_share": _r(share, 4),
            "half": {"first_R": _r(f_R, 4), "second_R": _r(s_R, 4), "first_n": len(first), "second_n": len(second)},
            "coins_up": up, "coins_traded": len(by_coin), "max_lose_streak": worst,
            "worst_day": {"day": wd[0], "pnl": _r(wd[1], 2)} if wd else None, "flags_ko": flags}


def judge_rows(accts, rank_luck) -> tuple:
    rows, passed = [], 0
    pools = flip_pools(accts)
    for a in accts:
        s = a.spec
        luck = rank_luck.get((s["strategy"], s["tf"]), 0.0) if s["strategy"] else 0.0
        for L in grid.LEVS:
            ln = a.lines[str(L)]
            ours = ours_checks(ln["trades"], ln["mean_R"], ln["max_dd"], ln["ruined"], luck)
            dd = ln["max_dd"] * 100
            weeks_plus = int(a.rng.integers(0, 2))
            friend = {"pass": None, "checks": []}
            if s["kind"] != "flip":
                fchecks = [{"name_ko": "지난주 고른 설정으로 이번 주 +", "ok": ln["today_pnl"] > 0 and ln["pnl"] > 0,
                            "value_ko": ("+" if ln["pnl"] >= 0 else "−") + f"${abs(ln['pnl']):,.2f}"},
                           {"name_ko": "4주 연속 +", "ok": False, "value_ko": f"{weeks_plus}주 / 4주"},
                           {"name_ko": "최대 낙폭 30% 이하", "ok": dd <= 30, "value_ko": f"{dd:.1f}%"}]
                friend = {"pass": all(c["ok"] for c in fchecks), "checks": fchecks}
            ok = all(c["ok"] for c in ours)
            passed += ok
            sl = a.ssims[L]["line"]
            s_ok = all(c["ok"] for c in ours_checks(sl["trades"], sl["mean_R"], sl["max_dd"], sl["ruined"], luck))
            rows.append({"id": s["id"], "name": s["name"], "L": L, "ours": {"pass": ok, "checks": ours},
                         "friend": friend, "stops": {"pnl_pct": sl["pnl_pct"], "max_dd": sl["max_dd"], "ours_pass": s_ok},
                         "confirm": None, **line_numbers(a, L, pools)})
    return rows, passed


def _window(trades, start, at):
    """Stats of the trades entered at/after start and closed by `at` (the engine's judge._window)."""
    w0 = SEED_USD + sum(t["pnl"] for t in trades if t["status"] == "closed" and t["exit_ms"] <= start)
    win = sorted((t for t in trades if t["entry_ms"] >= start and t["status"] == "closed" and t["exit_ms"] <= at),
                 key=lambda t: t["exit_ms"])
    n = len(win)
    pnl = sum(t["pnl"] for t in win)
    W = peak = w0
    dd = 0.0
    for t in win:
        W += t["pnl"]
        peak = max(peak, W)
        dd = max(dd, 1 - W / peak) if peak > 0 else dd
    return {"n": n, "mean_R": _r(sum(t["R"] for t in win) / n, 3) if n else None, "pnl": _r(pnl, 2),
            "pnl_pct": _r(pnl / max(w0, 1e-9) * 100, 2), "max_dd": _r(dd, 4),
            "liqs": sum(1 for t in win if t["reason"] == "liq"), "ruins": sum(1 for t in win if t.get("ruin")),
            "_win": win}


def _verdict(w) -> tuple:
    why = []
    if w["n"] < CONFIRM_N:
        why.append(f"거래 {w['n']}건 (20건 필요)")
    if w["mean_R"] is None or w["mean_R"] <= 0:
        why.append("평균 R이 0 이하")
    if w["pnl"] <= 0:
        why.append("확인 기간 수익이 0 이하")
    if w["max_dd"] >= 0.30:
        why.append(f"낙폭 {w['max_dd'] * 100:.1f}% (30% 미만 필요)")
    if w["liqs"]:
        why.append(f"강제청산 {w['liqs']}번")
    if w["ruins"]:
        why.append(f"파산 {w['ruins']}번")
    return ("confirmed", "확인 기간 통과: 실전 후보") if not why else ("failed", "; ".join(why))


def confirmations(a, L, luck) -> list:
    """Replays one line's closes: the first close after which "우리 기준" passes starts a confirmation (next tick);
    it is decided by CONTRACT 8.1's end rule; a failed one may start again at the next pass. Every period, oldest
    first."""
    trades = a.sims[L]["trades"]
    closed = sorted((t for t in trades if t["status"] == "closed"), key=lambda t: t["exit_ms"])
    out, n, sumR, W, peak, dd, ruined, busy_until = [], 0, 0.0, SEED_USD, SEED_USD, 0.0, False, -1
    for t in closed:
        n += 1
        sumR += t["R"]
        W += t["pnl"]
        peak = max(peak, W)
        dd = max(dd, 1 - W / peak)
        ruined = ruined or bool(t.get("ruin"))
        tick = -(-t["exit_ms"] // M15) * M15 + M15
        if tick <= busy_until or tick > NOW_MS:
            continue
        if not all(c["ok"] for c in ours_checks(n, sumR / n, dd, ruined, luck)):
            continue
        start = tick
        at20 = sorted(x["exit_ms"] for x in trades if x["entry_ms"] >= start and x["status"] == "closed")
        due = start + CONFIRM_MIN
        if len([x for x in at20 if x <= due]) < CONFIRM_N:
            due = at20[CONFIRM_N - 1] if len(at20) >= CONFIRM_N and at20[CONFIRM_N - 1] <= start + CONFIRM_MAX \
                else start + CONFIRM_MAX
            due = -(-due // M15) * M15
        if due <= NOW_MS:
            w = _window(trades, start, due)
            status, why = _verdict(w)
            out.append({"start": start, "status": status, "decided": due, "w": w, "why": why})
            busy_until = due if status == "failed" else 2 ** 62
        else:
            w = _window(trades, start, NOW_MS)
            left = max(0.0, (start + CONFIRM_MIN - NOW_MS) / DAY)
            out.append({"start": start, "status": "confirming", "decided": None, "w": w,
                        "why": f"진행 중: {w['n']}/{CONFIRM_N}건, {left:.1f}일 남음"})
            busy_until = 2 ** 62
    return out


def confirm_item(a, L, c) -> dict:
    s, w = a.spec, c["w"]
    prog = 1.0 if c["status"] != "confirming" else min((NOW_MS - c["start"]) / CONFIRM_MIN, w["n"] / CONFIRM_N)
    return {"id": s["id"], "name": s["name"], "L": L, "status": c["status"], "start_ms": c["start"],
            "end_ms": c["decided"] or max(c["start"] + CONFIRM_MIN, NOW_MS), "min_end_ms": c["start"] + CONFIRM_MIN,
            "max_end_ms": c["start"] + CONFIRM_MAX, "decided_ms": c["decided"],
            "progress": _r(max(0.0, min(1.0, prog)), 4), "n": w["n"], "need_n": CONFIRM_N, "mean_R": w["mean_R"],
            "pnl": w["pnl"], "pnl_pct": w["pnl_pct"], "max_dd": w["max_dd"], "liqs": w["liqs"], "ruins": w["ruins"],
            "why_ko": c["why"]}


def line_costs(a, L, trades=None):
    """Measured entry cost of one line's trades (CONTRACT 8.3): the mean cost and the extra round trip over 2 bps."""
    meas = [t for t in (trades if trades is not None else a.sims[L]["trades"]) if t.get("cost_bps") is not None]
    if not meas:
        return None
    extra = [t["cost_bps"] - ASSUMED_BPS for t in meas]
    adj = sum(2 * x / 1e4 * t["notional"] for x, t in zip(extra, meas))
    return {"n": len(meas), "mean_extra_bps": _r(float(np.mean(extra)), 3),
            "mean_extra_R": _r(float(np.mean([x / 1e4 / t["_d"] for x, t in zip(extra, meas)])), 4),
            "mean_cost_bps": _r(float(np.mean([t["cost_bps"] for t in meas])), 3), "extra_cost": _r(adj, 2)}


COST_NOTES_KO = [
    "호가는 15분봉이 열리고 약 25~40초 뒤에 읽습니다 (실제 봇이 주문을 낼 때쯤). 호가 두께 때문에 드는 비용만 셉니다.",
    "엔진은 진입·청산마다 0.02%(2bp)의 미끄러짐을 가정합니다. '추가 비용'은 실제 호가로 잰 비용에서 이 2bp를 뺀 것입니다.",
    "청산할 때의 호가는 따로 재지 않고 진입과 같다고 보고 왕복으로 계산합니다.",
    "지정가 진입(비공개 매매법)은 호가 대신 그 봉이 지정가를 얼마나 넘어갔는지 봅니다. 1bp도 못 넘고 '닿기만' 한 경우는 "
    "실제로는 체결이 안 됐을 수 있습니다.",
]


def fake_costs(accts, cm) -> dict:
    coins, series = cm.snapshot()
    lines, maker = [], []
    for a in accts:
        for L in grid.LEVS:
            lc = line_costs(a, L)
            pnl = a.lines[str(L)]["pnl"]
            if lc:
                lines.append({"id": a.spec["id"], "name": a.spec["name"], "L": L, "n": lc["n"],
                              "mean_extra_bps": lc["mean_extra_bps"], "mean_extra_R": lc["mean_extra_R"],
                              "mean_cost_bps": lc["mean_cost_bps"], "pnl": pnl, "pnl_adj": _r(pnl - lc["extra_cost"], 2),
                              "pnl_adj_pct": _r((pnl - lc["extra_cost"]) / SEED_USD * 100, 2),
                              "extra_cost": lc["extra_cost"]})
            mk = [t for t in a.sims[L]["trades"] if t.get("maker")]
            if mk:
                touch = [t for t in mk if t["through_bps"] is not None and t["through_bps"] < 1.0]
                maker.append({"id": a.spec["id"], "name": a.spec["name"], "L": L, "n": len(mk), "touch_only": len(touch),
                              "touch_share": _r(len(touch) / len(mk), 4), "pnl": pnl,
                              "pnl_strict": _r(pnl - sum(t["pnl"] for t in touch), 2)})
    return {"generated_ms": NOW_MS, "since_ms": int(cm.since), "assumed_bps": ASSUMED_BPS, "sizes": list(SIZES),
            "coins": coins, "series": series, "lines": lines, "maker": maker, "notes_ko": list(COST_NOTES_KO)}


def fake_regime(accts, mk, rng) -> dict:
    def bucket(trades, key, vals):
        out = {}
        for v in vals:
            tt = [t for t in trades if t.get(key) == v and t["status"] == "closed"]
            out[v] = {"n": len(tt), "mean_R": _r(sum(t["R"] for t in tt) / len(tt), 3) if tt else None,
                      "pnl": _r(sum(t["pnl"] for t in tt), 2)}
        return out
    lines = []
    for a in accts:
        for L in grid.LEVS:
            tr = a.sims[L]["trades"]
            if any(t["status"] == "closed" for t in tr):
                lines.append({"id": a.spec["id"], "name": a.spec["name"], "L": L, "trend": bucket(tr, "trend", TRENDS),
                              "vol": bucket(tr, "vol", VOLS)})
    return {"generated_ms": NOW_MS, "labels_ko": {"trend": TREND_KO, "vol": VOL_KO}, "now": mk.now_rows(rng),
            "history": [{"coin": c, "points": mk.history[c][-800:]} for c in grid.COINS], "lines": lines}


# ---------------------------------------------------------------- analysis and 5-year vs now (CONTRACT 9.5, 9.6)
EXIT_REASON_KO = {"stop": "손절", "lock": "잠금 익절", "liq": "강제청산", "tp": "익절", "be": "본전", "time": "시간"}   # the engine's


def _bucket(trades) -> dict:
    n = len(trades)
    return {"n": n, "mean_R": _r(sum(t["R"] for t in trades) / n, 4) if n else None,
            "pnl": _r(sum(t["pnl"] for t in trades), 2), "win_rate": _r(sum(1 for t in trades if t["pnl"] > 0) / n, 4) if n else None}


def _kst_hw(t_ms):
    """(KST weekday Monday = 0, KST hour) of an entry time."""
    k = int(t_ms) + 9 * HOUR
    return (k // DAY + 3) % 7, (k % DAY) // HOUR


def _analysis_of(trades, per_tf=False) -> dict:
    """The CONTRACT 9.5 buckets of a list of closed trades (one account's 20x line, or a kind's)."""
    hw = [_kst_hw(t["entry_ms"]) for t in trades]
    hw_n = [[0] * 24 for _ in range(7)]
    hw_s = [[0.0] * 24 for _ in range(7)]
    for t, (d, hh) in zip(trades, hw):
        hw_n[d][hh] += 1
        hw_s[d][hh] += t["R"]
    return {"n": len(trades),
            "by_coin": {c: _bucket([t for t in trades if t["coin"] == c]) for c in grid.COINS},
            "by_side": {"long": _bucket([t for t in trades if t["side"] > 0]), "short": _bucket([t for t in trades if t["side"] < 0])},
            "by_hour": [_bucket([t for t, (_d, hh) in zip(trades, hw) if hh == k]) for k in range(24)],
            "by_weekday": [_bucket([t for t, (d, _h) in zip(trades, hw) if d == k]) for k in range(7)],
            "by_tf": {tf: _bucket([t for t in trades if t.get("_tf") == tf]) for tf in grid.TFS} if per_tf else {},
            "by_exit": {ko: _bucket([t for t in trades if t["reason"] == k]) for k, ko in EXIT_REASON_KO.items()},
            "hw_n": hw_n, "hw_R": [[_r(hw_s[d][hh] / hw_n[d][hh], 4) if hw_n[d][hh] else None for hh in range(24)] for d in range(7)]}


def fake_analysis(accts) -> dict:
    rows, by_kind = [], {}
    for a in accts:
        s = a.spec
        closed = [{**t, "_tf": s["tf"]} for t in a.sims[20]["trades"] if t["status"] == "closed"]
        by_kind.setdefault(s["kind"], []).extend(closed)
        rows.append({"id": s["id"], "name": s["name"], "kind": s["kind"], "tf": s["tf"], **_analysis_of(closed)})
    kinds = [{"kind": k, "kind_ko": KIND_KO.get(k, k), **_analysis_of(v, per_tf=True)} for k, v in by_kind.items()]
    return {"generated_ms": NOW_MS, "accounts": rows, "kinds": kinds}


def vs5y_note(live_n, gap) -> str:
    """The engine's words (demobot/extra.vs5y)."""
    if gap is None:
        return "거래가 아직 없음" if not live_n else "5년 시험 자료 없음"
    if live_n < 30:
        return f"거래 {live_n}건: 아직 비교하기 이름"
    if abs(gap) < 0.1:
        return "5년 시험과 비슷"
    return "5년 시험보다 좋음" if gap > 0 else "5년 시험보다 나쁨"


def fake_vs5y(accts, past) -> dict:
    rows = []
    for a in accts:
        s = a.spec
        if s["kind"] != "fixed":
            continue
        closed = [t for t in a.sims[20]["trades"] if t["status"] == "closed"]
        live = _bucket(closed)
        st = past[(s["strategy"], s["tf"])]["stats"]
        per = {}
        for pi, p in enumerate(PERIODS):
            n, wr, mR = (float(x) for x in st[pi, 0, 0, s["combo"]])
            ok = math.isfinite(n) and n > 0
            per[p] = {"n": int(n) if ok else 0, "mean_R": _r(mR, 4) if ok else None, "win_rate": _r(wr, 4) if ok else None}
        ref = per["2024-26"]["mean_R"]
        gap = live["mean_R"] - ref if live["mean_R"] is not None and ref is not None else None
        rows.append({"id": s["id"], "name": s["name"], "strategy": s["strategy"], "tf": s["tf"], "combo": s["combo"],
                     "exit": 0, "setting_ko": a.setting_ko, "exit_ko": HOUSE_KO,
                     "live": {"n": live["n"], "mean_R": live["mean_R"], "win_rate": live["win_rate"]}, "past": per,
                     "gap_R": _r(gap, 4), "note_ko": vs5y_note(live["n"], gap)})
    return {"generated_ms": NOW_MS, "rows": rows}


# ---------------------------------------------------------------- the weekly review (CONTRACT 8.10)
def _ok_timeline(a, L, luck):
    """(close times, "우리 기준" checks passed after each close) of one plain line."""
    closed = sorted((t for t in a.sims[L]["trades"] if t["status"] == "closed"), key=lambda t: t["exit_ms"])
    ts, oks = [], []
    n, sumR, W, peak, dd, ruined = 0, 0.0, SEED_USD, SEED_USD, 0.0, False
    for t in closed:
        n += 1
        sumR += t["R"]
        W += t["pnl"]
        peak = max(peak, W)
        dd = max(dd, 1 - W / peak)
        ruined = ruined or bool(t.get("ruin"))
        ts.append(t["exit_ms"])
        oks.append(sum(c["ok"] for c in ours_checks(n, sumR / n, dd, ruined, luck)))
    return ts, oks


def _ok_at(tl, t):
    ts, oks = tl
    i = bisect.bisect_right(ts, t) - 1
    return oks[i] if i >= 0 else sum(c["ok"] for c in ours_checks(0, None, 0.0, False, 0.0))


def _wk(t_ms):
    return _kst(t_ms)[:5]


def fake_review(accts, confirm, rank_luck, mk, views, n_weeks=3) -> dict:
    """The current week so far plus finished weeks (KST Monday 00:00 to Sunday 24:00), newest first."""
    cur = (NOW_MS + 9 * HOUR - 4 * DAY) // (7 * DAY) * (7 * DAY) + 4 * DAY - 9 * HOUR   # this KST Monday 00:00
    lines = [(a, L) for a in accts for L in grid.LEVS]
    tl = {}
    for a, L in lines:
        luck = rank_luck.get((a.spec["strategy"], a.spec["tf"]), 0.0) if a.spec["strategy"] else 0.0
        tl[(a.spec["id"], L)] = _ok_timeline(a, L, luck)
    weeks = []
    for k in range(n_weeks):
        ws = cur - k * 7 * DAY
        we = ws + 7 * DAY
        upto = min(we, NOW_MS)
        final = we <= NOW_MS
        rows = []
        for a, L in lines:
            pl = sum(t["pnl"] for t in a.sims[L]["trades"] if t["status"] == "closed" and ws <= t["exit_ms"] < upto)
            sp = sum(t["pnl"] for t in a.ssims[L]["trades"] if t["status"] == "closed" and ws <= t["exit_ms"] < upto)
            meas = [t for t in a.sims[L]["trades"] if t.get("cost_bps") is not None and ws <= t["entry_ms"] < upto]
            extra = sum(2 * (t["cost_bps"] - ASSUMED_BPS) / 1e4 * t["notional"] for t in meas)
            n = sum(1 for t in a.sims[L]["trades"] if t["status"] == "closed" and ws <= t["exit_ms"] < upto)
            key = (a.spec["id"], L)
            rows.append({"a": a, "L": L, "pnl": pl, "stop_pnl": sp, "extra": extra, "n": n,
                         "ok_from": _ok_at(tl[key], ws), "ok_to": _ok_at(tl[key], upto)})
        ref = lambda r: {"id": r["a"].spec["id"], "name": r["a"].spec["name"], "L": r["L"]}   # noqa: E731
        by_pnl = sorted(rows, key=lambda r: r["pnl"], reverse=True)
        acct_pnl = {}
        for r in rows:
            acct_pnl[r["a"].spec["id"]] = acct_pnl.get(r["a"].spec["id"], 0.0) + r["pnl"]
        by_kind = []
        for kind, ko in KIND_KO.items():
            ks = [r["pnl"] / SEED_USD * 100 for r in rows if r["a"].spec["kind"] == kind]
            if ks:
                by_kind.append({"kind": kind, "kind_ko": ko, "mean_pnl_pct": _r(float(np.mean(ks)), 2)})
        closer = sorted((r for r in rows if r["ok_to"] > r["ok_from"]), key=lambda r: (r["ok_from"] - r["ok_to"], -r["ok_to"]))
        further = sorted((r for r in rows if r["ok_to"] < r["ok_from"]), key=lambda r: (r["ok_to"] - r["ok_from"], r["ok_to"]))
        conf_at = [c for c in confirm if c["start_ms"] < upto and (c["decided_ms"] is None or c["decided_ms"] >= upto)]
        cand_at = [c for c in confirm if c["status"] == "confirmed" and c["decided_ms"] is not None and c["decided_ms"] < upto]
        new_cands = [c for c in cand_at if c["decided_ms"] >= ws]
        failed_in = [c for c in confirm if c["status"] == "failed" and c["decided_ms"] is not None and ws <= c["decided_ms"] < upto]
        diffs = sorted(((r["stop_pnl"] - r["pnl"]) / SEED_USD * 100, i) for i, r in enumerate(rows))
        saved = [{**ref(rows[i]), "diff_pct": _r(d, 2)} for d, i in diffs[::-1] if d > 0][:3]
        cost = [{**ref(rows[i]), "diff_pct": _r(d, 2)} for d, i in diffs if d < 0][:3]
        net = float(np.mean([d for d, _i in diffs])) if diffs else 0.0
        eaten = sorted(((r["extra"] / r["pnl"], i) for i, r in enumerate(rows) if r["pnl"] > 0 and r["extra"] > 0),
                       reverse=True)[:3]
        meas_all = [t["cost_bps"] for a in accts for L in grid.LEVS for t in a.sims[L]["trades"]
                    if t.get("cost_bps") is not None and ws <= t["entry_ms"] < upto]
        i0, i1 = max(0, mk.idx(ws)), max(1, min(len(mk.ts), mk.idx(upto)))
        regime = []
        for coin in grid.COINS:
            seg = mk.trend[coin][i0:i1]
            share = {tr: _r(float(np.mean(seg == j)), 3) if seg.size else 0.0 for j, tr in enumerate(TRENDS)}
            regime.append({"coin": coin, "trend": TRENDS[mk.trend[coin][i1 - 1]], "vol": VOLS[mk.vol[coin][i1 - 1]],
                           "share": share})
        vw = [v for v in views if ws <= v["t_ms"] < upto and v["status"] != "cancelled"]
        d24 = [v["dir"]["24h"] for v in vw if v["dir"]["24h"] is not None]
        trades = sum(r["n"] for r in rows)
        up = sum(1 for v in acct_pnl.values() if v > 0)
        down = sum(1 for v in acct_pnl.values() if v < 0)
        passed = sum(1 for r in rows if r["ok_to"] == len(OURS_KO))
        b, w = by_pnl[0], by_pnl[-1]
        this = "이번 주" if not final else "이 주"
        summary = [f"{this} 닫힌 거래 {trades:,}건, 오른 계좌 {up}개 · 내린 계좌 {down}개입니다.",
                   f"가장 잘 된 줄은 {b['a'].spec['name']} {b['L']}배 ({b['pnl'] / SEED_USD * 100:+.1f}%), 가장 안 된 줄은 "
                   f"{w['a'].spec['name']} {w['L']}배 ({w['pnl'] / SEED_USD * 100:+.1f}%)입니다.",
                   f"주말 기준 우리 기준 통과 {passed}줄, 확인 기간 {len(conf_at)}줄, 실전 후보 {len(cand_at)}줄입니다."
                   if final else f"지금 우리 기준 통과 {passed}줄, 확인 기간 {len(conf_at)}줄, 실전 후보 {len(cand_at)}줄입니다.",
                   f"정지 규칙을 썼다면 줄마다 평균 {abs(net):.1f}%p " + ("덜 잃었습니다." if net > 0 else "더 나빴습니다.")]
        n_tr = {tr: sum(1 for x in regime if x["trend"] == tr) for tr in TRENDS}
        summary.append(f"시장은 코인 7개 중 상승 추세 {n_tr['up']}개, 하락 추세 {n_tr['down']}개, 횡보 {n_tr['range']}개로 "
                       + ("주를 마쳤습니다." if final else "지나고 있습니다."))
        if vw and d24:
            summary.append(f"관점은 {len(vw)}개를 적었고, 24시간 방향은 {len(d24)}개 중 {sum(1 for x in d24 if x > 0)}개가 맞았습니다.")
        elif vw:
            summary.append(f"관점은 {len(vw)}개를 적었고, 아직 24시간이 지난 것은 없습니다.")
        summary = [x.replace("-", "−") for x in summary]
        decide = []
        for c in new_cands:
            decide.append(f"{c['name']} {c['L']}배가 실전 후보가 됐습니다: 실제 돈을 쓸지 두 분이 정할 차례입니다 "
                          "(정하기 전까지는 실전 금지).")
        for c in failed_in[:2]:
            decide.append(f"{c['name']} {c['L']}배의 확인 기간이 실패했습니다 ({c['why_ko']}). 운으로 통과했을 수 있으니 "
                          "설정을 믿을지 다시 볼 것.")
        if eaten and eaten[0][0] > 0.15:
            r = rows[eaten[0][1]]
            decide.append(f"{r['a'].spec['name']} {r['L']}배는 번 돈의 {eaten[0][0] * 100:.0f}%를 실제 호가 비용이 먹었습니다: "
                          "큰 배수에서 비용을 확인할 것.")
        weeks.append({"week_ko": f"{_wk(ws)}~{_wk(we - 1)}", "start_ms": int(ws), "end_ms": int(we), "final": final,
                      "numbers": {"trades": trades, "accounts_up": up, "accounts_down": down,
                                  "best": [{**ref(r), "pnl_pct": _r(r["pnl"] / SEED_USD * 100, 2)} for r in by_pnl[:3]],
                                  "worst": [{**ref(r), "pnl_pct": _r(r["pnl"] / SEED_USD * 100, 2)} for r in by_pnl[::-1][:3]],
                                  "by_kind": by_kind},
                      "judge": {"passed": passed, "confirming": len(conf_at), "candidates": len(cand_at),
                                "closer": [{**ref(r), "ok_from": r["ok_from"], "ok_to": r["ok_to"]} for r in closer[:5]],
                                "further": [{**ref(r), "ok_from": r["ok_from"], "ok_to": r["ok_to"]} for r in further[:5]]},
                      "stops": {"saved": saved, "cost": cost, "net_pct": _r(net, 2)},
                      "costs": {"median_entry_bps": _r(float(np.median(meas_all)), 3) if meas_all else None,
                                "assumed_bps": ASSUMED_BPS,
                                "eaten": [{**ref(rows[i]), "share": _r(sh, 4)} for sh, i in eaten]},
                      "regime": regime,
                      "views": {"n": len(vw), "done": sum(1 for v in vw if v["status"] == "done"),
                                "dir24_rate": _r(sum(1 for x in d24 if x > 0) / len(d24), 4) if d24 else None},
                      "decide_ko": decide, "summary_ko": summary})
    return {"generated_ms": NOW_MS, "weeks": weeks}


# ---------------------------------------------------------------- the Telegram history (CONTRACT 8.11)
def _px(x):
    a = abs(x)
    return f"{x:,.{5 if a < 1 else 4 if a < 10 else 2 if a < 1000 else 1}f}"


def fake_telegram(accts, confirm, home, views, review, rng) -> dict:
    """About 60 rendered messages of the last days, newest first (the text exactly as a message would read)."""
    items = []
    TG = ("adaptive", "friend")
    tg_accts = [a for a in accts if a.spec["kind"] in TG or (a.spec["kind"] == "fixed" and a.spec["sub"] == "friend")]
    events = {}
    for a in tg_accts:
        for t in a.sims[20]["trades"]:
            for when, what in ((t["entry_ms"], "open"), (t["exit_ms"], "close")):
                if when and NOW_MS - 3 * DAY <= when <= NOW_MS:
                    events.setdefault(when // M15 * M15, []).append((what, a, t))
    for tick in sorted(events)[-30:]:
        ev = events[tick]
        opens = [x for x in ev if x[0] == "open"]
        closes = [x for x in ev if x[0] == "close"]
        out = [f"[데모 랩] {_kst(tick)} 봉 · 들어감 {len(opens)} · 나감 {len(closes)}"]
        for _w, a, t in opens[:4]:
            out.append(f"▲ {a.spec['name']}: {coin_ko(t['coin'])} {'롱' if t['side'] > 0 else '숏'} {_px(t['entry'])} "
                       f"({t['setting_ko']} · {t['exit_ko']})")
        for _w, a, t in closes[:4]:
            by = [(L, next((x["pnl"] for x in a.sims[L]["trades"] if x["signal_ms"] == t["signal_ms"] and x["coin"] == t["coin"]), None))
                  for L in grid.LEVS]
            pnl_by = " · ".join(f"{L}배 {'+' if p >= 0 else '-'}${abs(p):,.2f}" for L, p in by if p is not None)
            out.append(f"▼ {a.spec['name']}: {coin_ko(t['coin'])} {_px(t['entry'])} → {_px(t['exit'])} "
                       f"{ {'stop': '손절', 'lock': '익절 잠금', 'tp': '익절', 'liq': '강제청산', 'time': '시간 청산'}.get(t['reason'], t['reason']) } "
                       f"{t['R']:+.2f}R ({pnl_by})".replace("-", "−"))
        if len(ev) > 8:
            out.append(f"… 외 {len(ev) - 8}건은 대시보드에서")
        items.append({"ts_ms": int(tick + 35_000), "kind": "tick", "text": "\n".join(out)})
    sw = sorted(((d, a) for a in accts for d in a.decisions[:1] if NOW_MS - 3 * DAY <= d["t_ms"]),
                key=lambda x: x[0]["t_ms"], reverse=True)[:6]
    for d, a in sw:
        if True:
                items.append({"ts_ms": int(d["t_ms"] + 36_000), "kind": "switch", "text":
                              f"[데모 랩] 설정 교체: {a.spec['name']}\n"
                              f"{'전체 코인' if d['coin'] == 'ALL' else coin_ko(d['coin'])}"
                              f"{'' if d['L'] is None else ' · ' + str(d['L']) + '배'}: {d['from_ko']} → {d['to_ko']}\n"
                              f"이유: {d['why_ko']}"})
    for k in range(3):
        day = (NOW_MS + 9 * HOUR) // DAY * DAY - 9 * HOUR - k * DAY          # a KST midnight
        ts = day + 9 * HOUR if day + 9 * HOUR <= NOW_MS else day + 9 * HOUR - DAY   # its 09:00 KST
        b = home["best"][0]
        w = home["worst"][0]
        items.append({"ts_ms": int(ts + 4_000), "kind": "daily", "text":
                      f"[데모 랩] 하루 요약 {_kst(ts)[:5]}\n실시간 {home['live_days'] - k:.1f}일째\n"
                      f"잘 된 줄: {b['name']} {b['L']}배 {b['pnl_pct']:+.1f}%\n안 된 줄: {w['name']} {w['L']}배 {w['pnl_pct']:+.1f}%\n"
                      f"우리 기준 통과 {home['totals']['passed']}줄 · 확인 기간 {home['totals']['confirming']}줄 · "
                      f"실전 후보 {home['totals']['candidates']}줄\n"
                      f"실제 진입 비용 중간값 {home['costs_now']['median_entry_bps'] or 0:.1f}bp (가정 2bp)".replace("-", "−")})
    items.append({"ts_ms": NOW_MS - 2 * HOUR + 50_000, "kind": "warn",
                  "text": "[데모 랩] 경고 · 자료\nXRPUSD 15분봉 1개가 늦게 왔습니다. 다시 받았고 계산은 그대로입니다."})
    items.append({"ts_ms": NOW_MS - 30 * HOUR, "kind": "warn",
                  "text": "[데모 랩] 경고 · 순위표\n순위표가 3시간째 새로 쓰이지 않았습니다 (마지막 실행 실패)."})
    items.append({"ts_ms": NOW_MS - 29 * HOUR, "kind": "warn_clear",
                  "text": "[데모 랩] 정상으로 돌아옴 · 순위표\n순위표가 다시 새로 쓰였습니다."})
    for c in confirm:
        if c["decided_ms"] and NOW_MS - 14 * DAY <= c["decided_ms"] <= NOW_MS:
            res = "실전 후보 (확인 기간 통과)" if c["status"] == "confirmed" else f"실패 ({c['why_ko']})"
            items.append({"ts_ms": int(c["decided_ms"] + 40_000), "kind": "confirm_done", "text":
                          f"[데모 랩] 확인 기간 끝: {c['name']} {c['L']}배\n결과: {res}\n"
                          f"기간 {_kst(c['start_ms'])[:5]}~{_kst(c['decided_ms'])[:5]} · 거래 {c['n']}건 · 평균 "
                          f"{(c['mean_R'] or 0):+.3f}R · 손익 {c['pnl_pct']:+.1f}% · 최대 낙폭 {c['max_dd'] * 100:.1f}%".replace("-", "−")})
        if c["status"] == "confirming" and NOW_MS - 30 * DAY <= c["start_ms"]:
            items.append({"ts_ms": int(c["start_ms"] + 40_000), "kind": "pass", "text":
                          f"[데모 랩] 우리 기준 통과: {c['name']} {c['L']}배\n지금부터 확인 기간입니다 "
                          f"(가장 빨리 {_kst(c['min_end_ms'])[:5]}에 끝, 거래 20건 이상 필요).\n실전은 여전히 금지입니다."})
    for v in views[:6] + [x for x in views[6:] if "<" in x["memo"]][:1]:
        if v["status"] == "cancelled":
            continue
        z = " · ".join(f"{k} {_px(x[0])}~{_px(x[1])}" for k, x in v["zones"].items() if x)
        memo = f"\n메모: {v['memo']}" if v["memo"] else ""
        items.append({"ts_ms": int(v["entered_ms"] + 2_000), "kind": "view_ack", "text":
                      f"[데모 랩] 관점 #{v['id']} 받음: {coin_ko(v['coin'])} {'롱' if v['side'] > 0 else '숏'} · {z}"
                      + (f" · 손절 {_px(v['stop'])}" if v["stop"] else "") + memo})
    for v in [x for x in views if x["status"] == "done"][:2]:
        d = v["dir"]
        items.append({"ts_ms": int(v["t_ms"] + 48 * HOUR + 60_000), "kind": "view_done", "text":
                      f"[데모 랩] 관점 #{v['id']} 끝 ({coin_ko(v['coin'])} {'롱' if v['side'] > 0 else '숏'})\n"
                      f"방향: 4시간 {d['4h'] or 0:+.2f}% · 24시간 {d['24h'] or 0:+.2f}% · 48시간 {d['48h'] or 0:+.2f}%\n"
                      f"구간 도달: {'예' if v['reached'] else '아니오'}".replace("-", "−")})
    items.append({"ts_ms": NOW_MS - 7 * HOUR, "kind": "view_err", "text":
                  "[데모 랩] 이해하지 못했습니다: 구간(A/B/C)이 하나도 없습니다.\n예: 관점 BTC 숏 A 84750-84840 손절 85600"})
    items.append({"ts_ms": NOW_MS - 6 * HOUR, "kind": "view_list", "text":
                  "[데모 랩] 최근 관점 10개\n" + "\n".join(
                      f"#{v['id']} {_kst(v['t_ms'])} {coin_ko(v['coin'])} {'롱' if v['side'] > 0 else '숏'} · "
                      f"{ {'watching': '지켜보는 중', 'done': '끝남', 'cancelled': '취소'}[v['status']] }" for v in views[:10])})
    fin = [w for w in review["weeks"] if w["final"]]
    if fin:
        w = fin[0]
        items.append({"ts_ms": int(w["end_ms"] + 9 * HOUR + 30_000), "kind": "weekly", "text":
                      f"[데모 랩] 주간 회의록 {w['week_ko']}\n" + "\n".join(w["summary_ko"])
                      + ("\n정할 것:\n" + "\n".join("· " + x for x in w["decide_ko"]) if w["decide_ko"] else "\n정할 것: 없음")})
    items = [x for x in items if x["ts_ms"] <= NOW_MS + 60_000]
    items.sort(key=lambda x: x["ts_ms"], reverse=True)
    items = items[:60]
    for i, x in enumerate(items):
        x["id"] = 5000 + len(items) - i
        x["status"] = "queued" if i < 1 else "error" if i == 17 else "sent"
    return {"generated_ms": NOW_MS, "items": [{"id": x["id"], "ts_ms": x["ts_ms"], "kind": x["kind"],
                                              "status": x["status"], "text": x["text"]} for x in items[:300]]}


def build(outdir: str, seed: int = 7, past5y_dir=None, phase: str = "live", empty: bool = False,
          now_ms: int = FIXED_NOW_MS, views: int = 40) -> dict:
    """Write the fake snapshot folder; returns a few facts about it (for tests). now_ms: the fake 'now' (rounded down
    to 15 minutes); the default is a fixed date so the files are the same on every run."""
    global NOW_MS
    NOW_MS = int(now_ms) // (15 * 60_000) * (15 * 60_000)
    rng = np.random.default_rng(seed)
    prng = np.random.default_rng(seed + 1)          # the 5-year files: their own stream, so writing them changes nothing else
    os.makedirs(outdir, exist_ok=True)
    live_start = NOW_MS - int(LIVE_DAYS * DAY) // (15 * 60_000) * (15 * 60_000)
    status = {
        "generated_ms": NOW_MS, "version": "demobot-1", "phase": phase, "live_start_ms": live_start,
        "history_start_ms": live_start - 182 * DAY,
        "last_bar_ms": {"15m": NOW_MS - 15 * 60_000, "30m": NOW_MS - 45 * 60_000}, "last_tick_ms": NOW_MS - 20_000,
        "tick_seconds": 41.7, "next_tick_ms": NOW_MS + 15 * 60_000 - 20_000, "data_ok": True,
        "data_issues": [f"XRPUSD 15분봉 1개 늦게 도착 ({_kst(NOW_MS - 2 * HOUR)}, 다시 받음)"], "errors": [],
        "coins": list(grid.COINS), "tfs": list(grid.TFS), "leverages": list(grid.LEVS), "seed": SEED_USD,
        "costs": {"taker": TAKER, "slippage": SLIP, "funding_8h_ranking": FUND8, "funding_accounts": "real"},
        "counts": {"settings": sum(grid.NCOMBO.values()), "players": sum(grid.NCOMBO.values()) * 14,
                   "cells_open": 214, "cells_total": sum(grid.NCOMBO.values()) * grid.NEXIT * 2 * len(grid.COINS),
                   "signals_24h": 18_442},
        "proc": {"rss_mb": 412.6, "cpu_pct": 11.8}, "db_mb": 1_284.3, "disk_free_mb": 31_870.0,
        "telegram": {"configured": True, "queued": 0, "last_ok_ms": NOW_MS - 15 * 60_000 + 30_000, "last_error": None},
        "deadman": {"configured": True, "last_ok_ms": NOW_MS - 20_000, "last_error": None},
        # the shared server (CONTRACT 8.13): the rule bot's machine; a field the engine cannot read is null
        "server": {"mem_total_mb": 7936.0, "mem_avail_mb": 3184.6, "swap_used_mb": 18.0, "load": [0.84, 0.71, 0.66],
                   "cpus": 4, "rule_bot": [
                       {"unit": "paperbot-live3.service", "active": "active", "mem_mb": 618.2},
                       {"unit": "paperbot-dash.service", "active": "active", "mem_mb": 104.5},
                       {"unit": "paperbot-liq.service", "active": "active", "mem_mb": 87.9},
                       {"unit": "paperbot-executor.service", "active": "inactive", "mem_mb": None}]}}
    if phase == "warm":
        status.update({"live_start_ms": None, "last_tick_ms": None, "next_tick_ms": None})
    _write_json(os.path.join(outdir, "status.json"), status)
    if empty:
        return {"accounts": 0}

    # ranks first (the home leaders and the judge's luck lines read them)
    leaders, rank_luck, files, past = [], {}, [], {}
    for strat in grid.STRATS:
        for tf in grid.TFS:
            z = fake_rank(strat, tf, rng, live_start)
            name = f"rank_{strat}_{tf}.npz"
            _write_npz(os.path.join(outdir, name), **z)
            files.append(name)
            w, e = grid.WINDOWS.index("26w"), 0
            cell = z["stats"][w, e, 0].astype(float)
            c = grid.top(cell[:, 8])[0]
            luck = float(z["luck95"][w, e, 0])
            rank_luck[(strat, tf)] = round(luck, 3)
            n = int(cell[c, 0])
            mR = float(cell[c, 2])
            leaders.append({"strategy": strat, "tf": tf, "window": "26w", "exit": "house", "label": _label(strat, c),
                            "n": n, "mean_R": _r(mR, 4), "win_rate": _r(cell[c, 1] / n, 4) if n else None,
                            "luck95": _r(luck, 4), "beats_luck": bool(mR > luck)})
            past[(strat, tf)] = fake_past(strat, tf, prng)      # always made (vs5y.json reads it); same stream
            if past5y_dir:
                os.makedirs(past5y_dir, exist_ok=True)
                _write_npz(os.path.join(past5y_dir, f"past5y_{strat}_{tf}.npz"), **past[(strat, tf)])
    _write_json(os.path.join(outdir, "rank_meta.json"), {
        "generated_ms": NOW_MS - 40_000, "build_seconds": 6.4, "files": files, "windows": list(grid.WINDOWS),
        "exits": list(grid.EXITS), "scopes": list(grid.SCOPES), "players": status["counts"]["players"],
        "luck_draws": 2000})

    # the market (bars + regimes) and the order book costs: their own streams
    mk = Market(np.random.default_rng(seed + 3), live_start)
    mk.write(outdir)
    cm = CostModel(np.random.default_rng(seed + 4), mk, live_start + int(COST_LOG_DAYS * DAY) // M15 * M15)
    accts = [_Acct(sp, rng, live_start, mk, cm) for sp in account_specs()]
    rows = [a.row() for a in accts]
    _write_json(os.path.join(outdir, "accounts.json"), {"generated_ms": NOW_MS, "live_start_ms": live_start,
                                                        "accounts": rows})
    from . import fake_live                              # round 4 part A files (CONTRACT 9.2-9.4, 9.9)
    for a in accts:
        _write_json(os.path.join(outdir, "acct", a.spec["id"] + ".json"), {**a.detail(), "daily": fake_live.acct_daily(a)})
    all_trades = [{**t, "account": a.spec["id"], "name": a.spec["name"]} for a in accts for t in a.trades]
    all_trades.sort(key=lambda t: (t["exit_ms"] or NOW_MS + 1, t["entry_ms"]), reverse=True)
    _write_json(os.path.join(outdir, "trades.json"), {"generated_ms": NOW_MS, "trades": all_trades[:300]})

    # the judgment, the confirmation periods (8.1) and the stop-rule lines (8.2)
    jrows, passed = judge_rows(accts, rank_luck)
    byid = {a.spec["id"]: a for a in accts}
    confirm, cands = [], []
    for row in jrows:
        a = byid[row["id"]]
        luck = rank_luck.get((a.spec["strategy"], a.spec["tf"]), 0.0) if a.spec["strategy"] else 0.0
        periods = confirmations(a, row["L"], luck)
        if not periods:
            continue
        c = periods[-1]
        item = confirm_item(a, row["L"], c)
        confirm.append(item)
        row["confirm"] = {"status": item["status"], "start_ms": item["start_ms"], "end_ms": item["end_ms"]}
        if c["status"] == "confirmed":
            lc = line_costs(a, row["L"], c["w"]["_win"])
            w = c["w"]
            cands.append({"id": item["id"], "name": item["name"], "L": item["L"], "decided_ms": item["decided_ms"],
                          "window": {"n": w["n"], "mean_R": w["mean_R"], "pnl_pct": w["pnl_pct"], "max_dd": w["max_dd"]},
                          "costs": {"entry_bps": lc["mean_cost_bps"] if lc else None,
                                    "roundtrip_pct_of_pnl": _r(lc["extra_cost"] / w["pnl"] * 100, 2)
                                    if lc and w["pnl"] > 0 else None},
                          "stops": {"pnl_pct": row["stops"]["pnl_pct"], "max_dd": row["stops"]["max_dd"]}})
    order = {"confirmed": 0, "confirming": 1, "failed": 2}
    confirm.sort(key=lambda x: (order[x["status"]], -x["start_ms"]))
    n_conf = sum(1 for c in confirm if c["status"] == "confirming")
    if cands:
        verdict = (f"실전 금지: 실전 후보 {len(cands)}줄이 나왔지만 실제 돈은 두 분이 정합니다"
                   + (f" · 확인 기간 {n_conf}줄 진행 중" if n_conf else ""))
    elif n_conf:
        verdict = f"실전 금지: 확인 기간 {n_conf}줄 진행 중 (우리 기준 통과 {passed}줄)"
    elif passed:
        verdict = f"실전 금지: 우리 기준 통과 {passed}줄, 확인 기간을 거쳐야 실전 후보가 됩니다"
    else:
        verdict = "실전 금지: 아직 통과한 계좌가 없습니다"
    n_lines = len(jrows)
    _write_json(os.path.join(outdir, "judge.json"), {
        "generated_ms": NOW_MS, "verdict_ko": verdict,
        "rules_ko": {"ours": list(OURS_KO),
                     "friend": ["지난 26주에 수익 + 낙폭 최소 설정을 일주일 돌려 +", "그렇게 4주 연속 +",
                                "최대 낙폭 30% 이하"]},
        "stop_rules_ko": list(STOP_RULES_KO), "lines_judged": n_lines,
        "multi_note_ko": (f"{n_lines}줄을 한꺼번에 보면 실력이 없어도 몇 줄은 운으로 통과할 수 있어서, "
                          "통과한 줄은 그 뒤 4주(거래 20건 이상) 확인 기간을 거칩니다"),
        "rows": jrows, "confirm": confirm, "candidates": cands})
    # round 4 part B (CONTRACT 9.5, 9.6): analysis buckets and the fixed accounts against their 5-year numbers
    _write_json(os.path.join(outdir, "analysis.json"), fake_analysis(accts))
    _write_json(os.path.join(outdir, "vs5y.json"), fake_vs5y(accts, past))

    costs = fake_costs(accts, cm)
    _write_json(os.path.join(outdir, "costs.json"), costs)
    regime = fake_regime(accts, mk, np.random.default_rng(seed + 5))
    _write_json(os.path.join(outdir, "regime.json"), regime)

    lines = [(a, L, a.lines[str(L)]) for a in accts for L in grid.LEVS]
    lines.sort(key=lambda x: x[2]["pnl_pct"], reverse=True)
    pick = lambda xs: [{"id": a.spec["id"], "name": a.spec["name"], "L": L, "pnl_pct": ln["pnl_pct"]} for a, L, ln in xs]
    by_kind = []
    for kind, ko in KIND_KO.items():
        ks = [a for a in accts if a.spec["kind"] == kind]
        by_kind.append({"kind": kind, "kind_ko": ko, "accounts": len(ks),
                        "mean_pnl_pct": {str(L): _r(float(np.mean([a.lines[str(L)]["pnl_pct"] for a in ks])), 2)
                                         for L in grid.LEVS}})
    switches = sorted(({**d, "account": a.spec["id"], "name": a.spec["name"]} for a in accts for d in a.decisions),
                      key=lambda d: d["t_ms"], reverse=True)
    # the goal line (8.7): the furthest stage of any line, and the line closest to "우리 기준"
    stage = 1 if phase == "live" else 0
    if confirm:
        stage = 3
    elif passed:
        stage = 2
    if cands:
        stage = 4
    cand_keys = {(c["id"], c["L"]) for c in cands}
    pool = [r for r in jrows if (r["id"], r["L"]) not in cand_keys] or jrows
    best = max(pool, key=lambda r: (sum(c["ok"] for c in r["ours"]["checks"]),
                                    float(byid[r["id"]].lines[str(r["L"])]["mean_R"] or -9)))
    ok = sum(c["ok"] for c in best["ours"]["checks"])
    of = len(best["ours"]["checks"])
    days_left = max(0, -(-(DEADLINE_MS - NOW_MS) // DAY))
    stages = ["설치", "데모 진행", "우리 기준 통과", "확인 기간", "실전 후보"]
    line_ko = (f"12/31까지 {days_left}일: {stages[stage]}"
               + (f" {len(cands)}줄 (두 분이 정할 차례)" if stage == 4 else " 단계")
               + f", 가장 가까운 줄 {best['name']} {best['L']}배 ({of}개 중 {ok}개 통과)")
    meas = [t["cost_bps"] for a in accts for t in a.trades if t.get("cost_bps") is not None]
    home = {"generated_ms": NOW_MS, "live_days": round((NOW_MS - live_start) / DAY, 2), "phase": phase,
            "totals": {"accounts": len(accts), "open_positions": sum(1 for t in all_trades if t["status"] == "open"),
                       "trades": sum(ln["trades"] for _a, _L, ln in lines), "passed": passed,
                       "confirming": n_conf, "candidates": len(cands)},
            "best": pick(lines[:5]), "worst": pick(lines[::-1][:5]), "by_kind": by_kind, "leaders": leaders,
            "recent_switches": switches[:10], "recent_trades": all_trades[:12],
            "goal": {"deadline_ms": DEADLINE_MS, "days_left": int(days_left), "stage": stage, "stages_ko": stages,
                     "closest": {"id": best["id"], "name": best["name"], "L": best["L"], "ok": ok, "of": of,
                                 "missing_ko": [f"{c['name_ko']} (지금 {c['value_ko']})" for c in best["ours"]["checks"]
                                                if not c["ok"]]},
                     "line_ko": line_ko},
            "regime_now": regime["now"],
            "costs_now": {"median_entry_bps": _r(float(np.median(meas)), 3) if meas else None,
                          "assumed_bps": ASSUMED_BPS}}
    home.update(fake_live.home_extra(accts, live_start, NOW_MS))          # equity_total / pnl_total (9.3)
    _write_json(os.path.join(outdir, "home.json"), home)
    # the view log: its own random stream, so the number of views changes nothing else
    vw = fake_views(np.random.default_rng(seed + 2), views)
    _write_json(os.path.join(outdir, "views.json"), vw)
    # the weekly review (8.10) and the Telegram history (8.11)
    review = fake_review(accts, confirm, rank_luck, mk, vw["views"])
    _write_json(os.path.join(outdir, "review.json"), review)
    _write_json(os.path.join(outdir, "telegram.json"),
                fake_telegram(accts, confirm, home, vw["views"], review, np.random.default_rng(seed + 6)))
    # the nightly backup (04:40 KST = 19:40 UTC) and the outside watch (every 10 minutes), CONTRACT 8.8
    last_backup = (NOW_MS - (19 * HOUR + 40 * 60_000)) // DAY * DAY + 19 * HOUR + 40 * 60_000
    n_dec = sum(len(a.decisions) for a in accts)
    _write_json(os.path.join(outdir, "backup.json"), {
        "last_ok_ms": last_backup + 41_000, "last_try_ms": last_backup + 41_000, "bytes": 1_843_221,
        "tables": {"views": len(vw["views"]), "decisions": n_dec, "passes": sum(1 for _ in confirm),
                   "depth": len(cm.ticks) * len(grid.COINS), "notified": 3_912, "meta": 14, "outbox": 611},
        "encrypted": True, "error_ko": None})
    checked = NOW_MS - 4 * 60_000
    _write_json(os.path.join(outdir, "watch.json"), {
        "checked_ms": checked, "ok": True, "items": [
            {"what": "dead", "ok": True, "detail_ko": "마지막 처리 4분 전 · demobot-live 켜져 있음"},
            {"what": "rank", "ok": True, "detail_ko": "순위표 41분 전에 새로 씀 (마지막 실행 성공)"},
            {"what": "backup", "ok": True, "detail_ko": f"마지막 백업 {_kst(last_backup)} (정상)"}]})
    live_facts = fake_live.write(outdir, accts, mk, cm, status, confirm, live_start, seed, NOW_MS)
    statuses = sorted({c["status"] for c in confirm})
    return {"accounts": len(accts), "passed": passed, "trades": len(all_trades), "live_start_ms": live_start,
            "confirm": statuses, "candidates": len(cands), "halts": sum(1 for a in accts for L in grid.LEVS
                                                                         if a.lines[str(L)]["stops"]["halted_ms"]),
            "touch_only": sum(m["touch_only"] for m in costs["maker"]), **live_facts}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demobot.dash.fake", description=__doc__.splitlines()[0])
    ap.add_argument("outdir")
    ap.add_argument("--past5y", default=None, help="also write fake past5y_<STRAT>_<tf>.npz into this folder")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--phase", default="live", choices=["live", "warm"])
    ap.add_argument("--empty", action="store_true", help="only status.json (nothing else written yet)")
    ap.add_argument("--views", type=int, default=40, help="views in views.json (under 30 finished: 표본 부족)")
    ap.add_argument("--now", default=None, help="'now' for the current time, or epoch ms (default: a fixed date)")
    a = ap.parse_args(argv)
    now = FIXED_NOW_MS if a.now is None else int(datetime.datetime.now(UTC).timestamp() * 1000) if a.now == "now" else int(a.now)
    facts = build(a.outdir, seed=a.seed, past5y_dir=a.past5y, phase=a.phase, empty=a.empty, now_ms=now, views=a.views)
    print(f"fake snapshot written to {a.outdir}: {facts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
