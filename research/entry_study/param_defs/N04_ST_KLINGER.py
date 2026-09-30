"""Parameter re-implementation of N04_ST_KLINGER for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:n04 (variant 0; registered in sweep_lib.REGISTRY
through APPROX12 / _wrap_port, no timeframe scaling):

    line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    kl, ks = fg.klinger_oscillator(df, 34, 55, 13)
    up, dn = cross_above(kl, ks), cross_below(kl, ks)
    d = direction;  fu = d > 0 & d[-1] <= 0;  fd = d < 0 & d[-1] >= 0
    L = d > 0 & recent(up, 2) & (up | fu)
    S = d < 0 & recent(dn, 2) & (dn | fd);  S &= ~L

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar. Parameters varied:
  st_atr_len      SuperTrend ATR length 10
  st_mult         SuperTrend band multiplier 6.0
  kvo_lens        Klinger fast / slow EMA lengths (34, 55), scaled together: scaling one alone would, at
                  x0.5 of the slow or x1.5 of the fast, put fast >= slow and flip the oscillator's sign.
                  The value is a two-element list [fast, slow]; each element is rounded half up, min 2.
  kvo_signal_len  Klinger signal-line EMA length 13
Not varied: the 2-bar cross window.
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
from strategies import _f, cross_above, cross_below, gt, lt, recent  # noqa: E402

NAME = "N04_ST_KLINGER"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/ports12.py:n04"
WINDOW = 2          # recent(up, 2), locked, not varied

PARAMS = [
    {"name": "st_atr_len", "default": 10, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg_fast.supertrend(df, 10, 6.0): ATR length)"},
    {"name": "st_mult", "default": 6.0, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (fg_fast.supertrend(df, 10, 6.0): band multiplier)"},
    {"name": "kvo_lens", "default": [34, 55], "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.klinger_oscillator(df, 34, 55, 13): fast and slow EMA lengths, scaled together)"},
    {"name": "kvo_signal_len", "default": 13, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.klinger_oscillator(df, 34, 55, 13): signal EMA length)"},
]
_SPEC = {p["name"]: p for p in PARAMS}
MULTIPLIERS = (0.5, 0.75, 1.25, 1.5)


def _round_len(x: float) -> int:
    return max(2, int(math.floor(float(x) + 0.5)))


def variant_value(spec: dict, m: float):
    """PREREG 4: length -> round half up, min 2 (a list of lengths: every element); mult / threshold_abs ->
    m * default; threshold_neutral -> neutral + m * (default - neutral). Floats are rounded to 12 decimals
    (0.15000000000000002 -> 0.15)."""
    d, kind = spec["default"], spec["kind"]
    if kind == "length":
        return [_round_len(v * m) for v in d] if isinstance(d, (list, tuple)) else _round_len(d * m)
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
        if s["kind"] == "length":
            p[k] = [int(v) for v in p[k]] if isinstance(s["default"], list) else int(p[k])
        else:
            p[k] = float(p[k])
    if len(p["kvo_lens"]) != 2:
        raise ValueError(f"{NAME}: kvo_lens must be [fast, slow], got {p['kvo_lens']!r}")
    return p


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    _line, direction, _u, _l = fg_fast.supertrend(df, p["st_atr_len"], p["st_mult"])
    fast, slow = p["kvo_lens"]
    kl, ks = fg.klinger_oscillator(df, fast, slow, p["kvo_signal_len"])
    up, dn = cross_above(kl, ks), cross_below(kl, ks)
    d = _f(direction)
    dp = np.full(len(d), np.nan)
    dp[1:] = d[:-1]
    with np.errstate(invalid="ignore"):
        fu = (d > 0) & (dp <= 0)
        fd = (d < 0) & (dp >= 0)
    long = gt(d, 0) & recent(up, WINDOW) & (up | fu)
    short = lt(d, 0) & recent(dn, WINDOW) & (dn | fd)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
