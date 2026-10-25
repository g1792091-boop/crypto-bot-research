"""Trade simulator of the V3.9 1h study: paperbot.engine.PaperEngine's rules for one position on 1-minute (or coarser)
bars, compiled with numba, with the exit / entry / leverage variants the owners asked about.

It follows research/fullgrid/kernel.py ``_trade`` (itself checked trade-for-trade against PaperEngine) and adds:
- a trailing stop at the best price -/+ k x ATR (the signal's 1h ATR14), switched on once the best net ROE reaches a
  start level (no equivalent in the bot; ``TrailEngine`` below is the PaperEngine twin used for the parity check);
- a forced leverage / margin share (no safety checks: the stop may sit beyond liquidation, which then liquidates);
- the fill price and entry minute chosen by the caller (the paper trade's own ref_price, or a delayed market entry).

Exact PaperEngine semantics kept (engine.py): funding first on the bar's mark open (not on the entry bar); the entry
bar is checked for stop and liquidation on its whole range but gets no gap check and no lock / trail step (ref_price
fill); later bars: mark open beyond liquidation liquidates, open beyond the stop exits at the open with slippage, a
fixed take-profit gapped through exits at the open (maker); then a low/high through the stop exits at the stop with
slippage (the stop wins a bar that also touches the take-profit), a mark low/high through liquidation liquidates, a
take-profit traded through exits at it (maker fee); otherwise the lock / trail steps up from the next bar. A close whose
loss exceeds the isolated margin is a liquidation. Nothing here trades: research code, reads arrays only.
"""
from __future__ import annotations

import math

import numpy as np
from numba import njit

R_NONE, R_SL, R_LOCK, R_LIQ, R_OPEN, R_REJECT, R_TP = 0, 1, 2, 3, 4, 5, 6
REASON = {R_SL: "SL", R_LOCK: "LOCK", R_LIQ: "LIQ", R_OPEN: "OPEN", R_REJECT: "REJECTED", R_TP: "TP"}
TP_NONE, TP_R, TP_ROE = 0, 1, 2


def settings_vector(s) -> np.ndarray:
    """The paperbot Settings numbers the kernel uses (quality_v1 tiers: best 50/50, 40/40; normal 30/30, 20/20)."""
    best = [(t.margin_frac, lev) for t in s.tiers if t.name == "best" for lev in t.leverages]
    normal = [(t.margin_frac, lev) for t in s.tiers if t.name == "normal" for lev in t.leverages]
    assert s.leverage_rule == "quality_v1" and len(best) == 2 and len(normal) == 2 and s.best_falls_to_normal
    assert s.stop_first_on_ambiguous_bar
    return np.array([s.taker_fee, s.slippage_frac, s.max_loss_frac, s.liq_buffer_atr_mult, s.liq_buffer_min_frac,
                     s.round_trip_cost, s.bust_below, s.maker_fee,
                     best[0][0], best[0][1], best[1][0], best[1][1], normal[0][0], normal[0][1], normal[1][0],
                     normal[1][1]], float)


def bracket_array(br) -> np.ndarray:
    return np.array([[t.notional_cap, t.max_leverage, t.mmr, t.cum] for t in br.tiers], float)


@njit(cache=False)
def _round_down(x, step):
    if step <= 0:
        return x
    return math.floor(x / step + 1e-9) * step


@njit(cache=False)
def _bracket(br, notional):
    for k in range(br.shape[0]):
        if notional <= br[k, 0]:
            return k
    return br.shape[0] - 1


@njit(cache=False)
def _liq(side, qty, entry, margin, mmr, cum):
    lp = (margin + cum - side * qty * entry) / (qty * mmr - side * qty)
    return lp if lp > 0.0 else 0.0


@njit(cache=False)
def size_rule(S, br, equity, side, fill, stop, atr, best, qty_step, min_notional):
    """sizing.size_position under quality_v1 -> (ok, leverage, margin, qty, liq)."""
    if equity <= 0 or (fill - stop) * side <= 0:
        return False, 0, 0.0, 0.0, 0.0
    taker, slip, max_loss, buf_atr, buf_min = S[0], S[1], S[2], S[3], S[4]
    buffer = max(buf_min * fill, buf_atr * atr)
    stop_dist = abs(fill - stop)
    first = 0 if best else 2
    for c in range(first, 4):
        frac, lev = S[8 + 2 * c], int(S[9 + 2 * c])
        qty = _round_down(equity * frac * lev / fill, qty_step)
        notional = qty * fill
        if qty <= 0 or notional < min_notional:
            continue
        margin = notional / lev
        k = _bracket(br, notional)
        if lev > br[k, 1]:
            continue
        liq = _liq(side, qty, fill, margin, br[k, 2], br[k, 3])
        if (stop - liq) * side < buffer:
            continue
        exit_px = stop * (1 - side * slip)
        loss = qty * stop_dist + qty * abs(stop - exit_px) + notional * taker + qty * exit_px * taker
        if loss > max_loss * equity:
            continue
        return True, lev, margin, qty, liq
    return False, 0, 0.0, 0.0, 0.0


