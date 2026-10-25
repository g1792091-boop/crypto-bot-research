"""Which condition moves 'x5 every month' the most? The recommended bots with one condition changed at a time:
round-trip cost (0.04 % ~ maker both sides, 0.08 %, 0.12 % base), margin share (40 % base, 60 %, 80 %, 100 %) at the
same 40x / 30x, and two positions at once (40 % margin each). Read: KST months with a fresh start (x5 before -50 %),
the longest run of x5 months, x5 within 30 days from every 2026 start day, and the forward 19 days."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])


def merge_n(T_list, slots):
    T = pd.concat(T_list, ignore_index=True).sort_values(["t", "tfo"], ascending=[True, False]).reset_index(drop=True)
    if slots == 1:
        return SM.H.merge(T_list)
    t = T.t.to_numpy(); k = T.k.to_numpy(); co = T.coin.to_numpy(); keep = np.zeros(len(T), bool); open_ = []
    for i in range(len(T)):
        open_ = [(e, c) for e, c in open_ if e > t[i]]
        if len(open_) < slots and all(c != co[i] for _, c in open_):
            keep[i] = True; open_.append((t[i] + k[i] * 60000, co[i]))
    return T[keep].reset_index(drop=True)


def months(T):
    d = pd.to_datetime(T.t + 9 * 3600 * 1000, unit="ms"); key = (d.dt.year * 100 + d.dt.month).to_numpy()
    hits, bust, pos = [], 0, 0
    for k in range(202003, 202611):
        if k % 100 == 0 or k % 100 > 12:
            continue
        w = T.w.to_numpy()[key == k]; eq = np.cumprod(1 + w) if len(w) else np.array([1.0]); r = 0
        for v in eq:
            if v >= 5:
                r = 1; break
            if v <= 0.5:
                r = -1; break
        hits.append(r == 1); bust += r == -1; pos += eq[-1] >= 1
    s = "".join("1" if h else "0" for h in hits)
    return {"x5달": int(sum(hits)), "달": len(hits), "-50%먼저": int(bust), "플러스": int(pos),
            "연속최대": max(len(x) for x in s.split("0"))}


BOTS = {"A 하락장에서만": gate(A, (1,)), "A 모든 장세": A, "B 상승·횡보 + A 하락장": [m for m in B if m[4] != (1,)] + gate(A, (1,))}
LEVERS = [("기준 (0.12%, 40%, 1포지션)", 0.0012, 0.40, 1), ("비용 0.08%", 0.0008, 0.40, 1), ("비용 0.04%", 0.0004, 0.40, 1),
          ("증거금 60%", 0.0012, 0.60, 1), ("증거금 80%", 0.0012, 0.80, 1), ("증거금 100%", 0.0012, 1.00, 1),
          ("2포지션 (각 40%)", 0.0012, 0.40, 2), ("비용 0.04% + 증거금 80%", 0.0004, 0.80, 1)]
out = {}
for blab, mems in BOTS.items():
    for llab, cost, margin, slots in LEVERS:
        SM.HB.COST = cost; SM.HB.MARGIN = margin; SM._S.clear()
        TL = []
        for c, f, m, x, regs in mems:
            tr = SM.trades(c, f, m, x)
            if regs is not None:
                tr = tr[np.isin(reg_at(tr.t.to_numpy()), regs)]
            TL.append(tr)
        T = merge_n(TL, slots)
        r = {"달": months(T), "2026 30일 x5/-50%": [round(v, 3) for v in SM.roll(T, ms("2026-01-01"), ms("2026-09-25"))],
             "19일": round(SM.forward(T)["x"], 2)}
        out[f"{blab} / {llab}"] = r
        print(blab, "|", llab, "|", json.dumps(r, ensure_ascii=False), flush=True)
json.dump(out, open(os.path.join(OUTD, "levers7.json"), "w"), ensure_ascii=False, indent=1, default=float)
