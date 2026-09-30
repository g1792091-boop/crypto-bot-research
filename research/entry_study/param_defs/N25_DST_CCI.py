"""Parameter re-implementation of N25_DST_CCI for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/strategies.py:n25_double_supertrend_cci (registered
in sweep_lib.REGISTRY through EXACT19, no timeframe scaling):

    _f1, fast_up = fg_fast.supertrend_v2(df, 10, 6.0)
    _f2, slow_up = fg_fast.supertrend_v2(df, 20, 6.0)
    c = fg_fast.cci(df, 20)
    c_up = cross_above(c, -100.0);  c_down = cross_below(c, 100.0)
    agree_up = fast_up & slow_up;  agree_down = ~fast_up & ~slow_up;  range_mode = fast_up != slow_up
    long  = (agree_up & c_up) | (range_mode & c_up & ~(agree_down & c_down))
    short = ((agree_down & c_down) & ~trend_long) | (range_mode & c_down & ~trend_long & ~range_long)
    short &= ~long                     (in the strategy and again in sweep_lib._clean)

Parameters varied (up to 4): the CCI length, the CCI level (+-100; CCI's neutral point is 0, so
the level is 'threshold_neutral' with both sides moving together: -L for longs, +L for shorts), and
the band multipliers of the two supertrends (6.0 each; they are two separate literals, varied one at
a time, so a variant also changes how often the two lines disagree = the rule's range mode).
Not varied: the supertrends' ATR lengths 10 and 20. They shape the entry much less than the
multipliers (signal bars only, no outcome: on BTC/ETH 1h full series, x0.5..x1.5 of either length
changes 0.9-7.4 % as many bars as the default signal count, of either multiplier 14-31 %), and
PREREG allows at most 4 parameters.

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar (checked on all
6 coins x 15m/1h/4h, periods 1-2 and 3).

Variant rule (PREREG section 4): multipliers x0.5, x0.75, x1.25, x1.5 of the locked value, one
parameter at a time. 'length' -> round half up, min 2; 'mult' / 'threshold_abs' -> m * default;
'threshold_neutral' -> neutral + m * (default - neutral).
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
from strategies import _b, cross_above, cross_below  # noqa: E402

NAME = "N25_DST_CCI"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/strategies.py:n25_double_supertrend_cci"
ST_FAST_LEN, ST_SLOW_LEN = 10, 20  # locked, not varied

PARAMS = [
    {"name": "cci_len", "default": 20, "kind": "length", "neutral": None,
     "where": _WHERE + " (c = fg_fast.cci(df, 20))"},
    {"name": "cci_level", "default": 100.0, "kind": "threshold_neutral", "neutral": 0.0,
     "where": _WHERE + " (c_up = cross_above(c, -100.0); c_down = cross_below(c, 100.0))"},
    {"name": "st_fast_mult", "default": 6.0, "kind": "mult", "neutral": None,
     "where": _WHERE + " (fg_fast.supertrend_v2(df, 10, 6.0): band multiplier of the fast supertrend)"},
    {"name": "st_slow_mult", "default": 6.0, "kind": "mult", "neutral": None,
     "where": _WHERE + " (fg_fast.supertrend_v2(df, 20, 6.0): band multiplier of the slow supertrend)"},
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
    out = {}
    for k, p in _P.items():
        out[k] = _round_len(v[k]) if p["kind"] == "length" else float(v[k])
    return out


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    _f1, fast_up = fg_fast.supertrend_v2(df, ST_FAST_LEN, p["st_fast_mult"])
    _f2, slow_up = fg_fast.supertrend_v2(df, ST_SLOW_LEN, p["st_slow_mult"])
    fast_up, slow_up = _b(fast_up), _b(slow_up)
    c = fg_fast.cci(df, p["cci_len"])
    lvl = p["cci_level"]
    c_up = cross_above(c, -lvl)
    c_down = cross_below(c, lvl)
    agree_up = fast_up & slow_up
    agree_down = (~fast_up) & (~slow_up)
    range_mode = fast_up != slow_up
    trend_long, trend_short = agree_up & c_up, agree_down & c_down
    range_long, range_short = range_mode & c_up, range_mode & c_down
    long = trend_long | (range_long & ~trend_short)
    short = (trend_short & ~trend_long) | (range_short & ~trend_long & ~range_long)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
