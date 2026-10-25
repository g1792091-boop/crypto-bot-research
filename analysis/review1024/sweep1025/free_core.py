"""Shared parts of the no-hold-limit monthly-return sweeps (s35, s36): one-position walker without a hold limit, the
40 exits, the month read (with the month stop / lock variants), 15m-close data per coin."""
import os, sys
import numpy as np, pandas as pd
from numba import njit
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.path.insert(0, "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/hunt1025")
import hb_build as HB                                    # noqa: E402
from hb_common import RD                                 # noqa: E402
from common import COINS, MIN, TF_MIN, grid, bars, ms, T0 as GT0   # noqa: E402

KST = 9 * 3600 * 1000; DAY = 86_400_000; M15 = 15 * MIN
P_A, P_B = 202201, 202412; C_A, C_B = 202501, 202609; FWD = 202610
PROF = {"L5": (0, 0.0, 0.12, 0.10, 0.05), "L10": (0, 0.0, 0.12, 0.10, 0.10), "L20": (0, 0.0, 0.12, 0.10, 0.20),
        "T10": (0, 0.0, 0.12, 0.02, 0.10), "T20": (0, 0.0, 0.22, 0.02, 0.20), "W50": (0, 0.0, 0.50, 0.25, 0.25),
        "W100": (0, 0.0, 1.00, 0.50, 0.50), "TP50": (1, 0.50, 0.0, 0.0, 1.0), "TP100": (1, 1.00, 0.0, 0.0, 1.0),
        "TP200": (1, 2.00, 0.0, 0.0, 1.0)}
STOPS = (0.25, 0.35, 0.50, 0.75)
EXS = [(s, p) for s in STOPS for p in ("L5", "L10")]       # owners: only their two ladders


@njit(cache=True)
def seq_sim(o, h, l, c, cst, cside, ct, csend, clev, sv, tk, tv, lg, ll, ls, cost, margin):
    """one position, no hold limit: candidates in time order (ties already by priority); returns taken index, w, k."""
    n = len(cst)
    TI = np.empty(n, np.int64); TW = np.empty(n, np.float64); TK = np.empty(n, np.int64); m = 0
    free = -1
    for i in range(n):
        if ct[i] < free:
            continue
        e0 = cst[i]; e1 = csend[i]
        if e0 >= e1 - 1:
            continue
        p0 = o[e0]
        if not (p0 > 0):
            continue
        L = clev[i]; sd = cside[i]
        dliq = 1.0 / L - 0.005
        d = sv / L - cost
        if d <= 0.0005:
            d = 0.0005
        liq = d >= dliq
        if liq:
            d = dliq
        u = 1e9
        if tk == 1:
            u = tv / L + cost
        g1 = lg / L + cost if lg > 0 else 1e9
        l1 = ll / L + cost; stp = ls / L
        lock = -1e9; best = 0.0; mv = 0.0; why = 3; kk = e1 - e0 - 1
        for j in range(e0, e1):
            if sd > 0:
                oj = o[j] / p0 - 1; lj = l[j] / p0 - 1; hj = h[j] / p0 - 1
            else:
                oj = 1 - o[j] / p0; lj = 1 - h[j] / p0; hj = 1 - l[j] / p0
            floor = max(-d, lock)
            if oj <= floor:
                mv = oj; why = 0 if lock < -d + 1e-12 else 1; kk = j - e0; break
            if lj <= floor:
                mv = floor; why = 0 if lock == -1e9 else 1; kk = j - e0; break
            if hj >= u:
                mv = max(u, oj); why = 2; kk = j - e0; break
            if hj > best:
                best = hj
                if best >= g1:
                    nl = l1 + np.floor((best - g1) / stp + 1e-9) * stp
                    if nl > lock:
                        lock = nl
            if j == e1 - 1:
                mv = c[j] / p0 - 1 if sd > 0 else 1 - c[j] / p0
                kk = j - e0
        if why == 0 and liq and mv <= -d + 1e-12:
            w = -margin
        else:
            w = margin * L * (mv - cost)
            if w < -margin:
                w = -margin
        TI[m] = i; TW[m] = w; TK[m] = kk + 1; m += 1
        free = ct[i] + (kk + 1) * 60_000
    return TI[:m], TW[:m], TK[:m]


class Data:
    def __init__(self):
        O, H, L, C, OFF = [], [], [], [], [0]
        for cn in COINS:
            g = grid(cn); O.append(g["o"]); H.append(g["h"]); L.append(g["l"]); C.append(g["c"]); OFF.append(OFF[-1] + g["n"])
        self.o = np.concatenate(O); self.h = np.concatenate(H); self.l = np.concatenate(L); self.c = np.concatenate(C)
        self.off = np.array(OFF)


