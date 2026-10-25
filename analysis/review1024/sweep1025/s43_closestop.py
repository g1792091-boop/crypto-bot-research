"""Owners 10/25 night (found, not asked): about a quarter of the stop-outs went back to the ladder's first step within
4 h, so the stops are often taken by wicks. The best entries (price model: three predictions agree, 1 / 2 / 3 a day;
E5 above 0.01), with and without the two loss fixes (no BTC, no low-volatility entries), with the ROE stop checked on
1m / 5m / 15m / 1h closes instead of on touch (the liquidation distance still intrabar), ladder L5, stops ROE -25 / -35
/ -50 / -75 %, no hold limit, one position, weekday entries, DeepCoin 0.14 % / 0.08 %."""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out"); sys.path.insert(0, HERE)
src = open(os.path.join(HERE, "s41_pm_autopsy.py")).read().split("DIMS = {")[0]
exec(src)
res = {}
for lab, (t, c, s, p) in SETS.items():
    t = np.asarray(t, np.int64); c = np.asarray(c, np.int64); s = np.asarray(s, np.int64); p = np.asarray(p, float)
    btc, own, vol, ses = attrs(t, c)
    for fx, keep in (("그대로", np.ones(len(t), bool)), ("BTC + 낮은 변동성 빼기", (c != 0) & (vol != 0))):
        tt, cc, ss, pp = t[keep], c[keep], s[keep], p[keep]
        o_ = np.lexsort((-pp, tt)); tt, cc, ss = tt[o_], cc[o_], ss[o_]
        cst = D.off[cc] + ((tt - GT0) // MIN); csend = D.off[cc + 1]; coff = D.off[cc].astype(np.int64)
        lev = HB.LEVC[cc].astype(float)
        for cost in (0.0014, 0.0008):
            for every, hard in ((0, 0.0), (1, 0.0), (5, 0.0), (15, 0.0), (60, 0.0), (1, 0.75), (5, 0.75), (15, 0.75), (5, 0.6), (15, 0.6)):
                for stop in (0.25, 0.35, 0.50):
                    if every == 0:
                        ti, w, _ = FC.seq_sim(D.o, D.h, D.l, D.c, cst, ss, tt, csend, lev, stop, 0, 0.0, 0.12, 0.10, 0.05, cost, HB.MARGIN)
                    else:
                        ti, w = FC.seq_sim_close(D.o, D.h, D.l, D.c, cst, ss, tt, csend, lev, coff, every, stop, 0.12, 0.10, 0.05, cost, HB.MARGIN, hard)
                    t2 = tt[ti]
                    res[f"{lab} / {fx} / {cost * 100:.2f}% / {'꼬리' if every == 0 else f'{every}분봉 종가' + (f' + 비상 {int(hard * 100)}%' if hard else '')} / 손절 -{int(stop * 100)}%"] = {
                        "고르기": FC.read(t2, w, 202201, 202412), "확인": FC.read(t2, w, 202501, 202609), "10월": FC.read(t2, w, 202610, 202610),
                        "거래당": round(float(w.mean()), 4), "승률": round(float((w > 0).mean()), 3)}
json.dump(res, open(os.path.join(OUTD, "closestop43.json"), "w"), ensure_ascii=False, default=float)
for k, r in res.items():
    if "하루 1개" in k or "E5" in k:
        p_, c_ = r["고르기"], r["확인"]
        print(f"{k} | 거래당 {r['거래당']} 승률 {r['승률']} | 고르기 ×{p_['기하평균']}/×{p_['중간값']} 월 {p_['달 진입']} -50% {p_['-50%']} → 확인 ×{c_['기하평균']}/×{c_['중간값']} -50% {c_['-50%']}")
