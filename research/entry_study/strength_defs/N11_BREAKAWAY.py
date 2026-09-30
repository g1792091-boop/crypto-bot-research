"""Entry-strength numbers for N11_BREAKAWAY (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/ports12.py:n11, variant 0, no timeframe scaling; checked
chart view paperbot/strategy_view_defs/N11_BREAKAWAY.py). Five bars, bar 5 = the signal bar t,
body b = close - open, B1..B5 = bodies of bars t-4 .. t, a = ATR14 of bar t:
  long  = closes fell before the pattern (c[t-5] < c[t-9])
          & bar 1 bearish with -B1 >= 0.8 a & bar 2 bearish opening at or below bar 1's close (+ 0.05 a)
          & |B3| <= 0.4 a & |B4| <= 0.4 a
          & bar 5 bullish with B5 >= 0.8 a & close > bar 2's close
  short = mirror (prior rise, bar 1 bullish >= 0.8 a, bar 2 bullish opening >= bar 1 close - 0.05 a,
          small bars 3-4, bar 5 bearish with -B5 >= 0.8 a, close < bar 2's close)
  short &= ~long (ports12._pack / sweep_lib._clean)

The numbers below are the pattern's own ATR-sized body thresholds, measured on the signal bar. They are
defined from the strategy code only; no trading outcome was computed or looked at when writing them.
Every value at bar t uses bars t-4 .. t and ATR14 of bar t (Wilder's running average), i.e. bars <= t.
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

NAME = "N11_BREAKAWAY"

FEATURES = [
    {"name": "reversal_body_atr", "label_ko": "마지막 반전 봉 몸통", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Body of bar 5, the reversal bar that is the signal bar: B5 / ATR14 for longs (bullish), "
            "-B5 / ATR14 for shorts (bearish); the rule needs >= 0.8."},
    {"name": "first_body_atr", "label_ko": "첫 큰 봉 몸통", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Body of bar 1, the trend bar that opens the pattern four bars before the signal: "
            "-B1 / ATR14 for longs (bearish), B1 / ATR14 for shorts (bullish); the rule needs >= 0.8."},
    {"name": "pause_body_atr", "label_ko": "가운데 두 봉 몸통", "unit": "ATR14",
     "higher_is_stronger": False,
     "why": "max(|B3|, |B4|) / ATR14: how small the two pause bars before the reversal are; the rule "
            "needs <= 0.4 (same value for both sides)."},
]


def _arr(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _finite(x) -> np.ndarray:
    x = np.array(x, dtype=float)
    x[~np.isfinite(x)] = np.nan
    return x


def _sh(x, k: int) -> np.ndarray:
    """x shifted k bars into the past (NaN for the first k bars)."""
    x = _arr(x)
    out = np.full(len(x), np.nan)
    if k == 0:
        out[:] = x
    elif k < len(x):
        out[k:] = x[:-k]
    return out


def strength(df: pd.DataFrame, tf: str) -> dict:
    """{feature name: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    b = _arr(df["close"]) - _arr(df["open"])
    a = _arr(fg.atr(df, 14))
    B1, B3, B4 = _sh(b, 4), _sh(b, 2), _sh(b, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(a > 0, a, np.nan)
        rev = b / a
        first = B1 / a
        pause = np.maximum(np.abs(B3), np.abs(B4)) / a
    return {
        "reversal_body_atr": (_finite(rev), _finite(-rev)),
        "first_body_atr": (_finite(-first), _finite(first)),
        "pause_body_atr": (_finite(pause), _finite(pause)),
    }
