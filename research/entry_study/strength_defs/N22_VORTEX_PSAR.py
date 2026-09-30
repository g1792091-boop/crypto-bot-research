"""Entry strength of N22_VORTEX_PSAR (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n22_vortex_psar), vortex 14, parabolic SAR
(0.02, 0.02, 0.20), same bar:
  long  = close > SAR & VI+ crosses above VI-
  short = close < SAR & VI+ crosses below VI-   (& ~long)

psar_age_bars counts from the bar on which the close moved to the trade side of the SAR (0 = that bar). It
is NaN where the close is not on the trade side, and during the first run of the series (which starts at
the SAR's initial guess, not at an observed change of side).
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
from strategies import _f, gt, lt  # noqa: E402

NAME = "N22_VORTEX_PSAR"

FEATURES = [
    {"name": "vi_spread", "label_ko": "보텍스 VI+와 VI- 차이", "unit": "VI units",
     "higher_is_stronger": True,
     "why": "VI+ - VI- (long) / VI- - VI+ (short) of vortex(14) on the signal bar: size of the VI+ / VI- cross that triggers the entry."},
    {"name": "psar_dist_atr", "label_ko": "종가와 SAR 거리", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "(close - SAR) / ATR14 for long, (SAR - close) / ATR14 for short, SAR(0.02, 0.02, 0.20): how far the 'close above / below SAR' condition holds."},
    {"name": "psar_age_bars", "label_ko": "SAR 같은 편 유지 봉 수", "unit": "bars",
     "higher_is_stronger": True,
     "why": "Bars since the close moved to the trade side of the SAR (0 = on the signal bar): how long the SAR condition has held when the vortex cross comes."},
]


def _run_age(state: np.ndarray, valid_prev: np.ndarray) -> np.ndarray:
    """Bars since ``state`` last turned True (0 on that bar) while it stays True; NaN where it is False
    and during a run whose start is not observed (no False bar with a valid SAR before it)."""
    s = np.asarray(state, dtype=bool)
    n = len(s)
    idx = np.arange(n)
    prev = np.r_[False, s[:-1]] if n else s
    start = s & ~prev & np.asarray(valid_prev, dtype=bool)
    last = np.maximum.accumulate(np.where(start, idx, -1)) if n else np.zeros(0, dtype=np.int64)
    out = (idx - last).astype(float)
    # a run is attributed to its start only if no False bar lies between that start and i
    last_false = np.maximum.accumulate(np.where(~s, idx, -1)) if n else np.zeros(0, dtype=np.int64)
    out[(last < 0) | ~s | (last_false > last)] = np.nan
    return out


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    n = len(df)
    close = df["close"].to_numpy(dtype=float)
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    plus, minus = fg.vortex_indicator(df, 14)
    plus, minus = _f(plus), _f(minus)
    psar, _d = fg_fast.parabolic_sar(df, 0.02, 0.02, 0.20)
    ps = _f(psar)
    above, below = gt(close, ps), lt(close, ps)
    prev_ok = np.r_[False, np.isfinite(ps[:-1])] if n else np.zeros(0, dtype=bool)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        dist = (close - ps) / a
    spread = plus - minus
    return {
        "vi_spread": (spread, -spread),
        "psar_dist_atr": (dist, -dist),
        "psar_age_bars": (_run_age(above, prev_ok), _run_age(below, prev_ok)),
    }
