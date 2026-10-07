#!/usr/bin/env python3
"""C6/C7: per-coin real execution costs from fill_costs (entry book walk) and d3_stop_slips (real stop-market fill).
python3 -I v6_exec.py <export_dir> <v2_replay_rows.csv>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vboot  # noqa
import numpy as np, pandas as pd
ex, rep = sys.argv[1:3]
pd.set_option("display.width", 250)
F = []
for run in ("run-20261005T014624Z", "run-20261005T183457Z", "current"):
    f = pd.read_csv(os.path.join(ex, run, "fill_costs.csv")); f["run"] = run[:7] if run != "current" else "v4"; F.append(f)
F = pd.concat(F)
print(F.groupby(["event", "status"]).size())
E = F[(F["event"] == "entry") & (F["status"] == "ok")].copy()
E["walk_bp"] = E["slip_best"] * 1e4
E["nb"] = pd.cut(E["notional"], [0, 30000, 60000, 1e9], labels=["<30k", "30-60k", ">60k"])
print(E.groupby("symbol").agg(n=("walk_bp", "size"), mean=("walk_bp", "mean"), med=("walk_bp", "median"),
                              gt2=("walk_bp", lambda x: (x > 2).mean())).round(3))
print(E.groupby(["symbol", "nb"], observed=True)["walk_bp"].agg(["size", "mean", "median"]).round(3).unstack())
print(E.groupby(["symbol", "run"])["walk_bp"].agg(["size", "mean"]).round(3).unstack())
S = pd.read_csv(os.path.join(ex, "current", "d3_stop_slips.csv"))
print(S.groupby(["exit_reason", "status"]).size())
ok = S[S["status"] == "ok"]
print(ok.groupby(["exit_reason", "symbol"]).agg(n=("real_bps", "size"), real=("real_bps", "mean"), real_med=("real_bps", "median"),
       paper=("paper_bps", "mean"), diff_usd=("diff_usd", "sum")).round(3))
print("all-status diff_usd by symbol", S.groupby("symbol")["diff_usd"].sum().round(0).to_dict(), "total", round(S["diff_usd"].sum()))
print("cap rows real_bps", S[S.status == "cap"]["real_bps"].describe().round(3).to_dict())
# per-coin real taker cost and cost R on the replay rows
walk = E.groupby("symbol")["walk_bp"].mean()
sl = ok[ok["exit_reason"] == "SL"].groupby("symbol")["real_bps"].mean()
lk = ok[ok["exit_reason"] == "LOCK"].groupby("symbol")["real_bps"].mean()
R = pd.read_csv(rep)
R = R[R["grp"].isin(["core36", "ds200"]) & R["timeframe"].isin(["15m", "30m"])].copy()
# real: fees 10 + entry walk + exit slip (SL real slip for SL exits, LOCK real slip for LOCK exits, open: SL)
xs = np.where(R["exit_reason"] == "LOCK", R["symbol"].map(lk), R["symbol"].map(sl))
R["real_bp"] = 10 + R["symbol"].map(walk) + xs
R["real_R"] = R["real_bp"] / (R["stop_frac_fill"] * 1e4)
R["real_R_sl_only"] = (10 + R["symbol"].map(walk) + R["symbol"].map(sl)) / (R["stop_frac_fill"] * 1e4)
g = R.groupby(["timeframe", "symbol"]).agg(n=("real_R", "size"), stop_med=("stop_frac_fill", lambda x: x.median() * 100),
       paper_R=("cost_R", "mean"), real_bp=("real_bp", "mean"), real_R=("real_R", "mean"), real_R_sl=("real_R_sl_only", "mean"),
       gross=("gross_R", "mean"))
print(g.round(3))
print("RT bp by coin (10+walk+SL slip):", (10 + walk + sl).round(2).to_dict())
print("RT bp by coin (10+walk+LOCK slip):", (10 + walk + lk).round(2).to_dict())
