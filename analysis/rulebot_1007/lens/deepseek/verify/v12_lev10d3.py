import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from vlib import *
E = EXP + "/current"
start = int(pd.read_csv(E + "/runs.csv").started_ts.min()); end = int(pd.read_csv(E + "/live_bars.csv", usecols=["ts"]).ts.max()); mid = start + (end - start) / 2
D = pd.read_csv(E + "/d3_shadows.csv"); D["bc"] = D.key.str.split("|").str[-1].astype("int64")
acc = pd.read_csv(E + "/accounts.csv"); ds = set(acc[acc.kind == "ds200"].account_id)
D = D[D.account_id.isin(ds) & (D.kind == "lev10")]
kst = lambda ms: (pd.to_datetime(ms, unit="ms") + pd.Timedelta(hours=9))
print("d3 lev10 ds200 signal bar_close KST range", kst(D.bc.min()), kst(D.bc.max()), "share before mid", round((D.bc < mid).mean(), 3))
L = pd.read_csv(sys.argv[1] + "/my_lev.csv")
L["Rv"] = np.where(L.status == "TRADED", L.R, np.where(L.status == "UNRESOLVED", L.mark_R, np.nan))
L["aid"] = L.strategy + "@" + L.timeframe
W = L.pivot_table(index=["aid", "symbol", "bar_close", "timeframe"], columns="L", values="Rv").reset_index()
St = L.pivot_table(index=["aid", "symbol", "bar_close"], columns="L", values="status", aggfunc="first").add_prefix("st").reset_index()
W = W.merge(St, on=["aid", "symbol", "bar_close"])
M = D.merge(W, left_on=["account_id", "symbol", "bc"], right_on=["aid", "symbol", "bar_close"], how="left")
for tf, g in M.groupby("timeframe_x"):
    a = g[g[10].notna() & g[30].notna()]
    r = a[(a.st10 == "TRADED") & (a.st30 == "TRADED")]
    rr = a[a.resolved == 1]
    print(tf, "d3 rows", len(g), "my replay 10x-30x (incl marked) %.3f n%d | both resolved in my replay %.3f n%d | d3-resolved subset %.3f n%d" % ((a[10] - a[30]).mean(), len(a), (r[10] - r[30]).mean(), len(r), (rr[10] - rr[30]).mean(), len(rr)))
# account-entered pipeline signals at 15m, resolved both
P = load_replay()
ent = P[(P.acct_status == "ENTERED")][["strategy", "timeframe", "symbol", "bar_close"]]
ent["aid"] = ent.strategy + "@" + ent.timeframe
M2 = ent.merge(W, on=["aid", "symbol", "bar_close"])
for tf, g in M2.groupby("timeframe_x" if "timeframe_x" in M2 else "timeframe"):
    r = g[(g.st10 == "TRADED") & (g.st30 == "TRADED")]
    h1 = r[r.bar_close < mid]; h2 = r[r.bar_close >= mid]
    print("acct-entered", tf, "resolved-both 10x-30x %.3f n%d | H1 %.3f n%d | H2 %.3f n%d" % ((r[10] - r[30]).mean(), len(r), (h1[10] - h1[30]).mean(), len(h1), (h2[10] - h2[30]).mean(), len(h2)))
