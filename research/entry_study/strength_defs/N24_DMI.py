"""Entry-strength numbers for N24_DMI (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/strategies.py:n24_dmi, no timeframe scaling;
checked chart view paperbot/strategy_view_defs/N24_DMI.py):
  adx, +DI, -DI = fg.adx_dmi(df, 14)          (= fg.dmi_adx(df, 14, 14))
  long  = ADX >= 25 & +DI crosses above -DI on this bar
  short = ADX <= 25 & -DI crosses above +DI on this bar
The two sides use the 25 level in opposite directions: longs need a trending market, shorts a
non-trending one.

The numbers below measure how strongly those conditions hold on the signal bar. They are defined
from the strategy code only; no trading outcome was computed or looked at when writing them.
Every value at bar i uses bars <= i only (Wilder averages are forward recursions).
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

NAME = "N24_DMI"
ADX_LEVEL = 25.0

FEATURES = [
    {"name": "adx_margin", "label_ko": "ADX가 25에서 떨어진 폭", "unit": "ADX 포인트",
     "higher_is_stronger": True,
     "why": "How far ADX(14) is past the rule's 25 level on the side each trade needs: ADX - 25 for "
            "longs (ADX >= 25), 25 - ADX for shorts (ADX <= 25)."},
    {"name": "di_spread", "label_ko": "+DI와 -DI 벌어진 폭", "unit": "DI 포인트",
     "higher_is_stronger": True,
     "why": "Size of the DI cross on the signal bar: (+DI) - (-DI) for longs, (-DI) - (+DI) for "
            "shorts, DMI(14)."},
]


def _arr(x) -> np.ndarray:
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def _finite(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float).copy()
    x[~np.isfinite(x)] = np.nan
    return x


def strength(df: pd.DataFrame, tf: str) -> dict:
    """{feature name: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    adx_line, plus, minus = fg.adx_dmi(df, 14)
    adx, p, m = _arr(adx_line), _arr(plus), _arr(minus)
    margin = adx - ADX_LEVEL
    spread = p - m
    return {
        "adx_margin": (_finite(margin), _finite(-margin)),
        "di_spread": (_finite(spread), _finite(-spread)),
    }
