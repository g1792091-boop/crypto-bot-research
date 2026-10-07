import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
OUT=os.path.dirname(os.path.abspath(__file__))
T=pd.read_csv(f"{OUT}/trades_R.csv",low_memory=False)
# LF7 clustering in v4
t=T[T.run=="v4"]; t=t[t.kind.isin(["strategy","ds200","random","reel"])]
c=t.groupby(["symbol","entry_time"]).account_id.transform("size")
for k in ["ds200","strategy"]:
    m=t.kind==k; print("v4",k,"share sharing coin+minute with >=1 other",(c[m]>=2).mean().round(3),">=5 others",(c[m]>=6).mean().round(3))
print("largest cluster",c.max(), t.loc[c.idxmax(),["symbol","entry_time"]].tolist())
# same with only strategy+ds200
t2=t[t.kind.isin(["strategy","ds200"])]; c2=t2.groupby(["symbol","entry_time"]).account_id.transform("size")
for k in ["ds200","strategy"]:
    m=t2.kind==k; print(" (strategy+ds200 only)",k,(c2[m]>=2).mean().round(3),(c2[m]>=6).mean().round(3))
# deff of pooled trade R by tf (strategy, all runs), clusters = 4h block, minute, coin-minute
def deff(x,cl):
    x=np.asarray(x); df=pd.DataFrame({"x":x-x.mean(),"c":cl}); s=df.groupby("c").x.sum()
    return (s**2).sum()/((df.x**2).sum())
for k in ["strategy","ds200"]:
    for tf in ["15m","30m","1h"]:
        g=T[(T.kind==k)&(T.timeframe==tf)]
        print(k,tf,len(g),"deff coin-min",round(deff(g.R,g.run+g.symbol+g.entry_time.astype(str)),2),"min",round(deff(g.R,g.run+g.entry_time.astype(str)),2),"4h",round(deff(g.R,g.run+(g.entry_time//(4*3600000)).astype(str)),2),"sd",round(g.R.std(),2))
# replay neff
D=pd.read_csv(f"{OUT}/replay_sig_rows.csv"); D=D[D.status=="TRADED"]
for k in ["strategy","ds200"]:
    for tf in ["15m","30m","1h"]:
        g=D[(D.kind==k)&(D.tf==tf)]; d=deff(g.R,g.run+(g.bc//(4*3600000)).astype(str))
        print("replay",k,tf,len(g),"blocks",(g.run+(g.bc//(4*3600000)).astype(str)).nunique(),"deff",round(d,1),"neff",round(len(g)/d))
# LF9 luck concentration
A=T[T.kind.isin(["strategy","ds200"])].groupby(["run","account_id"])
rows=[]
for (r,a),g in A:
    pn=g.pnl.sum()
    if pn>0: rows.append(dict(run=r,acc=a,kind=g.kind.iloc[0],n=len(g),gone=(pn-g.pnl.max())<0,best_share=g.pnl.max()/pn))
L=pd.DataFrame(rows); print("profitable acct-runs",len(L),"gone w/o best",L.gone.sum(),round(L.gone.mean(),3))
for k in ["strategy","ds200"]:
    x=L[(L.kind==k)&L.n.between(5,9)]; print(k,"5-9 trades",len(x),"gone share",round(x.gone.mean(),2),"median best share",round(x.best_share.median(),2))
R=T[T.kind=="random"].groupby(["run","account_id"]).pnl.agg(["sum","max","size"]); R=R[R["sum"]>0]
print("random profitable",len(R),"gone",((R["sum"]-R["max"])<0).sum(),"median best share",(R["max"]/R["sum"]).median().round(2))
# N20 v3a live
x=T[(T.strategy_id=="N20_EMA9_CHOP")&(T.run=="v3a")&T.timeframe.isin(["15m","30m"])]; print("N20 v3a 15m+30m live",len(x),x.R.mean().round(3), "sides",x.side.value_counts().to_dict())
# LF13 4h replay
for k in ["strategy","ds200"]:
    g=D[(D.kind==k)&(D.tf=="4h")]; a=pd.read_csv(f"{OUT}/replay_sig_rows.csv"); a=a[(a.kind==k)&(a.tf=="4h")]
    print(k,"4h replay traded",len(g),round(g.R.mean(),3),"incl unresolved",round(a[a.status!="REJECTED"].R.mean(),3),"unres",(a.status=="UNRESOLVED").sum(),"rejected",(a.status=="REJECTED").sum(),"of",len(a),"long share",round((a.side>0).mean(),2))
