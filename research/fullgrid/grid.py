"""The full-grid custom-value study's parameter grid (research/fullgrid, DESIGN_KO.md). DRAFT until the owners' OK;
then PREREG.md pins this file's sha256.

Every parameter of the 2026-09-30 parameter study (research/entry_study/param_defs/<NAME>.py, DEFS_BC.sha256) gets 9
values (fewer when values collide after rounding or clipping); a strategy's grid is every combination (the product),
minus combinations that break a rule's own order (``valid``).

- length (bars):          default x (1/3, 1/2, 2/3, 0.8, 1, 1.25, 1.5, 2, 3), rounded half up, at least 2
- mult / threshold_abs:   default x the same nine, clipped to the parameter's bounds (``BOUNDS``)
- threshold_neutral:      neutral + f x (default - neutral), f in (0.25, 0.5, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 2), clipped
                          to the oscillator's range (never crossing the neutral point: the rule keeps its meaning)
"""
from __future__ import annotations

import itertools
import math

MULTS = (1 / 3, 1 / 2, 2 / 3, 0.8, 1.0, 1.25, 1.5, 2.0, 3.0)
NEUTRAL_F = (0.25, 0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0)

# (strategy, parameter) -> (low, high): where a value stops meaning the same rule (a body or a fraction above 1, an
# oscillator level outside its range). Parameters not listed are bounded only by > 0.
BOUNDS = {
    ("S5_DONCHIAN_MFI", "mfi_level"): (0.0, 100.0), ("S1_EMA_RSI_CHOP", "rsi_level"): (0.0, 100.0),
    ("N14_ICHI_RSI", "rsi_oversold"): (0.0, 100.0), ("N17_KC_RSI", "rsi_level"): (0.0, 100.0),
    ("N21_ST_RSI_ADX", "rsi_level"): (0.0, 100.0), ("OBV_S", "stc_level"): (0.0, 100.0),
    ("N08_ICHI_WR", "wr_oversold"): (-100.0, 0.0),
    ("S6_EMA_DMI_ADX", "adx_min"): (0.0, 100.0), ("N03_ADX_GC", "adx_level"): (0.0, 100.0),
    ("N21_ST_RSI_ADX", "adx_level"): (0.0, 100.0), ("N24_DMI", "adx_long_min"): (0.0, 100.0),
    ("N24_DMI", "adx_short_max"): (0.0, 100.0), ("N20_EMA9_CHOP", "adx_thr"): (0.0, 100.0),
    ("DOGE", "chop_max"): (0.0, 100.0),
    ("S4_BB_BBP", "sq_pct"): (0.0, 1.0), ("N05_PSAR_POC", "pierce_frac"): (0.0, 1.0),
    ("N11_BREAKAWAY", "big_body"): (0.0, 1.0), ("N11_BREAKAWAY", "small_body"): (0.0, 1.0),
    ("N13_3OUTSIDE", "engulf_min"): (0.0, 1.0), ("N19_FIB_CHOP", "fib_level"): (0.0, 1.0),
    ("S3_CMO_SANDWICH", "body_min"): (0.0, 1.0),
}


def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def values(strategy: str, spec: dict) -> list:
    """The parameter's distinct values, ascending, the default included."""
    d, kind = spec["default"], spec["kind"]
    lo, hi = BOUNDS.get((strategy, spec["name"]), (0.0, math.inf))
    out = set()
    if kind == "length" and isinstance(d, (list, tuple)):     # a set of lengths scaled together (KST, Klinger)
        out = {tuple(max(2, _round_half_up(x * m)) for x in d) for m in MULTS}
        out.add(tuple(d))
        return [list(v) for v in sorted(out)]
    if kind == "length":
        out = {max(2, _round_half_up(d * m)) for m in MULTS}
    elif kind in ("mult", "threshold_abs"):
        for m in MULTS:
            v = round(float(d) * m, 12)
            if lo < v <= hi or (v == hi and hi < math.inf):
                out.add(v)
    elif kind == "threshold_neutral":
        n = float(spec["neutral"])
        for f in NEUTRAL_F:
            v = round(n + f * (float(d) - n), 12)
            v = min(max(v, lo), hi)
            if v != n:
                out.add(v)
    else:
        raise ValueError(f"{strategy}.{spec['name']}: unknown kind {kind}")
    out.add(d if kind == "length" else float(d))
    return sorted(out)


def valid(strategy: str, combo: dict) -> bool:
    """Combinations that keep a rule's own order (Parabolic SAR: start and step not above the cap; two bodies: the
    small one smaller than the big one; DOGE has none)."""
    for start, step, cap in (("sar_af_start", "sar_af_step", "sar_af_max"), ("psar_start", "psar_step", "psar_max")):
        if cap in combo and (combo[start] > combo[cap] or combo[step] > combo[cap]):
            return False
    if "big_body" in combo and combo["small_body"] >= combo["big_body"]:
        return False
    return True


def grid(strategy: str, params: list) -> list[dict]:
    names = [p["name"] for p in params]
    vals = [values(strategy, p) for p in params]
    return [dict(zip(names, c)) for c in itertools.product(*vals) if valid(strategy, dict(zip(names, c)))]
