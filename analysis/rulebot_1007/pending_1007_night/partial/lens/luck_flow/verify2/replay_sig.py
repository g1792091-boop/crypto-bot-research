"""Every SUBMITTED signal (v3b+v4, 15m/30m/1h/4h, strategy+ds200+random) through my own exit sim, chosen and flipped side."""
import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from mysim import *
OUT=os.path.dirname(os.path.abspath(__file__))
rows=[]
for lab in ["v3b","v4"]:
    B=bars_by_symbol(lab); s=load(lab,"signal_log"); a=load(lab,"accounts")
    s=s[(s.status=="SUBMITTED")&s.timeframe.isin(["15m","30m","1h","4h"])]
    s=s.merge(a[["strategy","timeframe","kind"]],on=["strategy","timeframe"])
    for r in s.itertuples():
        sd=2*r.atr; lev=None
        for L in (30,20):
            if (1/L-0.005)/(1-0.005)*r.ref_price-sd>=max(r.atr,0.002*r.ref_price): lev=L;break
        base=dict(run=lab,kind=r.kind,strategy=r.strategy,tf=r.timeframe,symbol=r.symbol,bc=r.bar_close,side=r.side,lev=lev)
        if lev is None: rows.append({**base,"status":"REJECTED"}); continue
        x=sim(B,r.symbol,r.bar_close,r.side,r.ref_price,sd,lev)
        y=sim(B,r.symbol,r.bar_close,-r.side,r.ref_price,sd,lev)
        if x is None: continue
        rows.append({**base,"status":x["status"],"R":x["R"],"hold_min":x["hold_min"],"exit_time":x["exit_time"],"mfe_R":x["mfe_R"],"mae_R":x["mae_R"],
                     "flip_status":y["status"],"flip_R":y["R"],"flip_exit_time":y["exit_time"]})
D=pd.DataFrame(rows); D.to_csv(f"{OUT}/replay_sig_rows.csv",index=False)
print(D.groupby(["run","kind","tf","status"]).size().unstack(fill_value=0))
