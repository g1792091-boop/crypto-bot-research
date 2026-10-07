#!/usr/bin/env python3
"""Paired R of fixed-leverage variants (late_lev_signals.csv): each pair of leverages on the signals both traded.
    python3 -I lev_pairs.py <out_dir>"""
import sys
sys.dont_write_bytecode = True
import site
sys.path.append(site.getusersitepackages())
import os
import numpy as np
import pandas as pd
out = sys.argv[1]
R = pd.read_csv(os.path.join(out, "late_lev_signals.csv"))
RUNS = {"run-20261005T183457Z": "v3b", "current": "v4"}
R["run_s"] = R["run"].map(RUNS)
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
R["cl"] = R["run_s"] + "|" + (R["bar_close"] // (np.maximum(R["timeframe"].map(TFM), 60) * 60000)).astype(str)
rng = np.random.default_rng(13)
rows = []
for kind in ("strategy", "ds200"):
    for tf in ("15m", "30m", "1h"):
        g0 = R[(R["kind"] == kind) & (R["timeframe"] == tf)]
        for a, b in ((20, 30), (30, 40), (40, 50), (20, 50)):
            ok = g0[f"lev{a}_status"].isin(["TRADED", "UNRESOLVED"]) & g0[f"lev{b}_status"].isin(["TRADED", "UNRESOLVED"])
            g = g0[ok]
            if len(g) < 10:
                rows.append({"kind": kind, "tf": tf, "pair": f"{b}x-{a}x", "n": len(g),
                             "n_rejected_at_higher": int((g0[f"lev{a}_status"].isin(["TRADED", "UNRESOLVED"]) & (g0[f"lev{b}_status"] == "REJECTED")).sum())})
                continue
            d = (g[f"lev{b}_R"] - g[f"lev{a}_R"]).to_numpy(float)
            u, inv = np.unique(g["cl"], return_inverse=True)
            sums, cnt = np.bincount(inv, weights=d), np.bincount(inv)
            idx = rng.integers(0, len(u), size=(4000, len(u)))
            bs = sums[idx].sum(1) / cnt[idx].sum(1)
            row = {"kind": kind, "tf": tf, "pair": f"{b}x-{a}x", "n": len(g), "clusters": len(u),
                   f"mean_R_low": g[f"lev{a}_R"].mean(), "mean_R_high": g[f"lev{b}_R"].mean(), "diff_R": d.mean(),
                   "ci_lo": np.percentile(bs, 2.5), "ci_hi": np.percentile(bs, 97.5),
                   "lock_share_low": (g[f"lev{a}_exit"] == "LOCK").mean(), "lock_share_high": (g[f"lev{b}_exit"] == "LOCK").mean(),
                   "n_rejected_at_higher": int((g0[f"lev{a}_status"].isin(["TRADED", "UNRESOLVED"]) & (g0[f"lev{b}_status"] == "REJECTED")).sum())}
            for rs in ("v3b", "v4"):
                gg = g[g["run_s"] == rs]
                row[f"diff_{rs}"] = (gg[f"lev{b}_R"] - gg[f"lev{a}_R"]).mean() if len(gg) else np.nan
                row[f"n_{rs}"] = len(gg)
            rows.append(row)
S = pd.DataFrame(rows)
S.to_csv(os.path.join(out, "lev_pairs.csv"), index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
print(S.round(3).to_string())
