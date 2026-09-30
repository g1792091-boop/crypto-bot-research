"""Entry strength of S4_BB_BBP (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/ports12.py:s4, variant 0, no timeframe scaling):
  up, mid, lo, bw = Bollinger(close, 20, 2.0), bw = (up - lo) / mid * 100
  thr = rolling 100-bar 20th percentile of bw;  squeeze = bw <= thr on any of bars i-1 .. i-5
  bbp = Bull/Bear Power(13) = (high - EMA13) + (low - EMA13)
  long  = squeeze & close > up & close[-1] <= up[-1] & bbp > 0
  short = squeeze & close < lo & close[-1] >= lo[-1] & bbp < 0      (then short &= ~long)

The break and the power are conditions of the signal bar; the squeeze is read on bars i-1 .. i-5 exactly as
the rule does. Every value at bar i uses bars <= i only. Defined from the strategy code only, without
computing or looking at any trading outcome.
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

NAME = "S4_BB_BBP"
SQUEEZE_BARS = 5  # squeeze on any of bars i-1 .. i-5

FEATURES = [
    {"name": "band_break_atr", "label_ko": "볼린저 밴드 돌파 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "(close - upper band) / ATR14 for longs, (lower band - close) / ATR14 for shorts on the signal "
            "bar: how far the close broke through the Bollinger(20, 2) band the rule requires."},
    {"name": "squeeze_ratio", "label_ko": "직전 밴드 수축 정도", "unit": "bandwidth / 20th-pct threshold",
     "higher_is_stronger": False,
     "why": "Smallest bandwidth / (100-bar 20th-percentile threshold) over bars i-1..i-5 (same for both "
            "sides; a zero bandwidth counts as 0): how deep the required squeeze (ratio <= 1) was."},
    {"name": "bbp_atr", "label_ko": "불베어 파워 크기", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Bull/Bear Power(13) = high + low - 2 EMA13 over ATR14 on the signal bar (negated for shorts): "
            "how far past zero the 'power > 0 (< 0)' condition is."},
]


def _arr(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _finite(x) -> np.ndarray:
    x = np.array(x, dtype=float)
    x[~np.isfinite(x)] = np.nan
    return x


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    close = df["close"]
    c = _arr(close)
    atr = _arr(fg.atr(df, 14))
    up, _mid, lo, bw = fg.bollinger_bands(close, 20, 2.0)
    thr = _arr(fg.rolling_percentile_threshold(bw, 100, 0.2))
    _bu, _be, bbp = fg.bull_bear_power(df, 13)
    bw = _arr(bw)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        ratio = bw / np.where(thr > 0, thr, np.nan)
        brk_long = (c - _arr(up)) / a
        brk_short = (_arr(lo) - c) / a
        power = _arr(bbp) / a
    # bandwidth 0 (flat closes) is <= any threshold, so it is the deepest squeeze: ratio 0, also when the
    # threshold itself is 0 (0 / 0 would leave a squeeze bar the rule counts without a value)
    ratio = np.where(np.isfinite(thr) & (bw == 0), 0.0, _finite(ratio))
    # min over bars i-1 .. i-5 (shift 1, then a 5-bar window), NaN-skipping
    sq = pd.Series(ratio).shift(1).rolling(SQUEEZE_BARS, min_periods=1).min().to_numpy(dtype=float)
    return {
        "band_break_atr": (_finite(brk_long), _finite(brk_short)),
        "squeeze_ratio": (sq, sq.copy()),
        "bbp_atr": (_finite(power), _finite(-power)),
    }
