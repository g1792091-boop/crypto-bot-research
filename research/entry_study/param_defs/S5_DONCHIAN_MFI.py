"""Parameter re-implementation of S5_DONCHIAN_MFI for the sensitivity study (PREREG_ENTRY.md section 4, C).

``signals(df, tf)`` with no overrides reproduces ``strategies.s5_donchian_mfi`` bar for bar (plus the
``short & ~long`` step of sweep_lib._clean). Locked code:

    upper, middle, lower = fg.donchian_channel(df, 20, shift_previous=True)
    m = fg.mfi(df, 14)
    breakout_up / down = close crosses the previous-20-bar high / low
    mfi_up = m crosses above 30, mfi_down = m crosses below 70, sync = 3
    long  = recent(breakout_up, 3) & recent(mfi_up, 3) & close > upper & m > 30 & (breakout_up | mfi_up)
    short = recent(breakout_down, 3) & recent(mfi_down, 3) & close < lower & m < 70 & (breakout_down | mfi_down)

``mfi_level`` is the long level (30); the short level is its mirror 100 - mfi_level (70), so the variant
50 + m * (30 - 50) moves both levels the same distance from the neutral 50. The rule does not depend on the
timeframe.
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

import fg_indicators as fg  # noqa: E402
from strategies import cross_above, cross_below, ge, gt, le, lt, recent  # noqa: E402

NAME = "S5_DONCHIAN_MFI"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/strategies.py:s5_donchian_mfi"

PARAMS = [
    {"name": "dc_len", "default": 20, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.donchian_channel(df, 20, shift_previous=True))"},
    {"name": "mfi_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.mfi(df, 14))"},
    {"name": "mfi_level", "default": 30.0, "kind": "threshold_neutral", "neutral": 50.0,
     "where": f"{_WHERE} (cross_above(m, 30.0) / m > 30 for long; short uses the mirror 100 - level = 70)"},
    {"name": "sync", "default": 3, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (sync = 3: recent(breakout, sync) & recent(mfi_cross, sync))"},
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
    """The four override dicts (x0.5, x0.75, x1.25, x1.5) of parameter ``p`` (name or PARAMS entry).
    ``sync`` x0.5 and x0.75 both give 2 (min 2 / rounding); both are kept so every parameter has four."""
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
    lo_level = p["mfi_level"]
    hi_level = 100.0 - p["mfi_level"]
    upper, _middle, lower = fg.donchian_channel(df, p["dc_len"], shift_previous=True)
    m = fg.mfi(df, p["mfi_len"])
    close = df["close"]
    breakout_up = gt(close, upper) & le(close.shift(1), upper.shift(1))
    breakout_down = lt(close, lower) & ge(close.shift(1), lower.shift(1))
    mfi_up = cross_above(m, lo_level)
    mfi_down = cross_below(m, hi_level)
    sync = p["sync"]
    long_state = gt(close, upper) & gt(m, lo_level)
    short_state = lt(close, lower) & lt(m, hi_level)
    long = recent(breakout_up, sync) & recent(mfi_up, sync) & long_state & (breakout_up | mfi_up)
    short = recent(breakout_down, sync) & recent(mfi_down, sync) & short_state & (breakout_down | mfi_down)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
