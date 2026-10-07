import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = pd.read_pickle("xl.pkl")
X = X[X.flip==0]
X["fp"] = X.run + "|" + X.timeframe + "|" + X.symbol + "|" + X.bar_close.astype(str) + "|" + X.side.astype(str)
b = X[X.variant=="base"]
for tf in ["15m","30m","1h","4h"]:
    g = b[b.timeframe==tf]
    print(tf, "rows", len(g), "unique signals", g.fp.nunique(), "dup share", round(1-g.fp.nunique()/len(g),3),
          "| mean R all", round(g.R.mean(),3), "dedup (mean per fp)", round(g.groupby("fp").R.mean().mean(),3))
P = X.pivot_table(index=["run","sig_id"], columns="variant", values="R").join(b.set_index(["run","sig_id"])[["fp","timeframe","runl"]])
for v in ["geo10","tp1.5R","RL1_0.5_bar"]:
    for tf in ["15m","30m","1h"]:
        g = P[P.timeframe==tf]
        d = (g[v]-g.base)
        dd = d.groupby(g.fp).mean()
        rl = g.groupby("fp").runl.first()
        print(v, tf, "all", round(d.mean(),3), "dedup", round(dd.mean(),3), "| dedup v3b", round(dd[rl=="v3b"].mean(),3), "v4", round(dd[rl=="v4"].mean(),3))
# biggest duplicate groups
c = b.groupby("fp").strategy.apply(lambda s: "+".join(sorted(s)))
print(c[c.str.count(r"\+")>=2].value_counts().head(10).to_string())
