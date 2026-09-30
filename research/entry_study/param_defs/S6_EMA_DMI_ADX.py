"""Parameter re-implementation of S6_EMA_DMI_ADX for the sensitivity study (PREREG_ENTRY.md section 4, C).

``signals(df, tf)`` with no overrides reproduces ``strategies.s6_ema_dmi_adx`` bar for bar (plus the
``short & ~long`` step of sweep_lib._clean). Locked code:

    e = fg.ema(close, 20)
    plus, minus, adx = fg.dmi_adx(df, 14, 14)
    price_up / down = close crosses above / below e;  di_up = +DI crosses above -DI, di_down = -DI above +DI
    sync = 2, adx_ok = adx >= 25
    long  = adx_ok & recent(di_up, 2) & recent(price_up, 2) & close > e & +DI > -DI & (price_up | di_up)
    short = adx_ok & recent(di_down, 2) & recent(price_down, 2) & close < e & -DI > +DI & (price_down | di_down)

Not a parameter here: sync = 2 (x0.5 and x0.75 round to 1 -> min 2 = the default, so only two of its four
variants would differ); the four chosen are the ones that define the entry levels. The ADX threshold has no
neutral point (0 = no trend), so it is 'threshold_abs'. The rule does not depend on the timeframe.
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
from strategies import cross_above, cross_below, ge, gt, lt, recent  # noqa: E402

NAME = "S6_EMA_DMI_ADX"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/strategies.py:s6_ema_dmi_adx"
SYNC = 2  # locked, not varied

PARAMS = [
    {"name": "ema_len", "default": 20, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.ema(df['close'], 20))"},
    {"name": "di_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.dmi_adx(df, 14, 14): di_length, the +DI/-DI and ATR smoothing)"},
    {"name": "adx_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.dmi_adx(df, 14, 14): adx_smoothing)"},
    {"name": "adx_min", "default": 25.0, "kind": "threshold_abs", "neutral": None,
     "where": f"{_WHERE} (adx_ok = ge(adx, 25.0))"},
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
        if s["kind"] == "length":
            p[k] = int(p[k])
        else:
            p[k] = float(p[k])
    return p


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    e = fg.ema(df["close"], p["ema_len"])
    plus, minus, adx = fg.dmi_adx(df, p["di_len"], p["adx_len"])
    close = df["close"]
    price_up = cross_above(close, e)
    price_down = cross_below(close, e)
    di_up = cross_above(plus, minus)
    di_down = cross_above(minus, plus)
    adx_ok = ge(adx, p["adx_min"])
    long_state = gt(close, e) & gt(plus, minus)
    short_state = lt(close, e) & gt(minus, plus)
    long = adx_ok & recent(di_up, SYNC) & recent(price_up, SYNC) & long_state & (price_up | di_up)
    short = adx_ok & recent(di_down, SYNC) & recent(price_down, SYNC) & short_state & (price_down | di_down)
    long = np.asarray(long, dtype=bool)
    short = np.asarray(short, dtype=bool) & ~long
    return long, short
