"""Entry strength of V45_AMB (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/sweep_lib.py:v45_signals_gen via v45_amb; HTF = sweep_lib.HTF_OF[tf]
resampled from the chart bars, value of the last HTF bar closed by the chart bar's open), long side:
    HTF ST(14, 6) up & STC(chart) < 75 & STC(HTF) < 75
    & chart ST(14, 6) and ST(14, 3) opposite & chop angle(34, 30, 25) <= -0.71 (EMA34 sloping down)
    & a stochastic golden cross at/under 50 with MACD(12, 26, 9) histogram < 0 and rising
    & NOT (AC < 0 rising & AO < 0 falling).     Shorts mirror.
It buys a pullback inside a higher-timeframe up-trend. The features, all read on the signal bar:
  stc_room        75 - max(STC chart, STC HTF) long;  min(STC chart, STC HTF) - 25 short
                  (how far the tighter of the two STC readings is inside the allowed side)
  pullback_angle  -chop angle long;  chop angle short   (degrees; the rule needs <= -0.71 / >= 0.71, so larger =
                  steeper counter-trend EMA34 slope)
  macd_hist_atr   -hist / ATR14 long;  hist / ATR14 short (depth of the MACD histogram on the pullback side,
                  the rule needs hist < 0 and rising / > 0 and falling)
Every value at bar i uses bars <= i only (the HTF STC comes from HTF bars that closed by bar i's open).
Defined without looking at any trading outcome.
"""

from __future__ import annotations

import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from paperbot import sweepsig  # noqa: E402

_L = sweepsig.lib()  # hash-checked locked code; puts the vendored indicator modules on sys.path

import fg_indicators as fg  # noqa: E402
import pine_indicators as pi  # noqa: E402
from strategies import _f  # noqa: E402

NAME = "V45_AMB"
STC_HI, STC_LO = 75.0, 25.0

FEATURES = [
    {"name": "stc_room", "label_ko": "STC 과열·침체선까지 여유", "unit": "STC points",
     "higher_is_stronger": True,
     "why": "Room of the tighter STC (chart and higher timeframe) inside its limit (long 75 - max, short min - 25): the 'STC < 75 / > 25 on both frames' filter."},
    {"name": "pullback_angle", "label_ko": "EMA34 되돌림 기울기", "unit": "degrees",
     "higher_is_stronger": True,
     "why": "Chop-zone angle(34,30,25) against the trade (long -angle, short angle): the 'chop angle <= -0.71 / >= 0.71' pullback-slope condition."},
    {"name": "macd_hist_atr", "label_ko": "MACD 히스토그램 깊이", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "MACD(12,26,9) histogram depth on the pullback side (long -hist, short hist) in ATR14: the 'histogram < 0 and rising / > 0 and falling' trigger condition."},
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
    htf = _L.HTF_OF[tf]
    dfh = _L.resample_ohlcv(df, htf)
    _d, stc_h = _L.v45_htf_components(df, dfh, htf, "closed")
    high, low, close = _f(df["high"]), _f(df["low"]), _f(df["close"])
    stc_c = pi.stc(close, 12, 26, 50, 0.5)
    chop = pi.chop_angle(high, low, close, 34, 30, 25.0)
    _ml, _ms, hist = pi.pine_macd(close, 12, 26, 9)
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    stc_h = np.asarray(stc_h, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        room_long = STC_HI - np.maximum(stc_c, stc_h)      # NaN while the HTF STC is not available
        room_short = np.minimum(stc_c, stc_h) - STC_LO
        h_a = hist / a
    return {
        "stc_room": (room_long.astype(float), room_short.astype(float)),
        "pullback_angle": ((-chop).astype(float), chop.astype(float)),
        "macd_hist_atr": ((-h_a).astype(float), h_a.astype(float)),
    }
