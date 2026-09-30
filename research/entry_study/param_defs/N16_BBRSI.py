"""Parameter re-implementation of N16_BBRSI for the sensitivity study (PREREG_ENTRY.md section 4, C).

Locked rule: third_party/sweep/harness/vendor/ports12.py:n16 (variant 0; registered in sweep_lib.REGISTRY
through APPROX12 / _wrap_port, no timeframe scaling):

    up, mid, lo, rsi_, mp, sg = fg.mapped_rsi_bollinger(df, 20, 2.0, 14, 5, 2.0)
    reL = (mp[-1] < lo[-1]) & (mp >= lo) & cross_above(mp, sg)
    reS = (mp[-1] > up[-1]) & (mp <= up) & cross_below(mp, sg)
    evL = fg.confirmed_pivot_low(low, 3, 3);  evH = fg.confirmed_pivot_high(high, 3, 3)
    divL on an evL bar i (pivot p = i - 3; prev = previous evL pivot):  5 <= p - prev <= 60 and
         low[p] < low[prev] and mp[p] > mp[prev];   divS mirrored on evH with high / mp
    L = (reL | divL) & (close > open);  S = (reS | divS) & (close < open);  S &= ~L

``signals(df, tf)`` with no overrides reproduces the locked signal bar for bar. The pivot events are
computed vectorised (rolling min / max over the 2k+1 bars i-2k .. i, the pivot read k bars back), which is
the same set as fg.confirmed_pivot_low / _high(x, k, k) (checked in tests/test_entry_defs_N15_KC_AO.py).

Parameters varied:
  bb_len      Bollinger length 20 (the mapped line's centre and scale, used by both paths)
  rsi_len     RSI length 14
  map_scale   2.0: mapped RSI = mid + (RSI - 50) / 50 * band half-width * map_scale. Since the band edge is
              one half-width from mid, 'mapped RSI outside the band' is 'RSI beyond 50 -/+ 50 / map_scale'
              (25 / 75 at 2.0); map_scale also weights RSI against the moving centre in the signal-line cross
              and in the divergence comparison. At x0.5 (1.0) the level is RSI 0 / 100, so the re-entry path
              cannot fire and only divergences remain.
  pivot_len   3: left = right = 3 bars of the confirmed pivots (the pivot sits pivot_len bars before the
              confirming bar). x0.5 and x0.75 both round to 2.
Not varied: Bollinger std 2.0 (it cancels out of the band test and only rescales the mapped line together
with map_scale), the signal EMA length 5 (re-entry path only), the divergence spacing 5..60 bars. The
re-entry path gave about a quarter of the default long signals on BTC 15m / 1h / 4h (signal counts only,
no outcome looked at), the divergence path the rest, so the varied numbers are the ones both paths use plus
the pivot length.
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

sweepsig.lib()  # hash-checked locked code; puts the vendored indicator modules on sys.path

import fg_indicators as fg  # noqa: E402
from strategies import _f, cross_above, cross_below  # noqa: E402

NAME = "N16_BBRSI"
EXCLUDED_REASON = None
_WHERE = "third_party/sweep/harness/vendor/ports12.py:n16"
BB_STD = 2.0          # locked, not varied
SIG_LEN = 5           # locked, not varied
SPACING = (5, 60)     # locked, not varied

PARAMS = [
    {"name": "bb_len", "default": 20, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.mapped_rsi_bollinger(df, 20, 2.0, 14, 5, 2.0): Bollinger length)"},
    {"name": "rsi_len", "default": 14, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.mapped_rsi_bollinger(df, 20, 2.0, 14, 5, 2.0): RSI length)"},
    {"name": "map_scale", "default": 2.0, "kind": "mult", "neutral": None,
     "where": f"{_WHERE} (fg.mapped_rsi_bollinger(df, 20, 2.0, 14, 5, 2.0): map_scale, RSI band level 50 -/+ 50 / 2.0)"},
    {"name": "pivot_len", "default": 3, "kind": "length", "neutral": None,
     "where": f"{_WHERE} (fg.confirmed_pivot_low(df['low'], 3, 3) / confirmed_pivot_high(df['high'], 3, 3); p = i - 3)"},
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


def pivot_events(x: np.ndarray, k: int, low: bool) -> np.ndarray:
    """Event bool of fg.confirmed_pivot_low (low=True) / confirmed_pivot_high(x, k, k): bar i >= 2k confirms
    the pivot at i - k when x[i - k] is the min (max) of x[i - 2k .. i] (NaN-skipping, as window.min())."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    ev = np.zeros(n, bool)
    if n > 2 * k:
        r = pd.Series(x).rolling(2 * k + 1, min_periods=1)
        ext = (r.min() if low else r.max()).to_numpy()
        piv = _sh(x, k)
        with np.errstate(invalid="ignore"):
            ok = (piv <= ext) if low else (piv >= ext)
        ev[2 * k:] = (~np.isnan(piv[2 * k:])) & ok[2 * k:]
    return ev


def _divergence(price: np.ndarray, mp: np.ndarray, ev: np.ndarray, k: int, low: bool) -> np.ndarray:
    out = np.zeros(len(price), bool)
    prev = None
    for i in np.flatnonzero(ev):
        p = i - k
        if prev is not None and SPACING[0] <= p - prev <= SPACING[1]:
            if low and price[p] < price[prev] and mp[p] > mp[prev]:
                out[i] = True
            elif not low and price[p] > price[prev] and mp[p] < mp[prev]:
                out[i] = True
        prev = p
    return out


def signals(df, tf, **overrides):
    """(long_bool, short_bool) of len(df); the locked signal when no override is given."""
    p = _resolve(overrides)
    df = df.reset_index(drop=True)
    o, h, l, c = (_f(df[k]) for k in ("open", "high", "low", "close"))
    up, _mid, lo, _rsi, mp, sg = fg.mapped_rsi_bollinger(df, p["bb_len"], BB_STD, p["rsi_len"], SIG_LEN,
                                                         p["map_scale"])
    upf, lof, mpf = _f(up), _f(lo), _f(mp)
    mp1, lo1, up1 = _sh(mpf, 1), _sh(lof, 1), _sh(upf, 1)
    xu, xd = cross_above(mp, sg), cross_below(mp, sg)
    with np.errstate(invalid="ignore"):
        reL = (mp1 < lo1) & (mpf >= lof) & xu
        reS = (mp1 > up1) & (mpf <= upf) & xd
    k = p["pivot_len"]
    divL = _divergence(l, mpf, pivot_events(l, k, True), k, True)
    divS = _divergence(h, mpf, pivot_events(h, k, False), k, False)
    long = np.asarray((reL | divL) & (c > o), dtype=bool)
    short = np.asarray((reS | divS) & (c < o), dtype=bool) & ~long
    return long, short
