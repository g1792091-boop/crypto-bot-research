"""Owners 10/25 night ("only 15 minutes?"): the best entry so far (s21 price model, three exits agreeing, BTC and
low-volatility moments out) deciding only at 1 h, 4 h or daily (00:00 KST) closes instead of every 15 minutes.
Picks: the k highest predictions of a weekday by the causal 30-day quantile among that cadence's closes; one position,
L5, stop ROE -25 % / -35 %, no hold limit, DeepCoin 0.14 % / 0.08 %. Read 2022-24, 2025-26 and October."""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
from free_core import HB, MIN, KST, DAY, GT0, ms          # noqa: E402
D = FC.Data()
A_ = np.load(os.path.join(OUTD, "ml21_price.npz")); B_ = np.load(os.path.join(OUTD, "l5m48.npz"))
TT = A_["T"].astype(np.int64); CC = A_["COIN"].astype(np.int64); LOWV = B_["LOWV"]
agg = np.nanmin(A_["PRED"], axis=2)
best = np.fmax(agg[:, 0], agg[:, 1]); side = np.where(agg[:, 0] >= agg[:, 1], 1, -1)
FWD_A, FWD_B = ms("2026-10-05 15:00"), ms("2026-10-24 14:12")
base = FC.wk(TT) & (CC != 0) & ~LOWV & np.isfinite(best)
RES = {}
for cad, step in (("15분", 15 * MIN), ("1시간", 60 * MIN), ("4시간", 240 * MIN), ("하루 (00시)", DAY)):
    on = ((TT + KST) % step) == 0
    te = np.flatnonzero(base & on); te = te[np.argsort(TT[te], kind="stable")]
    nday = 5 * DAY // step
    day = (TT[te] + KST) // DAY; ud, st = np.unique(day, return_index=True); bd = list(st) + [len(te)]
    b = best[te]
    for per_day in (1, 2, 3):
        if per_day > nday:
            continue
        q = 1 - per_day / nday; keep = np.zeros(len(te), bool)
        for i, d in enumerate(ud):
            lo = np.searchsorted(day, d - 30); hi = bd[i]
            if hi - lo < 15:
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
                key = f"{cad} / 하루 {per_day}개 / 손절 -{int(stop * 100)}% / 비용 {cost * 100:.2f}%"
                RES[key] = {"2022-24 한 달": rp["기하평균"], "2025-26 한 달": rc["기하평균"], "2025-26 x2+": rc["x2+"], "2025-26 -50%": rc["-50%"],
                            "2025-26 달 진입": rc["달 진입"], "10월 배수": round(float(np.prod(1 + w[fw])), 3), "10월 거래": int(fw.sum())}
                if cost == 0.0014:
                    print(key, RES[key], flush=True)
json.dump(RES, open(os.path.join(OUTD, "cadence53.json"), "w"), ensure_ascii=False, indent=1, default=float)
print("done")
