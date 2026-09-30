"""Entry-strength numbers for OBV_S (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:obv_s, no timeframe scaling; checked
chart view paperbot/strategy_view_defs/OBV_S.py):
  OBV = pi.obv(close, volume), trend line = SMA30(OBV)
  AC  = pi.ao_ac(high, low, 5, 34, 5)[1]
  STC = pi.stc(close, 12, 26, 50, 0.5)
  stochastic %K = SMA4(raw stoch), %D = SMA3(%K) for raw lengths 11, 15 and 9
  long  = any %K/%D golden cross on this bar & AC > 0 & STC < 70 & OBV > SMA30(OBV)
  short = any %K/%D dead cross on this bar   & AC < 0 & STC > 30 & OBV < SMA30(OBV)

The numbers below measure how strongly the three filter conditions hold on the signal bar (the
stochastic cross is the trigger). They are defined from the strategy code only; no trading outcome
was computed or looked at when writing them. Every value at bar i uses bars <= i only (OBV is a
running sum, SMAs are trailing windows, STC and ATR are forward recursions).
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
import pine_indicators as pi  # noqa: E402

NAME = "OBV_S"
OBV_MA = 30
STC_OB, STC_OS = 70.0, 30.0

FEATURES = [
    {"name": "obv_gap_vol", "label_ko": "OBV가 30봉 평균 넘은 폭", "unit": "30봉 평균 거래량 배수",
     "higher_is_stronger": True,
     "why": "How far OBV is on the required side of its SMA30 (the 'OBV above / below its 30-bar "
            "average' condition), in units of the 30-bar average volume: (OBV - SMA30(OBV)) / "
            "SMA30(volume) for longs, the negative for shorts."},
    {"name": "ac_atr", "label_ko": "가속도(AC) 크기", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the Accelerator Oscillator AC(5, 34, 5) is past 0 on the trade side (the "
            "'AC > 0 / < 0' condition), in ATR14: AC / ATR14 for longs, -AC / ATR14 for shorts."},
    {"name": "stc_room", "label_ko": "STC 과열·침체선까지 여유", "unit": "STC 포인트",
     "higher_is_stronger": True,
     "why": "How far STC(12, 26, 50) is inside the rule's cap on the signal bar: 70 - STC for longs "
            "(STC < 70), STC - 30 for shorts (STC > 30)."},
]


def _finite(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float).copy()
    x[~np.isfinite(x)] = np.nan
    return x


def strength(df: pd.DataFrame, tf: str) -> dict:
    """{feature name: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    n = len(df)
    if n == 0:
        e = np.zeros(0)
        return {f["name"]: (e.copy(), e.copy()) for f in FEATURES}
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    vol = df["volume"].to_numpy(dtype=float)
    o = pi.obv(close, vol)
    vol_ma = pi.pine_sma(np.nan_to_num(vol), OBV_MA)      # pi.obv treats a missing volume as 0
    _ao, ac = pi.ao_ac(high, low, 5, 34, 5)
    stc_v = pi.stc(close, 12, 26, 50, 0.5)
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        gap = (o - pi.pine_sma(o, OBV_MA)) / np.where(vol_ma > 0, vol_ma, np.nan)
        acn = ac / np.where(atr > 0, atr, np.nan)
    return {
        "obv_gap_vol": (_finite(gap), _finite(-gap)),
        "ac_atr": (_finite(acn), _finite(-acn)),
        "stc_room": (_finite(STC_OB - stc_v), _finite(stc_v - STC_OS)),
    }
