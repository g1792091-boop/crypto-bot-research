#!/usr/bin/env python3
"""Where the ROE ladder (first lock 10% net ROE armed at 12%) sits in R units, by timeframe (median live stop
distance from trades_enriched) and leverage; trades per account-day by timeframe.
    python3 -I ladder_geometry.py <trades_enriched.csv> <out_dir>"""
import sys
sys.dont_write_bytecode = True
import site
sys.path.append(site.getusersitepackages())
import os
import numpy as np
import pandas as pd
T = pd.read_csv(sys.argv[1]); out = sys.argv[2]
T = T[T["kind"].isin(["strategy", "ds200"]) & (T["exits"] == "house")]
rt = 2 * (0.0005 + 0.0002)
rows = []
for tf in ["15m", "30m", "1h", "4h"]:
    sf = T[T["tf"] == tf]["stop_frac"].median()
    for L in (20, 30, 40, 50):
        arm = (0.12 / L + rt) / sf
        lock = (0.10 / L + rt) / sf
        rows.append({"tf": tf, "median_stop_pct": 100 * sf, "leverage": L, "first_lock_arms_at_R": arm,
                     "first_lock_at_R": lock, "round_trip_cost_R": rt / sf,
                     "notional_x_equity_at_margin_eq_lev_pct": L * L / 100,
                     "round_trip_cost_pct_equity": 100 * rt * L * L / 100,
                     "max_loss_at_stop_pct_equity": 100 * (sf + rt) * L * L / 100})
G = pd.DataFrame(rows)
G.to_csv(os.path.join(out, "ladder_geometry.csv"), index=False)
# trades per account-day (real accounts, accounts with >= 1 trade), by run x kind x tf
DAYS = {"run-20261005T014624Z": 2.61, "run-20261005T183457Z": 0.699, "current": 1.5}
tp = T.groupby(["run", "kind", "tf"]).agg(trades=("R", "size"), accounts=("account_id", "nunique")).reset_index()
tp["days"] = tp["run"].map(DAYS)
tp["trades_per_account_day"] = tp["trades"] / tp["accounts"] / tp["days"]
tp.to_csv(os.path.join(out, "trades_per_account_day.csv"), index=False)
pd.set_option("display.width", 220)
print(G.round(3).to_string()); print(tp.round(2).to_string())
