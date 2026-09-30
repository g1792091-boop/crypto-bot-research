"""Parameter re-implementation of N10_HA_PSAR for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/strategies.py:n10_heikin_psar (registered in
sweep_lib.REGISTRY through EXACT19, no timeframe scaling):

    ha = fg_fast.heikin_ashi(df)
    psar, pdir = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2)        # start, step, max
    tol = |ha_high - ha_low| * 0.02                                 # wick tolerance
    no_lower = |min(ha_open, ha_close) - ha_low| <= tol ;  no_upper = |ha_high - max(...)| <= tol
    turn_green = ha_close > ha_open & not on the previous bar      (mirror: turn_red)
    flip_up = pdir > 0 & pdir[1] <= 0                              (mirror: flip_down)
    long  = recent(turn_green, 2) & no_lower & psar < close & (pdir > 0 | recent(flip_up, 2))
            & (turn_green | flip_up)
    short = recent(turn_red, 2) & no_upper & psar > close & (pdir < 0 | recent(flip_down, 2))
            & (turn_red | flip_down)
    short &= ~long                     (sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar (checked on all
6 coins x 15m/1h/4h, periods 1-2 and 3). Not varied: the sync window (2 bars; x0.5/x0.75 round
back to 2). Heikin-Ashi itself has no parameter.

Variant rule (PREREG section 4): multipliers x0.5, x0.75, x1.25, x1.5 of the locked value, one
parameter at a time. 'length' -> round half up, min 2; 'mult' / 'threshold_abs' -> m * default;
'threshold_neutral' -> neutral + m * (default - neutral). The SAR acceleration factors are 'mult'
(start 0.02 -> 0.01, 0.015, 0.025, 0.03; the step and the cap move alone, the others stay locked);
the wick tolerance is 'threshold_abs' (a fraction of the HA range with natural zero).
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
from strategies import ge, gt, le, lt, recent, shift_bool  # noqa: E402

NAME = "N10_HA_PSAR"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/strategies.py:n10_heikin_psar"

PARAMS = [
    {"name": "sar_af_start", "default": 0.02, "kind": "mult", "neutral": None,
     "where": _WHERE + " (fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2): starting acceleration factor)"},
    {"name": "sar_af_step", "default": 0.02, "kind": "mult", "neutral": None,
     "where": _WHERE + " (fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2): acceleration step)"},
    {"name": "sar_af_max", "default": 0.2, "kind": "mult", "neutral": None,
     "where": _WHERE + " (fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2): acceleration cap)"},
    {"name": "wick_tol", "default": 0.02, "kind": "threshold_abs", "neutral": None,
     "where": _WHERE + " (tol = (ha_high - ha_low).abs() * 0.02 in the no-lower / no-upper wick test)"},
]
_P = {p["name"]: p for p in PARAMS}
_SYNC = 2


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
    return {k: float(v[k]) for k in _P}


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    ha = fg_fast.heikin_ashi(df)
    psar, pdir = fg_fast.parabolic_sar(df, p["sar_af_start"], p["sar_af_step"], p["sar_af_max"])
    ha_green = gt(ha["ha_close"], ha["ha_open"])
    ha_red = lt(ha["ha_close"], ha["ha_open"])
    tol = (ha["ha_high"] - ha["ha_low"]).abs() * p["wick_tol"]
    body_min = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).min(axis=1)
    body_max = pd.concat([ha["ha_open"], ha["ha_close"]], axis=1).max(axis=1)
    no_lower = le((body_min - ha["ha_low"]).abs(), tol)
    no_upper = le((ha["ha_high"] - body_max).abs(), tol)
    turn_green = ha_green & ~shift_bool(ha_green, 1)
    turn_red = ha_red & ~shift_bool(ha_red, 1)
    d = pdir.to_numpy(dtype=float)
    dp = pd.Series(d).shift(1)
    flip_up = gt(d, 0) & le(dp, 0)
    flip_down = lt(d, 0) & ge(dp, 0)
    close = df["close"]
    long = (recent(turn_green, _SYNC) & no_lower & lt(psar, close) & (gt(pdir, 0) | recent(flip_up, _SYNC))
            & (turn_green | flip_up))
    short = (recent(turn_red, _SYNC) & no_upper & gt(psar, close) & (lt(pdir, 0) | recent(flip_down, _SYNC))
             & (turn_red | flip_down))
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
