"""Entry strength of V39_ALL (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:v39_signals via v39_all, chart timeframe,
stc_filter=False). Two entry types share a 2-bar cooldown:
  type A: ST(10, 3) and ST(10, 6) up, +DI20 - -DI20 >= 2, chop angle(34, 30, 25) >= 2, ADX(20, 20) in [10, 60],
          MACD histogram < 0 and rising, AO/AC condition, trigger = armed stochastic golden cross or
          DMI(16) +DI crossing above -DI;
  type B: ST(10, 3) up, ADX >= 10, |+DI20 - -DI20| >= 2, |chop angle| >= 2, first bar of AC < 0 rising with
          AO < 0 falling.  Shorts mirror.
The features measure the trend conditions both entry types check on the signal bar (the triggers differ by
type and oscillator, so they are not measured):
  di_gap        +DI20 - -DI20 long;  -DI20 - +DI20 short  (DMI(20) of the rule; type A needs >= 2)
  chop_angle    chop angle long;  -chop angle short      (degrees; type A needs >= 2 / <= -2, type B |.| >= 2)
  st_dist_atr   (close - ST(10,3) line) / ATR14 while ST(10,3) is up (long), (line - close) / ATR14 while it is
                down (short); NaN on the other side (every V39 signal needs ST(10,3) in its direction)
di_gap and chop_angle are signed in the trade direction: type-A entries have them >= 2, type-B (AC-first)
entries only need |gap| >= 2 and |angle| >= 2, so a counter-trend type-B entry reads negative (weak alignment).
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
import pine_indicators as pi  # noqa: E402
from strategies import _f  # noqa: E402

NAME = "V39_ALL"

FEATURES = [
    {"name": "di_gap", "label_ko": "+DI와 -DI의 차이", "unit": "DI points",
     "higher_is_stronger": True,
     "why": "DMI(20) directional gap in the trade direction (long +DI - -DI, short -DI - +DI): the 'DI gap >= 2' trend condition."},
    {"name": "chop_angle", "label_ko": "EMA34 기울기 각도", "unit": "degrees",
     "higher_is_stronger": True,
     "why": "Chop-zone angle(34,30,25) in the trade direction (long angle, short -angle): the 'chop angle >= 2 / <= -2' slope condition."},
    {"name": "st_dist_atr", "label_ko": "슈퍼트렌드선과 거리", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the close is beyond the ST(10,3) line on its trend side, in ATR14: the 'ST(10,3) up / down' condition every V39 entry needs."},
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
    plus20, minus20 = pi.dmi(high, low, close, 20)
    chop = pi.chop_angle(high, low, close, 34, 30, 25.0)
    line3, d3 = pi.exchange_supertrend(high, low, close, 10, 3.0)
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        gap = plus20 - minus20
        dist = (close - line3) / a
    st_long = np.where(d3 == 1, dist, np.nan)
    st_short = np.where(d3 == -1, -dist, np.nan)
    return {
        "di_gap": (gap.astype(float), (-gap).astype(float)),
        "chop_angle": (chop.astype(float), (-chop).astype(float)),
        "st_dist_atr": (st_long.astype(float), st_short.astype(float)),
    }
