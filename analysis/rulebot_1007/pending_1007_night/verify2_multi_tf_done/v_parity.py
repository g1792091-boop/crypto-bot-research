import sys, os
sys.path[:0]=['/root/.local/lib/python3.11/site-packages']
import numpy as np, pandas as pd
V, OUTC = sys.argv[1:3]
COINS = ("BTCUSD","ETHUSD","SOLUSD","DOGEUSD","LTCUSD","BCHUSD"); TFS=("15m","30m","1h","4h")
d = pd.read_csv(os.path.join(V,"outc.csv"))
u = d.drop_duplicates(["tf","coin","e","side"])
res=[]
for (t,c),g in u.groupby(["tf","coin"]):
    z=np.load(os.path.join(OUTC,f"out_{TFS[t]}_{COINS[c]}.npz"))
    k=pd.DataFrame({"e":z["e"],"side":z["side"],"R2":z["R"],"lev2":z["lev"],"feas2":z["feasible"],"g2":z["gross"]})
    m=g.merge(k,on=["e","side"],how="left")
    res.append(m.assign(tfn=t))
m=pd.concat(res)
print("unmatched", m.R2.isna().sum(), "of", len(m))
m=m.dropna(subset=["R2"])
m["dR"]=(m.R-m.R2).abs()
print("lev agree", ((m.lev==m.lev2)).mean())
for t,g in m.groupby("tfn"):
    print(TFS[t], len(g), "meanR mine %.4f theirs %.4f | |dR|>1e-3 share %.4f | gross %.4f vs %.4f | feas %.3f vs %.3f"%(g.R.mean(),g.R2.mean(),(g.dR>1e-3).mean(),g.gross.mean(),g.g2.mean(),(g.lev>0).mean(),g.feas2.mean()))
