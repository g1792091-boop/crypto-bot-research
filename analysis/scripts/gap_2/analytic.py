import os, sys, numpy as np, pandas as pd
sys.path.insert(0,"../bt"); sys.path.insert(0,".")
from posctrl3 import load_tf, SYMS, BARMIN, WINDOW
from run import window_bounds
rows=[]
for tf in ("5m","15m","1h"):
    dfs=load_tf(tf)
    for H in (16,64):
        E=[];SD=[]
        for s,df in dfs.items():
            o=df.open.values; n=len(o)
            lo,hi=(window_bounds(df,WINDOW[tf]) if tf!="1h" else (0,n))
            lo=max(lo,1000); hi=min(hi,n-H-2)
            r=o[lo+1+H:hi+1+H]/o[lo+1:hi+1]-1
            E.append(np.mean(np.abs(r))); SD.append(r.std())
        Eabs=np.mean(E); fund=0.0001*H*BARMIN[tf]/480
        cost=0.0014+fund
        rows.append(dict(tf=tf,H=H,hours=H*BARMIN[tf]/60,Eabs_r_pct=Eabs*100,sd_r_pct=np.mean(SD)*100,
            Eabs_by_sym=" ".join(f"{x*100:.2f}" for x in E),cost_pct=cost*100,
            mnet_star_pct=0.0909*Eabs*100, mu_star_pct=(cost+0.0909*Eabs)*100))
R=pd.DataFrame(rows); pd.set_option("display.width",250); print(R.round(3).to_string(index=False)); R.to_csv("../out/analytic.csv",index=False)
