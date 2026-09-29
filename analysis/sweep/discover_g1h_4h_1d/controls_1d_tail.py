"""DESCRIPTIVE extra (not a PREREG rule; changes no decision).
The pre-registered-style real-IS control (run_controls.py, seed 1, 200 reps) showed 3/200 zero-edge
burst4 n=150 replicates passing the full gate INCLUDING A1 at 1d H64.  This re-runs sweep_lib.controls()
on the real IS panel with more replicates and an independent seed (2) for the long-horizon cells of the
higher timeframes, to estimate that false-pass rate with less noise.
usage: python3 controls_1d_tail.py --tf 1d --Hs 16,64 --reps 1000"""
import argparse
import os
import sys
import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_lib as L  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--tf", default="1d")
ap.add_argument("--Hs", default="16,64")
ap.add_argument("--reps", type=int, default=1000)
ap.add_argument("--kinds", default="iid,burst4")
ap.add_argument("--n_targets", default="150,500")
ap.add_argument("--seed", type=int, default=2)
a = ap.parse_args()
t0 = time.time()
panel = L.load_panel(a.tf, "is")
res = L.controls(a.tf, panel, split="is", Hs=[int(h) for h in a.Hs.split(",")], reps=a.reps,
                 n_targets=[int(x) for x in a.n_targets.split(",")], kinds=a.kinds.split(","), seed=a.seed)
res["data"] = "is"
res["seed"] = a.seed
res["sec"] = time.time() - t0
res["fp_raw"] = (res["null_rate_gate"] * res["reps"]).round().astype(int)
res["fp_A1"] = (res["null_rate_gate_and_vn"] * res["reps"]).round().astype(int)
fn = os.path.join(HERE, "out", f"controls_extra_is_{a.tf}_seed{a.seed}.csv")
res.to_csv(fn, index=False)
pd.set_option("display.width", 250)
cols = ["tf", "H", "kind", "n_target", "reps", "n_mean", "null_z_sd", "vn_null_z_sd", "null_max_z", "vn_null_max_z",
        "null_rate_holm1", "vn_null_rate_holm1", "fp_raw", "fp_A1", "null_rate_gate", "null_rate_gate_and_vn"]
print(res[cols].round(4).to_string(index=False))
print("saved", fn, f"{time.time() - t0:.0f}s")
