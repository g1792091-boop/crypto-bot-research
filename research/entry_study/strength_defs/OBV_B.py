"""Entry strength of OBV_B (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:obv_b, defaults on every timeframe):
    o = OBV;  break_ma = SMA(o, 9);  ac = AC(5, 34, 5);  stc = STC(12, 26, 50, 0.5)
    long  = o crosses above break_ma  & ac > 0 & ac rising  & stc < 70
    short = o crosses below break_ma  & ac < 0 & ac falling & stc > 30      (short &= ~long)
All three conditions sit on the signal bar itself, so every feature is read on that bar:
  obv_cross_vol  (o - break_ma) / SMA(volume, 9)     long;  (break_ma - o) / SMA(volume, 9)  short
                 = how far OBV closed past its 9-bar average on the crossing bar, in units of the 9-bar mean
                   volume (OBV itself is a running volume sum, so its distance to its average is a volume)
  ac_atr         ac / ATR14 long;  -ac / ATR14 short   (AC is in price units: AO = SMA5(hl2) - SMA34(hl2))
  stc_room       70 - stc long;  stc - 30 short        (distance to the STC limit the rule allows)
Every value at bar i uses bars <= i only (OBV is a cumulative sum from the first bar, SMAs / ATR / STC are
trailing). Defined without looking at any trading outcome.
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
import pine_indicators as pi  # noqa: E402
from strategies import _f  # noqa: E402

NAME = "OBV_B"
BREAK_LEN = 9
STC_OB, STC_OS = 70.0, 30.0

FEATURES = [
    {"name": "obv_cross_vol", "label_ko": "OBV가 평균선을 넘은 폭", "unit": "x 9-bar mean volume",
     "higher_is_stronger": True,
     "why": "Distance of OBV past its 9-bar SMA on the crossing bar (long above, short below), in 9-bar mean volumes: the size of the OBV break trigger."},
    {"name": "ac_atr", "label_ko": "AC 가속도 크기", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "AC(5,34,5) beyond zero in the trade direction (long AC, short -AC) divided by ATR14: the 'AC > 0 and rising / < 0 and falling' condition."},
    {"name": "stc_room", "label_ko": "STC 과열·침체선까지 여유", "unit": "STC points",
     "higher_is_stronger": True,
     "why": "How far STC(12,26,50) is inside its allowed side (long 70 - STC, short STC - 30): the 'STC < 70 / > 30' filter."},
]


def _empty():
    z = np.zeros(0, dtype=float)
    return {f["name"]: (z.copy(), z.copy()) for f in FEATURES}


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    n = len(df)
    if n == 0:
        return _empty()
    df = df.reset_index(drop=True)
    high, low, close = _f(df["high"]), _f(df["low"]), _f(df["close"])
    vol = _f(df["volume"])
    o = pi.obv(close, vol)
    break_ma = pi.pine_sma(o, BREAK_LEN)
    vol_ma = pi.pine_sma(np.nan_to_num(vol), BREAK_LEN)
    _ao, ac = pi.ao_ac(high, low, 5, 34, 5)
    stc_v = pi.stc(close, 12, 26, 50, 0.5)
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        vm = np.where(vol_ma > 0, vol_ma, np.nan)
        a = np.where(atr > 0, atr, np.nan)
        cross = (o - break_ma) / vm
        ac_a = ac / a
    return {
        "obv_cross_vol": (cross.astype(float), (-cross).astype(float)),
        "ac_atr": (ac_a.astype(float), (-ac_a).astype(float)),
        "stc_room": ((STC_OB - stc_v).astype(float), (stc_v - STC_OS).astype(float)),
    }