@njit(cache=False)
def trade(S, br, o, h, l, mo, mh, ml, fund, e, end, raw, side, stop_dist, atr, best, equity, qty_step, min_notional,
          force_lev, force_frac, tp_kind, tp_val, ladder, first_lock, step, gap, trail_k, trail_start):
    """One position filled in bar ``e`` at ``raw`` (+ slippage), until an exit or bar ``end`` (exclusive).
    Sizing: the rule (force_lev <= 0) or a forced leverage and margin share. Returns
    (wallet change, exit bar, reason, leverage, margin, qty, fill, liq, stop_initial, best price, worst price,
    exit price, final lock ROE (-1 none), exit at the bar open)."""
    taker, slip, rt, maker = S[0], S[1], S[5], S[7]
    fill = raw * (1 + side * slip)
    stop = raw - side * stop_dist
    if force_lev > 0:
        qty = _round_down(equity * force_frac * force_lev / fill, qty_step)
        if qty <= 0 or qty * fill < min_notional:
            return 0.0, e, R_REJECT, 0, 0.0, 0.0, fill, 0.0, stop, fill, fill, 0.0, -1.0, False
        lev = int(force_lev)
        margin = qty * fill / lev
        kb0 = _bracket(br, qty * fill)
        liq = _liq(side, qty, fill, margin, br[kb0, 2], br[kb0, 3])
    else:
        ok, lev, margin, qty, liq = size_rule(S, br, equity, side, fill, stop, atr, best, qty_step, min_notional)
        if not ok:
            return 0.0, e, R_REJECT, 0, 0.0, 0.0, fill, 0.0, stop, fill, fill, 0.0, -1.0, False
    stop0 = stop
    has_tp = tp_kind != TP_NONE
    if tp_kind == TP_R:
        tp = raw + side * tp_val * stop_dist
    else:
        tp = fill * (1.0 + side * (tp_val / lev + rt))
    notional = qty * fill
    wallet = equity - notional * taker
    fpaid = 0.0
    mfe = fill
    mae = fill
    lock_roe = -1.0
    moved = False
    kb = _bracket(br, notional)
    for j in range(e, end):
        entry_bar = j == e
        if not entry_bar and fund[j] != 0.0:
            pay = side * qty * mo[j] * fund[j]
            wallet -= pay
            margin -= pay
            fpaid += pay
            liq = _liq(side, qty, fill, margin, br[kb, 2], br[kb, 3])
        if side > 0:
            if h[j] > mfe:
                mfe = h[j]
            if l[j] < mae:
                mae = l[j]
        else:
            if l[j] < mfe:
                mfe = l[j]
            if h[j] > mae:
                mae = h[j]
        price = -1.0
        liquidate = False
        at_tp = False
        at_open = False
        if not entry_bar:
            if (mo[j] - liq) * side <= 0:
                liquidate = True
                at_open = True
            elif (o[j] - stop) * side <= 0:
                price = o[j] * (1 - side * slip)
                at_open = True
            elif has_tp and (o[j] - tp) * side > 0:
                price = o[j]
                at_tp = True
                at_open = True
        if not liquidate and price < 0:
            hit_stop = (l[j] <= stop) if side > 0 else (h[j] >= stop)
            hit_tp = has_tp and ((h[j] > tp) if side > 0 else (l[j] < tp))
            hit_liq = (ml[j] <= liq) if side > 0 else (mh[j] >= liq)
            if hit_stop:
                price = stop * (1 - side * slip)
            elif hit_liq:
                liquidate = True
            elif hit_tp:
                price = tp
                at_tp = True
            elif not entry_bar:
                fr = fpaid / notional
                bst = lev * (side * (mfe / fill - 1.0) - rt - fr)
                if ladder:
                    ft = first_lock + gap
                    if bst >= ft - 1e-12:
                        n = math.floor((bst - ft) / step + 1e-9)
                        lk = first_lock + step * n
                        if lock_roe < 0 or lk > lock_roe + 1e-12:
                            cand = fill * (1.0 + side * (lk / lev + rt + fr))
                            if side > 0:
                                stop = max(stop, cand)
                            else:
                                stop = min(stop, cand)
                            lock_roe = lk
                            moved = True
                if trail_k > 0 and bst >= trail_start - 1e-12:
                    cand = mfe - side * trail_k * atr
                    if (cand - stop) * side > 0:
                        stop = cand
                        moved = True
        if price >= 0:
            gross = side * qty * (price - fill)
            if gross < -margin:
                liquidate = True
            else:
                wallet += gross - qty * price * (maker if at_tp else taker)
                r = R_TP if at_tp else (R_LOCK if moved else R_SL)
                return wallet - equity, j, r, lev, margin, qty, fill, liq, stop0, mfe, mae, price, lock_roe, at_open
        if liquidate:
            wallet -= margin
            return wallet - equity, j, R_LIQ, lev, margin, qty, fill, liq, stop0, mfe, mae, liq, lock_roe, at_open
    return wallet - equity, end - 1, R_OPEN, lev, margin, qty, fill, liq, stop0, mfe, mae, -1.0, lock_roe, False


