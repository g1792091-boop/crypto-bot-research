"""Owners 10/25 night, "deeper": s50 showed the goal needs the right side about 75 % of the time at 4 or more tries a
day (L5, stop ROE -25 %), while the best entry so far is right 60-66 %. So train for exactly that: a classifier of the
right side (the better of long / short with the owners' exit, L5 stop ROE -25 %, 0.14 %) on the s21 price features,
half-year walk-forward blocks 2022-01 .. 2026-10 (training ends 3 days before each block, every 3rd sample, 600 trees).
Trading: at each weekday 15m close (BTC and low-volatility moments out, s41) the most confident coin, the top k a day by
the causal 30-day quantile of the confidence, one position. Read accuracy and months on 2022-24, 2025-26, October."""
import os, sys, json
import numpy as np, pandas as pd
import lightgbm as lgb
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.argv = [sys.argv[0], "price"]
src = open(os.path.join(HERE, "s21_mlprice.py")).read()
exec(src.split("# ---------------------------------------------------------------- labels: walk long and short")[0])
import free_core as FC                                    # noqa: E402
B_ = np.load(os.path.join(OUTD, "l5m48.npz"))
Tm = MT["T"].to_numpy(); assert (B_["T"] == Tm).all()
WL, WS, KL, KS, LOWV = B_["WL"], B_["WS"], B_["KL"], B_["KS"], B_["LOWV"]
COINI = MT.coin.to_numpy()
y_all = (WL[:, 0] >= WS[:, 0]).astype(np.int8); okl = np.isfinite(WL[:, 0]) & np.isfinite(WS[:, 0])
blocks = []
y0 = 2022
while True:
    for half in (0, 1):
        a = ms(f"{y0}-{1 + 6 * half:02d}-01") - KST
        b = ms(f"{y0 + half}-{(7 if half == 0 else 1):02d}-01") - KST
        if a >= Z:
            break
        blocks.append((a, min(b, Z)))
    y0 += 1
    if ms(f"{y0}-01-01") > Z:
        break
P = np.full(len(MT), np.nan, np.float32)
for (a, b) in blocks:
    tr = np.flatnonzero((Tm < a - 3 * DAY) & okl)[::3]
    te = np.flatnonzero((Tm >= a) & (Tm < b))
    mdl = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.03, num_leaves=63, min_child_samples=300, subsample=0.7,
                             subsample_freq=1, colsample_bytree=0.5, reg_lambda=5.0, n_jobs=4, verbose=-1)
    mdl.fit(X[tr], y_all[tr])
    P[te] = mdl.predict_proba(X[te])[:, 1]
    log("block", pd.Timestamp(a, unit="ms").strftime("%Y-%m"), "trained", len(tr))
np.savez_compressed(os.path.join(OUTD, "cls51.npz"), P=P, T=Tm)
YM = FC.ym_of(Tm); WKD = FC.wk(Tm)
FWD_A = ms("2026-10-05 15:00")


def one_pos(idx, sd, x=0):
    o_ = np.argsort(Tm[idx], kind="stable"); idx, sd = idx[o_], sd[o_]
    W = np.where(sd > 0, WL[idx, x], WS[idx, x]).astype(float); K = np.where(sd > 0, KL[idx, x], KS[idx, x])
    tk = []; free = -1
    for i in range(len(idx)):
        if Tm[idx[i]] >= free and np.isfinite(W[i]):
            tk.append(i); free = Tm[idx[i]] + int(K[i]) * MIN
    tk = np.array(tk, int)
    return Tm[idx[tk]], W[tk], idx[tk], sd[tk]


RES = {}
for vn, vm in (("BTC·낮은 변동성 빼기", (COINI != 0) & ~LOWV), ("BTC 빼기", COINI != 0), ("6개 코인", np.ones(len(MT), bool))):
    te = np.flatnonzero(np.isfinite(P) & WKD & vm & okl)
    te = te[np.argsort(Tm[te], kind="stable")]
    conf = np.abs(P[te] - 0.5); sd_all = np.where(P[te] >= 0.5, 1, -1)
    day = (Tm[te] + KST) // DAY; ud, st = np.unique(day, return_index=True); bd = list(st) + [len(te)]
    nper = 96 * (5 if vn != "6개 코인" else 6)
    for per_day in (1, 2, 4, 8):
        q = 1 - per_day / nper; keep = np.zeros(len(te), bool)
        for i, d in enumerate(ud):
            lo = np.searchsorted(day, d - 30); hi = bd[i]
            if hi - lo < 2000:
                continue
            keep[bd[i]:bd[i + 1]] = conf[bd[i]:bd[i + 1]] > np.quantile(conf[lo:hi], q)
        k = te[keep]; sk = sd_all[keep]
        right = np.where(WL[k, 0] >= WS[k, 0], 1, -1)
        t2, w2, i2, s2 = one_pos(k, sk)
        r = {}
        for lab, a_, z_ in (("2022-24", 202201, 202412), ("2025-26", 202501, 202609)):
            m = (YM[k] >= a_) & (YM[k] <= z_)
            for cost in (0.0014, 0.0008):
                w_ = w2 - (cost - 0.0014) * 0.4 * HB.LEVC[COINI[i2]]
                rr = FC.read(t2, w_, a_, z_)
                r[f"{lab} {cost * 100:.2f}%"] = {"한 달 기하평균": rr["기하평균"], "x3+": rr["x3+"], "-50%": rr["-50%"], "달 진입": rr["달 진입"]}
            r[f"{lab} 맞히는 비율 (고른 것 전부)"] = round(float((sk[m] == right[m]).mean()), 3)
            mt = (FC.ym_of(t2) >= a_) & (FC.ym_of(t2) <= z_)
            r[f"{lab} 맞히는 비율 (실제 거래)"] = round(float((s2[mt] == np.where(WL[i2[mt], 0] >= WS[i2[mt], 0], 1, -1)).mean()), 3) if mt.any() else None
        fw = t2 >= FWD_A
        r["10월"] = {"거래": int(fw.sum()), "배수": round(float(np.prod(1 + w2[fw])), 3)}
        RES[f"{vn} / 하루 {per_day}개"] = r
        print(vn, per_day, json.dumps(r, ensure_ascii=False), flush=True)
json.dump(RES, open(os.path.join(OUTD, "cls51.json"), "w"), ensure_ascii=False, indent=1, default=float)
print("done")
