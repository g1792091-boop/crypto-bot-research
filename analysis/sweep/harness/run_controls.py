"""Positive / negative controls of the gate on a SYNTHETIC IS-length 7-coin panel (default) or on
a real panel (--split is, for the Discover agents; not run by the harness agent).
usage: python3 run_controls.py --tf 1h [--reps 200] [--split synthetic|is] [--out DIR]"""
import argparse
import os
import sys
import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_lib as L  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--tf", required=True)
ap.add_argument("--reps", type=int, default=200)
ap.add_argument("--split", default="synthetic")
ap.add_argument("--n_targets", default="150,500,2000")
ap.add_argument("--kinds", default="iid,burst4,voltimed,hourtimed")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--out", default=os.path.join(HERE, "out"))
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
t0 = time.time()
if a.split == "synthetic":
    panel = L.synth_panel(a.tf, n_days=1096, seed=1000 + L.tf_minutes(a.tf))
    split = "is"   # synthetic dates 2021-07-01.. -> use the IS window definition
else:
    panel = L.load_panel(a.tf, a.split)
    split = a.split
res = L.controls(a.tf, panel, split=split, reps=a.reps, n_targets=[int(x) for x in a.n_targets.split(",")],
                 kinds=a.kinds.split(","), seed=a.seed)
res["data"] = a.split
res["sec"] = time.time() - t0
fn = os.path.join(a.out, f"controls_{a.split}_{a.tf}.csv")
res.to_csv(fn, index=False)
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
cols = ["tf", "H", "kind", "n_target", "n_mean", "mu_star", "null_rate_p05", "null_rate_emp05", "null_rate_p01",
        "null_rate_holm1", "null_rate_gate", "null_rate_naive_t05", "null_z_sd", "mde80_over_mu", "power_gate",
        "power_p05", "planted_frac_fwd_ge_mu", "vn_null_rate_p05", "vn_null_z_sd", "null_rate_gate_and_vn",
        "power_gate_and_vn", "null_max_z", "vn_null_max_z"]
print(res[cols].round(4).to_string(index=False))
print("saved", fn, f"{time.time() - t0:.0f}s")
