"""Owners 10/25 night: "is it really impossible? analyse deeper". What the goal needs, on real prices.
Every weekday 15m close on ETH / SOL / DOGE / LTC / BCH (BTC out, s41) has the real result of a long and of a short with
the owners' exit (L5, stop ROE -25 % or -35 %, DeepCoin 0.14 %, fixed rules, no hold limit). The better side of the two
is the "right" side. A trader who picks k moments a day at random and the right side with probability p, one position
at a time, earns what? -> the accuracy p the goal (a month x3 / x5 / x10) needs, for k = 1 .. 8 a day.
Then the best entry found so far (the s21 price model, three exits agreeing, 1 / 2 / 3 picks a day by the causal
30-day quantile, BTC and low-volatility moments out): how often it picks the right side, and how much its moments are
worth (the right side's result, i.e. its timing), on 2022-24 and 2025-26, and in which slices (coin, side, hour,
volatility, BTC 4h trend, weekday) it comes closest to the need on BOTH periods."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import KST, DAY, MIN, bars               # noqa: E402
sys.path.insert(0, "/home/user/crypto-bot-research")
from paperbot.rmember import regimes                     # noqa: E402
A_ = np.load(os.path.join(OUTD, "ml21_price.npz")); B_ = np.load(os.path.join(OUTD, "l5m48.npz"))
TT = B_["T"].astype(np.int64); CC = B_["COIN"].astype(np.int64); LOWV = B_["LOWV"]
WL, WS, KL, KS = B_["WL"], B_["WS"], B_["KL"], B_["KS"]                 # (n, 2): L5 stop -25 % / -35 % at 0.14 %
PA = A_["PRED"]
YM = FC.ym_of(TT)
WKD = FC.wk(TT)
USE = WKD & (CC != 0) & np.isfinite(WL[:, 0]) & np.isfinite(WS[:, 0]) & (YM >= 202201) & (YM <= 202609)
OUT = {"읽는 법": __doc__}


def one_pos(idx, sd, x):
    """time-ordered candidates idx with side sd (1 long, -1 short): one position; returns times and wallet results."""
    o_ = np.argsort(TT[idx], kind="stable"); idx, sd = idx[o_], sd[o_]
    W = np.where(sd > 0, WL[idx, x], WS[idx, x]).astype(float); K = np.where(sd > 0, KL[idx, x], KS[idx, x])
    tk = []; free = -1
    for i in range(len(idx)):
        if TT[idx[i]] >= free and np.isfinite(W[i]):
            tk.append(i); free = TT[idx[i]] + int(K[i]) * MIN
    tk = np.array(tk, int)
    return TT[idx[tk]], W[tk]


def months_read(t, w, a, b):
    r = FC.read(t, w, a, b)
    return r["기하평균"], r["중간값"], r["x3+"], r["-50%"], r["달 진입"]


# ---------------------------------------------------------------- (1) the need: accuracy p vs monthly result
pool = np.flatnonzero(USE)
day = (TT[pool] + KST) // DAY
ud, st = np.unique(day, return_index=True); bd = list(st) + [len(pool)]
NEED = {}
for x, xn in ((0, "손절 -25%"), (1, "손절 -35%")):
    right = np.where(WL[:, x] >= WS[:, x], 1, -1)
    for k in (1, 2, 4, 8):
        for p in (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 1.0):
            geo, x3 = [], []
            for seed in range(4):
                g = np.random.default_rng(1000 * k + int(p * 100) + seed)
                pick = np.concatenate([pool[bd[i] + g.choice(bd[i + 1] - bd[i], size=min(k, bd[i + 1] - bd[i]), replace=False)] for i in range(len(ud))])
                sd = np.where(g.random(len(pick)) < p, right[pick], -right[pick])
                t, w = one_pos(pick, sd, x)
                gm, md, n3, b50, ent = months_read(t, w, 202201, 202609)
                geo.append(gm); x3.append(n3)
            NEED[f"{xn} / 하루 {k}번 / 맞히는 비율 {int(p * 100)}%"] = {"한 달 기하평균": round(float(np.median(geo)), 3),
                                                                     "x3 이상 달 (57달 중)": int(np.median(x3))}
            print(xn, k, p, round(float(np.median(geo)), 3), flush=True)
OUT["목표에 필요한 맞히는 비율 (무작위 시점)"] = NEED
# ---------------------------------------------------------------- (2) the best entry so far: accuracy and timing
agg = np.nanmin(PA, axis=2)
best = np.fmax(agg[:, 0], agg[:, 1]); side = np.where(agg[:, 0] >= agg[:, 1], 1, -1)
te = np.flatnonzero(np.isfinite(best) & USE & ~LOWV)
te = te[np.argsort(TT[te], kind="stable")]
dday = (TT[te] + KST) // DAY; uu, ss = np.unique(dday, return_index=True); bb = list(ss) + [len(te)]
bv = best[te]
# attributes for slices
b4 = bars("BTCUSDT", "4h"); RB, _ = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
CB = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000
HR = ((TT + KST) // 3600_000) % 24
SES = np.where((HR >= 9) & (HR < 16), "아시아 09-16", np.where((HR >= 16) & (HR < 22), "유럽 16-22", np.where((HR >= 22) | (HR < 2), "미국 22-02", "새벽 02-09")))
jb = np.searchsorted(CB, TT, side="right") - 1
BTCR = np.array(["상승", "하락", "횡보"])[np.where(jb >= 0, RB[np.clip(jb, 0, None)], 2)]
WDAY = np.array(["월", "화", "수", "목", "금", "토", "일"])[((((TT + KST) // DAY) + 3) % 7)]
COINN = np.array(["BTC", "ETH", "SOL", "DOGE", "LTC", "BCH"])[CC]
MODEL = {}
for per_day in (1, 2, 3):
    q = 1 - per_day / 480.0; keep = np.zeros(len(te), bool)
    for i, d in enumerate(uu):
        lo = np.searchsorted(dday, d - 30); hi = bb[i]
        if hi - lo < 2000:
            continue
        keep[bb[i]:bb[i + 1]] = bv[bb[i]:bb[i + 1]] > np.quantile(bv[lo:hi], q)
    k = te[keep]
    for x, xn in ((0, "손절 -25%"), (1, "손절 -35%")):
        right = np.where(WL[:, x] >= WS[:, x], 1, -1)
        t, w = one_pos(k, side[k], x)
        rows = {}
        for lab, a, b in (("2022-24", 202201, 202412), ("2025-26", 202501, 202609)):
            m = (YM[k] >= a) & (YM[k] <= b)
            acc = float((side[k][m] == right[k][m]).mean())
            # timing: what the right side would have paid at these moments vs at random moments of the same days
            perfect_here = float(np.maximum(WL[k[m], x], WS[k[m], x]).mean())
            pm = USE & (YM >= a) & (YM <= b) & ~LOWV
            perfect_rand = float(np.nanmean(np.maximum(WL[pm, x], WS[pm, x])))
            gm, md, n3, b50, ent = months_read(t, w, a, b)
            rows[lab] = {"맞히는 비율": round(acc, 3), "고른 시점의 맞는 쪽 평균": round(perfect_here, 4), "아무 시점의 맞는 쪽 평균": round(perfect_rand, 4),
                         "한 달 기하평균": gm, "달 진입": ent}
        # slices: accuracy on both periods
        sl = {}
        for dim, arr in (("코인", COINN), ("방향", np.where(side > 0, "롱", "숏")), ("시간대", SES), ("BTC 4시간 장세", BTCR), ("요일", WDAY)):
            for v in np.unique(arr[k]):
                r_ = {}
                for lab, a, b in (("2022-24", 202201, 202412), ("2025-26", 202501, 202609)):
                    m = (YM[k] >= a) & (YM[k] <= b) & (arr[k] == v)
                    if m.sum() >= 20:
                        wr = np.where(side[k][m] > 0, WL[k[m], x], WS[k[m], x])
                        r_[lab] = {"신호": int(m.sum()), "맞히는 비율": round(float((side[k][m] == right[k][m]).mean()), 3),
                                   "신호당": round(float(np.nanmean(wr)), 4)}
                sl[f"{dim} {v}"] = r_
        rows["구간별"] = sl
        MODEL[f"하루 {per_day}개 / {xn}"] = rows
        print("model", per_day, xn, rows["2022-24"], rows["2025-26"], flush=True)
OUT["지금 가장 좋은 진입 (가격 모델)"] = MODEL
json.dump(OUT, open(os.path.join(OUTD, "needacc50.json"), "w"), ensure_ascii=False, indent=1, default=float)
print("done")
