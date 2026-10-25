"""Owners 10/25 night: "a month of +200 % (x2), keep searching". New information the models never used: Binance futures
order-book depth (data/bookdepth, 5-minute snapshots from 2023-01, cumulative bid / ask notional within 1 .. 5 % of the
price) and the premium index (data/orderflow *_premium_1h, the futures-vs-index basis, hourly klines).
Features at each 15m close T, strictly from data known by T (the snapshot's own time snap_ts <= T, at most 15 minutes
old; the premium kline closed by T): bid / ask imbalance at 1 / 2 / 5 %, its change over 1 h and 4 h, the 1 % depth vs
its 30-day median, the premium close, its 24 h mean and 4 h change.
Two arms on the same samples, labels (owners' exit L5, stop ROE -25 %, 0.14 %, from s48) and half-year walk-forward
blocks 2024-01 .. 2026-10 (training only on samples from 2023-01 to 3 days before each block, every 2nd sample):
the s21 price features alone, and the s21 features + depth + premium. Read: right-side accuracy and one-position months
for 1 / 2 / 4 / 8 picks a day (causal 30-day quantile; BTC and low-volatility moments out), 2024, 2025-26, October."""
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
DATA = "/home/user/crypto-bot-research/data"
H1 = 3600_000
NEWF = ["imb1", "imb2", "imb5", "imb1_d1h", "imb1_d4h", "imb5_d4h", "dep1_rel", "prem", "prem24", "prem_d4h"]
XN = np.full((len(MT), len(NEWF)), np.nan, np.float32)
for ci, cn in enumerate(COINS):
    m = np.flatnonzero(COINI == ci)
    base = cn.replace("USDT", "").lower()
    d = pd.read_csv(os.path.join(DATA, "bookdepth", f"{base}_depth_5m.csv.gz"))
    d = d.sort_values("snap_ts").reset_index(drop=True)
    st = d.snap_ts.to_numpy(np.int64)
    b1, a1 = d.bid_1.to_numpy(float), d.ask_1.to_numpy(float)
    b2, a2 = d.bid_2.to_numpy(float), d.ask_2.to_numpy(float)
    b5, a5 = d.bid_5.to_numpy(float), d.ask_5.to_numpy(float)
    imb1 = (b1 - a1) / (b1 + a1); imb2 = (b2 - a2) / (b2 + a2); imb5 = (b5 - a5) / (b5 + a5)
    dep1 = b1 + a1; med = pd.Series(dep1).rolling(8640, min_periods=1000).median().to_numpy()

    def at(arr, tt, maxage=15 * MIN):
        j = np.searchsorted(st, tt, side="right") - 1; jj = np.clip(j, 0, None)
        okk = (j >= 0) & (tt - st[jj] <= maxage)
        return np.where(okk, arr[jj], np.nan)
    T_ = Tm[m]
    i1 = at(imb1, T_); i5 = at(imb5, T_)
    XN[m, 0] = i1; XN[m, 1] = at(imb2, T_); XN[m, 2] = i5
    XN[m, 3] = i1 - at(imb1, T_ - H1); XN[m, 4] = i1 - at(imb1, T_ - 4 * H1); XN[m, 5] = i5 - at(imb5, T_ - 4 * H1)
    XN[m, 6] = at(dep1 / med, T_)
    p = pd.read_csv(os.path.join(DATA, "orderflow", f"{base}_premium_1h.csv.gz")).sort_values("close_time")
    pc = p.close.to_numpy(float); pct = p.close_time.to_numpy(np.int64) + 1
    p24 = pd.Series(pc).rolling(24, min_periods=12).mean().to_numpy()
    j = np.searchsorted(pct, T_, side="right") - 1; jj = np.clip(j, 0, None); okp = j >= 4
    XN[m, 7] = np.where(okp, pc[jj], np.nan); XN[m, 8] = np.where(okp, p24[jj], np.nan)
    XN[m, 9] = np.where(okp, pc[jj] - pc[np.clip(jj - 4, 0, None)], np.nan)
    log(cn, "depth rows", len(d), "coverage", round(float(np.isfinite(XN[m, 0]).mean()), 3))
