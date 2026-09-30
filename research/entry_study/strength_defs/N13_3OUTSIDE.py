"""Entry-strength numbers for N13_3OUTSIDE (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/ports12.py:n13, variant 0, no timeframe scaling; checked
chart view paperbot/strategy_view_defs/N13_3OUTSIDE.py), body b = close - open, a = ATR14. A Three
Outside Up pattern completes on bar j (bars j-2, j-1, j):
  bull(j) = closes fell before the pattern (c[j-3] < c[j-7]) & bar j-2 bearish
            & bar j-1 bullish with body >= 0.5 a[j] engulfing bar j-2's body (o[j-1] <= c[j-2], c[j-1] >= o[j-2])
            & bar j bullish & c[j] > c[j-1]
  bear(j) = mirror (prior rise, bullish then bearish engulfing >= 0.5 a[j], bearish bar j, c[j] < c[j-1])
  long on bar i  = bull(j) for j = i-1 or i-2 & close[i] > max(high[j-2 .. j]) & close[i-1] <= that high
  short on bar i = bear(j) for j = i-1 or i-2 & close[i] < min(low[j-2 .. j]) & close[i-1] >= that low
  short &= ~long (ports12._pack / sweep_lib._clean)
A bull (bear) pattern cannot complete on two bars less than 3 apart: a bull pattern on j+1 would need
bar j-1 bearish (it is pattern j's bullish engulfing bar), one on j+2 would need bar j bearish (it is
bullish). So the pattern behind a signal is unique.

The pattern features are read on that pattern bar j (i-1 or i-2), the breakout on the signal bar i; NaN
when no pattern of that side completed 1 or 2 bars before. Defined from the strategy code only; no
trading outcome was computed or looked at when writing them. Every value at bar i uses bars <= i only.
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

NAME = "N13_3OUTSIDE"
LAGS = (2, 1)  # pattern completed 2 or 1 bars before the signal bar (later assignment = more recent wins)

FEATURES = [
    {"name": "engulf_body_atr", "label_ko": "장악형 봉 몸통 크기", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Body of the engulfing middle bar of the pattern, (c - o)[j-1] / ATR14[j] for longs "
            "(bullish), (o - c)[j-1] / ATR14[j] for shorts (bearish); the rule needs >= 0.5."},
    {"name": "confirm_close_atr", "label_ko": "셋째 봉이 더 나간 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Third-bar confirmation: (c[j] - c[j-1]) / ATR14[j] for longs, (c[j-1] - c[j]) / ATR14[j] "
            "for shorts; the rule needs > 0 (close beyond the engulfing bar's close)."},
    {"name": "breakout_atr", "label_ko": "패턴 고저 돌파 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the signal bar's close is past the pattern's 3-bar high (long) or low (short) that it "
            "breaks for the first time: (close - pattern high) / ATR14 or (pattern low - close) / ATR14."},
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


def _shb(x, k: int) -> np.ndarray:
    x = np.asarray(x, dtype=bool)
    out = np.zeros(len(x), dtype=bool)
    if k == 0:
        out[:] = x
    elif k < len(x):
        out[k:] = x[:-k]
    return out


def _roll(x, n: int, how: str) -> np.ndarray:
    r = pd.Series(_arr(x)).rolling(n, min_periods=n)
    return (r.max() if how == "max" else r.min()).to_numpy()


def patterns(df: pd.DataFrame):
    """(bull, bear) pattern-completion bars exactly as ports12.n13 variant 0 builds them, plus ATR14."""
    o, c = _arr(df["open"]), _arr(df["close"])
    a = _arr(fg.atr(df, 14))
    b = c - o
    last, first = _sh(c, 3), _sh(c, 7)
    B1, B2, B3 = _sh(b, 2), _sh(b, 1), b
    O1, C1, O2, C2 = _sh(o, 2), _sh(c, 2), _sh(o, 1), _sh(c, 1)
    with np.errstate(invalid="ignore"):
        upp, dnp = last > first, last < first
        bull = dnp & (B1 < 0) & (B2 > 0) & (B2 >= 0.5 * a) & (O2 <= C1) & (C2 >= O1) & (B3 > 0) & (c > C2)
        bear = upp & (B1 > 0) & (B2 < 0) & (-B2 >= 0.5 * a) & (O2 >= C1) & (C2 <= O1) & (B3 < 0) & (c < C2)
    return bull, bear, a


def _at_pattern(pattern: np.ndarray, value: np.ndarray) -> np.ndarray:
    """value on the pattern bar j = i-1 or i-2 (the unique one), NaN when there is none."""
    out = np.full(len(value), np.nan)
    for lag in LAGS:
        out = np.where(_shb(pattern, lag), _sh(value, lag), out)
    return out


def strength(df: pd.DataFrame, tf: str) -> dict:
    """{feature name: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    bull, bear, a = patterns(df)
    c = _arr(df["close"])
    b = c - _arr(df["open"])
    ph3, pl3 = _roll(df["high"], 3, "max"), _roll(df["low"], 3, "min")
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(a > 0, a, np.nan)
        engulf = _sh(b, 1) / a                 # on bar j: body of bar j-1 over ATR of bar j
        confirm = (c - _sh(c, 1)) / a          # on bar j: c[j] - c[j-1]
        brk_l = (c - _at_pattern(bull, ph3)) / a
        brk_s = (_at_pattern(bear, pl3) - c) / a
    return {
        "engulf_body_atr": (_finite(_at_pattern(bull, engulf)), _finite(_at_pattern(bear, -engulf))),
        "confirm_close_atr": (_finite(_at_pattern(bull, confirm)), _finite(_at_pattern(bear, -confirm))),
        "breakout_atr": (_finite(brk_l), _finite(brk_s)),
    }
