"""Base rates on CONFIRM for the family (rebuilt cells.pkl): share of eligible cells (SELECT n >= 60 in >= 12 months)
positive on CONFIRM raw / with payback, per condition; same for SELECT-positive cells; with matching (etf, htf) mix of
the 20 with-picks.   python3 lm_base.py"""
import os
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import PAYBACK
PB = 35 * PAYBACK
D = pd.read_pickle("/dev/shm/claude_verify_lm/cells.pkl")
for cn in ("W", "A", "N"):
    q = D[(D[f"SEL_n{cn}"] >= 60) & (D[f"SEL_M{cn}"] >= 12)]
    if cn == "N":
        q = q[q.kind != "l"]
    q = q[np.isfinite(q[f"CONF_m{cn}"]) & (q[f"CONF_n{cn}"] > 0)]
    p = q[q[f"SEL_m{cn}"] > 0]
    p4 = q[(q[f"SEL_m{cn}"] > 0) & (q.etf == "4h")]
    print(cn, "eligible", len(q), "CONF>0 %.3f" % (q[f"CONF_m{cn}"] > 0).mean(), "CONF+pb>0 %.3f" % (q[f"CONF_m{cn}"] + PB > 0).mean(),
          "| SEL>0:", len(p), "CONF>0 %.3f" % (p[f"CONF_m{cn}"] > 0).mean(), "CONF+pb>0 %.3f" % (p[f"CONF_m{cn}"] + PB > 0).mean(),
          "| SEL>0 & 4h:", len(p4), "CONF+pb>0 %.3f" % (p4[f"CONF_m{cn}"] + PB > 0).mean())
