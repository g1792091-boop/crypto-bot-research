"""argv 1 "conf": a confirmation instead (enter once the price has gone r WITH the signal).

Owners 10/25 night: wait for a pullback before entering (market order when the price comes back r against the signal
within the wait; no limit orders). At 40x, 0.2 % better on BTC is +8 ROE points. The best entries so far (price model:
the three predictions agree / E5, causal 30-day quantile, 0.5 / 1 / 2 / 3 a day; fixed threshold 0.01 / 0.02) with
pullbacks 0 (= now) / 0.1 / 0.2 / 0.3 / 0.5 % within 15 / 60 / 240 minutes, owners' ladder L5, stops ROE -25 / -35 / -50
/ -75 %, no hold limit, one position, weekday signals, DeepCoin 0.14 % / 0.08 %."""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
import free_core as FC                                    # noqa: E402
CONF = len(sys.argv) > 1 and sys.argv[1] == "conf"
from free_core import KST, DAY                             # noqa: E402
D = FC.Data()
z = np.load(os.path.join(OUTD, "ml21_price.npz"))
P, TT, CC = z["PRED"], z["T"], z["COIN"].astype(np.int64)
SETS = {}
for how in ("최소", "E5"):
    agg = np.nanmin(P, axis=2) if how == "최소" else P[:, :, 2]
    best = np.fmax(agg[:, 0], agg[:, 1]); side = np.where(agg[:, 0] >= agg[:, 1], 1, -1)
    te = np.flatnonzero(np.isfinite(best) & FC.wk(TT)); te = te[np.argsort(TT[te], kind="stable")]
    day = (TT[te] + KST) // DAY; ud, st = np.unique(day, return_index=True); bd = list(st) + [len(te)]
    b = best[te]
    for per_day in (0.5, 1, 2, 3):
        q = 1 - per_day / 576.0; keep = np.zeros(len(te), bool)
        for i, d in enumerate(ud):
            lo = np.searchsorted(day, d - 30); hi = bd[i]
            if hi - lo < 2000:
                continue
            keep[bd[i]:bd[i + 1]] = b[bd[i]:bd[i + 1]] > np.quantile(b[lo:hi], q)
        k = te[keep]
        SETS[f"가격모델 {how} · 하루 {per_day}개"] = (TT[k], CC[k], side[k], best[k])
    if how == "E5":
        for thr in (0.01, 0.02):
            mm = np.isfinite(best) & (best > thr) & FC.wk(TT)
            SETS[f"가격모델 E5 · 기준 {thr}"] = (TT[mm], CC[mm], side[mm], best[mm])
EX = [(s, "L5") for s in (0.25, 0.35, 0.50, 0.75)]
res = {}
for lab, (t, c, s, p) in SETS.items():
    res[lab] = {}
    for cost in (0.0014, 0.0008):
        for wait in (15, 60, 240):
            for r in (0.0, 0.001, 0.002, 0.003, 0.005):
                if r == 0.0 and wait != 15:
                    continue
                res[lab][f"{cost * 100:.2f}% / 되돌림 {r * 100:.1f}% {wait}분"] = FC.run_pull(D, t, c, s, p, cost, wait, r, EX, CONF)
    print(lab, "done", flush=True)
json.dump(res, open(os.path.join(OUTD, "conf38.json" if CONF else "pull38.json"), "w"), ensure_ascii=False, default=float)
for cst in ("0.14%", "0.08%"):
    print("\n==", cst)
    for lab, byk in res.items():
        rows = [(k, xn, r) for k, byx in byk.items() if k.startswith(cst) for xn, r in byx.items()]
        base = [x for x in rows if "되돌림 0.0%" in x[0]]
        b0 = max(base, key=lambda x: x[2]["고르기"]["기하평균"])
        b1 = max(rows, key=lambda x: x[2]["고르기"]["기하평균"])
        for tag, (k, xn, r) in (("바로", b0), ("최고", b1)):
            p_, c_ = r["고르기"], r["확인"]
            print(f"{lab} | {tag} | {k} {xn} | 승률 {r['승률']} 거래당 {r['거래당']} | 고르기 ×{p_['기하평균']}/×{p_['중간값']} 월 {p_['달 진입']} -50% {p_['-50%']}"
                  f" → 확인 ×{c_['기하평균']}/×{c_['중간값']} 월 {c_['달 진입']} -50% {c_['-50%']}")
