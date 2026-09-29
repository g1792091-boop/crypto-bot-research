"""SPEC-BASED approximate ports of 6 of the 12 FINGRAD strategies that stage 1
excluded ("근사식 12개는 원본이 없어 제외").  Conditions follow the previous
session's own 31-strategy report (claude.ai artifact 46br7PTC1MtZoe78PAgGNF,
sections S1~S6 / N09~N16 / N17~N25), which states all 31 are
REPRODUCIBLE_FROM_CODE.  NOT verified against fingrad_bot/strategies/*.py
(that code is not in the package).  N11/N13/N19 are three of the four
strategies that were positive in the 7-day live audit (N19, N13, N08, N11)."""
import numpy as np
import pandas as pd
import fg_indicators as fg
from strategies import _b, _f, recent, gt, lt, ge, le, cross_above, cross_below


def _body(df):
    return df["close"] - df["open"]


def n13_three_outside(df):
    o, h, l, c = (df[k] for k in ("open", "high", "low", "close"))
    atr = fg.atr(df, 14)
    b = c - o
    # pattern completes on bar t (bar3); bar1 = t-2, bar2 = t-1
    prior_down = c.shift(3) < c.shift(8)
    prior_up = c.shift(3) > c.shift(8)
    bull = prior_down & (b.shift(2) < 0) & (b.shift(1) > 0) & (b.shift(1) >= 0.5 * atr.shift(1)) \
        & (o.shift(1) <= c.shift(2)) & (c.shift(1) >= o.shift(2)) & (b > 0) & (c > c.shift(1))
    bear = prior_up & (b.shift(2) > 0) & (b.shift(1) < 0) & (-b.shift(1) >= 0.5 * atr.shift(1)) \
        & (o.shift(1) >= c.shift(2)) & (c.shift(1) <= o.shift(2)) & (b < 0) & (c < c.shift(1))
    ph = h.rolling(3).max()
    pl = l.rolling(3).min()
    long = np.zeros(len(df), bool); short = np.zeros(len(df), bool)
    cv = c.to_numpy()
    for lag in (1, 2):  # pattern completed lag bars ago, still valid (2 bars)
        pb = bull.shift(lag).fillna(False).to_numpy(bool)
        ps = bear.shift(lag).fillna(False).to_numpy(bool)
        PH = ph.shift(lag).to_numpy(); PL = pl.shift(lag).to_numpy()
        prev = np.concatenate([[np.nan], cv[:-1]])
        with np.errstate(invalid="ignore"):
            long |= pb & (cv > PH) & (prev <= PH)
            short |= ps & (cv < PL) & (prev >= PL)
    return long, short


def n11_breakaway(df):
    o, c = df["open"], df["close"]
    atr = fg.atr(df, 14)
    b = c - o
    a = atr
    # bars 1..5 = t-4..t
    prior_down = c.shift(5) < c.shift(10)
    prior_up = c.shift(5) > c.shift(10)
    bull = prior_down & (b.shift(4) < 0) & (-b.shift(4) >= 0.8 * a) & (b.shift(3) < 0) \
        & (o.shift(3) <= c.shift(4) + 0.05 * a) & (b.shift(2).abs() <= 0.4 * a) & (b.shift(1).abs() <= 0.4 * a) \
        & (b > 0) & (b >= 0.8 * a) & (c > c.shift(3))
    bear = prior_up & (b.shift(4) > 0) & (b.shift(4) >= 0.8 * a) & (b.shift(3) > 0) \
        & (o.shift(3) >= c.shift(4) - 0.05 * a) & (b.shift(2).abs() <= 0.4 * a) & (b.shift(1).abs() <= 0.4 * a) \
        & (b < 0) & (-b >= 0.8 * a) & (c < c.shift(3))
    return _b(bull), _b(bear)


def n19_fib_chop(df):
    h, l, c, o = df["high"], df["low"], df["close"], df["open"]
    atr = fg.atr(df, 14)
    hh = h.rolling(34).max().shift(3)
    ll = l.rolling(34).min().shift(3)
    mid = ll + 0.5 * (hh - ll)
    chop = fg.research_chop_zone(df)
    long = (l <= mid + 0.2 * atr) & (c > mid) & (c > o) & chop.isin(["GREEN", "BLUE"])
    short = (h >= mid - 0.2 * atr) & (c < mid) & (c < o) & chop.isin(["RED", "DARK_RED"])
    return _b(long), _b(short)


def n20_ema9_chop_short(df):
    c = df["close"]
    e9 = fg.ema(c, 9)
    reg = fg.research_chop_regime(df)
    short = reg.isin(["YELLOW", "RED"]) & lt(c, e9) & cross_below(c, e9)
    return np.zeros(len(df), bool), _b(short)


def s4_bb_squeeze_bbp(df):
    c = df["close"]
    up, mid, lo, bw = fg.bollinger_bands(c, 20, 2.0)
    thr = fg.rolling_percentile_threshold(bw, 100, 0.2)
    sq = _b(bw <= thr)
    sq_prev = recent(pd.Series(sq).shift(1).fillna(False), 5)  # any of bars t-5..t-1
    _, _, bbp = fg.bull_bear_power(df, 13)
    long = sq_prev & gt(c, up) & le(c.shift(1), up.shift(1)) & gt(bbp, 0.0)
    short = sq_prev & lt(c, lo) & ge(c.shift(1), lo.shift(1)) & lt(bbp, 0.0)
    return long, short


def n15_keltner_ao(df):
    up, mid, lo = fg.keltner_channel(df, 20, 10, 2.0)
    ao = fg.awesome_oscillator(df, 5, 34)
    l, h, c = df["low"], df["high"], df["close"]
    long = lt(l.shift(1), lo.shift(1)) & gt(c, lo) & gt(ao, ao.shift(1)) & gt(ao, 0.0)
    short = gt(h.shift(1), up.shift(1)) & lt(c, up) & lt(ao, ao.shift(1)) & lt(ao, 0.0)
    return long, short


EXTRA = {
    "N11_BREAKAWAY*": n11_breakaway,
    "N13_3OUTSIDE*": n13_three_outside,
    "N19_FIB_CHOP*": n19_fib_chop,
    "N20_EMA9_CHOP*": n20_ema9_chop_short,
    "S4_BB_BBP*": s4_bb_squeeze_bbp,
    "N15_KC_AO*": n15_keltner_ao,
}
