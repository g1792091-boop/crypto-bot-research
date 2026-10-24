"""vco step 5: goal bootstrap at the live executors' real margin (~30 % of wallet) vs 40 %, payback in, entries fixed.
Run (no -I): python3 vco_goal_m30.py"""
import os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vco_goal import boot, POOLS, PAYBACK  # noqa: E402  (vco_goal main loop only runs with its own argv; guard below)
HERE = os.path.dirname(os.path.abspath(__file__))
rows = []
for v in ("B3", "B6"):
    R = pd.read_csv(os.path.join(HERE, f"vco_rewalk_{v}.csv.gz"))
    for pn, (a, b) in POOLS.items():
        m = ((R.t >= a) & (R.t < b)).to_numpy()
        t = R.t.to_numpy(np.int64)[m]
        for sc in ("orig", "c1p6"):
            x = R[sc].to_numpy()[m] + R.lev.to_numpy()[m] * PAYBACK
            for mg in (0.3, 0.4):
                g = boot(t, x, a, b, margin=mg, n_boot=20000 if pn == "oct" else 4000)
                rows.append({"v": v, "pool": pn, "scen": sc, "margin": mg, **g})
print(pd.DataFrame(rows).round(4).to_string(index=False))
