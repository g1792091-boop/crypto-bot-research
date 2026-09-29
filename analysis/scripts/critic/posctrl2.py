import os, sys, numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.join(HERE,"..","bt"))
import fg_indicators as fg
from engine import CostCfg, ExitCfg, default_exit_configs, run_backtest
from run import load_csv
from analyze import pooled, apply_rule
DATA=os.path.join(HERE,"..","data")
base=[c for c in default_exit_configs() if c.name in ("L50_sl15","L50_sl20","F_sl2.0_tp3.0")]
time64=ExitCfg(name="TIME64_taker",mode="FIXED",sl_atr=1e4,tp_atr=1e4)
rng=np.random.default_rng(12)
dfs={s:load_csv(os.path.join(DATA,f"{s.lower()}-5m-ohlcv.csv"),5) for s in ("BTCUSD","ETHUSD","SOLUSD")}
rows=[]
for k,qs in ((3,(0.4,0.6,0.8)),(6,(0.4,0.6,0.8)),(64,(0.3,0.5))):
  for q in qs:
    tr=[]; fk=[]; f64=[]
    for sym,df in dfs.items():
        o=df.open.to_numpy(float); n=len(o); atr=fg.atr(df,14).to_numpy(float)
        idx=np.sort(rng.choice(np.arange(1000,n-70),size=1800,replace=False))
        fut=np.sign(o[idx+1+k]/o[idx+1]-1); rnd=rng.choice([-1,1],size=len(idx))
        side=np.where(rng.random(len(idx))<q,fut,rnd); side[side==0]=1
        L=np.zeros(n,bool); S_=np.zeros(n,bool); L[idx[side>0]]=True; S_[idx[side<0]]=True
        fk.append(side*(o[idx+1+k]/o[idx+1]-1)); f64.append(side*(o[idx+1+64]/o[idx+1]-1))
        for cfg in base+[time64]:
            cc=CostCfg(bar_minutes=5,max_hold=(65 if cfg.name.startswith("TIME") else 3000))
            t=run_backtest(df,atr,L,S_,cfg,cc,0,n).copy()
            t["symbol"]=sym; t["strategy"]="oracle"; t["exit"]=cfg.name; t["entry_ts"]=df.ts.to_numpy()[t.entry_idx.to_numpy()]; tr.append(t)
    P=apply_rule(pooled(pd.concat(tr)))
    for _,r in P.iterrows():
        rows.append(dict(k=k,q=q,fwdk_pct=np.concatenate(fk).mean()*100,fwd64_pct=np.concatenate(f64).mean()*100,exit=r.exit,trades=r.trades,
                         exp_gross=r.exp_gross_pct,exp_net=r.exp_net_pct,pf=r.pf,wr=r.wr,hold=r.avg_hold,eqL50=r.eq_L50,passed=r["pass"]))
R=pd.DataFrame(rows); pd.set_option("display.width",250); print(R.round(4).to_string(index=False)); R.to_csv("posctrl2.csv",index=False)
