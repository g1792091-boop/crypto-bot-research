import os, sys, numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.join(HERE,"..","bt")); sys.path.insert(0,HERE)
import fg_indicators as fg
from engine import CostCfg, default_exit_configs, run_backtest, summarize
from run import load_csv, window_bounds
from forward import forward_stats
from analyze import pooled, apply_rule
from extra_ports import EXTRA
DATA=os.path.join(HERE,"..","data")
cost=CostCfg(); cfgs=default_exit_configs()
tr=[]; fw=[]
for sym in ("BTCUSD","ETHUSD","SOLUSD","LTCUSD","BCHUSD"):
    df=load_csv(os.path.join(DATA,f"{sym.lower()}-15m-ohlcv.csv"),15)
    atr=fg.atr(df,14).to_numpy(float); lo,hi=window_bounds(df,"IS")
    for name,fn in EXTRA.items():
        L,S=fn(df); L=np.asarray(L,bool); S=np.asarray(S,bool)&~L
        r=forward_stats(df,L,S,lo,hi); r.update(symbol=sym,strategy=name); fw.append(r)
        for cfg in cfgs:
            t=run_backtest(df,atr,L,S,cfg,cost,lo,hi)
            if len(t):
                t=t.copy(); t["symbol"]=sym; t["strategy"]=name; t["exit"]=cfg.name
                t["entry_ts"]=df["ts"].to_numpy()[t["entry_idx"].to_numpy()]; tr.append(t)
T=pd.concat(tr); P=apply_rule(pooled(T)).sort_values("pf",ascending=False)
F=pd.DataFrame(fw)
g=F.groupby("strategy")
fp=pd.DataFrame({"signals":g["signals"].sum(),**{f"fwd{h}":g.apply(lambda x,h=h: np.average(x[f"fwd{h}_mean_pct"],weights=x["signals"]) if x["signals"].sum() else np.nan) for h in (4,16,64)}})
pd.set_option("display.width",250)
print(fp.round(3).to_string())
print(P[["strategy","exit","trades","wr","pf","exp_net_pct","exp_gross_pct","symbols_pos","eq_L50","pass"]].groupby("strategy").head(3).round(3).to_string(index=False))
print("PASS:",int(P["pass"].sum()),"of",len(P), " max PF", P.pf.max())
P.to_csv(os.path.join(HERE,"extra_pooled.csv"),index=False); F.to_csv(os.path.join(HERE,"extra_forward.csv"),index=False)
