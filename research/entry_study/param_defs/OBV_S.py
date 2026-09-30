"""Parameter re-implementation of OBV_S for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/strategies.py:obv_s (sweep_lib.REGISTRY["OBV_S"] =
_wrap_exact(S.obv_s), called with its defaults stc_ob=70, stc_os=30; no timeframe scaling):

    o = pi.obv(close, volume);  trend_ma = pi.pine_sma(o, 30)
    _ao, ac = pi.ao_ac(high, low, 5, 34, 5)
    stc_v = pi.stc(close, 12, 26, 50, 0.5)
    for raw length in (11, 15, 9):  k = pine_sma(pine_stoch(close, high, low, length), 4); d = pine_sma(k, 3)
        golden = crossover(k, d) & finite(k) & finite(d);  dead = crossunder(k, d) & finite(k) & finite(d)
    long  = any golden & ac > 0 & stc_v < stc_ob & o > trend_ma
    short = any dead   & ac < 0 & stc_v > stc_os & o < trend_ma
    short &= ~long                     (in the strategy and again in sweep_lib._clean)

Parameters varied (up to 4), one per entry condition:
  obv_ma_len     30  OBV trend line (the OBV condition)
  stc_level      70  STC cap. obv_s exposes it as two keywords, stc_ob=70 (longs: STC < 70) and
                     stc_os=30 (shorts: STC > 30), mirror images around STC's neutral 50 (STC is a
                     0-100 stochastic of MACD); they are varied together as one 'threshold_neutral'
                     level L with neutral 50: longs STC < L, shorts STC > 100 - L (the STC condition)
  stoch_k_smooth  4  %K smoothing shared by the three stochastics (the trigger)
  ao_slow_len    34  slow SMA of the Awesome Oscillator inside AC (the AC condition)
Not varied: the raw stochastic lengths 11 / 15 / 9, the %D smoothing 3 (x0.5 and x0.75 both round
to 2), AO fast 5, AC length 5, STC (12, 26, 50, 0.5).

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar (checked on all
6 coins x 15m/1h/4h, periods 1-2 and 3). An empty frame gives empty arrays (the locked code
raises there).

Variant rule (PREREG section 4): multipliers x0.5, x0.75, x1.25, x1.5 of the locked value, one
parameter at a time. 'length' -> round half up, min 2; 'mult' / 'threshold_abs' -> m * default;
'threshold_neutral' -> neutral + m * (default - neutral).
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from paperbot import sweepsig  # noqa: E402

sweepsig.lib()  # hash-checked locked code; puts the vendored indicator modules on sys.path
import pine_indicators as pi  # noqa: E402
from strategies import _f  # noqa: E402

NAME = "OBV_S"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/strategies.py:obv_s"
STOCH_LENS = (11, 15, 9)   # locked, not varied
STOCH_D = 3                # locked, not varied
AO_FAST, AC_LEN = 5, 5     # locked, not varied
STC_NEUTRAL = 50.0

PARAMS = [
    {"name": "obv_ma_len", "default": 30, "kind": "length", "neutral": None,
     "where": _WHERE + " (trend_ma = pi.pine_sma(o, 30); obv_up = o > trend_ma)"},
    {"name": "stc_level", "default": 70.0, "kind": "threshold_neutral", "neutral": 50.0,
     "where": _WHERE + " (keywords stc_ob=70.0 / stc_os=30.0: stc_v < stc_ob for longs, stc_v > stc_os "
                       "for shorts; varied together, stc_os = 100 - stc_ob)"},
    {"name": "stoch_k_smooth", "default": 4, "kind": "length", "neutral": None,
     "where": _WHERE + " (k = pi.pine_sma(raw, 4) for the raw 11 / 15 / 9 stochastics)"},
    {"name": "ao_slow_len", "default": 34, "kind": "length", "neutral": None,
     "where": _WHERE + " (pi.ao_ac(high, low, 5, 34, 5): slow SMA of hl2 in AO, AC = AO - SMA5(AO))"},
]
_P = {p["name"]: p for p in PARAMS}


def _round_len(x: float) -> int:
    return max(2, int(math.floor(float(x) + 0.5)))


def _vary(p: dict, m: float):
    d, kind = p["default"], p["kind"]
    if kind == "length":
        return _round_len(m * d)
    if kind in ("mult", "threshold_abs"):
        return round(m * d, 12)
    if kind == "threshold_neutral":
        return round(p["neutral"] + m * (d - p["neutral"]), 12)
    raise ValueError(kind)


def variants(p) -> list:
    """The 4 override dicts for parameter ``p`` (name or PARAMS entry), in the order x0.5, x0.75,
    x1.25, x1.5."""
    spec = _P[p["name"] if isinstance(p, dict) else p]
    return [{spec["name"]: _vary(spec, m)} for m in MULTS]


def _resolve(overrides: dict) -> dict:
    bad = set(overrides) - set(_P)
    if bad:
        raise ValueError(f"{NAME}: unknown parameter(s) {sorted(bad)}")
    v = {k: p["default"] for k, p in _P.items()}
    v.update(overrides)
    out = {}
    for k, p in _P.items():
        out[k] = _round_len(v[k]) if p["kind"] == "length" else float(v[k])
    return out


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    if len(df) == 0:  # the locked obv_s raises on an empty frame (pi.shift1 indexes bar 0)
        return np.zeros(0, dtype=bool), np.zeros(0, dtype=bool)
    high, low, close = _f(df["high"]), _f(df["low"]), _f(df["close"])
    vol = _f(df["volume"])
    o = pi.obv(close, vol)
    trend_ma = pi.pine_sma(o, p["obv_ma_len"])
    _ao, ac = pi.ao_ac(high, low, AO_FAST, p["ao_slow_len"], AC_LEN)
    stc_v = pi.stc(close, 12, 26, 50, 0.5)
    stc_ob = p["stc_level"]
    stc_os = 2.0 * STC_NEUTRAL - stc_ob          # 30 at the locked 70
    with np.errstate(invalid="ignore"):
        ac_pos, ac_neg = ac > 0.0, ac < 0.0
        stc_long_ok = stc_v < stc_ob
        stc_short_ok = stc_v > stc_os
        obv_up, obv_down = o > trend_ma, o < trend_ma
    gcs, dcs = [], []
    for length in STOCH_LENS:
        raw = pi.pine_stoch(close, high, low, length)
        k = pi.pine_sma(raw, p["stoch_k_smooth"])
        d = pi.pine_sma(k, STOCH_D)
        gcs.append(pi.crossover(k, d) & np.isfinite(k) & np.isfinite(d))
        dcs.append(pi.crossunder(k, d) & np.isfinite(k) & np.isfinite(d))
    any_golden = np.logical_or.reduce(gcs)
    any_dead = np.logical_or.reduce(dcs)
    long = np.asarray(any_golden & ac_pos & stc_long_ok & obv_up, dtype=bool)
    short = np.asarray(any_dead & ac_neg & stc_short_ok & obv_down, dtype=bool) & ~long
    return long, short
