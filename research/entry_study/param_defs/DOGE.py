"""Parameter re-implementation of DOGE for the sensitivity study (PREREG_ENTRY.md section 4, C).

DOGE in the signal caches is DOGE_L - DOGE_S (research/paper_rules/rules_bt.py:_signals_job,
research/entry_study/final_signals.py:signal_arrays), both from ``sweep_lib.doge_entries``:
``doge_strategy.compute_indicators`` / ``compute_signals`` with the lengths of ``sweep_lib.doge_params(tf)``.
``rule_signals(df, tf)`` gives the strategy's own two sides (long_entry, short_entry; they can never fire
together because long needs EMA fast > EMA slow and short needs EMA fast < EMA slow).

SIGN OF THE DOGE SIGNAL: the account goes long on the long rule and SHORT on the short rule
(paperbot.sigservice.doge_join). When these definitions were first written, the caches and the live bot used the
old join DOGE_L - DOGE_S, which turned every short-rule bar into a long (compute_signals already stores DOGE_S as
-1); this definition then reproduced that join. The bug was fixed everywhere on 2026-09-30 and the caches'
s__DOGE rebuilt, so ``signals(df, tf)`` now returns the strategy's own sides (long = long_entry, short =
short_entry) and must equal the rebuilt caches exactly. JOIN_AS_CACHED is kept only as False for the record.

Locked rule (third_party/sweep/harness/vendor/doge_strategy.py:compute_signals), long side:
    EMA fast > EMA slow & close > EMA trend & (EMA fast - EMA slow) / EMA slow * 100 > 0.15
    & CHOP(14) < 61.8 & StochRSI K crosses above D & K < 45 & RSI(26) > 52 & close > EMA short
short mirrors: fast < slow, close < trend, spread < -0.15, CHOP < 61.8, K crosses below D, K > 55 (= 100 - 45),
RSI < 48 (= 100 - 52), close < EMA short.

Timeframe scaling (reproduced): every length is the 5-minute length of doge_strategy.DEFAULT divided by
tf minutes / 5, rounded half up, min 2 (sweep_lib.doge_params). A length parameter here is the 5-minute BASE
length (the number in DEFAULT): its variant (PREREG 4 rule on the base: m * base, round half up, min 2) is
scaled to the chart timeframe with that same locked rule. Example ema_slow 156: 15m -> 52, 1h -> 13, 4h -> 3;
variant x0.5 = 78 -> 15m 26, 1h 7 (6.5 rounds up), 4h 2.

Parameters:
  ema_slow    156    slow EMA (5m base; "EMA_15M_52"): EMA fast > EMA slow and the spread denominator
  stoch_len   70     MIN/MAX window of the RSI inside StochRSI (5m base): shapes the K/D cross trigger
  spread_min  0.15   minimum EMA fast-slow spread in % of the slow EMA (threshold_abs: variants m * 0.15)
  chop_max    61.8   CHOP(14) ceiling, the same for both sides (a non-directional regime filter with no neutral
                     point in PREREG 4, so threshold_abs: variants m * 61.8 = 30.9, 46.35, 77.25, 92.7)
Chosen by how much a number moves the entries (signal flags only, no outcome; BTC 1h, last 5000 bars, 90 cached
signals, changed signal bars over x0.5..x1.5): ema_slow 13-68, stoch_len 27-90, spread_min 6-16, chop_max 48-79;
not varied: ema_fast 4-13, stoch_rsi_len 5-36 (the same kind of window as stoch_len), ema_trend 2-5, k_max 2-6,
rsi_len 0-4, ema_short 0-1, rsi_min 0-1, k_smooth / d_smooth (at the minimum 2 on 15m, 1h and 4h).
On 4h every StochRSI length is at the minimum 2 (stoch_len variants included) and the locked DOGE rule fires on
no 4h bar of the 6 coins in periods 1-3.
"""

from __future__ import annotations

import math
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
EXCLUDED_REASON = None
JOIN_AS_CACHED = False  # the old long-only join (module docstring); the caches now hold the corrected sides
_WHERE = "third_party/sweep/harness/vendor/doge_strategy.py"

