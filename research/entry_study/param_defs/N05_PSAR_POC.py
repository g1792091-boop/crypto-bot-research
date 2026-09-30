"""Parameter re-implementation of N05_PSAR_POC for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:n05 (registered in sweep_lib.REGISTRY through
APPROX12 / _wrap_port, no timeframe scaling), a = ATR14 (ports12._base):

    poc = poc_fast.poc_series(df, 100, 32)                              # lookback, bins
    psar, pdir = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2)             # start, step, max
    sup  = (|low - poc| <= 0.2 a) | ((low <= poc) & (poc <= close))
    res  = (|high - poc| <= 0.2 a) | ((close <= poc) & (poc <= high))
    pierce = (c1 < o1) & (c > o) & (c >= (o1 + c1) / 2) & (c < o1)
    dark   = (c1 > o1) & (c < o) & (c <= (o1 + c1) / 2) & (c > o1)
    long  = sup & pierce & (close > psar)
    short = res & dark & (close < psar)
    short &= ~long                        (ports12._pack and sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar. Parameters varied:
  poc_lookback  bars of the rolling volume profile (100)
  poc_tol       how close (in ATR14) the low (high) must come to the POC (0.2)
  pierce_frac   share of the previous bar's body the close must take back (0.5, the midpoint
                (o1 + c1) / 2). The level is written f * o1 + (1 - f) * c1; at f = 0.5 that is
                0.5 o1 + 0.5 c1, bit-identical to (o1 + c1) / 2 (halving is exact in floating point)
  sar_af        the Parabolic SAR acceleration factor: the start and the step (both 0.02 in the
                locked call) move together, the 0.2 cap stays locked
Not varied: POC bins (32), SAR cap (0.2), ATR length (14).

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
import fg_fast  # noqa: E402
import fg_indicators as fg  # noqa: E402
from poc_fast import poc_series  # noqa: E402

NAME = "N05_PSAR_POC"
EXCLUDED_REASON = None
MULTS = (0.5, 0.75, 1.25, 1.5)
_WHERE = "third_party/sweep/harness/vendor/ports12.py:n05"
POC_BINS = 32      # locked, not varied
SAR_MAX = 0.2      # locked, not varied
ATR_LEN = 14       # locked (ports12._base), not varied

PARAMS = [
    {"name": "poc_lookback", "default": 100, "kind": "length", "neutral": None,
     "where": _WHERE + " (poc = poc_series(df, 100, 32): lookback of the rolling volume profile)"},
    {"name": "poc_tol", "default": 0.2, "kind": "threshold_abs", "neutral": None,
     "where": _WHERE + " (sup = |l - poc| <= 0.2 * a | ...; res = |h - poc| <= 0.2 * a | ...)"},
    {"name": "pierce_frac", "default": 0.5, "kind": "threshold_abs", "neutral": None,
     "where": _WHERE + " (pierce: c >= (o1 + c1) / 2.0; dark: c <= (o1 + c1) / 2.0)"},
    {"name": "sar_af", "default": 0.02, "kind": "mult", "neutral": None,
     "where": _WHERE + " (fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2): start and step together)"},
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
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    a = fg.atr(df, ATR_LEN).to_numpy(dtype=float)
    poc = poc_series(df, p["poc_lookback"], POC_BINS)
    psar, _pdir = fg_fast.parabolic_sar(df, p["sar_af"], p["sar_af"], SAR_MAX)
    ps = psar.to_numpy(dtype=float)
    o1, c1 = _sh(o, 1), _sh(c, 1)
    f, tol = p["pierce_frac"], p["poc_tol"]
    mid = f * o1 + (1.0 - f) * c1
    with np.errstate(invalid="ignore"):
        sup = (np.abs(l - poc) <= tol * a) | ((l <= poc) & (poc <= c))
        res = (np.abs(h - poc) <= tol * a) | ((c <= poc) & (poc <= h))
        pierce = (c1 < o1) & (c > o) & (c >= mid) & (c < o1)
        dark = (c1 > o1) & (c < o) & (c <= mid) & (c > o1)
        long = sup & pierce & (c > ps)
        short = res & dark & (c < ps)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
