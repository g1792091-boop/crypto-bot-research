"""Gross (pre-fee, pre-slippage) R of the later runs' every-signal rows, 4h-cluster bootstrap. usage: python3 -I -B gross_ci.py <out_dir>"""
import os, site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
import numpy as np, pandas as pd
OUT = sys.argv[1]
E = pd.read_csv(os.path.join(OUT, "every_signal_rows_15_30.csv"))
E = E[(E.status == "TRADED") & (E.rn != "v3a")].copy()
E["gross"] = E.R + E.cost_R + 2 * 0.0002 / E.stop_frac
rng = np.random.default_rng(7)
for tf in ["15m", "30m"]:
    g = E[E.timeframe == tf]
    for col in ["R", "gross"]:
        cs = g.groupby("blk4").agg(s=(col, "sum"), c=(col, "size"), run=("run", "first"))
        S = np.zeros(10000); N = np.zeros(10000)
        for _, cr in cs.groupby("run"):
            idx = rng.integers(0, len(cr), (10000, len(cr)))
            S += cr.s.to_numpy()[idx].sum(1); N += cr.c.to_numpy()[idx].sum(1)
        m = S / N
        print(tf, col, len(g), "clusters", len(cs), "mean", round(g[col].mean(), 3), "CI", np.round(np.percentile(m, [2.5, 97.5]), 3))