PARAMS = [
    {"name": "ema_slow", "default": 156, "kind": "length", "neutral": None,
     "where": f"{_WHERE}:compute_indicators (ema(c, p['ema_slow']); DEFAULT ema_slow=156 at 5m, scaled by "
              "third_party/sweep/harness/sweep_lib.py:doge_params)"},
    {"name": "stoch_len", "default": 70, "kind": "length", "neutral": None,
     "where": f"{_WHERE}:compute_indicators (rmin / rmax(r70, p['stoch_len']); DEFAULT stoch_len=70 at 5m, scaled "
              "by third_party/sweep/harness/sweep_lib.py:doge_params)"},
    {"name": "spread_min", "default": 0.15, "kind": "threshold_abs", "neutral": None,
     "where": f"{_WHERE}:compute_signals (sp > p['spread_min'] / sp < -p['spread_min'], DEFAULT 0.15)"},
    {"name": "chop_max", "default": 61.8, "kind": "threshold_abs", "neutral": None,
     "where": f"{_WHERE}:compute_signals (ch < p['chop_max'] on both sides, DEFAULT 61.8)"},
]
_SPEC = {p["name"]: p for p in PARAMS}
MULTIPLIERS = (0.5, 0.75, 1.25, 1.5)
LEN_KEYS = list(_L.DOGE_LEN_KEYS)


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def variant_value(spec: dict, m: float):
    """PREREG 4: length -> round half up, min 2; mult / threshold_abs -> m * default;
    threshold_neutral -> neutral + m * (default - neutral). Lengths are 5-minute base lengths."""
    d, kind = spec["default"], spec["kind"]
    if kind == "length":
        return max(2, _round_half_up(d * m))
    if kind in ("mult", "threshold_abs"):
        return float(d) * m
    if kind == "threshold_neutral":
        return float(spec["neutral"]) + m * (float(d) - float(spec["neutral"]))
    raise ValueError(f"unknown kind {kind!r}")


def variants(p) -> list[dict]:
    """The four override dicts (x0.5, x0.75, x1.25, x1.5) of parameter ``p`` (name or PARAMS entry)."""
    spec = _SPEC[p["name"] if isinstance(p, dict) else p]
    return [{spec["name"]: variant_value(spec, m)} for m in MULTIPLIERS]


def _resolve(overrides: dict) -> dict:
    bad = set(overrides) - set(_SPEC)
    if bad:
        raise ValueError(f"{NAME}: unknown parameter(s) {sorted(bad)}")
    p = {k: s["default"] for k, s in _SPEC.items()}
    p.update(overrides)
    for k, s in _SPEC.items():
        p[k] = int(p[k]) if s["kind"] == "length" else float(p[k])
    return p


def scale_len(base: int, tf: str) -> int:
    """sweep_lib.doge_params rule for one 5-minute base length."""
    ratio = _L.tf_minutes(tf) / 5.0
    return max(2, int(math.floor(base / ratio + 0.5))) if ratio > 1 else int(base)


def doge_params(tf: str, **overrides) -> dict:
    """Full doge_strategy parameter dict for the chart timeframe: tf-scaled lengths (== sweep_lib.doge_params
    with no override) plus the thresholds."""
    p = _resolve(overrides)
    base = {k: ds.DEFAULT[k] for k in LEN_KEYS}
    base["ema_slow"], base["stoch_len"] = p["ema_slow"], p["stoch_len"]
    out = {k: scale_len(v, tf) for k, v in base.items()}
    out["spread_min"] = p["spread_min"]
    out["chop_max"] = p["chop_max"]
    return out


def _frame(df) -> pd.DataFrame:
    return df.set_index(pd.DatetimeIndex(pd.to_datetime(df["ts"], utc=True)))[["open", "high", "low", "close", "volume"]]


def rule_signals(df, tf, **overrides):
    """The strategy's own sides (long_entry, short_entry & ~long_entry) of len(df) (== sweep_lib.doge_long /
    doge_short with no override)."""
    p = doge_params(tf, **overrides)
    n = len(df)
    if n == 0:
        return np.zeros(0, bool), np.zeros(0, bool)
    d = _frame(df)
    ind = ds.compute_indicators(d, p)
    sig = ds.compute_signals(d, ind, p)
    long = np.asarray(sig["long_entry"].to_numpy(), bool)
    short = np.asarray(sig["short_entry"].to_numpy(), bool) & ~long
    return long, short


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked (cached) DOGE signal when no override is given.
    Long on the long rule, short on the short rule (the corrected join; see the module docstring)."""
    long, short = rule_signals(df, tf, **overrides)
    if JOIN_AS_CACHED:
        return long | short, np.zeros(len(long), bool)
    return long, short
