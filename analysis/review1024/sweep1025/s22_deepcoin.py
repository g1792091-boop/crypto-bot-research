"""DeepCoin costs (owners 10/25: the live bot runs on DeepCoin): round trip 0.14 % (taker 0.05 % + slippage 0.02 % a
side, paid) and 0.08 % (the owners' payback: final market fee 0.02 % a side, refunded later), against Bybit's 0.12 %.
The October bot (A) in the down regime and in all regimes, the regime bot (B, fixed take profits), B up/range + A down.
Read: KST months x5 before -50 % (2020-03 .. 2026-09), 2026 30-day starts, the forward 19 days, per trade 2026."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
out = {}
BOTS2 = {"A 하락장에서만": gate(A, (1,)), "A 모든 장세": A, "B 장세별 6개": B,
         "B 상승·횡보 + A 하락장": [m for m in B if m[4] != (1,)] + gate(A, (1,))}
for cost in (0.0014, 0.0012, 0.0008):
    SM.HB.COST = cost; SM._S.clear()
    for lab, mems in BOTS2.items():
        T = trades(mems, None)
        r = read(T); mo = SM.months(T)
        r["x5달 (2020~25 / 2026)"] = [mo["2020~25"][0], mo["2026"][0]]; r["달 수"] = [mo["2020~25"][2], mo["2026"][2]]
        fl = trades(mems, 21); mf = SM.months(fl)
        r["동전 x5달 (2020~25 / 2026)"] = [mf["2020~25"][0], mf["2026"][0]]
        out[f"{lab} / 왕복 {cost*100:.2f}%"] = r
        print(lab, cost, "19일", r["19일"]["x"] if isinstance(r["19일"], dict) else r["19일"], "x5달", r["x5달 (2020~25 / 2026)"],
              "동전", r["동전 x5달 (2020~25 / 2026)"], "2026 30일 x5/-50%", r["2026 시작 30일 x5/-50%"],
              "x5/-30%", r["2026 시작 30일 x5/-30%"], "2026 거래당", r["2026 1~9월 거래당"], flush=True)
json.dump(out, open(os.path.join(OUTD, "deepcoin22.json"), "w"), ensure_ascii=False, indent=1, default=float)
print("done")
