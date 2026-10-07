import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = pd.read_pickle("xl.pkl")
X = X[(X.flip==0) & X.kind.isin(["strategy","ds200"])]
LEV = {"lev10","lev20m20","lev30m30","lev40m40","lev50m50"}
X = X[~X.variant.isin(LEV)]
P = X.pivot_table(index=["run","sig_id"], columns="variant", values="R")
meta = X[X.variant=="base"].set_index(["run","sig_id"])[["runl","kind","strategy","timeframe","bar_close","fp" if "fp" in X.columns else "symbol"]]
P = P.join(meta)
exits = [c for c in P.columns if c not in meta.columns]
rows = []
for (s, tf), g in P.groupby(["strategy","timeframe"]):
    if len(g) < 25: continue
    r1 = cboot(g.base, g.bar_close//3600_000, seed=2); r6 = cboot(g.base, g.bar_close//(6*3600_000), seed=2)
    m = g[exits].mean()
    rows.append(dict(strategy=s, tf=tf, kind=g.kind.iloc[0], n=len(g), house=g.base.mean(), lo=r1["lo"], hi=r1["hi"], p=r1["p"], G=r1["G"],
                     lo6=r6["lo"], hi6=r6["hi"], p6=r6["p"],
                     v3b=g[g.runl=="v3b"].base.mean(), n3b=(g.runl=="v3b").sum(), v4=g[g.runl=="v4"].base.mean(), n4=(g.runl=="v4").sum(),
                     geo20_bar=m["geo20_bar"], RL1_05_bar=m["RL1_0.5_bar"], tp1R=m["tp1R"], best=m.idxmax(), bestR=m.max(),
                     spread=m.max()-m.min(), npos=int((m>0).sum()), nexits=len(m)))
C = pd.DataFrame(rows)
C["q"] = bh(C.p.to_numpy()); C["q6"] = bh(C.p6.to_numpy())
pd.set_option("display.width", 300); pd.set_option("display.max_rows", 200)
C = C.sort_values(["tf","house"], ascending=[True, False])
print(len(C), "cells; house>0:", (C.house>0).sum(), "| any exit>0:", (C.npos>0).sum(), "| all exits>0:", (C.npos==C.nexits).sum(), "| all exits<0:", (C.npos==0).sum())
print("exit spread median", C.spread.median(), "min", C.spread.min(), "max", C.spread.max())
print("min q", C.q.min(), "BH<0.05:", C[C.q<0.05][["strategy","tf","house","q"]].to_dict("records"))
print("min q6", C.q6.min(), C[C.q6<0.1][["strategy","tf","house","q6"]].to_dict("records"))
print(C.round(3).to_string(index=False))
C.to_csv("x13_cells.csv", index=False)
