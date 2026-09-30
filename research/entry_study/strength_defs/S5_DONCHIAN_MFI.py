"""Entry strength of S5_DONCHIAN_MFI (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:s5_donchian_mfi), upper / lower = highest high /
lowest low of the PREVIOUS 20 bars, MFI 14, sync 3:
  long  = close > upper & MFI > 30 & close broke above upper within 3 bars & MFI crossed above 30 within 3 bars
          & (breakout or MFI cross on this bar)
  short = close < lower & MFI < 70 & close broke below lower within 3 bars & MFI crossed below 70 within 3 bars
          & (breakdown or MFI cross on this bar)

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

import fg_indicators as fg  # noqa: E402
from strategies import _f, cross_above, cross_below, ge, gt, le, lt  # noqa: E402

NAME = "S5_DONCHIAN_MFI"

FEATURES = [
    {"name": "breakout_atr", "label_ko": "돈치안 돌파 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "How far the close is beyond the previous-20-bar high (long) / low (short), in ATR14: the 'close > upper / < lower' condition."},
    {"name": "mfi_past_level", "label_ko": "MFI가 30/70을 넘은 폭", "unit": "MFI points",
     "higher_is_stronger": True,
     "why": "How far MFI(14) is past its trigger level in the trade direction (long MFI - 30, short 70 - MFI): the 'MFI > 30 / < 70' condition."},
    {"name": "sync_gap_bars", "label_ko": "돌파·MFI 신호 간격", "unit": "bars (0-2)",
     "higher_is_stronger": False,
     "why": "Bars between the channel breakout and the MFI level cross (the older of the two events; 0 = same bar): tightness of the sync-3 rule."},
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
    close_s = df["close"]
    close = close_s.to_numpy(dtype=float)
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    upper, _middle, lower = fg.donchian_channel(df, 20, shift_previous=True)
    m = _f(fg.mfi(df, 14))
    breakout_up = gt(close_s, upper) & le(close_s.shift(1), upper.shift(1))
    breakout_down = lt(close_s, lower) & ge(close_s.shift(1), lower.shift(1))
    mfi_up = cross_above(m, 30.0)
    mfi_down = cross_below(m, 70.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        br_long = (close - _f(upper)) / a
        br_short = (_f(lower) - close) / a
    gap_long = np.maximum(_bars_since(breakout_up), _bars_since(mfi_up))       # NaN if either never happened
    gap_short = np.maximum(_bars_since(breakout_down), _bars_since(mfi_down))
    return {
        "breakout_atr": (br_long, br_short),
        "mfi_past_level": (m - 30.0, 70.0 - m),
        "sync_gap_bars": (gap_long, gap_short),
    }
