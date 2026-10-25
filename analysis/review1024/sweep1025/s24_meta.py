"""New method 9 (10/25 night): meta-labeling. The 121 coded strategies (15m / 30m / 1h / 4h, both sides) give the
entries; a LightGBM model only decides whether to follow each signal. Features: the price-only features of s21 at the
signal's close (no Binance 5m metrics: they leak, s20) + which strategy, timeframe and side. Label: the signal's wallet
result with the fixed rules at DeepCoin cost (round trip 0.14 %), exits: ladder 12->10 with stop ROE -75 % (the
house exit) or with stop 2 ATR. Walk-forward half-year blocks 2022-01 .. 2026-10 (each block trained on signals ending
3 days before it, 1.2 M sampled). Trading: the followed signals (predicted result above a threshold), the highest
first at one close, one position. Read: months x5, in a row, -50 %, per year and regime, and at 0.08 % (payback).
Controls: as many signals picked at random (does the model choose better than chance?); argv 1 "shuffle": labels shuffled by month."""
import os, sys, json, time
import numpy as np, pandas as pd
import lightgbm as lgb
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
MODE24 = sys.argv[1] if len(sys.argv) > 1 else "real"
sys.argv = [sys.argv[0], "price"]
src = open(os.path.join(HERE, "s21_mlprice.py")).read()
head = src.split("# ---------------------------------------------------------------- labels: walk long and short")[0]
exec(head)                                                 # X, MT (T, coin), FNAMES, log, HB, RD, ms, KST, DAY, ...
del o, h, l, cl
import s2_members as SM                                    # noqa: E402
from paperbot.rmember import regimes as _regs              # noqa: E402
HB.COST = 0.0014; SM.HB.COST = 0.0014
XS = [6, 2]
XN = ["계단12→10·손절ROE-75%", "계단12→10·손절2ATR"]

# row of X for (coin, T)
ROWK = MT.coin.to_numpy().astype(np.int64) * (10 ** 13) + MT["T"].to_numpy()
order = np.argsort(ROWK); ROWK_S = ROWK[order]
cells = [str(c) for c in np.load(os.path.join(OUTD, "meta.npz"), allow_pickle=True)["cells"]]
CELLID = {c: i for i, c in enumerate(cells)}
parts = []
for n, cell in enumerate(cells):
    got = []
    for x in XS:
        try:
            T = SM.trades(cell, "none", "양방향", x)
        except IndexError:
            got = []
            break
        got.append(T)
    SM._S.pop(cell, None)
    if not got or not len(got[0]):
        continue
    t = got[0].t.to_numpy(np.int64); coin = got[0].coin.to_numpy(np.int64)
    k = coin * (10 ** 13) + t
    pos = np.searchsorted(ROWK_S, k); pos = np.clip(pos, 0, len(ROWK_S) - 1); ok = ROWK_S[pos] == k
    row = np.where(ok, order[pos], -1)
    parts.append(pd.DataFrame({"t": t, "coin": coin.astype(np.int8), "row": row.astype(np.int32),
                               "cell": np.int16(CELLID[cell]), "tfo": got[0].tfo.to_numpy().astype(np.int8),
                               "side": got[0].side.to_numpy().astype(np.int8),
                               "w0": got[0].w.to_numpy(np.float32), "k0": got[0].k.to_numpy(np.int32),
                               "w1": got[1].w.to_numpy(np.float32), "k1": got[1].k.to_numpy(np.int32)}))
    if n % 100 == 0:
        log("walked", n, "/", len(cells))
