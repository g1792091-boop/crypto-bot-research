import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
OUT=os.path.dirname(os.path.abspath(__file__))
for lab in RUNS:
    s=load(lab,"signal_log"); s=s[s.symbol!="XRPUSDT"].sort_values("ref_time")
    f=s.groupby("symbol").ref_price.first(); l=s.groupby("symbol").ref_price.last()
    r=(l/f-1)*100
    print(lab,"signal_log ref first->last %",r.round(2).to_dict(),"EW",round(r.mean(),2))
    if lab!="v3a":
        b=load(lab,"live_bars").sort_values("ts")
        f=b.groupby("symbol").open.first(); l=b.groupby("symbol").close.last(); r=(l/f-1)*100
        print("   live_bars %",r.round(2).to_dict(),"EW",round(r.mean(),2), kst(b.ts.min()),kst(b.ts.max()))
D=pd.read_csv(f"{OUT}/cf_mine_rows.csv"); D=D[D.status=="TRADED"]
p=D.groupby(["run","tf","side"]).R.mean().unstack(); p["short_minus_long"]=p[-1]-p[1]
c=D.groupby(["run","tf"]).cost_R.mean(); p["cost"]=c; p["ratio"]=p.short_minus_long/p.cost
print(p.round(3))
q=D[(D.run=="v4")&(D.tf=="15m")].groupby(["symbol","side"]).R.mean().unstack(); q["l_minus_s"]=q[1]-q[-1]; print(q.round(2))
