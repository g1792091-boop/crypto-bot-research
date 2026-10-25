"""Owners 10/25 night: the ladder take profit they like, compared. L5 = now (net ROE 12 % -> lock 10 %, then every +5 %:
17 -> 15, 22 -> 20 ...), L10 = their proposal (12 -> 10, 22 -> 20, 32 -> 30, 42 -> 40 ...), L20 (12 -> 10, 32 -> 30,
52 -> 50 ...), L10late (first lock at 22 -> 20, then every +10). Stops ROE -35 / -50 / -75 %. The same entries re-walked:
the October 5 (A), A in the down regime (short 5), the regime bot (B entries), the price-only model's weekday picks
(s21 E5 model, thresholds 0.02 / 0.03), the meta-labeled signals (s24, thresholds 0.02 / 0.03). Weekday entries only
(owners: no weekend entries). DeepCoin costs 0.14 % and 0.08 %. Read the month: median, share of months ending >= x3 /
>= x5 / >= x10, months touching -50 %, trades a month, per trade, 2022-01 .. 2026-09 (the models' unseen span)."""
import os, sys, json, time
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
from common import COINS, MIN, grid, T0 as GT0           # noqa: E402
HB = SM.HB
T00 = time.time()
KST = 9 * 3600 * 1000; DAY = 86_400_000
PART = sys.argv[1] if len(sys.argv) > 1 else "all"


def log(*a):
    print(f"[{time.time() - T00:6.0f}s]", *a, flush=True)


LAD = {"L5 (12→10, +5)": (0.12, 0.10, 0.05), "L10 (12→10, 22→20, 32→30)": (0.12, 0.10, 0.10),
       "L20 (12→10, 32→30, 52→50)": (0.12, 0.10, 0.20), "L10late (22→20, 32→30)": (0.22, 0.20, 0.10)}
STOPS = (0.35, 0.50, 0.75)
EXS = [(s, ln) for s in STOPS for ln in LAD]

O, H, L, C, OFF = [], [], [], [], [0]
for cn in COINS:
    g = grid(cn); O.append(g["o"]); H.append(g["h"]); L.append(g["l"]); C.append(g["c"]); OFF.append(OFF[-1] + g["n"])
o = np.concatenate(O); h = np.concatenate(H); l = np.concatenate(L); cl = np.concatenate(C); off = np.array(OFF)
del O, H, L, C
b4 = bars("BTCUSDT", "4h"); REG4, _ = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
B4C = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000


