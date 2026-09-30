"""Parameter re-implementation of S4_BB_BBP for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:s4 (variant 0; registered in sweep_lib.REGISTRY
through APPROX12 / _wrap_port, no timeframe scaling):

    up, mid, lo, bw = fg.bollinger_bands(close, 20, 2.0)
    thr = fg.rolling_percentile_threshold(bw, 100, 0.2);  sq = bw <= thr
    sq_prev = recent(shift_bool(sq, 1), 5)                     (any of t-1 .. t-5)
    _bu, _be, bbp = fg.bull_bear_power(df, 13)
    L = sq_prev & close > up & close[-1] <= up[-1] & bbp > 0
    S = sq_prev & close < lo & close[-1] >= lo[-1] & bbp < 0;  S &= ~L

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar. Parameters varied:
  bb_len       Bollinger length 20 (bands and the bandwidth of the squeeze)
  bb_mult      Bollinger width 2.0 standard deviations (the bandwidth percentile test is scale free, so this
               moves only the band the close must break)
  sq_lookback  bars of the rolling bandwidth percentile, 100
  sq_pct       the percentile of that window that counts as a squeeze, 0.2 (threshold_abs: 0.1 .. 0.3)
Not varied: Bull/Bear Power length 13, the 5-bar squeeze window.
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
from strategies import ge, gt, le, lt, recent, shift_bool  # noqa: E402

NAME = "S4_BB_BBP"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/ports12.py:s4"
BBP_LEN = 13        # locked, not varied
SQ_BARS = 5         # recent(shift_bool(sq, 1), 5), locked, not varied

PARAMS = [
    {"name": "bb_len", "default": 20, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (up, mid, lo, bw = fg.bollinger_bands(close, 20, 2.0): length)"},
    {"name": "bb_mult", "default": 2.0, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (up, mid, lo, bw = fg.bollinger_bands(close, 20, 2.0): standard deviations)"},
    {"name": "sq_lookback", "default": 100, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (thr = fg.rolling_percentile_threshold(bw, 100, 0.2): lookback)"},
    {"name": "sq_pct", "default": 0.2, "kind": "threshold_abs", "neutral": None,
     "where": f"{_WHERE} (thr = fg.rolling_percentile_threshold(bw, 100, 0.2): percentile)"},
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


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    close = df["close"]
    up, _mid, lo, bw = fg.bollinger_bands(close, p["bb_len"], p["bb_mult"])
    thr = fg.rolling_percentile_threshold(bw, p["sq_lookback"], p["sq_pct"])
    sq = le(bw, thr)
    sq_prev = recent(shift_bool(sq, 1), SQ_BARS)          # any of t-1 .. t-5
    _bu, _be, bbp = fg.bull_bear_power(df, BBP_LEN)
    long = sq_prev & gt(close, up) & le(close.shift(1), up.shift(1)) & gt(bbp, 0.0)
    short = sq_prev & lt(close, lo) & ge(close.shift(1), lo.shift(1)) & lt(bbp, 0.0)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
