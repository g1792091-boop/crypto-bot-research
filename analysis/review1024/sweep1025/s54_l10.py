"""Owners 10/25 night: "a month of at least +200 % (up to +1000 %), with the 10 % / 20 % ladder". The owners' wider
ladder L10 (lock 10 % net ROE at 12 %, then 20 % at 22 %, 30 % at 32 % ...) instead of L5, with stop ROE -25 / -35 / -50 %,
DeepCoin 0.14 % (and 0.08 %), fixed rules (BTC 40x / alts 30x, margin 40 %), no hold limit, one position.
(1) What the goal needs with L10: random weekday 15m moments (ETH / SOL / DOGE / LTC / BCH), k a day, the right side
(the better of long / short) with probability p -> month geometric mean and months x2 / x3 or more.
(2) The best entry so far (s21 price model, three exits agreeing, 1 / 2 / 3 a day by the causal 30-day quantile, BTC
and low-volatility moments out) traded with L10: 2022-24, 2025-26 (unseen), October 20 days."""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, MIN, KST, DAY, GT0, ms          # noqa: E402
D = FC.Data()
A_ = np.load(os.path.join(OUTD, "ml21_price.npz")); B_ = np.load(os.path.join(OUTD, "l5m48.npz"))
TT = A_["T"].astype(np.int64); CC = A_["COIN"].astype(np.int64); LOWV = B_["LOWV"]
N = len(TT)
start = D.off[CC] + (TT - GT0) // MIN; send = D.off[CC + 1]
good = (start < send - 1) & np.isfinite(D.o[np.minimum(start, len(D.o) - 1)])
STOPS = np.array([0.25, 0.35, 0.50]); NX = len(STOPS)
args = (np.ones(NX, np.int8), STOPS, np.zeros(NX, np.int8), np.zeros(NX), np.full(NX, 0.12), np.full(NX, 0.10), np.full(NX, 0.10))
lev = HB.LEVC[CC]; atrf = np.full(N, 0.01); st2 = np.where(good, start, 0)
WL, KL, _ = HB.walk_all(D.o, D.h, D.l, D.c, st2, send, np.ones(N, np.int8), lev, atrf, *args, 0.0014, HB.MARGIN, 10 ** 12)
WS, KS, _ = HB.walk_all(D.o, D.h, D.l, D.c, st2, send, -np.ones(N, np.int8), lev, atrf, *args, 0.0014, HB.MARGIN, 10 ** 12)
WL[~good] = np.nan; WS[~good] = np.nan
print("walked", N, np.nanmean(WL, 0), np.nanmean(WS, 0), flush=True)
np.savez_compressed(os.path.join(OUTD, "l10w54.npz"), WL=WL.astype(np.float32), WS=WS.astype(np.float32), KL=KL, KS=KS)
YM = FC.ym_of(TT); WKD = FC.wk(TT)
FWD_A = ms("2026-10-05 15:00")
USE = WKD & (CC != 0) & np.isfinite(WL[:, 0]) & np.isfinite(WS[:, 0]) & (YM >= 202201)


def one_pos(idx, sd, x, cost=0.0014):
    o_ = np.argsort(TT[idx], kind="stable"); idx, sd = idx[o_], sd[o_]
    W = np.where(sd > 0, WL[idx, x], WS[idx, x]).astype(float) - (cost - 0.0014) * 0.4 * lev[idx]
    K = np.where(sd > 0, KL[idx, x], KS[idx, x])
    tk = []; free = -1
    for i in range(len(idx)):
        if TT[idx[i]] >= free and np.isfinite(W[i]):
            tk.append(i); free = TT[idx[i]] + int(K[i]) * MIN
    tk = np.array(tk, int)
    return TT[idx[tk]], W[tk]


