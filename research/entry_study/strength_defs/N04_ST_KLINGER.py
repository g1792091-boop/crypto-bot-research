"""Entry strength of N04_ST_KLINGER (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/ports12.py:n04, variant 0, no timeframe scaling):
  direction = fg_fast.supertrend(df, 10, 6.0);  kl, ks = fg.klinger_oscillator(df, 34, 55, 13)
  long  = direction > 0 & recent(kl crosses above ks, 2) & (that cross | SuperTrend up-flip on this bar)
  short = direction < 0 & recent(kl crosses below ks, 2) & (that cross | SuperTrend down-flip on this bar)
  short &= ~long (sweep_lib._clean)

Klinger (kl, ks) is in units of 100 x volume (force = +-volume x (2 close - high - low) / (high - low) x 100),
so the Klinger gap is divided by 100 x SMA(volume, 55) (55 = the Klinger slow length) to compare bars and
coins. Every value at bar i uses bars <= i only (EWM / rolling / the SuperTrend loop are causal). Defined
from the strategy code only, without computing or looking at any trading outcome.
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

NAME = "N04_ST_KLINGER"
VOL_LEN = 55  # Klinger slow length, used for the volume scale

FEATURES = [
    {"name": "kvo_gap_vol", "label_ko": "클링어 교차 폭(거래량 대비)", "unit": "Klinger / (100 x SMA55 volume)",
     "higher_is_stronger": True,
     "why": "(Klinger - its signal line) / (100 x SMA(volume, 55)) on the signal bar (negated for shorts): size "
            "of the required Klinger(34, 55, 13) signal-line cross."},
    {"name": "st_dist_atr", "label_ko": "슈퍼트렌드선에서 거리(ATR)", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "(close - SuperTrend(10, 6) line) / ATR14 for longs, (line - close) / ATR14 for shorts: how far the "
            "close sits on the side of the SuperTrend line that sets the trade direction."},
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
    close = _arr(df["close"])
    atr = _arr(fg.atr(df, 14))
    line, _direction, _u, _l = fg_fast.supertrend(df, 10, 6.0)
    kl, ks = fg.klinger_oscillator(df, 34, 55, 13)
    vol = _arr(fg.sma(df["volume"].astype(float), VOL_LEN))
    with np.errstate(invalid="ignore", divide="ignore"):
        scale = np.where(vol > 0, 100.0 * vol, np.nan)
        gap = (_arr(kl) - _arr(ks)) / scale
        st = (close - _arr(line)) / np.where(atr > 0, atr, np.nan)
    return {
        "kvo_gap_vol": (_finite(gap), _finite(-gap)),
        "st_dist_atr": (_finite(st), _finite(-st)),
    }
