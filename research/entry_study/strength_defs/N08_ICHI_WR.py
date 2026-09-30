"""Entry-strength numbers for N08_ICHI_WR (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:_ichimoku_family(df, "WILLIAMS_R"), no
timeframe scaling; Ichimoku (9, 26, 52, 26) with the cloud read as visible at the bar):
  long  = Tenkan crossed above Kijun in the last 3 bars & cloud green (span A > span B)
          & Williams %R(14) crossed above -80 in the last 3 bars & %R > -80
          & (one of the two crosses on this bar)
  short = mirror (Tenkan below Kijun, red cloud, %R crossed below -20, %R < -20).

The numbers below measure how strongly those conditions hold on the signal bar. They are defined
from the strategy code only; no trading outcome was computed or looked at when writing them.
Every value at bar i uses bars <= i only (the cloud spans are the values computed 26 bars earlier).
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

NAME = "N08_ICHI_WR"

FEATURES = [
    {"name": "wr_margin", "label_ko": "%R이 문턱을 넘은 정도", "unit": "%R 포인트",
     "higher_is_stronger": True,
     "why": "How far Williams %R(14) is past the rule's level on the signal bar: %R - (-80) for longs "
            "(above -80), (-20) - %R for shorts (below -20)."},
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
    wr = _finite(_arr(fg.williams_r(df, 14)))
    with np.errstate(divide="ignore", invalid="ignore"):
        tk = (_arr(tenkan) - _arr(kijun)) / atr
        cloud = (_arr(span_a) - _arr(span_b)) / atr
    return {
        "wr_margin": (wr - (-80.0), (-20.0) - wr),
        "tk_gap_atr": (_finite(tk), _finite(-tk)),
        "cloud_gap_atr": (_finite(cloud), _finite(-cloud)),
    }
