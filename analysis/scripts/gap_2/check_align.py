import os, sys, numpy as np, pandas as pd
sys.path.insert(0,"bt")
from run import load_csv
for tf,syms in (("5m",("BTCUSD","ETHUSD","SOLUSD")),("15m",("BTCUSD","ETHUSD","SOLUSD","LTCUSD","BCHUSD"))):
    for s in syms:
        df=load_csv(f"data/{s.lower()}-{tf}-ohlcv.csv",int(tf[:-1]))
        o=df.open.values; c=df.close.values
        d=np.abs(o[1:]/c[:-1]-1)
        print(tf,s,"|o[t]/c[t-1]-1|: median %.5f%%  mean %.5f%%  share==0 %.3f  p99 %.4f%%"%(np.median(d)*100,d.mean()*100,(d==0).mean(),np.quantile(d,.99)*100))
# oracle hit rate check (posctrl2 construction)
rng=np.random.default_rng(0)
df=load_csv("data/btcusd-5m-ohlcv.csv",5); o=df.open.values; n=len(o)
for k in (6,64):
  for q in (0.3,0.5,0.8):
    idx=np.sort(rng.choice(np.arange(1000,n-70),size=1800,replace=False))
    fut=np.sign(o[idx+1+k]/o[idx+1]-1); rnd=rng.choice([-1,1],size=len(idx))
    side=np.where(rng.random(len(idx))<q,fut,rnd); side[side==0]=1
    r=side*(o[idx+1+k]/o[idx+1]-1)
    print(f"k={k} q={q}: hit rate at k = {(r>0).mean():.3f}  (theory (1+q)/2={(1+q)/2:.2f})")
