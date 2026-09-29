"""Positive control: how much signal edge does each exit family need to pass the rule?
Oracle signals on the real 5m data: at random bars, side = sign(o[i+1+k]/o[i+1]-1) with prob q,
else random. q dials in a known edge at horizon k.  Engine/costs/rule exactly as stage 1."""
import os, sys, numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.join(HERE,"..","bt"))
import fg_indicators as fg
from engine import CostCfg, default_exit_configs, run_backtest
from run import load_csv
from analyze import pooled, apply_rule
DATA=os.path.join(HERE,"..","data")
cfgs=[c for c in default_exit_configs() if c.name in ("L50_sl15","L50_sl20","F_sl2.0_tp3.0","F_sl1.0_tp1.5")]
rng=np.random.default_rng(11)
dfs={s:load_csv(os.path.join(DATA,f"{s.lower()}-5m-ohlcv.csv"),5) for s in ("BTCUSD","ETHUSD","SOLUSD")}
rows=[]
for k in (6,64):
  for q in (0.0,0.05,0.10,0.20,0.30):
    tr=[]; fw=[]
    for sym,df in dfs.items():
        o=df.open.to_numpy(float); n=len(o); atr=fg.atr(df,14).to_numpy(float)
        idx=np.sort(rng.choice(np.arange(1000,n-70),size=1800,replace=False))
        fut=np.sign(o[idx+1+k]/o[idx+1]-1); rnd=rng.choice([-1,1],size=len(idx))
        side=np.where(rng.random(len(idx))<q,fut,rnd); side[side==0]=1
        L=np.zeros(n,bool); S_=np.zeros(n,bool); L[idx[side>0]]=True; S_[idx[side<0]]=True
        fw.append(side*(o[idx+1+64]/o[idx+1]-1)); fw.append(np.array([]))
        g6=side*(o[idx+1+6]/o[idx+1]-1)
        for cfg in cfgs:
            t=run_backtest(df,atr,L,S_,cfg,CostCfg(bar_minutes=5,max_hold=3000),0,n)
            t=t.copy(); t["symbol"]=sym; t["strategy"]="oracle"; t["exit"]=cfg.name
            t["entry_ts"]=df.ts.to_numpy()[t.entry_idx.to_numpy()]; tr.append(t)
        rows_fw6=g6.mean()
    T=pd.concat(tr); P=apply_rule(pooled(T))
    f64=np.concatenate(fw).mean()*100
    for _,r in P.iterrows():
        rows.append(dict(k=k,q=q,fwd64_pct=f64,exit=r.exit,trades=r.trades,exp_gross=r.exp_gross_pct,exp_net=r.exp_net_pct,pf=r.pf,wr=r.wr,avg_hold=r.avg_hold,sym_pos=r.symbols_pos,eqL50=r.eq_L50,passed=r["pass"]))
R=pd.DataFrame(rows); pd.set_option("display.width",250)
print(R.round(4).to_string(index=False)); R.to_csv("posctrl.csv",index=False)