class Variant:
    """An exit / sizing variant. Fields (all optional): stop_atr (2.0), tp ('none' | 'R' | 'ROE'), tp_val, ladder
    (True), first_lock (0.10), step (0.05), gap (0.02), trail_k (0 = none), trail_start (net ROE at which the trail
    switches on), lev_btc / lev_alt / frac (forced leverage per coin group and margin share; frac None = margin share
    equal to leverage %), same_lev (keep the paper trade's leverage and margin share)."""

    def __init__(self, name: str, label: str = "", **kw):
        self.name, self.label = name, label or name
        self.stop_atr = kw.pop("stop_atr", 2.0)
        self.tp = kw.pop("tp", "none")
        self.tp_val = kw.pop("tp_val", 0.0)
        self.ladder = kw.pop("ladder", True)
        self.first_lock = kw.pop("first_lock", 0.10)
        self.step = kw.pop("step", 0.05)
        self.gap = kw.pop("gap", 0.02)
        self.trail_k = kw.pop("trail_k", 0.0)
        self.trail_start = kw.pop("trail_start", 0.12)
        self.lev_btc = kw.pop("lev_btc", 0)
        self.lev_alt = kw.pop("lev_alt", 0)
        self.frac = kw.pop("frac", None)
        self.same_lev = kw.pop("same_lev", False)
        if kw:
            raise ValueError(f"unknown variant fields {sorted(kw)}")

    def tp_kind(self) -> int:
        return {"none": TP_NONE, "R": TP_R, "ROE": TP_ROE}[self.tp]

    def forced(self, symbol: str, paper_lev: int = 0, paper_frac: float = 0.0) -> tuple[int, float]:
        if self.same_lev:
            return int(paper_lev), float(paper_frac if self.frac is None else self.frac)
        lev = self.lev_btc if symbol == "BTCUSDT" else self.lev_alt
        if lev <= 0:
            return 0, 0.0
        return int(lev), (lev / 100.0 if self.frac is None else float(self.frac))

    def args(self) -> tuple:
        return (self.tp_kind(), float(self.tp_val), bool(self.ladder), float(self.first_lock), float(self.step),
                float(self.gap), float(self.trail_k), float(self.trail_start))


def run_one(S, br, A: dict, e: int, raw: float, side: int, atr: float, best: bool, equity: float, spec: dict,
            v: Variant, symbol: str, paper_lev: int = 0, paper_frac: float = 0.0, end: int | None = None,
            bar_ms: int = 60_000) -> dict:
    """One trade of variant ``v`` on symbol arrays ``A`` (ts, o, h, l, mo, mh, ml, fund) from bar ``e``."""
    fl, ff = v.forced(symbol, paper_lev, paper_frac)
    n = len(A["ts"]) if end is None else end
    res = trade(S, br, A["o"], A["h"], A["l"], A["mo"], A["mh"], A["ml"], A["fund"], int(e), int(n), float(raw),
                int(side), float(v.stop_atr * atr), float(atr), bool(best), float(equity), float(spec["qty_step"]),
                float(spec["min_notional"]), int(fl), float(ff), *v.args())
    keys = ("pnl", "j", "reason", "lev", "margin", "qty", "fill", "liq", "stop0", "best_px", "worst_px", "exit_px",
            "lock_roe", "at_open")
    out = dict(zip(keys, res))
    out["reason"] = REASON.get(int(out["reason"]), "?")
    out["entry_ts"] = int(A["ts"][e])
    # the engine's exit time: the bar open for an exit at the open, else the bar's close time (open + 59,999 ms on 1m)
    tj = int(A["ts"][int(out["j"])])
    out["exit_ts"] = tj if out["at_open"] else tj + bar_ms - 1
    if out["reason"] == "OPEN":
        # still open at the data end: marked to the last close as a market exit (slippage and taker fee included)
        c = float(A["c"][int(out["j"])])
        px = c * (1 - side * S[1])
        out["pnl"] += side * out["qty"] * (px - out["fill"]) - out["qty"] * px * S[0]
        out["exit_px"] = px
    out["roe"] = out["pnl"] / out["margin"] if out["margin"] else np.nan
    out["ret"] = out["pnl"] / equity
    return out
