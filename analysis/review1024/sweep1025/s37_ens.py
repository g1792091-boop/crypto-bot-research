"""Owners 10/25 night: the price model holds three predictions per side (trained on three different exits). Enter only
when they agree: the smallest of the three (or their mean) above a threshold, same side; owners' ladders L5 / L10,
stops ROE -25 / -35 / -50 / -75 %, no hold limit, weekday entries, one position. Does agreement buy quality at the same
count? Read as s35 (pick 2022-24, check 2025-01 .. 2026-09, October apart)."""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
D = FC.Data()
z = np.load(os.path.join(OUTD, "ml21_price.npz"))
P, TT, CC = z["PRED"], z["T"], z["COIN"].astype(np.int64)
SETS = {}
for how in ("최소", "평균"):
    agg = np.nanmin(P, axis=2) if how == "최소" else np.nanmean(P, axis=2)
    best = np.fmax(agg[:, 0], agg[:, 1]); side = np.where(agg[:, 0] >= agg[:, 1], 1, -1)
    for thr in (0.0, 0.0025, 0.005, 0.01, 0.015, 0.02):
        mm = np.isfinite(best) & (best > thr) & FC.wk(TT)
        if mm.sum() < 50:
            continue
        SETS[f"가격모델 3개 {how} {thr}"] = (TT[mm], CC[mm], side[mm], best[mm])
res = {}
for lab, (t, c, s, p) in SETS.items():
    res[lab] = {f"{cost * 100:.2f}%": FC.run(D, t, c, s, p, cost) for cost in (0.0014, 0.0008)}
json.dump(res, open(os.path.join(OUTD, "ens37.json"), "w"), ensure_ascii=False, default=float)
for lab, byc in res.items():
    for cst, byx in byc.items():
        b = max(byx.items(), key=lambda kv: kv[1]["고르기"]["기하평균"])
        p_, c_ = b[1]["고르기"], b[1]["확인"]
        print(f"{lab} | {cst} | {b[0]} | 고르기 ×{p_['기하평균']}/×{p_['중간값']} 월 {p_['달 진입']} x3+ {p_['x3+']} -50% {p_['-50%']}"
              f" → 확인 ×{c_['기하평균']}/×{c_['중간값']} 월 {c_['달 진입']} x3+ {c_['x3+']} -50% {c_['-50%']}")
