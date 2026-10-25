"""New method 2 (10/25): trade live only while the bot is hot. The bot runs on paper all the time; a trade is taken with
real money only when its own recent paper trades pass a rule (last N trades net positive / win rate >= q / paper equity
up over the last D days). Rules are read on 2020-2025 and checked on 2026 Jan-Sep and the forward 19 days."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
DAY = 86_400_000


def gate_mask(T, rule):
    w = T.w.to_numpy(); t = T.t.to_numpy(); ex = t + T.k.to_numpy() * 60000
    kind, p, q = rule
    live = np.zeros(len(T), bool)
    if kind == "all":
        return np.ones(len(T), bool)
    for i in range(len(T)):
        done = np.flatnonzero(ex[:i] <= t[i]) if kind == "days" else np.arange(max(0, i - p), i)
        if kind == "sum":
            live[i] = len(done) == p and w[done].sum() > 0
        elif kind == "win":
            live[i] = len(done) == p and (w[done] > 0).mean() >= q
        elif kind == "days":
            m = done[(t[done] >= t[i] - p * DAY)]
            live[i] = len(m) >= 3 and np.prod(1 + w[m]) > 1 + q
    return live


def read(T, live):
    L = T[live].reset_index(drop=True); w = L.w.to_numpy(); t = L.t.to_numpy()
    d = pd.to_datetime(t + 9 * 3600 * 1000, unit="ms"); y = d.year.to_numpy(); ym = (d.year * 100 + d.month).to_numpy()
    out = {"실거래 비율": round(float(live.mean()), 3)}
    for yy in range(2020, 2027):
        m = (y == yy) & (t < SM.FWD_A)
        out[str(yy)] = round(float(w[m].mean()), 4) if m.any() else None
    hit = {"2020~25": 0, "2026": 0}; bust = {"2020~25": 0, "2026": 0}
    for k in np.unique(ym):
        if k >= 202610:
            continue
        eq = np.cumprod(1 + w[ym == k]); p = "2026" if k >= 202601 else "2020~25"
        for v in eq:
            if v >= 5:
                hit[p] += 1; break
            if v <= 0.5:
                bust[p] += 1; break
    out["x5달"] = hit; out["-50%달"] = bust
    f = t >= SM.FWD_A
    out["10월19일"] = round(float(np.prod(1 + w[f])), 2); out["10월 실거래"] = int(f.sum())
    out["2026 30일 x5/-50%"] = [round(v, 3) for v in SM.roll(L, ms("2026-01-01"), ms("2026-09-25"))]
    return out


RULES = [("all", 0, 0)] + [("sum", n, 0) for n in (3, 5, 10, 20)] + [("win", n, q) for n in (5, 10, 20) for q in (0.9, 1.0)] + \
        [("days", dd, g) for dd in (2, 3, 7) for g in (0.0, 0.2, 0.5)]
res = {}
for lab, mems in (("A 하락장에서만", gate(A, (1,))), ("A 모든 장세", A), ("B 상승·횡보 + A 하락장", [m for m in B if m[4] != (1,)] + gate(A, (1,)))):
    T = trades(mems, None)
    for rule in RULES:
        r = read(T, gate_mask(T, rule)); res[f"{lab} / {rule}"] = r
        print(lab, rule, json.dumps(r, ensure_ascii=False), flush=True)
json.dump(res, open(os.path.join(OUTD, "gate10.json"), "w"), ensure_ascii=False, indent=1, default=float)
