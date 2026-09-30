"""Entry-strength numbers for N05_PSAR_POC (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/ports12.py:n05, no timeframe scaling; checked chart view
paperbot/strategy_view_defs/N05_PSAR_POC.py), a = ATR14, poc = poc_fast.poc_series(df, 100, 32),
SAR = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2):
  support = |low - poc| <= 0.2 a  |  (low <= poc <= close)
  pierce  = prior bar bearish (c1 < o1) & this bar bullish (c > o) & c >= (o1 + c1) / 2 & c < o1
  long    = support & pierce & close > SAR
  short   = resistance (|high - poc| <= 0.2 a | close <= poc <= high) & dark cloud cover
            (c1 > o1 & c < o & c <= (o1 + c1) / 2 & c > o1) & close < SAR
  short &= ~long (ports12._pack / sweep_lib._clean)

The numbers below measure how strongly those conditions hold on the signal bar. They are defined from
the strategy code only; no trading outcome was computed or looked at when writing them. Every value at
bar i uses bars <= i only (POC over bars i-99 .. i, the SAR is a forward recursion, ATR is Wilder's
running average).
"""

from __future__ import annotations

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

FEATURES = [
    {"name": "pierce_depth", "label_ko": "앞 봉 몸통 되돌린 비율", "unit": "앞 봉 몸통 대비 비율",
     "higher_is_stronger": True,
     "why": "Piercing / dark-cloud depth: the share of the previous bar's opposite body that this bar's "
            "close took back, (c - c1) / (o1 - c1) for longs, (c1 - c) / (c1 - o1) for shorts; the rule "
            "needs >= 0.5 and < 1."},
    {"name": "poc_bounce_atr", "label_ko": "POC에서 튕긴 거리", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the close ended away from the volume POC (100 bars, 32 bins) the bar tested as "
            "support / resistance: (close - POC) / ATR14 for longs, (POC - close) / ATR14 for shorts."},
    {"name": "sar_gap_atr", "label_ko": "가격과 SAR 점 거리", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the close is on the required side of the Parabolic SAR(0.02, 0.02, 0.2): "
            "(close - SAR) / ATR14 for longs, (SAR - close) / ATR14 for shorts."},
]


def _arr(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _finite(x) -> np.ndarray:
    x = np.array(x, dtype=float)
    x[~np.isfinite(x)] = np.nan
    return x


def _sh(x, k: int) -> np.ndarray:
    """x shifted k bars into the past (NaN for the first k bars)."""
    x = _arr(x)
    out = np.full(len(x), np.nan)
    if k == 0:
        out[:] = x
    elif k < len(x):
        out[k:] = x[:-k]
    return out


def strength(df: pd.DataFrame, tf: str) -> dict:
    """{feature name: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    o, c = _arr(df["open"]), _arr(df["close"])
    a = _arr(fg.atr(df, 14))
    poc = _arr(poc_series(df, 100, 32))
    sar = _arr(fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2)[0])
    o1, c1 = _sh(o, 1), _sh(c, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(a > 0, a, np.nan)
        prior_bear = c1 < o1
        prior_bull = c1 > o1
        pierce_l = np.where(prior_bear, (c - c1) / (o1 - c1), np.nan)
        pierce_s = np.where(prior_bull, (c1 - c) / (c1 - o1), np.nan)
        bounce = (c - poc) / a
        gap = (c - sar) / a
    return {
        "pierce_depth": (_finite(pierce_l), _finite(pierce_s)),
        "poc_bounce_atr": (_finite(bounce), _finite(-bounce)),
        "sar_gap_atr": (_finite(gap), _finite(-gap)),
    }
