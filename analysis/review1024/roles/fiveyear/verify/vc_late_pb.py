"""2026 (LATE 2026-01-01 .. 10-23 00:00 UTC) with the TetherMax payback: the study's stacked filter (1h 4/4 + 4h held)
per signal vs one position at a time, at the study's cost and at the WOO X Pro measured cost (8.58 bp a side) + payback.
python3 vc_late_pb.py -> vc_late_pb.csv"""
import os, sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
import numpy as np
import pandas as pd
from vc_analyze import bot, IND
from common import ms, PAYBACK, DAY
PB = 35 * PAYBACK
lo, hi = ms("2026-01-01"), ms("2026-10-23")
rows = []
for tf in ("15m", "30m"):
    S = pd.read_pickle(os.path.join(IND, f"{tf}.pkl"))
    S = S[(S.t >= lo) & (S.t < hi)]
    sd = S.side.to_numpy()
    S["f1"] = S.v4_1h.to_numpy() == sd
    S["f2"] = S.f1.to_numpy() & (S.dir_4h.to_numpy() == sd)
    for v, dl in (("base", 0), ("woo", 0), ("x2", 0), ("d1", 1)):
        Q = S[(S[f"{v}_why"] != 3) & (S[f"{v}_opp_why"] != 3) & (S[f"{v}_k"] >= 0)]
        for f in ("all", "f1", "f2"):
            F = Q if f == "all" else Q[Q[f]]
            bm, bn = [], []
            for seed in range(1, 11):
                T = F[bot(F, v, dl, seed)]
                bm.append(T[f"{v}_roe"].mean()); bn.append(len(T))
            rows.append({"tf": tf, "var": v, "filter": f, "n_sig": len(F), "pool": F[f"{v}_roe"].mean(),
                         "pool_pb": F[f"{v}_roe"].mean() + PB, "bot": np.mean(bm), "bot_pb": np.mean(bm) + PB,
                         "bot_pb_min": np.min(bm) + PB, "bot_pb_max": np.max(bm) + PB,
                         "bot_per_day": np.mean(bn) / ((hi - lo) / DAY)})
R = pd.DataFrame(rows)
R.to_csv("vc_late_pb.csv", index=False, float_format="%.5g")
for c in ("pool", "pool_pb", "bot", "bot_pb", "bot_pb_min", "bot_pb_max"):
    R[c] = (100 * R[c]).round(2)
print(R.round(2).to_string())
