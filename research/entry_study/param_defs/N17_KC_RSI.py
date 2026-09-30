"""Parameter re-implementation of N17_KC_RSI for the sensitivity study (PREREG_ENTRY.md section 4, C).

``signals(df, tf)`` with no overrides reproduces ``strategies.n17_keltner_rsi`` bar for bar (plus the
``short & ~long`` step of sweep_lib._clean). Locked code:

    mid = fg.ema(close, 20);  a = fg.atr(df, 14);  upper, lower = mid + a * 2.0, mid - a * 2.0
    r = fg.rsi(close, 14);  approach = 0.10 * a
    long_touch = low <= lower + approach;  short_touch = high >= upper - approach
    long  = synchronized([long_touch, r <= 30], 2)
    short = synchronized([short_touch, r >= 70], 2) & ~long

``rsi_level`` is the long level (30); the short level is its mirror 100 - rsi_level (70), so the variant
50 + m * (30 - 50) moves both levels the same distance from the neutral 50.
Not parameters here: ATR length 14 (also the ATR of the approach), approach 0.10 ATR (a small shift of the
same band edge that kc_mult moves), sync 2. The rule does not depend on the timeframe.
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
from strategies import ge, le, synchronized  # noqa: E402

NAME = "N17_KC_RSI"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/strategies.py:n17_keltner_rsi"
ATR_LEN = 14      # locked, not varied
APPROACH = 0.10   # locked, not varied
SYNC = 2          # locked, not varied

PARAMS = [
    {"name": "kc_len", "default": 20, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (mid = fg.ema(df['close'], 20): Keltner middle line)"},
    {"name": "kc_mult", "default": 2.0, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (upper, lower = mid + a * 2.0, mid - a * 2.0)"},
    {"name": "rsi_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (r = fg.rsi(df['close'], 14))"},
    {"name": "rsi_level", "default": 30.0, "kind": "threshold_neutral", "neutral": 50.0,
     "where": f"{_WHERE} (long_rsi = le(r, 30.0); short uses the mirror 100 - level: ge(r, 70.0))"},
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
    mid = fg.ema(df["close"], p["kc_len"])
    a = fg.atr(df, ATR_LEN)
    upper, lower = mid + a * p["kc_mult"], mid - a * p["kc_mult"]
    r = fg.rsi(df["close"], p["rsi_len"])
    approach = APPROACH * a
    long_touch = le(df["low"], lower + approach)
    short_touch = ge(df["high"], upper - approach)
    long_rsi, short_rsi = le(r, p["rsi_level"]), ge(r, 100.0 - p["rsi_level"])
    long = np.asarray(synchronized([long_touch, long_rsi], SYNC), dtype=bool)
    short = np.asarray(synchronized([short_touch, short_rsi], SYNC), dtype=bool) & ~long
    return long, short
