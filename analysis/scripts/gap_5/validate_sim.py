"""PESS mode must equal engine._simulate_one exactly (random trades on real 5m/15m/1m data, all 13 exits)."""
import os, sys, numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.join(HERE,"..","bt")); sys.path.insert(0,HERE)
from engine import _simulate_one, CostCfg, default_exit_configs
from sim_modes import simulate
import fg_indicators as fg
G=os.path.dirname(HERE); rng=np.random.default_rng(0)
cnt=0; bad=0; maxd=0
for path,bm,mh in ((f"{G}/data/btcusd-5m-ohlcv.csv",5,3000),(f"{G}/data/ethusd-15m-ohlcv.csv",15,1000),(f"{G}/data1m/solusd-1m-ohlcv.csv",1,15000)):
    d=pd.read_csv(path); o,h,l,c=(d[k].to_numpy(float) for k in ("open","high","low","close"))
    atr=fg.atr(d.rename(columns={"timestamp":"ts"}),14).to_numpy(float); n=len(o)
    cost=CostCfg(bar_minutes=bm,max_hold=mh)
    for cfg in default_exit_configs():
        for _ in range(150):
            e=int(rng.integers(100,n-1)); side=int(rng.choice([-1,1])); a=float(atr[e-1])
            r1=_simulate_one(side,e,o,h,l,c,a,cfg,cost,n); r2=simulate(side,e,o,h,l,c,a,cfg,cost,n,"PESS")
            cnt+=1
            ok = (r1["exit_idx"]==r2["exit_idx"]+0) and r1["reason"]==r2["reason"] and abs(r1["net"]-r2["net"])<1e-15 and abs(r1["mae"]-r2["mae"])<1e-15
            maxd=max(maxd,abs(r1["net"]-r2["net"]))
            if not ok: bad+=1
print(f"validated {cnt} random trades: mismatches={bad} max|dnet|={maxd:.2e}")
