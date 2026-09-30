"""Entry-strength numbers for N09_ALLIG_AROON (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n09_alligator_aroon, no timeframe
scaling; checked chart view paperbot/strategy_view_defs/N09_ALLIG_AROON.py):
  lips, teeth, jaw = SMA5, SMA8, SMA13 of the close; Aroon(25) up / down
  long  = lips above both teeth and jaw (and it just got there, within 2 bars)
          & Aroon up crossed above Aroon down within 2 bars & Aroon up >= Aroon down
          & (one of the two events on this bar)
  short = mirror (lips below both, Aroon down crossed above Aroon up, Aroon down >= Aroon up).

The numbers below measure how strongly those conditions hold on the signal bar. They are defined
from the strategy code only; no trading outcome was computed or looked at when writing them.
Every value at bar i uses bars <= i only (rolling means, rolling 25-bar Aroon, Wilder ATR).
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
from strategies import cross_above, cross_below, gt, lt, shift_bool  # noqa: E402

NAME = "N09_ALLIG_AROON"

FEATURES = [
    {"name": "aroon_spread", "label_ko": "아룬 상승·하락 차이", "unit": "아룬 포인트(0~100)",
     "higher_is_stronger": True,
     "why": "How far the required Aroon(25) cross has gone on the signal bar: Aroon up - Aroon down for "
            "longs, Aroon down - Aroon up for shorts (the rule needs it >= 0)."},
    {"name": "lips_gap_atr", "label_ko": "입술선이 벌어진 폭(ATR)", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the lips line (SMA5) is past both teeth (SMA8) and jaw (SMA13): (lips - max(teeth, "
            "jaw)) / ATR14 for longs, (min(teeth, jaw) - lips) / ATR14 for shorts."},
    {"name": "sync_gap_bars", "label_ko": "두 신호 사이 봉 수", "unit": "봉(0~1)",
     "higher_is_stronger": False,
     "why": "Bars between the two required trigger events (lips crossing past teeth and jaw, and the "
            "Aroon cross): the older one's age, 0 = both on the signal bar (sync window 2)."},
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
    close = df["close"]
    lips, teeth, jaw = _arr(fg.sma(close, 5)), _arr(fg.sma(close, 8)), _arr(fg.sma(close, 13))
    atr = _arr(fg.atr(df, 14))
    lips_above = gt(lips, teeth) & gt(lips, jaw)
    lips_below = lt(lips, teeth) & lt(lips, jaw)
    a_up = lips_above & ~shift_bool(lips_above, 1)
    a_down = lips_below & ~shift_bool(lips_below, 1)
    up, down = fg_fast.aroon(df, 25)
    up, down = _arr(up), _arr(down)
    ar_up, ar_down = cross_above(up, down), cross_below(up, down)
    with np.errstate(divide="ignore", invalid="ignore"):
        gap_long = (lips - np.fmax(teeth, jaw)) / atr
        gap_short = (np.fmin(teeth, jaw) - lips) / atr
    # np.fmax / np.fmin would ignore a NaN side; the rule needs both lines, so NaN if either is NaN
    both = np.isfinite(teeth) & np.isfinite(jaw)
    gap_long[~both] = np.nan
    gap_short[~both] = np.nan
    return {
        "aroon_spread": (_finite(up - down), _finite(down - up)),
        "lips_gap_atr": (_finite(gap_long), _finite(gap_short)),
        # np.maximum propagates NaN: undefined until both events have happened once
        "sync_gap_bars": (np.maximum(_bars_since(a_up), _bars_since(ar_up)),
                          np.maximum(_bars_since(a_down), _bars_since(ar_down))),
    }
