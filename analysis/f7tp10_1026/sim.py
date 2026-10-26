"""The position engine of this study, on 5-minute bars (owners' rule: 1-minute bars only for 20-day windows).

Two exit families, both with the paper bots' costs (taker 0.05 % + slippage 0.02 % a side; a take-profit limit fills
at its price with the maker fee 0.02 %, as the league's fills show: every TP trade at 30x closed at +12.1 % net ROE):

  "tp10"   the league account's exit (candleague/exits.py roe10 with stop_max 2): stop = reference price -/+ 2 x ATR(1h),
           take-profit at net ROE +10 % (paperbot.sizing.tp_from_roe on the fill and the leverage, round trip 0.14 %).
  "trend"  the 추세판단 봇's exit (deploy/combo.trend.json): stop at net ROE -50 %, the two-part ladder (paperbot.ladder2:
           10 % at 11 %, 12 % at 15 %, then every 5 %: reached - 3), a new lock from the next bar, no lock on the entry bar;
           before the first lock: JUDGE (a 4h bar closed after the entry judged the other way, 3 of 4) and REV (the
           member's own opposite signal on the same coin) close at the next bar's open.

Inside a bar: open gap first, then the stop before any take-profit or lock (the engine's order). Funding on the
notional at each settlement held over. Net ROE = net P&L / margin."""
from __future__ import annotations

import math

import numpy as np

TAKER, MAKER, SLIP = 0.0005, 0.0002, 0.0002
RT = 2 * (TAKER + SLIP)                       # 0.14 %: the round trip tp_from_roe and roe_price are given
FIVE = 300_000


def ladder_lock(best: float) -> float | None:
    """paperbot.ladder2.ComboLadder(0.10, 0.05, 0.01, 0.15, 0.03).lock_for (checked in check_ladder)."""
    if best < 0.11 - 1e-12:
        return None
    if best < 0.15 - 1e-12:
        return 0.10
    n = math.floor((best - 0.15) / 0.05 + 1e-9)
    return 0.12 + 0.05 * n


def check_ladder() -> None:
    from paperbot.ladder2 import ComboLadder
    lad = ComboLadder(0.10, 0.05, 0.01, 0.15, 0.03)
    for b in np.linspace(-0.6, 1.5, 4201):
        a, w = ladder_lock(float(b)), lad.lock_for(float(b))
        assert (a is None and w is None) or (a is not None and w is not None and abs(a - w) < 1e-9), (b, a, w)


def lad_lock(best: float, lad: tuple) -> float | None:
    """A stepped lock (owners 10/26 "12%도달하면 10% 계단식"): ``lad`` = (first trigger, first lock, step, gap): the first lock
    once the best net ROE reaches the first trigger, then every ``step`` more a lock ``gap`` under the reached trigger
    ((0.12, 0.10, 0.05, 0.02): 12 -> 10, 17 -> 15, 22 -> 20 ...)."""
    ft, fl, step, gap = lad
    if best < ft - 1e-12:
        return None
    n = math.floor((best - ft) / step + 1e-9)
    return fl if n == 0 else ft + step * n - gap


def run_position(m: dict, i0: int, side: int, lev: float, ref: float, exit_kind: str, stop_dist: float = 0.0,
                 sup_at: int | None = None, tp_roe: float = 0.10, lad: tuple | None = None) -> dict:
    """One position. ``m``: the coin's 5m arrays (ts o h l c fund). ``i0``: the 5m bar whose open is the fill.
    ``sup_at``: the first 5m bar index at whose open a JUDGE / REV exit would close (trend exit, before the first lock).
    Returns {exit_i, reason, roe, mfe (best net ROE seen), fill, exit_px}."""
    o, h, l, c, fund = m["o"], m["h"], m["l"], m["c"], m["fund"]
    n = len(o)
    fill = o[i0] * (1 + side * SLIP)
    fee_in = TAKER
    f_paid = 0.0                                   # funding paid, fraction of the entry notional
    if exit_kind == "tp10":
        stop = ref - side * stop_dist
        tp = fill * (1 + side * (tp_roe / lev + RT))
    elif exit_kind in ("lad", "trendlad"):              # the league's ATR stop, no take-profit, a stepped lock
        stop = ref - side * stop_dist
        tp = None
    else:
        stop = fill * (1 + side * (-0.50 / lev + RT))
        tp = None
    lock = None
    best = -9.0

    def roe_at(px: float, fee_out: float, slip: bool) -> float:
        xp = px * (1 - side * SLIP) if slip else px
        return lev * (side * (xp / fill - 1) - fee_in - fee_out * xp / fill - f_paid), xp

    i = i0
    while i < n:
        if i > i0 and fund[i] != 0.0:
            f_paid += side * fund[i] * o[i] / fill
            if exit_kind == "trend" and lock is None:      # roe_price with the funding paid (the engine's stop moves)
                stop = fill * (1 + side * (-0.50 / lev + RT + f_paid))
        if exit_kind == "trend" and sup_at is not None and i >= sup_at and lock is None and i > i0:
            r, xp = roe_at(o[i], TAKER, True)
            return {"exit_i": i, "reason": "SUP", "roe": r, "mfe": best, "fill": fill, "exit_px": xp}
        # open gap through the stop
        if (o[i] - stop) * side <= 0:
            r, xp = roe_at(o[i], TAKER, True)
            return {"exit_i": i, "reason": "SL" if lock is None else "LOCK", "roe": r, "mfe": max(best, r), "fill": fill,
                    "exit_px": xp}
        worst, top = (l[i], h[i]) if side > 0 else (h[i], l[i])
        if (worst - stop) * side <= 0:
            r, xp = roe_at(stop, TAKER, True)
            return {"exit_i": i, "reason": "SL" if lock is None else "LOCK", "roe": r, "mfe": best, "fill": fill,
                    "exit_px": xp}
        b = lev * (side * (top / fill - 1) - RT - f_paid)
        best = max(best, b)
        if tp is not None and (top - tp) * side >= 0:
            px = max(tp, o[i]) if side > 0 else min(tp, o[i])
            r, xp = roe_at(px, MAKER, False)
            return {"exit_i": i, "reason": "TP", "roe": r, "mfe": best, "fill": fill, "exit_px": xp}
        if exit_kind in ("trend", "trendlad", "lad") and i > i0:
            k = lad_lock(best, lad) if exit_kind == "lad" else ladder_lock(best)
            if k is not None and (lock is None or k > lock + 1e-12):
                cand = fill * (1 + side * (k / lev + RT + f_paid))
                stop = max(stop, cand) if side > 0 else min(stop, cand)
                lock = k
        i += 1
    r, xp = roe_at(c[n - 1], TAKER, True)
    return {"exit_i": n - 1, "reason": "END", "roe": r, "mfe": best, "fill": fill, "exit_px": xp}
