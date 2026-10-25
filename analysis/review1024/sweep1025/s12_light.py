"""The executor's own gates on the recommended bot: 신호등 (follow a paper entry only while the paper's last N closed
trades won >= q; fewer than N closed: followed) and 잔고 바닥 (no new entry once the live balance is <= 70 % of the
month's start; a fresh start each KST month). Rules read on 2020-25; checked on 2026 Jan-Sep and the forward 19 days."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])


def light(T, n, q):
    w = T.w.to_numpy(); live = np.ones(len(T), bool)
    if n == 0:
        return live
    for i in range(len(T)):
        if i >= n:
            live[i] = (w[i - n:i] > 0).sum() >= q * n - 1e-9
    return live


def months(T, live, floor):
    """Fresh start each KST month on the live trades; stop the month at x5 (goal) or once at or below floor."""
    L = T[live]; d = pd.to_datetime(L.t + 9 * 3600 * 1000, unit="ms"); ym = (d.dt.year * 100 + d.dt.month).to_numpy()
    w = L.w.to_numpy(); res = {}
    for k in range(202003, 202611):
        if k % 100 == 0 or k % 100 > 12 or k == 202610:
            continue
        eq = 1.0; r = "그대로"
        for x in w[ym == k]:
            eq *= 1 + x
            if eq >= 5:
                r = "x5"; break
            if eq <= floor:
                r = "바닥"; break
        res[k] = (r, eq)
    out = {}
    for lab, a, b in (("2020~25", 202003, 202512), ("2026 1~9월", 202601, 202609)):
        v = [res[k] for k in res if a <= k <= b]
        out[lab] = {"x5": sum(r == "x5" for r, _ in v), "바닥": sum(r == "바닥" for r, _ in v), "달": len(v),
                    "끝 중간값": round(float(np.median([e for _, e in v])), 2)}
    return out


res = {}
for lab, mems in (("A 하락장에서만", gate(A, (1,))), ("A 모든 장세", A)):
    T = trades(mems, None)
    for n, q in [(0, 0)] + [(n, q) for n in (10, 20, 30) for q in (0.75, 0.8, 0.85, 0.9)]:
        lv = light(T, n, q); L = T[lv].reset_index(drop=True)
        r = {"실거래 비율": round(float(lv.mean()), 3), "달(바닥 0.7)": months(T, lv, 0.7), "달(바닥 0.5)": months(T, lv, 0.5),
             "2026 30일 x5/-30%": [round(v, 3) for v in SM.roll(L, ms("2026-01-01"), ms("2026-09-25"), floor=0.7)],
             "2020~25 30일 x5/-30%": [round(v, 3) for v in SM.roll(L, ms("2020-03-01"), ms("2025-12-02"), floor=0.7)],
             "19일": round(SM.forward(L)["x"], 2), "19일 거래": SM.forward(L)["n"]}
        res[f"{lab} / 신호등 {n} {q}"] = r
        print(lab, n, q, json.dumps(r, ensure_ascii=False), flush=True)
json.dump(res, open(os.path.join(OUTD, "light12.json"), "w"), ensure_ascii=False, indent=1, default=float)
