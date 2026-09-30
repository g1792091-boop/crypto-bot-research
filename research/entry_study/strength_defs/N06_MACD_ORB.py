"""Entry-strength numbers for N06_MACD_ORB (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/ports12.py:n06, no timeframe scaling; checked chart view
paperbot/strategy_view_defs/N06_MACD_ORB.py), a = ATR14:
  opening range = high / low of the first bar of each UTC date (not usable on that bar itself)
  bu = close > orb_high & previous close <= orb_high        (bd mirror on orb_low)
  mu / md = MACD(12, 26, 9) line crosses above / below its signal line
  long  = recent(bu, 2) & recent(mu, 2) & MACD line > 0 & hist > 0 & hist >= hist[-1]
          & close - orb_high <= 1.5 a & (bu | mu)
  short = recent(bd, 2) & recent(md, 2) & MACD line < 0 & hist < 0 & hist <= hist[-1]
          & orb_low - close <= 1.5 a & (bd | md)
  short &= ~long (ports12._pack / sweep_lib._clean)

The numbers below measure how strongly those conditions hold on the signal bar. They are defined from
the strategy code only; no trading outcome was computed or looked at when writing them. Every value at
bar i uses bars <= i only (the opening range comes from the first bar of the bar's own UTC date, which
is at or before i; EMAs and ATR are forward recursions).
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

NAME = "N06_MACD_ORB"

FEATURES = [
    {"name": "orb_break_atr", "label_ko": "첫 봉 고저 돌파 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the close is past the opening-range level it broke: (close - first-bar high) / ATR14 "
            "for longs, (first-bar low - close) / ATR14 for shorts (the rule also caps it at 1.5)."},
    {"name": "macd_line_atr", "label_ko": "MACD선이 0에서 먼 정도", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "MACD(12, 26, 9) line / ATR14 (negated for shorts): how far past zero the 'MACD line > 0' "
            "('< 0') condition is."},
    {"name": "macd_hist_atr", "label_ko": "MACD 교차 크기", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "MACD histogram (line - signal) / ATR14 (negated for shorts): size of the MACD signal-line "
            "cross and of the 'histogram > 0 and growing' condition."},
]


def _arr(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _finite(x) -> np.ndarray:
    x = np.array(x, dtype=float)
    x[~np.isfinite(x)] = np.nan
    return x


def opening_range(df: pd.DataFrame):
    """(orb_high, orb_low) as ports12.n06: high / low of the first bar of each UTC date, NaN on that bar."""
    h, l = _arr(df["high"]), _arr(df["low"])
    ts = pd.to_datetime(df["ts"], utc=True)
    first = (~ts.dt.floor("D").duplicated()).to_numpy(dtype=bool)
    orb_h = pd.Series(np.where(first, h, np.nan)).ffill().to_numpy()
    orb_l = pd.Series(np.where(first, l, np.nan)).ffill().to_numpy()
    orb_h[first] = np.nan
    orb_l[first] = np.nan
    return orb_h, orb_l


def strength(df: pd.DataFrame, tf: str) -> dict:
    """{feature name: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    c = _arr(df["close"])
    a = _arr(fg.atr(df, 14))
    orb_h, orb_l = opening_range(df)
    ml, _sl, hist = fg.macd(df["close"], 12, 26, 9)
    ml, hist = _arr(ml), _arr(hist)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(a > 0, a, np.nan)
        brk_l = (c - orb_h) / a
        brk_s = (orb_l - c) / a
        line = ml / a
        hs = hist / a
    return {
        "orb_break_atr": (_finite(brk_l), _finite(brk_s)),
        "macd_line_atr": (_finite(line), _finite(-line)),
        "macd_hist_atr": (_finite(hs), _finite(-hs)),
    }
