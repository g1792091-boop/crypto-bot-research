"""Aggregate s3 over strategies: mean (and worst) ruin probabilities, median final multiple, per tfset x policy x size x edge x H.
    python3 -I -B s6_summary.py <out_dir>"""
import os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
O = sys.argv[1]
p = pd.read_csv(os.path.join(O, "s3_paths.csv"))
g = p.groupby(["tfset", "policy", "size", "edge", "H"])
s = g.agg(traders=("strategy", "size"), per_day_med=("per_day", "median"), mean_f_med=("mean_f", "median"),
          worst_f_min=("worst_f", "min"),
          ruin50_mean=("ruin50", "mean"), ruin50_max=("ruin50", "max"), ruin25_mean=("ruin25", "mean"),
          ruin25_max=("ruin25", "max"), p_loss_mean=("p_loss", "mean"), final_med_med=("final_med", "median"),
          final_p05_med=("final_p05", "median"), mdd_med_med=("mdd_med", "median"), mdd_p95_med=("mdd_p95", "median")).reset_index()
s.to_csv(os.path.join(O, "s6_paths_summary.csv"), index=False)
c = pd.read_csv(os.path.join(O, "s3_confidence.csv"), keep_default_na=False, na_values=[""])
cs = c.groupby(["tfset", "info", "edge", "design", "H"]).agg(traders=("strategy", "size"), mean_f=("mean_f", "median"),
     sd_f=("sd_f", "median"), ruin50=("ruin50", "mean"), ruin25=("ruin25", "mean"), p_loss=("p_loss", "mean"),
     final_med=("final_med", "median"), final_p05=("final_p05", "median"), mdd_med=("mdd_med", "median")).reset_index()
cs.to_csv(os.path.join(O, "s6_confidence_summary.csv"), index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
q = pd.read_csv(os.path.join(O, "s3_sequences.csv"))
qs = q.groupby(["tfset", "policy"]).agg(traders=("strategy", "size"), per_day_med=("per_day", "median"),
     per_day_min=("per_day", "min"), per_day_max=("per_day", "max"), mean_R=("mean_R", "median"),
     mean_cR=("mean_cR", "median"), M_loss_stop_med=("M_loss_stop_med", "median"), liq_gaps=("liq_gaps", "sum"),
     worst_R=("worst_trade_R", "min")).reset_index()
qs.to_csv(os.path.join(O, "s6_sequences_summary.csv"), index=False)
print(qs.round(3).to_string(index=False))
for H in (30, 76):
    t = s[(s.H == H)]
    print(f"\n=== H={H} ===")
    print(t[t.policy.isin(["K30", "K50", "K20", "K20f10", "M20", "M30", "M40", "M50", "K30_thin2", "M30_thin2"])]
          [["tfset", "policy", "size", "edge", "traders", "per_day_med", "ruin50_mean", "ruin50_max", "ruin25_mean",
            "p_loss_mean", "final_med_med", "final_p05_med", "mdd_med_med"]].round(3).to_string(index=False))
print(cs[cs.H == 76].round(3).to_string(index=False))
