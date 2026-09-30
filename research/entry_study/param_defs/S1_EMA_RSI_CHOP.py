"""Parameter re-implementation of S1_EMA_RSI_CHOP for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:s1 (variant 0; registered in sweep_lib.REGISTRY
through APPROX12 / _wrap_port, no timeframe scaling):

    e5, e20 = fg.ema(close, 5), fg.ema(close, 20)
    r = fg.rsi(close, 14);  r1 = r[-1]
    _ang, cz, _st = fg.chop_zone_proxy(df, 34, 1.0, 5.0, 14);  cz1 = cz[-1]
    eu, ed = cross_above(e5, e20), cross_below(e5, e20)
    ru = (r1 < 30) & (r > r1);  rd = (r1 > 70) & (r < r1)
    cu = (cz1 <= 0) & (cz > 0); cd = (cz1 >= 0) & (cz < 0)
    L = recent(eu, 3) & recent(ru, 3) & recent(cu, 3) & (e5 > e20) & (cz > 0) & (eu | ru | cu)
    S = recent(ed, 3) & recent(rd, 3) & recent(cd, 3) & (e5 < e20) & (cz < 0) & (ed | rd | cd)
    S &= ~L                                 (ports12._pack and sweep_lib._clean)

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar. Parameters varied (one
per indicator, plus the RSI level):
  ema_slow   the EMA20 of the EMA5/EMA20 cross
  rsi_len    the RSI length 14
  rsi_level  the long level 30; the short level is its mirror 100 - rsi_level (70), so the variant
             50 + m * (30 - 50) moves both levels the same distance from the neutral 50
  chop_len   the EMA34 whose 1-bar slope makes the chop-zone angle
Not varied: EMA5; chop ATR length 14; the 3-bar windows; the chop-zone angle line 1.0 degree (its x0.75 /
x1.25 variants changed 0 of the 21 BTC 1h signals and 0-1 of the 56 BTC 15m signals: signal counts only,
no outcome looked at); the 5-degree 'strong' angle, which only splits +1 from +2 and never changes the rule.
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
from strategies import _f, cross_above, cross_below, recent  # noqa: E402

NAME = "S1_EMA_RSI_CHOP"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/ports12.py:s1"
EMA_FAST = 5         # locked, not varied
CHOP_ANGLE = 1.0     # locked, not varied (see module docstring)
CHOP_STRONG = 5.0    # locked, does not change the rule
CHOP_ATR = 14        # locked, not varied
WINDOW = 3           # recent(..., 3), locked, not varied

PARAMS = [
    {"name": "ema_slow", "default": 20, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (e5, e20 = fg.ema(close, 5), fg.ema(close, 20): slow EMA of the cross)"},
    {"name": "rsi_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (r = _f(fg.rsi(close, 14)))"},
    {"name": "rsi_level", "default": 30.0, "kind": "threshold_neutral", "neutral": 50.0,
     "where": f"{_WHERE} (ru = (r1 < 30) & (r > r1); short uses the mirror 100 - level: rd = (r1 > 70) & (r < r1))"},
    {"name": "chop_len", "default": 34, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.chop_zone_proxy(df, 34, 1.0, 5.0, 14): EMA length of the slope angle)"},
]
_SPEC = {p["name"]: p for p in PARAMS}
MULTIPLIERS = (0.5, 0.75, 1.25, 1.5)


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def variant_value(spec: dict, m: float):
    """PREREG 4: length -> round half up, min 2; mult / threshold_abs -> m * default;
    threshold_neutral -> neutral + m * (default - neutral). Floats are rounded to 12 decimals
    (0.15000000000000002 -> 0.15)."""
    d, kind = spec["default"], spec["kind"]
    if kind == "length":
        return max(2, _round_half_up(d * m))
    if kind in ("mult", "threshold_abs"):
        return round(float(d) * m, 12)
    if kind == "threshold_neutral":
        return round(float(spec["neutral"]) + m * (float(d) - float(spec["neutral"])), 12)
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


def _sh(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[:len(x) - k]
    return out


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    close = df["close"]
    e5, e20 = fg.ema(close, EMA_FAST), fg.ema(close, p["ema_slow"])
    r = _f(fg.rsi(close, p["rsi_len"]))
    r1 = _sh(r, 1)
    _ang, cz, _st = fg.chop_zone_proxy(df, p["chop_len"], CHOP_ANGLE, CHOP_STRONG, CHOP_ATR)
    cz = _f(cz)
    cz1 = _sh(cz, 1)
    eu, ed = cross_above(e5, e20), cross_below(e5, e20)
    lo_lvl, hi_lvl = p["rsi_level"], 100.0 - p["rsi_level"]
    with np.errstate(invalid="ignore"):
        ru = (r1 < lo_lvl) & (r > r1)
        rd = (r1 > hi_lvl) & (r < r1)
        cu = (cz1 <= 0) & (cz > 0)
        cd = (cz1 >= 0) & (cz < 0)
        lst = (_f(e5) > _f(e20)) & (cz > 0)
        sst = (_f(e5) < _f(e20)) & (cz < 0)
    long = recent(eu, WINDOW) & recent(ru, WINDOW) & recent(cu, WINDOW) & lst & (eu | ru | cu)
    short = recent(ed, WINDOW) & recent(rd, WINDOW) & recent(cd, WINDOW) & sst & (ed | rd | cd)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
