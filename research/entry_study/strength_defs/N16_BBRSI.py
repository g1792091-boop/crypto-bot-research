"""Entry strength of N16_BBRSI (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/ports12.py:n16, variant 0; no timeframe scaling):
    up, mid, lo, rsi, mp, sg = fg.mapped_rsi_bollinger(df, 20, 2.0, 14, 5, 2.0)
        mp = mid + (RSI14 - 50) / 50 * |up - mid| * 2.0  (RSI drawn on the Bollinger price scale), sg = EMA5(mp)
    reL  = (mp[-1] < lo[-1]) & (mp >= lo) & cross_above(mp, sg)      re-entry from below the lower band
    divL = on a confirmed price pivot low (3 left / 3 right, known 3 bars later, pivot p = i - 3) whose previous
           pivot prev is 5..60 bars earlier: low[p] < low[prev] and mp[p] > mp[prev]   (bullish divergence)
    long = (reL | divL) & (close > open);  short mirrored (upper band, pivot highs, close < open), & ~long.
Because mp - mid and lo - mid both scale with the band width, 'mp below the lower band' is 'RSI14 below
50 - 50 / 2.0 = 25' (above 75 for the upper band) whenever the band has width.

Features (long / short mirrored):
  reentry_rsi_depth  on bars where the re-entry path fires: how far RSI14 of the previous bar was beyond its
                     band level (25 - RSI[i-1], short RSI[i-1] - 75), in RSI points; NaN when that path is not
                     true on the bar (a divergence-only signal)
  div_gap_atr        on bars where the divergence path fires: mapped-RSI difference between the two pivots
                     (mp[p] - mp[prev], short mp[prev] - mp[p]) in ATR14 of the signal bar, i.e. how far past 0
                     the 'RSI line makes a higher low while price makes a lower low' condition is; NaN otherwise
  body_atr           candle body (close - open, short open - close) in ATR14: the candle-colour condition
Every value at bar i uses bars <= i only (pivots are read only once confirmed). Defined without looking at
any trading outcome.
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
from strategies import _f, cross_above, cross_below  # noqa: E402

NAME = "N16_BBRSI"
BB_LEN, BB_STD, RSI_LEN, SIG_LEN, MAP_SCALE = 20, 2.0, 14, 5, 2.0   # locked
PIVOT = 3                     # confirmed pivots, 3 bars left / 3 bars right
SPACING = (5, 60)             # bars between the two pivots of a divergence
RSI_LOW = 50.0 - 50.0 / MAP_SCALE    # 25: mapped RSI below the lower band <=> RSI14 below this
RSI_HIGH = 50.0 + 50.0 / MAP_SCALE   # 75

FEATURES = [
    {"name": "reentry_rsi_depth", "label_ko": "RSI가 25/75 밖으로 나간 깊이", "unit": "RSI points",
     "higher_is_stronger": True,
     "why": "Re-entry path only: previous-bar RSI14 beyond the level where the mapped RSI leaves the Bollinger band (long 25 - RSI, short RSI - 75): the 'RSI line was outside the band' condition."},
    {"name": "div_gap_atr", "label_ko": "다이버전스 RSI선 차이", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Divergence path only: mapped RSI at the new pivot minus at the previous pivot (short mirrored), in ATR14: how far past zero the 'RSI line higher low / lower high' condition is."},
    {"name": "body_atr", "label_ko": "신호 봉 몸통 크기", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Signal-bar body close - open (short open - close) in ATR14: the 'bullish / bearish candle' condition."},
]


def _sh(x: np.ndarray, k: int = 1) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def _pivot_events(x: np.ndarray, k: int, low: bool) -> np.ndarray:
    """fg.confirmed_pivot_low / _high(x, k, k) event (bar i confirms the pivot at i - k), vectorised."""
    n = len(x)
    ev = np.zeros(n, bool)
    if n > 2 * k:
        r = pd.Series(x).rolling(2 * k + 1, min_periods=1)
        ext = (r.min() if low else r.max()).to_numpy()
        piv = _sh(x, k)
        with np.errstate(invalid="ignore"):
            ok = (piv <= ext) if low else (piv >= ext)
        ev[2 * k:] = (~np.isnan(piv[2 * k:])) & ok[2 * k:]
    return ev


def _div_gap(price: np.ndarray, mp: np.ndarray, ev: np.ndarray, low: bool) -> np.ndarray:
    """mp[p] - mp[prev] on bars where the locked divergence fires (price lower low & mp higher low; for
    highs: price higher high & mp lower high, returned as mp[prev] - mp[p]); NaN elsewhere."""
    out = np.full(len(price), np.nan)
    prev = None
    for i in np.flatnonzero(ev):
        p = i - PIVOT
        if prev is not None and SPACING[0] <= p - prev <= SPACING[1]:
            if low and price[p] < price[prev] and mp[p] > mp[prev]:
                out[i] = mp[p] - mp[prev]
            elif not low and price[p] > price[prev] and mp[p] < mp[prev]:
                out[i] = mp[prev] - mp[p]
        prev = p
    return out


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    up, _mid, lo, rsi, mp, sg = fg.mapped_rsi_bollinger(df, BB_LEN, BB_STD, RSI_LEN, SIG_LEN, MAP_SCALE)
    upf, lof, mpf, r = _f(up), _f(lo), _f(mp), _f(rsi)
    mp1, lo1, up1, r1 = _sh(mpf), _sh(lof), _sh(upf), _sh(r)
    xu, xd = cross_above(mp, sg), cross_below(mp, sg)
    with np.errstate(invalid="ignore"):
        reL = (mp1 < lo1) & (mpf >= lof) & xu
        reS = (mp1 > up1) & (mpf <= upf) & xd
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        gap_l = _div_gap(l, mpf, _pivot_events(l, PIVOT, True), True) / a
        gap_s = _div_gap(h, mpf, _pivot_events(h, PIVOT, False), False) / a
        return {
            "reentry_rsi_depth": (np.where(reL, RSI_LOW - r1, np.nan), np.where(reS, r1 - RSI_HIGH, np.nan)),
            "div_gap_atr": (gap_l, gap_s),
            "body_atr": ((c - o) / a, (o - c) / a),
        }
