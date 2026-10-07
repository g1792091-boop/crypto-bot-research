import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path[:0]=['/root/.local/lib/python3.11/site-packages']
import numpy as np, pandas as pd
from v_outcomes import size, COINS, bracket, EQ, SLIP
SIG=sys.argv[1]; V=sys.argv[2]
def ok(coin, L, af, margin_pct=None):
    return size(coin, 1, 100.0, af*100.0, levs=(L,))[0] > 0
grid=np.exp(np.linspace(np.log(3e-4),np.log(0.06),500))
P={"5y":("2021-08-01","2026-09-30"),"30d":("2026-08-30","2026-09-30"),"3y":("2023-10-01","2026-09-29")}
out={}
for tf,L in (("4h",20),("4h",30),("1h",20),("1h",30),("15m",50)):
    row=[]
    for coin in COINS:
        tab=np.array([ok(coin,L,g) for g in grid])
        z=np.load(os.path.join(SIG,f"sig_{tf}_{coin}.npz")); ts,c,a=z["ts"],z["c"],z["atr"]; af=a/c
        r=[]
        for p,(a0,a1) in P.items():
            m=(ts>=pd.Timestamp(a0).value)&(ts<pd.Timestamp(a1).value)&np.isfinite(af)
            gi=np.clip(np.searchsorted(grid,af[m]),0,len(grid)-1); r.append(tab[gi].mean())
        row.append((coin,)+tuple(np.round(r,3)))
    mean=np.mean([x[1:] for x in row],axis=0)
    print(tf,f"{L}x (5y,30d,3y)",row,"mean",np.round(mean,3))
# forced 20x (no buffer gate) on 4h/1h signals of the subset: liq closer than stop and initial-stop exit
d=pd.read_csv(os.path.join(V,"outc.csv"))
for tfi,tf in ((3,"4h"),(2,"1h")):
    q=d[d.tf==tfi].drop_duplicates(["coin","e","side"])
    res=[]
    for L in (20,30):
        liqd=[]
        for coin,af in zip(q.coin,q.atr_frac):
            fill=1+SLIP; notional=EQ*L/100*L; qq=notional/fill; ml,mmr,cum=bracket(COINS[coin],notional)
            liq=(EQ*L/100+cum-qq*fill)/(qq*mmr-qq); liqd.append(1-liq)
        liqd=np.array(liqd); stopd=2*q.atr_frac.values+SLIP
        inside=liqd<stopd
        res.append(f"{L}x: liq inside stop {inside.mean():.3f}, liq inside & initial-stop exit {(inside&(q.reason.values==0)).mean():.3f}, gate fail {(liqd-stopd< q.atr_frac.values).mean():.3f}")
    print(tf,"signals",len(q)," | ".join(res))
