"""Owners 10/25 night, "keep searching": the price-only learned entry (s21 features, no Binance 5m metrics) trained
directly on the exit the owners chose, ladder L5 (12 -> 10, then 5 % steps) with stop ROE -25 % and -35 %, DeepCoin
0.14 % round trip, fixed rules (BTC 40x / alts 30x, margin 40 %), no hold limit. Walk-forward half-year blocks
2022-01 .. 2026-10 (training ends 3 days before each block, every 3rd sample, 500 trees). Trading: at each weekday 15m
close the highest predicted result over the coins x long / short, if above a threshold, one position. Variants: all 6
coins; without BTC; without BTC and without low-volatility moments (s41: both lost in both periods). Read 2022-01 ..
2024-12 (fit years of the earlier choices) and 2025-01 .. 2026-09 by KST month, October 2026 apart. Control: as many
entries at random test samples (random side)."""
import os, sys, json
import numpy as np, pandas as pd
import lightgbm as lgb
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
sys.argv = [sys.argv[0], "price"]
src = open(os.path.join(HERE, "s21_mlprice.py")).read()
exec(src.split("# ---------------------------------------------------------------- labels: walk long and short")[0])

EXN = ["L5·손절ROE-25%", "L5·손절ROE-35%"]
COST = 0.0014
sk = np.array([1, 1], np.int8); sv = np.array([0.25, 0.35]); tk = np.zeros(2, np.int8); tv = np.zeros(2)
lg = np.full(2, 0.12); ll = np.full(2, 0.10); ls = np.full(2, 0.05)
ci_ = MT.coin.to_numpy(); start = off[ci_] + MT.e.to_numpy(); send = off[ci_ + 1]
good = (start < send - 1) & np.isfinite(o[np.minimum(start, len(o) - 1)])
lev = HB.LEVC[ci_]; atrf = np.full(len(MT), 0.01); st2 = np.where(good, start, 0)
WL, KL, _ = HB.walk_all(o, h, l, cl, st2, send, np.ones(len(MT), np.int8), lev, atrf, sk, sv, tk, tv, lg, ll, ls, COST,
                        HB.MARGIN, 10 ** 12)
WS, KS, _ = HB.walk_all(o, h, l, cl, st2, send, -np.ones(len(MT), np.int8), lev, atrf, sk, sv, tk, tv, lg, ll, ls, COST,
                        HB.MARGIN, 10 ** 12)
