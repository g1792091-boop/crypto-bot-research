"""Cost sensitivity of the recommended bot (A gated to the down regime) and of A: round trip 0.12 % (Bybit measured),
0.16 %, 0.20 % (WOO measured without payback ~0.17 %)."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
out = {}
for cost in (0.001282, 0.0014):
    SM.HB.COST = cost; SM._S.clear()
    for lab, mems in (("A 하락장에서만", gate(A, (1,))), ("A 모든 장세", A)):
        r = read(trades(mems, None)); out[f"{lab} / 왕복 {cost*100:.2f}%"] = r
        print(lab, cost, r["19일"], r["2026 시작 30일 x5/-50%"], r["2026 시작 30일 x10/-50%"], r["2026 1~9월 거래당"], flush=True)
json.dump(out, open(os.path.join(OUTD, "cost5b.json"), "w"), ensure_ascii=False, indent=1, default=float)
