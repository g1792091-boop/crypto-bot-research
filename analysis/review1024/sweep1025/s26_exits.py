"""Owners' rule (95+ entries a month, weekdays only): keep the price-only learned entry's picks (s25 rule: each weekday the
candidates above the 30-day q-quantile, about 12 a day, for the E4 and E5 models) and walk the same entries with 30
exits: ROE stops 25 / 35 / 50 / 75 %, ATR stops 1 / 2, take profits ROE +15 / +25 / +35 / +50 / +100 %, ATR 1 / 2 / 3,
ladders (12->10 / 5, 6->4 / 3). One position, DeepCoin costs 0.14 % and 0.08 %. Which exit pays at this frequency?"""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
sys.path.insert(0, "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/hunt1025")
import hb_build as HB                                    # noqa: E402
from common import COINS, MIN, grid, T0 as GT0             # noqa: E402

z = np.load(os.path.join(OUTD, "ml21_price.npz"))
PRED, T, REG, COIN = z["PRED"], z["T"], z["REG"], z["COIN"]
KST = 9 * 3600 * 1000; DAY = 86_400_000
dow = (((T + KST) // DAY) + 3) % 7; wk = dow < 5


def picks(x, per_day=12):
    te = np.flatnonzero(np.isfinite(PRED[:, 0, x]) & wk)
    pl, ps = PRED[te, 0, x], PRED[te, 1, x]
    side = np.where(pl >= ps, 1, -1); best = np.maximum(pl, ps)
    o_ = np.argsort(T[te], kind="stable"); te, side, best = te[o_], side[o_], best[o_]
    day = (T[te] + KST) // DAY; q = 1 - per_day / 576.0
    keep = np.zeros(len(te), bool); ud, st = np.unique(day, return_index=True); bd = list(st) + [len(te)]
    for i, d in enumerate(ud):
        lo = np.searchsorted(day, d - 30); hi = bd[i]
        if hi - lo < 2000:
            continue
        keep[bd[i]:bd[i + 1]] = best[bd[i]:bd[i + 1]] > np.quantile(best[lo:hi], q)
    return te[keep], side[keep], best[keep]


O, H, L, C, OFF = [], [], [], [], [0]
ATR = {}
for ci, cn in enumerate(COINS):
    g = grid(cn)
    O.append(g["o"]); H.append(g["h"]); L.append(g["l"]); C.append(g["c"]); OFF.append(OFF[-1] + g["n"])
o = np.concatenate(O); h = np.concatenate(H); l = np.concatenate(L); cl = np.concatenate(C); off = np.array(OFF)
del O, H, L, C
# 15m ATR14 % at each sample (for the ATR exits), from the 1m grid's 15m bars
from common import bars                                   # noqa: E402
for ci, cn in enumerate(COINS):
    b = bars(cn, "15m"); c_ = b.close.to_numpy(); h_ = b.high.to_numpy(); l_ = b.low.to_numpy()
    pc = np.r_[c_[0], c_[:-1]]; tr = np.maximum(h_ - l_, np.maximum(np.abs(h_ - pc), np.abs(l_ - pc)))
    ATR[ci] = (b.ts.to_numpy(np.int64) + 15 * MIN, pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy() / c_)

EXS = []
for s in (("roe", 0.25), ("roe", 0.35), ("roe", 0.50), ("roe", 0.75), ("atr", 1.0), ("atr", 2.0)):
    for tp in (("roe", 0.15), ("roe", 0.25), ("roe", 0.35), ("roe", 0.50), ("roe", 1.00), ("atr", 1.0), ("atr", 2.0), ("atr", 3.0)):
        EXS.append((s, tp, "none"))
    EXS.append((s, ("none", 0.0), "house")); EXS.append((s, ("none", 0.0), "tight"))
sk = np.array([0 if s[0] == "atr" else 1 for s, _, _ in EXS], np.int8); sv = np.array([s[1] for s, _, _ in EXS])
tk = np.array([{"none": 0, "roe": 1, "atr": 2}[t[0]] for _, t, _ in EXS], np.int8); tv = np.array([t[1] for _, t, _ in EXS])
lg = np.array([HB.LADS[x][0] for _, _, x in EXS]); ll = np.array([HB.LADS[x][1] for _, _, x in EXS])
ls = np.array([max(HB.LADS[x][2], 1e-9) for _, _, x in EXS])
NAME = [f"손절 {s[0]} {s[1]} / " + (f"익절 {t[0]} {t[1]}" if t[0] != "none" else f"계단 {x}") for s, t, x in EXS]

res = {}
for x, xn in ((1, "E4 모델의 자리"), (2, "E5 모델의 자리")):
    te, side, best = picks(x)
    ci_ = COIN[te].astype(np.int64); e = ((T[te] - GT0) // MIN).astype(np.int64)
    start = off[ci_] + e; send = off[ci_ + 1]; good = (start < send - 1) & np.isfinite(o[np.minimum(start, len(o) - 1)])
    lev = HB.LEVC[ci_]
    atrf = np.full(len(te), 0.01)
    for c in range(6):
        m = ci_ == c
        tt, av = ATR[c]; j = np.clip(np.searchsorted(tt, T[te][m], side="right") - 1, 0, None); atrf[m] = av[j]
    for cost in (0.0014, 0.0008):
        W, K, _ = HB.walk_all(o, h, l, cl, np.where(good, start, 0), send, side.astype(np.int8), lev, atrf, sk, sv, tk, tv,
                              lg, ll, ls, cost, HB.MARGIN, HB.MAXK)
        for k in range(len(EXS)):
            w = W[:, k].astype(float); kk = K[:, k]
            taken = []; free = -1
            for i in range(len(te)):
                if good[i] and T[te[i]] >= free:
                    taken.append(i); free = T[te[i]] + int(kk[i]) * MIN
            taken = np.array(taken, int); ww = w[taken]; tt_ = T[te[taken]]
            d = pd.to_datetime(tt_ + KST, unit="ms"); ym = (d.year * 100 + d.month).to_numpy(); yr = d.year.to_numpy()
            hit = bust = 0; ends = []; cnt = []
            for q in sorted(set(ym)):
                if q >= 202610:
                    continue
                eq = 1.0
                for v in ww[ym == q]:
                    eq *= 1 + v
                    if eq >= 5:
                        hit += 1; break
                    if eq <= 0.5:
                        bust += 1; break
                ends.append(float(np.prod(1 + ww[ym == q]))); cnt.append(int((ym == q).sum()))
            r = {"달 평균 진입": round(float(np.mean(cnt)), 1), "거래당": round(float(ww.mean()), 4),
                 "승률": round(float((ww > 0).mean()), 3), "x5달": hit, "-50%달": bust,
                 "달 중간값": round(float(np.median(ends)), 3),
                 "해별": {str(y): round(float(ww[yr == y].mean()), 4) for y in range(2022, 2027) if (yr == y).any()}}
            res[f"{xn} / 왕복 {cost*100:.2f}% / {NAME[k]}"] = r
    print(xn, "done", flush=True)
json.dump(res, open(os.path.join(OUTD, "exits26.json"), "w"), ensure_ascii=False, indent=1, default=float)
best = sorted(res.items(), key=lambda kv: -kv[1]["달 중간값"])[:15]
for k, r in best:
    print(k, json.dumps(r, ensure_ascii=False))
