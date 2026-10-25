"""Owners 10/25 night: "the goal is the month's return, not the count of entries; test widely; no hold limit".

Every family below runs with NO hold limit (a position ends only by its stop, its take profit or ladder lock, or
liquidation), the fixed rules (BTC 40x / alts 30x, margin 40 %, one position, market orders, 6 coins), weekday entries
only (KST Mon-Fri; a position may stay open over the weekend), DeepCoin cost 0.14 % round trip (and 0.08 % payback).

Families (entry candidates; one position: the first candidate after the last exit, ties by priority):
  A  the entries found so far: October 5 (A), short 5 (A in the down regime), the regime bot's B entries, the price
     model's picks (thresholds 0.005 / 0.01 / 0.02 / 0.03), the meta-labeled signals (0.01 / 0.02 / 0.03, part "meta")
  B  always in the trend: at every weekday 15m close while flat, enter in the direction of a trend judge's state on the
     last closed 1h / 4h / 1d bar (V3.9, the trend bot's direction, EMA50/200, Supertrend 10/3, OBV, Donchian 55,
     EMA+DMI+ADX, DMI), each coin alone and the 6 coins together (the coin with the largest 4h move first);
     controls: the same with a coin-flip side, and long-only / short-only
  C  breakouts: 15m close above the high (below the low) of the last 1 / 3 / 7 days, alone and only with the V3.9 4h
     state, each coin alone and the 6 together
Exits (40): stop ROE -25 / -35 / -50 / -75 % x ladders L5 (12->10, +5), L10 (12->10, 22->20, ...), L20 (12->10,
32->30, ...), trailing T10 (lock 2 at 12, then trails 10 behind), T20 (lock 2 at 22, trails 20), wide W50 (50->25, +25),
W100 (100->50, +50), take profit ROE +50 / +100 / +200 %.
Read per KST month (start each month at 1.0, entries by their month): median month, geometric mean month, months
>= x2 / x3 / x5 / x10, months touching -50 %, entries a month; pick period 2022-01 .. 2024-12, check period 2025-01 ..
2026-09, October 2026 apart. Selection honesty: rank on the pick period only, then read the check period."""
import os, sys, json, time
import numpy as np, pandas as pd
from numba import njit
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
from common import COINS, MIN, TF_MIN, grid, T0 as GT0   # noqa: E402
from hb_common import RD                                 # noqa: E402
HB = SM.HB
T00 = time.time()
KST = 9 * 3600 * 1000; DAY = 86_400_000; M15 = 15 * MIN
PART = sys.argv[1] if len(sys.argv) > 1 else "main"
P_A, P_B = 202201, 202412; C_A, C_B = 202501, 202609; FWD = 202610


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


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


O, H, L, C, OFF = [], [], [], [], [0]
for cn in COINS:
    g = grid(cn); O.append(g["o"]); H.append(g["h"]); L.append(g["l"]); C.append(g["c"]); OFF.append(OFF[-1] + g["n"])
