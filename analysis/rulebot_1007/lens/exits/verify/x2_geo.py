import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = load_xl(sys.argv[1], variants=["base","lev10","geo10","lev20m20","geo20","lock30"])
X = X[X.flip==0]
B = X[X.variant=="base"].copy()
B["sf"] = B.dist/B.b_entry
for tf in ["15m","30m","1h","4h"]:
    sf = B[B.timeframe==tf].sf.median()
    rows = []
    for L in (10,20,30,40,50):
        trig = (0.12/L + 0.0014)/sf; lock = (0.10/L+0.0014)/sf; g0 = 0.02/L/sf; g1 = 0.07/L/sf
        rows.append(f"{L}x trig {trig:.2f}R lock {lock:.2f}R trail {g0:.2f}-{g1:.2f}R cost/trig {0.0014/(0.12/L+0.0014):.2f}")
    print(tf, f"median stop {sf*100:.3f}%", " | ".join(rows))
P = X.pivot_table(index=["run","sig_id"], columns="variant", values="R")
for a,b in [("lev10","geo10"),("lev20m20","geo20")]:
    d = (P[a]-P[b]).abs()
    print(a, "vs", b, "n", d.notna().sum(), "max|dR|", d.max(), "share>1e-6", (d>1e-6).mean())
