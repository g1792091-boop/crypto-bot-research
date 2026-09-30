"""Entry strength of S2_ST_ROC (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:s2_supertrend_roc):
  long  = supertrend(10, 6) up   & ROC(9) > 0 & (supertrend flips up on this bar   | ROC crosses above 0 on this bar)
  short = supertrend(10, 6) down & ROC(9) < 0 & (supertrend flips down on this bar | ROC crosses below 0 on this bar)

st_age_bars is NaN until the first supertrend flip of the series (the first trend's start is not
observed); after warm-up this happens on a handful of period-3 4h signals only.
Every value at bar i uses bars <= i only (EWM / rolling / the supertrend recursion are causal).
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

sweepsig.lib()  # hash-checked locked code; puts the vendored indicator modules on sys.path

import fg_fast  # noqa: E402
import fg_indicators as fg  # noqa: E402
from strategies import _f, ge, gt, le, lt  # noqa: E402

NAME = "S2_ST_ROC"

FEATURES = [
    {"name": "roc_past_zero", "label_ko": "ROC가 0을 넘은 크기", "unit": "% (ROC 9)",
     "higher_is_stronger": True,
     "why": "How far ROC(9) is past its 0 line in the trade direction (long ROC, short -ROC): the 'ROC > 0 / < 0' condition."},
    {"name": "st_line_dist_atr", "label_ko": "슈퍼트렌드선과의 거리", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the close is beyond the supertrend(10, 6) line on the trade side, in ATR14: the 'supertrend up / down' condition."},
    {"name": "st_age_bars", "label_ko": "슈퍼트렌드 전환 후 봉 수", "unit": "bars",
     "higher_is_stronger": True,
     "why": "Bars since the supertrend(10, 6) turned to the trade side (0 = the flip trigger itself): how long the direction condition has held."},
]


def _bars_since(event: np.ndarray) -> np.ndarray:
    """Bars since the last True of ``event`` at or before each bar (0 on the event bar); NaN before the first."""
    e = np.asarray(event, dtype=bool)
    idx = np.arange(len(e))
    last = np.maximum.accumulate(np.where(e, idx, -1)) if len(e) else np.zeros(0, dtype=np.int64)
    out = (idx - last).astype(float)
    out[last < 0] = np.nan
    return out


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    n = len(df)
    close = df["close"].to_numpy(dtype=float)
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    d, ln = _f(direction), _f(line)
    r = fg.roc(df["close"], 9).to_numpy(dtype=float)
    dp = np.r_[np.nan, d[:-1]] if n else d
    flip_up = gt(d, 0) & le(dp, 0)
    flip_down = lt(d, 0) & ge(dp, 0)
    up, down = gt(d, 0), lt(d, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        dist = (close - ln) / a
    nan = np.full(n, np.nan)
    return {
        "roc_past_zero": (r.copy(), -r),
        "st_line_dist_atr": (np.where(up, dist, nan), np.where(down, -dist, nan)),
        "st_age_bars": (np.where(up, _bars_since(flip_up), nan), np.where(down, _bars_since(flip_down), nan)),
    }
