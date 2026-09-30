"""Entry strength of S6_EMA_DMI_ADX (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:s6_ema_dmi_adx), EMA 20, DMI(14, 14), sync 2:
  long  = ADX >= 25 & close > EMA & +DI > -DI & +DI crossed above -DI within 2 bars & close crossed above EMA
          within 2 bars & (one of the two crosses on this bar)
  short = mirrored (-DI over +DI, close under EMA).

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
from strategies import _f, cross_above, cross_below  # noqa: E402

NAME = "S6_EMA_DMI_ADX"

FEATURES = [
    {"name": "adx_over_25", "label_ko": "ADX가 25를 넘은 폭", "unit": "ADX points",
     "higher_is_stronger": True,
     "why": "ADX(14) minus the strategy's 25 threshold (same for both sides): how strongly the 'ADX >= 25' trend-strength condition is met."},
    {"name": "di_spread", "label_ko": "+DI와 -DI의 차이", "unit": "DI points",
     "higher_is_stronger": True,
     "why": "+DI - -DI for long, -DI - +DI for short: how far the '+DI > -DI' (mirrored) condition is past the crossing."},
    {"name": "cross_gap_bars", "label_ko": "두 교차 사이 봉 수", "unit": "bars (0-1)",
     "higher_is_stronger": False,
     "why": "Bars between the close/EMA20 cross and the DI cross (the older of the two; 0 = same bar): tightness of the sync-2 rule."},
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
    close = df["close"]
    e = fg.ema(close, 20)
    plus, minus, adx = fg.dmi_adx(df, 14, 14)
    p, mi, ax = _f(plus), _f(minus), _f(adx)
    price_up = cross_above(close, e)
    price_down = cross_below(close, e)
    di_up = cross_above(plus, minus)
    di_down = cross_above(minus, plus)
    adx_over = ax - 25.0
    return {
        "adx_over_25": (adx_over, adx_over.copy()),
        "di_spread": (p - mi, mi - p),
        "cross_gap_bars": (np.maximum(_bars_since(price_up), _bars_since(di_up)),
                           np.maximum(_bars_since(price_down), _bars_since(di_down))),
    }
