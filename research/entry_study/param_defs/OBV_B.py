"""Parameter re-implementation of OBV_B for the sensitivity study (PREREG_ENTRY.md section 4, C).

``signals(df, tf)`` with no overrides reproduces ``strategies.obv_b`` bar for bar (plus the
``short & ~long`` step of sweep_lib._clean). Locked code (third_party/sweep/harness/vendor/strategies.py:obv_b,
called with its defaults break_len=9, stc_ob=70, stc_os=30 on every timeframe):

    o = pi.obv(close, volume);  break_ma = pi.pine_sma(o, 9)
    _ao, ac = pi.ao_ac(high, low, 5, 34, 5);  ac_p = pi.shift1(ac)
    stc_v = pi.stc(close, 12, 26, 50, 0.5)
    long  = crossover(o, break_ma)  & (ac > 0) & (ac > ac_p) & (stc_v < 70)
    short = crossunder(o, break_ma) & (ac < 0) & (ac < ac_p) & (stc_v > 30)   ;  short &= ~long

Parameters (the numbers that shape the entry):
  break_len  9    OBV moving-average length (the trigger is OBV crossing this average)
  ao_fast    5    fast SMA of the Awesome Oscillator behind AC (AO = SMA5(hl2) - SMA34(hl2))
  ao_slow    34   slow SMA of the Awesome Oscillator
  ac_len     5    AC smoothing (AC = AO - SMA5(AO)); AC sign and slope are the momentum filter
Not parameters here: the STC filter (70 / 30, lengths 12/26/50, factor 0.5). Chosen by how much a number moves
the entries (signal flags only, no outcome): on BTC 1h (last 5000 bars, 202 signals) the x0.5..x1.5 moves of
the STC level change 5-12 signal bars, those of ao_fast 86-169, break_len 115-200, ao_slow 51-92, ac_len 39-103,
so the STC level would be trivially "flat" in the sensitivity study.
The rule does not depend on the timeframe (obv_b is called with the same defaults on every timeframe).
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
from strategies import _f  # noqa: E402

NAME = "OBV_B"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/strategies.py:obv_b"
STC_ARGS = (12, 26, 50, 0.5)      # locked, not varied
STC_OB, STC_OS = 70.0, 30.0       # locked, not varied (obv_b defaults stc_ob / stc_os)

PARAMS = [
    {"name": "break_len", "default": 9, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (break_ma = pi.pine_sma(o, break_len) with break_len=9; up = pi.crossover(o, break_ma))"},
    {"name": "ao_fast", "default": 5, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (_ao, ac = pi.ao_ac(high, low, 5, 34, 5): fast SMA of AO)"},
    {"name": "ao_slow", "default": 34, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (_ao, ac = pi.ao_ac(high, low, 5, 34, 5): slow SMA of AO)"},
    {"name": "ac_len", "default": 5, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (_ao, ac = pi.ao_ac(high, low, 5, 34, 5): AC = AO - SMA(AO, 5))"},
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
    if n == 0:  # pi.shift1 cannot index an empty array (the locked obv_b fails there too)
        return np.zeros(0, bool), np.zeros(0, bool)
    high, low, close = _f(df["high"]), _f(df["low"]), _f(df["close"])
    vol = _f(df["volume"])
    o = pi.obv(close, vol)
    break_ma = pi.pine_sma(o, p["break_len"])
    _ao, ac = pi.ao_ac(high, low, p["ao_fast"], p["ao_slow"], p["ac_len"])
    ac_p = pi.shift1(ac)
    stc_v = pi.stc(close, *STC_ARGS)
    with np.errstate(invalid="ignore"):
        ac_pos_rising = (ac > 0.0) & (ac > ac_p)
        ac_neg_falling = (ac < 0.0) & (ac < ac_p)
        stc_long_ok = stc_v < STC_OB
        stc_short_ok = stc_v > STC_OS
    up, down = pi.crossover(o, break_ma), pi.crossunder(o, break_ma)
    long = np.asarray(up & ac_pos_rising & stc_long_ok, dtype=bool)
    short = np.asarray(down & ac_neg_falling & stc_short_ok, dtype=bool) & ~long
    return long, short
