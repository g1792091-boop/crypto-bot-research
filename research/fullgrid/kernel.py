"""Trade simulator of the full-grid study (research/fullgrid, DESIGN_KO.md section 4): paperbot.engine.PaperEngine's rules
for one original account (config.v3_settings: quality_v1 sizing, 2 x ATR14 stop, stepped lock, taker fees, slippage,
funding, isolated-margin liquidation on mark price, bust) on Binance 1m bars, compiled with numba.

Read-only research code: nothing here trades. tests/test_fullgrid_kernel.py replays the same signals through
PaperEngine and requires identical trades (entry, exit minute, reason, leverage, P&L to 1e-9).

Semantics (as paperbot/paramshadow.py replays the live account):
- A signal of the chart bar closing at ``close`` is submitted after the first 1m step whose minute ends at or after
  ``close`` (index j0 = first minute with open >= close - 1 min) and fills at the NEXT available minute (j0 + 1), at
  that minute's open as ``ref_price`` (+ slippage); stop = ref - side x 2 x ATR14 (``meta["stop_dist"]``).
- Sizing (sizing.size_position): the group's candidates in order ("best": 50x/50%, 40x/40%, then 30x/30%, 20x/20%;
  "normal": 30x/30%, 20x/20%), each must pass the bracket's max leverage, the stop inside liquidation by
  max(0.2% x entry, 1 x ATR) and the stop loss (fees and slippage included) <= 15% of the wallet.
- Each later minute: funding at the minute open on the mark open (liquidation price recomputed), then (engine
  _handle_exit) the favourable extreme is updated, a mark open beyond liquidation liquidates, an open beyond the stop
  exits at the open, a low/high through the stop exits at the stop (with slippage), a mark low/high through
  liquidation liquidates, otherwise the lock steps up (from the next minute). The entry minute is checked for stop and
  liquidation but gets no gap check and no lock step (ref_price fill).
- Exit variants (``EXITS``): the stop distance k x ATR14 (sizing uses that stop) x a take-profit rule (``TP_RULES``):
  the stepped lock from 5%, 10% (live) or 20%; a fixed take-profit at net ROE 10/20/30/50% (the engine's own fixed mode)
  or at 1/1.5/2/3 R from the entry reference (R = the stop distance); the lock with a 2R take-profit; the lock with a
  take-profit at the nearest swing level (structure, 3- or 10-bar swings).
- One trade alone (``outcomes``): the wallet before the trade is ``equity``; the result is the wallet change.
  The account (``account``): one position at a time over the coins, signals that arrive while a position is open are
  skipped, ties at one minute go to the coin priority order, bust below $10 stops the account.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np

try:
    from numba import njit
except ImportError:  # pragma: no cover  the server installs numba (bootstrap.sh); tests skip without it
    def njit(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MIN = 60_000
# reasons
R_NONE, R_SL, R_LOCK, R_LIQ, R_OPEN, R_REJECT, R_NOFILL, R_NOATR, R_TP = 0, 1, 2, 3, 4, 5, 6, 7, 8
REASON_NAMES = {R_SL: "SL", R_LOCK: "LOCK", R_LIQ: "LIQ", R_OPEN: "OPEN", R_REJECT: "REJECTED", R_NOFILL: "NO_FILL",
                R_NOATR: "NO_ATR", R_TP: "TP"}

# Take-profit rules (PREREG 5): name -> (take-profit kind, value, stepped lock on/off, first lock, lock step, trigger gap).
# Kind TP_NONE; TP_R: a limit at the entry reference + value x R (R = the stop distance); TP_ROE: a limit at net ROE
# `value` (the engine's own tp_mode "fixed", policy.tp_from_roe). "ladder" is the live rule (lock 10% at 12%, +5%).
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
            # structure: the nearest confirmed swing high above (long) / swing low below (short) the signal bar's close,
            # swings of 3 or 10 bars each side on the signal timeframe (``structure_levels``), with the 10% lock;
            # no such level beyond the entry reference price = the lock alone
            ("swing3", TP_STRUCT, 3.0, True, 0.10, 0.05, 0.02),
            ("swing10", TP_STRUCT, 10.0, True, 0.10, 0.05, 0.02))
STRUCT_LOOKBACK = 300          # bars: swings older than this are not used
STOPS = (2.0, 1.0, 1.5, 2.5, 3.0, 4.0)        # x ATR14; 2.0 (the live stop) first so that EXITS[0] is the live rule
# Exit variants: (name, stop x ATR14, take-profit kind, value, lock on/off, first lock, lock step, trigger gap).
EXITS = tuple((f"{r[0]}|{k:g}", k) + r[1:] for k in STOPS for r in TP_RULES)


def exit_args(e: int) -> tuple:
    """kernel arguments of exit variant e: (stop x ATR, tp kind, tp value, ladder, first lock, lock step, gap)."""
    return EXITS[e][1:]


@njit
def structure_levels(h, l, c, k, lookback):
    """(tp_long, tp_short) per chart bar: the lowest confirmed swing high above the bar's close and the highest
    confirmed swing low below it, among swings of the last ``lookback`` bars (NaN when none). A swing high at bar p has
    a high strictly above the k bars on each side and is known at bar p + k (no look-ahead)."""
    n = len(c)
    tl = np.full(n, np.nan)
    ts = np.full(n, np.nan)
    ph = np.zeros(n, np.bool_)
    pl = np.zeros(n, np.bool_)
    for p in range(k, n - k):
        hi = True
        lo = True
        for j in range(p - k, p + k + 1):
            if j == p:
                continue
            if not h[p] > h[j]:
                hi = False
            if not l[p] < l[j]:
                lo = False
        ph[p] = hi
        pl[p] = lo
    for i in range(n):
        best_h = np.inf
        best_l = -np.inf
        last = i - k                                   # swings at p <= i - k are confirmed at bar i
        for p in range(max(0, i - lookback), last + 1):
            if ph[p] and h[p] > c[i] and h[p] < best_h:
                best_h = h[p]
            if pl[p] and l[p] < c[i] and l[p] > best_l:
                best_l = l[p]
        if best_h < np.inf:
            tl[i] = best_h
        if best_l > -np.inf:
            ts[i] = best_l
    return tl, ts


def settings_vector(settings=None) -> np.ndarray:
    """The numbers of config.v3_settings() the kernel uses, in a fixed order (so the rules can never drift)."""
    from paperbot.config import v3_settings
    s = settings or v3_settings()
    assert s.leverage_rule == "quality_v1" and s.tp_mode == "ladder" and s.best_falls_to_normal
    assert s.stop_first_on_ambiguous_bar
    best = [(t.margin_frac, lev) for t in s.tiers if t.name == "best" for lev in t.leverages]
    normal = [(t.margin_frac, lev) for t in s.tiers if t.name == "normal" for lev in t.leverages]
    assert len(best) == 2 and len(normal) == 2
    lad = s.ladder
    return np.array([s.taker_fee, s.slippage_frac, s.max_loss_frac, s.liq_buffer_atr_mult, s.liq_buffer_min_frac,
                     s.round_trip_cost, lad.first_lock, lad.step, lad.trigger_gap, s.bust_below, s.initial_equity,
                     best[0][0], best[0][1], best[1][0], best[1][1], normal[0][0], normal[0][1], normal[1][0],
                     normal[1][1], s.maker_fee], float)


def bracket_arrays(br) -> np.ndarray:
    """paperbot.margin.Brackets -> rows (notional_cap, max_leverage, mmr, cum), lowest notional first."""
    return np.array([[t.notional_cap, t.max_leverage, t.mmr, t.cum] for t in br.tiers], float)


@njit
def _round_down(x, step):
    if step <= 0:
        return x
    return math.floor(x / step + 1e-9) * step


@njit
def _bracket(br, notional):
    for k in range(br.shape[0]):
        if notional <= br[k, 0]:
            return k
    return br.shape[0] - 1


@njit
def _liq(side, qty, entry, margin, mmr, cum):
    denom = qty * mmr - side * qty
    lp = (margin + cum - side * qty * entry) / denom
    return lp if lp > 0.0 else 0.0


@njit
def _size(S, br, equity, side, fill, stop, atr, best, qty_step, min_notional):
    """sizing.size_position under quality_v1. Returns (ok, leverage, margin, qty, liq)."""
    if equity <= 0 or (fill - stop) * side <= 0:
        return False, 0, 0.0, 0.0, 0.0
    taker, slip, max_loss, buf_atr, buf_min = S[0], S[1], S[2], S[3], S[4]
    buffer = max(buf_min * fill, buf_atr * atr)
    stop_dist = abs(fill - stop)
    first = 0 if best else 2
    for c in range(first, 4):
        frac, lev = S[11 + 2 * c], int(S[12 + 2 * c])
        margin = equity * frac
        qty = _round_down(margin * lev / fill, qty_step)
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


@njit
def _trade(S, br, o, h, l, mo, mh, ml, fund, e, end, side, stop_dist, atr, best, equity, qty_step, min_notional,
           tp_kind, tp_val, ladder, first_lock, step, gap, tp_price):
    """One position from entry minute e (fill at o[e]) until an exit or ``end`` (exclusive). Take-profit (engine
    tp_mode "fixed": fills only when price trades through it, at it or a better gapped open, maker fee; the stop wins a
    bar that touches both): TP_R at the entry reference + tp_val x stop distance, TP_ROE at net ROE tp_val
    (policy.tp_from_roe on the fill and the leverage), TP_STRUCT at ``tp_price`` when it lies beyond the fill
    price (else none: a level at or behind the fill would only take a loss). ``ladder``: the stepped lock
    (first_lock, step, gap).
    Returns (wallet change, exit minute index, reason, leverage); reason R_OPEN when no exit before ``end``."""
    taker, slip, rt, maker = S[0], S[1], S[5], S[19]
    raw = o[e]
    fill = raw * (1 + side * slip)
    stop = raw - side * stop_dist
    ok, lev, margin, qty, liq = _size(S, br, equity, side, fill, stop, atr, best, qty_step, min_notional)
    if not ok:
        return 0.0, e, R_REJECT, 0
    has_tp = tp_kind != TP_NONE
    if tp_kind == TP_R:
        tp = raw + side * tp_val * stop_dist
    elif tp_kind == TP_STRUCT:
        tp = tp_price
        has_tp = np.isfinite(tp_price) and (tp_price - fill) * side > 0
    else:
        tp = fill * (1.0 + side * (tp_val / lev + rt))
    notional = qty * fill
    wallet = equity - notional * taker
    fpaid = 0.0
    mfe = fill
    lock_roe = -1.0
    has_lock = False
    kb = _bracket(br, qty * fill)
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
        else:
            if l[j] < mfe:
                mfe = l[j]
        price = -1.0
        liquidate = False
        at_tp = False
        if not entry_bar:
            if (mo[j] - liq) * side <= 0:
                liquidate = True
            elif (o[j] - stop) * side <= 0:
                price = o[j] * (1 - side * slip)
            elif has_tp and (o[j] - tp) * side > 0:
                price = o[j]
                at_tp = True
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
            elif ladder and not entry_bar:
                fr = fpaid / notional
                bst = lev * (side * (mfe / fill - 1.0) - rt - fr)
                ft = first_lock + gap
                if bst >= ft - 1e-12:
                    n = math.floor((bst - ft) / step + 1e-9)
                    lk = first_lock + step * n
                    if (not has_lock) or lk > lock_roe + 1e-12:
                        cand = fill * (1.0 + side * (lk / lev + rt + fr))
                        if side > 0:
                            stop = max(stop, cand)
                        else:
                            stop = min(stop, cand)
                        lock_roe = lk
                        has_lock = True
        if price >= 0:
            gross = side * qty * (price - fill)
            if gross < -margin:
                liquidate = True
            else:
                wallet += gross - qty * price * (maker if at_tp else taker)
                return wallet - equity, j, (R_TP if at_tp else (R_LOCK if has_lock else R_SL)), lev
        if liquidate:
            wallet -= margin
            return wallet - equity, j, R_LIQ, lev
    return wallet - equity, end - 1, R_OPEN, lev


@njit
def _entry_index(ts, close):
    """j0 + 1 where j0 is the first minute with open >= close - 1 min (paramshadow.replay_day), or -1."""
    j0 = np.searchsorted(ts, close - 60_000)
    if j0 + 1 >= len(ts):
        return -1
    return j0 + 1


@njit
def outcomes(S, br, ts, o, h, l, mo, mh, ml, fund, close, atr, best_l, best_s, equity, qty_step, min_notional,
             stop_atr, tp_kind, tp_val, ladder, first_lock, step, gap, tp_long, tp_short):
    """Every chart bar as a signal, each side, alone: arrays [bar, side(0 long, 1 short)] of wallet change / equity,
    exit minute index, reason and leverage. ``best_l`` / ``best_s``: the bar's group per side (True = "best");
    ``tp_long`` / ``tp_short``: the bar's structure take-profit level per side (TP_STRUCT only)."""
    n = len(close)
    pnl = np.full((n, 2), np.nan)
    ex = np.full((n, 2), -1, np.int64)
    rs = np.zeros((n, 2), np.int8)
    lv = np.zeros((n, 2), np.int8)
    m = len(ts)
    for i in range(n):
        a = atr[i]
        e = _entry_index(ts, close[i])
        for k in range(2):
            side = 1 if k == 0 else -1
            if not (a > 0) or not np.isfinite(a):
                rs[i, k] = R_NOATR
                continue
            if e < 0:
                rs[i, k] = R_NOFILL
                continue
            best = best_l[i] if k == 0 else best_s[i]
            d, x, r, lev = _trade(S, br, o, h, l, mo, mh, ml, fund, e, m, side, stop_atr * a, a, best, equity,
                                  qty_step, min_notional, tp_kind, tp_val, ladder, first_lock, step, gap,
                                  tp_long[i] if k == 0 else tp_short[i])
            rs[i, k] = r
            lv[i, k] = lev
            ex[i, k] = x
            if r != R_REJECT and r != R_OPEN:
                pnl[i, k] = d / equity
    return pnl, ex, rs, lv


