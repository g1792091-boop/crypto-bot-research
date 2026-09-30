"""Parameter re-implementation of N23_HA_ST for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/strategies.py:n23_heikin_supertrend (registered in
sweep_lib.REGISTRY through EXACT19, no timeframe scaling):

    ha = fg_fast.heikin_ashi(df)
    _st, up = fg_fast.supertrend_v2(df, 10, 6.0)                   # ATR length, band multiplier
    rng = (ha_high - ha_low).replace(0, NaN)
    no_lower = (min(ha_open, ha_close) - ha_low) / rng <= 0.02      # wick tolerance
    no_upper = (ha_high - max(ha_open, ha_close)) / rng <= 0.02
    long_ok  = ha_close > ha_open & no_lower & up
    short_ok = ha_close < ha_open & no_upper & ~up
    long  = long_ok & ~long_ok[1]          short = short_ok & ~short_ok[1]      (fresh)
    short &= ~long                     (in the strategy and again in sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar (checked on all
6 coins x 15m/1h/4h, periods 1-2 and 3). Not varied: the 1-bar "fresh" test (structural) and the
Heikin-Ashi construction (no parameter).

Variant rule (PREREG section 4): multipliers x0.5, x0.75, x1.25, x1.5 of the locked value, one
parameter at a time. 'length' -> round half up, min 2; 'mult' / 'threshold_abs' -> m * default;
'threshold_neutral' -> neutral + m * (default - neutral). The wick tolerance is a fraction of the HA
range with a natural zero, so it is 'threshold_abs'.
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
import fg_fast  # noqa: E402
from strategies import _b, gt, le, lt, shift_bool  # noqa: E402

NAME = "N23_HA_ST"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/strategies.py:n23_heikin_supertrend"

PARAMS = [
    {"name": "st_atr_len", "default": 10, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg_fast.supertrend_v2(df, 10, 6.0): ATR length of the supertrend)"},
    {"name": "st_mult", "default": 6.0, "kind": "mult", "neutral": None,
     "where": _WHERE + " (fg_fast.supertrend_v2(df, 10, 6.0): band multiplier)"},
    {"name": "wick_tol", "default": 0.02, "kind": "threshold_abs", "neutral": None,
     "where": _WHERE + " (no_lower / no_upper: HA wick / HA range <= 0.02)"},
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
    df = df.reset_index(drop=True)
    ha = fg_fast.heikin_ashi(df)
    _st, up = fg_fast.supertrend_v2(df, p["st_atr_len"], p["st_mult"])
    up = _b(up)
    rng = (ha["ha_high"] - ha["ha_low"]).replace(0, np.nan)
    body_min = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).min(axis=1)
    body_max = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).max(axis=1)
    no_lower = le((body_min - ha["ha_low"]) / rng, p["wick_tol"])
    no_upper = le((ha["ha_high"] - body_max) / rng, p["wick_tol"])
    green = gt(ha["ha_close"], ha["ha_open"])
    red = lt(ha["ha_close"], ha["ha_open"])
    long_ok = green & no_lower & up
    short_ok = red & no_upper & (~up)
    long = np.asarray(long_ok & ~shift_bool(long_ok, 1), dtype=bool)
    short = np.asarray(short_ok & ~shift_bool(short_ok, 1), dtype=bool) & ~long
    return long, short
