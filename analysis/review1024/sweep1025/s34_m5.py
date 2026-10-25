"""s34: as s32, but every 5m close is a sample (the same features with windows x3, so they span the same time): three
times the chances to find a good spot. Does the count of good spots grow at the same quality?

s32: the price-only learned entry (s21 features, no Binance 5m metrics) trained directly on the exit
the owners like: ladder 12->10, 22->20, 32->30 ... (L10) with stop ROE -35 % and with stop ROE -50 %, DeepCoin cost
0.14 % round trip, fixed rules (BTC 40x / alts 30x, margin 40 %). Walk-forward half-year blocks 2022-01 .. 2026-10
(training ends 3 days before each block). Trading: at each weekday 15m close the highest predicted result over the 6
coins x long / short, if above a threshold, one position. Read 2022-01 .. 2026-09 by KST month: median, months >= x3 /
x5 / x10, months touching -50 %, entries a month, per trade, years, regimes; October 2026 (forward) apart. Control: as
many entries at random test samples (random side). argv 1 "shuffle": labels shuffled by month (no signal)."""
import os, sys, json
import numpy as np, pandas as pd
import lightgbm as lgb
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
MODE32 = sys.argv[1] if len(sys.argv) > 1 else "real"
sys.argv = [sys.argv[0], "price"]
src = open(os.path.join(HERE, "s21_mlprice.py")).read()
head = src.split("# ---------------------------------------------------------------- labels: walk long and short")[0]
REPL = [  # the same features on 5m closes (windows x3 so they span the same time)
    ('M15 = 15 * MIN', 'M15 = 15 * MIN; M5 = 5 * MIN'),
    ('bq = bars(cn, "15m"); lcq = np.log(bq.close.to_numpy())', 'bq = bars(cn, "5m"); lcq = np.log(bq.close.to_numpy())'),
    ('XRET[ci] = (bq.ts.to_numpy(np.int64) + M15, {"ret4": lcq - np.r_[np.full(4, np.nan), lcq[:-4]],',
     'XRET[ci] = (bq.ts.to_numpy(np.int64) + M5, {"ret4": lcq - np.r_[np.full(12, np.nan), lcq[:-12]],'),
    ('"ret16": lcq - np.r_[np.full(16, np.nan), lcq[:-16]]})', '"ret16": lcq - np.r_[np.full(48, np.nan), lcq[:-48]]})'),
    ('b15 = bars(cn, "15m"); bars_cache', 'b15 = bars(cn, "5m"); bars_cache'),
    ('ts = b15.ts.to_numpy(np.int64); T = ts + M15', 'ts = b15.ts.to_numpy(np.int64); T = ts + M5'),
    ('F[f"ret{k}"] = lc - np.r_[np.full(k, np.nan), lc[:-k]]', 'F[f"ret{k}"] = lc - np.r_[np.full(3 * k, np.nan), lc[:-3 * k]]'),
    ('F["sd16"] = pd.Series(r1).rolling(16).std().to_numpy(); F["sd96"] = pd.Series(r1).rolling(96).std().to_numpy()',
     'F["sd16"] = pd.Series(r1).rolling(48).std().to_numpy(); F["sd96"] = pd.Series(r1).rolling(288).std().to_numpy()'),
    ('F["atr15"] = atrp(h, l, c); F["rsi15"] = rsi(c)', 'F["atr15"] = atrp(h, l, c, 42); F["rsi15"] = rsi(c, 42)'),
    ('F[f"ema{sp}"] = c / ema(c, sp) - 1', 'F[f"ema{sp}"] = c / ema(c, 3 * sp) - 1'),
    ('for nwin, lab in ((96, "1d"), (672, "7d")):', 'for nwin, lab in ((288, "1d"), (2016, "7d")):'),
    ('F["vratio"] = pd.Series(v).rolling(4).sum().to_numpy() / (pd.Series(v).rolling(672).mean().to_numpy() * 4 + 1e-12)',
     'F["vratio"] = pd.Series(v).rolling(12).sum().to_numpy() / (pd.Series(v).rolling(2016).mean().to_numpy() * 12 + 1e-12)'),
]
for a_, b_ in REPL:
    assert head.count(a_) == 1, a_
    head = head.replace(a_, b_)
exec(head)

EXN = ["L10·손절ROE-35%", "L10·손절ROE-50%"]
COST = 0.0014
sk = np.array([1, 1], np.int8); sv = np.array([0.35, 0.50]); tk = np.zeros(2, np.int8); tv = np.zeros(2)
lg = np.full(2, 0.12); ll = np.full(2, 0.10); ls = np.full(2, 0.10)
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
rng = np.random.default_rng(32)
for (a, b) in blocks:
    tr = np.flatnonzero(Tm < a - 3 * DAY)[::12]
    te = np.flatnonzero((Tm >= a) & (Tm < b))
    for si, W in enumerate((WL, WS)):
        for x in range(2):
            y = W[tr, x]; m = np.isfinite(y); idx = tr[m]; yy = y[m].astype(np.float64)
            if MODE32 == "shuffle":
                d = pd.to_datetime(Tm[idx] + KST, unit="ms"); mon = ((d.year - 2020) * 12 + d.month).to_numpy()
                um = np.unique(mon); perm = dict(zip(um, rng.permutation(um)))
                yy = np.concatenate([np.resize(yy[mon == perm[u]], int((mon == u).sum())) for u in um])
                idx = np.concatenate([idx[mon == u] for u in um])
            mdl = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.04, num_leaves=63, min_child_samples=300,
                                    subsample=0.7, subsample_freq=1, colsample_bytree=0.5, reg_lambda=5.0,
                                    n_jobs=4, verbose=-1)
            mdl.fit(X[idx], yy)
            PRED[te, si, x] = mdl.predict(X[te])
    log("block", pd.Timestamp(a, unit="ms").strftime("%Y-%m"), "trained", len(tr), "tested", len(te))
