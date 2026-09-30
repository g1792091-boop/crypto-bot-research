"""Entry strength of N18_VWMA_MACD (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n18_vwma_macd), VWMA 20, MACD 12/26/9,
synchronized 2:
  long  = synchronized([MACD crosses above signal, close > VWMA20, histogram rising, MACD > 0], 2)
  short = synchronized([MACD crosses below signal, close < VWMA20, histogram falling, MACD < 0], 2) & ~long

All three features are read on the signal bar itself (the state at entry) and mirrored for shorts (sign
flipped), so a larger value means the condition holds by a wider margin in the trade direction on that bar.
synchronized(..., 2) lets each condition be met one or two bars before the signal bar, so on a minority of
signal bars a value sits on the wrong side of its rule (negative). Signal-bar counts only, 6 coins x
{15m, 1h, 4h} period-1/2 series after warm-up: about 10% of signals for macd_hist_atr, 9% for
vwma_dist_atr, under 2% for macd_zero_dist_atr. These are kept as they are (no clipping).
Every value at bar i uses bars <= i only. Defined without looking at any trading outcome.
"""

from __future__ import annotations

import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from paperbot import sweepsig  # noqa: E402

sweepsig.lib()  # hash-checked locked code; puts the vendored indicator modules on sys.path

import fg_indicators as fg  # noqa: E402
from strategies import _f  # noqa: E402

NAME = "N18_VWMA_MACD"

FEATURES = [
    {"name": "macd_hist_atr", "label_ko": "MACD 히스토그램 크기", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "MACD(12,26,9) histogram (MACD - signal) / ATR14, sign flipped for shorts: size of the MACD / signal cross and of the 'histogram rising' condition."},
    {"name": "macd_zero_dist_atr", "label_ko": "MACD선과 0선 거리", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "MACD line / ATR14 (long) or -MACD line / ATR14 (short): how far the 'MACD > 0 / < 0' condition is past the zero line."},
    {"name": "vwma_dist_atr", "label_ko": "종가와 VWMA 거리", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "(close - VWMA20) / ATR14 for long, (VWMA20 - close) / ATR14 for short: how far the 'close above / below VWMA' condition holds."},
]


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    close = df["close"].to_numpy(dtype=float)
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    v = _f(fg.vwma(df, 20))
    ml, _sl, h = fg.macd(df["close"], 12, 26, 9)
    ml, h = _f(ml), _f(h)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        hist = h / a
        zero = ml / a
        dist = (close - v) / a
    return {
        "macd_hist_atr": (hist, -hist),
        "macd_zero_dist_atr": (zero, -zero),
        "vwma_dist_atr": (dist, -dist),
    }
