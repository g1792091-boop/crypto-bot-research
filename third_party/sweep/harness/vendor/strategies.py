"""Vectorised entry-signal generators.

Each function takes an OHLCV DataFrame (columns open/high/low/close/volume,
bar-close ordering) and returns (long, short): boolean numpy arrays that are
True on the bar whose CLOSE produced the signal.  Execution happens on the
next bar's open (engine.py).

31-set strategies reproduce fingrad_bot/strategies/*.py evaluate() logic
(per-bar `_recent_bool` / `_current_bool` / `synchronized` semantics turned
into rolling operations).  V3.9 / OBV reproduce the Pine v6 sources.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import fg_fast
import fg_indicators as fg
import pine_indicators as pi


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _b(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        x = x.fillna(False).to_numpy()
    return np.asarray(x).astype(bool)


def _f(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        x = x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def recent(x, bars: int) -> np.ndarray:
    """True if x was True on any of the last `bars` bars (inclusive of current)."""
    s = pd.Series(_b(x).astype(np.int8))
    return (s.rolling(max(1, int(bars)), min_periods=1).max() > 0).to_numpy()


def shift_bool(x, k: int = 1) -> np.ndarray:
    out = np.zeros(len(x), dtype=bool)
    out[k:] = _b(x)[:-k]
    return out


def synchronized(parts, bars: int) -> np.ndarray:
    """Vectorised v2_base.synchronized: all parts true inside window ending at
    the current bar OR inside the window ending at the previous bar."""
    w = max(1, int(bars))
    rm = [recent(p, w) for p in parts]
    now = np.logical_and.reduce(rm)
    prev = shift_bool(now, 1)
    return now | prev


def gt(a, b):
    with np.errstate(invalid="ignore"):
        return _f(a) > _f(b)


def lt(a, b):
    with np.errstate(invalid="ignore"):
        return _f(a) < _f(b)


def ge(a, b):
    with np.errstate(invalid="ignore"):
        return _f(a) >= _f(b)


def le(a, b):
    with np.errstate(invalid="ignore"):
        return _f(a) <= _f(b)


def cross_above(a, b):
    return _b(fg.crossed_above(pd.Series(_f(a)), pd.Series(_f(b)) if not np.isscalar(b) else b))


def cross_below(a, b):
    return _b(fg.crossed_below(pd.Series(_f(a)), pd.Series(_f(b)) if not np.isscalar(b) else b))


# ---------------------------------------------------------------------------
# 31-set: S2 / S5 / S6
# ---------------------------------------------------------------------------
def s2_supertrend_roc(df):
    line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    r = fg.roc(df["close"], 9)
    d = _f(direction)
    st_flip_up = gt(d, 0) & le(pd.Series(d).shift(1), 0)
    st_flip_down = lt(d, 0) & ge(pd.Series(d).shift(1), 0)
    roc_up = cross_above(r, 0.0)
    roc_down = cross_below(r, 0.0)
    long = gt(d, 0) & gt(r, 0) & (st_flip_up | roc_up)
    short = lt(d, 0) & lt(r, 0) & (st_flip_down | roc_down)
    return long, short


def s5_donchian_mfi(df):
    upper, middle, lower = fg.donchian_channel(df, 20, shift_previous=True)
    m = fg.mfi(df, 14)
    close = df["close"]
    breakout_up = gt(close, upper) & le(close.shift(1), upper.shift(1))
    breakout_down = lt(close, lower) & ge(close.shift(1), lower.shift(1))
    mfi_up = cross_above(m, 30.0)
    mfi_down = cross_below(m, 70.0)
    sync = 3
    long_state = gt(close, upper) & gt(m, 30.0)
    short_state = lt(close, lower) & lt(m, 70.0)
    long = recent(breakout_up, sync) & recent(mfi_up, sync) & long_state & (breakout_up | mfi_up)
    short = recent(breakout_down, sync) & recent(mfi_down, sync) & short_state & (breakout_down | mfi_down)
    return long, short


def s6_ema_dmi_adx(df):
    e = fg.ema(df["close"], 20)
    plus, minus, adx = fg.dmi_adx(df, 14, 14)
    close = df["close"]
    price_up = cross_above(close, e)
    price_down = cross_below(close, e)
    di_up = cross_above(plus, minus)
    di_down = cross_above(minus, plus)
    sync = 2
    adx_ok = ge(adx, 25.0)
    long_state = gt(close, e) & gt(plus, minus)
    short_state = lt(close, e) & gt(minus, plus)
    long = adx_ok & recent(di_up, sync) & recent(price_up, sync) & long_state & (price_up | di_up)
    short = adx_ok & recent(di_down, sync) & recent(price_down, sync) & short_state & (price_down | di_down)
    return long, short


# ---------------------------------------------------------------------------
# 31-set: N01 / N02 / N03
# ---------------------------------------------------------------------------
def _st_flips(direction):
    d = _f(direction)
    dp = pd.Series(d).shift(1)
    return (gt(d, 0) & le(dp, 0)), (lt(d, 0) & ge(dp, 0))


def n01_supertrend_ema(df):
    ef = fg.ema(df["close"], 5)
    es = fg.ema(df["close"], 20)
    _line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    up, down = cross_above(ef, es), cross_below(ef, es)
    flip_up, flip_down = _st_flips(direction)
    sync = 2
    long = recent(up, sync) & gt(direction, 0) & (up | flip_up)
    short = recent(down, sync) & lt(direction, 0) & (down | flip_down)
    return long, short


def n02_supertrend_kst(df):
    _line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    kline, ksig = fg.kst(df["close"], (10, 15, 20, 30), (10, 10, 10, 15), 9)
    up, down = cross_above(kline, ksig), cross_below(kline, ksig)
    flip_up, flip_down = _st_flips(direction)
    sync = 2
    long = gt(direction, 0) & recent(up, sync) & (up | flip_up)
    short = lt(direction, 0) & recent(down, sync) & (down | flip_down)
    return long, short


def n03_adx_golden_cross(df):
    ef = fg.ema(df["close"], 50)
    es = fg.ema(df["close"], 200)
    _p, _m, adx = fg.dmi_adx(df, 14, 14)
    gc, dc = cross_above(ef, es), cross_below(ef, es)
    adx_evt = cross_above(adx, 25.0)
    sync = 3
    state = ge(adx, 25.0)
    long = recent(gc, sync) & recent(adx_evt, sync) & state & (gc | adx_evt)
    short = recent(dc, sync) & recent(adx_evt, sync) & state & (dc | adx_evt)
    return long, short


# ---------------------------------------------------------------------------
# 31-set: Ichimoku family N07 / N08 / N12 / N14
# ---------------------------------------------------------------------------
def _ichimoku_family(df, kind: str):
    tenkan, kijun, span_a, span_b = fg.ichimoku(df, 9, 26, 52, 26)
    tk_up, tk_down = cross_above(tenkan, kijun), cross_below(tenkan, kijun)
    cloud_green, cloud_red = gt(span_a, span_b), lt(span_a, span_b)
    if kind == "CMO":
        mom = fg.cmo(df["close"], 14)
        le_, se_ = cross_above(mom, 0.0), cross_below(mom, 0.0)
        ls_, ss_ = gt(mom, 0.0), lt(mom, 0.0)
    elif kind == "WILLIAMS_R":
        mom = fg.williams_r(df, 14)
        le_, se_ = cross_above(mom, -80.0), cross_below(mom, -20.0)
        ls_, ss_ = gt(mom, -80.0), lt(mom, -20.0)
    elif kind == "AO":
        mom = fg.awesome_oscillator(df, 5, 34)
        m1, m2 = mom.shift(1), mom.shift(2)
        le_ = cross_above(mom, 0.0) | (gt(mom, m1) & le(m1, m2))
        se_ = cross_below(mom, 0.0) | (lt(mom, m1) & ge(m1, m2))
        ls_ = gt(mom, 0.0) & gt(mom, m1)
        ss_ = lt(mom, 0.0) & lt(mom, m1)
    elif kind == "RSI":
        mom = fg.rsi(df["close"], 14)
        m1 = mom.shift(1)
        le_ = lt(mom, 30.0) & gt(mom, m1)
        se_ = gt(mom, 70.0) & lt(mom, m1)
        ls_ = lt(mom, 30.0)
        ss_ = gt(mom, 70.0)
    else:
        raise ValueError(kind)
    sync = 3
    long = recent(tk_up, sync) & cloud_green & recent(le_, sync) & ls_ & (tk_up | le_)
    short = recent(tk_down, sync) & cloud_red & recent(se_, sync) & ss_ & (tk_down | se_)
    return long, short


def n07_ichimoku_cmo(df):
    return _ichimoku_family(df, "CMO")


def n08_ichimoku_williams(df):
    return _ichimoku_family(df, "WILLIAMS_R")


def n12_ichimoku_ao(df):
    return _ichimoku_family(df, "AO")


def n14_ichimoku_rsi(df):
    return _ichimoku_family(df, "RSI")


# ---------------------------------------------------------------------------
# 31-set: N09 / N10
# ---------------------------------------------------------------------------
def n09_alligator_aroon(df):
    close = df["close"]
    lips, teeth, jaw = fg.sma(close, 5), fg.sma(close, 8), fg.sma(close, 13)
    lips_above = gt(lips, teeth) & gt(lips, jaw)
    lips_below = lt(lips, teeth) & lt(lips, jaw)
    a_up = lips_above & ~shift_bool(lips_above, 1)
    a_down = lips_below & ~shift_bool(lips_below, 1)
    up, down = fg_fast.aroon(df, 25)
    ar_up, ar_down = cross_above(up, down), cross_below(up, down)
    sync = 2
    long_state = lips_above & ge(_f(up) - _f(down), 0.0)
    short_state = lips_below & ge(_f(down) - _f(up), 0.0)
    long = recent(a_up, sync) & recent(ar_up, sync) & long_state & (a_up | ar_up)
    short = recent(a_down, sync) & recent(ar_down, sync) & short_state & (a_down | ar_down)
    return long, short


def n10_heikin_psar(df):
    ha = fg_fast.heikin_ashi(df)
    psar, pdir = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2)
    ha_green = gt(ha["ha_close"], ha["ha_open"])
    ha_red = lt(ha["ha_close"], ha["ha_open"])
    tol = (ha["ha_high"] - ha["ha_low"]).abs() * 0.02
    body_min = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).min(axis=1)
    body_max = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).max(axis=1)
    no_lower = le((body_min - ha["ha_low"]).abs(), tol)
    no_upper = le((ha["ha_high"] - body_max).abs(), tol)
    turn_green = ha_green & ~shift_bool(ha_green, 1)
    turn_red = ha_red & ~shift_bool(ha_red, 1)
    flip_up, flip_down = _st_flips(pdir)
    sync = 2
    close = df["close"]
    long = (recent(turn_green, sync) & no_lower & lt(psar, close) & (gt(pdir, 0) | recent(flip_up, sync))
            & (turn_green | flip_up))
    short = (recent(turn_red, sync) & no_upper & gt(psar, close) & (lt(pdir, 0) | recent(flip_down, sync))
             & (turn_red | flip_down))
    return long, short


# ---------------------------------------------------------------------------
# 31-set v2: N17 / N18 / N21 / N22 / N23 / N24 / N25
# ---------------------------------------------------------------------------
def n17_keltner_rsi(df):
    mid = fg.ema(df["close"], 20)
    a = fg.atr(df, 14)
    upper, lower = mid + a * 2.0, mid - a * 2.0
    r = fg.rsi(df["close"], 14)
    approach = 0.10 * a
    long_touch = le(df["low"], lower + approach)
    short_touch = ge(df["high"], upper - approach)
    long_rsi, short_rsi = le(r, 30.0), ge(r, 70.0)
    long_ok = synchronized([long_touch, long_rsi], 2)
    short_ok = synchronized([short_touch, short_rsi], 2)
    return long_ok, short_ok & ~long_ok


def n18_vwma_macd(df):
    v = fg.vwma(df, 20)
    ml, sl, h = fg.macd(df["close"], 12, 26, 9)
    up, down = cross_above(ml, sl), cross_below(ml, sl)
    above, below = gt(df["close"], v), lt(df["close"], v)
    hist_up, hist_down = gt(h, h.shift(1)), lt(h, h.shift(1))
    long_ok = synchronized([up, above, hist_up, gt(ml, 0.0)], 2)
    short_ok = synchronized([down, below, hist_down, lt(ml, 0.0)], 2)
    return long_ok, short_ok & ~long_ok


def n21_supertrend_rsi_adx(df):
    _st, up = fg_fast.supertrend_v2(df, 10, 6.0)
    up = _b(up)
    r = fg.rsi(df["close"], 14)
    adx_line, _p, _m = fg.adx_dmi(df, 14)
    adx_cross_down = cross_below(adx_line, 25.0)
    rsi_down = gt(r, 70.0) & lt(r, r.shift(1))
    rsi_up = lt(r, 30.0) & gt(r, r.shift(1))
    short_ok = (~up) & adx_cross_down & rsi_down
    long_ok = up & adx_cross_down & rsi_up
    return long_ok & ~short_ok, short_ok


def n22_vortex_psar(df):
    plus, minus = fg.vortex_indicator(df, 14)
    psar, _d = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.20)
    up, down = cross_above(plus, minus), cross_below(plus, minus)
    above, below = gt(df["close"], psar), lt(df["close"], psar)
    long_ok = above & up
    short_ok = below & down
    return long_ok, short_ok & ~long_ok


def n23_heikin_supertrend(df):
    ha = fg_fast.heikin_ashi(df)
    _st, up = fg_fast.supertrend_v2(df, 10, 6.0)
    up = _b(up)
    rng = (ha["ha_high"] - ha["ha_low"]).replace(0, np.nan)
    body_min = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).min(axis=1)
    body_max = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).max(axis=1)
    no_lower = le((body_min - ha["ha_low"]) / rng, 0.02)
    no_upper = le((ha["ha_high"] - body_max) / rng, 0.02)
    green = gt(ha["ha_close"], ha["ha_open"])
    red = lt(ha["ha_close"], ha["ha_open"])
    long_ok = green & no_lower & up
    short_ok = red & no_upper & (~up)
    fresh_long = long_ok & ~shift_bool(long_ok, 1)
    fresh_short = short_ok & ~shift_bool(short_ok, 1)
    return fresh_long, fresh_short & ~fresh_long


def n24_dmi(df):
    adx_line, plus, minus = fg.adx_dmi(df, 14)
    plus_up = cross_above(plus, minus)
    minus_up = cross_above(minus, plus)
    long_ok = ge(adx_line, 25.0) & plus_up
    short_ok = le(adx_line, 25.0) & minus_up
    return long_ok, short_ok & ~long_ok


def n25_double_supertrend_cci(df):
    _f1, fast_up = fg_fast.supertrend_v2(df, 10, 6.0)
    _f2, slow_up = fg_fast.supertrend_v2(df, 20, 6.0)
    fast_up, slow_up = _b(fast_up), _b(slow_up)
    c = fg_fast.cci(df, 20)
    c_up = cross_above(c, -100.0)
    c_down = cross_below(c, 100.0)
    agree_up = fast_up & slow_up
    agree_down = (~fast_up) & (~slow_up)
    range_mode = fast_up != slow_up
    trend_long, trend_short = agree_up & c_up, agree_down & c_down
    range_long, range_short = range_mode & c_up, range_mode & c_down
    long = trend_long | (range_long & ~trend_short)
    short = (trend_short & ~trend_long) | (range_short & ~trend_long & ~range_long)
    return long, short & ~long


# ---------------------------------------------------------------------------
# V3.9 on its own chart timeframe (15m chart => no MTF filter, STC optional)
# ---------------------------------------------------------------------------
def v39_signals(df, stc_filter: bool = False, adx_max_for_c: bool = False):
    """Returns dict of boolean arrays: S42_L/S42_S, S52, SR, D16, AC1 and ALL_L/ALL_S.

    stc_filter=False reproduces the 15-minute chart behaviour of the Pine
    source (STC restriction and 15m reference are both disabled on a 15m chart).
    stc_filter=True is the research variant that re-enables the 75/25 STC gate.
    """
    high, low, close = _f(df["high"]), _f(df["low"]), _f(df["close"])
    n = len(close)
    _l3, d3 = pi.exchange_supertrend(high, low, close, 10, 3.0)
    _l6, d6 = pi.exchange_supertrend(high, low, close, 10, 6.0)
    st3_bull, st3_bear = d3 == 1, d3 == -1
    st6_bull, st6_bear = d6 == 1, d6 == -1
    _ml, _ms, hist = pi.pine_macd(close, 12, 26, 9)
    hist_prev = pi.shift1(hist)
    with np.errstate(invalid="ignore"):
        macd_weak_neg = (hist < 0.0) & (hist > hist_prev)
        macd_weak_pos = (hist > 0.0) & (hist < hist_prev)
    stc_v = pi.stc(close, 12, 26, 50, 0.5)
    stc_long_ok = np.ones(n, dtype=bool) if not stc_filter else ~(stc_v >= 75.0)
    stc_short_ok = np.ones(n, dtype=bool) if not stc_filter else ~(stc_v <= 25.0)
    ao, ac = pi.ao_ac(high, low, 5, 34, 5)
    ao_p, ac_p = pi.shift1(ao), pi.shift1(ac)
    with np.errstate(invalid="ignore"):
        ao_below, ao_above = ao < 0.0, ao > 0.0
        ac_below, ac_above = ac < 0.0, ac > 0.0
        ao_up, ao_down = ao > ao_p, ao < ao_p
        ac_up, ac_down = ac > ac_p, ac < ac_p
    ao_ac_long = (ao_above & ao_down & ac_below & ac_up) | (ao_below & ac_below)
    ao_ac_short = (ao_below & ao_up & ac_above & ac_down) | (ao_above & ac_above)
    chop = pi.chop_angle(high, low, close, 34, 30, 25.0)
    with np.errstate(invalid="ignore"):
        chop_bull, chop_bear = chop >= 0.71, chop <= -0.71
    plus20, minus20 = pi.dmi(high, low, close, 20)
    plus16, minus16 = pi.dmi(high, low, close, 16)
    adx20 = pi.adx(high, low, close, 20, 20)
    with np.errstate(invalid="ignore"):
        dmi20_bull, dmi20_bear = plus20 > minus20, minus20 > plus20
        d16_up = pi.crossover(plus16, minus16)
        d16_down = pi.crossunder(plus16, minus16)
        four_long = st3_bull & st6_bull & dmi20_bull & chop_bull
        four_short = st3_bear & st6_bear & dmi20_bear & chop_bear
        adx_min_ok = adx20 >= 10.0
        adx_max_ok = adx20 <= 60.0
        gap = np.abs(plus20 - minus20)
        dmi_long_gap = dmi20_bull & ((plus20 - minus20) >= 2.0)
        dmi_short_gap = dmi20_bear & ((minus20 - plus20) >= 2.0)
        chop_long_angle = chop >= 2.0
        chop_short_angle = chop <= -2.0
        chop_abs = np.abs(chop) >= 2.0
    # chopConfirmBars = 1 -> f_recentTrue == condition itself
    anti_long = adx_max_ok & adx_min_ok & dmi_long_gap & chop_long_angle
    anti_short = adx_max_ok & adx_min_ok & dmi_short_gap & chop_short_angle
    acfirst_anti = adx_min_ok & (gap >= 2.0) & chop_abs
    # oscillators
    raw = pi.pine_stoch(close, high, low, 14)
    k42 = pi.pine_sma(raw, 4); d42 = pi.pine_sma(k42, 2)
    k52 = pi.pine_sma(raw, 5); d52 = pi.pine_sma(k52, 2)
    kr, dr = pi.stoch_rsi_kd(close, 14, 14, 3, 3)
    oscs = {"S42": (k42, d42), "S52": (k52, d52), "SR": (kr, dr)}
    with np.errstate(invalid="ignore"):
        ac_neg_up_state = ac_below & ac_up
        ac_pos_down_state = ac_above & ac_down
    ac_neg_up_first = ac_neg_up_state & ~shift_bool(ac_neg_up_state, 1)
    ac_pos_down_first = ac_pos_down_state & ~shift_bool(ac_pos_down_state, 1)
    ao_neg_down = ao_below & ao_down
    ao_pos_up = ao_above & ao_up

    out = {}
    # sequential part: cross memory + cooldown
    armed_long = {k: False for k in oscs}
    armed_short = {k: False for k in oscs}
    armed_long_bar = {k: -1 for k in oscs}
    armed_short_bar = {k: -1 for k in oscs}
    last_long_bar, last_short_bar = -10**9, -10**9
    cooldown = 2
    memory = 4
    sig = {f"{k}_L": np.zeros(n, dtype=bool) for k in oscs}
    sig.update({f"{k}_S": np.zeros(n, dtype=bool) for k in oscs})
    sig.update({"D16_L": np.zeros(n, dtype=bool), "D16_S": np.zeros(n, dtype=bool),
                "AC1_L": np.zeros(n, dtype=bool), "AC1_S": np.zeros(n, dtype=bool)})
    with np.errstate(invalid="ignore"):
        osc_data = {}
        for k, (kk, dd) in oscs.items():
            osc_data[k] = dict(
                gc=pi.crossover(kk, dd), dc=pi.crossunder(kk, dd),
                lcenter=(kk <= 50.0) | (dd <= 50.0), scenter=(kk >= 50.0) | (dd >= 50.0),
                gstate=kk > dd, dstate=kk < dd,
                both_above=(kk > 50.0) & (dd > 50.0), both_below=(kk < 50.0) & (dd < 50.0),
            )
    for i in range(n):
        long_cd = (i - last_long_bar) > cooldown
        short_cd = (i - last_short_bar) > cooldown
        common_long = four_long[i] and anti_long[i] and long_cd and macd_weak_neg[i] and ao_ac_long[i] and stc_long_ok[i]
        common_short = four_short[i] and anti_short[i] and short_cd and macd_weak_pos[i] and ao_ac_short[i] and stc_short_ok[i]
        # memory update (confirmed bar)
        for k, od in osc_data.items():
            if od["gc"][i]:
                armed_long[k] = bool(od["lcenter"][i]); armed_long_bar[k] = i if armed_long[k] else -1
                armed_short[k] = False; armed_short_bar[k] = -1
            elif od["dc"][i]:
                armed_short[k] = bool(od["scenter"][i]); armed_short_bar[k] = i if armed_short[k] else -1
                armed_long[k] = False; armed_long_bar[k] = -1
            if armed_long[k] and armed_long_bar[k] >= 0 and i - armed_long_bar[k] > memory:
                armed_long[k] = False; armed_long_bar[k] = -1
            if armed_short[k] and armed_short_bar[k] >= 0 and i - armed_short_bar[k] > memory:
                armed_short[k] = False; armed_short_bar[k] = -1
            if od["both_above"][i]:
                armed_long[k] = False; armed_long_bar[k] = -1
            if od["both_below"][i]:
                armed_short[k] = False; armed_short_bar[k] = -1
        fired_long = fired_short = False
        for k, od in osc_data.items():
            if common_long and armed_long[k] and od["gstate"][i] and od["lcenter"][i]:
                sig[f"{k}_L"][i] = True; fired_long = True
                armed_long[k] = False; armed_long_bar[k] = -1
            if common_short and armed_short[k] and od["dstate"][i] and od["scenter"][i]:
                sig[f"{k}_S"][i] = True; fired_short = True
                armed_short[k] = False; armed_short_bar[k] = -1
        if common_long and d16_up[i]:
            sig["D16_L"][i] = True; fired_long = True
        if common_short and d16_down[i]:
            sig["D16_S"][i] = True; fired_short = True
        acf_long_base = st3_bull[i] and acfirst_anti[i] and long_cd and stc_long_ok[i]
        acf_short_base = st3_bear[i] and acfirst_anti[i] and short_cd and stc_short_ok[i]
        if acf_long_base and ac_neg_up_first[i] and ao_neg_down[i]:
            sig["AC1_L"][i] = True; fired_long = True
        if acf_short_base and ac_pos_down_first[i] and ao_pos_up[i]:
            sig["AC1_S"][i] = True; fired_short = True
        if fired_long:
            last_long_bar = i
        if fired_short:
            last_short_bar = i
    out.update(sig)
    out["ALL_L"] = np.logical_or.reduce([sig[k] for k in sig if k.endswith("_L")])
    out["ALL_S"] = np.logical_or.reduce([sig[k] for k in sig if k.endswith("_S")])
    return out


def v39_all(df):
    s = v39_signals(df, stc_filter=False)
    return s["ALL_L"], s["ALL_S"] & ~s["ALL_L"]


def v39_all_stc(df):
    s = v39_signals(df, stc_filter=True)
    return s["ALL_L"], s["ALL_S"] & ~s["ALL_L"]


def _v39_sub(key):
    def f(df):
        s = v39_signals(df, stc_filter=False)
        return s[f"{key}_L"], s[f"{key}_S"] & ~s[f"{key}_L"]
    f.__name__ = f"v39_{key.lower()}"
    return f


# ---------------------------------------------------------------------------
# OBV V1.2 S path (chart timeframe; 15m => breakMa 9 unused for S)
# ---------------------------------------------------------------------------
def obv_s(df, stc_ob: float = 70.0, stc_os: float = 30.0):
    high, low, close = _f(df["high"]), _f(df["low"]), _f(df["close"])
    vol = _f(df["volume"])
    o = pi.obv(close, vol)
    trend_ma = pi.pine_sma(o, 30)
    ao, ac = pi.ao_ac(high, low, 5, 34, 5)
    stc_v = pi.stc(close, 12, 26, 50, 0.5)
    with np.errstate(invalid="ignore"):
        ac_pos, ac_neg = ac > 0.0, ac < 0.0
        stc_long_ok = stc_v < stc_ob
        stc_short_ok = stc_v > stc_os
        obv_up, obv_down = o > trend_ma, o < trend_ma
    raw11 = pi.pine_stoch(close, high, low, 11)
    raw15 = pi.pine_stoch(close, high, low, 15)
    raw9 = pi.pine_stoch(close, high, low, 9)
    gcs, dcs = [], []
    for raw in (raw11, raw15, raw9):
        k = pi.pine_sma(raw, 4); d = pi.pine_sma(k, 3)
        gcs.append(pi.crossover(k, d) & np.isfinite(k) & np.isfinite(d))
        dcs.append(pi.crossunder(k, d) & np.isfinite(k) & np.isfinite(d))
    any_golden = np.logical_or.reduce(gcs)
    any_dead = np.logical_or.reduce(dcs)
    long = any_golden & ac_pos & stc_long_ok & obv_up
    short = any_dead & ac_neg & stc_short_ok & obv_down
    return long, short & ~long


def obv_b(df, break_len: int = 9, stc_ob: float = 70.0, stc_os: float = 30.0):
    high, low, close = _f(df["high"]), _f(df["low"]), _f(df["close"])
    vol = _f(df["volume"])
    o = pi.obv(close, vol)
    break_ma = pi.pine_sma(o, break_len)
    _ao, ac = pi.ao_ac(high, low, 5, 34, 5)
    ac_p = pi.shift1(ac)
    stc_v = pi.stc(close, 12, 26, 50, 0.5)
    with np.errstate(invalid="ignore"):
        ac_pos_rising = (ac > 0.0) & (ac > ac_p)
        ac_neg_falling = (ac < 0.0) & (ac < ac_p)
        stc_long_ok = stc_v < stc_ob
        stc_short_ok = stc_v > stc_os
    up, down = pi.crossover(o, break_ma), pi.crossunder(o, break_ma)
    long = up & ac_pos_rising & stc_long_ok
    short = down & ac_neg_falling & stc_short_ok
    return long, short & ~long


# ---------------------------------------------------------------------------
# V4.5 (5m chart + confirmed 15m ST14/6 and STC).  Needs both dataframes.
# ---------------------------------------------------------------------------
def v45_signals(df5: pd.DataFrame, df15: pd.DataFrame):
    """Returns dict with AMIX/ASAME/B/C long/short arrays aligned to df5 bars.

    df5 and df15 must carry a 'ts' column (UTC bar OPEN time).  The 15-minute
    values used on a 5m bar are those of the last 15m bar that CLOSED at or
    before the 5m bar's close (Pine: HTF[1] with lookahead_on)."""
    h5, l5, c5 = _f(df5["high"]), _f(df5["low"]), _f(df5["close"])
    h15, l15, c15 = _f(df15["high"]), _f(df15["low"]), _f(df15["close"])
    n = len(c5)
    _lm, dm = pi.exchange_supertrend(h5, l5, c5, 14, 6.0)
    _ls, ds = pi.exchange_supertrend(h5, l5, c5, 14, 3.0)
    _l15, d15 = pi.exchange_supertrend(h15, l15, c15, 14, 6.0)
    stc15 = pi.stc(c15, 12, 26, 50, 0.5)
    # map: for each 5m bar close time, the last 15m bar close time <= it
    def _utc_ns(s):
        s = pd.to_datetime(s, utc=True)
        return s.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy().astype("datetime64[ns]")
    # Pine: request.security(..., f()[1], lookahead_on) => on every 5m bar inside
    # 15m bar T the value of 15m bar T-1 is used, i.e. the last 15m bar whose
    # close is <= the 5m bar's OPEN time.
    ts5_open = _utc_ns(df5["ts"])
    ts15_close = _utc_ns(df15["ts"]) + np.timedelta64(15, "m")
    idx = np.searchsorted(ts15_close, ts5_open, side="right") - 1
    valid = idx >= 0
    idx_c = np.clip(idx, 0, len(c15) - 1)
    d15m = np.where(valid, d15[idx_c], 0)
    stc15m = np.where(valid, stc15[idx_c], np.nan)
    st_main_bull, st_main_bear = dm == 1, dm == -1
    st_str_bull, st_str_bear = ds == 1, ds == -1
    opposite = (st_main_bull & st_str_bear) | (st_main_bear & st_str_bull)
    same = (st_main_bull & st_str_bull) | (st_main_bear & st_str_bear)
    f15_bull, f15_bear = d15m == 1, d15m == -1
    _ml, _ms, hist = pi.pine_macd(c5, 12, 26, 9)
    hp = pi.shift1(hist)
    with np.errstate(invalid="ignore"):
        weak_neg = (hist < 0.0) & (hist > hp)
        weak_pos = (hist > 0.0) & (hist < hp)
    ao, ac = pi.ao_ac(h5, l5, 5, 34, 5)
    aop, acp = pi.shift1(ao), pi.shift1(ac)
    with np.errstate(invalid="ignore"):
        ao_below, ao_above, ac_below, ac_above = ao < 0, ao > 0, ac < 0, ac > 0
        ao_up, ao_down, ac_up, ac_down = ao > aop, ao < aop, ac > acp, ac < acp
    chop = pi.chop_angle(h5, l5, c5, 34, 30, 25.0)
    with np.errstate(invalid="ignore"):
        chop_bull, chop_bear = chop >= 0.71, chop <= -0.71
    stc5 = pi.stc(c5, 12, 26, 50, 0.5)
    with np.errstate(invalid="ignore"):
        ready = np.isfinite(stc5) & np.isfinite(stc15m)
        stc_long_ok = ready & ~(stc5 >= 75.0) & ~(stc15m >= 75.0)
        stc_short_ok = ready & ~(stc5 <= 25.0) & ~(stc15m <= 25.0)
    raw = pi.pine_stoch(c5, h5, l5, 14)
    k33 = pi.pine_sma(raw, 3); d33 = pi.pine_sma(k33, 3)
    k43 = pi.pine_sma(raw, 4); d43 = pi.pine_sma(k43, 3)
    kr, dr = pi.stoch_rsi_kd(c5, 14, 14, 5, 3)
    with np.errstate(invalid="ignore"):
        g = [pi.crossover(k, d) & ((k <= 50) | (d <= 50)) for k, d in ((k33, d33), (k43, d43), (kr, dr))]
        dd = [pi.crossunder(k, d) & ((k >= 50) | (d >= 50)) for k, d in ((k33, d33), (k43, d43), (kr, dr))]
    any_long_now = np.logical_or.reduce(g) & weak_neg
    any_short_now = np.logical_or.reduce(dd) & weak_pos
    f15_long = f15_bull & stc_long_ok
    f15_short = f15_bear & stc_short_ok
    opp_long, opp_short = f15_long & opposite, f15_short & opposite
    same_long, same_short = f15_long & same, f15_short & same
    out = {
        "AMIX_L": opp_long & any_long_now, "AMIX_S": opp_short & any_short_now,
        "ASAME_L": same_long & ac_below & any_long_now, "ASAME_S": same_short & ac_above & any_short_now,
        "B_L": opp_long & chop_bear & any_long_now, "B_S": opp_short & chop_bull & any_short_now,
        "C_L": opp_long & chop_bear & ac_below & ac_up & ao_below & ao_down,
        "C_S": opp_short & chop_bull & ac_above & ac_down & ao_above & ao_up,
    }
    return out


