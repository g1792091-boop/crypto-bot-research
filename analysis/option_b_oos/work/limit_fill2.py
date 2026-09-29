"""Follow-ups for option B: stop width, realistic exit-limit fallback, and
one-position-per-symbol (non-overlapping) sequencing. In-sample upper bound."""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bt"))
import strategies as S, fg_indicators as fg
from run import load_csv
DATA = os.path.join(HERE, "..", "data")
H = 64; TAKER, MAKER, SLIP = 0.0005, 0.0002, 0.0002

def one(o,h,l,c,atr,i,s,stop_atr,exit_mode,n):
    ex = i+1+H
    L = c[i]; fj=None
    for j in range(i+1, min(i+4, ex)):
        if (s>0 and l[j]<L) or (s<0 and h[j]>L):
            fj=j; fpx=min(o[j],L) if s>0 else max(o[j],L); break
    if fj is None: return None
    xp=None; stop=False; xj=ex
    if stop_atr:
        sl = fpx*(1-s*stop_atr*atr[i]/fpx)
        for j in range(fj+1, ex):
            if (s>0 and l[j]<=sl) or (s<0 and h[j]>=sl):
                xp=(min(o[j],sl) if s>0 else max(o[j],sl))*(1-s*SLIP); stop=True; xj=j; break
    if stop:
        fee=MAKER+TAKER
    elif exit_mode=="maker":
        xp=o[ex]; fee=2*MAKER
    elif exit_mode=="taker":
        xp=o[ex]*(1-s*SLIP); fee=MAKER+TAKER
    else:  # limit at o[ex] valid 3 bars, trade-through, else taker at o[ex+3]
        P=o[ex]; got=False
        for j in range(ex, min(ex+3,n)):
            if (s>0 and h[j]>P) or (s<0 and l[j]<P):
                xp=P; got=True; xj=j; break
        if got: fee=2*MAKER
        else:
            jj=min(ex+3,n-1); xp=o[jj]*(1-s*SLIP); fee=MAKER+TAKER; xj=jj
    g=s*(xp/fpx-1)
    return g-fee, xj, stop

rows=[]
data={}
for sym in ("BTCUSD","ETHUSD","SOLUSD"):
    d5=load_csv(os.path.join(DATA,f"{sym.lower()}-5m-ohlcv.csv"),5); d15=load_csv(os.path.join(DATA,f"{sym.lower()}-15m-ohlcv.csv"),15)
    Lg,Sg=S.v45_exact_amb(d5,d15); Lg=np.asarray(Lg,bool); Sg=np.asarray(Sg,bool)&~Lg
    o,h,l,c=(d5[x].to_numpy(float) for x in ("open","high","low","close")); atr=fg.atr(d5,14).to_numpy(float)
    idx=np.where((Lg|Sg)[1000:])[0]+1000; side=np.where(Lg[idx],1,-1)
    data[sym]=(o,h,l,c,atr,idx,side,d5["ts"].to_numpy())
for stop_atr in (None,2.0,4.0,6.0):
    for exit_mode in ("maker","limit_fallback","taker"):
        for seq in ("all_signals","one_pos_per_symbol"):
            nets=[]; stops=0; persym={}; months={}
            for sym,(o,h,l,c,atr,idx,side,ts) in data.items():
                n=len(o); busy=-1; ps=[]
                for i,s in zip(idx,side):
                    if i+1+H+3>=n: continue
                    if seq=="one_pos_per_symbol" and i<=busy: continue
                    r=one(o,h,l,c,atr,i,s,stop_atr,exit_mode,n)
                    if r is None: continue
                    net,xj,st=r; busy=xj; ps.append(net); stops+=st
                    m=str(pd.Timestamp(ts[i]))[:7]; months.setdefault(m,[]).append(net)
                persym[sym]=np.mean(ps)*100; nets+=ps
            nets=np.array(nets)
            rows.append(dict(stop_atr=stop_atr,exit=exit_mode,seq=seq,trades=len(nets),net_pct=nets.mean()*100,
                             pf=nets[nets>0].sum()/-nets[nets<=0].sum(),stop_share=stops/len(nets),
                             sym=" ".join(f"{k[:3]}{v:+.3f}" for k,v in persym.items()),
                             months_pos=sum(np.sum(v)>0 for v in months.values()),months=len(months)))
res=pd.DataFrame(rows); pd.set_option("display.width",250)
print(res.round(4).to_string(index=False)); res.to_csv(os.path.join(HERE,"limit_fill2.csv"),index=False)
