import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from mysim import *
OUT=os.path.dirname(os.path.abspath(__file__))
rows=[]
for lab in ["v3b","v4"]:
    B=bars_by_symbol(lab); t=load(lab,"trades"); a=load(lab,"accounts")
    o=load(lab,"outcomes"); o=o[o.status=="ENTERED"]
    t=t.merge(a[["account_id","kind"]],on="account_id")
    t=t[t.kind.isin(["strategy","ds200","random"])]
    t=t.merge(o[["account_id","sig_ts","symbol","ref_price","stop_dist","sig_atr"]],left_on=["account_id","signal_ts","symbol"],right_on=["account_id","sig_ts","symbol"],how="left")
    for r in t.itertuples():
        sd=r.stop_dist if r.stop_dist==r.stop_dist else 2*r.sig_atr
        x=sim(B,r.symbol,int(r.signal_ts)+1,int(r.side),r.ref_price,sd,int(r.leverage))
        if x is None: continue
        Rlive=r.pnl/(r.qty*abs(r.entry_price-r.stop_initial))
        rows.append(dict(run=lab,kind=r.kind,tf=r.timeframe,lev=r.leverage,R_live=Rlive,R_my=x["R"],st=x["status"],
            same_exit=abs(x["exit_time"]-r.exit_time)<2 if x["status"]=="TRADED" else False,reason_live=r.exit_reason,reason_my=x["reason"],funding=r.funding))
D=pd.DataFrame(rows); D.to_csv(f"{OUT}/validate_rows.csv",index=False)
D["d"]=D.R_my-D.R_live
print(len(D), D.groupby(["run","tf"]).agg(n=("d","size"),same_exit=("same_exit","mean"),mean_d=("d","mean"),mad=("d",lambda x:x.abs().median()),corr=("R_live",lambda x: np.corrcoef(x,D.loc[x.index,"R_my"])[0,1])).round(3))
print(pd.crosstab(D.reason_live,D.reason_my))
