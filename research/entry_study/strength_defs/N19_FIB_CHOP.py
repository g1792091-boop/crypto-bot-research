"""Entry strength of N19_FIB_CHOP (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/ports12.py:n19, variant 0; no timeframe scaling):
    a = ATR14;  hh = max(high over the 34 bars ending 3 bars ago);  ll = min(low over the same bars)
    mid = ll + 0.5 * (hh - ll)                                   (the 50 % retracement line)
    slope = (EMA34 - EMA34[-3]) / ATR14                          (fg.research_chop_zone: GREEN/BLUE >= 0.20,
                                                                  RED/DARK_RED <= -0.20)
    long  = (low  <= mid + 0.2 a) & (close > mid) & (close > open) & (slope >= 0.20)
    short = (high >= mid - 0.2 a) & (close < mid) & (close < open) & (slope <= -0.20)   (& ~long)

Features (ATR14 of the signal bar, long / short mirrored):
  touch_depth_atr      (mid - low) / a, short (high - mid) / a: how far the bar reached through the 50 % line
                       (the touch condition allows down to -0.2)
  close_past_line_atr  (close - mid) / a, short (mid - close) / a: the 'close back on the trade side of the
                       line' condition (> 0 on every signal)
  chop_slope           slope, short -slope: the chop-zone trend filter (>= 0.20 on every signal)
Every value at bar i uses bars <= i only. Defined without looking at any trading outcome.
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

NAME = "N19_FIB_CHOP"
RANGE_LEN, RANGE_LAG, FIB = 34, 3, 0.5      # locked
CHOP_EMA, CHOP_ATR, SLOPE_LAG = 34, 14, 3  # locked (fg.research_chop_zone(df, 34, 14))

FEATURES = [
    {"name": "touch_depth_atr", "label_ko": "50% 선을 파고든 깊이", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Low below the 50% line of the 34-bar range ending 3 bars ago (short: high above it), in ATR14: the 'low touches the line (within 0.2 ATR)' condition."},
    {"name": "close_past_line_atr", "label_ko": "종가가 50% 선 넘은 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Close above the 50% line (short: below it), in ATR14: the 'close on the trade side of the line' condition."},
    {"name": "chop_slope", "label_ko": "추세 기울기(EMA34)", "unit": "ATR14 per 3 bars",
     "higher_is_stronger": True,
     "why": "Chop-zone slope (EMA34 - EMA34 3 bars ago) / ATR14 (short: its negative): the trend filter slope >= 0.20 (<= -0.20)."},
]


def _sh(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    h, l, c = (df[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
    hh = _sh(pd.Series(h).rolling(RANGE_LEN, min_periods=RANGE_LEN).max().to_numpy(), RANGE_LAG)
    ll = _sh(pd.Series(l).rolling(RANGE_LEN, min_periods=RANGE_LEN).min().to_numpy(), RANGE_LAG)
    mid = ll + FIB * (hh - ll)
    atr_s = fg.atr(df, CHOP_ATR)
    base = fg.ema(df["close"], CHOP_EMA)
    slope = ((base - base.shift(SLOPE_LAG)) / atr_s.replace(0, np.nan)).to_numpy(dtype=float)
    atr = atr_s.to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        return {
            "touch_depth_atr": ((mid - l) / a, (h - mid) / a),
            "close_past_line_atr": ((c - mid) / a, (mid - c) / a),
            "chop_slope": (slope, -slope),
        }
