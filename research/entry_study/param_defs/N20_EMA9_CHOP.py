"""Parameter re-implementation of N20_EMA9_CHOP for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:n20 (variant 0; registered in sweep_lib.REGISTRY
through APPROX12 / _wrap_port, no timeframe scaling). Short only:

    e9 = fg.ema(close, 9)
    reg = fg.research_chop_regime(df, 14)     # RED by default, YELLOW 15 <= ADX14 < 20, GREEN 20..30, BLUE >= 30
    S = isin(reg, [YELLOW, RED]) & lt(close, e9) & cross_below(close, e9)
    L = zeros

YELLOW or RED is exactly 'not (ADX14 >= 20)' (a NaN ADX in the warm-up reads RED, i.e. allowed), so the
filter is written as ~(adx >= adx_thr). ``signals(df, tf)`` with no overrides reproduces the locked signal
bar for bar.

Parameters varied: the EMA length 9, the ADX length 14 (DI and ADX smoothing both, as fg.adx_dmi(df, n)),
the ADX level 20 (threshold_abs: ADX has no neutral point, 0 = no trend). Not varied: the 15 / 30 regime
bounds, which do not enter the rule. The rule does not depend on the timeframe.
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

import fg_indicators as fg  # noqa: E402
from strategies import _f, cross_below, lt  # noqa: E402

NAME = "N20_EMA9_CHOP"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/ports12.py:n20"

PARAMS = [
    {"name": "ema_len", "default": 9, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (e9 = fg.ema(close, 9))"},
    {"name": "adx_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.research_chop_regime(df, 14) -> fg.adx_dmi(df, 14))"},
    {"name": "adx_thr", "default": 20.0, "kind": "threshold_abs", "neutral": None,
     "where": "third_party/sweep/harness/vendor/fg_indicators.py:research_chop_regime via ports12.py:n20 "
              "(YELLOW/RED <=> not ADX >= 20)"},
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
    """(long_bool, short_bool) of len(df); the locked signal when no override is given (long all False)."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    close = df["close"]
    e9 = fg.ema(close, p["ema_len"])
    adx = _f(fg.adx_dmi(df, p["adx_len"])[0])
    with np.errstate(invalid="ignore"):
        quiet = ~(adx >= p["adx_thr"])
    short = np.asarray(quiet & lt(close, e9) & cross_below(close, e9), dtype=bool)
    return np.zeros(len(df), dtype=bool), short
