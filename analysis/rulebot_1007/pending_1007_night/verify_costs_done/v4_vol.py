# 5y distribution of the 2 ATR stop (% of price) per tf, all bars of 6 coins since 2021-08; percentile of live median stops.
import sys, os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boot.py')).read())
import numpy as np, pandas as pd
sd = sys.argv[1]; live = dict(zip(['15m','30m','1h','4h'], map(float, sys.argv[2].split(','))))
T0 = pd.Timestamp('2021-08-01').value
for tf in ['15m','30m','1h','4h']:
    xs=[]; ys=[]
    for c in ['BTC','ETH','SOL','DOGE','LTC','BCH']:
        z=np.load(f'{sd}/sig_{tf}_{c}USD.npz', allow_pickle=False); m=(z['ts']>=T0)&np.isfinite(z['atr'])&(z['atr']>0)
        xs.append(200*z['atr'][m]/z['c'][m]); ys.append(pd.to_datetime(z['ts'][m]).year)
    x=np.concatenate(xs); y=np.concatenate(ys); med=np.median(x)
    pct=100*(x<live[tf]).mean()
    extra = {int(k): round(float(np.median(x[y==k])),3) for k in np.unique(y)} if tf=='15m' else ''
    print(tf, 'live', live[tf], '5y median', round(med,3), 'pctile', round(pct,1), 'costR14bp live/5y', round(0.14/live[tf],3), round(0.14/med,3), 'share stop>=1.4%', round((x>=1.4).mean(),3), extra)
