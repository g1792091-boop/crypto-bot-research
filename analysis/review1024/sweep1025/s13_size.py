"""How the live executor really sizes under the 신호등: live quantity = paper quantity x qty_scale, the scale fixed when
the switch runs (live balance / paper wallet). While the light is red the paper keeps trading and the live account does
not, so the two drift apart and the live size stops being 40 % of the live balance. s12 assumed 40 % of the live balance
on every live trade; here the executor's way, with the scale set at the start of each window (= the monthly re-run of
the switch). r = paper wallet x scale / live balance; a size above 1x is cut by the 35 % stop-loss cap (approximated
as r <= 1, "cap1") or not ("cap2", r <= 2)."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
DAY = 86_400_000


def light(w, n, q):
    live = np.ones(len(w), bool)
    if n:
        for i in range(n, len(w)):
            live[i] = (w[i - n:i] > 0).sum() >= q * n - 1e-9
    return live


def run(t, w, lv, a, b, mode, floor=0.7, goal=5.0):
    """one window [a, b): returns (result, live balance end). mode ideal / cap1 / cap2."""
    i = np.searchsorted(t, a); P = E = 1.0
    while i < len(t) and t[i] < b:
        if lv[i]:
            r = 1.0 if mode == "ideal" else min(P / E, 1.0 if mode == "cap1" else 2.0)
            E *= 1 + r * w[i]
            if E >= goal:
                return 1, E
            if E <= floor:
                return -1, E
        P *= 1 + w[i]; i += 1
    return 0, E


res = {}
T = trades(gate(A, (1,)), None)
t = T.t.to_numpy(); w = T.w.to_numpy()
for n, q in ((0, 0), (20, 0.9), (20, 0.85), (10, 0.9)):
    lv = light(w, n, q)
    for mode in ("ideal", "cap1", "cap2"):
        out = {}
        for lab, a0, b0 in (("2026 30일", "2026-01-01", "2026-09-25"), ("2020~25 30일", "2020-03-01", "2025-12-02")):
            R = np.array([run(t, w, lv, s, s + 30 * DAY, mode)[0] for s in range(ms(a0), ms(b0), DAY)])
            out[lab + " x5/-30%"] = [round(float((R == 1).mean()), 3), round(float((R == -1).mean()), 3)]
        mo = {"x5": 0, "바닥": 0, "달": 0}
        for y in range(2020, 2027):
            for m in range(1, 13):
                k = y * 100 + m
                if k < 202003 or k > 202609:
                    continue
                a = ms(f"{y}-{m:02d}-01") - 9 * 3600 * 1000
                b = ms(f"{y + (m == 12)}-{m % 12 + 1:02d}-01") - 9 * 3600 * 1000
                r, _ = run(t, w, lv, a, b, mode)
                mo["달"] += 1; mo["x5"] += r == 1; mo["바닥"] += r == -1
        out["달(2020-03~2026-09)"] = mo
        r, e = run(t, w, lv, SM.FWD_A, SM.Z, mode, floor=0.0, goal=1e9)
        out["10월19일"] = round(e, 2)
        res[f"신호등 {n} {q} / {mode}"] = out
        print(n, q, mode, json.dumps(out, ensure_ascii=False), flush=True)
json.dump(res, open(os.path.join(OUTD, "size13.json"), "w"), ensure_ascii=False, indent=1, default=float)
