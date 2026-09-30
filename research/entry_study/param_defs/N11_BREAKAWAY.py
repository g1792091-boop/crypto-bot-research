"""Parameter re-implementation of N11_BREAKAWAY for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:n11 (variant 0; registered in sweep_lib.REGISTRY
through APPROX12 / _wrap_port, no timeframe scaling), a = ATR14 of the signal bar (ports12._base),
b = close - open, bar 5 = the signal bar t, B1..B5 = bodies of bars t-4 .. t:

    O2, C1, C2 = o[t-3], c[t-4], c[t-3]
    upp, dnp = _prior_dir(c, 4, 5, 0) = c[t-5] > c[t-9], c[t-5] < c[t-9]
    bull = dnp & (B1 < 0) & (-B1 >= 0.8 a) & (B2 < 0) & (O2 <= C1 + 0.05 a)
           & (|B3| <= 0.4 a) & (|B4| <= 0.4 a) & (B5 > 0) & (B5 >= 0.8 a) & (c > C2)
    bear = upp & (B1 > 0) & (B1 >= 0.8 a) & (B2 > 0) & (O2 >= C1 - 0.05 a)
           & (|B3| <= 0.4 a) & (|B4| <= 0.4 a) & (B5 < 0) & (-B5 >= 0.8 a) & (c < C2)
    long, short = bull, bear & ~bull      (ports12._pack and sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar. Parameters varied:
  big_body    the 'long body' size 0.8 ATR14, used by bar 1 and bar 5 (one number in the locked code,
              moved together)
  small_body  the 'small body' cap 0.4 ATR14 of bars 3 and 4
  gap_tol     the bar-2 open tolerance 0.05 ATR14 (O2 <= C1 + 0.05 a; mirror for shorts)
  prior_n     the prior-trend span 5: c[t-5] vs c[t-4-n]
Not varied: ATR length 14.

Variant rule (PREREG section 4): multipliers x0.5, x0.75, x1.25, x1.5 of the locked value, one parameter
at a time. 'length' -> round half up, min 2; 'mult' / 'threshold_abs' -> m * default;
'threshold_neutral' -> neutral + m * (default - neutral). Floats are rounded to 12 decimals.
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

NAME = "N11_BREAKAWAY"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/ports12.py:n11"
FIRST_LAG = 4      # the pattern's first bar is t-4
ATR_LEN = 14       # locked (ports12._base), not varied

PARAMS = [
    {"name": "big_body", "default": 0.8, "kind": "threshold_abs", "neutral": None,
     "where": _WHERE + " (-B1 >= 0.8 * a and B5 >= 0.8 * a; shorts B1 >= 0.8 * a and -B5 >= 0.8 * a)"},
    {"name": "small_body", "default": 0.4, "kind": "threshold_abs", "neutral": None,
     "where": _WHERE + " (np.abs(B3) <= 0.4 * a and np.abs(B4) <= 0.4 * a)"},
    {"name": "gap_tol", "default": 0.05, "kind": "threshold_abs", "neutral": None,
     "where": _WHERE + " (O2 <= C1 + 0.05 * a; shorts O2 >= C1 - 0.05 * a)"},
    {"name": "prior_n", "default": 5, "kind": "length", "neutral": None,
     "where": _WHERE + " (_prior_dir(c, 4, 5, variant): c[t-5] vs c[t-4-5])"},
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
    return {k: (int(v[k]) if _P[k]["kind"] == "length" else float(v[k])) for k in _P}


def _sh(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if k == 0:
        out[:] = x
    elif k < len(x):
        out[k:] = x[:len(x) - k]
    return out


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    o, c = df["open"].to_numpy(dtype=float), df["close"].to_numpy(dtype=float)
    a = fg.atr(df, ATR_LEN).to_numpy(dtype=float)
    b = c - o
    B1, B2, B3, B4, B5 = (_sh(b, k) for k in (4, 3, 2, 1, 0))
    O2, C1, C2 = _sh(o, 3), _sh(c, 4), _sh(c, 3)
    last, first = _sh(c, FIRST_LAG + 1), _sh(c, FIRST_LAG + p["prior_n"])
    big, small, gap = p["big_body"], p["small_body"], p["gap_tol"]
    with np.errstate(invalid="ignore"):
        upp, dnp = last > first, last < first
        bull = dnp & (B1 < 0) & (-B1 >= big * a) & (B2 < 0) & (O2 <= C1 + gap * a) \
            & (np.abs(B3) <= small * a) & (np.abs(B4) <= small * a) & (B5 > 0) & (B5 >= big * a) & (c > C2)
        bear = upp & (B1 > 0) & (B1 >= big * a) & (B2 > 0) & (O2 >= C1 - gap * a) \
            & (np.abs(B3) <= small * a) & (np.abs(B4) <= small * a) & (B5 < 0) & (-B5 >= big * a) & (c < C2)
    long = np.asarray(bull, dtype=bool)
    short = np.asarray(bear, dtype=bool) & ~long
    return long, short
