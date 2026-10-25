"""Sweep 4b: the regime bot with ladder exits only (what the combined bot runs today), and the BTC 4h regime now."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
src = open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0]
exec(src)
print("BTC 4h regime of the last closed bars:", list(zip(pd.to_datetime(CLOSE[-8:] + 9*3600*1000, unit="ms").strftime("%m-%d %H:%M"), REG[-8:])))
d = pd.to_datetime(CLOSE + 9*3600*1000, unit="ms")
oc = (d >= "2026-10-06") & (d < "2026-10-25")
print("October 19 days regime share (up/down/range):", [round(float((REG[oc] == r).mean()), 2) for r in range(3)])
for y in (2021, 2022, 2023, 2024, 2025, 2026):
    m = d.year == y
    print(y, [round(float((REG[m] == r).mean()), 2) for r in range(3)])
L3A, L2A = X["손절 3ATR · 익절 없음 · 계단 12→10 / 5"], X["손절 2ATR · 익절 없음 · 계단 12→10 / 5"]
BU = [m for m in B if m[4] != (1,)]
BOTS = {}
for lab, xx in (("계단 ROE -75%", L75), ("계단 3ATR", L3A), ("계단 2ATR", L2A)):
    BOTS[f"상승·횡보 4개({lab}) + A 하락장"] = [(c, f, m, xx, r) for c, f, m, _, r in BU] + gate(A, (1,))
BOTS["상승·횡보 4개(고정 익절, 기준) + A 하락장"] = BU + gate(A, (1,))
res = {}
for lab, mems in BOTS.items():
    r = read(trades(mems, None)); r["동전"] = [read(trades(mems, s)) for s in (21, 22, 23)]
    res[lab] = r
    print("==", lab, json.dumps({k: v for k, v in r.items() if k != "동전"}, ensure_ascii=False, default=float), flush=True)
    print("   동전 2026 x5/-50%:", [d_["2026 시작 30일 x5/-50%"] for d_ in r["동전"]], " 19일:", [d_["19일"]["x"] for d_ in r["동전"]], flush=True)
json.dump(res, open(os.path.join(OUTD, "combo4b.json"), "w"), ensure_ascii=False, indent=1, default=float)
