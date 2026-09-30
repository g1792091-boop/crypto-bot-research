"""Entry strength of S1_EMA_RSI_CHOP (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/ports12.py:s1, variant 0, no timeframe scaling):
  e5, e20 = EMA5, EMA20 of close;  r = RSI14;  angle = degrees(arctan((EMA34 - EMA34[-1]) / ATR14))
  cz (chop zone) = +1/+2 when angle >= 1, -1/-2 when angle <= -1, else 0   (fg.chop_zone_proxy(34, 1, 5, 14))
  eu = EMA5 crosses above EMA20;  ru = RSI[-1] < 30 & RSI > RSI[-1];  cu = cz[-1] <= 0 & cz > 0
  long  = recent(eu, 3) & recent(ru, 3) & recent(cu, 3) & EMA5 > EMA20 & cz > 0 & (eu | ru | cu)
  short = mirror (EMA5 crosses below, RSI[-1] > 70 turning down, cz turns negative), then short &= ~long.

recent(x, 3) is true on bar i when x fired on bar i-2, i-1 or i, so the RSI hook behind a signal on bar i
had its RSI below 30 (above 70) on one of bars i-3 .. i-1. rsi_extreme therefore takes the most extreme
RSI over bars i-3 .. i. The EMA gap and the chop angle are conditions of the signal bar itself.

RSI values from before fg.rsi has its Wilder averages (the locked RSI reads 0 there, a warm-up artifact)
are treated as missing. Every value at bar i uses bars <= i only. Defined from the strategy code only,
without computing or looking at any trading outcome.
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

NAME = "S1_EMA_RSI_CHOP"
RSI_WINDOW = 4  # bars i-3 .. i: an RSI hook on bar j in i-2 .. i reads RSI[j-1]

FEATURES = [
    {"name": "rsi_extreme", "label_ko": "RSI가 30/70 밖으로 간 깊이", "unit": "RSI points",
     "higher_is_stronger": True,
     "why": "Deepest RSI(14) beyond its level over bars i-3..i (long 30 - min RSI, short max RSI - 70): the "
            "'RSI below 30 then turning up' (above 70 then turning down) hook that must fire within 3 bars."},
    {"name": "ema_gap_atr", "label_ko": "EMA5와 EMA20 벌어진 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "(EMA5 - EMA20) / ATR14 on the signal bar (mirrored for shorts): size of the required EMA5/EMA20 "
            "cross and of the 'EMA5 > EMA20' condition."},
    {"name": "chop_angle_deg", "label_ko": "찹존 기울기 각도", "unit": "degrees",
     "higher_is_stronger": True,
     "why": "Chop-zone angle of the signal bar, degrees(arctan(EMA34 1-bar change / ATR14)) (negated for "
            "shorts): how far past the +1 (-1) degree line of the 'chop zone up (down)' condition."},
]


def _arr(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _finite(x) -> np.ndarray:
    x = np.array(x, dtype=float)
    x[~np.isfinite(x)] = np.nan
    return x


def _rsi_ready(close: pd.Series, length: int = 14) -> np.ndarray:
    """True once fg.rsi has its Wilder averages (before that the locked RSI reads 0)."""
    return (close.diff().notna().cumsum() >= length).to_numpy()


def _roll(x: np.ndarray, n: int, how: str) -> np.ndarray:
    """Rolling min / max over bars i-n+1 .. i, NaN-skipping; NaN if all missing."""
    r = pd.Series(np.asarray(x, dtype=float)).rolling(n, min_periods=1)
    return (r.min() if how == "min" else r.max()).to_numpy(dtype=float)


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    close = df["close"]
    atr = _arr(fg.atr(df, 14))
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
    r = _arr(fg.rsi(close, 14))
    r = np.where(_rsi_ready(close, 14), r, np.nan)
    gap = (_arr(fg.ema(close, 5)) - _arr(fg.ema(close, 20))) / a
    angle, _cz, _st = fg.chop_zone_proxy(df, 34, 1.0, 5.0, 14)
    angle = _finite(_arr(angle))
    return {
        "rsi_extreme": (30.0 - _roll(r, RSI_WINDOW, "min"), _roll(r, RSI_WINDOW, "max") - 70.0),
        "ema_gap_atr": (_finite(gap), _finite(-gap)),
        "chop_angle_deg": (angle, _finite(-angle)),
    }
