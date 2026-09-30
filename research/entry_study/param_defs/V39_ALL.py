"""Parameter re-implementation of V39_ALL for the sensitivity study (PREREG_ENTRY.md section 4, C).

``signals(df, tf)`` with no overrides reproduces ``strategies.v39_all`` (= v39_signals(df, stc_filter=False),
ALL_L / ALL_S & ~ALL_L) bar for bar. The body below is the locked v39_signals with four numbers threaded
through; everything else (the sequential stochastic-cross memory of 4 bars, the 2-bar cooldown shared by
all entry types, the AC-first entry, the D16 cross) is copied unchanged.

Locked code (third_party/sweep/harness/vendor/strategies.py:v39_signals):
    ST(10, 3) and ST(10, 6) directions, DMI(20) +DI/-DI, ADX(20, 20) in [10, 60], chop angle(34, 30, 25),
    MACD(12, 26, 9) histogram < 0 and rising (long), AO/AC(5, 34, 5) condition,
    type A trigger: armed golden cross of Stoch 14 K4/D2, Stoch 14 K5/D2 or StochRSI 14/14/3/3 (cross at/under
    50, remembered 4 bars) or DMI(16) +DI crossing above -DI; needs +DI20 - -DI20 >= 2 and chop angle >= 2;
    type B (AC first): ST(10, 3) up, ADX >= 10, |+DI20 - -DI20| >= 2, |chop angle| >= 2, first bar of AC < 0
    rising while AO < 0 falling.  Shorts mirror.

Parameters:
  st_mult    3.0  multiplier of the ST(10, 3) SuperTrend (its direction gates both entry types)
  dmi_len    20   DI length of DMI(20) and both lengths of ADX(20, 20) (the same 20 in all three places)
  dmi_gap    2.0  minimum +DI20 - -DI20 gap (the same 2.0 in the type-A directional gap and the type-B
                  absolute gap); threshold_abs: variants m * 2.0
  stoch_len  14   look-back of the raw stochastic behind the S42 (K4/D2) and S52 (K5/D2) triggers
Not varied: ST(10, 6), the ATR length 10, ADX 10/60, the chop thresholds (the chop angle is a whole number of
degrees, so x0.75 / x1.25 of 2.0 would not change the rule), StochRSI 14/14/3/3, DMI(16), MACD, AO/AC, the
4-bar memory and the 2-bar cooldown. The rule does not depend on the timeframe.
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

sweepsig.lib()  # hash-checked locked code; puts the vendored indicator modules on sys.path

import pine_indicators as pi  # noqa: E402
from strategies import _f, shift_bool  # noqa: E402

NAME = "V39_ALL"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/strategies.py:v39_signals (via v39_all)"

PARAMS = [
    {"name": "st_mult", "default": 3.0, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (_l3, d3 = pi.exchange_supertrend(high, low, close, 10, 3.0))"},
    {"name": "dmi_len", "default": 20, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (plus20, minus20 = pi.dmi(high, low, close, 20); adx20 = pi.adx(high, low, close, 20, 20))"},
    {"name": "dmi_gap", "default": 2.0, "kind": "threshold_abs", "neutral": None,
     "where": f"{_WHERE} (dmi_long_gap: (plus20 - minus20) >= 2.0; dmi_short_gap; acfirst_anti: gap >= 2.0)"},
    {"name": "stoch_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (raw = pi.pine_stoch(close, high, low, 14) behind k42/d42 and k52/d52)"},
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


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    n = len(df)
    if n == 0:  # pi.shift1 cannot index an empty array (the locked v39_all fails there too)
        return np.zeros(0, bool), np.zeros(0, bool)
    high, low, close = _f(df["high"]), _f(df["low"]), _f(df["close"])
    _l3, d3 = pi.exchange_supertrend(high, low, close, 10, p["st_mult"])
    _l6, d6 = pi.exchange_supertrend(high, low, close, 10, 6.0)
    st3_bull, st3_bear = d3 == 1, d3 == -1
    st6_bull, st6_bear = d6 == 1, d6 == -1
    _ml, _ms, hist = pi.pine_macd(close, 12, 26, 9)
    hist_prev = pi.shift1(hist)
    with np.errstate(invalid="ignore"):
        macd_weak_neg = (hist < 0.0) & (hist > hist_prev)
        macd_weak_pos = (hist > 0.0) & (hist < hist_prev)
    stc_long_ok = np.ones(n, dtype=bool)   # stc_filter=False (v39_all)
    stc_short_ok = np.ones(n, dtype=bool)
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
    plus20, minus20 = pi.dmi(high, low, close, p["dmi_len"])
    plus16, minus16 = pi.dmi(high, low, close, 16)
    adx20 = pi.adx(high, low, close, p["dmi_len"], p["dmi_len"])
    g = p["dmi_gap"]
    with np.errstate(invalid="ignore"):
        dmi20_bull, dmi20_bear = plus20 > minus20, minus20 > plus20
        d16_up = pi.crossover(plus16, minus16)
        d16_down = pi.crossunder(plus16, minus16)
        four_long = st3_bull & st6_bull & dmi20_bull & chop_bull
        four_short = st3_bear & st6_bear & dmi20_bear & chop_bear
        adx_min_ok = adx20 >= 10.0
        adx_max_ok = adx20 <= 60.0
        gap = np.abs(plus20 - minus20)
        dmi_long_gap = dmi20_bull & ((plus20 - minus20) >= g)
        dmi_short_gap = dmi20_bear & ((minus20 - plus20) >= g)
        chop_long_angle = chop >= 2.0
        chop_short_angle = chop <= -2.0
        chop_abs = np.abs(chop) >= 2.0
    anti_long = adx_max_ok & adx_min_ok & dmi_long_gap & chop_long_angle
    anti_short = adx_max_ok & adx_min_ok & dmi_short_gap & chop_short_angle
    acfirst_anti = adx_min_ok & (gap >= g) & chop_abs
    raw = pi.pine_stoch(close, high, low, p["stoch_len"])
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

    # sequential part (copied from the locked loop): cross memory + cooldown
    armed_long = {k: False for k in oscs}
    armed_short = {k: False for k in oscs}
    armed_long_bar = {k: -1 for k in oscs}
    armed_short_bar = {k: -1 for k in oscs}
    last_long_bar, last_short_bar = -10**9, -10**9
    cooldown = 2
    memory = 4
    all_long = np.zeros(n, dtype=bool)
    all_short = np.zeros(n, dtype=bool)
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
                fired_long = True
                armed_long[k] = False; armed_long_bar[k] = -1
            if common_short and armed_short[k] and od["dstate"][i] and od["scenter"][i]:
                fired_short = True
                armed_short[k] = False; armed_short_bar[k] = -1
        if common_long and d16_up[i]:
            fired_long = True
        if common_short and d16_down[i]:
            fired_short = True
        acf_long_base = st3_bull[i] and acfirst_anti[i] and long_cd and stc_long_ok[i]
        acf_short_base = st3_bear[i] and acfirst_anti[i] and short_cd and stc_short_ok[i]
        if acf_long_base and ac_neg_up_first[i] and ao_neg_down[i]:
            fired_long = True
        if acf_short_base and ac_pos_down_first[i] and ao_pos_up[i]:
            fired_short = True
        if fired_long:
            last_long_bar = i
            all_long[i] = True
        if fired_short:
            last_short_bar = i
            all_short[i] = True
    return all_long, all_short & ~all_long