np.savez_compressed(os.path.join(OUTD, f"m5_34_{MODE32}.npz"), PRED=PRED, WL=WL.astype(np.float32),
                    WS=WS.astype(np.float32), KL=KL, KS=KS, T=Tm, REG=REGS, COIN=MT.coin.to_numpy().astype(np.int8))
log("saved")
LEVI = HB.LEVC[MT.coin.to_numpy()]


def picks(x, thr, rand=None):
    te = np.flatnonzero(np.isfinite(PRED[:, 0, x]) & WKD)
    pl, ps = PRED[te, 0, x], PRED[te, 1, x]
    side = np.where(pl >= ps, 0, 1); best = np.maximum(pl, ps)
    keep = best > thr
    te, side, best = te[keep], side[keep], best[keep]
    if rand is not None:
        pool = np.flatnonzero(np.isfinite(PRED[:, 0, x]) & WKD)
        g = np.random.default_rng(rand)
        te = np.sort(g.choice(pool, size=len(te), replace=False)); side = g.integers(0, 2, len(te)); best = np.zeros(len(te))
    return te, side, best


def trade(x, thr, cost, rand=None):
    te, side, best = picks(x, thr, rand)
    o_ = np.lexsort((-best, Tm[te])); te, side = te[o_], side[o_]
    W = np.where(side == 0, WL[te, x], WS[te, x]).astype(float) - (cost - COST) * 0.4 * LEVI[te]
    K = np.where(side == 0, KL[te, x], KS[te, x])
    taken = []; free = -1
    for i in range(len(te)):
        if Tm[te[i]] >= free and np.isfinite(W[i]):
            taken.append(i); free = Tm[te[i]] + int(K[i]) * MIN
    taken = np.array(taken, int)
    return Tm[te[taken]], W[taken], REGS[te[taken]]


def read(t, w, rg):
    d = pd.to_datetime(t + KST, unit="ms"); ym = (d.year * 100 + d.month).to_numpy(); yr = d.year.to_numpy()
    sel = (ym >= 202201) & (ym < 202610)
    ends, cnt, bust = [], [], 0
    for q in range(2022, 2027):
        for mo in range(1, 13):
            k = q * 100 + mo
            if k >= 202610:
                break
            ww = w[ym == k]; eq = np.cumprod(1 + ww) if len(ww) else np.array([1.0])
            ends.append(float(eq[-1])); cnt.append(len(ww)); bust += bool((eq <= 0.5).any())
    ends = np.array(ends); fw = w[ym == 202610]
    return {"달": len(ends), "달 평균 진입": round(float(np.mean(cnt)), 1), "진입 없는 달": int(sum(c == 0 for c in cnt)),
            "거래당": round(float(w[sel].mean()), 4) if sel.any() else None,
            "승률": round(float((w[sel] > 0).mean()), 3) if sel.any() else None,
            "한 달 중간값": round(float(np.median(ends)), 3), "x3 이상 달": int((ends >= 3).sum()),
            "x5 이상 달": int((ends >= 5).sum()), "x10 이상 달": int((ends >= 10).sum()), "-50% 닿은 달": int(bust),
            "가장 좋은 달": round(float(ends.max()), 2), "가장 나쁜 달": round(float(ends.min()), 2),
            "해별 거래당": {str(y): round(float(w[sel & (yr == y)].mean()), 4) for y in range(2022, 2027) if (sel & (yr == y)).any()},
            "장세별 거래당(상승/하락/횡보)": [round(float(w[sel & (rg == g)].mean()), 4) if (sel & (rg == g)).any() else None
                                     for g in (0, 1, 2)],
            "10월(앞으로 본 기간)": {"거래": int(len(fw)), "배수": round(float(np.prod(1 + fw)), 3)}}


res = {}
for x in range(2):
    for thr in (0.005, 0.01, 0.015, 0.02, 0.03, 0.04):
        for cost in (0.0014, 0.0008):
            r = read(*trade(x, thr, cost))
            rr = read(*trade(x, thr, cost, rand=5))
            r["무작위 같은 수"] = {k: rr[k] for k in ("거래당", "한 달 중간값", "-50% 닿은 달")}
            key = f"{EXN[x]} / 기준 {thr} / 왕복 {cost * 100:.2f}%"
            res[key] = r
            log(key, json.dumps(r, ensure_ascii=False))
json.dump(res, open(os.path.join(OUTD, f"m5_34_{MODE32}.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
