"""Parameter re-implementation of N02_ST_KST for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/strategies.py:n02_supertrend_kst (registered in
sweep_lib.REGISTRY through EXACT19, no timeframe scaling):

    _line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    kline, ksig = fg.kst(close, (10, 15, 20, 30), (10, 10, 10, 15), 9)
    long  = direction > 0 & recent(KST crosses above signal, 2) & (KST up-cross | SuperTrend up-flip)
    short = direction < 0 & recent(KST crosses below signal, 2) & (KST down-cross | SuperTrend down-flip)
    short &= ~long                     (sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar (checked on all
6 coins x 15m/1h/4h, periods 1-2 and 3). The sync window (2 bars) is not varied: x0.5 and x0.75
both round to 2, i.e. no change.

Variant rule (PREREG section 4): multipliers x0.5, x0.75, x1.25, x1.5 of the locked value, one
parameter at a time. 'length' -> round half up, min 2 (a tuple of lengths: every element);
'mult' / 'threshold_abs' -> m * default; 'threshold_neutral' -> neutral + m * (default - neutral).
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
import fg_indicators as fg  # noqa: E402
from strategies import cross_above, cross_below, ge, gt, le, lt, recent  # noqa: E402

NAME = "N02_ST_KST"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/strategies.py:n02_supertrend_kst"

PARAMS = [
    {"name": "st_atr_len", "default": 10, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg_fast.supertrend(df, 10, 6.0): ATR length)"},
    {"name": "st_mult", "default": 6.0, "kind": "mult", "neutral": None,
     "where": _WHERE + " (fg_fast.supertrend(df, 10, 6.0): band multiplier)"},
    {"name": "kst_roc_lens", "default": [10, 15, 20, 30], "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.kst roc_lengths (10, 15, 20, 30); each element scaled, SMA lengths "
                       "(10, 10, 10, 15) kept)"},
    {"name": "kst_signal_len", "default": 9, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.kst signal_length 9)"},
]
_P = {p["name"]: p for p in PARAMS}
_SYNC = 2
_KST_SMA = (10, 10, 10, 15)


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
    roc = tuple(int(x) for x in v["kst_roc_lens"])
    if len(roc) != 4:
        raise ValueError("kst_roc_lens needs 4 lengths")
    return dict(st_atr_len=int(v["st_atr_len"]), st_mult=float(v["st_mult"]), kst_roc_lens=roc,
                kst_signal_len=int(v["kst_signal_len"]))


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    _line, direction, _u, _l = fg_fast.supertrend(df, p["st_atr_len"], p["st_mult"])
    kline, ksig = fg.kst(df["close"], p["kst_roc_lens"], _KST_SMA, p["kst_signal_len"])
    up, down = cross_above(kline, ksig), cross_below(kline, ksig)
    d = direction.to_numpy(dtype=float) if isinstance(direction, pd.Series) else np.asarray(direction, float)
    dp = pd.Series(d).shift(1)
    flip_up = gt(d, 0) & le(dp, 0)
    flip_down = lt(d, 0) & ge(dp, 0)
    long = gt(d, 0) & recent(up, _SYNC) & (up | flip_up)
    short = lt(d, 0) & recent(down, _SYNC) & (down | flip_down)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
