"""Owners 10/25 night, "keep searching": the two price models together. The s21 model (three exits, the picks of 5-20 /
5-21) and the s48 model trained on the owners' L5 exit with stop ROE -25 % / -35 %: a side is taken only when the
minimum over the five predictions is the best; picks per weekday KST day by the causal 30-day quantile (1 / 2 / 3 a
day), as in s41; without BTC and without low-volatility moments (s41). One position, L5, stop ROE -25 % / -35 %, no
hold limit, DeepCoin 0.14 % / 0.08 %. Read 2022-01 .. 2024-12, 2025-01 .. 2026-09 and the 20 live days of October.
Compared with the s21 model alone (the same reading) and with the s48 model alone."""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, MIN, KST, DAY, GT0, ms          # noqa: E402
D = FC.Data()
A_ = np.load(os.path.join(OUTD, "ml21_price.npz")); B_ = np.load(os.path.join(OUTD, "l5m48.npz"))
assert (A_["T"] == B_["T"]).all() and (A_["COIN"].astype(int) == B_["COIN"].astype(int)).all()
TT = A_["T"].astype(np.int64); CC = A_["COIN"].astype(np.int64); LOWV = B_["LOWV"]
PA = A_["PRED"]; PB = B_["PRED"]                         # (n, side, exits)
FWD_A, FWD_B = ms("2026-10-05 15:00"), ms("2026-10-24 14:12")
base = FC.wk(TT) & (CC != 0) & ~LOWV
VAR = {"기존 모델 (세 예측)": np.nanmin(PA, axis=2), "L5 모델 (두 예측)": np.nanmin(PB, axis=2),
       "두 모델 모두 (다섯 예측)": np.fmin(np.nanmin(PA, axis=2), np.nanmin(PB, axis=2))}
RES = {}
for vn, agg in VAR.items():
    best = np.fmax(agg[:, 0], agg[:, 1]); side = np.where(agg[:, 0] >= agg[:, 1], 1, -1)
    te = np.flatnonzero(np.isfinite(best) & base & np.isfinite(PA[:, 0, 0]) & np.isfinite(PB[:, 0, 0]))
    te = te[np.argsort(TT[te], kind="stable")]
    day = (TT[te] + KST) // DAY; ud, st = np.unique(day, return_index=True); bd = list(st) + [len(te)]
    b = best[te]
    for per_day in (1, 2, 3):
        q = 1 - per_day / 480.0; keep = np.zeros(len(te), bool)
        for i, d in enumerate(ud):
            lo = np.searchsorted(day, d - 30); hi = bd[i]
            if hi - lo < 2000:
                continue
            keep[bd[i]:bd[i + 1]] = b[bd[i]:bd[i + 1]] > np.quantile(b[lo:hi], q)
        k = te[keep]
        t, c, s, p = TT[k], CC[k], side[k], best[k]
        o_ = np.lexsort((-p, t)); t, c, s = t[o_], c[o_], s[o_]
        cst = D.off[c] + ((t - GT0) // MIN); csend = D.off[c + 1]
        for stop in (0.25, 0.35):
            for cost in (0.0014, 0.0008):
                ti, w, _ = FC.seq_sim(D.o, D.h, D.l, D.c, cst, s.astype(np.int64), t, csend, HB.LEVC[c].astype(float), stop, 0, 0.0,
                                      0.12, 0.10, 0.05, cost, HB.MARGIN)
                t2 = t[ti]; fw = (t2 >= FWD_A) & (t2 < FWD_B)
                rp = FC.read(t2, w, 202201, 202412); rc = FC.read(t2, w, 202501, 202609)
                key = f"{vn} / 하루 {per_day}개 / 손절 -{int(stop * 100)}% / 비용 {cost * 100:.2f}%"
                RES[key] = {"2022-24 한 달": rp["기하평균"], "2022-24 x3+": rp["x3+"], "2025-26 한 달": rc["기하평균"], "2025-26 중간값": rc["중간값"],
                            "2025-26 x3+": rc["x3+"], "2025-26 -50%": rc["-50%"], "2025-26 달 진입": rc["달 진입"], "2025-26 최고": rc["최고"],
                            "2025-26 거래당": round(float(w[(FC.ym_of(t2) >= 202501) & (FC.ym_of(t2) <= 202609)].mean()), 4),
                            "10월 배수": round(float(np.prod(1 + w[fw])), 3), "10월 거래": int(fw.sum())}
                print(key, RES[key], flush=True)
json.dump(RES, open(os.path.join(OUTD, "agree48b.json"), "w"), ensure_ascii=False, indent=1, default=float)
print("done")
