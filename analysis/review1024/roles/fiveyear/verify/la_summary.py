"""Summarise la_rederive_blocks.csv / la_rederive_sid.csv into the claim's numbers (per period: with / all / effect,
coin-flip twin, long share; per block effect; share of strategies improved; lag diagnostics).  python3 la_summary.py"""
import os
import sys
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
PER = {"SEL": ["Y21", "Y22", "Y23"], "CONF": ["Y24", "Y25", "Y26a"], "FWD": ["F1", "F2"], "Y26a": ["Y26a"]}
B = pd.read_csv(os.path.join(HERE, "la_rederive_blocks.csv"))
g = B.groupby(["etf", "htf", "lag", "src", "block"])[["nALL", "sALL", "nW", "sW", "sWo", "nlongW"]].sum().reset_index()
out = []
for (etf, htf, lag, src), q in g.groupby(["etf", "htf", "lag", "src"]):
    for per, bl in PER.items():
        r = q[q.block.isin(bl)].sum(numeric_only=True)
        out.append({"map": f"{etf}->{htf}", "lag": lag, "src": src, "per": per, "nW": int(r.nW), "nALL": int(r.nALL),
                    "mW%": 100 * r.sW / r.nW, "mALL%": 100 * r.sALL / r.nALL, "eff_pts": 100 * (r.sW / r.nW - r.sALL / r.nALL),
                    "mWo%": 100 * r.sWo / r.nW, "lsW": r.nlongW / r.nW})
O = pd.DataFrame(out)
pd.set_option("display.width", 250)
print(O[(O.lag == 0)].round(3).to_string(index=False))
print("\nlag diagnostics (lag -1 = previous closed bar, +1 = the still-open bar = deliberate look-ahead):")
print(O[(O.per.isin(["SEL", "CONF"])) & (O.src.isin(["V4OF4", "DIR"]))].pivot_table(
    index=["map", "src", "per"], columns="lag", values="eff_pts").round(3).to_string())
print("\nper block effect (pts), lag 0:")
g0 = g[g.lag == 0].copy()
g0["eff"] = 100 * (g0.sW / g0.nW - g0.sALL / g0.nALL)
print(g0.pivot_table(index=["etf", "htf", "src"], columns="block", values="eff")[
    ["Y21", "Y22", "Y23", "Y24", "Y25", "Y26a", "O26a", "F1", "F2"]].round(2).to_string())
S = pd.read_csv(os.path.join(HERE, "la_rederive_sid.csv"))
rows = []
for (etf, htf, src), q in S.groupby(["etf", "htf", "src"]):
    for per, bl in PER.items():
        x = q[q.block.isin(bl)].groupby("sid")[["nALL", "sALL", "nW", "sW"]].sum()
        x = x[x.nW >= 30]
        e = x.sW / x.nW - x.sALL / x.nALL
        rows.append({"map": f"{etf}->{htf}", "src": src, "per": per, "n_strat": len(x), "median_eff_pts": 100 * e.median(),
                     "share_improved": (e > 0).mean()})
print("\nper strategy (with n >= 30):")
print(pd.DataFrame(rows).round(3).to_string(index=False))
