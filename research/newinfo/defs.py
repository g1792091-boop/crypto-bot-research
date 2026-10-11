"""Signal rules of the new-information batch (research/newinfo/PREREG_NEWINFO.md section 3), vectorised.

Every rule maps a ``Market`` (one timeframe; chart bars of one or more coins plus the inputs the rule reads) and one
combination of its numbers to per-coin boolean arrays (long, short) over the coin's chart bars. A True at bar i means
a signal of the bar closing at ``close_ms[i]``; the kernel fills it at the open of the next minute.

Timing (PREREG 2.4, no look-ahead): a bar closing at T reads
- its own and earlier bars' OHLCV;
- the 5-minute metrics row with the latest stamp t such that t + 5 min <= T (missing when t < T - 30 min; the row's
  value as it is, NaN when that row's value is missing: nothing is carried over a missing value);
- funding settlements whose settlement time (calc time floored to the minute) is <= T;
- for the daily VWAP, the 1m bars of the bar's UTC day with open < T;
- other coins' bars closing at or before T; a higher-timeframe bar only once its close <= T.
Trailing windows count samples at the cell's own bar closes: a window of D days is N = D x bars-per-day rows and needs
at least 0.9 N non-missing samples. A rank includes the current sample (pandas rank(pct=True), ties averaged); a mean
and standard deviation for a z use the N rows before the current one.

Warm-up: the first ``WARMUP_BARS`` chart bars of each coin never count (run.py's periods leave them out; D08 also
leaves such coins out of its ranking, PREREG 3.5).

Read-only research code: nothing here trades.
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")    # D08 tie order
TF_MS = {"30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000, "1d": DAY}
HTF_OF = {"1h": "4h", "4h": "1d"}          # D05: the higher timeframe of each cell
WARMUP_BARS = 300
NEUTRAL_F8 = 0.0001                        # 0.01% per 8 hours
METRIC_LAG = 5 * MIN
METRIC_STALE = 30 * MIN
COVER = 0.9                                # share of a trailing window that must be present
D04_MIN_PER_DAY = 2.7                      # settlements per lookback day (90% of three a day)
D05_DAYS, D05_MIN = 90, 243
D08_MIN_COINS = 4

# name -> timeframes, information kind ("metrics" rules have their own periods, PREREG 6), parameters in grid order:
# (name, values ascending / off before on, catalog or earlier value: a reference only).
RULES = {
    "H3A_CROWD_FADE": {"tfs": ("1h", "4h"), "info": "metrics", "params": (
        ("q", (0.02, 0.05, 0.10), 0.05), ("window_d", (14, 30, 60), 30), ("confirm", (False, True), False))},
    "D04_FUNDING_FADE": {"tfs": ("1h", "4h"), "info": "funding", "params": (
        ("q", (0.025, 0.05, 0.10), 0.05), ("lookback_d", (45, 90, 180), 90), ("confirm", (False, True), False))},
    "D05_FUNDING_TREND": {"tfs": ("1h", "4h"), "info": "funding", "params": (
        ("trend_ema", (100, 200, 300), 200), ("trigger_ema", (10, 20, 40), 20), ("fund_pct", (30, 50, 70), 50))},
    "D06_OI_DIVERGENCE": {"tfs": ("1h", "4h"), "info": "metrics", "params": (
        ("window_h", (12, 24, 48), 24), ("oi_z", (0.5, 1.0, 1.5), 1.0), ("z_lookback_d", (15, 30, 60), 30))},
    "D08_CROSS_COIN": {"tfs": ("1h", "4h"), "info": "price", "params": (
        ("rank_bars", (12, 24, 48), 24), ("rebalance_bars", (3, 6, 12), 6), ("abs_filter", (False, True), False))},
    "D10_VWAP_REVERT": {"tfs": ("30m", "1h"), "info": "price", "params": (
        ("dist_atr", (1.5, 2.0, 3.0), 2.0), ("skip_h", (1, 2, 4), 2), ("lookback_bars", (1, 3, 6), 3))},
    "D01_VOL_SPIKE": {"tfs": ("1h", "4h"), "info": "price", "params": (
        ("vol_mult", (2.0, 3.0, 4.0), 3.0), ("vol_len", (10, 20, 40), 20), ("ema_filter", (False, True), False))},
}
ORDER = tuple(RULES)
GRID_SIZE = {"H3A_CROWD_FADE": 18, "D04_FUNDING_FADE": 18, "D05_FUNDING_TREND": 27, "D06_OI_DIVERGENCE": 27,
             "D08_CROSS_COIN": 18, "D10_VWAP_REVERT": 27, "D01_VOL_SPIKE": 18}


# ------------------------------------------------------------------ grid
def grid(rule: str) -> list[dict]:
    """Every combination, first parameter outermost, values in the listed (ascending) order."""
    ps = RULES[rule]["params"]
    return [dict(zip([p[0] for p in ps], vals)) for vals in itertools.product(*[p[1] for p in ps])]


def neighbours(rule: str) -> list[list[int]]:
    """For each row, the rows one step up or down in one parameter (none outside the grid)."""
    ps = RULES[rule]["params"]
    sizes = [len(p[1]) for p in ps]
    keys = list(itertools.product(*[range(s) for s in sizes]))
    pos = {k: r for r, k in enumerate(keys)}
    out = []
    for k in keys:
        nb = []
        for j in range(len(sizes)):
            for d in (-1, 1):
                q = k[:j] + (k[j] + d,) + k[j + 1:]
                if q in pos:
                    nb.append(pos[q])
        out.append(nb)
    return out


def reference_row(rule: str) -> int:
    ref = {p[0]: p[2] for p in RULES[rule]["params"]}
    return grid(rule).index(ref)


# ------------------------------------------------------------------ bars and inputs
def bars(ts, o, h, l, c, v, step: int) -> dict:
    """UTC bins of 1m bars, exactly as research/fullgrid/run.py build_frame: the first bin dropped when the data start
    after its open, the last when the data end before its close; a bin with missing minutes is kept."""
    ts = np.asarray(ts, np.int64)
    if not len(ts):
        z = np.zeros(0)
        return {"open_ms": np.zeros(0, np.int64), "o": z, "h": z, "l": z, "c": z, "v": z}
    b = ts // step
    cut = np.flatnonzero(np.diff(b)) + 1
    st = np.r_[0, cut]
    en = np.r_[cut, len(ts)]
    open_ms = b[st] * step
    keep = np.ones(len(st), bool)
    if ts[0] > open_ms[0]:
        keep[0] = False
    if ts[-1] < open_ms[-1] + step - MIN:
        keep[-1] = False
    return {"open_ms": open_ms[keep], "o": np.asarray(o, float)[st][keep],
            "h": np.maximum.reduceat(np.asarray(h, float), st)[keep],
            "l": np.minimum.reduceat(np.asarray(l, float), st)[keep], "c": np.asarray(c, float)[en - 1][keep],
            "v": np.add.reduceat(np.asarray(v, float), st)[keep]}


def _fg():
    from paperbot import sweepsig
    sweepsig.lib()
    import fg_indicators
    return fg_indicators


def ema(x: np.ndarray, n: int) -> np.ndarray:
    """fg_indicators.ema (no value before n bars)."""
    return _fg().ema(pd.Series(np.asarray(x, float)), int(n)).to_numpy(float)


def atr14(h, l, c) -> np.ndarray:
    """fg_indicators.atr(df, 14), the ATR the exits use."""
    df = pd.DataFrame({"high": np.asarray(h, float), "low": np.asarray(l, float), "close": np.asarray(c, float)})
    return _fg().atr(df, 14).to_numpy(float)


class Coin:
    """One coin's chart bars on one timeframe and the inputs its rules read (each optional):
    minutes  dict ts, h, l, c, v of the 1m bars (D10's VWAP)
    metrics  dict t (stamp ms), ls, oi (D06, H3A), NaN = missing
    funding  dict t (settlement time ms = calc time floored to the minute), f8 (D04, D05)
    htf      dict close_ms, c of the higher timeframe's bars (D05)
    Derived series are memoised per object (``cached``)."""

    def __init__(self, sym: str, tf: str, open_ms, o, h, l, c, v, minutes=None, metrics=None, funding=None, htf=None,
                 atr=None):
        self.sym, self.tf, self.step = sym, tf, TF_MS[tf]
        self.open_ms = np.asarray(open_ms, np.int64)
        self.close_ms = self.open_ms + self.step
        self.o, self.h, self.l, self.c, self.v = (np.asarray(x, float) for x in (o, h, l, c, v))
        self.minutes, self.metrics, self.funding, self.htf = minutes, metrics, funding, htf
        self.memo = {} if atr is None else {("atr",): np.asarray(atr, float)}

    @property
    def n(self) -> int:
        return len(self.close_ms)

    @property
    def bpd(self) -> int:
        return DAY // self.step

    def cached(self, key: tuple, fn):
        if key not in self.memo:
            self.memo[key] = fn()
        return self.memo[key]

    def atr(self) -> np.ndarray:
        return self.cached(("atr",), lambda: atr14(self.h, self.l, self.c))

    def ema(self, n: int) -> np.ndarray:
        return self.cached(("ema", n), lambda: ema(self.c, n))

    def metric(self, col: str, lag_ms: int = 0) -> np.ndarray:
        """The metrics column ``col`` at each bar close minus ``lag_ms`` (PREREG 2.4)."""
        m = self.metrics
        return self.cached(("metric", col, lag_ms), lambda: metric_asof(m["t"], m[col], self.close_ms - lag_ms))

    def vwap(self) -> np.ndarray:
        m = self.minutes
        return self.cached(("vwap",), lambda: daily_vwap(m["ts"], m["h"], m["l"], m["c"], m["v"], self.open_ms,
                                                         self.close_ms))


class Market:
    """The coins of one timeframe (in SYMBOLS order)."""

    def __init__(self, tf: str, coins: list[Coin]):
        self.tf = tf
        self.coins = {c.sym: c for c in sorted(coins, key=lambda c: SYMBOLS.index(c.sym))}


# ------------------------------------------------------------------ building blocks
def need(n: int) -> int:
    """Non-missing samples a window of n rows needs (at least 0.9 n)."""
    return int(math.ceil(round(COVER * n, 9)))


def trailing_rank(x: np.ndarray, n: int) -> np.ndarray:
    """Rank of each sample among the n samples ending at it (itself included): (a + (e + 1) / 2) / m with a samples
    below, e equal (itself included), m present; NaN when the sample is missing or fewer than 0.9 n are present."""
    return pd.Series(np.asarray(x, float)).rolling(int(n), min_periods=need(n)).rank(pct=True).to_numpy(float)


def trailing_z(x: np.ndarray, n: int) -> np.ndarray:
    """(x - mean) / std (ddof 1) of the n samples before each one; NaN when fewer than 0.9 n of them are present."""
    s = pd.Series(np.asarray(x, float)).shift(1)
    r = s.rolling(int(n), min_periods=need(n))
    with np.errstate(invalid="ignore", divide="ignore"):
        return (np.asarray(x, float) - r.mean().to_numpy(float)) / r.std(ddof=1).to_numpy(float)


def first_in_episode(cond: np.ndarray, qual: np.ndarray | None = None) -> np.ndarray:
    """An episode is a run of consecutive bars where ``cond`` holds (a missing value is False and ends it). Returns
    True at the first bar of each episode where ``qual`` also holds (``qual`` None: the episode's first bar)."""
    cond = np.asarray(cond, bool)
    hit = cond if qual is None else cond & np.asarray(qual, bool)
    start = cond & ~np.r_[False, cond[:-1]]
    epi = np.cumsum(start)
    idx = np.flatnonzero(hit)
    out = np.zeros(len(cond), bool)
    if len(idx):
        e = epi[idx]
        out[idx[np.r_[True, e[1:] != e[:-1]]]] = True
    return out


def metric_asof(t: np.ndarray, vals: np.ndarray, at: np.ndarray) -> np.ndarray:
    """The value of the row with the latest stamp t such that t + 5 min <= at; NaN when no row or that t is older
    than at - 30 min (PREREG 2.4)."""
    t = np.asarray(t, np.int64)
    at = np.asarray(at, np.int64)
    k = np.searchsorted(t, at - METRIC_LAG, side="right") - 1
    kk = np.maximum(k, 0)
    ok = (k >= 0) & (t[kk] >= at - METRIC_STALE) if len(t) else np.zeros(len(at), bool)
    if not len(t):
        return np.full(len(at), np.nan)
    return np.where(ok, np.asarray(vals, float)[kk], np.nan)


def settlement_rank(t: np.ndarray, x: np.ndarray, span_ms: int) -> tuple[np.ndarray, np.ndarray]:
    """Per settlement s: the rank (pandas pct, ties averaged) of x_s among the present x of the settlements with time
    in (s - span, s], s included; and how many there are."""
    t = np.asarray(t, np.int64)
    x = np.asarray(x, float)
    lo = np.searchsorted(t, t - span_ms, side="right")
    hi = np.searchsorted(t, t, side="right")
    r = np.full(len(t), np.nan)
    cnt = np.zeros(len(t), np.int64)
    for i in range(len(t)):
        w = x[lo[i]:hi[i]]
        w = w[np.isfinite(w)]
        cnt[i] = len(w)
        if len(w) and np.isfinite(x[i]):
            r[i] = ((w < x[i]).sum() + ((w == x[i]).sum() + 1) / 2.0) / len(w)
    return r, cnt


def funding_percentiles(t: np.ndarray, f8: np.ndarray, at: np.ndarray, ks=(30, 50, 70)) -> tuple[np.ndarray, dict]:
    """D05 at each time T: f8 of the latest settlement with time <= T and the ks-th percentiles (numpy, linear) of
    the f8 of the settlements with time in (T - 90 days, T] (NaN when fewer than 243)."""
    t = np.asarray(t, np.int64)
    f8 = np.asarray(f8, float)
    at = np.asarray(at, np.int64)
    hi = np.searchsorted(t, at, side="right")
    lo = np.searchsorted(t, at - D05_DAYS * DAY, side="right")
    last = np.where(hi > 0, f8[np.maximum(hi - 1, 0)] if len(t) else np.nan, np.nan)
    P = {k: np.full(len(at), np.nan) for k in ks}
    pairs, inv = np.unique(np.stack([lo, hi], 1), axis=0, return_inverse=True)
    inv = np.asarray(inv).reshape(-1)
    vals = np.full((len(pairs), len(ks)), np.nan)
    for j, (a, b) in enumerate(pairs):
        w = f8[a:b]
        w = w[np.isfinite(w)]
        if len(w) >= D05_MIN:
            vals[j] = np.percentile(w, ks)
    for i, k in enumerate(ks):
        P[k] = vals[inv, i]
    return last, P


def daily_vwap(mts, mh, ml, mc, mv, open_ms, close_ms) -> np.ndarray:
    """Per chart bar: sum(typical x volume) / sum(volume) over the 1m bars of the UTC day of the bar's open with
    open < the bar's close (typical = (h + l + c) / 3); NaN without such minutes."""
    mts = np.asarray(mts, np.int64)
    if not len(mts):
        return np.full(len(open_ms), np.nan)
    day = mts // DAY
    typ = (np.asarray(mh, float) + np.asarray(ml, float) + np.asarray(mc, float)) / 3.0
    v = np.asarray(mv, float)
    g = pd.Series(day)
    cpv = pd.Series(typ * v).groupby(g.values).cumsum().to_numpy(float)    # within the UTC day only
    cv = pd.Series(v).groupby(g.values).cumsum().to_numpy(float)
    k = np.searchsorted(mts, np.asarray(close_ms, np.int64), side="left") - 1      # last minute with open < T
    kk = np.maximum(k, 0)
    bday = np.asarray(open_ms, np.int64) // DAY
    ok = (k >= 0) & (day[kk] == bday)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(ok & (cv[kk] > 0), cpv[kk] / np.where(cv[kk] > 0, cv[kk], 1.0), np.nan)


def _green(c: Coin) -> np.ndarray:
    return c.c > c.o


def _red(c: Coin) -> np.ndarray:
    return c.c < c.o


def _lt(a, b) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.asarray(a < b, bool)


def _shift(x: np.ndarray, k: int, fill=np.nan) -> np.ndarray:
    out = np.full(len(x), fill, dtype=np.asarray(x).dtype if not isinstance(fill, float) else float)
    if k < len(x):
        out[k:] = x[:len(x) - k]
    return out


# ------------------------------------------------------------------ rules (one coin)
def h3a(c: Coin, q: float, window_d: int, confirm: bool) -> tuple:
    """3.1 crowd fade: the all-account long/short ratio's rank over window_d days at an extreme -> the other side."""
    x = c.metric("ls")
    n = window_d * c.bpd
    r = c.cached(("ls_rank", n), lambda: trailing_rank(x, n))
    with np.errstate(invalid="ignore"):
        sh_c = r >= 1 - q
        lo_c = r <= q
    if confirm:
        return first_in_episode(lo_c, _green(c)), first_in_episode(sh_c, _red(c))
    return first_in_episode(lo_c), first_in_episode(sh_c)


def d04(c: Coin, q: float, lookback_d: int, confirm: bool) -> tuple:
    """3.2 funding fade: a settlement whose 8-hour-equivalent rate ranks at an extreme of its lookback -> the other
    side, on the first bar closing at or after the settlement (confirm: the bar after it, closing the trade's way).
    Two settlements on one signal bar: the later settlement decides that bar (the earlier one is dropped)."""
    F = c.funding
    t, f8 = np.asarray(F["t"], np.int64), np.asarray(F["f8"], float)
    r, cnt = c.cached(("f_rank", lookback_d), lambda: settlement_rank(t, f8, lookback_d * DAY))
    ok = cnt >= D04_MIN_PER_DAY * lookback_d
    with np.errstate(invalid="ignore"):
        side = np.where(ok & (r >= 1 - q) & (f8 > NEUTRAL_F8), -1, np.where(ok & (r <= q) & (f8 < NEUTRAL_F8), 1, 0))
    j = np.searchsorted(c.close_ms, t, side="left") + (1 if confirm else 0)
    keep = j < c.n
    j, side = j[keep], side[keep]
    bar = np.zeros(c.n, np.int8)
    if len(j):
        rev = j[::-1]
        _u, first_rev = np.unique(rev, return_index=True)       # the last settlement of each bar
        last = len(j) - 1 - first_rev
        bar[j[last]] = side[last]
    lo, sh = bar == 1, bar == -1
    if confirm:
        lo, sh = lo & _green(c), sh & _red(c)
    return lo, sh


def _htf_trend(c: Coin, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Close of the last closed higher-timeframe bar (close <= T) above / below its own EMA_n."""
    H = c.htf
    hc = np.asarray(H["c"], float)
    he = c.cached(("htf_ema", n), lambda: ema(hc, n))
    k = np.searchsorted(np.asarray(H["close_ms"], np.int64), c.close_ms, side="right") - 1
    kk = np.maximum(k, 0)
    has = k >= 0
    with np.errstate(invalid="ignore"):
        return has & (hc[kk] > he[kk]), has & (hc[kk] < he[kk])


def d05(c: Coin, trend_ema: int, trigger_ema: int, fund_pct: int) -> tuple:
    """3.3 trend pullback with a funding filter: in the trend of both timeframes, the close crossing back over
    EMA_trigger, only while the latest funding is not crowded that way (vs its 90-day percentiles)."""
    en, em = c.ema(trend_ema), c.ema(trigger_ema)
    hu, hd = _htf_trend(c, trend_ema)
    F = c.funding
    f, P = c.cached(("f_pct",), lambda: funding_percentiles(F["t"], F["f8"], c.close_ms))
    cp, ep = _shift(c.c, 1), _shift(em, 1)
    with np.errstate(invalid="ignore"):
        up = (c.c > en) & hu
        dn = (c.c < en) & hd
        cross_up = (cp <= ep) & (c.c > em)
        cross_dn = (cp >= ep) & (c.c < em)
        lo = up & cross_up & (f <= P[fund_pct])
        sh = dn & cross_dn & (f >= P[100 - fund_pct])
    return np.asarray(lo, bool), np.asarray(sh, bool)


def d06(c: Coin, window_h: int, oi_z: float, z_lookback_d: int) -> tuple:
    """3.4 open-interest divergence: a new window_h high (low) while open interest over window_h fell by more than
    oi_z standard deviations of its last z_lookback_d days -> fade."""
    def dlog():
        a, b = c.metric("oi"), c.metric("oi", window_h * HOUR)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.log(a / b)
    d = c.cached(("oi_d", window_h), dlog)
    n = z_lookback_d * c.bpd
    z = c.cached(("oi_z", window_h, n), lambda: trailing_z(d, n))
    w = window_h * HOUR // c.step
    hmax = pd.Series(c.h).rolling(w, min_periods=w).max().shift(1).to_numpy(float)
    lmin = pd.Series(c.l).rolling(w, min_periods=w).min().shift(1).to_numpy(float)
    with np.errstate(invalid="ignore"):
        falling = z < -oi_z
        sh_c = (c.c > hmax) & falling
        lo_c = (c.c < lmin) & falling
    return first_in_episode(lo_c), first_in_episode(sh_c)


def d10(c: Coin, dist_atr: float, skip_h: int, lookback_bars: int) -> tuple:
    """3.6 VWAP reversion: after a bar of the same UTC day stretched dist_atr ATR from the daily VWAP, the first bar
    turning back (still on the stretched side of the VWAP) -> toward it; not in the day's first skip_h hours."""
    vw, a = c.vwap(), c.atr()
    day = c.open_ms // DAY
    with np.errstate(invalid="ignore"):
        down = c.c <= vw - dist_atr * a
        up = c.c >= vw + dist_atr * a
    prev_dn = np.zeros(c.n, bool)
    prev_up = np.zeros(c.n, bool)
    for k in range(1, lookback_bars + 1):
        same = _shift(day, k, -1) == day
        prev_dn |= same & _shift(down, k, False)
        prev_up |= same & _shift(up, k, False)
    late = (c.close_ms - day * DAY) > skip_h * HOUR
    with np.errstate(invalid="ignore"):
        lo_c = prev_dn & _green(c) & (c.c < vw)
        sh_c = prev_up & _red(c) & (c.c > vw)
    return first_in_episode(lo_c, late), first_in_episode(sh_c, late)


def d01(c: Coin, vol_mult: float, vol_len: int, ema_filter: bool) -> tuple:
    """3.7 volume spike: volume above vol_mult x the mean of the vol_len bars before -> the candle's direction."""
    vma = c.cached(("vma", vol_len), lambda: pd.Series(c.v).rolling(vol_len, min_periods=vol_len).mean()
                   .shift(1).to_numpy(float))
    with np.errstate(invalid="ignore"):
        spike = c.v > vol_mult * vma
    lo, sh = spike & _green(c), spike & _red(c)
    if ema_filter:
        e = c.ema(200)
        with np.errstate(invalid="ignore"):
            lo, sh = lo & (c.c > e), sh & (c.c < e)
    return lo, sh


# ------------------------------------------------------------------ rules (all coins)
def d08(m: Market, rank_bars: int, rebalance_bars: int, abs_filter: bool) -> dict:
    """3.5 cross-coin strength: at UTC-aligned ranking times, long the coin with the highest return over rank_bars,
    short the lowest among the others (at least four coins past their warm-up; ties in SYMBOLS order)."""
    coins = list(m.coins.values())
    step = TF_MS[m.tf]
    out = {c.sym: (np.zeros(c.n, bool), np.zeros(c.n, bool)) for c in coins}
    times = np.unique(np.concatenate([c.close_ms for c in coins])) if coins else np.zeros(0, np.int64)
    times = times[(times // step) % rebalance_bars == 0]
    if not len(times):
        return out
    R = np.full((len(times), len(coins)), np.nan)
    at = np.full((len(times), len(coins)), -1, np.int64)
    for j, c in enumerate(coins):
        i = np.searchsorted(c.close_ms, times)
        ii = np.minimum(i, c.n - 1)
        here = (i < c.n) & (c.close_ms[ii] == times) & (i >= WARMUP_BARS)
        p = np.searchsorted(c.close_ms, times - rank_bars * step)
        pp = np.minimum(p, c.n - 1)
        back = (p < c.n) & (c.close_ms[pp] == times - rank_bars * step)
        ok = here & back
        with np.errstate(invalid="ignore", divide="ignore"):
            R[ok, j] = c.c[ii[ok]] / c.c[pp[ok]] - 1.0
        at[ok, j] = ii[ok]
    good = np.isfinite(R).sum(1) >= D08_MIN_COINS
    hiR = np.where(np.isfinite(R), R, -np.inf)
    lg = np.argmax(hiR, axis=1)                                   # first of the tied: SYMBOLS order
    loR = np.where(np.isfinite(R), R, np.inf)
    loR[np.arange(len(times)), lg] = np.inf                        # never the same coin
    sg = np.argmin(loR, axis=1)
    rows = np.arange(len(times))
    lret, sret = R[rows, lg], R[rows, sg]
    lok = good & ((lret > 0) if abs_filter else True)
    sok = good & ((sret < 0) if abs_filter else True)
    for k in np.flatnonzero(lok):
        out[coins[lg[k]].sym][0][at[k, lg[k]]] = True
    for k in np.flatnonzero(sok):
        out[coins[sg[k]].sym][1][at[k, sg[k]]] = True
    return out


PER_COIN = {"H3A_CROWD_FADE": h3a, "D04_FUNDING_FADE": d04, "D05_FUNDING_TREND": d05, "D06_OI_DIVERGENCE": d06,
            "D10_VWAP_REVERT": d10, "D01_VOL_SPIKE": d01}


def signals(rule: str, m: Market, combo: dict) -> dict:
    """{symbol: (long, short)} boolean arrays over each coin's chart bars."""
    if m.tf not in RULES[rule]["tfs"]:
        raise ValueError(f"{rule} has no {m.tf} cell")
    if rule == "D08_CROSS_COIN":
        res = d08(m, **combo)
    else:
        fn = PER_COIN[rule]
        res = {s: fn(c, **combo) for s, c in m.coins.items()}
    return {s: (np.asarray(lo, bool), np.asarray(sh, bool)) for s, (lo, sh) in res.items()}