S = pd.concat(parts, ignore_index=True); del parts
S = S[S.row >= 0].reset_index(drop=True)
b4 = bars("BTCUSDT", "4h"); REG4, _ = _regs(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
B4C = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000
jj = np.searchsorted(B4C, S.t.to_numpy(), side="right") - 1
S["reg"] = np.where(jj >= 0, REG4[np.clip(jj, 0, None)], 2).astype(np.int8)
log("signals", len(S), "mean w", float(S.w0.mean()), float(S.w1.mean()))


def mat(idx):
    r = S.row.to_numpy()[idx]
    extra = np.c_[S.cell.to_numpy()[idx], S.tfo.to_numpy()[idx], S.side.to_numpy()[idx]].astype(np.float32)
    return np.hstack([X[r], extra])


NAMES = FNAMES + ["cell", "tfo", "side"]
St = S.t.to_numpy()
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
PRED = np.full((len(S), 2), np.nan, np.float32)
rng = np.random.default_rng(11)
for (a, b) in blocks:
    pool = np.flatnonzero(St < a - 3 * DAY)
    tr = np.sort(rng.choice(pool, size=min(len(pool), 600_000), replace=False))
    te = np.flatnonzero((St >= a) & (St < b))
    Xtr = mat(tr)
    for x in range(2):
        y = (S.w0 if x == 0 else S.w1).to_numpy()[tr].astype(np.float64)
        idx = np.arange(len(tr))
        if MODE24 == "shuffle":
            d = pd.to_datetime(St[tr] + KST, unit="ms"); mon = ((d.year - 2020) * 12 + d.month).to_numpy()
            um = np.unique(mon); perm = dict(zip(um, rng.permutation(um)))
            y = np.concatenate([np.resize(y[mon == perm[u]], int((mon == u).sum())) for u in um])
            idx = np.concatenate([idx[mon == u] for u in um])
        mdl = lgb.LGBMRegressor(n_estimators=250, learning_rate=0.05, num_leaves=63, min_child_samples=500,
                                subsample=0.7, subsample_freq=1, colsample_bytree=0.5, reg_lambda=5.0, n_jobs=4,
                                verbose=-1)
        mdl.fit(Xtr[idx], y, categorical_feature=[len(NAMES) - 3])
        for c0 in range(0, len(te), 400_000):
            ch = te[c0:c0 + 400_000]
            PRED[ch, x] = mdl.predict(mat(ch))
    del Xtr
    log("block", pd.Timestamp(a, unit="ms").strftime("%Y-%m"), "trained", len(tr), "tested", len(te))
LEV = HB.LEVC[S.coin.to_numpy().astype(int)]
_keep = np.flatnonzero(np.nanmax(PRED, axis=1) > 0.01)
np.savez_compressed(os.path.join(OUTD, f"meta24_{MODE24}_cand.npz"), idx=_keep, pred=PRED[_keep], t=St[_keep],
                    coin=S.coin.to_numpy()[_keep], w0=S.w0.to_numpy()[_keep], k0=S.k0.to_numpy()[_keep],
                    w1=S.w1.to_numpy()[_keep], k1=S.k1.to_numpy()[_keep], reg=S.reg.to_numpy()[_keep],
                    cell=S.cell.to_numpy()[_keep], side=S.side.to_numpy()[_keep])
log("saved candidates", len(_keep))


def trade(x, thr, rand=None, cost_adj=0.0):
    """followed signals (prediction above thr), or with ``rand`` a random pick of as many test signals (the control:
    does the model choose better than chance among the same strategies' signals?)."""
    alltest = np.flatnonzero(np.isfinite(PRED[:, x]))
    te = alltest[PRED[alltest, x] > thr]
    if rand is not None:
        te = np.sort(np.random.default_rng(rand).choice(alltest, size=len(te), replace=False))
        o_ = np.argsort(St[te], kind="stable")
    else:
        o_ = np.lexsort((-PRED[te, x], St[te]))
    te = te[o_]
    W = (S.w0 if x == 0 else S.w1).to_numpy()[te].astype(float) + cost_adj * 0.4 * LEV[te]
    K = (S.k0 if x == 0 else S.k1).to_numpy()[te]
    keep = []; free = -1
    for i in range(len(te)):
        if St[te[i]] >= free:
            keep.append(i); free = St[te[i]] + int(K[i]) * MIN
    keep = np.array(keep, int)
    return St[te[keep]], W[keep], S.reg.to_numpy()[te[keep]]


def read(t, w, rg):
    d = pd.to_datetime(t + KST, unit="ms"); ym = (d.year * 100 + d.month).to_numpy(); yr = d.year.to_numpy()
    rs, ends = [], []
    for k in sorted(set(ym)):
        if k >= 202610:
            continue
        eq = 1.0; r = "그대로"
        for v in w[ym == k]:
            eq *= 1 + v
            if eq >= 5:
                r = "x5"; break
            if eq <= 0.5:
                r = "-50%"; break
        rs.append((k, r)); ends.append(float(np.prod(1 + w[ym == k])))
    hits = [r == "x5" for _, r in rs]
    return {"거래": len(w), "거래당": round(float(w.mean()), 4) if len(w) else None, "x5달": int(sum(hits)),
            "연속 x5": sum(1 for i in range(1, len(hits)) if hits[i] and hits[i - 1]),
            "-50%달": sum(r == "-50%" for _, r in rs), "달": len(rs),
            "달 중간값": round(float(np.median(ends)), 3) if ends else None,
            "해별": {str(y): round(float(w[yr == y].mean()), 4) for y in range(2022, 2027) if (yr == y).any()},
            "장세별(상승/하락/횡보)": [round(float(w[rg == g].mean()), 4) if (rg == g).any() else None for g in (0, 1, 2)]}


res = {}
for x in range(2):
    for thr in (0.0, 0.01, 0.02, 0.03, 0.05):
        for cl_, adj in (("0.14%", 0.0), ("0.08%", 0.0006)):
            r = read(*trade(x, thr, cost_adj=adj)); rr = read(*trade(x, thr, rand=1, cost_adj=adj)); r["무작위 고르기"] = {k: rr[k] for k in ("거래당", "x5달", "-50%달")}
            key = f"{XN[x]} / 기준 {thr} / 왕복 {cl_}"
            res[key] = r
            log(key, json.dumps(r, ensure_ascii=False))
json.dump(res, open(os.path.join(OUTD, f"meta24_{MODE24}.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
