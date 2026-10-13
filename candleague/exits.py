"""후보 리그: the full-grid study's 84 exit rules on the paper bot's own engine (paperbot.engine.PaperEngine).

The study computed every exit with research/fullgrid/kernel.py, checked trade for trade against PaperEngine set up as
here (tests/test_fullgrid_kernel.py); this module is that set-up, for the league's live accounts, without numba:

- EXITS: the same 84 rules, same names and order as kernel.EXITS ("<take-profit rule>|<stop x ATR14>").
- make_engine(exit name, ...): a PaperEngine (or a small subclass) that exits the way the rule means: the stepped lock
  (first lock, step, trigger gap), a fixed take-profit at net ROE (the engine's tp_mode "fixed"), at the entry
  reference + m x R (R = the stop distance), or the stepped lock plus a take-profit at m x R or at a structure level.
- The stop width is the signal's ``meta["stop_dist"]`` = k x ATR14 (stop_dist below); a structure exit reads the
  signal's ``meta["tp_struct"]`` (structure_level, the kernel's structure_levels for one bar).
- ADDED for the exit study's family F13 (research/exitflex/PREREG_EXITFLEX.md 5.2, "stepped lock"): ``lock_exit(name, mode)`` builds,
  from a pick's own exit name, the exit "the pick's hard stop and the rule bot's stepped lock (``LOCK``: 10%, 5% steps, a step arms at
  lock + 2%), with the pick's own fixed take-profit kept (mode a) or none (mode b: ``ladder|k``)". A name that is not one of the 84
  above is built as "lock+<take-profit rule>|<k>" ("lock+tp3R|4", "lock+roe50|4"); the existing 84 names and what they do are unchanged
  (``lock_exit`` maps "tp2R|k" to the existing "ladder_tp2R|k", the same rule). ``spec`` / ``make_engine`` / ``exit_ko`` read these names
  as well; EXITS (the kernel's 84) does not list them.
"""

from __future__ import annotations

import math
import os
from typing import Optional

import numpy as np

from paperbot.config import V3_INITIAL, v3_settings
from paperbot.engine import PaperEngine
from paperbot.ladder import net_roe, roe_price, tighten
from paperbot.policy import OwnerPolicy
from paperbot.sizing import tp_from_roe

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


# ---- F13: the stepped lock added to a pick's own exit (names built on demand; none of the 84 above changes)
LOCK = (0.10, 0.05, 0.02)                      # first lock, step, trigger gap: kernel TP_RULES "ladder" = paperbot/ladder.py LadderSpec
LOCK_PREFIX = "lock+"
_LOCKABLE = tuple(r for r in TP_RULES if not r[3])           # the rules with a fixed take-profit and no lock: tp1R .. tp3R, roe10 .. roe50
_EXISTING_LOCK_PLUS = {"tp2R": "ladder_tp2R"}                # lock + 2R is already one of the 84


def _lock_plus_spec(name: str):
    """The kernel-style row of "lock+<rule>|<k>" ((name, k, kind, value, True, 0.10, 0.05, 0.02)), or None when ``name`` is not one."""
    if not name.startswith(LOCK_PREFIX) or "|" not in name:
        return None
    rule, k = name[len(LOCK_PREFIX):].split("|", 1)
    base = next((r for r in _LOCKABLE if r[0] == rule), None)
    if base is None:
        return None
    try:
        kf = float(k)
    except ValueError:
        return None
    if f"{kf:g}" != k or kf not in STOPS:
        return None
    return (name, kf, base[1], base[2], True) + LOCK


def lock_exit(name: str, mode: str = "a") -> str:
    """F13 (PREREG_EXITFLEX 5.2): the exit of a pick whose own exit is ``name`` ("<take-profit rule>|<k>") with the stepped lock
    added. Mode "a": the pick's fixed take-profit kept and the lock added ("tp3R|4" -> "lock+tp3R|4"; "tp2R|2" -> "ladder_tp2R|2",
    which is that rule among the 84; a rule that already has the lock at 10% ("ladder", "ladder_tp2R", "swing3", "swing10") stays as it
    is; "ladder5" and "ladder20" get the lock at 10% instead of theirs: "ladder|k"). Mode "b": no fixed take-profit, the lock alone,
    the rule bot's exit ("ladder|k"). The hard stop (k x ATR14) is the pick's in both."""
    if mode not in ("a", "b"):
        raise ValueError(f"F13 mode {mode!r} is neither a nor b")
    rule, k = name.split("|")
    base = BY_NAME.get(name) or _lock_plus_spec(name)
    if base is None:
        raise KeyError(name)
    if mode == "b" or rule in ("ladder5", "ladder20"):
        return f"ladder|{k}"
    if base[4]:                                                  # the pick's exit has the lock already (10%, or a name built here)
        return name
    return f"{_EXISTING_LOCK_PLUS[rule]}|{k}" if rule in _EXISTING_LOCK_PLUS else f"{LOCK_PREFIX}{rule}|{k}"


