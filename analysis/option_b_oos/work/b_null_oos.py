"""Option B in-sample 'pass' vs a circular-shift null that keeps signal clustering and side mix.
Mechanics (fixed, from limit_fill2.py): limit at signal close valid 3 bars (trade-through),
exit at o[i+1+64] as maker (and a taker-exit variant), no stop, one position per symbol."""
import os, sys, numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.join(HERE,"..","bt"))
import strategies as S
from run import load_csv
DATA=os.environ["BNULL_DATA"]; H=64; MAKER,TAKER,SLIP=0.0002,0.0005,0.0002
def run(o,h,l,c,idx,side,exit_taker):
    n=len(o); busy=-1; nets=[]
    for i,s in zip(idx,side):
        ex=i+1+H
        if ex>=n or i<=busy: continue
        L=c[i]; fp=None
        for j in range(i+1,min(i+4,ex)):
            if (s>0 and l[j]<L) or (s<0 and h[j]>L): fp=min(o[j],L) if s>0 else max(o[j],L); break
        if fp is None: continue
        if exit_taker: xp=o[ex]*(1-s*SLIP); fee=MAKER+TAKER
        else: xp=o[ex]; fee=2*MAKER
        nets.append(s*(xp/fp-1)-fee); busy=ex
    return np.array(nets)
D={}
for sym in ("BTCUSD","ETHUSD","SOLUSD"):
    d5=load_csv(os.path.join(DATA,f"{sym.lower()}-5m-ohlcv.csv"),5); d15=load_csv(os.path.join(DATA,f"{sym.lower()}-15m-ohlcv.csv"),15)
    L,Sg=S.v45_exact_amb(d5,d15); L=np.asarray(L,bool); Sg=np.asarray(Sg,bool)&~L
    D[sym]=(d5.open.to_numpy(float),d5.high.to_numpy(float),d5.low.to_numpy(float),d5.close.to_numpy(float),L,Sg)
def evaluate(shifts,exit_taker):
    allnet=[]; pos=0
    for k,(sym,(o,h,l,c,L,Sg)) in enumerate(D.items()):
        n=len(o); sh=shifts[k]
        Ls=np.roll(L[1000:],sh); Ss=np.roll(Sg[1000:],sh)
        idx=np.where(Ls|Ss)[0]+1000; side=np.where(Ls[idx-1000],1,-1)
        x=run(o,h,l,c,idx,side,exit_taker); allnet.append(x); pos+=x.sum()>0
    x=np.concatenate(allnet); pf=x[x>0].sum()/-x[x<=0].sum()
    return len(x), x.mean()*100, pf, pos
M=min(len(v[0]) for v in D.values())-1000  # rolled length (was hard-coded 39000 = 40000-1000)
rng=np.random.default_rng(3)
for exit_taker in (False,True):
    real=evaluate([0,0,0],exit_taker)
    null=[]
    for r in range(300):
        null.append(evaluate(list(rng.integers(288,M-1000-288,size=3)),exit_taker))
    N=pd.DataFrame(null,columns=["n","exp","pf","pos"])
    passn=((N.n>=100)&(N.pf>=1.2)&(N.exp>0)&(N.pos>=3))
    print(("TAKER exit" if exit_taker else "MAKER exit"), "real: n=%d exp=%+.4f%% pf=%.3f pos=%d/3"%real,
          "| null: mean exp %+.4f%%, pf median %.3f, p95 %.3f; P(null pf>=real)=%.3f; null PASS rate=%.3f; P(null exp>=real)=%.3f"%(
          N.exp.mean(),N.pf.median(),N.pf.quantile(.95),(N.pf>=real[2]).mean(),passn.mean(),(N.exp>=real[1]).mean()))

print("--- common shift across symbols (keeps cross-symbol co-timing) ---")
for exit_taker in (False,True):
    real=evaluate([0,0,0],exit_taker)
    null=[]
    for r in range(300):
        s=int(rng.integers(288,M-1000-288)); null.append(evaluate([s,s,s],exit_taker))
    N=pd.DataFrame(null,columns=["n","exp","pf","pos"])
    passn=((N.n>=100)&(N.pf>=1.2)&(N.exp>0)&(N.pos>=3))
    z=(real[1]-N.exp.mean())/N.exp.std()
    print(("TAKER exit" if exit_taker else "MAKER exit"), "real exp=%+.4f%% pf=%.3f | null exp mean %+.4f sd %.4f -> z=%.2f; P(null exp>=real)=%.3f; null PASS rate=%.3f"%(
          real[1],real[2],N.exp.mean(),N.exp.std(),z,(N.exp>=real[1]).mean(),passn.mean()))
