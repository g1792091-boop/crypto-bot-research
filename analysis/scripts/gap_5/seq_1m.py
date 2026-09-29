"""Fully sequential re-run of 5m V4.5 signals with exits simulated on 1m bars (or on 1m->5m resampled bars).
Entry = open of the 5m bar after the signal bar (same instant on the 1m series).  Per-symbol one position;
a new signal is accepted only if its 5m bar starts after the 5m bar containing the previous exit (engine rule).
Then: per-symbol stats, handoff-style single account (portfolio.single_account), and a true merged
one-position-across-symbols account, over the whole 1m window and the reconstructed RC2 window."""
import os, sys, numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,os.path.join(HERE,"..","bt")); sys.path.insert(0,HERE)
import strategies as S, fg_indicators as fg
from run import load_csv
from engine import CostCfg, default_exit_configs
from sim_vec import simulate
from portfolio import single_account
G=os.path.dirname(HERE)
STRAT=sys.argv[1] if len(sys.argv)>1 else "V45_EXACT_AMB_G1"
EXITS=sys.argv[2].split(",") if len(sys.argv)>2 else ["L50_sl15","L50_sl20"]
fn={"V45_EXACT_AMB_G1":S.v45_exact_amb_g1,"V45_EXACT_AMB":S.v45_exact_amb,"V45_ANY":S.v45_any}[STRAT]
cfgs={c.name:c for c in default_exit_configs()}
RC2=(pd.Timestamp("2026-09-04T07:00Z"),pd.Timestamp("2026-09-13T08:00Z"))
allt=[]
for sym in ("BTCUSD","ETHUSD","SOLUSD"):
    df5=load_csv(f"{G}/data/{sym.lower()}-5m-ohlcv.csv",5); df15=load_csv(f"{G}/data/{sym.lower()}-15m-ohlcv.csv",15)
    L,Sh=fn(df5,df15); L=np.asarray(L,bool); Sh=np.asarray(Sh,bool); Sh=Sh&~(L&Sh)
    atr5=fg.atr(df5,14).to_numpy(float); ts5d=df5.ts.values
    m=pd.read_csv(f"{G}/data1m/{sym.lower()}-1m-ohlcv.csv"); m["ts"]=pd.to_datetime(m.timestamp,utc=True)
    o,h,l,c=(m[k].to_numpy(float) for k in ("open","high","low","close")); ts1=m.ts.values
    r5=m.set_index("ts").resample("5min",label="left",closed="left").agg({"open":"first","high":"max","low":"min","close":"last"}).dropna()
    o5,h5,l5,c5=(r5[k].to_numpy(float) for k in ("open","high","low","close")); tsr5=r5.index.values
    lo=m.ts.iloc[0]+pd.Timedelta("10min"); hi=m.ts.iloc[-1]-pd.Timedelta("1D")
    sig=np.where((L|Sh))[0]; sig=sig[(sig>=1000)&(sig+1<len(df5))]
    sig=[i for i in sig if lo.to_datetime64()<=ts5d[i+1]<hi.to_datetime64()]
    for ex in EXITS:
        cfg=cfgs[ex]
        for res,(oo,hh,ll,cc,tsa,bm,mh) in (("m1",(o,h,l,c,ts1,1,15000)),("r5",(o5,h5,l5,c5,tsr5,5,3000))):
            for mode in ("PESS","DET","OPT"):
                for fee,slip in ((0.0005,0.0002),(0.0001,0.0002),(0.0001,0.0)):
                    cost=CostCfg(fee_side=fee,slip_side=slip,bar_minutes=bm,max_hold=mh)
                    free_after=np.datetime64("1970-01-01")  # 5m-bar open ts of the bar containing the last exit
                    for i in sig:
                        if ts5d[i] <= free_after: continue
                        if not np.isfinite(atr5[i]) or atr5[i]<=0: continue
                        ets=ts5d[i+1]; e=int(np.searchsorted(tsa,ets))
                        if e>=len(oo) or tsa[e]!=ets: continue
                        side=1 if L[i] else -1
                        r=simulate(side,e,oo,hh,ll,cc,float(atr5[i]),cfg,cost,len(oo),mode)
                        xts=tsa[r["exit_idx"]]
                        free_after=(pd.Timestamp(xts).floor("5min")).to_datetime64()
                        allt.append(dict(symbol=sym,strategy=STRAT,exit=ex,res=res,mode=mode,fee=fee,slip=slip,side=side,
                                         entry_ts=pd.Timestamp(ets,tz="UTC"),exit_ts=pd.Timestamp(xts,tz="UTC"),net=r["net"],mae=r["mae"],reason=r["reason"],hold_min=r["hold"]*bm))
d=pd.DataFrame(allt); d.to_csv(f"{G}/out/seq_1m_{STRAT}.csv",index=False)
def pf(x): x=np.asarray(x); gl=-x[x<=0].sum(); return x[x>0].sum()/gl if gl>0 else np.inf
def merged(g, lev=50.0, mf=0.4, mmr=0.005):
    """true single account: all symbols' signals in time order; 1 position overall; exits from this sim"""
    g=g.sort_values(["entry_ts","symbol"]); eq=1000.0; busy=pd.Timestamp("1970-01-01",tz="UTC"); n=w=0
    for r in g.itertuples(index=False):
        if r.entry_ts < busy: continue
        roe=-1.0 if r.mae <= -(1/lev-mmr) else max(-1.0, lev*r.net); eq*=1+mf*roe; busy=r.exit_ts; n+=1; w+=r.net>0
    return eq,n,w
out=[]
for key,g in d.groupby(["exit","res","mode","fee","slip"]):
    for wname,(a,b) in (("ALL",(None,None)),("RC2",RC2)):
        gg=g if a is None else g[(g.entry_ts>=a)&(g.entry_ts<b)]
        sa=single_account(gg,50.0)
        # single_account only uses net/mae/entry/exit/symbol; per-symbol ledgers here are the SAME sequential ones
        # (note: skipped signals in a per-symbol ledger are not re-offered; the merged sim below has the same limitation)
        eqm,nm,wm=merged(gg)
        out.append(dict(exit=key[0],res=key[1],mode=key[2],fee=key[3],slip=key[4],window=wname,n=len(gg),exp=gg.net.mean()*100,pf=pf(gg.net),wr=(gg.net>0).mean()*100,
                        sa_taken=sa["taken"],sa_final=sa["final"],merged_taken=nm,merged_final=eqm,merged_wr=(wm/nm*100 if nm else np.nan)))
o=pd.DataFrame(out); pd.set_option("display.width",250)
print(o.round(4).to_string(index=False)); o.to_csv(f"{G}/out/seq_1m_{STRAT}_summary.csv",index=False)