OUT = {"읽는 법": __doc__}
# (1) need curve with L10
pool = np.flatnonzero(USE & (YM <= 202609))
day = (TT[pool] + KST) // DAY; ud, st = np.unique(day, return_index=True); bd = list(st) + [len(pool)]
NEED = {}
for x in range(NX):
    right = np.where(WL[:, x] >= WS[:, x], 1, -1)
    for k in (1, 2, 4, 8):
        for p in (0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85):
            geo, x2, x3 = [], [], []
            for seed in range(3):
                g = np.random.default_rng(1000 * k + int(p * 100) + seed)
                pick = np.concatenate([pool[bd[i] + g.choice(bd[i + 1] - bd[i], size=min(k, bd[i + 1] - bd[i]), replace=False)] for i in range(len(ud))])
                sd = np.where(g.random(len(pick)) < p, right[pick], -right[pick])
                r = FC.read(*one_pos(pick, sd, x), 202201, 202609)
                geo.append(r["기하평균"]); x2.append(r["x2+"]); x3.append(r["x3+"])
            key = f"L10 손절 -{int(STOPS[x] * 100)}% / 하루 {k}번 / 맞히는 비율 {int(p * 100)}%"
            NEED[key] = {"한 달 기하평균": round(float(np.median(geo)), 3), "x2 이상 달 (57달)": int(np.median(x2)), "x3 이상 달": int(np.median(x3))}
            print(key, NEED[key], flush=True)
OUT["목표에 필요한 맞히는 비율 (L10)"] = NEED
# (2) the price model with L10
agg = np.nanmin(A_["PRED"], axis=2)
best = np.fmax(agg[:, 0], agg[:, 1]); side = np.where(agg[:, 0] >= agg[:, 1], 1, -1)
te = np.flatnonzero(np.isfinite(best) & USE & ~LOWV); te = te[np.argsort(TT[te], kind="stable")]
dd = (TT[te] + KST) // DAY; uu, ss = np.unique(dd, return_index=True); bb = list(ss) + [len(te)]
bv = best[te]
MODEL = {}
for per_day in (1, 2, 3):
    q = 1 - per_day / 480.0; keep = np.zeros(len(te), bool)
    for i, d in enumerate(uu):
        lo = np.searchsorted(dd, d - 30); hi = bb[i]
        if hi - lo < 2000:
            continue
        keep[bb[i]:bb[i + 1]] = bv[bb[i]:bb[i + 1]] > np.quantile(bv[lo:hi], q)
    k = te[keep]
    for x in range(NX):
        right = np.where(WL[k, x] >= WS[k, x], 1, -1)
        for cost in (0.0014, 0.0008):
            t2, w2 = one_pos(k, side[k], x, cost)
            rp = FC.read(t2, w2, 202201, 202412); rc = FC.read(t2, w2, 202501, 202609); fw = t2 >= FWD_A
            m25 = (YM[k] >= 202501) & (YM[k] <= 202609)
            key = f"가격 모델 · 하루 {per_day}개 / L10 손절 -{int(STOPS[x] * 100)}% / 비용 {cost * 100:.2f}%"
            MODEL[key] = {"2022-24 한 달": rp["기하평균"], "2022-24 x2+": rp["x2+"], "2025-26 한 달": rc["기하평균"], "2025-26 중간값": rc["중간값"],
                          "2025-26 x2+": rc["x2+"], "2025-26 x3+": rc["x3+"], "2025-26 -50%": rc["-50%"], "2025-26 달 진입": rc["달 진입"],
                          "2025-26 최고": rc["최고"], "2025-26 맞히는 비율": round(float((side[k][m25] == right[m25]).mean()), 3),
                          "10월 배수": round(float(np.prod(1 + w2[fw])), 3), "10월 거래": int(fw.sum())}
            print(key, MODEL[key], flush=True)
OUT["가격 모델 (L10)"] = MODEL
json.dump(OUT, open(os.path.join(OUTD, "l10_54.json"), "w"), ensure_ascii=False, indent=1, default=float)
print("done")