# ---- the owners' own stepped lock (owners 2026-10-13): "13%가 되면 10% 자동익절, 20%가 되면 15%, 25%가 되면 20%, 30%가 되면 25%"
# Names "ladderU|<k>": the pick's stop of k x ATR14 and a lock on net ROE (after fees, slippage and funding, as the rule bot's ladder):
# best net ROE >= 13% locks 10%, >= 20% locks 15%, then 5% more for every 5% more (25 -> 20, 30 -> 25, 35 -> 30 ...). No fixed take-profit.
ULAD = "ladderU"
ULAD_FIRST = (0.13, 0.10)                    # (best net ROE that arms the first lock, the net ROE it locks)
ULAD_SECOND = (0.20, 0.15)
ULAD_STEP = 0.05


def user_lock_for(best: float):
    """The highest lock armed by a best net ROE under the owners' ladder, or None below 13%."""
    if best < ULAD_FIRST[0] - 1e-12:
        return None
    if best < ULAD_SECOND[0] - 1e-12:
        return ULAD_FIRST[1]
    return round(ULAD_SECOND[1] + ULAD_STEP * math.floor((best - ULAD_SECOND[0]) / ULAD_STEP + 1e-9), 10)


def _user_ladder_spec(name: str):
    """The kernel-style row of "ladderU|<k>" ((name, k, TP_NONE, 0, True, 0.10, 0.05, 0.03)), or None when ``name`` is not one."""
    if not name.startswith(ULAD + "|"):
        return None
    k = name.split("|", 1)[1]
    try:
        kf = float(k)
    except ValueError:
        return None
    if f"{kf:g}" != k or kf not in STOPS:
        return None
    return (name, kf, TP_NONE, 0.0, True, ULAD_FIRST[1], ULAD_STEP, round(ULAD_FIRST[0] - ULAD_FIRST[1], 6))


def known(name: str) -> bool:
    """Whether ``spec`` can read this exit name: one of the 84, or "lock+<take-profit rule>|<k>"."""
    return name in BY_NAME or _lock_plus_spec(name) is not None or _user_ladder_spec(name) is not None


def exit_ko(name: str) -> str:
    rule, k = name.split("|")
    if rule == ULAD:
        return f"두 분 계단 익절(13%→10%, 20%→15%, 25%→20%, 30%→25%…) · 손절 {k} ATR"
    if rule.startswith(LOCK_PREFIX):
        return f"계단 잠금 10%부터 + {TP_KO[rule[len(LOCK_PREFIX):]]} · 손절 {k} ATR"
    return f"{TP_KO[rule]} · 손절 {k} ATR"


def spec(name: str) -> dict:
    """{stop_atr, tp_kind, tp_val, ladder, first_lock, step, gap} of an exit rule (KeyError for an unknown name)."""
    e = BY_NAME.get(name)
    if e is None:
        e = _lock_plus_spec(name) or _user_ladder_spec(name)
        if e is None:
            raise KeyError(name)
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
    """The stepped lock plus a take-profit limit: at m x R, at net ROE ``roe`` (F13: the pick's "roe50|k" with the lock), or (struct)
    at the signal's structure level when it lies beyond the fill."""

    def __init__(self, *a, m=0.0, struct=False, roe=None, **k):
        super().__init__(*a, **k)
        self.m, self.struct, self.roe = m, struct, roe

    def _try_enter(self, sig, bar):
        ok = super()._try_enter(sig, bar)
        if ok:
            p = self.position
            if self.struct:
                lvl = p.signal.meta.get("tp_struct", math.nan)
                if lvl is not None and np.isfinite(lvl) and (lvl - p.entry_price) * p.side > 0:
                    p.tp_price = lvl
            elif self.roe is not None:                # the engine's own fixed-mode price (policy.tp_from_roe on the fill and the leverage)
                p.tp_price = tp_from_roe(p.side, p.entry_price, p.leverage, self.roe, round_trip=self.s.round_trip_cost)
            else:
                p.tp_price = p.signal.meta["ref_price"] + p.side * self.m * p.signal.meta["stop_dist"]
        return ok


class UserLadder(PaperEngine):
    """The owners' stepped lock (``ULAD``): the engine's own ``_raise_lock`` with ``user_lock_for`` in place of the rule bot's ``LadderSpec``;
    the stop, fills, fees and the rest are the plain engine's, and no take-profit."""

    def _raise_lock(self, p) -> None:
        fund = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
        rt = self.s.round_trip_cost
        best = net_roe(p.side, p.entry_price, p.mfe_price, p.leverage, rt, fund)
        lock = user_lock_for(best)
        if lock is None or (p.lock_roe is not None and lock <= p.lock_roe + 1e-12):
            return
        p.stop_price = tighten(p.side, p.stop_price, roe_price(p.side, p.entry_price, p.leverage, lock, rt, fund))
        p.lock_roe = lock