X2 = np.hstack([X, XN])
okl = np.isfinite(WL[:, 0]) & np.isfinite(WS[:, 0])
D0 = ms("2023-01-01") - KST
blocks = [(ms(f"{y}-{mo:02d}-01") - KST, ms(f"{y + (mo == 7)}-{(1 if mo == 7 else 7):02d}-01") - KST) for y in (2024, 2025, 2026) for mo in (1, 7)]
blocks = [(a, min(b, Z)) for a, b in blocks if a < Z]
PRED = {arm: np.full((len(MT), 2), np.nan, np.float32) for arm in ("가격만", "가격+호가+프리미엄")}
for (a, b) in blocks:
    tr = np.flatnonzero((Tm >= D0) & (Tm < a - 3 * DAY) & okl)[::2]
    te = np.flatnonzero((Tm >= a) & (Tm < b))
    for arm, XX in (("가격만", X), ("가격+호가+프리미엄", X2)):
        for si, W in enumerate((WL, WS)):
            mdl = lgb.LGBMRegressor(n_estimators=500, learning_rate=0.03, num_leaves=63, min_child_samples=300, subsample=0.7,
                                    subsample_freq=1, colsample_bytree=0.5, reg_lambda=5.0, n_jobs=4, verbose=-1)
            mdl.fit(XX[tr], W[tr, 0].astype(np.float64))
            PRED[arm][te, si] = mdl.predict(XX[te])
            if arm != "가격만" and si == 0 and b >= Z:
                imp = pd.Series(mdl.feature_importances_, index=list(FNAMES) + NEWF).sort_values(ascending=False)
                log("top features (last block, long)", imp.head(20).to_dict())
    log("block", pd.Timestamp(a, unit="ms").strftime("%Y-%m"), "trained", len(tr))
np.savez_compressed(os.path.join(OUTD, "depth52.npz"), P0=PRED["가격만"], P1=PRED["가격+호가+프리미엄"], T=Tm)
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
    return Tm[idx[tk]], W[tk], idx[tk]


RES = {}
vm = (COINI != 0) & ~LOWV & WKD & okl
for arm, P in PRED.items():
    best = np.fmax(P[:, 0], P[:, 1]); side = np.where(P[:, 0] >= P[:, 1], 1, -1)
    te = np.flatnonzero(np.isfinite(best) & vm)
    te = te[np.argsort(Tm[te], kind="stable")]
    day = (Tm[te] + KST) // DAY; ud, st_ = np.unique(day, return_index=True); bd = list(st_) + [len(te)]
    bv = best[te]
    for per_day in (1, 2, 4, 8):
        q = 1 - per_day / 480.0; keep = np.zeros(len(te), bool)
        for i, dd in enumerate(ud):
            lo = np.searchsorted(day, dd - 30); hi = bd[i]
            if hi - lo < 1500:
                continue
            keep[bd[i]:bd[i + 1]] = bv[bd[i]:bd[i + 1]] > np.quantile(bv[lo:hi], q)
        k = te[keep]; sk = side[k]
        right = np.where(WL[k, 0] >= WS[k, 0], 1, -1)
        t2, w2, i2 = one_pos(k, sk)
        r = {}
        for lab, a_, z_ in (("2024", 202401, 202412), ("2025-26", 202501, 202609)):
            mm = (YM[k] >= a_) & (YM[k] <= z_)
            r[f"{lab} 맞히는 비율"] = round(float((sk[mm] == right[mm]).mean()), 3) if mm.any() else None
            for cost in (0.0014, 0.0008):
                w_ = w2 - (cost - 0.0014) * 0.4 * HB.LEVC[COINI[i2]]
                rr = FC.read(t2, w_, a_, z_)
                r[f"{lab} {cost * 100:.2f}%"] = {"한 달 기하평균": rr["기하평균"], "중간값": rr["중간값"], "x2+": rr["x2+"], "x3+": rr["x3+"],
                                                 "-50%": rr["-50%"], "달 진입": rr["달 진입"], "최고": rr["최고"]}
        fw = t2 >= FWD_A
        r["10월"] = {"거래": int(fw.sum()), "배수": round(float(np.prod(1 + w2[fw])), 3)}
        RES[f"{arm} / 하루 {per_day}개"] = r
        log(arm, per_day, "acc", r["2024 맞히는 비율"], r["2025-26 맞히는 비율"], "| month", r["2024 0.14%"]["한 달 기하평균"],
            r["2025-26 0.14%"]["한 달 기하평균"], r["2025-26 0.08%"]["한 달 기하평균"], "| oct", r["10월"])
json.dump(RES, open(os.path.join(OUTD, "depth52.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
