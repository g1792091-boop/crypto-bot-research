"""Entry strength of N21_ST_RSI_ADX (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n21_supertrend_rsi_adx), supertrend(10, 6),
RSI 14, ADX 14 (fg.adx_dmi), all conditions on the same bar:
  long  = supertrend up   & ADX crosses below 25 & RSI < 30 & RSI > previous RSI
  short = supertrend down & ADX crosses below 25 & RSI > 70 & RSI < previous RSI

adx_cross_size is the same number for both sides (the ADX rule is not directional). st_line_dist_atr is
NaN where the supertrend is not on the trade side (and during its warm-up). RSI values from before fg.rsi
has its Wilder averages (the locked RSI reads 0 there) are treated as missing.
The locked rule is very rare (one signal in all period-1/2 files of 6 coins x {15m, 1h, 4h}, none in period
3), so no cell is expected to reach the PREREG minimum sample; the features are defined all the same.
Every value at bar i uses bars <= i only. Defined without looking at any trading outcome.
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
from strategies import _f, gt, lt  # noqa: E402

NAME = "N21_ST_RSI_ADX"

FEATURES = [
    {"name": "rsi_extreme", "label_ko": "RSI가 30/70을 넘은 폭", "unit": "RSI points",
     "higher_is_stronger": True,
     "why": "How far RSI(14) is past its level on the signal bar (long 30 - RSI, short RSI - 70): the 'RSI < 30 / > 70' condition."},
    {"name": "adx_cross_size", "label_ko": "ADX가 한 봉에 떨어진 폭", "unit": "ADX points",
     "higher_is_stronger": True,
     "why": "Previous ADX(14) - current ADX(14): size of the 'ADX crosses below 25' trigger on the signal bar."},
    {"name": "st_line_dist_atr", "label_ko": "슈퍼트렌드선과의 거리", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the close is beyond the supertrend(10, 6) line on the trade side, in ATR14: the 'supertrend up / down' condition."},
]


def _rsi_ready(close: pd.Series, length: int = 14) -> np.ndarray:
    """True once fg.rsi has its Wilder averages (before that the locked RSI reads 0)."""
    return (close.diff().notna().cumsum() >= length).to_numpy()


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    n = len(df)
    close_s = df["close"]
    close = close_s.to_numpy(dtype=float)
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    r = _f(fg.rsi(close_s, 14))
    r = np.where(_rsi_ready(close_s, 14), r, np.nan)
    adx_line, _p, _m = fg.adx_dmi(df, 14)
    adx = _f(adx_line)
    adx_prev = np.r_[np.nan, adx[:-1]] if n else adx
    line, direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    d, ln = _f(direction), _f(line)
    up, down = gt(d, 0), lt(d, 0)
    nan = np.full(n, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        dist = (close - ln) / a
    drop = adx_prev - adx
    return {
        "rsi_extreme": (30.0 - r, r - 70.0),
        "adx_cross_size": (drop, drop.copy()),
        "st_line_dist_atr": (np.where(up, dist, nan), np.where(down, -dist, nan)),
    }
