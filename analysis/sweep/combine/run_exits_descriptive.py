"""DESCRIPTIVE ONLY -- NOT the pre-registered exit stage (which applies to gate survivors, of which
there are none).  Runs sweep_lib.exits() unchanged (5 exits, B=300 common-shift null, studentised
max-stat p) on the family cells that reached fwd >= mu* but failed Holm, to show what realistic
one-position-per-coin trading of the IS near-misses looked like.  Nothing here can be carried to OOS.

usage: python3 run_exits_descriptive.py <tf> [<tf> ...]
"""
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.dirname(HERE)
os.environ["SWEEP_DATA"] = os.path.join(HERE, "data")      # exposes only is/
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as SL  # noqa: E402

CACHE = {"1h": "discover_g1h_4h_1d/out/signals_is_1h.npz", "4h": "discover_g1h_4h_1d/out/signals_is_4h.npz",
         "1d": "discover_g1h_4h_1d/out/signals_is_1d.npz"}

g = pd.read_csv(os.path.join(HERE, "out", "gate_all_is_applied.csv"))
near = g[g["in_family"] & (g["fwd"] >= g["mu_star"]) & ~g["gate_pass"]]
for tf in sys.argv[1:]:
    cells = near[near["tf"] == tf]
    if cells.empty:
        continue
    panel = SL.load_panel(tf, "is")
    last = max(df["ts"].max() for df in panel.values())
    assert last < pd.Timestamp("2024-07-01", tz="UTC"), last
    names = sorted(cells["strategy"].unique())
    t0 = time.time()
    sigs = SL.compute_signals(panel, tf, names)
    cache = SL.load_signals(os.path.join(SWEEP, CACHE[tf]))
    for n in names:
        for c in panel:
            same = np.array_equal(sigs[n][c], cache[n][c])
            if not same:
                print(f"CACHE MISMATCH {tf} {n} {c}: recomputed {int(np.abs(sigs[n][c]).sum())} vs cache "
                      f"{int(np.abs(cache[n][c]).sum())}", flush=True)
    print(f"{tf}: recomputed signals for {names} in {time.time() - t0:.1f}s; last IS bar {last}", flush=True)
    rows = []
    for _, r in cells.iterrows():
        t1 = time.time()
        ex = SL.exits(tf, r["strategy"], int(r["H"]), panel, sigs, split="is", B=SL.B_EXIT)
        ex["gate_fwd"], ex["gate_mu_star"], ex["gate_z"], ex["gate_p_holm"], ex["gate_p_vn"] = (
            r["fwd"], r["mu_star"], r["z"], r["p_holm"], r["p_vn"])
        ex = ex.rename(columns={"exit_pass": "exit_criteria_met_DESCRIPTIVE"})
        ex["carry_eligible"] = False   # failed the gate (PREREG 5: exit stage only for gate survivors)
        rows.append(ex)
        print(f"  {tf} {r['strategy']} H{int(r['H'])}: {time.time() - t1:.0f}s", flush=True)
        print(ex[["exit", "trades", "pf", "exp_net", "symbols_pos", "months_pos", "months", "z_exit", "p_max",
                  "exit_criteria_met_DESCRIPTIVE"]].to_string(), flush=True)
    pd.concat(rows, ignore_index=True).to_csv(os.path.join(HERE, "out", f"exits_descriptive_nearmiss_{tf}.csv"),
                                              index=False)
