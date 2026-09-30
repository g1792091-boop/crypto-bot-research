"""Parameter re-implementation of S3_CMO_SANDWICH for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:s3 (variant 0; registered in sweep_lib.REGISTRY
through APPROX12 / _wrap_port, no timeframe scaling), a = ATR14, b = close - open:

    b1, b2, b3 = b[-2], b[-1], b;  h1, h3, l1, l3 = high[-2], high, low[-2], low
    up_prior, dn_prior = c[-3] > c[-2-5], c[-3] < c[-2-5]          (_prior_dir(c, 2, 5, 0))
    bodies = |b1|, |b2|, |b3| >= 0.08 a
    bear = up_prior & bodies & b1 > 0 & b2 < 0 & b3 > 0 & |h1 - h3| <= 0.3 a & c <= max(h1, h3) + 0.075 a
    bull = dn_prior & bodies & b1 < 0 & b2 > 0 & b3 < 0 & |l1 - l3| <= 0.3 a & c >= min(l1, l3) - 0.075 a
    cm = fg.cmo(close, 14);  cmu, cmd = cross_above(cm, 0), cross_below(cm, 0)
    L = recent(bull, 3) & recent(cmu, 3) & cm > 0 & (bull | cmu)
    S = recent(bear, 3) & recent(cmd, 3) & cm < 0 & (bear | cmd);  S &= ~L

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar. Parameters varied:
  cmo_len    CMO length 14 (the CMO zero line itself is the neutral 0 and cannot be scaled)
  body_min   minimum body of each of the three pattern bars, 0.08 x ATR14
  match_tol  how close the two outer lows (highs) must be, 0.3 x ATR14
  prior_n    number of closes whose first-vs-last change sets the prior trend (5): c[j-3] vs c[j-2-n]
Not varied: ATR length 14, the 0.075 x ATR14 close tolerance, the 3-bar windows.
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
from strategies import _f, cross_above, cross_below, gt, lt, recent  # noqa: E402

NAME = "S3_CMO_SANDWICH"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/ports12.py:s3"
ATR_LEN = 14         # locked, not varied
CLOSE_TOL = 0.075    # locked, not varied
FIRST_LAG = 2        # pattern's first bar is t-2 (structure, not a parameter)
WINDOW = 3           # recent(..., 3), locked, not varied

PARAMS = [
    {"name": "cmo_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (cm = fg.cmo(df['close'], 14))"},
    {"name": "body_min", "default": 0.08, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (bodies = abs(b1), abs(b2), abs(b3) >= 0.08 * a)"},
    {"name": "match_tol", "default": 0.3, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (np.abs(l1 - l3) <= 0.3 * a for bull, np.abs(h1 - h3) <= 0.3 * a for bear)"},
    {"name": "prior_n", "default": 5, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (_prior_dir(c, 2, 5, variant): c[t-3] vs c[t-2-5])"},
]
_SPEC = {p["name"]: p for p in PARAMS}
MULTIPLIERS = (0.5, 0.75, 1.25, 1.5)


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def variant_value(spec: dict, m: float):
    """PREREG 4: length -> round half up, min 2; mult / threshold_abs -> m * default;
    threshold_neutral -> neutral + m * (default - neutral). Floats are rounded to 12 decimals
    (0.15000000000000002 -> 0.15)."""
    d, kind = spec["default"], spec["kind"]
    if kind == "length":
        return max(2, _round_half_up(d * m))
    if kind in ("mult", "threshold_abs"):
        return round(float(d) * m, 12)
    if kind == "threshold_neutral":
        return round(float(spec["neutral"]) + m * (float(d) - float(spec["neutral"])), 12)
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


def _sh(x, k: int) -> np.ndarray:
    """ports12._sh: x shifted k bars into the past (NaN for the first k bars)."""
    x = _f(x)
    out = np.full(len(x), np.nan)
    if k == 0:
        out[:] = x
    elif k < len(x):
        out[k:] = x[:len(x) - k]
    return out


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    o, h, l, c = (_f(df[k]) for k in ("open", "high", "low", "close"))
    a = _f(fg.atr(df, ATR_LEN))
    b = c - o
    b1, b2, b3 = _sh(b, 2), _sh(b, 1), b
    h1, h3, l1, l3 = _sh(h, 2), h, _sh(l, 2), l
    last, first = _sh(c, FIRST_LAG + 1), _sh(c, FIRST_LAG + p["prior_n"])
    bmin, tol = p["body_min"], p["match_tol"]
    with np.errstate(invalid="ignore"):
        up_prior, dn_prior = last > first, last < first
        bodies = (np.abs(b1) >= bmin * a) & (np.abs(b2) >= bmin * a) & (np.abs(b3) >= bmin * a)
        bear = up_prior & bodies & (b1 > 0) & (b2 < 0) & (b3 > 0) & (np.abs(h1 - h3) <= tol * a) \
            & (c <= np.maximum(h1, h3) + CLOSE_TOL * a)
        bull = dn_prior & bodies & (b1 < 0) & (b2 > 0) & (b3 < 0) & (np.abs(l1 - l3) <= tol * a) \
            & (c >= np.minimum(l1, l3) - CLOSE_TOL * a)
    cm = fg.cmo(df["close"], p["cmo_len"])
    cmu, cmd = cross_above(cm, 0.0), cross_below(cm, 0.0)
    long = recent(bull, WINDOW) & recent(cmu, WINDOW) & gt(cm, 0.0) & (bull | cmu)
    short = recent(bear, WINDOW) & recent(cmd, WINDOW) & lt(cm, 0.0) & (bear | cmd)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
