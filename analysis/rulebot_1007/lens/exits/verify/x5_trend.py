import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
ex = sys.argv[1]
B = pd.concat([pd.read_csv(os.path.join(ex, d, "live_bars.csv")) for d in ("run-20261005T183457Z","current")]).drop_duplicates(["ts","symbol"])
t0 = pd.Timestamp("2026-10-05 00:00", tz="UTC").value//10**6
B["blk"] = (B.ts - t0)//(6*3600_000)
B["q"] = (B.ts - t0)//(15*60_000)
C = B.sort_values("ts").groupby(["symbol","q"]).agg(close=("close","last"), blk=("blk","first")).reset_index()
er = []
for (s,b), g in C.groupby(["symbol","blk"]):
    c = g.close.to_numpy()
    if len(c) < 4: continue
    er.append(dict(symbol=s, blk=b, er=abs(c[-1]-c[0])/np.abs(np.diff(c)).sum(), ret=c[-1]/c[0]-1))
E = pd.DataFrame(er).groupby("blk").agg(er=("er","mean"), absret=("ret", lambda r: np.abs(r).mean()))
X = pd.read_pickle("xl.pkl")
X = X[(X.flip==0)&X.timeframe.isin(["15m","30m"])&X.variant.isin(["base","geo10"])]
P = X.pivot_table(index=["run","sig_id"], columns="variant", values="R").join(X[X.variant=="base"].set_index(["run","sig_id"])[["bar_close"]])
P["blk"] = (P.bar_close - t0)//(6*3600_000)
D = (P.geo10-P.base).groupby(P.blk).mean().rename("d")
J = E.join(D, how="inner")
print(J.round(3).to_string())
for k in [9, 10]:
    j = J.iloc[:k]
    print(k, "blocks corr(d, ER)", round(np.corrcoef(j.d, j.er)[0,1],3), "corr(d, |ret|)", round(np.corrcoef(j.d, j.absret)[0,1],3))
