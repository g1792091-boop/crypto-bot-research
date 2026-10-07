import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from vlib import *
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 50)
R = load_replay()
print("status by tf\n", R.groupby("timeframe").status.value_counts().unstack(fill_value=0))
T = R[R.status == "TRADED"].copy()
d = (T.entry_price - T.stop_initial).abs()
T["costR"] = (T.fees + T.funding) / (T.qty * d)
# check R definition
chk = T.pnl / (T.qty * d)
print("R def check max abs diff", float((chk - T.R).abs().max()))
# slippage: replay entry vs ref price (adverse in bps)
T["slip_entry_bps"] = 1e4 * T.side * (T.entry_price - T.ref_price) / T.ref_price
print("entry slip bps by tf (median, mean):\n", T.groupby("timeframe").slip_entry_bps.agg(["median", "mean"]))
T["slipR_est"] = 2 * 0.0002 * T.entry_price / d
T["grossR"] = T.R + T.costR + T.slipR_est
T["net_notional_pct"] = 100 * T.pnl / (T.qty * T.entry_price)
rows = []
for tf, g in T.groupby("timeframe"):
    for lab, cl in (("1h", "cl1h"), ("4h", "cl4h")):
        c = crse(g.R, g[cl])
        rows.append(dict(tf=tf, cl=lab, n=c["n"], G=c["G"], mean=c["mean"], lo=c["lo"], hi=c["hi"], p_lt=c["p_lt"], sd=c["sd"], deff=c["deff"],
                         gross=g.grossR.mean(), feefund=g.costR.mean(), slip=g.slipR_est.mean(), net_notional=g.net_notional_pct.mean(),
                         roe_per_lev=100 * g.roe_per_lev.mean(), med_stop_pct=100 * g.stop_frac.median()))
    # daily clusters
    dd = (g.bar_close // (24 * H))
    c = crse(g.R, dd); rows.append(dict(tf=tf, cl="day", n=c["n"], G=c["G"], mean=c["mean"], lo=c["lo"], hi=c["hi"], p_lt=c["p_lt"]))
print(pd.DataFrame(rows).round(4).to_string())
# unique signals per tf
U = T.drop_duplicates(["timeframe", "bar_close", "symbol", "side"])
for tf, g in U.groupby("timeframe"):
    c = crse(g.R, g.cl1h); print("unique", tf, c["n"], round(c["mean"], 4), round(c["lo"], 3), round(c["hi"], 3))
# include unresolved marked
Um = R[R.status == "UNRESOLVED"]
for tf in ["15m", "30m", "1h", "4h"]:
    a = np.r_[T[T.timeframe == tf].R.values, Um[Um.timeframe == tf].mark_R.dropna().values]
    print("incl marked", tf, len(a), round(a.mean(), 4), "unresolved n", (Um.timeframe == tf).sum(), "mark_R mean", round(Um[Um.timeframe == tf].mark_R.mean(), 3))
