"""Vectorised equivalent of sim_modes.simulate (PESS/DET/OPT). Validated against the loop version."""
import numpy as np
from engine import ladder_lock

def _stops(peakarr, entry, side, sl_px, cfg, atr_e):
    if cfg.mode == "TRAIL":
        tr = peakarr - side * cfg.trail_atr * atr_e
        return np.maximum(sl_px, tr) if side > 0 else np.minimum(sl_px, tr)
    roe = side * (peakarr / entry - 1.0) * 100.0 * cfg.lev
    lk = ladder_lock(roe, cfg)
    lp = entry * (1.0 + side * lk / 100.0 / cfg.lev)
    return np.where(np.isfinite(lk), np.maximum(sl_px, lp) if side > 0 else np.minimum(sl_px, lp), sl_px)

def simulate(side, e, o, h, l, c, atr_e, cfg, cost, n, mode="PESS"):
    entry = o[e] * (1.0 + side * cost.slip_side)
    last = min(n - 1, e + cost.max_hold - 1)
    oo, hh, ll, cc = o[e:last + 1], h[e:last + 1], l[e:last + 1], c[e:last + 1]
    m = len(oo)
    sl_dist = cfg.sl_roe / 100.0 / cfg.lev if cfg.mode == "LADDER" else cfg.sl_atr * atr_e / entry
    sl_px = entry * (1.0 - side * sl_dist)
    adv = ll if side > 0 else hh
    fav = hh if side > 0 else ll
    W = (lambda a, b: a <= b) if side > 0 else (lambda a, b: a >= b)
    jx = None; exit_px = None; reason = None
    if cfg.mode == "FIXED":
        tp_px = entry * (1.0 + side * cfg.tp_atr * atr_e / entry)
        hs = W(adv, sl_px); ht = (fav >= tp_px) if side > 0 else (fav <= tp_px)
        anyh = hs | ht
        if anyh.any():
            j = int(np.argmax(anyh))
            take_sl = hs[j] and (not ht[j] or mode != "OPT" or W(oo[j], sl_px))
            if take_sl:
                fill = min(oo[j], sl_px) if side > 0 else max(oo[j], sl_px)
                exit_px = fill * (1.0 - side * cost.slip_side); reason = "SL"
            else:
                fill = max(oo[j], tp_px) if side > 0 else min(oo[j], tp_px)
                exit_px = fill; reason = "TP"
            jx = j
    else:
        peak = np.maximum.accumulate(fav) if side > 0 else np.minimum.accumulate(fav)
        peak_prev = np.concatenate([[entry], peak[:-1]])
        peak_cur = np.maximum(peak, entry) if side > 0 else np.minimum(peak, entry)
        S_prev = _stops(peak_prev, entry, side, sl_px, cfg, atr_e)
        S_cur = _stops(peak_cur, entry, side, sl_px, cfg, atr_e)
        if mode == "PESS":
            hit = W(adv, S_prev)
            if hit.any():
                j = int(np.argmax(hit)); st = S_prev[j]
                fill = min(oo[j], st) if side > 0 else max(oo[j], st)
                exit_px = fill * (1.0 - side * cost.slip_side); jx = j
        elif mode == "OPT":
            hit = W(adv, S_cur)
            if hit.any():
                j = int(np.argmax(hit))
                if W(oo[j], S_prev[j]):
                    st = S_prev[j]; fill = oo[j]
                else:
                    st = S_cur[j]; fill = st
                exit_px = fill * (1.0 - side * cost.slip_side); jx = j
        elif mode == "DET":
            hp = W(adv, S_prev)
            hd = (S_cur != S_prev) & W(cc, S_cur)
            hit = hp | hd
            if hit.any():
                j = int(np.argmax(hit))
                if hp[j]:
                    st = S_prev[j]; fill = min(oo[j], st) if side > 0 else max(oo[j], st)
                else:
                    st = S_cur[j]; fill = st
                exit_px = fill * (1.0 - side * cost.slip_side); jx = j
        if jx is not None:
            reason = "SL" if abs(st - sl_px) < 1e-12 else ("LOCK" if cfg.mode == "LADDER" else "TRAIL")
    if jx is None:
        jx = m - 1; reason = "TIME" if last < n - 1 else "EOD"
        exit_px = cc[jx] * (1.0 - side * cost.slip_side)
    hold = jx + 1
    sa = adv[:jx + 1]; sf = fav[:jx + 1]
    mae = side * ((sa.min() if side > 0 else sa.max()) / entry - 1.0)
    mfe = side * ((sf.max() if side > 0 else sf.min()) / entry - 1.0)
    gross = side * (exit_px / entry - 1.0)
    fee = 2.0 * cost.fee_side
    funding = cost.funding_8h * (hold * cost.bar_minutes / 480.0)
    return dict(side=side, entry_idx=e, exit_idx=e + jx, entry_px=entry, exit_px=exit_px, gross=gross, fee=fee,
                funding=funding, net=gross - fee - funding, mae=mae, mfe=mfe, reason=reason, hold=hold, sl_dist=sl_dist)
