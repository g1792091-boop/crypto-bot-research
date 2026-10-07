"""My own fixed-leverage replay of 15m/30m strategy SUBMITTED signals (v3b, v4) on live_bars via the repo engine
(daily3._alone). Funding 0. usage: python3 -I myreplay.py <export_dir> <repo> <out_csv>"""
import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
E,REPO,OUTF=sys.argv[1:4]
sys.path.insert(0,REPO)
import bisect, numpy as np, pandas as pd
from dataclasses import replace
from paperbot.config import v3_settings
from paperbot.obsshadows import variant_settings, symbol_steps
from paperbot.daily3 import _alone, make_signal, _bar_of
from paperbot.margin import Brackets, BracketTier
BR = {"BTCUSDT": [(1e12, 50, 0.004, 0.0)],"ETHUSDT": [(1e12, 50, 0.004, 0.0)],
    "SOLUSDT": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGEUSDT": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCHUSDT": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTCUSDT": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)]}
brackets={s:Brackets([BracketTier(*t) for t in v]) for s,v in BR.items()}
base=v3_settings(taker_fee=0.0005)
VARS=['lev10','lev20m20','lev30m30','lev40m40','lev50m50']
rows=[]
for run in ['run-20261005T183457Z','current']:
    tr=pd.read_csv(f'{E}/{run}/trades.csv'); specs={}
    for s,g in tr.groupby('symbol'):
        q=g.qty.to_numpy(float)
        for k in range(-2,9):
            if np.all(np.abs(q*10.0**k-np.round(q*10.0**k))<1e-6*np.maximum(1,q*10.0**k)):
                specs[s]={'qty_step':10.0**-k,'min_notional':5.0}; break
    acc=pd.read_csv(f'{E}/{run}/accounts.csv').set_index('account_id')
    sig=pd.read_csv(f'{E}/{run}/signal_log.csv'); sig=sig[(sig.status=='SUBMITTED')&sig.timeframe.isin(['15m','30m'])]
    sig=sig[(sig.strategy+'@'+sig.timeframe).map(acc['kind']).eq('strategy')]
    bars=pd.read_csv(f'{E}/{run}/live_bars.csv').sort_values(['ts','symbol'])
    by={}
    cols=list(bars.columns)
    for r in bars.itertuples(index=False):
        d=dict(zip(cols,r))
        for k in ('mark_open','mark_high','mark_low','mark_close','volume','close_time'):
            v=d.get(k)
            if isinstance(v,float) and v!=v: d[k]=None
        by.setdefault(int(d['ts']),{})[d['symbol']]=_bar_of(d)
    ts=sorted(by); steps=[(t,by[t],{}) for t in ts]
    ss={s:symbol_steps(steps,s) for s in bars.symbol.unique()}
    print(run,len(sig),'signals',flush=True)
    for v in VARS:
        S=variant_settings(base,v)
        for d in sig.to_dict('records'):
            i0=bisect.bisect_left(ts,d['bar_close'])
            if i0>=len(ts) or (ts[i0]-d['bar_close'])>5*60000: continue
            t,res=_alone(S,brackets,specs,make_signal(d),ss[d['symbol']],i0)
            o=dict(run=run,variant=v,strategy=d['strategy'],tf=d['timeframe'],symbol=d['symbol'],bar_close=d['bar_close'],side=d['side'])
            if t is not None:
                dist=abs(t.entry_price-t.stop_initial)
                o.update(status='TRADED',R=t.pnl/(t.qty*dist),lev=t.leverage,exit_reason=t.exit_reason,sf=dist/t.entry_price,roe=t.roe)
            else: o['status']='REJECTED' if res else 'UNRESOLVED'
            rows.append(o)
        print(v,flush=True)
pd.DataFrame(rows).to_csv(OUTF,index=False)