@njit
def account(S, brs, ts, o, h, l, mo, mh, ml, fund, starts, ends, sig_coin, sig_close, sig_side, sig_atr, sig_best,
            qty_steps, min_notionals, stop_atr, tp_kind, tp_val, ladder, first_lock, step, gap, sig_tp):
    """One account over several coins (1m arrays concatenated; coin c is [starts[c], ends[c])). Signals must be sorted
    by (entry minute, coin priority). Returns per signal: status (0 skipped, 1 entered, 2 rejected, 3 no fill,
    4 not taken after bust), P&L, exit time (ms), reason, leverage; and the final wallet."""
    n = len(sig_coin)
    status = np.zeros(n, np.int8)
    pnl = np.zeros(n)
    exit_ts = np.zeros(n, np.int64)
    reason = np.zeros(n, np.int8)
    lev = np.zeros(n, np.int8)
    wallet = S[10]
    busy_until = -1          # exit time (ms) of the open position; a signal must fill strictly after it
    bust = False
    entered_at = -1
    for q in range(n):
        c = sig_coin[q]
        a, b = starts[c], ends[c]
        tsc = ts[a:b]
        e = _entry_index(tsc, sig_close[q])
        if e < 0:
            status[q] = 3
            continue
        t_fill = tsc[e]
        if bust:
            status[q] = 4
            continue
        if t_fill <= busy_until or t_fill == entered_at:
            status[q] = 0
            continue
        x = sig_atr[q]
        if not (x > 0) or not np.isfinite(x):
            status[q] = 2
            continue
        d, j, r, lv_ = _trade(S, brs[c], o[a:b], h[a:b], l[a:b], mo[a:b], mh[a:b], ml[a:b], fund[a:b], e, b - a,
                              sig_side[q], stop_atr * x, x, sig_best[q], wallet, qty_steps[c], min_notionals[c], tp_kind,
                              tp_val, ladder, first_lock, step, gap, sig_tp[q])
        if r == R_REJECT:
            status[q] = 2
            continue
        status[q] = 1
        pnl[q] = d
        reason[q] = r
        lev[q] = lv_
        exit_ts[q] = tsc[j]
        wallet += d
        busy_until = tsc[j]
        entered_at = t_fill
        if r == R_OPEN:
            busy_until = 2 ** 62
        if S[9] > 0 and wallet < S[9]:
            bust = True
    return status, pnl, exit_ts, reason, lev, wallet