o = np.concatenate(O); h = np.concatenate(H); l = np.concatenate(L); cl = np.concatenate(C); off = np.array(OFF)
del O, H, L, C
wk = lambda t: ((((t + KST) // DAY) + 3) % 7) < 5        # noqa: E731
b4 = bars("BTCUSDT", "4h"); REG4, _ = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
B4C = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000


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


def read(t, w, a, b):
    ym = ym_of(t) if len(t) else np.zeros(0, np.int64)
    ends, cnt, bust = [], [], 0
    for q in months(a, b):
        ww = w[ym == q]
        eq = np.cumprod(1 + ww) if len(ww) else np.array([1.0])
        ends.append(float(eq[-1])); cnt.append(len(ww)); bust += bool((eq <= 0.5).any())
    e = np.maximum(np.array(ends), 1e-6)
    return {"중간값": round(float(np.median(e)), 3), "기하평균": round(float(np.exp(np.mean(np.log(e)))), 3),
            "x2+": int((e >= 2).sum()), "x3+": int((e >= 3).sum()), "x5+": int((e >= 5).sum()), "x10+": int((e >= 10).sum()),
            "-50%": int(bust), "달": len(e), "달 진입": round(float(np.mean(cnt)), 1), "최고": round(float(e.max()), 2)}


def run(t, coin, side, prio, cost):
    """all 40 exits for one candidate set; returns {exit: {pick, check, oct}}."""
    o_ = np.lexsort((-prio, t)); t, coin, side = t[o_], coin[o_].astype(np.int64), side[o_].astype(np.int64)
    e = ((t - GT0) // MIN).astype(np.int64); cst = off[coin] + e; csend = off[coin + 1]
    lev = HB.LEVC[coin].astype(np.float64)
    out = {}
    for s, pn in EXS:
        tk, tv, lg, ll, ls = PROF[pn]
        ti, w, _k = seq_sim(o, h, l, cl, cst, side, t, csend, lev, s, tk, tv, lg, ll, ls, cost, HB.MARGIN)
        tt = t[ti]
        out[f"손절{int(s * 100)} {pn}"] = {"고르기": read(tt, w, P_A, P_B), "확인": read(tt, w, C_A, C_B),
                                       "10월": read(tt, w, FWD, FWD)}
    return out


SETS = {}
# ---------------------------------------------------------------- family A
if PART == "main":
    for lab, mems in (("A 10월 5개", A), ("A 숏5 하락장", gate(A, (1,))), ("A 장세별 6개", B)):
        T = trades(mems, None)
        tt = T.t.to_numpy(np.int64); m = wk(tt)
        SETS[lab] = (tt[m], T.coin.to_numpy()[m], T.side.to_numpy()[m], np.zeros(m.sum()))
    z = np.load(os.path.join(OUTD, "ml21_price.npz"))
    P, TT, CC = z["PRED"], z["T"], z["COIN"].astype(np.int64)
    pl, ps = P[:, 0, 2], P[:, 1, 2]; best = np.fmax(pl, ps); sd_ = np.where(pl >= ps, 1, -1)
    for thr in (0.005, 0.01, 0.02, 0.03):
        mm = np.isfinite(best) & (best > thr) & wk(TT)
        SETS[f"A 가격모델 {thr}"] = (TT[mm], CC[mm], sd_[mm], best[mm])
if PART == "meta":
    m_ = np.load(os.path.join(OUTD, "meta24_real_cand.npz"))
    for x in (0, 1):
        for thr in (0.01, 0.02, 0.03):
            pr = m_["pred"][:, x]
            mm = np.isfinite(pr) & (pr > thr) & wk(m_["t"])
            SETS[f"A 메타 {['계단ROE-75', '계단2ATR'][x]} {thr}"] = (m_["t"][mm], m_["coin"][mm], m_["side"][mm], pr[mm])
    z = np.load(os.path.join(OUTD, "ml21_price.npz"))
    P, TT, CC = z["PRED"], z["T"], z["COIN"].astype(np.int64)
    pl, ps = P[:, 0, 2], P[:, 1, 2]; best = np.fmax(pl, ps); sd_ = np.where(pl >= ps, 1, -1)
    for mthr in (0.02, 0.03):
        pr = m_["pred"][:, 0]; mm = np.isfinite(pr) & (pr > mthr) & wk(m_["t"])
        for pthr in (0.01, 0.02):
            pm = np.isfinite(best) & (best > pthr) & wk(TT)
            SETS[f"A 메타 {mthr} + 가격모델 {pthr} 합치기"] = (np.r_[m_["t"][mm], TT[pm]], np.r_[m_["coin"][mm], CC[pm]],
                                                    np.r_[m_["side"][mm], sd_[pm]], np.r_[pr[mm], best[pm]])
# ---------------------------------------------------------------- 15m closes per coin, the trend states at them
if PART == "main":
    Q = {}
    for ci, cn in enumerate(COINS):
        b = bars(cn, "15m"); T = b.ts.to_numpy(np.int64) + M15
        keep = wk(T) & (T >= ms("2021-06-01")) & (T < ms("2026-10-24 14:12"))
        c = b.close.to_numpy(); hh = b.high.to_numpy(); ll_ = b.low.to_numpy()
        r16 = np.abs(np.log(c) - np.log(np.r_[np.full(16, np.nan), c[:-16]]))
        st = {}
        for tf in ("1h", "4h", "1d"):
            Zs = RD._states(cn, tf); close = Zs["ts"] + TF_MIN[tf] * MIN
            j = np.searchsorted(close, T, side="right") - 1; ok = j >= 0; jj = np.clip(j, 0, None)
            nbok = ok & (Zs["nb"][jj] >= 300)
            for k in ("j_V39", "j_dir", "c_T1_EMA50_200", "c_T5_ST10_3", "c_OBV_S", "c_T6_DON55", "c_S6_EMA_DMI_ADX",
                      "c_N24_DMI"):
                if k in Zs:
                    st[f"{k}@{tf}"] = np.where(nbok, Zs[k][jj], 0).astype(np.int64)
        brk = {}
        for nd, nb_ in ((1, 96), (3, 288), (7, 672)):
            hi = pd.Series(hh).shift(1).rolling(nb_).max().to_numpy(); lo = pd.Series(ll_).shift(1).rolling(nb_).min().to_numpy()
            brk[nd] = np.where(c > hi, 1, np.where(c < lo, -1, 0)).astype(np.int64)
        Q[ci] = {"T": T[keep], "r16": np.nan_to_num(r16[keep]), "st": {k: v[keep] for k, v in st.items()},
                 "brk": {k: v[keep] for k, v in brk.items()}}
    log("15m states ready", list(Q[0]["st"].keys()))
    JUDGES = list(Q[0]["st"].keys())

    def cand(per_coin, coins):
        """candidates from per-coin side arrays (0 = none) on the coins listed; priority = the coin's 4h move."""
        ts, cs, ss, ps = [], [], [], []
        for ci in coins:
            sd = per_coin(ci); m = sd != 0
            ts.append(Q[ci]["T"][m]); cs.append(np.full(m.sum(), ci)); ss.append(sd[m]); ps.append(Q[ci]["r16"][m])
        return np.concatenate(ts), np.concatenate(cs), np.concatenate(ss), np.concatenate(ps)

    rng = np.random.default_rng(35)
    for jn in JUDGES:
        for co in list(range(6)) + ["6개"]:
            coins = range(6) if co == "6개" else [co]
            nm = "6개" if co == "6개" else COINS[co].replace("USDT", "")
            SETS[f"B 추세 따라 항상 / {jn} / {nm}"] = cand(lambda ci: Q[ci]["st"][jn], coins)
    for co in list(range(6)) + ["6개"]:
        coins = range(6) if co == "6개" else [co]
        nm = "6개" if co == "6개" else COINS[co].replace("USDT", "")
        SETS[f"B 대조 동전던지기 / {nm}"] = cand(lambda ci: rng.choice(np.array([-1, 1]), len(Q[ci]["T"])), coins)
        SETS[f"B 대조 롱만 / {nm}"] = cand(lambda ci: np.ones(len(Q[ci]["T"]), np.int64), coins)
        SETS[f"B 대조 숏만 / {nm}"] = cand(lambda ci: -np.ones(len(Q[ci]["T"]), np.int64), coins)
    for nd in (1, 3, 7):
        for flt in ("", "V39@4h"):
            for co in list(range(6)) + ["6개"]:
                coins = range(6) if co == "6개" else [co]
                nm = "6개" if co == "6개" else COINS[co].replace("USDT", "")
                if flt:
                    f_ = lambda ci, nd=nd: np.where(Q[ci]["brk"][nd] == Q[ci]["st"]["j_V39@4h"], Q[ci]["brk"][nd], 0)  # noqa: E731
                else:
                    f_ = lambda ci, nd=nd: Q[ci]["brk"][nd]  # noqa: E731
                SETS[f"C 돌파 {nd}일{' +V39 4h' if flt else ''} / {nm}"] = cand(f_, coins)
log("sets", len(SETS))
res = {}
for n, (lab, (t, coin, side, prio)) in enumerate(SETS.items()):
    res[lab] = {}
    for cost in (0.0014, 0.0008):
        res[lab][f"{cost * 100:.2f}%"] = run(np.asarray(t, np.int64), np.asarray(coin), np.asarray(side), np.asarray(prio, float), cost)
    if n % 20 == 0:
        log(n, "/", len(SETS), lab)
json.dump(res, open(os.path.join(OUTD, f"free35_{PART}.json"), "w"), ensure_ascii=False, default=float)
log("saved")
# ---------------------------------------------------------------- read: rank on the pick period, look at the check period
rows = []
for lab, byc in res.items():
    for cst_, byx in byc.items():
        for xn, r in byx.items():
            rows.append((lab, cst_, xn, r["고르기"], r["확인"], r["10월"]))
for cst_ in ("0.14%", "0.08%"):
    rr = [x for x in rows if x[1] == cst_ and not x[0].startswith("B 대조")]
    print(f"\n== {cst_}: top 15 by the pick period's geometric mean month (2022-01..2024-12), then the check period (2025-01..2026-09)")
    for lab, _, xn, p, c, f in sorted(rr, key=lambda x: -x[3]["기하평균"])[:15]:
        print(f"{lab} | {xn} | 고르기 기하 ×{p['기하평균']} 중간 ×{p['중간값']} x3+ {p['x3+']} x5+ {p['x5+']} -50% {p['-50%']} /월 {p['달 진입']}"
              f" || 확인 기하 ×{c['기하평균']} 중간 ×{c['중간값']} x3+ {c['x3+']} x5+ {c['x5+']} -50% {c['-50%']} || 10월 ×{f['중간값']}")
    ctl = [x for x in rows if x[1] == cst_ and x[0].startswith("B 대조")]
    print("controls best by pick:", [(x[0], x[2], x[3]["기하평균"], x[4]["기하평균"]) for x in sorted(ctl, key=lambda x: -x[3]["기하평균"])[:5]])
    print("count with check median >= x3:", sum(1 for x in rr if x[4]["중간값"] >= 3), "/ check geometric >= x2:",
          sum(1 for x in rr if x[4]["기하평균"] >= 2), "of", len(rr))
log("done")
