"""Exit simulations on 15m bars, copied from the 5-year study (research/st_custom/common.py, itself a copy of
analysis/rulebot_1007/pending_1007_night/lens2_multi_tf_done/precompute.py), so the live ranking computes exactly what
the study computed:

* ``scan`` / ``run_scan``: the house exit (2 x ATR14 stop + the paperbot ladder) at a given leverage, taker +
  slippage both sides, funding per 15m bar, optional liquidation touch (accounts).
* ``tpsl_outcomes``: fixed take-profit / stop pairs (no ladder); here it also returns the exit bar index.
* ``sizer`` / ``lev_liq``: the rule bot's sizer at the study's 5,000 USD equity (leverage 30x, else 20x) used for the
  ranking's house exit, as in the study.
* ``entry_check``: the rule bot's entry checks for the owners' sizing (margin = L% of the wallet), as the study's
  account simulation ('house' mode).

Only open/high/low/close numpy arrays of 15m bars go in; nothing here touches the network or the database.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from paperbot.config import v3_settings  # noqa: E402
from paperbot.ladder import LadderSpec  # noqa: E402
from paperbot.margin import BracketTier, Brackets, liquidation_price  # noqa: E402
from paperbot.sizing import size_position  # noqa: E402

from . import grid as G  # noqa: E402

S = v3_settings()
LAD = LadderSpec(S.ladder_first_lock, S.ladder_step, S.ladder_trigger_gap)
K_STOP = 2.0
FUNDING_8H = 0.0001
F_BAR15 = FUNDING_8H * 15 / 480.0
TAKER, SLIP, MAKER = S.taker_fee, S.slippage_frac, S.maker_fee
EQUITY_SIZER = 5000.0
# copied from lens2_multi_tf_done/precompute.py via research/st_custom/common.py (fit to live trades' liquidation
# prices); XRP was never traded live: DOGE's table (study DEVIATIONS D3)
INFERRED_BRACKETS = {
    "BTCUSD": [(1e12, 50, 0.004, 0.0)],
    "ETHUSD": [(1e12, 50, 0.004, 0.0)],
    "SOLUSD": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGEUSD": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCHUSD": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTCUSD": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)],
}
INFERRED_BRACKETS["XRPUSD"] = INFERRED_BRACKETS["DOGEUSD"]
BR = {c: Brackets([BracketTier(*t) for t in v]) for c, v in INFERRED_BRACKETS.items()}
# Binance minimum order (quantity step, minimum notional USD): research/st_custom/s6_accounts.MINORDER (assumed values)
MINORDER = {"BTCUSD": (0.001, 100.0), "ETHUSD": (0.001, 20.0), "SOLUSD": (1.0, 5.0), "DOGEUSD": (1.0, 5.0),
            "LTCUSD": (0.001, 20.0), "BCHUSD": (0.001, 20.0), "XRPUSD": (0.1, 5.0)}
PASSES = (96, 768, 6144, 49152)


# ------------------------------------------------------------------ sizer (study: precompute.sizer)
_SZ: dict = {}


def sizer(coin: str, k_stop: float = K_STOP):
    key0 = (coin, k_stop)
    if key0 not in _SZ:
        _SZ[key0] = {}
    cache = _SZ[key0]

    def f(side, atr_frac):
        key = (side, float(f"{atr_frac:.4g}"))
        if key not in cache:
            raw = 100.0
            a = key[1] * raw
            fill = raw * (1 + side * S.slippage_frac)
            d = size_position(S, EQUITY_SIZER, side, fill, raw - side * k_stop * a, "normal", BR[coin], atr=a,
                              min_notional=5.0)
            cache[key] = (d.leverage, side * (fill - d.liq_price) / fill) if d.ok else (0, np.nan)
        return cache[key]
    return f


def lev_liq(coin: str, side: np.ndarray, atr_frac: np.ndarray, k_stop: float = K_STOP):
    """Sizer leverage (30 / 20; infeasible -> 20 without liquidation, as the study) and liquidation distance."""
    sz = sizer(coin, k_stop)
    ll = np.array([sz(int(s_), float(x)) for s_, x in zip(side, atr_frac)], float).reshape(-1, 2)
    lev = ll[:, 0]
    feas = lev > 0
    return np.where(feas, lev, 20.0), np.where(feas, ll[:, 1], 10.0), feas


def first_tier_liq_frac(coin: str, side: int, L: int) -> float:
    """Isolated-margin liquidation distance (fraction of the fill) at leverage L, first bracket tier (study s6)."""
    t = BR[coin].tiers[0]
    qty, entry = 1.0, 100.0
    margin = qty * entry / L
    liq = liquidation_price(side, qty, entry, margin, t)
    return side * (entry - liq) / entry


# ------------------------------------------------------------------ house exit scan (study common.scan)
def scan(b, e, side, lev, liq_frac, risk_dist, H, f_bar, liq_touch=False):
    """House exit on 15m bars b (dict o/h/l/c arrays) for entries at the open of 15m bar e.
    Same arithmetic as research/st_custom/common.scan with fill/raw None, ladder=True, fill_bar=False,
    entry_fee=None. Unfinished rows: reason 3, R / roe at the last available close (mark to market)."""
    rt, fee, slip = S.round_trip_cost, S.taker_fee, S.slippage_frac
    n = len(b["o"])
    m = len(e)
    off = np.arange(H)
    J = e[:, None] + off[None, :]
    valid = J < n
    Jc = np.minimum(J, n - 1)
    o, h, lo, c = b["o"][Jc], b["h"][Jc], b["l"][Jc], b["c"][Jc]
    raw = b["o"][e]
    fill = raw * (1 + side * slip)
    stop0 = raw - side * risk_dist
    liq = fill * (1 - side * liq_frac)
    s = side[:, None]
    fund = f_bar * (off[None, :] + 1)
    fav = np.where(s == 1, h, -lo)
    best_px = s * np.maximum.accumulate(np.concatenate([(side * fill)[:, None], fav], axis=1), axis=1)[:, 1:]
    roe_best = lev[:, None] * (s * (best_px / fill[:, None] - 1) - rt - fund)
    first = LAD.first_lock + LAD.trigger_gap
    nstep = np.floor((roe_best - first) / LAD.step + 1e-9)
    lock_roe = np.where(roe_best >= first - 1e-12, LAD.first_lock + LAD.step * nstep, np.nan)
    lock_px = fill[:, None] * (1 + s * (lock_roe / lev[:, None] + rt + fund))
    lp = np.where(np.isnan(lock_px), -np.inf, s * lock_px)
    lock_cum = np.maximum.accumulate(np.concatenate([np.full((m, 1), -np.inf), lp], axis=1), axis=1)[:, :-1]
    stop_eff = np.maximum((side * stop0)[:, None], lock_cum)
    adverse = np.where(s == 1, lo, -h)
    hit = (adverse <= stop_eff) & valid
    if liq_touch:
        hit_l = (adverse <= (side * liq)[:, None]) & valid
        first_l = np.where(hit_l.any(1), hit_l.argmax(1), H)
        hit = hit | hit_l
    done = hit.any(axis=1)
    q = np.where(done, hit.argmax(axis=1), np.minimum(H, np.maximum(valid.sum(axis=1), 1)) - 1)
    r = np.arange(m)
    st = side * stop_eff[r, q]
    oq = o[r, q]
    gap = (side * oq) <= (side * st)
    liq_gap = done & gap & ((side * oq) <= (side * liq))
    if liq_touch:
        liq_gap = liq_gap | (done & (first_l == q) & ((side * liq) >= (side * st) - 1e-12))
    exit_raw = np.where(done, np.where(gap, oq, st), c[r, q])
    exit_px = np.where(liq_gap, liq, exit_raw * (1 - side * slip))
    held = q + 1
    roe = lev * (side * (exit_px / fill - 1) - fee - fee * exit_px / fill - f_bar * held)
    roe = np.where(liq_gap, -1.0, np.maximum(roe, -1.0))
    is_lock = done & ~liq_gap & (side * st > side * stop0 + 1e-12)
    reason = np.where(~done, 3, np.where(liq_gap, 2, np.where(is_lock, 1, 0)))
    risk = np.abs(fill - stop0)
    R = roe * fill / (lev * risk)
    gross = side * (exit_raw - raw) / risk
    return dict(done=done, x=e + q, R=R, gross=gross, roe=roe, reason=reason, fill=fill, risk=risk,
                exit_raw=exit_raw, exit_px=exit_px)


def run_scan(b, e, side, lev, liq_frac, risk_dist, f_bar=F_BAR15, passes=PASSES, liq_touch=False):
    """Multi-pass driver (study common.run_scan): short horizon first, the unfinished rows again with a longer one."""
    m = len(e)
    keys = ("x", "R", "gross", "roe", "reason", "fill", "risk", "exit_raw", "exit_px")
    res = {k: np.full(m, np.nan) for k in keys}
    res["done"] = np.zeros(m, bool)
    todo = np.arange(m)
    nb = len(b["o"])
    for H in passes:
        if not len(todo):
            break
        nxt = []
        step = max(16, 400_000 // H)
        for c0 in range(0, len(todo), step):
            sel = todo[c0:c0 + step]
            r = scan(b, e[sel], side[sel], lev[sel], liq_frac[sel], risk_dist[sel], H, f_bar, liq_touch=liq_touch)
            keep = r["done"] | (H == passes[-1]) | (e[sel] + H >= nb)
            for k in res:
                res[k][sel[keep]] = r[k][keep]
            nxt.append(sel[~keep])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    res["x"] = res["x"].astype(np.int64)
    res["reason"] = res["reason"].astype(np.int8)
    return res


# ------------------------------------------------------------------ TPSL (study common.tpsl_outcomes, + exit index)
def tpsl_first_hits(b, e, side, raw, dist, tps, H):
    n = len(b["o"])
    J = e[:, None] + np.arange(H)[None, :]
    valid = J < n
    Jc = np.minimum(J, n - 1)
    s = side[:, None]
    adverse = np.where(s == 1, b["l"][Jc], -b["h"][Jc])
    fav = np.where(s == 1, b["h"][Jc], -b["l"][Jc])
    stp = (side * (raw - side * dist))[:, None]
    hit_s = (adverse <= stp) & valid
    qs = np.where(hit_s.any(1), hit_s.argmax(1), H)
    qt = []
    for tp in tps:
        tpp = (side * (raw + side * tp * dist))[:, None]
        hit_t = (fav >= tpp) & valid
        qt.append(np.where(hit_t.any(1), hit_t.argmax(1), H))
    return qs, np.array(qt), valid.sum(1)


def tpsl_outcomes(b, e, side, atr, lev, liq_frac, f_bar=F_BAR15, passes=PASSES):
    """Per row and per TPSL setting (12, grid.TPSL_CFG order): net R, gross R, exit 15m index (NaN / -1 while open).
    TP fills at its price; a bar touching both = stop; a stop bar opening beyond the stop fills at the open; exit
    costs taker + slippage; liquidation only through a gap beyond it. R in units of that setting's stop distance."""
    m = len(e)
    nb = len(b["o"])
    raw = b["o"][e]
    fill = raw * (1 + side * SLIP)
    BIG = 10**12
    R = np.full((len(G.TPSL_CFG), m), np.nan, np.float32)
    Gr = np.full((len(G.TPSL_CFG), m), np.nan, np.float32)
    X = np.full((len(G.TPSL_CFG), m), -1, np.int64)
    for ki, k in enumerate(G.TPSL_K):
        dist = k * atr
        qs = np.full(m, BIG, np.int64)
        qt = np.full((len(G.TPSL_TP), m), BIG, np.int64)
        todo = np.arange(m)
        for H in passes:
            if not len(todo):
                break
            nxt = []
            step = max(16, 300_000 // H)
            for c0 in range(0, len(todo), step):
                sel = todo[c0:c0 + step]
                a_s, a_t, _nv = tpsl_first_hits(b, e[sel], side[sel], raw[sel], dist[sel], G.TPSL_TP, H)
                resolved = (a_s < H) | np.all(a_t < H, axis=0) | (H == passes[-1]) | (e[sel] + H >= nb)
                qs[sel] = np.where(a_s < H, a_s, BIG)
                qt[:, sel] = np.where(a_t < H, a_t, BIG)
                nxt.append(sel[~resolved])
            todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
        stop_px = raw - side * dist
        risk = np.abs(fill - stop_px)
        liq = fill * (1 - side * liq_frac)
        for ti, tp in enumerate(G.TPSL_TP):
            j = ki * len(G.TPSL_TP) + ti
            is_tp = qt[ti] < qs
            stop_hit = ~is_tp & (qs < BIG)
            done = is_tp | stop_hit
            q = np.where(is_tp, qt[ti], np.where(stop_hit, qs, 0))
            x = np.minimum(e + q, nb - 1)
            oq = b["o"][x]
            gap = stop_hit & ((side * oq) <= (side * stop_px))
            tp_px = raw + side * tp * dist
            exit_raw = np.where(is_tp, tp_px, np.where(gap, oq, stop_px))
            liq_gap = gap & ((side * oq) <= (side * liq))
            exit_px = np.where(liq_gap, liq, exit_raw * (1 - side * SLIP))
            held = q + 1
            roe = lev * (side * (exit_px / fill - 1) - TAKER * (1 + exit_px / fill) - f_bar * held)
            roe = np.where(liq_gap, -1.0, np.maximum(roe, -1.0))
            R[j] = np.where(done, roe * fill / (lev * risk), np.nan)
            Gr[j] = np.where(done, side * (exit_raw - raw) / risk, np.nan)
            X[j] = np.where(done, e + q, -1)
    return R, Gr, X


def halfbe_outcomes(b, e, side, atr, lev, liq_frac, f_bar=F_BAR15, passes=PASSES, k=2.0, tp1=1.0, tp2=1.5):
    """Exit 13 ("반익반본"): stop k x ATR; half closes at tp1 R (limit price), then the rest's stop moves to the entry
    fill (break-even) and the rest closes at tp2 R or at break-even. Bar rules as tpsl_outcomes: a bar touching the
    stop and TP1 = stop; after TP1 the rest may reach TP2 in the same bar, break-even counts from the next bar;
    a stop bar opening beyond the stop fills at the open; exit legs pay taker + slippage. Returns per row net R, gross R,
    exit 15m index of the last leg, raw exit price of the last leg (NaN / -1 while open). R in units of the stop
    distance of the fill."""
    m = len(e)
    nb = len(b["o"])
    raw = b["o"][e]
    fill = raw * (1 + side * SLIP)
    dist = k * atr
    stop_px = raw - side * dist
    t1 = raw + side * tp1 * dist
    t2 = raw + side * tp2 * dist
    be = fill
    risk = np.abs(fill - stop_px)
    liq = fill * (1 - side * liq_frac)
    R = np.full(m, np.nan)
    Gr = np.full(m, np.nan)
    X = np.full(m, -1, np.int64)
    XP = np.full(m, np.nan)
    BIG = 10**12
    todo = np.arange(m)
    for H in passes:
        if not len(todo):
            break
        nxt = []
        step = max(16, 200_000 // H)
        for c0 in range(0, len(todo), step):
            sel = todo[c0:c0 + step]
            J = e[sel][:, None] + np.arange(H)[None, :]
            valid = J < nb
            Jc = np.minimum(J, nb - 1)
            sd = side[sel][:, None]
            adverse = np.where(sd == 1, b["l"][Jc], -b["h"][Jc])
            fav = np.where(sd == 1, b["h"][Jc], -b["l"][Jc])
            hit_s = (adverse <= (side[sel] * stop_px[sel])[:, None]) & valid
            hit_1 = (fav >= (side[sel] * t1[sel])[:, None]) & valid
            hit_2 = (fav >= (side[sel] * t2[sel])[:, None]) & valid
            hit_b = (adverse <= (side[sel] * be[sel])[:, None]) & valid
            qs = np.where(hit_s.any(1), hit_s.argmax(1), BIG)
            q1 = np.where(hit_1.any(1), hit_1.argmax(1), BIG)
            idx = np.arange(H)[None, :]
            q1c = np.minimum(q1, H)[:, None]
            h2 = hit_2 & (idx >= q1c)
            hb = hit_b & (idx > q1c)
            q2 = np.where(h2.any(1), h2.argmax(1), BIG)
            qb = np.where(hb.any(1), hb.argmax(1), BIG)
            full_stop = (qs < BIG) & (qs <= q1)
            half = (q1 < BIG) & (q1 < qs)
            rest_done = half & ((q2 < BIG) | (qb < BIG))
            resolved = full_stop | rest_done | (H == passes[-1]) | (e[sel] + H >= nb)
            fin = full_stop | rest_done
            r = np.flatnonzero(fin)
            if len(r):
                g = sel[r]
                sdg = side[g]
                # full stop
                fs = full_stop[r]
                q = np.where(fs, qs[r], np.where(q2[r] <= qb[r], q2[r], qb[r]))
                xi = np.minimum(e[g] + q, nb - 1)
                oq = b["o"][xi]
                gap = fs & ((sdg * oq) <= (sdg * stop_px[g]))
                stop_raw = np.where(gap, oq, stop_px[g])
                liq_gap = gap & ((sdg * oq) <= (sdg * liq[g]))
                # rest leg (after TP1): TP2 or break-even (break-even bar opening beyond it fills at the open)
                to_t2 = ~fs & (q2[r] <= qb[r])
                gap_b = ~fs & ~to_t2 & ((sdg * oq) <= (sdg * be[g]))
                rest_raw = np.where(to_t2, t2[g], np.where(gap_b, oq, be[g]))
                last_raw = np.where(fs, stop_raw, rest_raw)
                held = q + 1
                f = fill[g]
                px_stop = np.where(liq_gap, liq[g], stop_raw * (1 - sdg * SLIP))
                px1 = t1[g] * (1 - sdg * SLIP)
                px2 = rest_raw * (1 - sdg * SLIP)
                ret_full = sdg * (px_stop / f - 1) - TAKER * (1 + px_stop / f)
                ret_half = (0.5 * sdg * (px1 / f - 1) + 0.5 * sdg * (px2 / f - 1)
                            - TAKER * (1 + 0.5 * px1 / f + 0.5 * px2 / f))
                ret = np.where(fs, ret_full, ret_half) - f_bar * held
                levg = lev[g]
                roe = np.where(liq_gap, -1.0, np.maximum(levg * ret, -1.0))
                R[g] = roe * f / (levg * risk[g])
                gross_full = sdg * (stop_raw - raw[g]) / risk[g]
                gross_half = (0.5 * sdg * (t1[g] - raw[g]) + 0.5 * sdg * (rest_raw - raw[g])) / risk[g]
                Gr[g] = np.where(fs, gross_full, gross_half)
                X[g] = e[g] + q
                XP[g] = last_raw
            nxt.append(sel[~resolved])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    return R.astype(np.float32), Gr.astype(np.float32), X, XP


def tpsl_exit_price(raw: float, side: int, atr: float, j: int, x_open: float, is_tp: bool) -> float:
    """Raw exit price of TPSL setting j (for display): the TP price, or the stop / the gap open."""
    tp, k = G.TPSL_CFG[j]
    dist = k * atr
    if is_tp:
        return raw + side * tp * dist
    stop_px = raw - side * dist
    return x_open if side * x_open <= side * stop_px else stop_px


# ------------------------------------------------------------------ owners' sizing checks (study s6 'house' mode)
def entry_check(coin: str, side: int, fill: float, stop_dist: float, atr: float, wallet: float, L: int,
                minorder: bool = True):
    """Owners' rule: margin = L% of the wallet, qty = margin x L / fill. Returns (ok, qty, margin, why) with the
    rule bot's checks: bracket max leverage, stop inside the liquidation price by the buffer, loss at the stop
    <= max_loss_frac of the wallet, exchange minimum order (assumed sizes)."""
    stop = fill - side * stop_dist
    exit_px = stop * (1 - side * SLIP)
    per_qty_loss = stop_dist + abs(stop - exit_px) + TAKER * fill + TAKER * exit_px
    margin = wallet * L / 100.0
    qty = margin * L / fill
    if minorder:
        stp, mn = MINORDER[coin]
        qty = math.floor(qty / stp + 1e-9) * stp
    else:
        mn = 5.0
    notional = qty * fill
    if qty <= 0 or notional < mn:
        return False, 0.0, 0.0, "min"
    margin = notional / L
    br = BR[coin].for_notional(notional)
    if L > br.max_leverage:
        return False, 0.0, 0.0, "bracket"
    lp = liquidation_price(side, qty, fill, margin, br)
    buffer = max(S.liq_buffer_atr_mult * atr, S.liq_buffer_min_frac * fill)
    if (stop - lp) * side < buffer:
        return False, 0.0, 0.0, "liq"
    if qty * per_qty_loss > S.max_loss_frac * wallet:
        return False, 0.0, 0.0, "loss"
    return True, qty, margin, ""


def check_ok_frac(coin: str, side: np.ndarray, stop_frac: np.ndarray, atr_frac: np.ndarray, L: int) -> np.ndarray:
    """Vectorised entry_check without the minimum order (wallet-free: every term scales with the wallet):
    stop_frac = stop distance / fill, atr_frac = ATR / fill. Used for the friend rule's per-leverage selection."""
    t = BR[coin].tiers[0]
    if L > t.max_leverage:
        return np.zeros(len(side), bool)
    liqf = np.where(side > 0, first_tier_liq_frac(coin, 1, L), first_tier_liq_frac(coin, -1, L))
    buffer = np.maximum(S.liq_buffer_atr_mult * atr_frac, S.liq_buffer_min_frac)
    room_ok = (liqf - stop_frac) >= buffer
    stop = 1 - side * stop_frac
    exit_px = stop * (1 - side * SLIP)
    per_loss = stop_frac + np.abs(stop - exit_px) + TAKER + TAKER * exit_px
    loss_ok = (L * L / 100.0) * per_loss <= S.max_loss_frac
    return room_ok & loss_ok