def walk(t, coin, side, cost):
    """every exit for the entries (t = entry minute's time, coin index, side +-1): W, K (entries x exits)."""
    e = ((t - GT0) // MIN).astype(np.int64); start = off[coin] + e; send = off[coin + 1]
    good = (start < send - 1) & np.isfinite(o[np.minimum(start, len(o) - 1)])
    sk = np.ones(len(EXS), np.int8); sv = np.array([s for s, _ in EXS]); tk = np.zeros(len(EXS), np.int8); tv = np.zeros(len(EXS))
    lg = np.array([LAD[n][0] for _, n in EXS]); ll = np.array([LAD[n][1] for _, n in EXS]); ls = np.array([LAD[n][2] for _, n in EXS])
    W, K, _ = HB.walk_all(o, h, l, cl, np.where(good, start, 0), send, side.astype(np.int8), HB.LEVC[coin],
                          np.full(len(t), 0.01), sk, sv, tk, tv, lg, ll, ls, cost, HB.MARGIN, HB.MAXK)
    W[~good] = np.nan
    return W.astype(float), K


def one_pos(t, w, k, prio):
    o_ = np.lexsort((-prio, t)); t, w, k = t[o_], w[o_], k[o_]
    taken = []; free = -1
    for i in range(len(t)):
        if t[i] >= free and np.isfinite(w[i]):
            taken.append(i); free = t[i] + int(k[i]) * MIN
    taken = np.array(taken, int)
    return t[taken], w[taken]


def read(t, w):
    d = pd.to_datetime(t + KST, unit="ms"); ym = (d.year * 100 + d.month).to_numpy()
    ends, cnt, bust = [], [], 0
    for q in sorted(set(ym)):
        if q < 202201 or q >= 202610:
            continue
        ww = w[ym == q]; eq = np.cumprod(1 + ww)
        ends.append(float(eq[-1])); cnt.append(len(ww)); bust += bool((eq <= 0.5).any())
    ends = np.array(ends) if ends else np.array([1.0])
    sel = (ym >= 202201) & (ym < 202610)
    return {"달": len(cnt), "달 평균 진입": round(float(np.mean(cnt)), 1) if cnt else 0,
            "거래당": round(float(w[sel].mean()), 4) if sel.any() else None,
            "승률": round(float((w[sel] > 0).mean()), 3) if sel.any() else None,
            "한 달 중간값": round(float(np.median(ends)), 3), "x3 이상 달": int((ends >= 3).sum()),
            "x5 이상 달": int((ends >= 5).sum()), "x10 이상 달": int((ends >= 10).sum()), "-50% 닿은 달": int(bust),
            "가장 좋은 달": round(float(ends.max()), 2)}


SETS = {}
wk = lambda t: ((((t + KST) // DAY) + 3) % 7) < 5        # noqa: E731
if PART in ("all", "rules"):
    for lab, mems in (("10월 5개 (A)", A), ("숏5 하락장", gate(A, (1,))), ("장세별 6개 (B 진입)", B)):
        T = trades(mems, None)                        # one-position order of the original exits; re-walk each entry
        tt = T.t.to_numpy(np.int64); m = wk(tt)
        SETS[lab] = (tt[m], T.coin.to_numpy()[m].astype(np.int64), T.side.to_numpy()[m], np.zeros(m.sum()))
        log(lab, "entries", int(m.sum()))
if PART in ("all", "models", "price"):
    z = np.load(os.path.join(OUTD, "ml21_price.npz"))
    P, TT, CC = z["PRED"], z["T"], z["COIN"].astype(np.int64)
    for thr in (0.02, 0.03):
        pl, ps = P[:, 0, 2], P[:, 1, 2]
        best = np.fmax(pl, ps); side = np.where(pl >= ps, 1, -1)
        mm = np.isfinite(best) & (best > thr) & wk(TT)
        SETS[f"가격모델 자리 (기준 {thr})"] = (TT[mm], CC[mm], side[mm], best[mm])
        log("price", thr, int(mm.sum()))
if PART in ("all", "models", "meta"):
    cand = os.path.join(OUTD, "meta24_real_cand.npz")
    if os.path.exists(cand):
        m_ = np.load(cand)
        for thr in (0.02, 0.03):
            pr = m_["pred"][:, 0]
            mm = np.isfinite(pr) & (pr > thr) & wk(m_["t"])
            SETS[f"메타 라벨링 자리 (기준 {thr})"] = (m_["t"][mm], m_["coin"][mm].astype(np.int64), m_["side"][mm], pr[mm])
            log("meta", thr, int(mm.sum()))
res = {}
for lab, (t, coin, side, prio) in SETS.items():
    for cost in (0.0014, 0.0008):
        W, K = walk(t, coin, side, cost)
        for j, (s, ln) in enumerate(EXS):
            tt, ww = one_pos(t, W[:, j], K[:, j], prio)
            r = read(tt, ww)
            key = f"{lab} / 손절 ROE -{int(s * 100)}% / {ln} / 왕복 {cost * 100:.2f}%"
            res[key] = r
    log(lab, "done")
json.dump(res, open(os.path.join(OUTD, f"ladders29_{PART}.json"), "w"), ensure_ascii=False, indent=1, default=float)
for k, r in sorted(res.items(), key=lambda kv: -kv[1]["한 달 중간값"])[:25]:
    print(k, json.dumps(r, ensure_ascii=False))
