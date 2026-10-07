# Own 5-year simulator (written from the rule text, not the repo engine): every signal alone, entry next-bar open,
# 2 ATR stop, ROE ladder (first lock +10% net when net ROE reaches +12%, then +5% steps) at a fixed leverage,
# gap at open, no liquidation. Gross = side*(exit_raw/raw-1) before fees/slip/funding. Also opposite side and
# forward signed returns (exit-free martingale test).
import sys, os, time
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'vb.py')).read())
import numpy as np, pandas as pd
sig_dir, out, tfs = sys.argv[1], sys.argv[2], sys.argv[3].split(',')
LEV=float(sys.argv[4]) if len(sys.argv)>4 else 30.0
COINS=['BTCUSD','ETHUSD','SOLUSD','DOGEUSD','LTCUSD','BCHUSD']
T0=pd.Timestamp('2021-08-01').value; T1=pd.Timestamp('2024-07-01').value; T2=pd.Timestamp('2026-09-30').value
RT=0.0014; H=3000
def sim(o,h,l,c,idx,side,atr,lev):
    n=len(o); m=len(idx)
    raw=o[idx+1]; fill=raw*(1+side*2e-4)
    stop=raw-side*2*atr
    best=np.zeros(m)  # best favourable return vs fill (sign-adjusted)
    lockpx=np.full(m,np.nan)
    exit_raw=np.full(m,np.nan); reason=np.zeros(m,int); held=np.zeros(m,int)
    act=np.arange(m)
    for j in range(1,H+1):
        if len(act)==0: break
        J=idx[act]+j
        okb=J<n
        if not okb.all():
            # data end: close at last close
            e=act[~okb]; exit_raw[e]=c[n-1]; reason[e]=3; held[e]=j-1
            act=act[okb]; J=J[okb]
            if len(act)==0: break
        s=side[act]
        st=np.where(np.isnan(lockpx[act]),stop[act],np.where(s==1,np.maximum(stop[act],lockpx[act]),np.minimum(stop[act],lockpx[act])))
        oo=o[J]; adv=np.where(s==1,l[J],h[J])
        hit=np.where(s==1,adv<=st,adv>=st)
        gap=np.where(s==1,oo<=st,oo>=st)
        e=act[hit]
        exit_raw[e]=np.where(gap[hit],oo[hit],st[hit]); held[e]=j
        reason[e]=np.where(np.isnan(lockpx[e]),0,1)
        act=act[~hit]; J=J[~hit]; s=side[act]
        # update best and ladder at the end of the bar (lock applies from the next bar)
        fav=np.where(s==1,h[J]/fill[act]-1,1-l[J]/fill[act])
        best[act]=np.maximum(best[act],fav)
        roe=lev*(best[act]-RT)
        k=np.floor((roe-0.12)/0.05+1e-9)
        L=np.where(roe>=0.12-1e-12,0.10+0.05*k,np.nan)
        px=fill[act]*(1+s*(L/lev+RT))
        old=lockpx[act]
        new=np.where(np.isnan(old),px,np.where(s==1,np.fmax(old,px),np.fmin(old,px)))
        lockpx[act]=new
    if len(act):
        exit_raw[act]=c[np.minimum(idx[act]+H,n-1)]; reason[act]=3; held[act]=H
    return raw,exit_raw,reason,held
rows=[]
t0=time.time()
for tf in tfs:
    for coin in COINS:
        z=np.load(os.path.join(sig_dir,f'sig_{tf}_{coin}.npz'))
        ts=z['ts']; o,h,l,c,atr=z['o'],z['h'],z['l'],z['c'],z['atr']; n=len(ts)
        for key in [k for k in z.files if k.startswith('s__')]:
            sg=z[key]; idx=np.nonzero(sg)[0]
            idx=idx[(idx+1<n)]
            idx=idx[(ts[idx]>=T0)&(ts[idx]<T2)&np.isfinite(atr[idx])&(atr[idx]>0)&(ts[np.minimum(idx+1,n-1)]<T2)]
            if not len(idx): continue
            side=sg[idx].astype(int)
            raw,xr,rs,hd=sim(o,h,l,c,idx,side,atr[idx],LEV)
            _,xr2,rs2,hd2=sim(o,h,l,c,idx,-side,atr[idx],LEV)
            sf=2*atr[idx]/raw
            f4=np.where(idx+5<n, side*(o[np.minimum(idx+5,n-1)]/raw-1), np.nan)
            f16=np.where(idx+17<n, side*(o[np.minimum(idx+17,n-1)]/raw-1), np.nan)
            rows.append(pd.DataFrame(dict(tf=tf,coin=coin,strategy=key[3:],ts=ts[idx],period=np.where(ts[idx]<T1,1,2),side=side,
                stop_frac=sf,g=side*(xr/raw-1),g_flip=-side*(xr2/raw-1),reason=rs,held=hd,f4=f4,f16=f16)))
    print(tf,'done',round(time.time()-t0),flush=True)
D=pd.concat(rows,ignore_index=True)
D.to_parquet(os.path.join(out,f'a5_5y_{"_".join(tfs)}_lev{int(LEV)}.parquet')) if False else D.to_csv(os.path.join(out,f'a5_5y_{"_".join(tfs)}_lev{int(LEV)}.csv.gz'),index=False)
print('rows',len(D))
