"""Entry strength of N01_ST_EMA (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n01_supertrend_ema), EMA 5 / EMA 20,
supertrend(10, 6), sync 2:
  long  = EMA5 crossed above EMA20 within 2 bars & supertrend up   & (EMA cross or supertrend flip up on this bar)
  short = EMA5 crossed below EMA20 within 2 bars & supertrend down & (EMA cross or supertrend flip down on this bar)

st_age_bars is NaN until the first supertrend flip of the series (the first trend's start is not
observed); after warm-up this happens on a handful of period-3 4h signals only.
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

import fg_fast  # noqa: E402
import fg_indicators as fg  # noqa: E402
from strategies import _f, ge, gt, le, lt  # noqa: E402

NAME = "N01_ST_EMA"

FEATURES = [
    {"name": "ema_gap_atr", "label_ko": "EMA5·20 벌어진 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "(EMA5 - EMA20) / ATR14 for long, (EMA20 - EMA5) / ATR14 for short: size of the EMA5/EMA20 cross condition."},
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
    ef = _f(fg.ema(df["close"], 5))
    es = _f(fg.ema(df["close"], 20))
    line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    d, ln = _f(direction), _f(line)
    dp = np.r_[np.nan, d[:-1]] if n else d
    flip_up = gt(d, 0) & le(dp, 0)
    flip_down = lt(d, 0) & ge(dp, 0)
    up, down = gt(d, 0), lt(d, 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        gap = (ef - es) / a
        dist = (close - ln) / a
    nan = np.full(n, np.nan)
    return {
        "ema_gap_atr": (gap, -gap),
        "st_line_dist_atr": (np.where(up, dist, nan), np.where(down, -dist, nan)),
        "st_age_bars": (np.where(up, _bars_since(flip_up), nan), np.where(down, _bars_since(flip_down), nan)),
    }
