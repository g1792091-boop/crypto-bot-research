#!/usr/bin/env python3
"""C8: nightly d3 limit shadow (0.25 ATR better, trade-through within one bar, maker entry) joined to the market
replay of the same signal (pipeline replay_signals, v4). Units: market trade's R (ret per notional / stop frac).
python3 -I v7_limit.py <export_dir> <v2_replay_rows.csv>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vboot  # noqa
import numpy as np, pandas as pd
from v2_replay_gross import cboot
ex, rep = sys.argv[1:3]
D = pd.read_csv(os.path.join(ex, "current", "d3_shadows.csv"))
L = D[D["kind"] == "limit"].copy()
L["bar_close"] = L["key"].str.split("|").str[-1].astype(np.int64)
R = pd.read_csv(rep)
R = R[(R["run"] == "current") & (R["status"] == "TRADED")]
R = R[R["grp"].isin(["core36", "ds200"])]
M = L.merge(R[["account_id", "symbol", "bar_close", "grp", "R", "roe", "leverage", "stop_frac_fill", "cl4h", "cl1h", "dupkey"]],
            on=["account_id", "symbol", "bar_close"], how="inner", suffixes=("_lim", "_mkt"))
print("limit rows", len(L), "joined to resolved market replay", len(M))
M = M[(M["filled"] == 0) | ((M["resolved"] == 1) & M["roe_lim"].notna())]
M["R_lim"] = np.where(M["filled"] == 1, M["roe_lim"] / M["leverage"] / M["stop_frac_fill"], 0.0)
M["d"] = M["R_lim"] - M["R"]
rows = []
for (g, tf), x in M.groupby(["grp", "timeframe"]):
    f = x[x.filled == 1]; u = x[x.filled == 0]
    lo, hi, k = cboot(x["d"], x["cl4h"]); lo1, hi1, k1 = cboot(x["d"], x["cl1h"])
    rows.append(dict(grp=g, tf=tf, n=len(x), fill=x["filled"].mean(), missed_mkt_R=u["R"].mean(),
                     missed_win=(u["R"] > 0).mean(), filled_improve=(f["R_lim"] - f["R"]).mean(),
                     net_vs_mkt=x["d"].mean(), ci1h=f"[{lo1:+.3f},{hi1:+.3f}]", ci4h=f"[{lo:+.3f},{hi:+.3f}]",
                     per_signal_limit=x["R_lim"].mean(), per_signal_mkt=x["R"].mean()))
x = M[M.timeframe.isin(["15m", "30m"])]
lo, hi, k = cboot(x["d"], x["cl4h"])
rows.append(dict(grp="pooled", tf="15m+30m", n=len(x), fill=x.filled.mean(), net_vs_mkt=x["d"].mean(), ci4h=f"[{lo:+.3f},{hi:+.3f}]"))
pd.set_option("display.width", 250)
print(pd.DataFrame(rows).round(3).to_string(index=False))
