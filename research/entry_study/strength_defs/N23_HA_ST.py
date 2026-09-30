"""Entry-strength numbers for N23_HA_ST (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n23_heikin_supertrend, no timeframe
scaling; checked chart view paperbot/strategy_view_defs/N23_HA_ST.py):
  Heikin-Ashi candles; fg_fast.supertrend_v2(df, 10, 6.0) direction ``up``
  long_ok  = HA green (ha_close > ha_open) & lower HA wick <= 2 % of the HA range & supertrend up
  short_ok = HA red & upper HA wick <= 2 % of the HA range & supertrend not up
  signal on the first bar of each run (long_ok & not long_ok on the previous bar; same for short).

The numbers below measure how strongly those conditions hold on the signal bar. They are defined
from the strategy code only; no trading outcome was computed or looked at when writing them.
Every value at bar i uses bars <= i only (the HA open and the supertrend are forward recursions,
ATR is Wilder's running average).
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
import fg_fast  # noqa: E402
import fg_indicators as fg  # noqa: E402
from strategies import ge, gt, le, lt  # noqa: E402

NAME = "N23_HA_ST"

FEATURES = [
    {"name": "ha_body_atr", "label_ko": "하이킨아시 몸통 크기", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Size of the required Heikin-Ashi colour on the signal bar: (HA close - HA open) / ATR14 "
            "for longs (green body), (HA open - HA close) / ATR14 for shorts (red body)."},
    {"name": "st_line_dist_atr", "label_ko": "슈퍼트렌드선과의 거리", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the close is beyond the supertrend(10, 6) line on the trade side, in ATR14: "
            "the 'supertrend up / down' condition."},
    {"name": "st_age_bars", "label_ko": "슈퍼트렌드 전환 후 봉 수", "unit": "봉",
     "higher_is_stronger": True,
     "why": "Bars since the supertrend(10, 6) turned to the trade side (0 = it flipped on the signal "
            "bar): how long the direction condition has held when the fresh HA setup appears. "
            "NaN before the series' first supertrend flip to that side (age unknown)."},
]


def _arr(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _finite(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float).copy()
    x[~np.isfinite(x)] = np.nan
    return x


def _bars_since(event: np.ndarray) -> np.ndarray:
    """Bars since the last True of ``event`` at or before each bar (0 on the event bar); NaN before the first."""
    e = np.asarray(event, dtype=bool)
    idx = np.arange(len(e))
    last = np.maximum.accumulate(np.where(e, idx, -1)) if len(e) else np.zeros(0, dtype=np.int64)
    out = (idx - last).astype(float)
    out[last < 0] = np.nan
    return out


def strength(df: pd.DataFrame, tf: str) -> dict:
    """{feature name: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    n = len(df)
    close = df["close"].to_numpy(dtype=float)
    atr = _arr(fg.atr(df, 14))
    a = np.where(atr > 0, atr, np.nan)
    ha = fg_fast.heikin_ashi(df)
    line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)   # supertrend_v2 = (line, direction > 0)
    d, ln = _arr(direction), _arr(line)
    dp = np.r_[np.nan, d[:-1]] if n else d
    up, down = gt(d, 0), lt(d, 0)
    flip_up = up & le(dp, 0)
    flip_down = down & ge(dp, 0)
    nan = np.full(n, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        body = (_arr(ha["ha_close"]) - _arr(ha["ha_open"])) / a
        dist = (close - ln) / a
    return {
        "ha_body_atr": (_finite(body), _finite(-body)),
        "st_line_dist_atr": (_finite(np.where(up, dist, nan)), _finite(np.where(down, -dist, nan))),
        "st_age_bars": (np.where(up, _bars_since(flip_up), nan), np.where(down, _bars_since(flip_down), nan)),
    }
