"""Parameter re-implementation of V45_AMB for the sensitivity study (PREREG_ENTRY.md section 4, C).

``signals(df, tf)`` with no overrides reproduces ``sweep_lib.v45_amb`` (long = B_L & ~C_L,
short = B_S & ~C_S & ~long of ``sweep_lib.v45_signals_gen``) bar for bar, including the higher-timeframe
frame: HTF = sweep_lib.HTF_OF[tf] (15m -> 1h, 1h -> 4h, 4h -> 1d) resampled from the chart bars with
sweep_lib.resample_ohlcv, and HTF ST(14, 6) direction / STC(12, 26, 50) mapped onto each chart bar from the
last HTF bar whose close time (sweep_lib.htf_close_ns) <= the chart bar's open time (the body of
sweep_lib.v45_htf_components, mapping 'closed', with the HTF ST multiplier threaded through). The locked
rules_bt / compute_signals path passes no frames, so the locked code resamples exactly like this.

Locked chart-TF rule (third_party/sweep/harness/sweep_lib.py:v45_signals_gen), long side:
    HTF ST(14, 6) up & STC(chart) < 75 & STC(HTF) < 75                (f15_long)
    ST(14, 6) and ST(14, 3) point in opposite directions              (opposite)
    chop angle(34, 30, 25) <= -0.71                                    (chop_bear)
    a golden cross at/under 50 of Stoch 14 K3/D3, Stoch 14 K4/D3 or StochRSI 14/14/5/3,
      with MACD(12, 26, 9) histogram < 0 and rising                   (any_long_now)
    and NOT (AC < 0 rising & AO < 0 falling)                           (~C_L)
Shorts mirror (STC > 25, chop >= 0.71, dead cross at/over 50, histogram > 0 and falling).

Parameters:
  st_mult_main    6.0   multiplier of the chart ST(14, 6)
  st_mult_strict  3.0   multiplier of the chart ST(14, 3)
  htf_st_mult     6.0   multiplier of the higher-timeframe ST(14, 6) (a separate number in
                        sweep_lib.v45_htf_components)
  stoch_len       14    look-back of the raw stochastic behind the K3/D3 and K4/D3 triggers
Note: st_mult_main x0.5 = 3.0 equals st_mult_strict, so the two chart SuperTrends coincide, "opposite" can never
hold and that variant has no signal at all (a property of the rule, kept as PREREG 4 defines the variant).
Not varied: the STC level 75 / 25 (on BTC 1h, last 5000 bars, 69 signals, its x0.5..x1.5 moves change only
1-5 signal bars, against 2-33 for htf_st_mult and 14-25 for stoch_len; signal flags only, no outcome), the ATR
length 14, the STC lengths, the chop threshold 0.71 (the chop angle is a whole number of degrees: only x1.5 of
0.71 would change the rule), StochRSI 14/14/5/3, MACD, AO/AC.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from paperbot import sweepsig  # noqa: E402

_L = sweepsig.lib()  # hash-checked locked code; puts the vendored indicator modules on sys.path

import pine_indicators as pi  # noqa: E402
from strategies import _f  # noqa: E402

NAME = "V45_AMB"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/sweep_lib.py:v45_signals_gen (via v45_amb)"

PARAMS = [
    {"name": "st_mult_main", "default": 6.0, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (_lm, dm = pi.exchange_supertrend(h5, l5, c5, 14, 6.0))"},
    {"name": "st_mult_strict", "default": 3.0, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (_ls, dsx = pi.exchange_supertrend(h5, l5, c5, 14, 3.0))"},
    {"name": "htf_st_mult", "default": 6.0, "kind": "mult", "neutral": None,
     "where": "third_party/sweep/harness/sweep_lib.py:v45_htf_components "
              "(_l15, d15 = pi.exchange_supertrend(h15, l15, c15, 14, 6.0))"},
    {"name": "stoch_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (raw = pi.pine_stoch(c5, h5, l5, 14) behind k33/d33 and k43/d43)"},
]
_SPEC = {p["name"]: p for p in PARAMS}
MULTIPLIERS = (0.5, 0.75, 1.25, 1.5)


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def variant_value(spec: dict, m: float):
    """PREREG 4: length -> round half up, min 2; mult / threshold_abs -> m * default;
    threshold_neutral -> neutral + m * (default - neutral)."""
    d, kind = spec["default"], spec["kind"]
    if kind == "length":
        return max(2, _round_half_up(d * m))
    if kind in ("mult", "threshold_abs"):
        return float(d) * m
    if kind == "threshold_neutral":
        return float(spec["neutral"]) + m * (float(d) - float(spec["neutral"]))
    raise ValueError(f"unknown kind {kind!r}")


def variants(p) -> list[dict]:
    """The four override dicts (x0.5, x0.75, x1.25, x1.5) of parameter ``p`` (name or PARAMS entry)."""
    spec = _SPEC[p["name"] if isinstance(p, dict) else p]
    return [{spec["name"]: variant_value(spec, m)} for m in MULTIPLIERS]


def _resolve(overrides: dict) -> dict:
    bad = set(overrides) - set(_SPEC)
    if bad:
        raise ValueError(f"{NAME}: unknown parameter(s) {sorted(bad)}")
    p = {k: s["default"] for k, s in _SPEC.items()}
    p.update(overrides)
    for k, s in _SPEC.items():
        p[k] = int(p[k]) if s["kind"] == "length" else float(p[k])
    return p


def htf_frame(df, tf):
    """(HTF name, HTF bars resampled from the chart bars) exactly as sweep_lib.v45_amb builds them."""
    htf = _L.HTF_OF[tf]
    return htf, _L.resample_ohlcv(df, htf)


def htf_components(dfc, dfh, htf: str, st_mult: float = 6.0):
    """sweep_lib.v45_htf_components (mapping 'closed') with the HTF ST multiplier as an argument: HTF ST(14, m)
    direction and STC(12, 26, 50) of the last HTF bar whose close time <= the chart bar's open time."""
    h15, l15, c15 = _f(dfh["high"]), _f(dfh["low"]), _f(dfh["close"])
    n = len(dfc)
    if len(c15) == 0:
        return np.zeros(n), np.full(n, np.nan)
    _l15, d15 = pi.exchange_supertrend(h15, l15, c15, 14, st_mult)
    stc15 = pi.stc(c15, 12, 26, 50, 0.5)
    key = _L.htf_close_ns(dfh["ts"], htf)
    idx = np.searchsorted(key, _L._utc_ns(dfc["ts"]), side="right") - 1
    valid = idx >= 0
    idx_c = np.clip(idx, 0, len(c15) - 1)
    d15m = np.where(valid, d15[idx_c], 0)
    stc15m = np.where(valid, stc15[idx_c], np.nan)
    return d15m, stc15m


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    n = len(df)
    if n == 0:  # pi.shift1 cannot index an empty array (the locked v45_amb fails there too)
        return np.zeros(0, bool), np.zeros(0, bool)
    df = df.reset_index(drop=True)
    htf, dfh = htf_frame(df, tf)
    h5, l5, c5 = _f(df["high"]), _f(df["low"]), _f(df["close"])
    _lm, dm = pi.exchange_supertrend(h5, l5, c5, 14, p["st_mult_main"])
    _ls, dsx = pi.exchange_supertrend(h5, l5, c5, 14, p["st_mult_strict"])
    d15m, stc15m = htf_components(df, dfh, htf, p["htf_st_mult"])
    st_main_bull, st_main_bear = dm == 1, dm == -1
    st_str_bull, st_str_bear = dsx == 1, dsx == -1
    opposite = (st_main_bull & st_str_bear) | (st_main_bear & st_str_bull)
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
    raw = pi.pine_stoch(c5, h5, l5, p["stoch_len"])
    k33 = pi.pine_sma(raw, 3); d33 = pi.pine_sma(k33, 3)
    k43 = pi.pine_sma(raw, 4); d43 = pi.pine_sma(k43, 3)
    kr, dr = pi.stoch_rsi_kd(c5, 14, 14, 5, 3)
    with np.errstate(invalid="ignore"):
        g = [pi.crossover(k, d) & ((k <= 50) | (d <= 50)) for k, d in ((k33, d33), (k43, d43), (kr, dr))]
        dd = [pi.crossunder(k, d) & ((k >= 50) | (d >= 50)) for k, d in ((k33, d33), (k43, d43), (kr, dr))]
    any_long_now = np.logical_or.reduce(g) & weak_neg
    any_short_now = np.logical_or.reduce(dd) & weak_pos
    opp_long = f15_bull & stc_long_ok & opposite
    opp_short = f15_bear & stc_short_ok & opposite
    b_long = opp_long & chop_bear & any_long_now
    b_short = opp_short & chop_bull & any_short_now
    c_long = opp_long & chop_bear & ac_below & ac_up & ao_below & ao_down
    c_short = opp_short & chop_bull & ac_above & ac_down & ao_above & ao_up
    long = np.asarray(b_long & ~c_long, dtype=bool)
    short = np.asarray(b_short & ~c_short, dtype=bool) & ~long
    return long, short
