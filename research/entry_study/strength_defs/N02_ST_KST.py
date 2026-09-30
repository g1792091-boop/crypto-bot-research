"""Entry-strength numbers for N02_ST_KST (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n02_supertrend_kst, no timeframe scaling):
  long  = SuperTrend(10, 6) direction up  & KST crossed above its signal line in the last 2 bars
          & (that KST cross OR the SuperTrend up-flip happens on this bar)
  short = mirror (direction down, KST crossed below its signal line).

The numbers below measure how strongly those conditions hold on the signal bar. They are defined
from the strategy code only; no trading outcome was computed or looked at when writing them.
Every value at bar i uses bars <= i only (EWM / rolling / the SuperTrend loop are all causal).
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

NAME = "N02_ST_KST"

FEATURES = [
    {"name": "kst_gap_atr", "label_ko": "KST 교차 크기(ATR 대비)", "unit": "KST 포인트 / ATR14(%)",
     "higher_is_stronger": True,
     "why": "Size of the required KST-over-signal-line cross on the signal bar: (KST - signal line) for "
            "longs, (signal line - KST) for shorts, divided by ATR14 in percent of the close (KST is in "
            "percent units)."},
    {"name": "st_dist_atr", "label_ko": "슈퍼트렌드선에서 거리(ATR)", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the close sits on the required side of the SuperTrend(10, 6) line that sets the "
            "trade direction: (close - line) / ATR14 for longs, (line - close) / ATR14 for shorts."},
]


def _arr(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _finite(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float).copy()
    x[~np.isfinite(x)] = np.nan
    return x


def strength(df: pd.DataFrame, tf: str) -> dict:
    """{feature name: (value for long signals, value for short signals)}, float arrays of len(df)."""
    close = _arr(df["close"])
    atr = _arr(fg.atr(df, 14))
    line, _direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    line = _arr(line)
    kline, ksig = fg.kst(df["close"], (10, 15, 20, 30), (10, 10, 10, 15), 9)
    gap = _arr(kline) - _arr(ksig)
    with np.errstate(divide="ignore", invalid="ignore"):
        atr_pct = 100.0 * atr / close
        kst_long = gap / atr_pct
        st_long = (close - line) / atr
    return {
        "kst_gap_atr": (_finite(kst_long), _finite(-kst_long)),
        "st_dist_atr": (_finite(st_long), _finite(-st_long)),
    }
