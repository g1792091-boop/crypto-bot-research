"""Entry-strength numbers for N14_ICHI_RSI (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:_ichimoku_family(df, "RSI"), no
timeframe scaling; Ichimoku (9, 26, 52, 26) with the cloud read as visible at the bar; chart view
paperbot/strategy_view_defs/N14_ICHI_RSI.py):
  long  = Tenkan crossed above Kijun in the last 3 bars & cloud green (span A > span B)
          & RSI(14) below 30 and rising at some bar of the last 3 & RSI < 30
          & (one of the two triggers on this bar)
  short = mirror (Tenkan below Kijun, red cloud, RSI above 70 and falling, RSI > 70).

The numbers below measure how strongly those conditions hold on the signal bar. They are defined
from the strategy code only; no trading outcome was computed or looked at when writing them.
The Tenkan/Kijun and cloud numbers are the same definitions as for N07_ICHI_CMO / N08_ICHI_WR
(same Ichimoku rule). Every value at bar i uses bars <= i only (the cloud spans are the values
computed 26 bars earlier). This strategy fires very rarely (a trend-up cross with RSI still
oversold), so most cells will fall under the 300-signal minimum of PREREG section 1.
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
import fg_indicators as fg  # noqa: E402

NAME = "N14_ICHI_RSI"

FEATURES = [
    {"name": "rsi_depth", "label_ko": "RSI가 30/70을 넘은 깊이", "unit": "RSI 포인트",
     "higher_is_stronger": True,
     "why": "How far RSI(14) is past the rule's level on the signal bar: 30 - RSI for longs (below "
            "30), RSI - 70 for shorts (above 70)."},
    {"name": "tk_gap_atr", "label_ko": "전환선·기준선 간격(ATR)", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Size of the required Tenkan/Kijun cross on the signal bar: (Tenkan - Kijun) / ATR14 for "
            "longs, (Kijun - Tenkan) / ATR14 for shorts."},
    {"name": "cloud_gap_atr", "label_ko": "구름 두께(ATR)", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How strongly the required cloud colour holds: (span A - span B) / ATR14 for longs (green "
            "cloud), (span B - span A) / ATR14 for shorts (red cloud)."},
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
    atr = _arr(fg.atr(df, 14))
    tenkan, kijun, span_a, span_b = fg.ichimoku(df, 9, 26, 52, 26)
    r = _finite(_arr(fg.rsi(df["close"], 14)))
    with np.errstate(divide="ignore", invalid="ignore"):
        tk = (_arr(tenkan) - _arr(kijun)) / atr
        cloud = (_arr(span_a) - _arr(span_b)) / atr
    return {
        "rsi_depth": (30.0 - r, r - 70.0),
        "tk_gap_atr": (_finite(tk), _finite(-tk)),
        "cloud_gap_atr": (_finite(cloud), _finite(-cloud)),
    }
