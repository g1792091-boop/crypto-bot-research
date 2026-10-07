import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from vlib import *
for kind in ["ds200", "strategy"]:
    R = load_replay(kind=kind); T = R[R.status == "TRADED"].copy()
    T["aid"] = T.strategy + "@" + T.timeframe
    for tf in ["15m", "30m"]:
        g = T[T.timeframe == tf]
        print(kind, tf, g.groupby(["acct_status", "acct_reason"]).R.agg(["size", "mean"]).round(3).to_dict("index"))
        # same account, same bar: entered vs lower-score skipped
        e = g[g.acct_status == "ENTERED"][["aid", "bar_close", "R", "symbol"]]
        s = g[(g.acct_status == "SKIPPED") & g.acct_reason.str.contains("lower score", na=False)][["aid", "bar_close", "R", "symbol"]]
        m = e.merge(s, on=["aid", "bar_close"], suffixes=("_e", "_s"))
        if len(m):
            pe = m.groupby(["aid", "bar_close"]).agg(Re=("R_e", "first"), Rs=("R_s", "mean")).reset_index()
            c = crse(pe.Re - pe.Rs, pe.bar_close // H)
            print("   same-bar entered - lower-score skipped: %.3f n%d G%d CI [%.2f, %.2f]" % (c["mean"], c["n"], c["G"], c.get("lo", np.nan), c.get("hi", np.nan)))
