"""Parameter re-implementation of N09_ALLIG_AROON for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/strategies.py:n09_alligator_aroon (registered in
sweep_lib.REGISTRY through EXACT19, no timeframe scaling):

    lips, teeth, jaw = fg.sma(close, 5), fg.sma(close, 8), fg.sma(close, 13)
    lips_above = lips > teeth & lips > jaw ;  a_up = lips_above & ~lips_above[1]   (mirror: below)
    up, down = fg_fast.aroon(df, 25) ;  ar_up = up crosses above down                (mirror: below)
    long  = recent(a_up, 2) & recent(ar_up, 2) & lips_above & up - down >= 0 & (a_up | ar_up)
    short = recent(a_down, 2) & recent(ar_down, 2) & lips_below & down - up >= 0 & (a_down | ar_down)
    short &= ~long                     (sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar (checked on all
6 coins x 15m/1h/4h, periods 1-2 and 3). The three alligator lengths are separate numbers in the
locked code and are varied one at a time. Note: lips_len x1.5 = 8 equals teeth_len, so the lips
line can never be strictly above (below) the teeth line and that variant has no signals; this is
what the pre-registered rule gives and it is kept, not repaired. Not varied: the sync window
(2 bars; x0.5/x0.75 round back to 2) and the Aroon spread level 0 (its neutral point).

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
import fg_fast  # noqa: E402
import fg_indicators as fg  # noqa: E402
from strategies import cross_above, cross_below, ge, gt, lt, recent, shift_bool  # noqa: E402

NAME = "N09_ALLIG_AROON"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/strategies.py:n09_alligator_aroon"

PARAMS = [
    {"name": "lips_len", "default": 5, "kind": "length", "neutral": None,
     "where": _WHERE + " (lips = fg.sma(close, 5))"},
    {"name": "teeth_len", "default": 8, "kind": "length", "neutral": None,
     "where": _WHERE + " (teeth = fg.sma(close, 8))"},
    {"name": "jaw_len", "default": 13, "kind": "length", "neutral": None,
     "where": _WHERE + " (jaw = fg.sma(close, 13))"},
    {"name": "aroon_len", "default": 25, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg_fast.aroon(df, 25))"},
]
_P = {p["name"]: p for p in PARAMS}
_SYNC = 2


def _round_len(x: float) -> int:
    return max(2, int(math.floor(float(x) + 0.5)))


def _vary(p: dict, m: float):
    d, kind = p["default"], p["kind"]
    if kind == "length":
        return [_round_len(m * v) for v in d] if isinstance(d, (list, tuple)) else _round_len(m * d)
    if kind in ("mult", "threshold_abs"):
        return round(m * d, 12)                      # 0.75 * 0.2 -> 0.15, not 0.15000000000000002
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
    return {k: int(v[k]) for k in _P}


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    close = df["close"]
    lips, teeth, jaw = fg.sma(close, p["lips_len"]), fg.sma(close, p["teeth_len"]), fg.sma(close, p["jaw_len"])
    lips_above = gt(lips, teeth) & gt(lips, jaw)
    lips_below = lt(lips, teeth) & lt(lips, jaw)
    a_up = lips_above & ~shift_bool(lips_above, 1)
    a_down = lips_below & ~shift_bool(lips_below, 1)
    up, down = fg_fast.aroon(df, p["aroon_len"])
    up_a, down_a = up.to_numpy(dtype=float), down.to_numpy(dtype=float)
    ar_up, ar_down = cross_above(up, down), cross_below(up, down)
    long_state = lips_above & ge(up_a - down_a, 0.0)
    short_state = lips_below & ge(down_a - up_a, 0.0)
    long = recent(a_up, _SYNC) & recent(ar_up, _SYNC) & long_state & (a_up | ar_up)
    short = recent(a_down, _SYNC) & recent(ar_down, _SYNC) & short_state & (a_down | ar_down)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
