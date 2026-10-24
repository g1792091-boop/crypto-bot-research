"""Open-at-data-end trades dropped from the last 19 days (L1, L2, family A): how many, and the mean if they are kept
marked at the last close; funding check of the 2022 DOGE hand-check trade; five-year positive cells."""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import oscore as O
O.CACHE = "/dev/shm/claude_verify_la"
D = O.load_all()
for lab, c in (("L1", ("30m", "1h", "OBV30", "SRSI_KD", "w35")), ("L2", ("1h", "4h", "OBV30", "SRSI_KD", "w35")),
               ("best19", ("1h", "4h", "OBV30", "SRSI_X", "a2"))):
    R = O.rows(D, *c, "FWD")
    K = O.rows(D, *c, "FWD", drop_open=False)
    op = K["w"] == 3
    print(lab, "dropped", len(K["roe"]) - len(R["roe"]), "kept n", len(R["roe"]), "mean", round(R["roe"].mean(), 5),
          "| with open marked at last close n", len(K["roe"]), "mean", round(K["roe"].mean(), 5),
          "open own-side mean", round(K["roe"][op].mean(), 4) if op.any() else None)
S = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
z = np.load(f"{S}/fg1m/1m/DOGEUSDT.npz")
ts, f = z["ts"], z["fund"]
m = (ts >= O.ms("2022-06-01 05:00")) & (ts < O.ms("2022-06-01 09:46"))
print("DOGE funding between entry and exit:", [(str(pd.Timestamp(t, unit='ms')), x) for t, x in zip(ts[m], f[m]) if x != 0])
A = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(HERE)), "all_cells.csv.gz"))
for per in ("FIVE", "SEL", "CONF"):
    g = A[A.period == per]
    print(per, "cells", len(g), "positive", int((g.mean_roe > 0).sum()), "positive with payback", int((g.mean_roe_pb > 0).sum()))
