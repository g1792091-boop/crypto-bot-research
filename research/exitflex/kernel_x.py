"""exitflex kernel (research/exitflex/PREREG_EXITFLEX.md sections 4-6): a numba copy of research/fullgrid/kernel.py's
``_trade`` and ``account`` extended with the rule-exit step order of section 4, the placebo check of section 6, a forced
period-end close and a free fill minute after a rule or placebo exit.

Read-only research code: nothing here trades, and nothing here prints a number.

With ``rp[RP_FAM] == 0`` (no rule), ``plc == 0`` and ``force_end == False`` the functions are the kernel's, line for
line (test T1): the new steps are not entered and return the same tuple in its first four places.

Step order inside one minute j after the entry minute e (section 4):
  0. decision (rule or placebo) from state frozen at the end of minute j - 1: favourable extreme X and its time T_X over
     minutes e .. j - 1, funding paid before j, chart data closed at or before the check close. Nothing of minute j.
  1. funding at j's open (mark open); liquidation price recomputed.
  2. favourable extreme updated with j's high (long) / low (short): used by decisions at later minutes and the lock.
  3. mark open beyond liquidation -> LIQ.
  4. open beyond the hard stop -> SL at the open, taker.
  5. open beyond the take-profit -> TP at the open, maker.
  6. NEW: step 0 decided to exit (RULE / RAND) or the forced period-end close is due (END): exit at j's open with
     slippage, taker.
  7. the minute's range: stop (SL), liquidation, take-profit (TP); the stepped lock (unchanged).

Layout of the chart arrays handed to the kernel (one row per chart bar of a coin; coins concatenated, ``cst``/``cen`` mark
each coin's rows):
  PT  float64 (n, 9): close ms, close, ATR14, EMA(n) of the variant, low, high, structure_levels(w) second output at the
                      bar (highest confirmed swing low below the close), first output (lowest swing high above it), the
                      minute index of the bar's close (kernel._entry_index on the coin's minutes, -1 none).
  PF  int8 (n, 18):   swing low at the bar (strict, +-w bars), swing high, long signal, short signal, then the F11
                      components of the long side (6 columns) and of the short side (6): 0 false, 1 true, 2 NaN (unknown),
                      then F11's own long / short 'can fire here' flags (placebo stratum only).
  QT  float64 (nq, 4): the 15m bars of a q15 variant: close ms, close, minute index of the close, index of the latest
                      pick-timeframe bar closed at or before it (rows of ``qst``/``qen`` per coin).
Rule parameters ``rp`` (float64 vector, indices RP_*): family, swing width w, chandelier multiple m, arm level P (R), give-
back g, loss depth d (R), count N (bars), pick timeframe (ms), q15 flag, clock hours H (F7h and F12's F7h leg). F12 (all nine
components at once, prereg 5.2) reads its fixed values from the same vector (``F12_PARAMS``) and records every component that
fired at the exit's check as a bit mask (CB_*), returned as the 8th value of ``_trade_x`` and per signal by ``account_x``.
"""

from __future__ import annotations

import importlib.util
import math
import os
import sys

import numpy as np
from numba import njit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FG = os.path.join(ROOT, "research", "fullgrid")


def _load_kernel():
    """research/fullgrid/kernel.py under the name run.py gives it, so that both share one module object."""
    if "fullgrid_kernel" in sys.modules:
        return sys.modules["fullgrid_kernel"]
    spec = importlib.util.spec_from_file_location("fullgrid_kernel", os.path.join(FG, "kernel.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fullgrid_kernel"] = mod
    spec.loader.exec_module(mod)
    return mod


K = _load_kernel()
_size, _bracket, _liq, _entry_index = K._size, K._bracket, K._liq, K._entry_index
TP_NONE, TP_R, TP_ROE, TP_STRUCT = K.TP_NONE, K.TP_R, K.TP_ROE, K.TP_STRUCT
R_NONE, R_SL, R_LOCK, R_LIQ, R_OPEN, R_REJECT, R_NOFILL, R_NOATR, R_TP = (
    K.R_NONE, K.R_SL, K.R_LOCK, K.R_LIQ, K.R_OPEN, K.R_REJECT, K.R_NOFILL, K.R_NOATR, K.R_TP)
R_RULE, R_RAND, R_END = 9, 10, 11
REASON_NAMES = dict(K.REASON_NAMES)
REASON_NAMES.update({R_RULE: "RULE", R_RAND: "RAND", R_END: "END", R_NONE: "NONE"})

# families (prereg 5.2); 11 is the plug-in point of the native exit; F12 stacks nine of them (all at once)
F_NONE, F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11, F7H, F12 = range(14)
# F12 component bits of the exit mask ``tr_comp`` (prereg 5.2)
CB_F1, CB_F2, CB_F3, CB_F4, CB_F5, CB_F6, CB_F7H, CB_F10, CB_F11 = 1, 2, 4, 8, 16, 32, 64, 128, 256
COMP_NAMES = (("F1", CB_F1), ("F2", CB_F2), ("F3", CB_F3), ("F4", CB_F4), ("F5", CB_F5), ("F6", CB_F6), ("F7h", CB_F7H),
              ("F10", CB_F10), ("F11", CB_F11))
# F12's fixed values (prereg 5.2): the middle of each component's grid, the larger of a two-value grid
F12_PARAMS = {"w": 3, "n": 20, "m": 2.0, "P": 1.5, "g": 0.5, "d": 0.5, "H": 8, "N": 12}
# chart array columns
C_CMS, C_CL, C_ATR, C_EMA, C_LO, C_HI, C_SLO, C_SHI, C_MIN = range(9)
NPT = 9
NC = 6                                         # F11 components per side
P_SWL, P_SWH, P_SIGL, P_SIGS = range(4)
P_CL0, P_CS0 = 4, 4 + NC                       # F11 component columns: long side, short side (0 false, 1 true, 2 NaN)
P_ZL, P_ZS = 4 + 2 * NC, 5 + 2 * NC            # F11: the strategy's own 'can fire at this bar' flags (long, short; default 1)
NPF = 6 + 2 * NC
CK_NONE, CK_STATE, CK_EVENT = 0, 1, 2          # component kinds (prereg A.0 rule C3)
Q_CMS, Q_CL, Q_MIN, Q_PT = range(4)
NQT = 4
# rule parameter vector
RP_FAM, RP_W, RP_M, RP_P, RP_G, RP_D, RP_N, RP_TF, RP_Q15, RP_H, RP_CMASK = range(11)
NRP = 11
CB_ALL = 511                                   # F12: all nine components enabled (a smaller mask exists for tests only)
# placebo strata (prereg 6): age bucket of the check index, profit sign, precondition
N_AGE = 8
TRACE_COLS = 12      # j, check close ms, rule fires, a, s, z, armed, reference, Rc, Rpk, u, exits
INF = 2 ** 62


def empty_chart() -> tuple:
    """Chart arrays of a run without a rule (all kernel-typed, zero rows)."""
    return (np.zeros((0, NPT)), np.zeros((0, NPF), np.int8), np.zeros((0, NQT)))


def rp_vector(fam=0, w=0, m=0.0, P=0.0, g=0.0, d=0.0, N=0, tf_ms=0, q15=False, H=0.0, cmask=None) -> np.ndarray:
    """N: bars (F7, F10, F12's F10 leg); H: clock hours (F7h, F12's F7h leg); cmask: the F12 components that are enabled (bit mask
    CB_*; all nine in production, fewer in tests of one component alone)."""
    v = np.zeros(NRP)
    v[RP_FAM], v[RP_W], v[RP_M], v[RP_P], v[RP_G], v[RP_D], v[RP_N], v[RP_TF], v[RP_Q15], v[RP_H], v[RP_CMASK] = (
        fam, w, m, P, g, d, N, tf_ms, 1.0 if q15 else 0.0, H, float(CB_ALL if cmask is None else cmask))
    return v


# ------------------------------------------------------------------ placebo draw (prereg 6)
@njit
def _mix64(z):
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))


