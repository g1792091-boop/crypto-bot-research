"""Parameter re-implementation of S2_ST_ROC for the sensitivity study (PREREG_ENTRY.md section 4, C).

``signals(df, tf)`` with no overrides reproduces ``strategies.s2_supertrend_roc`` bar for bar (plus the
``short & ~long`` step of sweep_lib._clean). Locked code:

    line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    r = fg.roc(df["close"], 9)
    long  = dir > 0 & r > 0 & (supertrend flip up   | r crosses above 0)
    short = dir < 0 & r < 0 & (supertrend flip down | r crosses below 0)

Not a parameter here: the ROC zero line (a threshold at its own neutral point, so every variant equals the
default). The rule does not depend on the timeframe.
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
from strategies import _f, cross_above, cross_below, ge, gt, le, lt  # noqa: E402

NAME = "S2_ST_ROC"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/strategies.py:s2_supertrend_roc"

PARAMS = [
    {"name": "st_atr_len", "default": 10, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg_fast.supertrend(df, 10, 6.0): ATR length)"},
    {"name": "st_mult", "default": 6.0, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (fg_fast.supertrend(df, 10, 6.0): band multiplier)"},
    {"name": "roc_len", "default": 9, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.roc(df['close'], 9))"},
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
        if s["kind"] == "length":
            p[k] = int(p[k])
        else:
            p[k] = float(p[k])
    return p


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    _line, direction, _u, _l = fg_fast.supertrend(df, p["st_atr_len"], p["st_mult"])
    r = fg.roc(df["close"], p["roc_len"])
    d = _f(direction)
    st_flip_up = gt(d, 0) & le(pd.Series(d).shift(1), 0)
    st_flip_down = lt(d, 0) & ge(pd.Series(d).shift(1), 0)
    roc_up = cross_above(r, 0.0)
    roc_down = cross_below(r, 0.0)
    long = gt(d, 0) & gt(r, 0) & (st_flip_up | roc_up)
    short = lt(d, 0) & lt(r, 0) & (st_flip_down | roc_down)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
