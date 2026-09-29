"""For every stage-1 pooled combo: the smallest uniform per-trade shift delta (in % of price) that would make
PF>=1.2 AND expectancy>0 (pooled).  Compared with the measured resolution effects per exit."""
import os, numpy as np, pandas as pd
G=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R="/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/repro/results"
def pf(x):
    gl=-x[x<=0].sum(); return x[x>0].sum()/gl if gl>0 else np.inf
def need(x):
    lo,hi=0.0,0.02
    if pf(x)>=1.2 and x.mean()>0: return 0.0
    for _ in range(50):
        mid=(lo+hi)/2
        y=x+mid
        if pf(y)>=1.2 and y.mean()>0: hi=mid
        else: lo=mid
    return hi*100
out=[]
for f,tag in (("trades_IS_15m_all5.csv","15m_IS"),("trades_ALL_5m_v45g1.csv","5m_ALL")):
    t=pd.read_csv(os.path.join(R,f),usecols=["strategy","exit","net"])
    for (s,e),g in t.groupby(["strategy","exit"]):
        x=g.net.to_numpy(float)
        if len(x)<100: continue
        out.append(dict(set=tag,strategy=s,exit=e,n=len(x),exp=x.mean()*100,pf=pf(x),need_delta_pct=need(x)))
o=pd.DataFrame(out); o.to_csv(f"{G}/out/required_shift.csv",index=False)
pd.set_option("display.width",200)
for tag,g in o.groupby("set"):
    print(tag,"combos with n>=100:",len(g))
    g=g.copy(); g["emode"]=g.exit.str[0]
    print(g.groupby("emode").need_delta_pct.describe().round(4).to_string())
    print(g.sort_values("need_delta_pct").head(8).round(4).to_string(index=False))
