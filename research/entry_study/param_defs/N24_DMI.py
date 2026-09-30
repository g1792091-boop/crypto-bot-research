"""Parameter re-implementation of N24_DMI for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/strategies.py:n24_dmi (registered in
sweep_lib.REGISTRY through EXACT19, no timeframe scaling):

    adx, plus, minus = fg.adx_dmi(df, 14)        # = fg.dmi_adx(df, 14, 14): DI length, ADX smoothing
    long  = adx >= 25.0 & cross_above(plus, minus)
    short = adx <= 25.0 & cross_above(minus, plus)
    short &= ~long                     (in the strategy and again in sweep_lib._clean)

``fg.adx_dmi(df, length)`` passes its one length to both ``dmi_adx`` arguments; they are varied
separately here (the DI length sets when the +DI / -DI cross happens, the ADX smoothing sets the
filter), with the other one kept at 14. The level 25 appears twice in the locked code with opposite
meaning (long needs ADX >= 25, short needs ADX <= 25), so the two sides are varied separately.
ADX has no neutral point (0 = no trend), so both levels are 'threshold_abs'.

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar (checked on all
6 coins x 15m/1h/4h, periods 1-2 and 3).

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
import fg_indicators as fg  # noqa: E402
from strategies import cross_above, ge, le  # noqa: E402

NAME = "N24_DMI"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/strategies.py:n24_dmi"

PARAMS = [
    {"name": "di_len", "default": 14, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.adx_dmi(df, 14) -> fg.dmi_adx(df, 14, 14): di_length, the +DI/-DI and ATR smoothing)"},
    {"name": "adx_len", "default": 14, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.adx_dmi(df, 14) -> fg.dmi_adx(df, 14, 14): adx_smoothing)"},
    {"name": "adx_long_min", "default": 25.0, "kind": "threshold_abs", "neutral": None,
     "where": _WHERE + " (long_ok = ge(adx_line, 25.0) & plus_up)"},
    {"name": "adx_short_max", "default": 25.0, "kind": "threshold_abs", "neutral": None,
     "where": _WHERE + " (short_ok = le(adx_line, 25.0) & minus_up)"},
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
    plus, minus, adx_line = fg.dmi_adx(df, p["di_len"], p["adx_len"])
    plus_up = cross_above(plus, minus)
    minus_up = cross_above(minus, plus)
    long = np.asarray(ge(adx_line, p["adx_long_min"]) & plus_up, dtype=bool)
    short = np.asarray(le(adx_line, p["adx_short_max"]) & minus_up, dtype=bool) & ~long
    return long, short
