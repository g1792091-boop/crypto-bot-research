#!/usr/bin/env python3
"""Disposition check at the AI's decision points: take profit early (unrealized >= +0.3R) or cut a deep loser
(unrealized <= -0.5R) at k = 1, 2, 4 bars of the signal's timeframe; hold value - exit-now value, per run.
    python3 -I disposition.py <out_dir>"""
import sys
sys.dont_write_bytecode = True
import site
sys.path.append(site.getusersitepackages())
import os
import numpy as np
import pandas as pd
out = sys.argv[1]
R = pd.read_csv(os.path.join(out, "rules_signals.csv"))
R = R[R["base_status"].isin(["TRADED", "UNRESOLVED"]) & R["kind"].isin(["strategy", "ds200"])].copy()
RUNS = {"run-20261005T183457Z": "v3b", "current": "v4"}
R["run_s"] = R["run"].map(RUNS)
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
R["cl"] = R["run_s"] + "|" + (R["bar_close"] // (np.maximum(R["timeframe"].map(TFM), 60) * 60000)).astype(str)
sf = (R["base_entry_price"] - R["base_stop_initial"]).abs() / R["base_entry_price"]
cost = 0.0012 / sf
rng = np.random.default_rng(17)
rows = []
for k in (1, 2, 4):
    u = R[f"p_unr_{k}bar_R"]
    for state, m in (("winning >= +0.3R", u >= 0.3), ("deep loser <= -0.5R", u <= -0.5), ("in between", (u > -0.5) & (u < 0.3))):
        for kind in ("strategy", "ds200", "both"):
            for tf in ("15m", "30m", "1h"):
                g = R[m & u.notna() & (R["timeframe"] == tf) & ((R["kind"] == kind) if kind != "both" else True)]
                if len(g) < 5:
                    continue
                d = (g["base_R"] - (g[f"p_unr_{k}bar_R"] - cost[g.index])).to_numpy(float)
                uu, inv = np.unique(g["cl"], return_inverse=True)
                sums, cnt = np.bincount(inv, weights=d), np.bincount(inv)
                if len(uu) >= 3:
                    idx = rng.integers(0, len(uu), size=(4000, len(uu)))
                    bs = sums[idx].sum(1) / cnt[idx].sum(1)
                    lo, hi = np.percentile(bs, [2.5, 97.5])
                    null = rng.choice([-1.0, 1.0], size=(4000, len(uu))) @ sums / len(d)
                    p = (np.sum(np.abs(null) >= abs(d.mean())) + 1) / 4001
                else:
                    lo = hi = p = np.nan
                row = {"k_bars": k, "state": state, "kind": kind, "tf": tf, "n": len(g), "clusters": len(uu),
                       "hold_minus_exit_R": d.mean(), "ci_lo": lo, "ci_hi": hi, "p_two": p}
                for rs in ("v3b", "v4"):
                    gg = g[g["run_s"] == rs]
                    row[f"n_{rs}"] = len(gg)
                    row[f"hme_{rs}"] = (gg["base_R"] - (gg[f"p_unr_{k}bar_R"] - cost[gg.index])).mean() if len(gg) else np.nan
                rows.append(row)
D = pd.DataFrame(rows)
D.to_csv(os.path.join(out, "disposition.csv"), index=False)
pd.set_option("display.width", 220); pd.set_option("display.max_columns", 20)
print(D[D["state"] != "in between"].round(3).to_string())
