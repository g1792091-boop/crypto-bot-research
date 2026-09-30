"""Parameter re-implementation of N13_3OUTSIDE for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:n13 (variant 0; registered in sweep_lib.REGISTRY
through APPROX12 / _wrap_port, no timeframe scaling), a = ATR14 (ports12._base), b = close - open,
a pattern completes on bar j (bars j-2, j-1, j):

    upp, dnp = _prior_dir(c, 2, 5, 0) = c[j-3] > c[j-7], c[j-3] < c[j-7]
    B1, B2, B3 = b[j-2], b[j-1], b[j];  O1, C1, O2, C2 = o[j-2], c[j-2], o[j-1], c[j-1]
    bull = dnp & (B1 < 0) & (B2 > 0) & (B2 >= 0.5 a) & (O2 <= C1) & (C2 >= O1) & (B3 > 0) & (c > C2)
    bear = upp & (B1 > 0) & (B2 < 0) & (-B2 >= 0.5 a) & (O2 >= C1) & (C2 <= O1) & (B3 < 0) & (c < C2)
    ph3, pl3 = rolling 3-bar max(high), min(low)
    for lag in (2, 1):   L |= bull[i-lag] & (c > ph3[i-lag]) & (c1 <= ph3[i-lag])
                         S |= bear[i-lag] & (c < pl3[i-lag]) & (c1 >= pl3[i-lag])
    short &= ~long                        (ports12._pack and sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar. Parameters varied:
  engulf_min  the engulfing bar's minimum body 0.5 ATR14
  prior_n     the prior-trend span 5: c[j-3] vs c[j-2-n]
  atr_len     the ATR length 14 that scales the engulfing-body threshold (the locked ATR is used by
              no other entry condition of this strategy)
Not varied: the 2-bar breakout window (lags 1 and 2; x0.5 / x0.75 round back to 2 and x1.25 / x1.5
both round to 3, so it would give one distinct variant only) and the 3-bar pattern high / low (fixed by
the pattern).

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
from strategies import shift_bool  # noqa: E402

NAME = "N13_3OUTSIDE"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/ports12.py:n13"
FIRST_LAG = 2      # the pattern's first bar is j-2
LAGS = (2, 1)      # breakout 2 or 1 bars after the pattern, locked, not varied

PARAMS = [
    {"name": "engulf_min", "default": 0.5, "kind": "threshold_abs", "neutral": None,
     "where": _WHERE + " (bull: B2 >= 0.5 * a; bear: -B2 >= 0.5 * a)"},
    {"name": "prior_n", "default": 5, "kind": "length", "neutral": None,
     "where": _WHERE + " (_prior_dir(c, 2, 5, variant): c[j-3] vs c[j-2-5])"},
    {"name": "atr_len", "default": 14, "kind": "length", "neutral": None,
     "where": "third_party/sweep/harness/vendor/ports12.py:_base (a = fg.atr(df, 14)) used by n13's "
              "engulfing-body threshold"},
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


def _roll(x: np.ndarray, n: int, how: str) -> np.ndarray:
    r = pd.Series(x).rolling(n, min_periods=n)
    return (r.max() if how == "max" else r.min()).to_numpy()


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    a = fg.atr(df, p["atr_len"]).to_numpy(dtype=float)
    b = c - o
    last, first = _sh(c, FIRST_LAG + 1), _sh(c, FIRST_LAG + p["prior_n"])
    B1, B2, B3 = _sh(b, 2), _sh(b, 1), b
    O1, C1, O2, C2 = _sh(o, 2), _sh(c, 2), _sh(o, 1), _sh(c, 1)
    em = p["engulf_min"]
    with np.errstate(invalid="ignore"):
        upp, dnp = last > first, last < first
        bull = dnp & (B1 < 0) & (B2 > 0) & (B2 >= em * a) & (O2 <= C1) & (C2 >= O1) & (B3 > 0) & (c > C2)
        bear = upp & (B1 > 0) & (B2 < 0) & (-B2 >= em * a) & (O2 >= C1) & (C2 <= O1) & (B3 < 0) & (c < C2)
    ph3, pl3 = _roll(h, 3, "max"), _roll(l, 3, "min")
    n = len(c)
    long = np.zeros(n, dtype=bool)
    short = np.zeros(n, dtype=bool)
    c1 = _sh(c, 1)
    for lag in LAGS:
        pb, pbr = shift_bool(bull, lag), shift_bool(bear, lag)
        PH, PL = _sh(ph3, lag), _sh(pl3, lag)
        with np.errstate(invalid="ignore"):
            long |= pb & (c > PH) & (c1 <= PH)
            short |= pbr & (c < PL) & (c1 >= PL)
    short = short & ~long
    return long, short
