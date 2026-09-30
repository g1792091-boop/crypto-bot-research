"""Parameter re-implementation of N15_KC_AO for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:n15 (variant 0; registered in sweep_lib.REGISTRY
through APPROX12 / _wrap_port, no timeframe scaling):

    up, mid, lo = fg.keltner_channel(df, 20, 10, 2.0)        # EMA20 +/- 2.0 x ATR10
    ao = _f(fg.awesome_oscillator(df, 5, 34));  ao1 = _sh(ao, 1)
    L = (_sh(l, 1) < _sh(lo, 1)) & (c > lo) & (ao > ao1) & (ao > 0)
    S = (_sh(h, 1) > _sh(up, 1)) & (c < up) & (ao < ao1) & (ao < 0)
    S &= ~L                                 (ports12._pack and sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar. Parameters varied: the
Keltner middle EMA length and band multiplier (where the band is) and the two AO lengths (the AO sign and
slope). Not varied: the Keltner ATR length 10 (it smooths the band width that kc_mult scales). The rule does
not depend on the timeframe.
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
from strategies import _f  # noqa: E402

NAME = "N15_KC_AO"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/ports12.py:n15"
KC_ATR_LEN = 10   # locked, not varied

PARAMS = [
    {"name": "kc_len", "default": 20, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.keltner_channel(df, 20, 10, 2.0): middle EMA length)"},
    {"name": "kc_mult", "default": 2.0, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (fg.keltner_channel(df, 20, 10, 2.0): band = EMA +/- 2.0 x ATR10)"},
    {"name": "ao_fast", "default": 5, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.awesome_oscillator(df, 5, 34): fast SMA of the median price)"},
    {"name": "ao_slow", "default": 34, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.awesome_oscillator(df, 5, 34): slow SMA of the median price)"},
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


def _sh(x: np.ndarray, k: int = 1) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) > k:
        out[k:] = x[:-k]
    return out


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    h, l, c = (_f(df[k]) for k in ("high", "low", "close"))
    up, _mid, lo = fg.keltner_channel(df, p["kc_len"], KC_ATR_LEN, p["kc_mult"])
    upf, lof = _f(up), _f(lo)
    ao = _f(fg.awesome_oscillator(df, p["ao_fast"], p["ao_slow"]))
    ao1 = _sh(ao, 1)
    with np.errstate(invalid="ignore"):
        long = (_sh(l, 1) < _sh(lof, 1)) & (c > lof) & (ao > ao1) & (ao > 0)
        short = (_sh(h, 1) > _sh(upf, 1)) & (c < upf) & (ao < ao1) & (ao < 0)
    long = np.asarray(long, dtype=bool)
    return long, np.asarray(short, dtype=bool) & ~long