WL[~good] = np.nan; WS[~good] = np.nan
del o, h, l, cl
log("labels", np.nanmean(WL, 0), np.nanmean(WS, 0))
Tm = MT["T"].to_numpy(); REGS = MT.reg.to_numpy(); WKD = ((((Tm + KST) // DAY) + 3) % 7) < 5
COINI = MT.coin.to_numpy()
# low-volatility moments as in s41 (15m realized vol over a day below its 90-day lower third), closed bars only
LOWV = np.zeros(len(MT), bool)
for ci, cn in enumerate(COINS):
    m = COINI == ci
    b15 = bars(cn, "15m"); c15 = b15.close.to_numpy(); T15 = b15.ts.to_numpy(np.int64) + M15
    rv = pd.Series(np.r_[np.nan, np.diff(np.log(c15))]).rolling(96).std()
    lo_ = rv.rolling(8640, min_periods=2000).quantile(1 / 3).to_numpy(); rv = rv.to_numpy()
    jj = np.clip(np.searchsorted(T15, Tm[m], side="right") - 1, 0, None)
    LOWV[m] = rv[jj] < lo_[jj]
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
PRED = np.full((len(MT), 2, 2), np.nan, np.float32)
for (a, b) in blocks:
    tr = np.flatnonzero(Tm < a - 3 * DAY)[::3]
    te = np.flatnonzero((Tm >= a) & (Tm < b))
    for si, W in enumerate((WL, WS)):
        for x in range(2):
            y = W[tr, x]; m = np.isfinite(y); idx = tr[m]; yy = y[m].astype(np.float64)
            mdl = lgb.LGBMRegressor(n_estimators=500, learning_rate=0.03, num_leaves=63, min_child_samples=300,
                                    subsample=0.7, subsample_freq=1, colsample_bytree=0.5, reg_lambda=5.0,
                                    n_jobs=4, verbose=-1)
            mdl.fit(X[idx], yy)
            PRED[te, si, x] = mdl.predict(X[te])
    log("block", pd.Timestamp(a, unit="ms").strftime("%Y-%m"), "trained", len(tr), "tested", len(te))
np.savez_compressed(os.path.join(OUTD, "l5m48.npz"), PRED=PRED, WL=WL.astype(np.float32), WS=WS.astype(np.float32),
                    KL=KL, KS=KS, T=Tm, REG=REGS, COIN=COINI.astype(np.int8), LOWV=LOWV)
log("saved")
LEVI = HB.LEVC[COINI]
VARS = {"6개 코인": np.ones(len(MT), bool), "BTC 빼기": COINI != 0, "BTC·낮은 변동성 빼기": (COINI != 0) & ~LOWV}


def trade(x, thr, cost, mask, rand=None):
    pool = np.flatnonzero(np.isfinite(PRED[:, 0, x]) & WKD & mask)
    pl, ps = PRED[pool, 0, x], PRED[pool, 1, x]
    side = np.where(pl >= ps, 0, 1); best = np.maximum(pl, ps)
    keep = best > thr
    te, side, best = pool[keep], side[keep], best[keep]
    if rand is not None:
        g = np.random.default_rng(rand)
        te = np.sort(g.choice(pool, size=len(te), replace=False)); side = g.integers(0, 2, len(te)); best = np.zeros(len(te))
    o_ = np.lexsort((-best, Tm[te])); te, side = te[o_], side[o_]
    W = np.where(side == 0, WL[te, x], WS[te, x]).astype(float) - (cost - COST) * 0.4 * LEVI[te]
    K = np.where(side == 0, KL[te, x], KS[te, x])
    taken = []; free = -1
    for i in range(len(te)):
        if Tm[te[i]] >= free and np.isfinite(W[i]):
            taken.append(i); free = Tm[te[i]] + int(K[i]) * MIN
    taken = np.array(taken, int)
    return Tm[te[taken]], W[taken]


def read(t, w):
    d = pd.to_datetime(t + KST, unit="ms"); ym = (d.year * 100 + d.month).to_numpy()
    out = {}
    for lab, a_, z_ in (("2022-24", 202201, 202412), ("2025-26", 202501, 202609)):
        ends, cnt, bust = [], [], 0
        for k in FCm(a_, z_):
            ww = w[ym == k]; eq = np.cumprod(1 + ww) if len(ww) else np.array([1.0])
            ends.append(float(eq[-1])); cnt.append(len(ww)); bust += bool((eq <= 0.5).any())
        ends = np.array(ends); sel = (ym >= a_) & (ym <= z_)
        out[lab] = {"한 달 기하평균": round(float(np.exp(np.mean(np.log(np.maximum(ends, 1e-6))))), 3), "한 달 중간값": round(float(np.median(ends)), 3),
                    "x3 이상 달": int((ends >= 3).sum()), "-50% 닿은 달": int(bust), "달": len(ends), "달 진입": round(float(np.mean(cnt)), 1),
                    "거래당": round(float(w[sel].mean()), 4) if sel.any() else None, "승률": round(float((w[sel] > 0).mean()), 3) if sel.any() else None,
                    "가장 좋은 달": round(float(ends.max()), 2)}
    fw = w[ym == 202610]
    out["10월"] = {"거래": int(len(fw)), "배수": round(float(np.prod(1 + fw)), 3)}
    return out


def FCm(a, b):
    r = []; y, m = a // 100, a % 100
    while y * 100 + m <= b:
        r.append(y * 100 + m); m += 1
        if m == 13:
            y += 1; m = 1
    return r


res = {}
for vn, mask in VARS.items():
    for x in range(2):
        for thr in (0.0, 0.01, 0.02, 0.03, 0.04, 0.06):
            for cost in (0.0014, 0.0008):
                r = read(*trade(x, thr, cost, mask))
                rr = read(*trade(x, thr, cost, mask, rand=5))
                r["무작위 같은 수"] = {k: {kk: rr[k][kk] for kk in ("한 달 기하평균", "거래당")} for k in ("2022-24", "2025-26")}
                key = f"{vn} / {EXN[x]} / 기준 {thr} / 왕복 {cost * 100:.2f}%"
                res[key] = r
                log(key, r["2022-24"]["한 달 기하평균"], r["2025-26"]["한 달 기하평균"], r["2025-26"]["달 진입"], r["10월"])
json.dump(res, open(os.path.join(OUTD, "l5m48.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
