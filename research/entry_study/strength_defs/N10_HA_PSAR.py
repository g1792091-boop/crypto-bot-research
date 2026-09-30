"""Entry-strength numbers for N10_HA_PSAR (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n10_heikin_psar, no timeframe scaling;
checked chart view paperbot/strategy_view_defs/N10_HA_PSAR.py):
  Heikin-Ashi candles; Parabolic SAR (0.02, 0.02, 0.2) with its direction
  long  = HA candle turned green within 2 bars & no lower HA wick (<= 2% of the HA range)
          & SAR below the close & (SAR direction up | SAR flipped up within 2 bars)
          & (HA turn or SAR flip on this bar)
  short = mirror (HA turned red, no upper wick, SAR above the close, SAR direction down).

The numbers below measure how strongly those conditions hold on the signal bar. They are defined
from the strategy code only; no trading outcome was computed or looked at when writing them.
Every value at bar i uses bars <= i only (the HA open and the SAR are forward recursions, ATR is
Wilder's running average).
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
from strategies import ge, gt, le, lt  # noqa: E402

NAME = "N10_HA_PSAR"

FEATURES = [
    {"name": "ha_body_atr", "label_ko": "하이킨아시 몸통 크기", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Size of the required Heikin-Ashi colour on the signal bar: (HA close - HA open) / ATR14 "
            "for longs (green body), (HA open - HA close) / ATR14 for shorts (red body)."},
    {"name": "sar_gap_atr", "label_ko": "가격과 SAR 점 거리", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the close is on the required side of the Parabolic SAR(0.02, 0.02, 0.2): "
            "(close - SAR) / ATR14 for longs, (SAR - close) / ATR14 for shorts."},
    {"name": "sar_age_bars", "label_ko": "SAR 방향 전환 후 봉 수", "unit": "봉",
     "higher_is_stronger": True,
     "why": "Bars since the SAR direction last flipped to the trade side (0 = the flip trigger on the "
            "signal bar): how long the 'SAR direction up / down' condition has held."},
]


def _arr(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _finite(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float).copy()
    x[~np.isfinite(x)] = np.nan
    return x


def _bars_since(event: np.ndarray) -> np.ndarray:
    """Bars since the last True of ``event`` at or before each bar (0 on the event bar); NaN before the first."""
    e = np.asarray(event, dtype=bool)
    idx = np.arange(len(e))
    last = np.maximum.accumulate(np.where(e, idx, -1)) if len(e) else np.zeros(0, dtype=np.int64)
    out = (idx - last).astype(float)
    out[last < 0] = np.nan
    return out


def strength(df: pd.DataFrame, tf: str) -> dict:
    """{feature name: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    n = len(df)
    atr = _arr(fg.atr(df, 14))
    ha = fg_fast.heikin_ashi(df)
    psar, pdir = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.2)
    sar, d = _arr(psar), _arr(pdir)
    dp = np.r_[np.nan, d[:-1]] if n else d
    flip_up = gt(d, 0) & le(dp, 0)
    flip_down = lt(d, 0) & ge(dp, 0)
    close = df["close"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        body = (_arr(ha["ha_close"]) - _arr(ha["ha_open"])) / atr
        gap = (close - sar) / atr
    return {
        "ha_body_atr": (_finite(body), _finite(-body)),
        "sar_gap_atr": (_finite(gap), _finite(-gap)),
        "sar_age_bars": (_bars_since(flip_up), _bars_since(flip_down)),
    }
