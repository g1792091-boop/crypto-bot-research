"""Owners 10/25: design to at least 95 entries a month, no weekend entries (KST Sat/Sun), the 6 coins. The price-only
learned entry (s21, walk-forward predictions saved) traded with a causal frequency rule: each weekday, enter when the
best predicted result (over coins and sides) is above the q-quantile of the predictions of the 30 days before, q set so
that about TARGET weekday candidates a day pass; one position; read the realised entries a month. Costs: the labels'
0.12 % moved to DeepCoin 0.14 % and 0.08 % (payback) by the per-trade cost difference (x margin x leverage)."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
z = np.load(os.path.join(OUTD, "ml21_price.npz"))
PRED, WL, WS, KL, KS, T, REG, COIN = (z[k] for k in ("PRED", "WL", "WS", "KL", "KS", "T", "REG", "COIN"))
KST = 9 * 3600 * 1000; DAY = 86_400_000; MIN = 60_000
LEV = np.where(COIN == 0, 40.0, 30.0)
EXN = ["E3 손절2ATR·계단12→10", "E4 손절ROE-50%·작은계단6→4", "E5 손절ROE-35%·작은계단6→4"]
dow = (((T + KST) // DAY) + 3) % 7; wkday = dow < 5
FWD_A = 1791212400000


def run(x, per_day, cost):
    ok = np.isfinite(PRED[:, 0, x]) & wkday
    te = np.flatnonzero(ok)
    pl, ps = PRED[te, 0, x], PRED[te, 1, x]
    side = np.where(pl >= ps, 0, 1); best = np.maximum(pl, ps)
    o_ = np.argsort(T[te], kind="stable"); te, side, best = te[o_], side[o_], best[o_]
    day = (T[te] + KST) // DAY
    # candidates a weekday: 6 coins x 96 closes = 576 -> keep the top per_day/576 share, threshold from the 30 days before
    q = 1 - per_day / 576.0
    keep = np.zeros(len(te), bool)
    ud, start = np.unique(day, return_index=True)
    bounds = list(start) + [len(te)]
    for i, d in enumerate(ud):
        lo = np.searchsorted(day, d - 30); hi = bounds[i]
        if hi - lo < 2000:
            continue
        th = np.quantile(best[lo:hi], q)
        a, b = bounds[i], bounds[i + 1]
        keep[a:b] = best[a:b] > th
    te, side = te[keep], side[keep]
    W = np.where(side == 0, WL[te, x], WS[te, x]).astype(float) - (cost - 0.0012) * 0.4 * LEV[te]
    K = np.where(side == 0, KL[te, x], KS[te, x])
    taken = []; free = -1
    for i in range(len(te)):
        if T[te[i]] >= free and np.isfinite(W[i]):
            taken.append(i); free = T[te[i]] + int(K[i]) * MIN
    taken = np.array(taken, int)
    t = T[te[taken]]; w = W[taken]; rg = REG[te[taken]]
    d = pd.to_datetime(t + KST, unit="ms"); ym = (d.year * 100 + d.month).to_numpy(); yr = d.year.to_numpy()
    rs, ends, cnt = [], [], []
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
        rs.append(r); ends.append(float(np.prod(1 + w[ym == k]))); cnt.append(int((ym == k).sum()))
    hits = [r == "x5" for r in rs]
    return {"달 평균 진입": round(float(np.mean(cnt)), 1), "거래당": round(float(w.mean()), 4), "승률": round(float((w > 0).mean()), 3),
            "x5달": int(sum(hits)), "연속 x5": sum(1 for i in range(1, len(hits)) if hits[i] and hits[i - 1]),
            "-50%달": rs.count("-50%"), "달": len(rs), "달 중간값": round(float(np.median(ends)), 3),
            "해별": {str(y): round(float(w[yr == y].mean()), 4) for y in range(2022, 2027) if (yr == y).any()},
            "장세별(상승/하락/횡보)": [round(float(w[rg == g].mean()), 4) if (rg == g).any() else None for g in (0, 1, 2)]}


out = {}
for x in range(3):
    for per_day in (6, 8, 12, 20):
        for cost in (0.0014, 0.0008):
            r = run(x, per_day, cost)
            key = f"{EXN[x]} / 평일 후보 {per_day}개/일 / 왕복 {cost*100:.2f}%"
            out[key] = r
            print(key, json.dumps(r, ensure_ascii=False), flush=True)
json.dump(out, open(os.path.join(OUTD, "freq25.json"), "w"), ensure_ascii=False, indent=1, default=float)
