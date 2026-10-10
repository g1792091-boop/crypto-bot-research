"""후보 리그: the full-grid study's 84 exit rules on the paper bot's own engine (paperbot.engine.PaperEngine).

The study computed every exit with research/fullgrid/kernel.py, checked trade for trade against PaperEngine set up as
here (tests/test_fullgrid_kernel.py); this module is that set-up, for the league's live accounts, without numba:

- EXITS: the same 84 rules, same names and order as kernel.EXITS ("<take-profit rule>|<stop x ATR14>").
- make_engine(exit name, ...): a PaperEngine (or a small subclass) that exits the way the rule means: the stepped lock
  (first lock, step, trigger gap), a fixed take-profit at net ROE (the engine's tp_mode "fixed"), at the entry
  reference + m x R (R = the stop distance), or the stepped lock plus a take-profit at m x R or at a structure level.
- The stop width is the signal's ``meta["stop_dist"]`` = k x ATR14 (stop_dist below); a structure exit reads the
  signal's ``meta["tp_struct"]`` (structure_level, the kernel's structure_levels for one bar).
"""

from __future__ import annotations

import math

import numpy as np

from paperbot.config import v3_settings
from paperbot.engine import PaperEngine
from paperbot.policy import OwnerPolicy

TP_NONE, TP_R, TP_ROE, TP_STRUCT = 0, 1, 2, 3
TP_RULES = (("ladder", TP_NONE, 0.0, True, 0.10, 0.05, 0.02),
            ("ladder5", TP_NONE, 0.0, True, 0.05, 0.05, 0.02),
            ("ladder20", TP_NONE, 0.0, True, 0.20, 0.05, 0.02),
            ("roe10", TP_ROE, 0.10, False, 0.10, 0.05, 0.02),
            ("roe20", TP_ROE, 0.20, False, 0.10, 0.05, 0.02),
            ("roe30", TP_ROE, 0.30, False, 0.10, 0.05, 0.02),
            ("roe50", TP_ROE, 0.50, False, 0.10, 0.05, 0.02),
            ("tp1R", TP_R, 1.0, False, 0.10, 0.05, 0.02),
            ("tp1.5R", TP_R, 1.5, False, 0.10, 0.05, 0.02),
            ("tp2R", TP_R, 2.0, False, 0.10, 0.05, 0.02),
            ("tp3R", TP_R, 3.0, False, 0.10, 0.05, 0.02),
            ("ladder_tp2R", TP_R, 2.0, True, 0.10, 0.05, 0.02),
            ("swing3", TP_STRUCT, 3.0, True, 0.10, 0.05, 0.02),
            ("swing10", TP_STRUCT, 10.0, True, 0.10, 0.05, 0.02))
STRUCT_LOOKBACK = 300
STOPS = (2.0, 1.0, 1.5, 2.5, 3.0, 4.0)
EXITS = tuple((f"{r[0]}|{k:g}", k) + r[1:] for k in STOPS for r in TP_RULES)
BY_NAME = {e[0]: e for e in EXITS}
LIVE_EXIT = EXITS[0][0]                       # "ladder|2": the rule bot's own exit

# Korean labels (research/fullgrid/report.py's wording)
TP_KO = {"ladder": "계단 잠금 10%부터", "ladder5": "계단 잠금 5%부터", "ladder20": "계단 잠금 20%부터",
         "roe10": "고정 익절 수익 10%", "roe20": "고정 익절 수익 20%", "roe30": "고정 익절 수익 30%",
         "roe50": "고정 익절 수익 50%", "tp1R": "고정 익절 1R", "tp1.5R": "고정 익절 1.5R", "tp2R": "고정 익절 2R",
         "tp3R": "고정 익절 3R", "ladder_tp2R": "계단 잠금 + 익절 2R", "swing3": "구조 익절(3봉 스윙) + 계단 잠금",
         "swing10": "구조 익절(10봉 스윙) + 계단 잠금"}


def exit_ko(name: str) -> str:
    rule, k = name.split("|")
    return f"{TP_KO[rule]} · 손절 {k} ATR"


