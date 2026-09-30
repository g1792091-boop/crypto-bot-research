"""Entry strength of DOGE (PREREG_ENTRY.md section 3, B).

Locked rule (third_party/sweep/harness/vendor/doge_strategy.py:compute_signals with the tf-scaled lengths of
third_party/sweep/harness/sweep_lib.py:doge_params), long side:
    EMA fast > EMA slow & spread = (EMA fast - EMA slow) / EMA slow * 100 > 0.15 & close > EMA trend
    & close > EMA short & CHOP < 61.8 & StochRSI K crosses above D with K < 45 & RSI > 52
short mirrors (spread < -0.15, K crosses below D with K > 55, RSI < 48, closes below the EMAs).
The features read the indicators of that exact rule (same code, same scaled lengths) on the signal bar:
  ema_spread_pct  spread - 0.15 long;  -spread - 0.15 short   (percent of the slow EMA past the 0.15 % minimum)
  k_depth         45 - K long;  K - 55 short                  (StochRSI K points past its level at the cross)
  rsi_margin      RSI - 52 long;  48 - RSI short              (RSI points past its level)
Sides: the account goes long on the long rule and short on the short rule (paperbot.sigservice.doge_join; the
old long-only join was a bug fixed on 2026-09-30, see param_defs/DOGE.py). Each signal's feature value is taken
from the side it trades, so "higher_is_stronger" always describes the setup of the rule that fired and traded.
Report DOGE with that caveat (or split the cell by rule_signals) rather than read a flat result as "no effect".
Every value at bar i uses bars <= i only (EMAs, Wilder RSI, rolling min/max and the forward fill of
doge_strategy.compute_indicators are all trailing; the rule flag of bar i uses the same indicators).
Defined without looking at any trading outcome.
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

_L = sweepsig.lib()  # hash-checked locked code; puts the vendored indicator modules on sys.path

import doge_strategy as ds  # noqa: E402

NAME = "DOGE"
SPREAD_MIN = float(ds.DEFAULT["spread_min"])   # 0.15
K_MAX = float(ds.DEFAULT["k_max"])             # 45
RSI_MIN = float(ds.DEFAULT["rsi_min"])         # 52

FEATURES = [
    {"name": "ema_spread_pct", "label_ko": "빠른·느린 EMA 간격", "unit": "% of slow EMA",
     "higher_is_stronger": True,
     "why": "EMA fast-slow spread past the 0.15 % minimum in the trade direction (long spread - 0.15, short -spread - 0.15): the trend-spread condition."},
    {"name": "k_depth", "label_ko": "K가 45/55를 넘은 깊이", "unit": "StochRSI K points",
     "higher_is_stronger": True,
     "why": "How far StochRSI K is past its level on the crossing bar (long 45 - K, short K - 55): the 'K crosses D with K < 45 / > 55' trigger."},
    {"name": "rsi_margin", "label_ko": "RSI가 52/48을 넘은 폭", "unit": "RSI points",
     "higher_is_stronger": True,
     "why": "RSI past its level in the trade direction (long RSI - 52, short 48 - RSI): the 'RSI > 52 / < 48' momentum condition."},
]


def _empty():
    z = np.zeros(0, dtype=float)
    return {f["name"]: (z.copy(), z.copy()) for f in FEATURES}


def strength(df, tf):
    """{feature: (value for long signals, value for short signals)}, float arrays of len(df)."""
    n = len(df)
    if n == 0:
        return _empty()
    p = _L.doge_params(tf)
    d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["ts"], utc=True)))[["open", "high", "low", "close", "volume"]]
    ind = ds.compute_indicators(d, p)
    sig = ds.compute_signals(d, ind, p)
    short_rule = np.asarray(sig["short_entry"].to_numpy(), bool) & ~np.asarray(sig["long_entry"].to_numpy(), bool)
    sp = ind["spread_pct"].to_numpy(dtype=float)
    k = ind["K"].to_numpy(dtype=float)
    r = ind["rsi26"].to_numpy(dtype=float)
    short_side = {
        "ema_spread_pct": -sp - SPREAD_MIN,
        "k_depth": k - (100.0 - K_MAX),
        "rsi_margin": (100.0 - RSI_MIN) - r,
    }
    long_side = {
        "ema_spread_pct": sp - SPREAD_MIN,
        "k_depth": K_MAX - k,
        "rsi_margin": r - RSI_MIN,
    }
    return {f: (np.where(short_rule, short_side[f], long_side[f]).astype(float), short_side[f].astype(float))
            for f in long_side}
