"""s41 follow-up: two loss sources were negative in every setting on the pick period (2022-24) and again on the unseen
period: BTC trades (40x: the cost is 2.2 % of the wallet per trade while BTC moves less) and entries when the coin's
1-day realized volatility is in the bottom third of its 90 days. Drop them (no new coins: this only skips BTC) and read
both periods; ladders L5, stops ROE -25 / -35 / -50 %, no hold limit, weekday entries, DeepCoin 0.14 % / 0.08 %."""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
src = open(os.path.join(HERE, "s41_pm_autopsy.py")).read().split("DIMS = {")[0]
exec(src)
EX = [(s, "L5") for s in (0.25, 0.35, 0.50)]
res = {}
for lab, (t, c, s, p) in SETS.items():
    t = np.asarray(t, np.int64); c = np.asarray(c, np.int64); s = np.asarray(s, np.int64); p = np.asarray(p, float)
    btc, own, vol, ses = attrs(t, c)
    for fx, keep in (("그대로", np.ones(len(t), bool)), ("BTC 빼기", c != 0), ("낮은 변동성 빼기", vol != 0),
                     ("BTC + 낮은 변동성 빼기", (c != 0) & (vol != 0))):
        for cost in (0.0014, 0.0008):
            out = {}
            for stop, pn in EX:
                ex = [(stop, pn)]
                FC.EXS_SAVE = FC.EXS
                r = FC.run(D, t[keep], c[keep], s[keep], p[keep], cost)
                out = {k: v for k, v in r.items() if k in (f"손절{int(stop * 100)} L5",)} | out
            res[f"{lab} / {fx} / {cost * 100:.2f}%"] = out
for k, byx in res.items():
    for xn, r in byx.items():
        p_, c_, f_ = r["고르기"], r["확인"], r["10월"]
        print(f"{k} | {xn} | 고르기 ×{p_['기하평균']}/×{p_['중간값']} 월 {p_['달 진입']} -50% {p_['-50%']} → 확인 ×{c_['기하평균']}/×{c_['중간값']} 월 {c_['달 진입']} -50% {c_['-50%']} | 10월 ×{f_['중간값']}")
json.dump(res, open(os.path.join(OUTD, "fix41b.json"), "w"), ensure_ascii=False, default=float)
