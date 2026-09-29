"""Per-trade exit simulator with three intrabar-path assumptions.

PESS : identical to bt/engine.py::_simulate_one (adverse extreme first; stop raised by a bar only
       from the NEXT bar; SL before TP on the same bar).  Validated to reproduce the engine exactly.
DET  : PESS, plus the one case a finer path cannot dispute: if bar j's favourable extreme raises the
       stop to S' (> old stop S), bar j's adverse extreme does NOT reach S, and bar j CLOSES beyond S',
       then the price necessarily crossed S' after the extreme -> exit at S' (stop-market, - slippage).
       (The engine instead exits at the next bar's open, i.e. ~close_j, which is worse.)
OPT  : favourable extreme first inside every bar: the stop is raised by the bar's own extreme
       before the adverse extreme is tested; TP before SL for FIXED.  Best-case path.
For a 1-minute bar series, OPT - PESS bounds what any sub-minute (tick) path can change,
given the same prices and the same stop rules.
"""
import numpy as np
from engine import ladder_lock

def _stop_from_peak(peak, entry, side, sl_px, cfg, atr_e):
    if cfg.mode == "TRAIL":
        tr = peak - side * cfg.trail_atr * atr_e
        return max(sl_px, tr) if side > 0 else min(sl_px, tr)
    if cfg.mode == "LADDER":
        roe = side * (peak / entry - 1.0) * 100.0 * cfg.lev
        lk = ladder_lock(np.array([roe]), cfg)[0]
        if not np.isfinite(lk):
            return sl_px
        lp = entry * (1.0 + side * lk / 100.0 / cfg.lev)
        return max(sl_px, lp) if side > 0 else min(sl_px, lp)
    raise ValueError(cfg.mode)

def simulate(side, e, o, h, l, c, atr_e, cfg, cost, n, mode="PESS"):
    entry = o[e] * (1.0 + side * cost.slip_side)
    last = min(n - 1, e + cost.max_hold - 1)
    sl_dist = cfg.sl_roe / 100.0 / cfg.lev if cfg.mode == "LADDER" else cfg.sl_atr * atr_e / entry
    sl_px = entry * (1.0 - side * sl_dist)
    adv = l if side > 0 else h
    fav = h if side > 0 else l
    worse = (lambda a, b: a <= b) if side > 0 else (lambda a, b: a >= b)   # a at/through b adversely
    exit_px = None; reason = None; jx = None
    if cfg.mode == "FIXED":
        tp_px = entry * (1.0 + side * cfg.tp_atr * atr_e / entry)
        for j in range(e, last + 1):
            hs = worse(adv[j], sl_px)
            ht = (fav[j] >= tp_px) if side > 0 else (fav[j] <= tp_px)
            if hs or ht:
                if hs and ht:
                    # open beyond SL is a gap: SL regardless of mode
                    take_sl = (mode != "OPT") or worse(o[j], sl_px)
                else:
                    take_sl = hs
                if take_sl:
                    fill = min(o[j], sl_px) if side > 0 else max(o[j], sl_px)
                    exit_px = fill * (1.0 - side * cost.slip_side); reason = "SL"
                else:
                    fill = max(o[j], tp_px) if side > 0 else min(o[j], tp_px)
                    exit_px = fill; reason = "TP"
                jx = j; break
    else:
        peak = entry
        for j in range(e, last + 1):
            S = _stop_from_peak(peak, entry, side, sl_px, cfg, atr_e)
            if mode == "OPT":
                if worse(o[j], S):                       # gap through the standing stop at the open
                    exit_px = o[j] * (1.0 - side * cost.slip_side); st = S; jx = j; break
                peak2 = max(peak, fav[j]) if side > 0 else min(peak, fav[j])
                S2 = _stop_from_peak(peak2, entry, side, sl_px, cfg, atr_e)
                if worse(adv[j], S2):
                    exit_px = S2 * (1.0 - side * cost.slip_side); st = S2; jx = j; break
                peak = peak2
            else:
                if worse(adv[j], S):
                    fill = min(o[j], S) if side > 0 else max(o[j], S)
                    exit_px = fill * (1.0 - side * cost.slip_side); st = S; jx = j; break
                peak2 = max(peak, fav[j]) if side > 0 else min(peak, fav[j])
                if mode == "DET":
                    S2 = _stop_from_peak(peak2, entry, side, sl_px, cfg, atr_e)
                    if S2 != S and worse(c[j], S2):
                        exit_px = S2 * (1.0 - side * cost.slip_side); st = S2; jx = j; break
                peak = peak2
        if jx is not None:
            reason = "SL" if abs(st - sl_px) < 1e-12 else ("LOCK" if cfg.mode == "LADDER" else "TRAIL")
    if jx is None:
        jx = last; reason = "TIME" if last < n - 1 else "EOD"
        exit_px = c[jx] * (1.0 - side * cost.slip_side)
    k = jx - e
    hold = k + 1
    seg_a = adv[e:jx + 1]; seg_f = fav[e:jx + 1]
    mae = side * ((seg_a.min() if side > 0 else seg_a.max()) / entry - 1.0)
    mfe = side * ((seg_f.max() if side > 0 else seg_f.min()) / entry - 1.0)
    gross = side * (exit_px / entry - 1.0)
    fee = 2.0 * cost.fee_side
    funding = cost.funding_8h * (hold * cost.bar_minutes / 480.0)
    return dict(side=side, entry_idx=e, exit_idx=jx, entry_px=entry, exit_px=exit_px, gross=gross, fee=fee,
                funding=funding, net=gross - fee - funding, mae=mae, mfe=mfe, reason=reason, hold=hold, sl_dist=sl_dist)
