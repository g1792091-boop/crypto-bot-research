"""s37 follow-up: the prediction scale drifts between half-year blocks, so a fixed threshold means 76 entries a month in
2022-24 and 15 in 2025-26. Instead: each weekday, the candidates above the q-quantile of the 30 days before (causal,
no look-ahead), about 0.5 / 1 / 2 / 3 / 5 a day pass; prediction = the smallest (or the mean) of the three exits'
predictions; owners' ladders L5 / L10, stops ROE -25 / -35 / -50 / -75 %, no hold limit, one position."""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import KST, DAY                             # noqa: E402
D = FC.Data()
z = np.load(os.path.join(OUTD, "ml21_price.npz"))
P, TT, CC = z["PRED"], z["T"], z["COIN"].astype(np.int64)
SETS = {}
for how in ("최소", "평균", "E5"):
    agg = np.nanmin(P, axis=2) if how == "최소" else (np.nanmean(P, axis=2) if how == "평균" else P[:, :, 2])
    best = np.fmax(agg[:, 0], agg[:, 1]); side = np.where(agg[:, 0] >= agg[:, 1], 1, -1)
    te = np.flatnonzero(np.isfinite(best) & FC.wk(TT)); te = te[np.argsort(TT[te], kind="stable")]
    day = (TT[te] + KST) // DAY; ud, st = np.unique(day, return_index=True); bd = list(st) + [len(te)]
    b = best[te]
    for per_day in (0.5, 1, 2, 3, 5):
        q = 1 - per_day / 576.0; keep = np.zeros(len(te), bool)
        for i, d in enumerate(ud):
            lo = np.searchsorted(day, d - 30); hi = bd[i]
            if hi - lo < 2000:
                continue
            keep[bd[i]:bd[i + 1]] = b[bd[i]:bd[i + 1]] > np.quantile(b[lo:hi], q)
        k = te[keep]
        SETS[f"가격모델 {how} · 하루 후보 {per_day}개"] = (TT[k], CC[k], side[k], best[k])
res = {}
for lab, (t, c, s, p) in SETS.items():
    res[lab] = {f"{cost * 100:.2f}%": FC.run(D, t, c, s, p, cost) for cost in (0.0014, 0.0008)}
json.dump(res, open(os.path.join(OUTD, "quant37b.json"), "w"), ensure_ascii=False, default=float)
for lab, byc in res.items():
    for cst, byx in byc.items():
        for xn in ("손절35 L5", "손절50 L5"):
            r = byx[xn]; p_, c_, f_ = r["고르기"], r["확인"], r["10월"]
            print(f"{lab} | {cst} | {xn} | 고르기 ×{p_['기하평균']}/×{p_['중간값']} 월 {p_['달 진입']} x3+ {p_['x3+']} -50% {p_['-50%']}"
                  f" → 확인 ×{c_['기하평균']}/×{c_['중간값']} 월 {c_['달 진입']} x3+ {c_['x3+']} -50% {c_['-50%']} | 10월 ×{f_['중간값']}")
