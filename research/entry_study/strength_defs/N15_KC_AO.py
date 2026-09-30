"""Entry strength of N15_KC_AO (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/ports12.py:n15, variant 0; no timeframe scaling):
    up, mid, lo = fg.keltner_channel(df, 20, 10, 2.0)       # EMA20 +/- 2 x ATR10
    ao = fg.awesome_oscillator(df, 5, 34);  ao1 = ao[-1]
    long  = (low[-1]  < lo[-1]) & (close > lo) & (ao > ao1) & (ao > 0)
    short = (high[-1] > up[-1]) & (close < up) & (ao < ao1) & (ao < 0)   (& ~long)
i.e. the previous bar poked outside the Keltner band, the signal bar closes back inside, and the
Awesome Oscillator is on the trade's side of zero and moving that way.

Features (all in ATR14 of the bar they are read on, long / short mirrored):
  prev_pierce_atr  how far the previous bar's low was below the previous lower band (short: high above
                   the upper band): the 'previous bar outside the band' condition (> 0 on every signal)
  reentry_atr      how far the signal bar's close is back inside the band (long close - lower band,
                   short upper band - close): the 'close back inside' condition (> 0 on every signal)
  ao_atr           AO / ATR14 (short: -AO / ATR14): the 'AO above / below zero' condition (> 0)
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
from strategies import _f  # noqa: E402

NAME = "N15_KC_AO"
KC_LEN, KC_ATR_LEN, KC_MULT = 20, 10, 2.0   # locked Keltner channel
AO_FAST, AO_SLOW = 5, 34                    # locked Awesome Oscillator

FEATURES = [
    {"name": "prev_pierce_atr", "label_ko": "직전 봉이 밴드 밖으로 나간 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Previous bar's low below the previous lower Keltner band EMA20 - 2 ATR10 (short: high above the upper band), in ATR14 of that bar: the 'previous bar outside the band' condition."},
    {"name": "reentry_atr", "label_ko": "종가가 밴드 안으로 돌아온 폭", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Signal-bar close minus the lower Keltner band (short: upper band minus close), in ATR14: the 'close back inside the band' condition."},
    {"name": "ao_atr", "label_ko": "AO가 0에서 떨어진 크기", "unit": "ATR14",
     "higher_is_stronger": True,
     "why": "Awesome Oscillator(5, 34) / ATR14 (short: -AO / ATR14): the 'AO above zero / below zero' condition."},
]


def _sh(x: np.ndarray, k: int = 1) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    df = df.reset_index(drop=True)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    up, _mid, lo = fg.keltner_channel(df, KC_LEN, KC_ATR_LEN, KC_MULT)
    up, lo = _f(up), _f(lo)
    ao = _f(fg.awesome_oscillator(df, AO_FAST, AO_SLOW))
    atr = fg.atr(df, 14).to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        a = np.where(atr > 0, atr, np.nan)
        pierce_long = (lo - low) / a          # on bar j; read at i from j = i - 1
        pierce_short = (high - up) / a
        return {
            "prev_pierce_atr": (_sh(pierce_long), _sh(pierce_short)),
            "reentry_atr": ((close - lo) / a, (up - close) / a),
            "ao_atr": (ao / a, -ao / a),
        }
