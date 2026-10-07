#!/usr/bin/env python3
"""5y per strategy x tf gross R: week-block bootstrap one-sided p (gross > 0), several seeds for the CI lower bound,
BH over the cells. python3 -I v8_cells_bh.py <v3_5y.csv.gz>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vboot  # noqa
import numpy as np, pandas as pd
D = pd.read_csv(sys.argv[1])
D = D[(D["reason"] < 3) & (D["reason_flip"] < 3)]
D["gR"] = D["gross_n"] / D["stop_frac"]
t = pd.to_datetime(D["ts"])
D["week"] = (t.dt.floor("D") - pd.to_timedelta(t.dt.weekday, unit="D")).astype("int64")
rows = []
for (s, tf), g in D.groupby(["strategy", "tf"]):
    if len(g) < 50:
        continue
    u, inv = np.unique(g["week"].to_numpy(), return_inverse=True)
    sm = np.bincount(inv, weights=g["gR"].to_numpy()); c = np.bincount(inv)
    los = []
    for seed in range(5):
        rng = np.random.default_rng(100 + seed)
        d = rng.integers(0, len(u), size=(4000, len(u)))
        m = sm[d].sum(1) / c[d].sum(1)
        los.append(np.percentile(m, 2.5))
        if seed == 0:
            p = (m <= 0).mean()
    rows.append(dict(strategy=s, tf=tf, n=len(g), gross_R=g["gR"].mean(), lo_min=min(los), lo_max=max(los), p_pos=p))
R = pd.DataFrame(rows).sort_values("p_pos")
m = len(R)
R["bh_q"] = (R["p_pos"] * m / np.arange(1, m + 1))[::-1].cummin()[::-1].clip(upper=1)
print("cells", m)
print(R.head(10).round(4).to_string(index=False))
