"""Merge live per-strategy numbers with the 5-year filtered numbers -> strategy_context_grades.csv
    python3 -I strategy_table.py <out_dir> <out5y_dir>"""
import os, site, sys
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
OUT, O5 = sys.argv[1:3]
L = pd.read_csv(os.path.join(OUT, "per_strategy_live.csv"))
F5 = pd.read_csv(os.path.join(O5, "fiveyear_filter_by_strategy.csv")).rename(columns={"tf": "tf"})
M = L.merge(F5[["tf", "strategy", "n_cf", "mean_R_cf", "mean_R_kept", "se_mean_R_kept", "uplift", "se_uplift"]],
            on=["tf", "strategy"], how="left")
M = M[M["n"] >= 30].copy()
def grade(r):
    lo = r["R_pooled"] - 1.96 * r["se_pooled"]
    hi = r["R_pooled"] + 1.96 * r["se_pooled"]
    neg5 = (r["mean_R_kept"] + 1.96 * r["se_mean_R_kept"] < 0) if r["mean_R_kept"] == r["mean_R_kept"] else None
    if hi < 0:
        g = "D"
    elif r["R_pooled"] < 0:
        g = "C"
    else:
        g = "C+"
    if neg5 is None:
        g += " (no 5y ctx)"
    elif neg5:
        g += " (5y filtered < 0)"
    return g
M["grade"] = M.apply(grade, axis=1)
cols = ["kind", "strategy", "tf", "family", "n", "n_v3a", "n_v3b", "n_v4", "R_v3a", "R_v3b", "R_v4", "R_pooled", "se_pooled",
        "sideflip_excess_R", "n_cf", "mean_R_cf", "mean_R_kept", "se_mean_R_kept", "uplift", "grade"]
M = M[cols].sort_values(["tf", "R_pooled"], ascending=[True, False])
M.to_csv(os.path.join(OUT, "strategy_context_grades.csv"), index=False)
pd.set_option("display.width", 250)
print(M.round(3).to_string())
