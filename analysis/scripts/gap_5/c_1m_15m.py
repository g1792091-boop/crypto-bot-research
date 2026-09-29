"""Option C for the 15m strategies: the September trades of a 15m ALL-window run (BTC/ETH/SOL, delivered 15m data)
re-simulated on (r15) 1m bars resampled to 15m and (m1) the 1m bars, PESS/DET/OPT, all 13 exits."""
import os, sys, numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.join(HERE,"..","bt")); sys.path.insert(0,HERE)
from engine import CostCfg, default_exit_configs
from sim_vec import simulate
G=os.path.dirname(HERE)
cols=["side","entry_px","net","reason","hold","sl_dist","symbol","strategy","exit","entry_ts","exit_ts","mae"]
t=pd.read_csv(f"{G}/results/trades_ALL_15m_gap5_3sym.csv",usecols=cols)
t["entry_ts"]=pd.to_datetime(t.entry_ts,utc=True); t["exit_ts"]=pd.to_datetime(t.exit_ts,utc=True)
t=t[t.entry_ts>=pd.Timestamp("2026-08-31T17:00Z")]
cfgs={c.name:c for c in default_exit_configs()}
rows=[]
for sym in ("BTCUSD","ETHUSD","SOLUSD"):
    m=pd.read_csv(f"{G}/data1m/{sym.lower()}-1m-ohlcv.csv"); m["ts"]=pd.to_datetime(m.timestamp,utc=True)
    o,h,l,c=(m[k].to_numpy(float) for k in ("open","high","low","close")); ts1=m.ts.values
    r=m.set_index("ts").resample("15min",label="left",closed="left").agg({"open":"first","high":"max","low":"min","close":"last"})
    cnt=m.set_index("ts").resample("15min",label="left",closed="left").size(); r=r[cnt==15]   # complete 15m buckets only
    o15,h15,l15,c15=(r[k].to_numpy(float) for k in ("open","high","low","close")); ts15=r.index.values
    lo=pd.Timestamp(ts15[0],tz="UTC"); hi=m.ts.iloc[-1]-pd.Timedelta("1D")
    g0=t[(t.symbol==sym)&(t.entry_ts>=lo)&(t.exit_ts<=hi)]
    for tr in g0.itertuples(index=False):
        cfg=cfgs[tr.exit]
        atr_e = tr.sl_dist*tr.entry_px/cfg.sl_atr if cfg.mode!="LADDER" else 1.0
        et=tr.entry_ts.to_datetime64()
        e1=int(np.searchsorted(ts1,et)); e15=int(np.searchsorted(ts15,et))
        if e1>=len(o) or ts1[e1]!=et or e15>=len(o15) or ts15[e15]!=et: continue
        row=dict(strategy=tr.strategy,symbol=sym,exit=tr.exit,side=int(tr.side),entry_ts=tr.entry_ts,orig_net=tr.net,orig_reason=tr.reason,orig_hold_min=tr.hold*15)
        ca=CostCfg(bar_minutes=15,max_hold=1000); cb=CostCfg(bar_minutes=1,max_hold=15000)
        for mode in ("PESS","DET","OPT"):
            a=simulate(int(tr.side),e15,o15,h15,l15,c15,atr_e,cfg,ca,len(o15),mode)
            b=simulate(int(tr.side),e1,o,h,l,c,atr_e,cfg,cb,len(o),mode)
            row[f"r15_{mode}"]=a["net"]; row[f"m1_{mode}"]=b["net"]
            row[f"r15_{mode}_reason"]=a["reason"]; row[f"m1_{mode}_reason"]=b["reason"]; row[f"m1_{mode}_hold_min"]=b["hold"]
        rows.append(row)
d=pd.DataFrame(rows); d.to_csv(f"{G}/out/c_1m_15m_trades.csv",index=False); print("saved",len(d))
