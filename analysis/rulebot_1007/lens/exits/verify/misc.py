import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = pd.read_pickle("xl.pkl")
R0 = X[X.flip==0]
P = R0.pivot_table(index=["run","sig_id"], columns="variant", values="R")
meta = R0[R0.variant=="base"].set_index(["run","sig_id"])[["timeframe","runl","bar_close"]]
P = P.join(meta)
for tf in ["15m","30m"]:
    g = P[P.timeframe==tf]
    for rl in ["v3b","v4",None]:
        h = g if rl is None else g[g.runl==rl]
        d = h["be0.5_tp1"]-h["tp1R"]
        print("be0.5_tp1 - tp1R", tf, rl or "pooled", round(d.mean(),3), len(d))
# (b) TP share among tp1R closed rows (real side)
t = R0[(R0.variant=="tp1R")]
cl = t[t.status=="CLOSED"]
print("tp1R closed", len(cl), "TP exits", (cl.exit_reason=="TP").sum(), round((cl.exit_reason=="TP").mean(),3), "status counts", t.status.value_counts().to_dict())
g15 = t[(t.timeframe=="15m")&t.R.notna()]
w = g15.R>0
print("tp1R 15m win", round(w.mean(),3), "avgW", round(g15.R[w].mean(),3), "avgL", round(g15.R[~w].mean(),3))
# (c)/(d) open at end shares
for v in ["base","geo10","RL2_1","tp3R","tp2R","lock30"]:
    s = R0[R0.variant==v]
    print(v, "open_end real side", int(s.open_end.sum()), "of", int(s.R.notna().sum()), "| by tf:", s.groupby("timeframe").apply(lambda q: f"{q.open_end.sum()}/{q.R.notna().sum()}").to_dict())
# (e) pnl on equity per 15m signal
for v in ["base","lev10","geo10","lev20m20","lev40m40"]:
    s = R0[(R0.variant==v)&(R0.timeframe=="15m")]
    pe = np.where(s.status.isin(["CLOSED","OPEN_END"]), s.pnl/5000, 0.0)
    print("pe 15m", v, round(100*np.mean(pe),3), "% n", len(s))
# (f) pass shares
for v in ["lev30m30","lev40m40","lev50m50"]:
    s = R0[R0.variant==v]
    print(v, s.groupby("timeframe").apply(lambda q: round(q.status.isin(["CLOSED","OPEN_END"]).mean(),3)).to_dict())
# leverage mix of base
b = R0[R0.variant=="base"]
print("base leverage mix by tf:", b.groupby("timeframe").leverage.apply(lambda s: s.value_counts(normalize=True).round(3).to_dict()).to_dict())
