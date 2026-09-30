"""Parameter re-implementation of N03_ADX_GC for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/strategies.py:n03_adx_golden_cross (registered in
sweep_lib.REGISTRY through EXACT19, no timeframe scaling):

    ef, es = fg.ema(close, 50), fg.ema(close, 200)
    _p, _m, adx = fg.dmi_adx(df, 14, 14)
    gc, dc = EMA50 crosses above / below EMA200;  adx_evt = ADX crosses above 25
    long  = recent(gc, 3) & recent(adx_evt, 3) & ADX >= 25 & (gc | adx_evt)
    short = recent(dc, 3) & recent(adx_evt, 3) & ADX >= 25 & (dc | adx_evt)
    short &= ~long                     (sweep_lib._clean; both can hold after an EMA whipsaw)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar (checked on all
6 coins x 15m/1h/4h, periods 1-2 and 3). ``adx_level`` moves both the cross event and the
ADX >= level state (they use the same 25 in the locked code); ``adx_len`` sets both the DI length
and the ADX smoothing (both 14 in the locked code). The sync window (3 bars) is not varied: PREREG
section 4 allows at most 4 parameters and the two EMA lengths and the ADX length and level were chosen.

Variant rule (PREREG section 4): multipliers x0.5, x0.75, x1.25, x1.5 of the locked value, one
parameter at a time. 'length' -> round half up, min 2; 'mult' / 'threshold_abs' -> m * default;
'threshold_neutral' -> neutral + m * (default - neutral). ADX has no neutral point, so its level is
'threshold_abs'.
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
from strategies import cross_above, cross_below, ge, recent  # noqa: E402

NAME = "N03_ADX_GC"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/strategies.py:n03_adx_golden_cross"

PARAMS = [
    {"name": "ema_fast", "default": 50, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.ema(close, 50))"},
    {"name": "ema_slow", "default": 200, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.ema(close, 200))"},
    {"name": "adx_len", "default": 14, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.dmi_adx(df, 14, 14): DI length and ADX smoothing, moved together)"},
    {"name": "adx_level", "default": 25.0, "kind": "threshold_abs", "neutral": None,
     "where": _WHERE + " (cross_above(adx, 25.0) and ge(adx, 25.0))"},
]
_P = {p["name"]: p for p in PARAMS}
_SYNC = 3


def _round_len(x: float) -> int:
    return max(2, int(math.floor(float(x) + 0.5)))


def _vary(p: dict, m: float):
    d, kind = p["default"], p["kind"]
    if kind == "length":
        return [_round_len(m * v) for v in d] if isinstance(d, (list, tuple)) else _round_len(m * d)
    if kind in ("mult", "threshold_abs"):
        return m * d
    if kind == "threshold_neutral":
        return p["neutral"] + m * (d - p["neutral"])
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
    return dict(ema_fast=int(v["ema_fast"]), ema_slow=int(v["ema_slow"]), adx_len=int(v["adx_len"]),
                adx_level=float(v["adx_level"]))


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    ef = fg.ema(df["close"], p["ema_fast"])
    es = fg.ema(df["close"], p["ema_slow"])
    _p, _m, adx = fg.dmi_adx(df, p["adx_len"], p["adx_len"])
    gc, dc = cross_above(ef, es), cross_below(ef, es)
    adx_evt = cross_above(adx, p["adx_level"])
    state = ge(adx, p["adx_level"])
    adx_recent = recent(adx_evt, _SYNC)
    long = recent(gc, _SYNC) & adx_recent & state & (gc | adx_evt)
    short = recent(dc, _SYNC) & adx_recent & state & (dc | adx_evt)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
