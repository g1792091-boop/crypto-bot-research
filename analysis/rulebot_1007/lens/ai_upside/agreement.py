#!/usr/bin/env python3
"""PREREG addendum 2: signal agreement / conflict on the same coin within +-15 min and the replayed R.
    python3 -I agreement.py <out_dir>"""
import sys
sys.dont_write_bytecode = True
import site
sys.path.append(site.getusersitepackages())
import os
import numpy as np
import pandas as pd
out = sys.argv[1]
R = pd.read_csv(os.path.join(out, "rules_signals.csv"))
R = R[R["kind"].isin(["strategy", "ds200"])].copy()
RUNS = {"run-20261005T183457Z": "v3b", "current": "v4"}
R["run_s"] = R["run"].map(RUNS)
W = 15 * 60000
MODE = sys.argv[2] if len(sys.argv) > 2 else "past"   # "past" = AI-visible; "both" = +-15 min (look-ahead, leaky)
ns = []
for (run, sym), g in R.groupby(["run", "symbol"]):
    bc = g["bar_close"].to_numpy(); sd = g["side"].to_numpy(); ids = g.index.to_numpy()
    for i in range(len(g)):
        m = (np.abs(bc - bc[i]) <= W) if MODE == "both" else ((bc <= bc[i]) & (bc >= bc[i] - W))
        m[i] = False
        ns.append((ids[i], int((m & (sd == sd[i])).sum()), int((m & (sd != sd[i])).sum())))
A = pd.DataFrame(ns, columns=["idx", "n_same", "n_opp"]).set_index("idx")
R = R.join(A)
R["grp"] = np.where((R["n_same"] == 0) & (R["n_opp"] == 0), "alone", np.where(R["n_same"] > R["n_opp"], "agree", "conflict"))
R = R[R["base_status"].isin(["TRADED", "UNRESOLVED"])]
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
R["cl"] = R["run_s"] + "|" + (R["bar_close"] // (np.maximum(R["timeframe"].map(TFM), 60) * 60000)).astype(str)
rng = np.random.default_rng(21)
rows = []
for kind in ("strategy", "ds200"):
    for tf in ("15m", "30m", "1h"):
        for grp in ("alone", "agree", "conflict"):
            g = R[(R["kind"] == kind) & (R["timeframe"] == tf) & (R["grp"] == grp)]
            row = {"kind": kind, "tf": tf, "group": grp, "n": len(g), "mean_R": g["base_R"].mean(),
                   "share_of_signals": len(g) / max(len(R[(R["kind"] == kind) & (R["timeframe"] == tf)]), 1)}
            for rs in ("v3b", "v4"):
                gg = g[g["run_s"] == rs]
                row[f"n_{rs}"] = len(gg); row[f"mean_R_{rs}"] = gg["base_R"].mean() if len(gg) else np.nan
            rows.append(row)
D = pd.DataFrame(rows)
D.insert(0, "window", "past 15 min (AI-visible)" if MODE != "both" else "+-15 min (LEAKY)")
D.to_csv(os.path.join(out, "agreement.csv" if MODE != "both" else "agreement_leaky.csv"), index=False)
# conflict minus agree, cluster bootstrap
for kind in ("strategy", "ds200"):
    for tf in ("15m", "30m", "1h"):
        g = R[(R["kind"] == kind) & (R["timeframe"] == tf) & R["grp"].isin(["agree", "conflict"])]
        cl = g["cl"].to_numpy(); u, inv = np.unique(cl, return_inverse=True)
        a = g["grp"].to_numpy() == "conflict"; r = g["base_R"].to_numpy()
        sc, cc = np.bincount(inv, weights=r * a), np.bincount(inv, weights=a)
        sa, ca = np.bincount(inv, weights=r * ~a), np.bincount(inv, weights=~a)
        idx = rng.integers(0, len(u), size=(4000, len(u)))
        bs = sc[idx].sum(1) / cc[idx].sum(1) - sa[idx].sum(1) / ca[idx].sum(1)
        print(kind, tf, "conflict-agree", round(r[a].mean() - r[~a].mean(), 3), "CI", np.round(np.nanpercentile(bs, [2.5, 97.5]), 3))
pd.set_option("display.width", 200)
print(D.round(3).to_string())
