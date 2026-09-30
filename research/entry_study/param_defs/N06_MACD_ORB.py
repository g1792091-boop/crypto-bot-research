"""Parameter re-implementation of N06_MACD_ORB for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:n06 (registered in sweep_lib.REGISTRY through
APPROX12 / _wrap_port, no timeframe scaling), a = ATR14 (ports12._base):

    first = first bar of each UTC date; orb_h / orb_l = its high / low carried forward, NaN on it
    bu = (c > orb_h) & (c1 <= orb_h);   bd = (c < orb_l) & (c1 >= orb_l)
    ml, sl, hist = fg.macd(close, 12, 26, 9);  mu, md = cross_above(ml, sl), cross_below(ml, sl)
    long  = recent(bu, 2) & recent(mu, 2) & (ml > 0) & (hist > 0) & (hist >= hist1)
            & ((c - orb_h) <= 1.5 * a) & (bu | mu)
    short = recent(bd, 2) & recent(md, 2) & (ml < 0) & (hist < 0) & (hist <= hist1)
            & ((orb_l - c) <= 1.5 * a) & (bd | md)
    short &= ~long                        (ports12._pack and sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar. Parameters varied: the
three MACD lengths (12, 26, 9) and the 'not too far past the opening range' cap (1.5 ATR14).
Not varied: the 2-bar sync windows (x0.5 / x0.75 round back to 2 and x1.25 / x1.5 both round to 3,
so one distinct variant only; the four slots go to the MACD lengths and the cap), ATR length 14, the
opening range itself (one bar, the UTC-midnight bar, on every timeframe).

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
from strategies import cross_above, cross_below, recent  # noqa: E402

NAME = "N06_MACD_ORB"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/ports12.py:n06"
WINDOW = 2         # recent(..., 2), locked, not varied
ATR_LEN = 14       # locked (ports12._base), not varied

PARAMS = [
    {"name": "macd_fast", "default": 12, "kind": "length", "neutral": None,
     "where": _WHERE + " (ml, sl, hist = fg.macd(df['close'], 12, 26, 9): fast EMA)"},
    {"name": "macd_slow", "default": 26, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.macd(df['close'], 12, 26, 9): slow EMA)"},
    {"name": "macd_signal", "default": 9, "kind": "length", "neutral": None,
     "where": _WHERE + " (fg.macd(df['close'], 12, 26, 9): signal-line EMA)"},
    {"name": "ext_cap", "default": 1.5, "kind": "mult", "neutral": None,
     "where": _WHERE + " ((c - orb_h) <= 1.5 * a for longs, (orb_l - c) <= 1.5 * a for shorts)"},
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
    if k < len(x):
        out[k:] = x[:len(x) - k]
    return out


def signals(df: pd.DataFrame, tf: str, **overrides):
    """(long_bool, short_bool) of len(df); the signal is known at the bar's close."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    h, l, c = (df[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    a = fg.atr(df, ATR_LEN).to_numpy(dtype=float)
    ts = pd.to_datetime(df["ts"], utc=True)
    first = (~ts.dt.floor("D").duplicated()).to_numpy(dtype=bool)
    orb_h = pd.Series(np.where(first, h, np.nan)).ffill().to_numpy()
    orb_l = pd.Series(np.where(first, l, np.nan)).ffill().to_numpy()
    orb_h[first] = np.nan
    orb_l[first] = np.nan
    c1 = _sh(c, 1)
    with np.errstate(invalid="ignore"):
        bu = (c > orb_h) & (c1 <= orb_h)
        bd = (c < orb_l) & (c1 >= orb_l)
    ml, sl, hist = fg.macd(df["close"], p["macd_fast"], p["macd_slow"], p["macd_signal"])
    mu, md = cross_above(ml, sl), cross_below(ml, sl)
    hs = hist.to_numpy(dtype=float)
    hs1 = _sh(hs, 1)
    mlf = ml.to_numpy(dtype=float)
    cap = p["ext_cap"]
    with np.errstate(invalid="ignore"):
        long = (recent(bu, WINDOW) & recent(mu, WINDOW) & (mlf > 0) & (hs > 0) & (hs >= hs1)
                & ((c - orb_h) <= cap * a) & (bu | mu))
        short = (recent(bd, WINDOW) & recent(md, WINDOW) & (mlf < 0) & (hs < 0) & (hs <= hs1)
                 & ((orb_l - c) <= cap * a) & (bd | md))
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
