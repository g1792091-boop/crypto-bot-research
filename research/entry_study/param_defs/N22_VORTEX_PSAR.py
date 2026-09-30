"""Parameter re-implementation of N22_VORTEX_PSAR for the sensitivity study (PREREG_ENTRY.md section 4, C).

``signals(df, tf)`` with no overrides reproduces ``strategies.n22_vortex_psar`` bar for bar (plus the
``short & ~long`` step of sweep_lib._clean). Locked code:

    plus, minus = fg.vortex_indicator(df, 14)
    psar, _d = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.20)
    long  = close > psar & cross_above(plus, minus)
    short = close < psar & cross_below(plus, minus) & ~long

The three SAR numbers are acceleration factors (start, step, cap); a variant multiplies one of them by m
(kind 'mult'), the other two stay at their defaults. The rule does not depend on the timeframe.
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

import fg_fast  # noqa: E402
import fg_indicators as fg  # noqa: E402
from strategies import cross_above, cross_below, gt, lt  # noqa: E402

NAME = "N22_VORTEX_PSAR"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/strategies.py:n22_vortex_psar"

PARAMS = [
    {"name": "vi_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.vortex_indicator(df, 14))"},
    {"name": "psar_start", "default": 0.02, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (fg_fast.parabolic_sar(df, 0.02, 0.02, 0.20): initial acceleration)"},
    {"name": "psar_step", "default": 0.02, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (fg_fast.parabolic_sar(df, 0.02, 0.02, 0.20): acceleration step)"},
    {"name": "psar_max", "default": 0.20, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (fg_fast.parabolic_sar(df, 0.02, 0.02, 0.20): acceleration cap)"},
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
    df = df.reset_index(drop=True)
    plus, minus = fg.vortex_indicator(df, p["vi_len"])
    psar, _d = fg_fast.parabolic_sar(df, p["psar_start"], p["psar_step"], p["psar_max"])
    up, down = cross_above(plus, minus), cross_below(plus, minus)
    above, below = gt(df["close"], psar), lt(df["close"], psar)
    long = np.asarray(above & up, dtype=bool)
    short = np.asarray(below & down, dtype=bool) & ~long
    return long, short
