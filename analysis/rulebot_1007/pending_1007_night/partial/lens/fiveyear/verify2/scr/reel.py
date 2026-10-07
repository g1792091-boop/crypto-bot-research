import sys; sys.path.append('/root/.local/lib/python3.11/site-packages')
import pandas as pd, numpy as np
rt = pd.read_csv(sys.argv[1]); te = pd.read_csv(sys.argv[2]); sh = pd.read_csv(sys.argv[3])
print(rt.columns.tolist()); print(rt['split'].value_counts())
x = rt[rt.split.isin(['is','oos'])]
print('n', len(x), 'per day', len(x)/((pd.Timestamp('2026-09-30')-pd.Timestamp('2021-08-01')).days), 'net mean %', 100*x.net.mean(), 'gross IS %', 100*x[x.split=='is'].gross.mean(), 'gross oos %', 100*x[x.split=='oos'].gross.mean(), 'r_net', x.r_net.mean(), 'win', (x.net>0).mean())
print('all splits n', len(rt), rt.groupby('split').net.mean()*100)
lr = te[te.kind=='reel']; print('live reel trades', len(lr), 'R', lr.R.mean(), 'win', (lr.pnl>0).mean(), 'ret%', 100*lr.roe_per_lev.mean(), lr.leverage.value_counts().to_dict() if 'leverage' in lr else '')
s = sh[(sh.kind=='skipped') & sh.account_id.astype(str).str.startswith('REEL')]
print('reel skipped shadows rows', len(s), 'unique keys', s.key.nunique(), 'roe notnull', s.drop_duplicates('key').roe.notna().sum())
s = s.drop_duplicates('key')
allret = np.r_[lr.roe_per_lev.to_numpy(float), (s.roe/30).dropna().to_numpy(float)]
print('all n', len(allret), 'mean %', 100*allret.mean())
# windows: my own approach: random 1.5034-day windows over the 5y trade stream, mean net per trade
ts = pd.to_datetime(x.entry_ts).astype('int64').to_numpy(); o=np.argsort(ts); ts=ts[o]; v=x.net.to_numpy(float)[o]
cs=np.r_[0,np.cumsum(v)]; rng=np.random.default_rng(5); L=1.5034722*86400e9
st=rng.uniform(ts[0], ts[-1]-L, 20000); i0=np.searchsorted(ts,st); i1=np.searchsorted(ts,st+L); n=i1-i0; m=(cs[i1]-cs[i0])/np.where(n>0,n,1)
m=m[n>0]; print('window p5,p50,p95 %', np.percentile(m,[5,50,95])*100, 'pct of live all', (m<allret.mean()).mean(), 'pct of live trades only', (m<lr.roe_per_lev.mean()).mean())