def v45_exact_amb(df5, df15):
    s = v45_signals(df5, df15)
    long = s["B_L"] & ~s["C_L"]
    short = s["B_S"] & ~s["C_S"]
    return long, short & ~long


def v45_any(df5, df15):
    s = v45_signals(df5, df15)
    long = s["AMIX_L"] | s["ASAME_L"] | s["B_L"] | s["C_L"]
    short = s["AMIX_S"] | s["ASAME_S"] | s["B_S"] | s["C_S"]
    return long, short & ~long


# ---------------------------------------------------------------------------
# registry (15m single-timeframe candidates)
# ---------------------------------------------------------------------------
CANDIDATES_15M = {
    "S2_ST_ROC": s2_supertrend_roc,
    "S5_DONCHIAN_MFI": s5_donchian_mfi,
    "S6_EMA_DMI_ADX": s6_ema_dmi_adx,
    "N01_ST_EMA": n01_supertrend_ema,
    "N02_ST_KST": n02_supertrend_kst,
    "N03_ADX_GC": n03_adx_golden_cross,
    "N07_ICHI_CMO": n07_ichimoku_cmo,
    "N08_ICHI_WR": n08_ichimoku_williams,
    "N09_ALLIG_AROON": n09_alligator_aroon,
    "N10_HA_PSAR": n10_heikin_psar,
    "N12_ICHI_AO": n12_ichimoku_ao,
    "N14_ICHI_RSI": n14_ichimoku_rsi,
    "N17_KC_RSI": n17_keltner_rsi,
    "N18_VWMA_MACD": n18_vwma_macd,
    "N21_ST_RSI_ADX": n21_supertrend_rsi_adx,
    "N22_VORTEX_PSAR": n22_vortex_psar,
    "N23_HA_ST": n23_heikin_supertrend,
    "N24_DMI": n24_dmi,
    "N25_DST_CCI": n25_double_supertrend_cci,
    "V39_15M": v39_all,
    "V39_15M_STC": v39_all_stc,
    "V39_S42": _v39_sub("S42"),
    "V39_S52": _v39_sub("S52"),
    "V39_SR": _v39_sub("SR"),
    "V39_D16": _v39_sub("D16"),
    "V39_AC1": _v39_sub("AC1"),
    "OBV_S": obv_s,
    "OBV_B": obv_b,
}


