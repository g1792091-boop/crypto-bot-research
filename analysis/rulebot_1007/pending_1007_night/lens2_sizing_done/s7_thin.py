"""Thinned (about 2 trades/day) vs full sequences on the SAME strategies (those with > 2 trades/day).
    python3 -I -B s7_thin.py <out_dir>"""
import os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import pandas as pd
O = sys.argv[1]
p = pd.read_csv(os.path.join(O, "s3_paths.csv"))
rows = []
for base in ("K30", "M30"):
    th = p[p.policy == base + "_thin2"]
    keys = th[["strategy", "tfset"]].drop_duplicates()
    full = p[p.policy == base].merge(keys, on=["strategy", "tfset"])
    for name, d in (("full", full), ("thin2", th)):
        g = d.groupby(["tfset", "size", "edge", "H"]).agg(traders=("strategy", "nunique"), per_day=("per_day", "median"),
            ruin50=("ruin50", "mean"), ruin25=("ruin25", "mean"), final_med=("final_med", "median")).reset_index()
        g["policy"] = base; g["seq"] = name
        rows.append(g)
out = pd.concat(rows)
out.to_csv(os.path.join(O, "s7_thin_vs_full.csv"), index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400)
t = out[(out.H == 76) & out.tfset.isin(["15m", "15m+30m", "30m"]) & out["size"].isin(["r2", "r3", "L%"])]
print(t.pivot_table(index=["tfset", "policy", "size", "edge"], columns="seq", values=["per_day", "ruin50", "final_med"]).round(3).to_string())
