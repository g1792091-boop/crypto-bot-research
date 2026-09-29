"""Option C in 20 minutes: re-simulate the SAME 5m V4.5 entries on Astral 1m bars.
(a) 5m engine on 1m-resampled 5m bars (isolates data-snapshot differences)
(b) same engine run on the 1m bars (stop/ladder updated every minute; closer to the 0.25s live monitor)."""
import os, sys, numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.join(HERE,"..","bt"))
from engine import _simulate_one, CostCfg, default_exit_configs
R="/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/repro/results"
t=pd.read_csv(os.path.join(R,"trades_ALL_5m_v45g1.csv"))
cfgs={c.name:c for c in default_exit_configs()}
rows=[]
for strat in ("V45_EXACT_AMB_G1","V45_ANY"):
  for sym in ("BTCUSD","ETHUSD","SOLUSD"):
    m=pd.read_csv(os.path.join(HERE,"..","data1m",f"{sym.lower()}-1m-ohlcv.csv")); m["ts"]=pd.to_datetime(m.timestamp,utc=True)
    o,h,l,c=(m[k].to_numpy(float) for k in ("open","high","low","close"))
    # resampled 5m (open-labelled)
    r5=m.set_index("ts").resample("5min",label="left",closed="left").agg({"open":"first","high":"max","low":"min","close":"last"}).dropna()
    o5,h5,l5,c5=(r5[k].to_numpy(float) for k in ("open","high","low","close")); ts5=r5.index
    ts1=m.ts
    lo_ts=ts1.iloc[0]+pd.Timedelta("10min"); hi_ts=ts1.iloc[-1]-pd.Timedelta("1D")
    for ex in ("L50_sl15","L50_sl20","F_sl2.0_tp3.0","T_sl1.5_tr1.5"):
        g=t[(t.strategy==strat)&(t.symbol==sym)&(t.exit==ex)].copy()
        g["entry_ts"]=pd.to_datetime(g.entry_ts,utc=True); g["exit_ts"]=pd.to_datetime(g.exit_ts,utc=True)
        g=g[(g.entry_ts>=lo_ts)&(g.exit_ts<=hi_ts)]
        cfg=cfgs[ex]
        for _,tr in g.iterrows():
            side=int(tr.side)
            atr_e = tr.sl_dist*tr.entry_px/cfg.sl_atr if cfg.mode!="LADDER" else 1.0
            e1=int(np.searchsorted(ts1.values, tr.entry_ts.to_datetime64()))
            e5=int(np.searchsorted(ts5.values, tr.entry_ts.to_datetime64()))
            if e1>=len(o) or ts1.iloc[e1]!=tr.entry_ts or e5>=len(o5) or ts5[e5]!=tr.entry_ts: continue
            ca=CostCfg(bar_minutes=5,max_hold=3000); cb=CostCfg(bar_minutes=1,max_hold=15000)
            a=_simulate_one(side,e5,o5,h5,l5,c5,atr_e,cfg,ca,len(o5))
            b=_simulate_one(side,e1,o,h,l,c,atr_e,cfg,cb,len(o))
            rows.append(dict(strategy=strat,symbol=sym,exit=ex,orig_net=tr.net,orig_reason=tr.reason,
                             r5_net=a["net"],r5_reason=a["reason"],m1_net=b["net"],m1_reason=b["reason"],m1_hold_min=b["hold"],orig_hold_min=tr.hold*5))
d=pd.DataFrame(rows); d.to_csv(os.path.join(HERE,"c_1m_orig_trades.csv"),index=False)
def pf(x): return x[x>0].sum()/-x[x<=0].sum()
out=[]
for (s,ex),g in d.groupby(["strategy","exit"]):
    out.append(dict(strategy=s,exit=ex,n=len(g),
      orig_exp=g.orig_net.mean()*100, r5_exp=g.r5_net.mean()*100, m1_exp=g.m1_net.mean()*100,
      orig_pf=pf(g.orig_net), r5_pf=pf(g.r5_net), m1_pf=pf(g.m1_net),
      orig_wr=(g.orig_net>0).mean(), m1_wr=(g.m1_net>0).mean(),
      d_m1_minus_r5=(g.m1_net-g.r5_net).mean()*100, se_d=(g.m1_net-g.r5_net).std()/np.sqrt(len(g))*100,
      reason_agree=(g.m1_reason==g.r5_reason).mean()))
pd.set_option("display.width",250)
print(pd.DataFrame(out).round(4).to_string(index=False))