def wk(t):
    return ((((t + KST) // DAY) + 3) % 7) < 5


def ym_of(t):
    d = pd.to_datetime(t + KST, unit="ms")
    return (d.year * 100 + d.month).to_numpy()


def months(a, b):
    out = []
    y, m = a // 100, a % 100
    while y * 100 + m <= b:
        out.append(y * 100 + m); m += 1
        if m == 13:
            y += 1; m = 1
    return out


def month_ends(t, w, a, b, stop=None, lock=None):
    """each KST month from 1.0; with ``stop`` no more entries that month once the month's equity is at or below it,
    with ``lock`` none once it is at or above it."""
    ym = ym_of(t) if len(t) else np.zeros(0, np.int64)
    ends, cnt, bust = [], [], 0
    for q in months(a, b):
        eq = 1.0; low = 1.0; n = 0
        for v in w[ym == q]:
            if (stop is not None and eq <= stop) or (lock is not None and eq >= lock):
                break
            eq *= 1 + v; n += 1; low = min(low, eq)
        ends.append(eq); cnt.append(n); bust += low <= 0.5
    return np.maximum(np.array(ends), 1e-6), np.array(cnt), bust


def read(t, w, a, b, stop=None, lock=None):
    e, cnt, bust = month_ends(t, w, a, b, stop, lock)
    return {"중간값": round(float(np.median(e)), 3), "기하평균": round(float(np.exp(np.mean(np.log(e)))), 3),
            "x2+": int((e >= 2).sum()), "x3+": int((e >= 3).sum()), "x5+": int((e >= 5).sum()), "x10+": int((e >= 10).sum()),
            "-50%": int(bust), "달": len(e), "달 진입": round(float(np.mean(cnt)), 1), "최고": round(float(e.max()), 2)}


def run(D, t, coin, side, prio, cost, mm=False):
    """all 40 exits for one candidate set; returns {exit: {pick, check, oct}} (+ month stop / lock reads if mm)."""
    o_ = np.lexsort((-prio, t)); t, coin, side = t[o_], coin[o_].astype(np.int64), side[o_].astype(np.int64)
    e = ((t - GT0) // MIN).astype(np.int64); cst = D.off[coin] + e; csend = D.off[coin + 1]
    lev = HB.LEVC[coin].astype(np.float64)
    out = {}
    for s, pn in EXS:
        tk, tv, lg, ll, ls = PROF[pn]
        ti, w, _k = seq_sim(D.o, D.h, D.l, D.c, cst, side, t, csend, lev, s, tk, tv, lg, ll, ls, cost, HB.MARGIN)
        tt = t[ti]
        r = {"고르기": read(tt, w, P_A, P_B), "확인": read(tt, w, C_A, C_B), "10월": read(tt, w, FWD, FWD)}
        if mm:
            r["고르기 월-30%멈춤"] = read(tt, w, P_A, P_B, stop=0.7); r["확인 월-30%멈춤"] = read(tt, w, C_A, C_B, stop=0.7)
            r["고르기 월-30%멈춤·x3잠금"] = read(tt, w, P_A, P_B, stop=0.7, lock=3.0)
            r["확인 월-30%멈춤·x3잠금"] = read(tt, w, C_A, C_B, stop=0.7, lock=3.0)
        out[f"손절{int(s * 100)} {pn}"] = r
    return out


def q15(t_from="2021-06-01", t_to="2026-10-24 14:12"):
    """per coin: weekday 15m closes T, |4h move| for priority, the trend states (1h / 4h / 1d) at T."""
    Q = {}
    for ci, cn in enumerate(COINS):
        b = bars(cn, "15m"); T = b.ts.to_numpy(np.int64) + M15
        keep = wk(T) & (T >= ms(t_from)) & (T < ms(t_to))
        c = b.close.to_numpy()
        r16 = np.log(c) - np.log(np.r_[np.full(16, np.nan), c[:-16]])
        st = {}
        for tf in ("1h", "4h", "1d"):
            Zs = RD._states(cn, tf); close = Zs["ts"] + TF_MIN[tf] * MIN
            j = np.searchsorted(close, T, side="right") - 1; ok = j >= 0; jj = np.clip(j, 0, None)
            nbok = ok & (Zs["nb"][jj] >= 300)
            for k in ("j_V39", "j_dir", "c_T1_EMA50_200", "c_T5_ST10_3", "c_OBV_S", "c_T6_DON55", "c_S6_EMA_DMI_ADX",
                      "c_N24_DMI"):
                if k in Zs:
                    st[f"{k}@{tf}"] = np.where(nbok, Zs[k][jj], 0).astype(np.int64)
        Q[ci] = {"T": T, "keep": keep, "c": c, "h": b.high.to_numpy(), "l": b.low.to_numpy(), "r16": r16, "st": st}
    return Q


def cand(Q, per_coin, coins):
    """candidates from per-coin side arrays over the full 15m index (0 = none) on the coins listed, weekday closes in
    range only; priority = the coin's |4h move|."""
    ts, cs, ss, ps = [], [], [], []
    for ci in coins:
        sd = np.asarray(per_coin(ci)); m = (sd != 0) & Q[ci]["keep"]
        ts.append(Q[ci]["T"][m]); cs.append(np.full(m.sum(), ci)); ss.append(sd[m]); ps.append(np.nan_to_num(np.abs(Q[ci]["r16"][m])))
    return np.concatenate(ts), np.concatenate(cs), np.concatenate(ss), np.concatenate(ps)


@njit(cache=True)
def seq_sim_pull(o, h, l, c, cst, cside, ct, csend, clev, wait, r, sv, tk, tv, lg, ll, ls, cost, margin, conf=False):
    """as seq_sim, but after a signal wait up to ``wait`` minutes for the price to come back ``r`` against the signal
    (from the signal minute's open); enter at market when it does (at the trigger, or at the open if it gaps past it),
    skip the signal if it does not. Conservative: in the touch minute only the adverse side counts. ``conf``: the other
    way round, enter once the price has gone ``r`` WITH the signal (a confirmation; the fill is the worse price)."""
    n = len(cst)
    TI = np.empty(n, np.int64); TW = np.empty(n, np.float64); TT = np.empty(n, np.int64); m = 0
    free = -1
    for i in range(n):
        if ct[i] < free:
            continue
        es = cst[i]; e1 = csend[i]; sd = cside[i]
        if es >= e1 - 2:
            continue
        ps = o[es]
        if not (ps > 0):
            continue
        if conf:
            trig = ps * (1 + r) if sd > 0 else ps * (1 - r)
        else:
            trig = ps * (1 - r) if sd > 0 else ps * (1 + r)
        j0 = -1
        for j in range(es, min(es + wait, e1 - 1)):
            if conf:
                if sd > 0 and h[j] >= trig:
                    j0 = j; break
                if sd < 0 and l[j] <= trig:
                    j0 = j; break
            else:
                if sd > 0 and l[j] <= trig:
                    j0 = j; break
                if sd < 0 and h[j] >= trig:
                    j0 = j; break
        if j0 < 0:
            continue
        p0 = trig
        if conf:
            if sd > 0 and o[j0] > trig:
                p0 = o[j0]
            if sd < 0 and o[j0] < trig:
                p0 = o[j0]
        else:
            if sd > 0 and o[j0] < trig:
                p0 = o[j0]
            if sd < 0 and o[j0] > trig:
                p0 = o[j0]
        L = clev[i]
        dliq = 1.0 / L - 0.005
        d = sv / L - cost
        if d <= 0.0005:
            d = 0.0005
        liq = d >= dliq
        if liq:
            d = dliq
        u = 1e9
        if tk == 1:
            u = tv / L + cost
        g1 = lg / L + cost if lg > 0 else 1e9
        l1 = ll / L + cost; stp = ls / L
        lock = -1e9; best = 0.0; mv = 0.0; why = 3; kk = e1 - j0 - 1
        adv0 = (l[j0] / p0 - 1) if sd > 0 else (1 - h[j0] / p0)
        if adv0 <= -d:
            mv = -d; why = 0; kk = 0
        else:
            for j in range(j0 + 1, e1):
                if sd > 0:
                    oj = o[j] / p0 - 1; lj = l[j] / p0 - 1; hj = h[j] / p0 - 1
                else:
                    oj = 1 - o[j] / p0; lj = 1 - h[j] / p0; hj = 1 - l[j] / p0
                floor = max(-d, lock)
                if oj <= floor:
                    mv = oj; why = 0 if lock < -d + 1e-12 else 1; kk = j - j0; break
                if lj <= floor:
                    mv = floor; why = 0 if lock == -1e9 else 1; kk = j - j0; break
                if hj >= u:
                    mv = max(u, oj); why = 2; kk = j - j0; break
                if hj > best:
                    best = hj
                    if best >= g1:
                        nl = l1 + np.floor((best - g1) / stp + 1e-9) * stp
                        if nl > lock:
                            lock = nl
                if j == e1 - 1:
                    mv = c[j] / p0 - 1 if sd > 0 else 1 - c[j] / p0
                    kk = j - j0
        if why == 0 and liq and mv <= -d + 1e-12:
            w = -margin
        else:
            w = margin * L * (mv - cost)
            if w < -margin:
                w = -margin
        TI[m] = i; TW[m] = w; TT[m] = ct[i] + (j0 - es) * 60_000; m += 1
        free = ct[i] + (j0 - es + kk + 1) * 60_000
    return TI[:m], TW[:m], TT[:m]


def run_pull(D, t, coin, side, prio, cost, wait, r, exits=None, conf=False):
    o_ = np.lexsort((-prio, t)); t, coin, side = t[o_], coin[o_].astype(np.int64), side[o_].astype(np.int64)
    e = ((t - GT0) // MIN).astype(np.int64); cst = D.off[coin] + e; csend = D.off[coin + 1]
    lev = HB.LEVC[coin].astype(np.float64)
    out = {}
    for s, pn in (exits or EXS):
        tk, tv, lg, ll, ls = PROF[pn]
        ti, w, tt = seq_sim_pull(D.o, D.h, D.l, D.c, cst, side, t, csend, lev, wait, r, s, tk, tv, lg, ll, ls, cost, HB.MARGIN, conf)
        out[f"손절{int(s * 100)} {pn}"] = {"고르기": read(tt, w, P_A, P_B), "확인": read(tt, w, C_A, C_B), "10월": read(tt, w, FWD, FWD),
                                       "승률": round(float((w > 0).mean()), 3) if len(w) else None,
                                       "거래당": round(float(w.mean()), 4) if len(w) else None}
    return out
