#!/usr/bin/env python3
"""Directional discovery->test repeated on winsorized R (clip -2..3), win rate and gross R estimate (CR1 2h SEs from
scan_full.csv, normal approximation). Counts only.   python3 -I robust_dir.py <out_dir>"""
import os, site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))
import numpy as np, pandas as pd
from scipy import stats
from stats_util import bh
OUT = sys.argv[1]
T = pd.read_csv(os.path.join(OUT, "scan_full.csv"))
rows = []
for oc in ("Rw", "win", "gross"):
    for name, ds, ts, tk in (("A v3a->v3b+v4", "v3a", "v3b+v4", "strategy"), ("B v4->v3a+v3b", "v4", "v3a+v3b", "strategy"),
                             ("T v3a->v4 ds200", "v3a", "v4", "ds200")):
        a = T[(T.scope == ds) & (T.kind == "strategy") & T.tf.isin(["15m", "30m"]) & T.testable].set_index(["tf", "feature", "bucket"])
        b = T[(T.scope == ts) & (T.kind == tk) & T.tf.isin(["15m", "30m"]) & T.testable].set_index(["tf", "feature", "bucket"])
        J = a.join(b, lsuffix="_a", rsuffix="_b", how="inner")
        za = J[f"d_{oc}_a"] / J[f"se_{oc}_a"]
        pa = 2 * stats.norm.sf(np.abs(za))
        car = pa < 0.05
        zb = np.sign(J[f"d_{oc}_a"]) * J[f"d_{oc}_b"] / J[f"se_{oc}_b"]
        pb = stats.norm.sf(zb)
        q, _ = bh(np.where(car, pb, np.nan))
        rows.append({"outcome": oc, "direction": name, "tested_disc": len(J), "disc_p<.05": int(car.sum()),
                     "test_1s_p<.05": int(((pb < .05) & car).sum()), "test_q<.05": int(np.nansum(q < .05)),
                     "same_sign_among_carried": int(((np.sign(J[f"d_{oc}_a"]) == np.sign(J[f"d_{oc}_b"])) & car).sum()),
                     "corr_all_effects": float(np.corrcoef(J[f"d_{oc}_a"], J[f"d_{oc}_b"])[0, 1]),
                     "survivors": "; ".join(f"{i[0]} {i[1]}={i[2]}" for i in J.index[(q < .05)])})
R = pd.DataFrame(rows)
R.to_csv(os.path.join(OUT, "robust_directional.csv"), index=False)
pd.set_option("display.width", 250)
print(R.to_string())
