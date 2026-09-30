"""Entry strength of N20_EMA9_CHOP (PREREG_ENTRY.md section 3, B). Short-only strategy.

Locked rule (third_party/sweep/harness/vendor/ports12.py:n20, variant 0; no timeframe scaling):
    e9 = EMA9(close);  reg = fg.research_chop_regime(df, 14)   (ADX14: RED < 15 <= YELLOW < 20 <= GREEN < 30 <= BLUE)
    short = reg in (YELLOW, RED) & (close < e9) & cross_below(close, e9)
i.e. the close crosses below EMA9 while ADX14 is not >= 20 (no strong trend). There are no long signals,
so every feature is NaN on the long side.

Features (short side):
  cross_gap_atr  (EMA9 - close) / ATR14 on the signal bar: how far the close went below EMA9 on the cross
                 (> 0 on every signal)
  adx_room       20 - ADX14: how far ADX is under the 'strong trend' level 20 (> 0 on every signal with a
                 defined ADX; NaN during the ADX warm-up, where the locked rule also lets signals through)
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

NAME = "N20_EMA9_CHOP"
EMA_LEN, ADX_LEN, ADX_LEVEL = 9, 14, 20.0   # locked

FEATURES = [
    {"name": "cross_gap_atr", "label_ko": "종가가 EMA9 아래로 뚫은 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "EMA9 minus close on the signal bar, in ATR14: the 'close crosses below EMA9' condition."},
    {"name": "adx_room", "label_ko": "ADX가 20보다 낮은 정도", "unit": "ADX points",
     "higher_is_stronger": True,
     "why": "20 - ADX14: the 'chop regime YELLOW or RED (ADX14 below 20)' condition."},
]


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df); long is NaN."""
    df = df.reset_index(drop=True)
    c = df["close"].to_numpy(dtype=float)
    e9 = _f(fg.ema(df["close"], EMA_LEN))
    adx = _f(fg.adx_dmi(df, ADX_LEN)[0])
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    nan = np.full(len(df), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        return {
            "cross_gap_atr": (nan.copy(), (e9 - c) / a),
            "adx_room": (nan.copy(), ADX_LEVEL - adx),
        }
