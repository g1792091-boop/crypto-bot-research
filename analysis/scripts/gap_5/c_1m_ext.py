"""Extended Option-C check for the 5m V4.5 entries.
Same entries as the reproduced 5m ledger; exits re-simulated on
  r5 = 1m bars resampled to 5m (same data as m1, 5m resolution)
  m1 = the 1m bars
each under PESS (= engine), DET (certain same-bar lock), OPT (favourable-first) and two slippage settings.
Fee variants are applied analytically (fee does not affect the path)."""
import os, sys, numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.join(HERE,"..","bt")); sys.path.insert(0,HERE)
from engine import CostCfg, default_exit_configs
from sim_vec import simulate
G=os.path.dirname(HERE)
R="/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/repro/results"
t=pd.read_csv(os.path.join(R,"trades_ALL_5m_v45g1.csv"))
t["entry_ts"]=pd.to_datetime(t.entry_ts,utc=True); t["exit_ts"]=pd.to_datetime(t.exit_ts,utc=True)
cfgs={c.name:c for c in default_exit_configs()}
STRATS=sys.argv[1].split(",") if len(sys.argv)>1 else ["V45_EXACT_AMB_G1","V45_EXACT_AMB","V45_ANY"]
rows=[]
for sym in ("BTCUSD","ETHUSD","SOLUSD"):
    m=pd.read_csv(f"{G}/data1m/{sym.lower()}-1m-ohlcv.csv"); m["ts"]=pd.to_datetime(m.timestamp,utc=True)
    o,h,l,c=(m[k].to_numpy(float) for k in ("open","high","low","close"))
    r5=m.set_index("ts").resample("5min",label="left",closed="left").agg({"open":"first","high":"max","low":"min","close":"last"}).dropna()
    o5,h5,l5,c5=(r5[k].to_numpy(float) for k in ("open","high","low","close"))
    ts1=m.ts.values; ts5=r5.index.values
    lo_ts=m.ts.iloc[0]+pd.Timedelta("10min"); hi_ts=m.ts.iloc[-1]-pd.Timedelta("1D")
    g0=t[(t.symbol==sym)&(t.strategy.isin(STRATS))&(t.entry_ts>=lo_ts)&(t.exit_ts<=hi_ts)]
    for tr in g0.itertuples(index=False):
        cfg=cfgs[tr.exit]
        atr_e = tr.sl_dist*tr.entry_px/cfg.sl_atr if cfg.mode!="LADDER" else 1.0
        e1=int(np.searchsorted(ts1, tr.entry_ts.to_datetime64())); e5=int(np.searchsorted(ts5, tr.entry_ts.to_datetime64()))
        if e1>=len(o) or ts1[e1]!=tr.entry_ts.to_datetime64() or e5>=len(o5) or ts5[e5]!=tr.entry_ts.to_datetime64(): continue
        row=dict(strategy=tr.strategy,symbol=sym,exit=tr.exit,side=int(tr.side),entry_ts=tr.entry_ts,orig_net=tr.net,orig_reason=tr.reason,orig_hold_min=tr.hold*5,orig_mae=tr.mae)
        for slip,sl_tag in ((0.0002,""),(0.0,"_s0")):
            ca=CostCfg(bar_minutes=5,max_hold=3000,slip_side=slip); cb=CostCfg(bar_minutes=1,max_hold=15000,slip_side=slip)
            for mode in ("PESS","DET","OPT"):
                a=simulate(int(tr.side),e5,o5,h5,l5,c5,atr_e,cfg,ca,len(o5),mode)
                b=simulate(int(tr.side),e1,o,h,l,c,atr_e,cfg,cb,len(o),mode)
                row[f"r5_{mode}{sl_tag}"]=a["net"]; row[f"m1_{mode}{sl_tag}"]=b["net"]
                if sl_tag=="":
                    row[f"r5_{mode}_reason"]=a["reason"]; row[f"m1_{mode}_reason"]=b["reason"]
                    row[f"m1_{mode}_hold_min"]=b["hold"]; row[f"m1_{mode}_mae"]=b["mae"]; row[f"r5_{mode}_mae"]=a["mae"]
                    row[f"m1_{mode}_exit_ts"]=m.ts.iloc[b["exit_idx"]]
        rows.append(row)
d=pd.DataFrame(rows)
tag="_".join(s.replace("V45_","") for s in STRATS)
d.to_csv(f"{G}/out/c_1m_ext_trades_{tag}.csv",index=False)
print("saved",len(d),"trades")
