"""Entry strength of N17_KC_RSI (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n17_keltner_rsi), Keltner EMA20 +/- 2 x ATR14,
approach 0.10 x ATR14, RSI 14, synchronized 2:
  long_touch  = low  <= lower + 0.10 ATR14      long_rsi  = RSI14 <= 30
  short_touch = high >= upper - 0.10 ATR14      short_rsi = RSI14 >= 70
  long  = synchronized([long_touch, long_rsi], 2)
  short = synchronized([short_touch, short_rsi], 2) & ~long
synchronized(parts, 2) is true on bar i when every part was true on bar i or i-1 (window ending at i) or on
bar i-1 or i-2 (window ending at i-1), so the conditions behind a signal on bar i lie in bars i-2 .. i. Both
features therefore take the most extreme value over that 3-bar sync window.

RSI values from before fg.rsi has its Wilder averages (the locked RSI reads 0 there, a warm-up artifact)
are treated as missing. Every value at bar i uses bars <= i only. Defined without looking at any trading
outcome.
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
from strategies import _f  # noqa: E402

NAME = "N17_KC_RSI"
SYNC_WINDOW = 3  # bars i-2 .. i (synchronized(..., 2) = window ending at i or at i-1)

FEATURES = [
    {"name": "rsi_depth", "label_ko": "RSI가 30/70을 넘은 깊이", "unit": "RSI points",
     "higher_is_stronger": True,
     "why": "Deepest RSI(14) past its level over the 3-bar sync window (long 30 - min RSI, short max RSI - 70): the 'RSI <= 30 / >= 70' condition."},
    {"name": "band_pierce_atr", "label_ko": "켈트너 밴드 밖으로 나간 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Furthest the low went below the lower Keltner band EMA20 - 2 ATR14 (long) / the high above the upper band (short) over the 3-bar sync window, in ATR14: the band-touch condition (fires from -0.10)."},
]


def _rsi_ready(close: pd.Series, length: int = 14) -> np.ndarray:
    """True once fg.rsi has its Wilder averages (before that the locked RSI reads 0)."""
    return (close.diff().notna().cumsum() >= length).to_numpy()


def _roll(x: np.ndarray, how: str) -> np.ndarray:
    """Rolling min / max over the last SYNC_WINDOW bars (bars i-2 .. i), NaN-skipping; NaN if all missing."""
    r = pd.Series(np.asarray(x, dtype=float)).rolling(SYNC_WINDOW, min_periods=1)
    return (r.min() if how == "min" else r.max()).to_numpy(dtype=float)


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    close_s = df["close"]
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    mid = _f(fg.ema(close_s, 20))
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    upper, lower = mid + atr * 2.0, mid - atr * 2.0
    r = _f(fg.rsi(close_s, 14))
    r = np.where(_rsi_ready(close_s, 14), r, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        pierce_long = (lower - low) / a
        pierce_short = (high - upper) / a
    return {
        "rsi_depth": (30.0 - _roll(r, "min"), _roll(r, "max") - 70.0),
        "band_pierce_atr": (_roll(pierce_long, "max"), _roll(pierce_short, "max")),
    }
