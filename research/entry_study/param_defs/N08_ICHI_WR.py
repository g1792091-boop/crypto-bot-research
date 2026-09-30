"""Parameter re-implementation of N08_ICHI_WR for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/strategies.py:_ichimoku_family(df, "WILLIAMS_R") via
n08_ichimoku_williams (registered in sweep_lib.REGISTRY through EXACT19, no timeframe scaling):

    tenkan, kijun, span_a, span_b = fg.ichimoku(df, 9, 26, 52, 26)
    mom = fg.williams_r(df, 14)
    long  = recent(tenkan crosses above kijun, 3) & span_a > span_b & recent(%R crosses above -80, 3)
            & %R > -80 & (TK up-cross | %R up-cross)
    short = recent(tenkan crosses below kijun, 3) & span_a < span_b & recent(%R crosses below -20, 3)
            & %R < -20 & (TK down-cross | %R down-cross)
    short &= ~long                     (sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar (checked on all
6 coins x 15m/1h/4h, periods 1-2 and 3). ``wr_oversold`` is the long level (-80); the short level
is its mirror about the %R neutral point -50, i.e. -100 - wr_oversold (= -20 in the locked code),
so one parameter moves both levels symmetrically. Not varied: the cloud displacement (26, kept
when the Kijun length moves), the span B length (52) and the sync window (3 bars); PREREG section 4
allows at most 4 parameters and the four in PARAMS were chosen.

Variant rule (PREREG section 4): multipliers x0.5, x0.75, x1.25, x1.5 of the locked value, one
parameter at a time. 'length' -> round half up, min 2; 'mult' / 'threshold_abs' -> m * default;
'threshold_neutral' -> neutral + m * (default - neutral) with the Williams %R neutral -50
(-80 -> -65, -72.5, -87.5, -95; short level -35, -27.5, -12.5, -5).
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
from strategies import cross_above, cross_below, gt, lt, recent  # noqa: E402

NAME = "N08_ICHI_WR"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/strategies.py:_ichimoku_family"

PARAMS = [
    {"name": "tenkan_len", "default": 9, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.ichimoku(df, 9, 26, 52, 26): Tenkan length)"},
    {"name": "kijun_len", "default": 26, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.ichimoku(df, 9, 26, 52, 26): Kijun length; displacement stays 26)"},
    {"name": "wr_len", "default": 14, "kind": "length", "neutral": None,
     "where": _WHERE + " (kind 'WILLIAMS_R': fg.williams_r(df, 14))"},
    {"name": "wr_oversold", "default": -80.0, "kind": "threshold_neutral", "neutral": -50.0,
     "where": _WHERE + " (kind 'WILLIAMS_R': long level -80 in cross_above/gt; short level -20 in "
                       "cross_below/lt = -100 - wr_oversold)"},
]
_P = {p["name"]: p for p in PARAMS}
_SYNC = 3
_SENKOU_B = 52
_DISPLACEMENT = 26


def _round_len(x: float) -> int:
    return max(2, int(math.floor(float(x) + 0.5)))


def _vary(p: dict, m: float):
    d, kind = p["default"], p["kind"]
    if kind == "length":
        return [_round_len(m * v) for v in d] if isinstance(d, (list, tuple)) else _round_len(m * d)
    if kind in ("mult", "threshold_abs"):
        return m * d
    if kind == "threshold_neutral":
        return p["neutral"] + m * (d - p["neutral"])
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
    return dict(tenkan_len=int(v["tenkan_len"]), kijun_len=int(v["kijun_len"]), wr_len=int(v["wr_len"]),
                wr_oversold=float(v["wr_oversold"]))


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    lo_level = p["wr_oversold"]
    hi_level = -100.0 - lo_level
    tenkan, kijun, span_a, span_b = fg.ichimoku(df, p["tenkan_len"], p["kijun_len"], _SENKOU_B, _DISPLACEMENT)
    tk_up, tk_down = cross_above(tenkan, kijun), cross_below(tenkan, kijun)
    cloud_green, cloud_red = gt(span_a, span_b), lt(span_a, span_b)
    mom = fg.williams_r(df, p["wr_len"])
    le_, se_ = cross_above(mom, lo_level), cross_below(mom, hi_level)
    ls_, ss_ = gt(mom, lo_level), lt(mom, hi_level)
    long = recent(tk_up, _SYNC) & cloud_green & recent(le_, _SYNC) & ls_ & (tk_up | le_)
    short = recent(tk_down, _SYNC) & cloud_red & recent(se_, _SYNC) & ss_ & (tk_down | se_)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
