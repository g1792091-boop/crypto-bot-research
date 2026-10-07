import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = pd.read_pickle("xl.pkl")
X = X[X.flip==0]
anyopen = X.groupby(["run","sig_id"]).open_end.max().rename("anyopen")
P = X.pivot_table(index=["run","sig_id"], columns="variant", values="R").join(anyopen).join(X[X.variant=="base"].set_index(["run","sig_id"])[["timeframe","runl"]])
for v, tf in [("RL1.5_1","15m"),("geo10","1h"),("RL2_1","1h"),("geo10","15m"),("tp1.5R","15m")]:
    for rl in ["v3b","v4"]:
        g = P[(P.timeframe==tf)&(P.runl==rl)]
        r = g[g.anyopen==0]
        print(v, tf, rl, "all", round((g[v]-g.base).mean(),3), f"(n {len(g)})", "RES", round((r[v]-r.base).mean(),3), f"(n {len(r)})")
