"""Parameter re-implementation of N21_ST_RSI_ADX for the sensitivity study (PREREG_ENTRY.md section 4, C).

``signals(df, tf)`` with no overrides reproduces ``strategies.n21_supertrend_rsi_adx`` bar for bar (plus
the ``short & ~long`` step of sweep_lib._clean). Locked code:

    _st, up = fg_fast.supertrend_v2(df, 10, 6.0)          # up = direction.fillna(0) > 0
    r = fg.rsi(close, 14);  adx_line, _p, _m = fg.adx_dmi(df, 14)
    adx_cross_down = cross_below(adx_line, 25.0)
    short = ~up & adx_cross_down & r > 70 & r < r[-1]
    long  = up  & adx_cross_down & r < 30 & r > r[-1]  & ~short

``rsi_level`` is the long level (30); the short level is its mirror 100 - rsi_level (70), so the variant
50 + m * (30 - 50) moves both levels the same distance from the neutral 50. ``adx_level`` has no neutral
point (ADX is 0..100, trend strength only), so its variants are m * 25 (threshold_abs). ``adx_len`` is the
fg.adx_dmi length, used there for both the DI and the ADX smoothing, as in the locked call.
Not parameters here: supertrend ATR length 10, RSI length 14. The rule does not depend on the timeframe.

Signal counts (no outcomes; checked 2026-09-30 when these files were written): the locked rule fires once
in all 6 coins x {15m, 1h, 4h} of the period-1/2 series (BTC 1h, one long) and never in the period-3
series; the widest variant (rsi_level 40 / 60) gives at most 85 signals per timeframe over all six coins.
So no N21 cell reaches the PREREG minimum of 300 signals; the minimum-sample rule of the runner, not this
file, keeps it out of the tests. The re-implementation is exact, so it is not excluded here.
Because the rule fires once, three variants change no signal bar anywhere in those 18 files: st_mult 7.5
and 9.0, and rsi_level 25 (each only keeps the single signal). The other 13 variants change 1 to 86 bars
(summed over coins, per timeframe). The parameter threading is also checked on synthetic bars with
widened levels (tests/test_entry_defs_N17_KC_RSI.py).
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from paperbot import sweepsig  # noqa: E402

sweepsig.lib()  # hash-checked locked code; puts the vendored indicator modules on sys.path

import fg_fast  # noqa: E402
import fg_indicators as fg  # noqa: E402
from strategies import _b, cross_below, gt, lt  # noqa: E402

NAME = "N21_ST_RSI_ADX"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/strategies.py:n21_supertrend_rsi_adx"
ST_ATR_LEN = 10  # locked, not varied
RSI_LEN = 14     # locked, not varied

PARAMS = [
    {"name": "st_mult", "default": 6.0, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (fg_fast.supertrend_v2(df, 10, 6.0): band multiplier)"},
    {"name": "adx_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.adx_dmi(df, 14): DI length and ADX smoothing)"},
    {"name": "adx_level", "default": 25.0, "kind": "threshold_abs", "neutral": None,
     "where": f"{_WHERE} (cross_below(adx_line, 25.0))"},
    {"name": "rsi_level", "default": 30.0, "kind": "threshold_neutral", "neutral": 50.0,
     "where": f"{_WHERE} (lt(r, 30.0) for long; short uses the mirror 100 - level: gt(r, 70.0))"},
]
_SPEC = {p["name"]: p for p in PARAMS}
MULTIPLIERS = (0.5, 0.75, 1.25, 1.5)


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def variant_value(spec: dict, m: float):
    """PREREG 4: length -> round half up, min 2; mult / threshold_abs -> m * default;
    threshold_neutral -> neutral + m * (default - neutral)."""
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


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    _st, up = fg_fast.supertrend_v2(df, ST_ATR_LEN, p["st_mult"])
    up = _b(up)
    r = fg.rsi(df["close"], RSI_LEN)
    adx_line, _p, _m = fg.adx_dmi(df, p["adx_len"])
    adx_cross_down = cross_below(adx_line, p["adx_level"])
    rsi_down = gt(r, 100.0 - p["rsi_level"]) & lt(r, r.shift(1))
    rsi_up = lt(r, p["rsi_level"]) & gt(r, r.shift(1))
    short = np.asarray((~up) & adx_cross_down & rsi_down, dtype=bool)
    long = np.asarray(up & adx_cross_down & rsi_up, dtype=bool) & ~short
    short = short & ~long
    return long, short