# ---------------------------------------------------------------------------
# G1 entry filter (FINAL_PAPER_POLICY_KO.md §5): last 3 confirmed bars
# ---------------------------------------------------------------------------
def apply_g1(df, long, short):
    """Block LONG when range position >= 0.8 AND (last close - first open)/ATR14 >= 1
    over the last 3 confirmed bars; SHORT mirrored (<= 0.2, drop >= 1 ATR)."""
    high, low = _f(df["high"]), _f(df["low"])
    close, open_ = _f(df["close"]), _f(df["open"])
    a = fg.atr(df, 14).to_numpy(dtype=float)
    hh = pd.Series(high).rolling(3).max().to_numpy()
    ll = pd.Series(low).rolling(3).min().to_numpy()
    first_open = pd.Series(open_).shift(2).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        pos = (close - ll) / (hh - ll)
        prog_up = (close - first_open) / a
        prog_dn = (first_open - close) / a
        block_long = (pos >= 0.8) & (prog_up >= 1.0)
        block_short = (pos <= 0.2) & (prog_dn >= 1.0)
    return np.asarray(long, bool) & ~block_long, np.asarray(short, bool) & ~block_short


def v39_all_g1(df):
    l, s = v39_all(df)
    return apply_g1(df, l, s)


def obv_s_g1(df):
    l, s = obv_s(df)
    return apply_g1(df, l, s)


def v45_exact_amb_g1(df5, df15):
    l, s = v45_exact_amb(df5, df15)
    return apply_g1(df5, l, s)


CANDIDATES_15M["V39_15M_G1"] = v39_all_g1
CANDIDATES_15M["OBV_S_G1"] = obv_s_g1
