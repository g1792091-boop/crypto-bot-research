"""The recommended bot under the live engine's rules: paper cost 0.14 % round trip (taker 0.05 % + slippage 0.02 % a
side) or Bybit fee (0.1282 %), the ladder not armed on the entry minute; forward 19 days and 2026 / 2020-25 odds."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
import walk_bot as WB
orig = SM.HB.walk_all
out = {}
for lab_w, fn in (("진입 1분봉 포함 (연구)", orig), ("진입 1분봉 제외 (봇 규칙)", WB.walk_bot)):
    SM.HB.walk_all = fn
    for cost in (0.0012, 0.001282, 0.0014):
        SM.HB.COST = cost; SM._S.clear()
        for lab, mems in (("A 하락장에서만", gate(A, (1,))),):
            T = trades(mems, None); r = read(T); r["달"] = None
            out[f"{lab} / {lab_w} / {cost*100:.3f}%"] = r
            print(lab, lab_w, cost, r["19일"], "2026 x5/-50%", r["2026 시작 30일 x5/-50%"], "x10", r["2026 시작 30일 x10/-50%"],
                  "2020-25", r["2020~25 시작 30일 x5/-50%"], flush=True)
json.dump(out, open(os.path.join(OUTD, "botlike11.json"), "w"), ensure_ascii=False, indent=1, default=float)
