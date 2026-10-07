import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = pd.read_pickle("xl.pkl")
X = X[X.variant.isin(["base","geo10","RL1.5_1","RL2_1","RL1_0.5"])]
P = X.pivot_table(index=["run","sig_id","flip"], columns="variant", values="R")
meta = X[X.variant=="base"].set_index(["run","sig_id","flip"])[["timeframe","bar_close","kind"]]
P = P.join(meta).reset_index()
t0 = pd.Timestamp("2026-10-05 00:00", tz="UTC").value//10**6
P["blk"] = (P.bar_close - t0)//(6*3600_000)
for fl in (0,1):
    g = P[(P.flip==fl) & P.timeframe.isin(["15m","30m"])]
    s = g.assign(d=g.geo10-g.base).groupby("blk").d.agg(["mean","size"])
    print("flip", fl, "geo10-base by 6h block:", " ".join(f"{b}:{m:+.2f}(n{n})" for b,(m,n) in s.iterrows()))
    x = s["mean"].to_numpy(); print("   lag1 corr", np.corrcoef(x[:-1], x[1:])[0,1], "blocks", len(x))
    for v in ["RL2_1","RL1_0.5","RL1.5_1"]:
        s2 = g.assign(d=g[v]-g.base).groupby("blk").d.mean().to_numpy()
        print("  ", v, "lag1", round(np.corrcoef(s2[:-1], s2[1:])[0,1],3))
    if fl == 0: s_real = s["mean"]
    else: s_flip = s["mean"]
print("corr real vs flip block series:", np.corrcoef(s_real, s_flip)[0,1])
# flip vs real pooled at 15m
for tf in ["15m","30m"]:
    for v in ["RL1.5_1","geo10"]:
        r = P[(P.flip==0)&(P.timeframe==tf)]; f = P[(P.flip==1)&(P.timeframe==tf)]
        print(tf, v, "real", round((r[v]-r.base).mean(),3), "flip", round((f[v]-f.base).mean(),3))
# per-signal: is the real-side and flip-side variant gain correlated? (paired same signal)
r = P[P.flip==0][["run","sig_id","geo10","base"]]; f = P[P.flip==1][["run","sig_id","geo10","base"]]
j = r.merge(f, on=["run","sig_id"], suffixes=("_r","_f"))
print("signal-level corr of geo10 gain real vs flip:", np.corrcoef(j.geo10_r-j.base_r, j.geo10_f-j.base_f)[0,1])
