import sys, os
exec(open('vb.py').read())
import numpy as np, pandas as pd
sig=sys.argv[1]
T0=pd.Timestamp('2021-08-01').value; T2=pd.Timestamp('2026-09-30').value
live={'15m':0.620,'30m':0.886,'1h':1.244,'4h':2.016}
r=pd.read_csv('out/a2_replay_rows.csv'); r=r[r.k2.isin(['core36','ds200'])]
for tf in ['15m','30m','1h','4h']:
    allv=[];yr=[]
    for c in ['BTCUSD','ETHUSD','SOLUSD','DOGEUSD','LTCUSD','BCHUSD']:
        z=np.load(os.path.join(sig,f'sig_{tf}_{c}.npz')); ts=z['ts']; m=(ts>=T0)&(ts<T2)&np.isfinite(z['atr'])
        v=200*z['atr'][m]/z['c'][m]; allv.append(v); yr.append(pd.to_datetime(ts[m]).year)
    v=np.concatenate(allv); y=np.concatenate(yr)
    lv=r[r.timeframe==tf].stop_pct.median()
    pct=100*(v<lv).mean()
    print(tf,'live median',round(lv,3),'5y all-bar median',round(np.median(v),3),'live pctile',round(pct,1),
          'by year',{int(k):round(float(np.median(v[y==k])),3) for k in np.unique(y)},
          'share cost<=0.10R (stop>=1.4%)',round(100*(v>=1.4).mean(),1),
          'paper cost R live',round(14/(100*lv),3),'5y-median',round(14/(100*np.median(v)),3))
# per coin live median stop and real RT cost per coin
rt={'BCHUSDT':19.31,'BTCUSDT':10.10,'DOGEUSDT':12.40,'ETHUSDT':10.20,'LTCUSDT':16.03,'SOLUSDT':10.99}
rr=r.copy(); rr['rt_real']=rr.symbol.map(rt); rr['costR_real']=rr.rt_real/(100*rr.stop_pct); rr['costR_paper']=14/(100*rr.stop_pct)
t=rr.groupby(['timeframe','symbol']).agg(n=('stop_pct','size'),med_stop=('stop_pct','median'),costR_real_mean=('costR_real','mean'),costR_paper_mean=('costR_paper','mean')).reset_index()
t['costR_real_at_median']=t.symbol.map(rt)/(100*t.med_stop)
print(t.round(3).to_string())
print(rr.groupby('timeframe').agg(costR_real=('costR_real','mean'),costR_paper=('costR_paper','mean')).round(3))
