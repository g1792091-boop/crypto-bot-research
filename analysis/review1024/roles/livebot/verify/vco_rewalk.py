"""vco step 2: re-walk the taken trades of B0/B3/B6/B9 (entries held fixed, one-position schedule held fixed) under
cost 0 (true gross), cost x1 (parity), cost x2, cost +6bp entry slippage (live-like), entry delayed 1 / 2 minutes;
funding part per trade. Writes vco_rewalk_<v>.csv.gz and prints per-period means. Run (no -I): python3 vco_rewalk.py"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import lb_core as L
import numpy as np, pandas as pd

VARS = sys.argv[1:] or ["B0", "B3", "B6", "B9"]
COST = L.COST
SCEN = {"c0": (0.0, 0), "c1": (COST, 0), "c2": (2 * COST, 0), "c1p6": (COST + 0.0006, 0),
        "d1": (COST, 1), "d2": (COST, 2), "c2d1": (2 * COST, 1)}
fl, gap, step, nt, ng = L.LADDER2
G = {}
for ci, coin in enumerate(L.COINS):
    g = L.grid(coin)
    G[ci] = (np.ascontiguousarray(g["o"]), np.ascontiguousarray(g["h"]), np.ascontiguousarray(g["l"]),
             np.ascontiguousarray(g["c"]), np.cumsum(g["fund"]), g["n"])
for v in VARS:
    T = pd.read_csv(os.path.join(os.path.dirname(HERE), "trades", f"trades_{v}.csv.gz"))
    lev = L.lev_of(T.coin.to_numpy())
    out = pd.DataFrame({"t": T.t, "coin": T.coin, "side": T.side, "lev": lev, "orig": T.tb_roe})
    for sc, (cost, dl) in SCEN.items():
        for opp in (False, True):
            r = np.full(len(T), np.nan); kk = np.full(len(T), -1)
            for ci in range(6):
                m = (T.coin == ci).to_numpy()
                if not m.any():
                    continue
                o, h, l, c, cumf, n = G[ci]
                es = T.e.to_numpy(np.int64)[m] + dl
                ss = T.side.to_numpy(np.int64)[m] * (-1 if opp else 1)
                fo = T.force.to_numpy(np.int64)[m]
                a = L.walk(o, h, l, c, cumf, es, ss, lev[m], fo, cost, fl, gap, step, nt, ng, L.ROE_STOP, n)
                r[m], kk[m] = a[0], a[1]
                if sc == "c1" and not opp:
                    # funding part of the trade (in ROE): lev * s * (cumf[exit] - cumf[e-1])
                    ex = es + a[1]
                    out.loc[m, "fund_roe"] = -lev[m] * ss * (cumf[np.minimum(ex, n - 1)] - cumf[es - 1])
            out[f"{sc}{'_opp' if opp else ''}"] = lev * r
    out.to_csv(os.path.join(HERE, f"vco_rewalk_{v}.csv.gz"), index=False, float_format="%.6g")
    per = L.period_name(out.t.to_numpy())
    per = np.where(np.isin(per, ["confirm", "late"]), "conf+late", per)
    out["p"] = per
    print(v, "parity c1 vs orig: max|d| =", np.nanmax(np.abs(out.c1 - out.orig)))
    cols = ["orig", "c0", "c1", "c2", "c1p6", "d1", "d2", "c2d1", "fund_roe", "c0_opp", "c1_opp", "c2_opp"]
    s = out.groupby("p")[cols].mean().mul(100).round(3)
    s["n"] = out.groupby("p").size()
    print(s.to_string())
