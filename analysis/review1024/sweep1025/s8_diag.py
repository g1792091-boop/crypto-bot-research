"""Diagnosis: per trade, how big is the direction edge before costs next to the cost itself, by year, for the
recommended bots (same sizing: wallet share per trade)."""
import os, sys, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
out = {}
for lab, mems in (("A 하락장에서만", gate(A, (1,))), ("A 모든 장세", A), ("B 상승·횡보 + A 하락장", [m for m in B if m[4] != (1,)] + gate(A, (1,)))):
    T = trades(mems, None)
    lev = np.where(T.coin.to_numpy() == 0, 40.0, 30.0)
    cost_w = 0.40 * lev * SM.HB.COST                        # wallet share paid in costs per trade
    gross = T.w.to_numpy() + cost_w
    d = pd.to_datetime(T.t + 9 * 3600 * 1000, unit="ms"); y = d.dt.year.to_numpy()
    rows = {}
    for yy in range(2020, 2027):
        m = y == yy
        rows[int(yy)] = {"거래": int(m.sum()), "비용 전 거래당": round(float(gross[m].mean()), 4), "비용": round(float(cost_w[m].mean()), 4),
                         "비용 후 거래당": round(float(T.w.to_numpy()[m].mean()), 4), "승률": round(float((T.w.to_numpy()[m] > 0).mean()), 3)}
    f = (T.t >= SM.FWD_A).to_numpy()
    rows["10월19일"] = {"거래": int(f.sum()), "비용 전 거래당": round(float(gross[f].mean()), 4), "비용": round(float(cost_w[f].mean()), 4),
                       "비용 후 거래당": round(float(T.w.to_numpy()[f].mean()), 4), "승률": round(float((T.w.to_numpy()[f] > 0).mean()), 3)}
    out[lab] = rows
    print("==", lab)
    for k, v in rows.items():
        print("  ", k, v)
json.dump(out, open(os.path.join(OUTD, "diag8.json"), "w"), ensure_ascii=False, indent=1)