def spec(name: str) -> dict:
    """{stop_atr, tp_kind, tp_val, ladder, first_lock, step, gap} of an exit rule (KeyError for an unknown name)."""
    e = BY_NAME[name]
    return dict(zip(("stop_atr", "tp_kind", "tp_val", "ladder", "first_lock", "step", "gap"), e[1:]))


def stop_dist(name: str, atr: float) -> float:
    return spec(name)["stop_atr"] * atr


def structure_level(h, lo, c, i: int, k: int, side: int, lookback: int = STRUCT_LOOKBACK) -> float:
    """kernel.structure_levels for bar ``i`` and one side: the lowest confirmed swing high above c[i] (side 1) or the
    highest confirmed swing low below it (side -1) among swings at p in [i - lookback, i - k]; NaN when none. A swing
    high at p has a high strictly above the k bars on each side."""
    h, lo = np.asarray(h, float), np.asarray(lo, float)
    best = math.inf if side > 0 else -math.inf
    n = len(h)
    for p in range(max(0, i - lookback, k), i - k + 1):
        if p + k >= n:
            break
        win = np.r_[p - k:p, p + 1:p + k + 1]
        if side > 0 and np.all(h[p] > h[win]) and h[p] > c[i] and h[p] < best:
            best = float(h[p])
        if side < 0 and np.all(lo[p] < lo[win]) and lo[p] < c[i] and lo[p] > best:
            best = float(lo[p])
    return best if math.isfinite(best) else math.nan


class RPolicy(OwnerPolicy):
    """A fixed take-profit at the entry reference price + m x the stop distance."""

    def __init__(self, settings, m):
        super().__init__(settings)
        self.m = m

    def take_profit(self, sig, entry, dec):
        return sig.meta["ref_price"] + sig.side * self.m * sig.meta["stop_dist"]


class LadderTP(PaperEngine):
    """The stepped lock plus a take-profit limit: at m x R, or (struct) at the signal's structure level when it lies
    beyond the fill."""

    def __init__(self, *a, m=0.0, struct=False, **k):
        super().__init__(*a, **k)
        self.m, self.struct = m, struct

    def _try_enter(self, sig, bar):
        ok = super()._try_enter(sig, bar)
        if ok:
            p = self.position
            if self.struct:
                lvl = p.signal.meta.get("tp_struct", math.nan)
                if lvl is not None and np.isfinite(lvl) and (lvl - p.entry_price) * p.side > 0:
                    p.tp_price = lvl
            else:
                p.tp_price = p.signal.meta["ref_price"] + p.side * self.m * p.signal.meta["stop_dist"]
        return ok


def settings_for(name: str, **kw):
    """The v4 settings with this exit's lock and take-profit mode (``kw``: other v3_settings overrides)."""
    s = spec(name)
    kw = {**kw, "ladder_first_lock": s["first_lock"], "ladder_step": s["step"], "ladder_trigger_gap": s["gap"]}
    if not s["ladder"]:
        kw["tp_mode"] = "fixed"
        if s["tp_kind"] == TP_ROE:
            kw["default_tp_roe"] = s["tp_val"]
    return v3_settings(**kw)


def make_engine(name: str, brackets: dict, specs: dict, book=None, **kw) -> PaperEngine:
    """A paper account that exits by rule ``name`` (signals must carry meta stop_dist = stop_dist(name, atr), and
    tp_struct for a structure rule)."""
    s, st = spec(name), settings_for(name, **kw)
    extra = {} if book is None else {"book": book}
    if s["ladder"] and s["tp_kind"] == TP_STRUCT:
        return LadderTP(st, brackets, symbol_specs=specs, struct=True, **extra)
    if s["ladder"] and s["tp_kind"] == TP_R:
        return LadderTP(st, brackets, symbol_specs=specs, m=s["tp_val"], **extra)
    if s["ladder"] or s["tp_kind"] == TP_ROE:
        return PaperEngine(st, brackets, symbol_specs=specs, **extra)
    return PaperEngine(st, brackets, symbol_specs=specs, policy=RPolicy(st, s["tp_val"]), **extra)
