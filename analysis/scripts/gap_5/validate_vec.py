import os, sys, numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.join(HERE,"..","bt")); sys.path.insert(0,HERE)
from engine import _simulate_one, CostCfg, default_exit_configs
import sim_modes, sim_vec
import fg_indicators as fg
G=os.path.dirname(HERE); rng=np.random.default_rng(1)
stats={}
for path,bm,mh in ((f"{G}/data/btcusd-5m-ohlcv.csv",5,3000),(f"{G}/data1m/ethusd-1m-ohlcv.csv",1,15000)):
    d=pd.read_csv(path); o,h,l,c=(d[k].to_numpy(float) for k in ("open","high","low","close"))
    atr=fg.atr(d.rename(columns={"timestamp":"ts"}),14).to_numpy(float); n=len(o)
    for slip in (0.0002,0.0):
      cost=CostCfg(bar_minutes=bm,max_hold=mh,slip_side=slip)
      for cfg in default_exit_configs():
        for _ in range(60):
            e=int(rng.integers(100,n-1)); side=int(rng.choice([-1,1])); a=float(atr[e-1])*(5 if bm==1 else 1)
            ref=_simulate_one(side,e,o,h,l,c,a,cfg,cost,n)
            for mode in ("PESS","DET","OPT"):
                r1=sim_modes.simulate(side,e,o,h,l,c,a,cfg,cost,n,mode); r2=sim_vec.simulate(side,e,o,h,l,c,a,cfg,cost,n,mode)
                k=(mode,); s=stats.setdefault(mode,[0,0,0,0])
                s[0]+=1; s[1]+= not (r1["exit_idx"]==r2["exit_idx"] and r1["reason"]==r2["reason"] and abs(r1["net"]-r2["net"])<1e-14)
                if mode=="PESS": s[2]+= not (ref["exit_idx"]==r2["exit_idx"] and ref["reason"]==r2["reason"] and abs(ref["net"]-r2["net"])<1e-14)
                s[3]+= (r2["net"] < ref["net"]-1e-12)  # DET/OPT should never be worse than PESS? (not guaranteed for TRAIL/LADDER)
print({k:dict(n=v[0],loop_vs_vec_mismatch=v[1],vec_vs_engine_mismatch=v[2],worse_than_engine=v[3]) for k,v in stats.items()})
