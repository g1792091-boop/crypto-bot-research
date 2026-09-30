"""Parameter re-implementation of N19_FIB_CHOP for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:n19 (variant 0; registered in sweep_lib.REGISTRY
through APPROX12 / _wrap_port, no timeframe scaling):

    o, h, l, c, a = _base(df)                                   # a = fg.atr(df, 14)
    hh = _sh(_roll_max(h, 34), 3);  ll = _sh(_roll_min(l, 34), 3)
    R = hh - ll;  mid = ll + 0.5 * R
    cz = fg.research_chop_zone(df, 34, 14)   # slope = (EMA34 - EMA34.shift(3)) / ATR14.replace(0, nan)
    g = cz in (GREEN, BLUE)  <=> slope >= 0.20;   r = cz in (RED, DARK_RED)  <=> slope <= -0.20
    L = (l <= mid + 0.2 * a) & (c > mid) & (c > o) & g
    S = (h >= mid - 0.2 * a) & (c < mid) & (c < o) & r;   S &= ~L

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar.

Parameters varied:
  range_len  34, the length of the high/low range (ending 3 bars ago) whose retracement line is used
  fib_level  0.5, the retracement depth. The long line is hh - fib_level * R (a pullback from the range high,
             computed as ll + (1 - fib_level) * R), the short line ll + fib_level * R (a bounce from the range
             low); both are the locked mid at 0.5. A deeper retracement is a larger fib_level on both sides.
  touch_atr  0.2, the touch tolerance: the low must reach within 0.2 ATR14 of the line (short: the high)
  slope_thr  0.20, the chop-zone slope a long needs (a short needs <= -slope_thr); threshold_abs because the
             slope's neutral point is 0, so m * default is also the distance from neutral
Not varied: the 3-bar range lag, the chop-zone EMA length 34 and its 3-bar slope (slope_thr is the filter's
threshold), ATR length 14, the candle-colour condition.
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
from strategies import _f  # noqa: E402

NAME = "N19_FIB_CHOP"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/ports12.py:n19"
RANGE_LAG = 3                  # locked, not varied
CHOP_EMA, ATR_LEN = 34, 14     # locked, not varied (fg.research_chop_zone(df, 34, 14); _base ATR14)
SLOPE_LAG = 3                  # locked inside fg.research_chop_zone

PARAMS = [
    {"name": "range_len", "default": 34, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (hh = _sh(_roll_max(h, 34), 3); ll = _sh(_roll_min(l, 34), 3))"},
    {"name": "fib_level", "default": 0.5, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (mid = ll + 0.5 * R: retracement depth; long line hh - f R, short line ll + f R)"},
    {"name": "touch_atr", "default": 0.2, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (l <= mid + 0.2 * a; h >= mid - 0.2 * a)"},
    {"name": "slope_thr", "default": 0.2, "kind": "threshold_abs", "neutral": None,
     "where": "third_party/sweep/harness/vendor/fg_indicators.py:research_chop_zone via ports12.py:n19 "
              "(GREEN/BLUE: slope >= 0.20; RED/DARK_RED: slope <= -0.20)"},
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


def _sh(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    o, h, l, c = (_f(df[k]) for k in ("open", "high", "low", "close"))
    atr_s = fg.atr(df, ATR_LEN)
    a = _f(atr_s)
    n = p["range_len"]
    hh = _sh(pd.Series(h).rolling(n, min_periods=n).max().to_numpy(), RANGE_LAG)
    ll = _sh(pd.Series(l).rolling(n, min_periods=n).min().to_numpy(), RANGE_LAG)
    R = hh - ll
    f = p["fib_level"]
    line_l = ll + (1.0 - f) * R       # == hh - f * R; the locked ll + 0.5 * R at f = 0.5
    line_s = ll + f * R
    base = fg.ema(df["close"], CHOP_EMA)
    slope = _f((base - base.shift(SLOPE_LAG)) / atr_s.replace(0, np.nan))
    t, thr = p["touch_atr"], p["slope_thr"]
    with np.errstate(invalid="ignore"):
        long = (l <= line_l + t * a) & (c > line_l) & (c > o) & (slope >= thr)
        short = (h >= line_s - t * a) & (c < line_s) & (c < o) & (slope <= -thr)
    long = np.asarray(long, dtype=bool)
    return long, np.asarray(short, dtype=bool) & ~long