@njit
def _splitmix64(x):
    """The standard splitmix64 step: the finaliser applied to x + 0x9E3779B97F4A7C15 (mod 2^64)."""
    return _mix64(x + np.uint64(0x9E3779B97F4A7C15))


@njit
def draw_u(base, coin, close_ms):
    """u = (splitmix64(splitmix64(base) XOR key) >> 11) / 2^53 with key = coin x 2^36 + close_ms // 60,000."""
    key = np.uint64(coin) * np.uint64(68719476736) + np.uint64(close_ms // 60000)
    z = _splitmix64(_splitmix64(np.uint64(base)) ^ key)
    return float(z >> np.uint64(11)) / 9007199254740992.0


@njit
def age_bucket(k):
    """Bucket of the check index k (1 = the first check): {1}, {2}, {3-4}, {5-8}, {9-16}, {17-32}, {33-64}, {65+}."""
    if k <= 1:
        return 0
    b = 0
    v = k - 1
    while v > 0:
        b += 1
        v >>= 1
    return b if b < N_AGE - 1 else N_AGE - 1


@njit
def _sched_minute(PT, QT, q15, si, e):
    """Minute of schedule bar si (never before e + 1), INF when the bar does not exist or has no minute."""
    if q15:
        if si >= QT.shape[0]:
            return INF
        m = int(QT[si, Q_MIN])
    else:
        if si >= PT.shape[0]:
            return INF
        m = int(PT[si, C_MIN])
    if m < 0:
        return INF
    return m if m > e else e + 1


@njit
def _first_close_after(QT, t):
    """First 15m row whose close is after t (binary search)."""
    lo = 0
    hi = QT.shape[0]
    while lo < hi:
        mid = (lo + hi) // 2
        if QT[mid, Q_CMS] > t:
            hi = mid
        else:
            lo = mid + 1
    return lo


@njit
def _trade_x(S, br, ts, o, h, l, mo, mh, ml, fund, e, end, side, stop_dist, atr, best, equity, qty_step, min_notional,
             tp_kind, tp_val, ladder, first_lock, step, gap, tp_price,
             force_end, rp, i0, PT, PF, QT, plc, hz, seed_base, coin, num, den, trace, ckind, lvl):
    """kernel._trade + rule/placebo exits + forced period end. One position from entry minute e (fill at o[e]) until an
    exit or ``end`` (exclusive; the period's last minute is end - 1). Returns (wallet change, exit minute index, reason,
    leverage, exit price (0 when still open), checks made, minutes where stop and take-profit were both touched).
    ``trace`` (rows x TRACE_COLS, zero rows in production) records each check's frozen decision state.
    F12 (all nine components at once, prereg 5.2) tests F1, F2, F3, F4, F5, F6, F7h, F10 and F11 on the same frozen state at
    the values of F12_PARAMS; the 8th return value is the bit mask (CB_*) of every component that fired at the check of a
    RULE exit (0 for any other exit and for every other family).
    F11 (the strategy's own exit, prereg Appendix A): ``ckind`` (2 x NC, CK_*) gives the kind of each component of the long
    and of the short side, the component values are PF columns P_CL0 / P_CS0 +; ``lvl`` is the position's invalidation level
    (NaN none; a close beyond it, below for a long, is one more state component). A state component is armed once it has been
    false at some chart close in [i0, i - 1] and then fires where it is true; an event component fires where it is true on a
    bar after i0; a NaN (2) neither fires nor arms; the bars of a merged check are walked in time order and the check fires if
    any bar fires."""
    taker, slip, rt, maker = S[0], S[1], S[5], S[19]
    raw = o[e]
    fill = raw * (1 + side * slip)
    stop = raw - side * stop_dist
    ok, lev, margin, qty, liq = _size(S, br, equity, side, fill, stop, atr, best, qty_step, min_notional)
    if not ok:
        return 0.0, e, R_REJECT, 0, 0.0, 0, 0, 0
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
    tx = ts[e]
    lock_roe = -1.0
    has_lock = False
    kb = _bracket(br, qty * fill)
    both = 0
    # ---- rule / placebo state (only used when a family is set)
    fam = int(rp[RP_FAM])
    w_sw = int(rp[RP_W])
    q15 = rp[RP_Q15] > 0.5
    nxt = INF
    si = 0
    pi = i0
    k = 0
    ref = np.nan
    ema_armed = False
    armed = False
    car = np.zeros(NC + 1, np.bool_)
    kbase = 0 if side > 0 else NC
    pcol = P_CL0 if side > 0 else P_CS0
    has_lvl = np.isfinite(lvl)
    use_ref = fam == F1 or fam == F6 or fam == F8 or fam == F9 or fam == F12
    use_ema = fam == F2 or fam == F12
    use_f3 = fam == F3 or fam == F12
    use_f11 = fam == F11 or fam == F12
    use_arm = fam == F5 or fam == F8 or fam == F9 or fam == F12
    comp = 0
    cmk = int(rp[RP_CMASK])                    # F12: the enabled components (all nine in production)
    if use_f11:
        for c in range(NC):
            if ckind[kbase + c] == CK_STATE:
                car[c] = PF[i0, pcol + c] == 0
        if has_lvl and np.isfinite(PT[i0, C_CL]):
            car[NC] = side * (lvl - PT[i0, C_CL]) <= 0
    if fam != F_NONE:
        if use_ref:
            ref = PT[i0, C_SLO] if side > 0 else PT[i0, C_SHI]
        if use_ema:
            ema_armed = side * (PT[i0, C_CL] - PT[i0, C_EMA]) > 0
        if q15:
            si = _first_close_after(QT, PT[i0, C_CMS])
        else:
            si = i0 + 1
        nxt = _sched_minute(PT, QT, q15, si, e)
    for j in range(e, end):
        entry_bar = j == e
        fire = False
        rule_fire = False
        chk = False
        comp_now = 0
        clock_now = False
        ca = 0
        cs = 0
        cz = 0
        # ---- step 0: the decision, from the state frozen at the end of minute j - 1
        if fam != F_NONE and (not entry_bar) and j >= nxt:
            chk = True
            last = si
            while True:
                nm = _sched_minute(PT, QT, q15, si, e)
                if nm > j:
                    break
                last = si
                si += 1
            nxt = _sched_minute(PT, QT, q15, si, e)
            k += 1
            if q15:
                cc = QT[last, Q_CMS]
                px = QT[last, Q_CL]
                bi = int(QT[last, Q_PT])
            else:
                bi = last
                cc = PT[bi, C_CMS]
                px = PT[bi, C_CL]
            if bi < pi:
                bi = pi
            f3_any = False
            f11_any = False
            ema_fire = False
            ema_before = ema_armed
            zpre = has_lvl                         # F11's precondition: read before the check bar's own close updates the arms
            if use_f11:
                for c in range(NC):
                    kd = ckind[kbase + c]
                    if kd == CK_EVENT or (kd == CK_STATE and car[c]):
                        zpre = True
            for ib in range(pi + 1, bi + 1):
                if use_ref:
                    p = ib - w_sw
                    if p >= 0:
                        if side > 0:
                            if PF[p, P_SWL] == 1:
                                v = PT[p, C_LO]
                                if np.isnan(ref) or v > ref:
                                    ref = v
                        else:
                            if PF[p, P_SWH] == 1:
                                v = PT[p, C_HI]
                                if np.isnan(ref) or v < ref:
                                    ref = v
                if use_ema:
                    cl = PT[ib, C_CL]
                    em = PT[ib, C_EMA]
                    if ib == bi:
                        ema_fire = ema_armed and (side * (em - cl) > 0)
                        ema_before = ema_armed
                    if side * (cl - em) > 0:
                        ema_armed = True
                if use_f3:
                    if PF[ib, P_SIGS if side > 0 else P_SIGL] == 1:
                        f3_any = True
                if use_f11:
                    if ib == bi:
                        zpre = has_lvl
                        for c in range(NC):
                            kd = ckind[kbase + c]
                            if kd == CK_EVENT or (kd == CK_STATE and car[c]):
                                zpre = True
                    for c in range(NC):
                        kd = ckind[kbase + c]
                        if kd == CK_NONE:
                            continue
                        vv = PF[ib, pcol + c]
                        if vv == 2:
                            continue
                        if kd == CK_EVENT:
                            if vv == 1:
                                f11_any = True
                        elif vv == 1:
                            if car[c]:
                                f11_any = True
                        else:
                            car[c] = True
                    if has_lvl and np.isfinite(PT[ib, C_CL]):
                        if side * (lvl - PT[ib, C_CL]) > 0:
                            if car[NC]:
                                f11_any = True
                        else:
                            car[NC] = True
            pi = bi
            fr = fpaid / notional
            rc = (side * (px - fill) - fill * (rt + fr)) / stop_dist
            rpk = (side * (mfe - fill) - fill * (rt + fr)) / stop_dist
            if use_arm:
                if rpk >= rp[RP_P]:
                    armed = True
            have_ref = not np.isnan(ref)
            brk = have_ref and (side * (ref - px) > 0)
            if fam == F1:
                rule_fire = brk
            elif fam == F2:
                rule_fire = ema_fire
            elif fam == F3:
                rule_fire = f3_any
            elif fam == F11:
                rule_fire = f11_any
            elif fam == F4:
                lvl4 = mfe - side * rp[RP_M] * PT[bi, C_ATR]
                rule_fire = side * (lvl4 - px) > 0
            elif fam == F5:
                rule_fire = armed and (rc <= (1.0 - rp[RP_G]) * rpk)
            elif fam == F6:
                rule_fire = brk and (rc < -rp[RP_D])
            elif fam == F7:
                rule_fire = cc >= PT[i0, C_CMS] + rp[RP_N] * rp[RP_TF]
            elif fam == F7H:
                rule_fire = cc >= PT[i0, C_CMS] + rp[RP_H] * 3600000.0
            elif fam == F8:
                rule_fire = armed and brk
            elif fam == F9:
                rule_fire = brk and (armed or (rc < -rp[RP_D]))
            elif fam == F10:
                rule_fire = (rc > 0.0) and (cc - tx >= rp[RP_N] * rp[RP_TF])
            elif fam == F12:
                # nine components on the same frozen state; none reads another's result (prereg 5.2)
                cm = 0
                if brk:
                    cm |= CB_F1
                if ema_fire:
                    cm |= CB_F2
                if f3_any:
                    cm |= CB_F3
                lvl4 = mfe - side * rp[RP_M] * PT[bi, C_ATR]
                if side * (lvl4 - px) > 0:
                    cm |= CB_F4
                if armed and (rc <= (1.0 - rp[RP_G]) * rpk):
                    cm |= CB_F5
                if brk and (rc < -rp[RP_D]):
                    cm |= CB_F6
                if cc >= PT[i0, C_CMS] + rp[RP_H] * 3600000.0:
                    cm |= CB_F7H
                if (rc > 0.0) and (cc - tx >= rp[RP_N] * rp[RP_TF]):
                    cm |= CB_F10
                if f11_any:
                    cm |= CB_F11
                cm &= cmk
                comp_now = cm
                rule_fire = cm != 0
                clock_now = ((cmk & CB_F7H) != 0) and (cc >= PT[i0, C_CMS] + rp[RP_H] * 3600000.0)
            # the placebo stratum (age bucket, profit sign, precondition) of the frozen state
            ca = age_bucket(k)
            cs = 1 if rc >= 0.0 else 0
            if fam == F1:
                cz = 1 if have_ref else 0
            elif fam == F6:
                cz = 1 if (have_ref and rc < -rp[RP_D]) else 0
            elif fam == F2:
                cz = 1 if ema_before else 0
            elif fam == F5:
                cz = 1 if armed else 0
            elif fam == F8:
                cz = 1 if (armed and have_ref) else 0
            elif fam == F9:
                cz = 1 if (have_ref and (armed or rc < -rp[RP_D])) else 0
            elif fam == F11 or fam == F12:
                z11 = zpre and PF[bi, P_ZL if side > 0 else P_ZS] != 0
                if fam == F11:
                    cz = 1 if z11 else 0
                else:
                    # F12: a swing reference exists, F2 is armed, F5 is armed, or F11's own z (prereg 6)
                    cz = 1 if (((cmk & CB_F1) != 0 and have_ref) or ((cmk & CB_F2) != 0 and ema_before) or ((cmk & CB_F5) != 0 and armed)
                               or ((cmk & CB_F11) != 0 and z11)) else 0
            u = 0.0
            if plc:
                if clock_now:                      # F12 placebo: it exits with probability 1 at F12's clock check, no draw (prereg 6)
                    u = -1.0
                    fire = True
                else:
                    u = draw_u(seed_base, coin, int(cc))
                    fire = u < hz[ca, cs, cz]
            else:
                fire = rule_fire
            if k <= trace.shape[0]:
                trace[k - 1, 0] = j
                trace[k - 1, 1] = cc
                trace[k - 1, 2] = 1.0 if rule_fire else 0.0
                trace[k - 1, 3] = ca
                trace[k - 1, 4] = cs
                trace[k - 1, 5] = cz
                trace[k - 1, 6] = 1.0 if armed else (1.0 if (fam == F2 and ema_before) else 0.0)
                trace[k - 1, 7] = ref
                trace[k - 1, 8] = rc
                trace[k - 1, 9] = rpk
                trace[k - 1, 10] = u
                trace[k - 1, 11] = 1.0 if fire else 0.0
        # ---- step 1: funding
        entry_fund = (not entry_bar) and fund[j] != 0.0
        if entry_fund:
            pay = side * qty * mo[j] * fund[j]
            wallet -= pay
            margin -= pay
            fpaid += pay
            liq = _liq(side, qty, fill, margin, br[kb, 2], br[kb, 3])
        # ---- step 2: favourable extreme (used by decisions at later minutes and by the lock)
        if side > 0:
            if h[j] > mfe:
                mfe = h[j]
                tx = ts[j]
        else:
            if l[j] < mfe:
                mfe = l[j]
                tx = ts[j]
        price = -1.0
        liquidate = False
        at_tp = False
        code = R_NONE
        # ---- steps 3-5: gaps at the open
        if not entry_bar:
            if (mo[j] - liq) * side <= 0:
                liquidate = True
            elif (o[j] - stop) * side <= 0:
                price = o[j] * (1 - side * slip)
            elif has_tp and (o[j] - tp) * side > 0:
                price = o[j]
                at_tp = True
            # the check counts in the hazard only when the position is still open after steps 1-5
            if chk and (not liquidate) and price < 0 and not clock_now:      # F12: the clock check is outside the table (prereg 6)
                den[ca, cs, cz] += 1
                if fire:
                    num[ca, cs, cz] += 1
            # ---- step 6: rule / placebo exit or the forced period end, at the open
            if (not liquidate) and price < 0:
                if fire:
                    price = o[j] * (1 - side * slip)
                    code = R_RAND if plc else R_RULE
                    comp = 0 if plc else comp_now
                elif force_end and j == end - 1:
                    price = o[j] * (1 - side * slip)
                    code = R_END
        # ---- step 7: the minute's range
        if not liquidate and price < 0:
            hit_stop = (l[j] <= stop) if side > 0 else (h[j] >= stop)
            hit_tp = has_tp and ((h[j] > tp) if side > 0 else (l[j] < tp))
            hit_liq = (ml[j] <= liq) if side > 0 else (mh[j] >= liq)
            if hit_stop:
                price = stop * (1 - side * slip)
                if hit_tp:
                    both += 1
            elif hit_liq:
                liquidate = True
            elif hit_tp:
                price = tp
                at_tp = True
            elif ladder and not entry_bar:
                fr2 = fpaid / notional
                bst = lev * (side * (mfe / fill - 1.0) - rt - fr2)
                ft = first_lock + gap
                if bst >= ft - 1e-12:
                    n = math.floor((bst - ft) / step + 1e-9)
                    lk = first_lock + step * n
                    if (not has_lock) or lk > lock_roe + 1e-12:
                        cand = fill * (1.0 + side * (lk / lev + rt + fr2))
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
                if at_tp:
                    rcode = R_TP
                elif code != R_NONE:
                    rcode = code
                else:
                    rcode = R_LOCK if has_lock else R_SL
                return wallet - equity, j, rcode, lev, price, k, both, comp
        if liquidate:
            wallet -= margin
            return wallet - equity, j, R_LIQ, lev, 0.0, k, both, 0
    return wallet - equity, end - 1, R_OPEN, lev, 0.0, k, both, 0


@njit
def account_x(S, brs, ts, o, h, l, mo, mh, ml, fund, starts, ends, sig_coin, sig_close, sig_side, sig_atr, sig_best,
              sig_i0, qty_steps, min_notionals, stop_atr, tp_kind, tp_val, ladder, first_lock, step, gap, sig_tp,
              force_end, rp, PT, PF, cst, cen, QT, qst, qen, plc, hz, seed_base, num, den, ckind, sig_lvl, bar_ms):
    """kernel.account + rules. One account over several coins (1m arrays concatenated; coin c is [starts[c], ends[c]),
    ``ends`` = the period's end, exclusive). Every signal is offered, in the order given (fill time, coin priority).
    Returns per signal: status (0 skipped, 1 entered, 2 rejected, 3 no fill, 4 not taken after bust), P&L, fill time (ms),
    exit time (ms), reason, leverage, exit price; then the final wallet and the number of minutes where stop and
    take-profit were both touched, then the F12 component mask of each signal (``tr_comp``, 0 elsewhere). ``num`` / ``den`` (N_AGE x 2 x 2, int64) collect the realised hazard counts of a rule
    run; a placebo run (plc) reads ``hz`` of the same shape.
    After a RULE or RAND exit at minute j the account is free for signals that fill at j's open (busy_until = exit - 1 ms);
    after every other exit the kernel's rule stands.
    ``bar_ms`` is the bar length of the minute arrays: a signal's fill is kernel._entry_index(ts, close + 60,000 - bar_ms)
    (the replica's close shift; 60,000 for the study's 1m bars). ``sig_lvl`` / ``ckind``: F11 (see _trade_x)."""
    n = len(sig_coin)
    shift = 60000 - bar_ms
    status = np.zeros(n, np.int8)
    pnl = np.zeros(n)
    entry_ts = np.full(n, -1, np.int64)
    exit_ts = np.zeros(n, np.int64)
    reason = np.zeros(n, np.int8)
    lev = np.zeros(n, np.int8)
    xpx = np.zeros(n)
    comp = np.zeros(n, np.int16)
    wallet = S[10]
    busy_until = -1
    bust = False
    entered_at = -1
    both_total = 0
    tr0 = np.zeros((0, TRACE_COLS))
    for q in range(n):
        c = sig_coin[q]
        a, b = starts[c], ends[c]
        tsc = ts[a:b]
        e = _entry_index(tsc, sig_close[q] + shift)
        if e < 0 or (force_end and e >= b - a - 1):
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
        d, j, r, lv_, px_, _nk, bt, cm_ = _trade_x(
            S, brs[c], tsc, o[a:b], h[a:b], l[a:b], mo[a:b], mh[a:b], ml[a:b], fund[a:b], e, b - a, sig_side[q],
            stop_atr * x, x, sig_best[q], wallet, qty_steps[c], min_notionals[c], tp_kind, tp_val, ladder, first_lock,
            step, gap, sig_tp[q], force_end, rp, sig_i0[q], PT[cst[c]:cen[c]], PF[cst[c]:cen[c]], QT[qst[c]:qen[c]], plc,
            hz, seed_base, c, num, den, tr0, ckind, sig_lvl[q])
        both_total += bt
        if r == R_REJECT:
            status[q] = 2
            continue
        status[q] = 1
        pnl[q] = d
        reason[q] = r
        lev[q] = lv_
        entry_ts[q] = t_fill
        exit_ts[q] = tsc[j]
        xpx[q] = px_
        comp[q] = cm_
        wallet += d
        busy_until = tsc[j]
        if r == R_RULE or r == R_RAND:
            busy_until = tsc[j] - 1
        entered_at = t_fill
        if r == R_OPEN:
            busy_until = 2 ** 62
        if S[9] > 0 and wallet < S[9]:
            bust = True
    return status, pnl, entry_ts, exit_ts, reason, lev, xpx, wallet, both_total, comp


def new_counts() -> tuple:
    """Fresh hazard count arrays (numerator, denominator)."""
    return np.zeros((N_AGE, 2, 2), np.int64), np.zeros((N_AGE, 2, 2), np.int64)


def new_trace(rows: int = 0) -> np.ndarray:
    return np.zeros((rows, TRACE_COLS))


# ------------------------------------------------------------------ variants (prereg 5.2-5.3)
class Variant:
    """One exit variant: family, parameters, mode ('a' keeps the pick's take-profit, 'b' has none), q15 flag, group."""
    __slots__ = ("id", "fam", "famname", "group", "mode", "q15", "params", "nparams", "order", "native_target")

    def __init__(self, id, fam, famname, group, mode, q15, params, nparams, order=0, native_target=False):
        self.id, self.fam, self.famname, self.group, self.mode, self.q15 = id, fam, famname, group, mode, q15
        self.params, self.nparams, self.order, self.native_target = dict(params), nparams, order, native_target

    def __repr__(self):
        return f"Variant({self.id})"

    def rp(self, tf_ms: int, q15_effective: bool) -> np.ndarray:
        p = self.params
        return rp_vector(self.fam, p.get("w", 0), p.get("m", 0.0), p.get("P", 0.0), p.get("g", 0.0), p.get("d", 0.0),
                         p.get("N", 0), tf_ms, q15_effective, p.get("H", 0.0), p.get("cmask"))


E0 = Variant("E0", F_NONE, "E0", "-", "a", False, {}, 0, 0)
GROUP_OF = {"F1": "S", "F2": "M", "F3": "O", "F4": "C", "F5": "G", "F6": "S", "F7": "T", "F7h": "T", "F8": "S", "F9": "S", "F10": "L",
            "F11": "N", "F12": "A"}
F11_REGISTRY: dict = {"provider": None, "modes": ("a", "b")}


def _q(q15: bool) -> str:
    return ".q15" if q15 else ""


def _build_variants() -> list:
    """The 82 rule variants of F1-F10 (F7h included) of prereg 5.3 in canonical order (table rows in order; inside a row the
    parameters ascending in the order written, then mode a before b)."""
    out = []

    def add(fam, row_q15, params, modes, idf):
        for prm in params:
            for mode in modes:
                v = dict(prm)
                nparam = {"F1": 1, "F2": 1, "F3": 0, "F4": 1, "F5": 2, "F6": 2, "F7": 1, "F7h": 1, "F8": 2, "F9": 3, "F10": 1}[fam]
                if row_q15:
                    nparam = nparam + 1 if fam in ("F1", "F4", "F9") else nparam
                    if fam in ("F1", "F4"):
                        nparam = 2
                    if fam == "F9":
                        nparam = 4
                out.append(Variant(idf(v, mode), F7H if fam == "F7h" else int(fam[1:]), fam, GROUP_OF[fam], mode, row_q15, v, nparam))
    W, M, P, G, D, N = (2, 3, 5), (1.5, 2, 3), (1, 1.5, 2), (0.25, 0.5), (0, 0.5), (12, 24, 48)
    for q in (False, True):
        add("F1", q, [{"w": w} for w in W], "ab", lambda v, m, q=q: f"F1.w{v['w']}.{m}{_q(q)}")
    add("F2", False, [{"n": n} for n in (10, 20, 50)], "ab", lambda v, m: f"F2.n{v['n']}.{m}")
    add("F3", False, [{}], "ab", lambda v, m: f"F3.{m}")
    for q in (False, True):
        add("F4", q, [{"m": m} for m in M], "ab", lambda v, m, q=q: f"F4.m{v['m']:g}.{m}{_q(q)}")
    add("F5", False, [{"P": p, "g": g} for p in P for g in G], "ab",
        lambda v, m: f"F5.P{v['P']:g}.g{int(round(v['g'] * 100))}.{m}")
    add("F6", False, [{"w": w, "d": d} for w in W for d in D], "a", lambda v, m: f"F6.w{v['w']}.d{v['d']:g}")
    add("F7", False, [{"N": n} for n in N], "ab", lambda v, m: f"F7.N{v['N']}.{m}")
    add("F7h", False, [{"H": h_} for h_ in (4, 8, 16)], "ab", lambda v, m: f"F7h.H{v['H']}.{m}")
    add("F8", False, [{"w": w, "P": p} for w in W for p in (1, 2)], "ab", lambda v, m: f"F8.w{v['w']}.P{v['P']:g}.{m}")
    for q in (False, True):
        add("F9", q, [{"w": 3, "P": 1.0, "d": 0.5}], "ab", lambda v, m, q=q: f"F9.{m}{_q(q)}")
    add("F10", False, [{"N": n} for n in (6, 12)], "ab", lambda v, m: f"F10.N{v['N']}.{m}")
    for i, v in enumerate(out):
        v.order = i + 1
    return out


_VARIANTS = _build_variants()
assert len(_VARIANTS) == 82 and len({v.id for v in _VARIANTS}) == 82
SEEN_ON_SELECT = ()          # the first revision's 'seen on select' marks were dropped (prereg 16.2)


def variants(include_f11: bool = True) -> list:
    """The 82 rule variants in canonical order (F1 ... F10, F7h included), followed by the two F11 variants and the two F12
    variants once ``register_f11`` has been called: the 86 of prereg 5.3. (F12 holds F11 as one of its nine components, so it
    exists only where the strategies' own exits do.)"""
    out = list(_VARIANTS)
    if include_f11 and F11_REGISTRY["provider"] is not None:
        for m in F11_REGISTRY["modes"]:
            out.append(Variant(f"F11.{m}", F11, "F11", GROUP_OF["F11"], m, False, {}, 0, len(out) + 1, True))
        for m in F11_REGISTRY["modes"]:
            out.append(Variant(f"F12.{m}", F12, "F12", GROUP_OF["F12"], m, False, dict(F12_PARAMS), 8, len(out) + 1, True))
    return out


def has_placebo(v: Variant) -> bool:
    """F7 and F7h read only the clock and have no placebo (prereg 6); E0 has none."""
    return v.fam not in (F_NONE, F7, F7H)


def variant_by_id(vid: str) -> Variant:
    if vid == "E0":
        return E0
    for v in variants():
        if v.id == vid:
            return v
    raise KeyError(vid)


def register_f11(provider, modes=("a", "b")) -> None:
    """Plug-in point of the strategy's own exit (F11, prereg 5.2 and Appendix A). The kernel mechanics of rules C1-C8 are
    here; the per-strategy definitions are not (they come from native.py / native_ds.py). ``provider(pick, sym, df,
    close_ms, signal_long, signal_short)`` returns either a dict
        {"comp_long": [(kind, array), ...], "comp_short": [...], "lvl_long": array|None, "lvl_short": array|None,
         "tgt_long": array|None, "tgt_short": array|None}
    (kind 'state' or 'event'; every array has one entry per chart bar of the pick's timeframe: booleans, or floats with NaN
    for 'neither fires nor arms'; ``lvl_*`` is the per-signal invalidation level and ``tgt_*`` the per-signal target, both
    indexed by the signal bar, NaN elsewhere and where there is none; at most NC components per side), or the simple
    4-tuple (long_exit, short_exit, target_long, target_short) of per-bar boolean exit arrays (event components) and
    per-signal targets. F11.a keeps the pick's take-profit; F11.b has the strategy's target or none (TP_STRUCT rule:
    used only when it lies beyond the fill, filled at the level or at a gapped open, maker). Its placebo stratum has
    precondition z = 0 (like F3)."""
    F11_REGISTRY["provider"] = provider
    F11_REGISTRY["modes"] = tuple(modes)


def clear_f11() -> None:
    F11_REGISTRY["provider"] = None


def flip_levels(side_strategy: int, side_flip: int, fill_flip: float, inv: float, tgt: float) -> tuple:
    """Prereg 11.2 (the F11 coin flip): the invalidation level and target of a position on side ``side_flip`` whose signal bar belongs to
    a strategy trade on side ``side_strategy`` (level ``inv``, target ``tgt``; NaN = none). On the strategy's own side the values
    stand. On the other side they are mirrored around the flip's fill f' at the strategy's distances: inv' = f' - side' x |f' -
    inv| and tgt' = f' + side' x (tgt - f') x s, the target only where (tgt - f') x s > 0. A NaN input gives no level / target."""
    if side_flip == side_strategy:
        return inv, tgt
    inv2 = fill_flip - side_flip * abs(fill_flip - inv) if math.isfinite(inv) else float("nan")
    ok = math.isfinite(tgt) and (tgt - fill_flip) * side_strategy > 0
    tgt2 = fill_flip + side_flip * (tgt - fill_flip) * side_strategy if ok else float("nan")
    return inv2, tgt2


def exit_of_pick(pick: dict, variant: Variant) -> tuple:
    """(stop x ATR, tp kind, tp value, ladder, first lock, lock step, gap) of the pick under the variant: the pick's own
    exit (E0, mode a) or its stop alone (mode b: no take-profit and no lock)."""
    stop_atr, tp_kind, tp_val, ladder, first_lock, step, gap = K.exit_args(pick["exit_index"])
    if variant.fam in (F11, F12) and variant.mode == "b":
        return stop_atr, TP_STRUCT, 0.0, False, first_lock, step, gap     # the strategy's target (NaN: none), never the pick's
    if variant.mode == "b":
        return stop_atr, TP_NONE, 0.0, False, first_lock, step, gap
    return stop_atr, tp_kind, tp_val, ladder, first_lock, step, gap


class Result:
    """What ``simulate`` returns: the account's per-signal arrays (offered order) and its totals."""
    __slots__ = ("status", "pnl", "entry_ts", "exit_ts", "reason", "lev", "xpx", "wallet", "both", "comp", "num", "den", "sig",
                 "w0", "variant", "scale", "period")

    def trades(self) -> np.ndarray:
        """Indices of the entered signals (status 1)."""
        return np.flatnonzero(self.status == 1)


def simulate(market, pdata, variant: Variant, scale: float = 0.25, period: str = "select", force_end: bool = True,
             hz: np.ndarray | None = None, seed_base: int = 0, placebo: bool = False, S: np.ndarray | None = None,
             offered: dict | None = None) -> Result:
    """One account: the pick ``pdata.pick`` under ``variant`` (E0, a rule variant, or its placebo when ``placebo`` with the
    hazard table ``hz``) at size ``scale`` over the period, every offered signal in order.
    ``force_end=False`` with a period that ends after the data end is the kernel's own behaviour (test T1)."""
    S = market.S(scale) if S is None else S
    off = pdata.offered(period, market) if offered is None else offered
    stop_atr, tp_kind, tp_val, ladder, first_lock, step, gap = exit_of_pick(pdata.pick, variant)
    sig_tp = pdata.targets(off) if (variant.fam in (F11, F12) and variant.mode == "b") else np.full(len(off["coin"]), np.nan)
    rp, PT, PF, QT, cst, cen, qst, qen = pdata.chart(variant)
    num, den = new_counts()
    if hz is None:
        hz = np.zeros((N_AGE, 2, 2))
    if placebo and not has_placebo(variant):
        raise ValueError(f"{variant.id} has no placebo (prereg 6)")
    ends = market.period_end(period) if force_end else market.ends
    out = account_x(S, market.brs, market.cat["ts"], market.cat["o"], market.cat["h"], market.cat["l"], market.cat["mo"],
                    market.cat["mh"], market.cat["ml"], market.cat["fund"], market.starts, ends, off["coin"], off["close"],
                    off["side"], off["atr"], off["best"], off["i0"], market.qty_steps, market.min_notionals, stop_atr,
                    tp_kind, tp_val, ladder, first_lock, step, gap, sig_tp, bool(force_end), rp, PT, PF, cst, cen, QT, qst,
                    qen, bool(placebo), np.ascontiguousarray(hz, dtype=np.float64), int(seed_base), num, den, pdata.ckind,
                    off["lvl"] if variant.fam in (F11, F12) else np.full(len(off["coin"]), np.nan), int(market.bar_ms))
    r = Result()
    (r.status, r.pnl, r.entry_ts, r.exit_ts, r.reason, r.lev, r.xpx, r.wallet, r.both, r.comp) = out
    r.num, r.den, r.sig, r.w0, r.variant, r.scale, r.period = num, den, off, float(S[10]), variant, scale, period
    return r


def simulate_trade(market, pdata, variant: Variant, off: dict, q: int, scale: float = 0.25, period: str = "select",
                   force_end: bool = True, plc: bool = False, hz: np.ndarray | None = None, seed_base: int = 0,
                   trace_rows: int = 0, equity: float = 5000.0, tp_price: float = float("nan"), minutes: dict | None = None,
                   chart: tuple | None = None, e_override: int | None = None) -> tuple:
    """One position of offered signal ``q`` (``off`` = ``pdata.offered(period)``), alone at ``equity``, with an optional
    decision trace (one row per check, TRACE_COLS columns). ``minutes`` = optional replacement arrays of the signal's coin
    (o, h, l, mo, mh, ml, fund; same length as the period's minutes of the coin) and ``chart`` = optional replacement
    (PT, PF, QT) of the coin: used by the causality tests (T5) to change what lies after a check. Returns
    (kernel tuple (wallet change, exit minute index, reason, leverage, exit price, checks, both-touched, F12 component mask),
    num, den, trace)."""
    c = int(off["coin"][q])
    a = int(market.starts[c])
    b = int(market.period_end(period)[c]) if force_end else int(market.ends[c])
    tsc = market.cat["ts"][a:b]
    e = int(_entry_index(tsc, off["close"][q] + 60000 - market.bar_ms)) if e_override is None else e_override
    stop_atr, tp_kind, tp_val, ladder, first_lock, step, gap = exit_of_pick(pdata.pick, variant)
    rp, PT, PF, QT, cst, cen, qst, qen = pdata.chart(variant)
    if chart is None:
        PT, PF, QT = PT[cst[c]:cen[c]], PF[cst[c]:cen[c]], QT[qst[c]:qen[c]]
    else:
        PT, PF, QT = chart
    num, den = new_counts()
    trace = new_trace(trace_rows)
    hz = np.zeros((N_AGE, 2, 2)) if hz is None else np.ascontiguousarray(hz, dtype=np.float64)
    m = minutes or {}
    arr = {k: m[k] if k in m else market.cat[k][a:b] for k in ("o", "h", "l", "mo", "mh", "ml", "fund")}
    atr = float(off["atr"][q])
    out = _trade_x(market.S(scale), market.brs[c], tsc, arr["o"], arr["h"], arr["l"], arr["mo"], arr["mh"], arr["ml"],
                   arr["fund"], e, b - a, int(off["side"][q]), stop_atr * atr, atr, bool(off["best"][q]), equity,
                   market.qty_steps[c], market.min_notionals[c], tp_kind, tp_val, ladder, first_lock, step, gap,
                   tp_price, bool(force_end), rp, int(off["i0"][q]), PT, PF, QT, bool(plc), hz, int(seed_base), c, num, den, trace,
                   pdata.ckind, float(off["lvl"][q]) if variant.fam in (F11, F12) else float("nan"))
    return out, num, den, trace


def warm_up(market) -> None:
    """Compile ``account_x`` once in the calling process (no signals): forked worker processes then inherit the compiled
    function instead of each compiling it. The array types are those of ``simulate``."""
    PT, PF, QT = empty_chart()
    z = np.zeros(len(market.symbols), np.int64)
    num, den = new_counts()
    e0 = np.zeros(0, np.int64)
    S = market.S(0.25)
    account_x(S, market.brs, market.cat["ts"], market.cat["o"], market.cat["h"], market.cat["l"], market.cat["mo"], market.cat["mh"],
              market.cat["ml"], market.cat["fund"], market.starts, market.ends,
              e0, e0.copy(), e0.copy(), np.zeros(0), np.zeros(0, np.bool_), e0.copy(), market.qty_steps, market.min_notionals, 4.0, TP_R, 3.0,
              False, 0.1, 0.05, 0.02, np.zeros(0), True, rp_vector(), PT, PF, z, z, QT, z, z, False, np.zeros((N_AGE, 2, 2)), 0, num, den,
              np.zeros(2 * NC, np.int8), np.zeros(0), int(market.bar_ms))
