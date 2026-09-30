"""Entry strength of S3_CMO_SANDWICH (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/ports12.py:s3, variant 0, no timeframe scaling), a = ATR14,
body b = close - open, a pattern completes on bar j (bars j-2, j-1, j):
  bull (long)  = closes fell before the pattern (c[j-3] < c[j-7]) & all three |b| >= 0.08 a
                 & bodies down, up, down & |low[j-2] - low[j]| <= 0.3 a & c[j] >= min(low[j-2], low[j]) - 0.075 a
  bear (short) = closes rose before (c[j-3] > c[j-7]) & bodies up, down, up & |high[j-2] - high[j]| <= 0.3 a
                 & c[j] <= max(high[j-2], high[j]) + 0.075 a   (same body rule)
  long  = recent(bull, 3) & recent(CMO14 crosses above 0, 3) & CMO14 > 0 & (bull | CMO cross up)
  short = recent(bear, 3) & recent(CMO14 crosses below 0, 3) & CMO14 < 0 & (bear | CMO cross down)
  short &= ~long (sweep_lib._clean)

The pattern behind a signal on bar i completed on bar j in i-2 .. i; the two pattern features are read on
the most recent such j (the same choice the locked stop uses), so they need only bars <= j <= i. CMO is a
condition of the signal bar itself. Defined from the strategy code only, without computing or looking at
any trading outcome.
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

NAME = "S3_CMO_SANDWICH"
PATTERN_WINDOW = 3  # recent(pattern, 3): pattern bar j in i-2 .. i

FEATURES = [
    {"name": "cmo_level", "label_ko": "CMO가 0에서 먼 정도", "unit": "CMO points",
     "higher_is_stronger": True,
     "why": "CMO(14) on the signal bar (negated for shorts): how far past the zero line of the "
            "'CMO > 0' ('CMO < 0') condition that follows the CMO zero cross."},
    {"name": "sandwich_match_atr", "label_ko": "샌드위치 양끝 맞춤 오차", "unit": "ATR14",
     "higher_is_stronger": False,
     "why": "|low[j-2] - low[j]| / ATR14 (long) or |high[j-2] - high[j]| / ATR14 (short) of the most recent "
            "pattern bar j: how exactly the stick-sandwich 'matching lows (highs) within 0.3 ATR' rule holds."},
    {"name": "prior_move_atr", "label_ko": "패턴 전 하락/상승 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "(c[j-7] - c[j-3]) / ATR14 (long) or (c[j-3] - c[j-7]) / ATR14 (short) of the most recent pattern "
            "bar j: size of the prior fall (rise) the pattern's trend condition requires."},
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


def _shb(x: np.ndarray, k: int) -> np.ndarray:
    out = np.zeros(len(x), dtype=bool)
    if k == 0:
        out[:] = x
    elif k < len(x):
        out[k:] = x[:-k]
    return out


def _latest(pattern: np.ndarray, value: np.ndarray) -> np.ndarray:
    """value on the most recent bar j in i-2 .. i where pattern fired (NaN if none)."""
    out = np.full(len(value), np.nan)
    for lag in range(PATTERN_WINDOW - 1, -1, -1):  # later assignment = more recent pattern wins
        out = np.where(_shb(pattern, lag), _sh(value, lag), out)
    return out


def _patterns(df):
    """(bull, bear, ATR14, high, low, close); bull / bear exactly as ports12.s3 variant 0 builds them."""
    o, h, l, c = (_arr(df[k]) for k in ("open", "high", "low", "close"))
    a = _arr(fg.atr(df, 14))
    b = c - o
    b1, b2, b3 = _sh(b, 2), _sh(b, 1), b
    h1, h3, l1, l3 = _sh(h, 2), h, _sh(l, 2), l
    last, first = _sh(c, 3), _sh(c, 7)
    with np.errstate(invalid="ignore"):
        up_prior, dn_prior = last > first, last < first
        bodies = (np.abs(b1) >= 0.08 * a) & (np.abs(b2) >= 0.08 * a) & (np.abs(b3) >= 0.08 * a)
        bear = up_prior & bodies & (b1 > 0) & (b2 < 0) & (b3 > 0) & (np.abs(h1 - h3) <= 0.3 * a) \
            & (c <= np.maximum(h1, h3) + 0.075 * a)
        bull = dn_prior & bodies & (b1 < 0) & (b2 > 0) & (b3 < 0) & (np.abs(l1 - l3) <= 0.3 * a) \
            & (c >= np.minimum(l1, l3) - 0.075 * a)
    return bull, bear, a, h, l, c


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    bull, bear, a, h, l, c = _patterns(df)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(a > 0, a, np.nan)
        match_long = np.abs(_sh(l, 2) - l) / a
        match_short = np.abs(_sh(h, 2) - h) / a
        prior = (_sh(c, 7) - _sh(c, 3)) / a
    cm = _finite(_arr(fg.cmo(df["close"], 14)))
    return {
        "cmo_level": (cm, _finite(-cm)),
        "sandwich_match_atr": (_finite(_latest(bull, match_long)), _finite(_latest(bear, match_short))),
        "prior_move_atr": (_finite(_latest(bull, prior)), _finite(_latest(bear, -prior))),
    }
