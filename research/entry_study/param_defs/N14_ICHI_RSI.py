"""Parameter re-implementation of N14_ICHI_RSI for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/strategies.py:_ichimoku_family(df, "RSI") via
n14_ichimoku_rsi (registered in sweep_lib.REGISTRY through EXACT19, no timeframe scaling):

    tenkan, kijun, span_a, span_b = fg.ichimoku(df, 9, 26, 52, 26)
    mom = fg.rsi(close, 14) ;  m1 = mom[1]
    le_ = RSI < 30 & RSI > m1          ls_ = RSI < 30
    se_ = RSI > 70 & RSI < m1          ss_ = RSI > 70
    long  = recent(tenkan crosses above kijun, 3) & span_a > span_b & recent(le_, 3) & ls_ & (TK up-cross | le_)
    short = recent(tenkan crosses below kijun, 3) & span_a < span_b & recent(se_, 3) & ss_ & (TK down-cross | se_)
    short &= ~long                     (sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar (checked on all
6 coins x 15m/1h/4h, periods 1-2 and 3). ``rsi_oversold`` is the long level (30); the short level
is its mirror about the RSI neutral point 50, i.e. 100 - rsi_oversold (= 70 in the locked code),
so one parameter moves both levels symmetrically. Not varied: the cloud displacement (26, kept
when the Kijun length moves), the span B length (52) and the sync window (3 bars).
The locked signal is very rare (a handful per coin and timeframe), so most C cells will have
too few signals for the tests; the definitions are kept so the variants can still be counted.

Variant rule (PREREG section 4): multipliers x0.5, x0.75, x1.25, x1.5 of the locked value, one
parameter at a time. 'length' -> round half up, min 2; 'mult' / 'threshold_abs' -> m * default;
'threshold_neutral' -> neutral + m * (default - neutral) with the RSI neutral 50
(30 -> 40, 35, 25, 20; short level 60, 65, 75, 80).
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

NAME = "N14_ICHI_RSI"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/strategies.py:_ichimoku_family"

PARAMS = [
    {"name": "tenkan_len", "default": 9, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.ichimoku(df, 9, 26, 52, 26): Tenkan length)"},
    {"name": "kijun_len", "default": 26, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.ichimoku(df, 9, 26, 52, 26): Kijun length; displacement stays 26)"},
    {"name": "rsi_len", "default": 14, "kind": "length", "neutral": None,
     "where": _WHERE + " (kind 'RSI': fg.rsi(close, 14))"},
    {"name": "rsi_oversold", "default": 30.0, "kind": "threshold_neutral", "neutral": 50.0,
     "where": _WHERE + " (kind 'RSI': long level 30 in lt(mom, 30); short level 70 in gt(mom, 70) "
                       "= 100 - rsi_oversold)"},
]
_P = {p["name"]: p for p in PARAMS}
_SYNC = 3
_SPAN_B = 52
_DISPLACEMENT = 26
_INT = ("tenkan_len", "kijun_len", "rsi_len")


def _round_len(x: float) -> int:
    return max(2, int(math.floor(float(x) + 0.5)))


def _vary(p: dict, m: float):
    d, kind = p["default"], p["kind"]
    if kind == "length":
        return [_round_len(m * v) for v in d] if isinstance(d, (list, tuple)) else _round_len(m * d)
    if kind in ("mult", "threshold_abs"):
        return round(m * d, 12)                      # 0.75 * 0.2 -> 0.15, not 0.15000000000000002
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
    return {k: (int(v[k]) if k in _INT else float(v[k])) for k in _P}


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    lo_lvl = p["rsi_oversold"]
    hi_lvl = 100.0 - lo_lvl
    tenkan, kijun, span_a, span_b = fg.ichimoku(df, p["tenkan_len"], p["kijun_len"], _SPAN_B, _DISPLACEMENT)
    tk_up, tk_down = cross_above(tenkan, kijun), cross_below(tenkan, kijun)
    cloud_green, cloud_red = gt(span_a, span_b), lt(span_a, span_b)
    mom = fg.rsi(df["close"], p["rsi_len"])
    m1 = mom.shift(1)
    le_ = lt(mom, lo_lvl) & gt(mom, m1)
    se_ = gt(mom, hi_lvl) & lt(mom, m1)
    ls_ = lt(mom, lo_lvl)
    ss_ = gt(mom, hi_lvl)
    long = recent(tk_up, _SYNC) & cloud_green & recent(le_, _SYNC) & ls_ & (tk_up | le_)
    short = recent(tk_down, _SYNC) & cloud_red & recent(se_, _SYNC) & ss_ & (tk_down | se_)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
