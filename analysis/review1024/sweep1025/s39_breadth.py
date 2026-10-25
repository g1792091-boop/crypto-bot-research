"""Owners 10/25 night: market-wide agreement. At a 15m close, when the price model (E5 and the three-exit minimum) leans
the same way on k or more of the 6 coins (prediction above c), enter that way on the coin with the strongest
prediction. k = 2 / 3 / 4 / 5, c = 0 / 0.0025 / 0.005 / 0.01. Owners' ladder L5, stops ROE -25 / -35 / -50 / -75 %, no
hold limit, one position, weekday entries, DeepCoin 0.14 % / 0.08 %."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
D = FC.Data()
z = np.load(os.path.join(OUTD, "ml21_price.npz"))
P, TT, CC = z["PRED"], z["T"], z["COIN"].astype(np.int64)
SETS = {}
for how in ("최소", "E5"):
    agg = np.nanmin(P, axis=2) if how == "최소" else P[:, :, 2]
    ok = np.isfinite(agg[:, 0]) & np.isfinite(agg[:, 1]) & FC.wk(TT)
    df = pd.DataFrame({"T": TT[ok], "coin": CC[ok], "pl": agg[ok, 0], "ps": agg[ok, 1]})
    for c in (0.0, 0.0025, 0.005, 0.01):
        g = df.assign(L=df.pl > c, S=df.ps > c).groupby("T")
        nl, ns = g.L.sum(), g.S.sum()
        for k in (2, 3, 4, 5):
            tl = nl.index[nl >= k]; ts = ns.index[ns >= k]
            a = df[df["T"].isin(tl)].sort_values("pl", ascending=False).drop_duplicates("T")
            b = df[df["T"].isin(ts)].sort_values("ps", ascending=False).drop_duplicates("T")
            t = np.r_[a["T"].to_numpy(), b["T"].to_numpy()]
            if len(t) < 30:
                continue
            SETS[f"{how} · {k}개 코인 이상 · 예측 > {c}"] = (t, np.r_[a.coin.to_numpy(), b.coin.to_numpy()],
                                                       np.r_[np.ones(len(a), int), -np.ones(len(b), int)],
                                                       np.r_[a.pl.to_numpy(), b.ps.to_numpy()])
res = {}
for lab, (t, c_, s, p) in SETS.items():
    res[lab] = {f"{cost * 100:.2f}%": FC.run(D, t, c_, s, p, cost) for cost in (0.0014, 0.0008)}
json.dump(res, open(os.path.join(OUTD, "breadth39.json"), "w"), ensure_ascii=False, default=float)
for lab, byc in res.items():
    for cst, byx in byc.items():
        b = max(byx.items(), key=lambda kv: kv[1]["고르기"]["기하평균"]); p_, c2 = b[1]["고르기"], b[1]["확인"]
        print(f"{lab} | {cst} | {b[0]} | 고르기 ×{p_['기하평균']}/×{p_['중간값']} 월 {p_['달 진입']} x3+ {p_['x3+']} -50% {p_['-50%']}"
              f" → 확인 ×{c2['기하평균']}/×{c2['중간값']} 월 {c2['달 진입']} x3+ {c2['x3+']} -50% {c2['-50%']}")
