"""Parameter re-implementation of N18_VWMA_MACD for the sensitivity study (PREREG_ENTRY.md section 4, C).

``signals(df, tf)`` with no overrides reproduces ``strategies.n18_vwma_macd`` bar for bar (plus the
``short & ~long`` step of sweep_lib._clean). Locked code:

    v = fg.vwma(df, 20);  ml, sl, h = fg.macd(close, 12, 26, 9)
    long  = synchronized([cross_above(ml, sl), close > v, h > h[-1], ml > 0], 2)
    short = synchronized([cross_below(ml, sl), close < v, h < h[-1], ml < 0], 2) & ~long

Not a parameter here: sync = 2. The MACD zero line is a fixed level (0 x anything = 0), so it has no
variant. One parameter is varied at a time, so every variant keeps macd_fast < macd_slow (fast at most
18 < 26; slow at least 13 > 12). The rule does not depend on the timeframe.
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
from strategies import cross_above, cross_below, gt, lt, synchronized  # noqa: E402

NAME = "N18_VWMA_MACD"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/strategies.py:n18_vwma_macd"
SYNC = 2  # locked, not varied

PARAMS = [
    {"name": "vwma_len", "default": 20, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (v = fg.vwma(df, 20))"},
    {"name": "macd_fast", "default": 12, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.macd(df['close'], 12, 26, 9): fast EMA)"},
    {"name": "macd_slow", "default": 26, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.macd(df['close'], 12, 26, 9): slow EMA)"},
    {"name": "macd_signal", "default": 9, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.macd(df['close'], 12, 26, 9): signal EMA)"},
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
    v = fg.vwma(df, p["vwma_len"])
    ml, sl, h = fg.macd(df["close"], p["macd_fast"], p["macd_slow"], p["macd_signal"])
    up, down = cross_above(ml, sl), cross_below(ml, sl)
    above, below = gt(df["close"], v), lt(df["close"], v)
    hist_up, hist_down = gt(h, h.shift(1)), lt(h, h.shift(1))
    long = np.asarray(synchronized([up, above, hist_up, gt(ml, 0.0)], SYNC), dtype=bool)
    short = np.asarray(synchronized([down, below, hist_down, lt(ml, 0.0)], SYNC), dtype=bool) & ~long
    return long, short
