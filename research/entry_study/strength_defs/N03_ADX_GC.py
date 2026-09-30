"""Entry-strength numbers for N03_ADX_GC (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n03_adx_golden_cross, no timeframe scaling):
  long  = EMA50 crossed above EMA200 in the last 3 bars & ADX(14) crossed above 25 in the last 3 bars
          & ADX >= 25 & (one of the two crosses is on this bar)
  short = same with EMA50 crossing below EMA200 (ADX has no direction; the ADX condition is shared).

The numbers below measure how strongly those conditions hold on the signal bar. They are defined
from the strategy code only; no trading outcome was computed or looked at when writing them.
Every value at bar i uses bars <= i only.
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
from strategies import cross_above, cross_below  # noqa: E402

NAME = "N03_ADX_GC"

FEATURES = [
    {"name": "adx_excess", "label_ko": "ADX 25 초과분", "unit": "ADX 포인트",
     "higher_is_stronger": True,
     "why": "How far ADX(14) is above the rule's 25 threshold on the signal bar (ADX - 25; same for "
            "longs and shorts because ADX has no direction)."},
    {"name": "ema_gap_atr", "label_ko": "EMA 50·200 간격(ATR)", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Size of the required EMA50/EMA200 golden (dead) cross on the signal bar: (EMA50 - EMA200) / "
            "ATR14 for longs, (EMA200 - EMA50) / ATR14 for shorts."},
    {"name": "cross_lag_bars", "label_ko": "두 교차 사이 봉 수", "unit": "봉",
     "higher_is_stronger": False,
     "why": "Bars between the two required trigger events (EMA cross and ADX crossing 25): the older "
            "one's age, since the rule needs one of them on the signal bar (0 = both on the same bar)."},
]


def _arr(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _finite(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float).copy()
    x[~np.isfinite(x)] = np.nan
    return x


def _bars_since(ev) -> np.ndarray:
    """Bars since the last True of ``ev`` (0 on an event bar, NaN before the first event); causal."""
    ev = np.asarray(ev, dtype=bool)
    n = len(ev)
    if n == 0:
        return np.zeros(0)
    last = np.maximum.accumulate(np.where(ev, np.arange(n), -1))
    out = (np.arange(n) - last).astype(float)
    out[last < 0] = np.nan
    return out


def strength(df: pd.DataFrame, tf: str) -> dict:
    """{feature name: (value for long signals, value for short signals)}, float arrays of len(df)."""
    atr = _arr(fg.atr(df, 14))
    ef = fg.ema(df["close"], 50)
    es = fg.ema(df["close"], 200)
    _p, _m, adx = fg.dmi_adx(df, 14, 14)
    gc, dc = cross_above(ef, es), cross_below(ef, es)
    adx_evt = cross_above(adx, 25.0)
    excess = _finite(_arr(adx) - 25.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        gap = (_arr(ef) - _arr(es)) / atr
    bs_adx = _bars_since(adx_evt)
    lag_long = np.fmax(_bars_since(gc), bs_adx)
    lag_short = np.fmax(_bars_since(dc), bs_adx)
    # np.fmax ignores one NaN; a lag needs both events to exist
    lag_long[np.isnan(_bars_since(gc)) | np.isnan(bs_adx)] = np.nan
    lag_short[np.isnan(_bars_since(dc)) | np.isnan(bs_adx)] = np.nan
    return {
        "adx_excess": (excess, excess.copy()),
        "ema_gap_atr": (_finite(gap), _finite(-gap)),
        "cross_lag_bars": (lag_long, lag_short),
    }