EQUITY_ENV = "CANDLEAGUE_EQUITY"


def start_equity() -> float:
    """The paper wallet every account of the league starts with: the environment's ``CANDLEAGUE_EQUITY`` (the owners' new league: 1000), else the
    paper bot's $5,000 (``paperbot.config.V3_INITIAL``; the old league, the study and the tests). A value that is not a positive number is an error,
    never a silent default."""
    raw = (os.environ.get(EQUITY_ENV) or "").strip()
    if not raw:
        return V3_INITIAL
    try:
        v = float(raw)
    except ValueError:
        raise ValueError(f"{EQUITY_ENV}={raw!r} is not a number") from None
    if not (math.isfinite(v) and v > 0):
        raise ValueError(f"{EQUITY_ENV}={raw!r} must be a positive number")
    return v


MIN_LEV_ENV = "CANDLEAGUE_MIN_LEV"


def min_leverage() -> Optional[int]:
    """The lowest leverage the league may pick: the environment's ``CANDLEAGUE_MIN_LEV`` (the owners' new league, 2026-10-13: 30, so the
    ladder is 50 -> 40 -> 30 and a signal whose stop does not fit at 30x is not entered), else None (the paper bot's own 50/40/30/20).
    A value that is not a whole number from 1 to 50 is an error, never a silent default."""
    raw = (os.environ.get(MIN_LEV_ENV) or "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except ValueError:
        raise ValueError(f"{MIN_LEV_ENV}={raw!r} is not a whole number") from None
    if not 1 <= v <= 50:
        raise ValueError(f"{MIN_LEV_ENV}={raw!r} must be from 1 to 50")
    return v


def settings_for(name: str, size: float = 1.0, **kw):
    """The v4 settings with this exit's lock and take-profit mode (``kw``: other v3_settings overrides). ``size``
    multiplies every tier's margin fraction (leverages kept, as research/fullgrid/sizing.py's size_vector)."""
    s = spec(name)
    kw = {**kw, "ladder_first_lock": s["first_lock"], "ladder_step": s["step"], "ladder_trigger_gap": s["gap"]}
    kw.setdefault("initial_equity", start_equity())
    lev_min = min_leverage()
    if lev_min is not None and "tiers" not in kw:             # the owners' league: no leverage below the floor (a tier with none left is dropped)
        from paperbot.config import V3_QUALITY_TIERS, Tier
        kept = tuple(Tier(t.name, t.margin_frac, tuple(v for v in t.leverages if v >= lev_min)) for t in V3_QUALITY_TIERS)
        kw["tiers"] = tuple(t for t in kept if t.leverages)
    if size != 1.0:
        from paperbot.config import V3_QUALITY_TIERS, Tier
        tiers = tuple(Tier(t.name, round(t.margin_frac * size, 6), t.leverages) for t in (kw.get("tiers") or V3_QUALITY_TIERS))
        kw.update(tiers=tiers, min_margin_frac=min(t.margin_frac for t in tiers),
                  max_margin_frac=max(0.50, max(t.margin_frac for t in tiers)))
    if not s["ladder"]:
        kw["tp_mode"] = "fixed"
        if s["tp_kind"] == TP_ROE:
            kw["default_tp_roe"] = s["tp_val"]
    return v3_settings(**kw)


def make_engine(name: str, brackets: dict, specs: dict, book=None, size: float = 1.0, **kw) -> PaperEngine:
    """A paper account that exits by rule ``name`` (signals must carry meta stop_dist = stop_dist(name, atr), and
    tp_struct for a structure rule); ``size`` scales the margin fractions (settings_for)."""
    s, st = spec(name), settings_for(name, size=size, **kw)
    extra = {} if book is None else {"book": book}
    if name.startswith(ULAD + "|"):
        return UserLadder(st, brackets, symbol_specs=specs, **extra)
    if s["ladder"] and s["tp_kind"] == TP_STRUCT:
        return LadderTP(st, brackets, symbol_specs=specs, struct=True, **extra)
    if s["ladder"] and s["tp_kind"] == TP_R:
        return LadderTP(st, brackets, symbol_specs=specs, m=s["tp_val"], **extra)
    if s["ladder"] and s["tp_kind"] == TP_ROE:                       # F13: the lock plus the pick's net-ROE take-profit
        return LadderTP(st, brackets, symbol_specs=specs, roe=s["tp_val"], **extra)
    if s["ladder"] or s["tp_kind"] == TP_ROE:
        return PaperEngine(st, brackets, symbol_specs=specs, **extra)
    return PaperEngine(st, brackets, symbol_specs=specs, policy=RPolicy(st, s["tp_val"]), **extra)
