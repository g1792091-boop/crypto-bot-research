import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
OUT=os.path.dirname(os.path.abspath(__file__))
T=[]
for lab in RUNS:
    t=load(lab,"trades"); a=load(lab,"accounts")
    t=t.merge(a[["account_id","kind"]],on="account_id"); t["run"]=lab
    t["R"]=t.pnl/(t.qty*(t.entry_price-t.stop_initial).abs())
    T.append(t)
T=pd.concat(T); T.to_csv(f"{OUT}/trades_R.csv",index=False)
rng=np.random.default_rng(7)
def blockci(g,nb=4000):
    g=g.copy(); g["blk"]=g.entry_time//(4*3600*1000)
    bl=g.blk.unique(); d={b:g[g.blk==b].R.to_numpy() for b in bl}
    ms=[np.concatenate([d[b] for b in rng.choice(bl,len(bl))]).mean() for _ in range(nb)]
    return len(bl),np.percentile(ms,[2.5,97.5])
print("== kind x tf mean R all runs / v3b+v4")
for k in ["strategy","ds200","random"]:
    for tf in ["5m","15m","30m","1h","4h"]:
        g=T[(T.kind==k)&(T.timeframe==tf)]
        if len(g)==0: continue
        h=g[g.run!="v3a"]
        print(k,tf,"all n",len(g),round(g.R.mean(),3),"| v3b+v4 n",len(h),round(h.R.mean(),3) if len(h) else None, "| lev mix", g.leverage.value_counts().to_dict())
r=T[(T.kind=="random")&(T.timeframe=="15m")]
nb,ci=blockci(r); print("RANDOM 15m n",len(r),"mean",r.R.mean().round(3),"blocks",nb,"ci",ci.round(3))
for lab,g in r.groupby("run"): print(" ",lab,len(g),g.R.mean().round(3), "short",g[g.side<0].R.mean().round(3),(g.side<0).sum(),"long",g[g.side>0].R.mean().round(3),(g.side>0).sum())
s=r.R.sort_values(ascending=False); print("top2 share of summed R", (s.iloc[:2].sum()/s.sum()).round(3), "sum",s.sum().round(3))
for tf in ["30m","1h","4h","5m"]:
    g=T[(T.kind=="random")&(T.timeframe==tf)]
    nb,ci=blockci(g) if g.entry_time.nunique()>1 else (0,[np.nan,np.nan]); print("RANDOM",tf,len(g),g.R.mean().round(3),ci, g.groupby("run").R.agg(["size","mean"]).round(3).to_dict())
