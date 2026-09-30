"""Parameter re-implementation of N07_ICHI_CMO for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/strategies.py:_ichimoku_family(df, "CMO") via
n07_ichimoku_cmo (registered in sweep_lib.REGISTRY through EXACT19, no timeframe scaling):

    tenkan, kijun, span_a, span_b = fg.ichimoku(df, 9, 26, 52, 26)
    mom = fg.cmo(close, 14)
    long  = recent(tenkan crosses above kijun, 3) & span_a > span_b & recent(CMO crosses above 0, 3)
            & CMO > 0 & (TK up-cross | CMO up-cross)
    short = recent(tenkan crosses below kijun, 3) & span_a < span_b & recent(CMO crosses below 0, 3)
            & CMO < 0 & (TK down-cross | CMO down-cross)
    short &= ~long                     (sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar (checked on all
6 coins x 15m/1h/4h, periods 1-2 and 3). Not varied: the cloud displacement (26, kept when the
Kijun length moves), the sync window (3 bars; PREREG section 4 allows at most 4 parameters and the
three Ichimoku lengths and the CMO length were chosen) and the CMO level 0 (its neutral point, so
every 'threshold_neutral' variant would equal the default).

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
import fg_indicators as fg  # noqa: E402
from strategies import cross_above, cross_below, gt, lt, recent  # noqa: E402

NAME = "N07_ICHI_CMO"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/strategies.py:_ichimoku_family"

PARAMS = [
    {"name": "tenkan_len", "default": 9, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.ichimoku(df, 9, 26, 52, 26): Tenkan length)"},
    {"name": "kijun_len", "default": 26, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.ichimoku(df, 9, 26, 52, 26): Kijun length; displacement stays 26)"},
    {"name": "senkou_b_len", "default": 52, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.ichimoku(df, 9, 26, 52, 26): span B length)"},
    {"name": "cmo_len", "default": 14, "kind": "length", "neutral": None,
     "where": _WHERE + " (kind 'CMO': fg.cmo(close, 14))"},
]
_P = {p["name"]: p for p in PARAMS}
_SYNC = 3
_DISPLACEMENT = 26
_LEVEL = 0.0


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
    return {k: int(v[k]) for k in _P}


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    tenkan, kijun, span_a, span_b = fg.ichimoku(df, p["tenkan_len"], p["kijun_len"], p["senkou_b_len"],
                                                _DISPLACEMENT)
    tk_up, tk_down = cross_above(tenkan, kijun), cross_below(tenkan, kijun)
    cloud_green, cloud_red = gt(span_a, span_b), lt(span_a, span_b)
    mom = fg.cmo(df["close"], p["cmo_len"])
    le_, se_ = cross_above(mom, _LEVEL), cross_below(mom, _LEVEL)
    ls_, ss_ = gt(mom, _LEVEL), lt(mom, _LEVEL)
    long = recent(tk_up, _SYNC) & cloud_green & recent(le_, _SYNC) & ls_ & (tk_up | le_)
    short = recent(tk_down, _SYNC) & cloud_red & recent(se_, _SYNC) & ss_ & (tk_down | se_)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
