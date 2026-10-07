import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np, json
E=sys.argv[1]; R='run-20261005T014624Z'
d=pd.read_csv(f'{E}/{R}/d3_shadows.csv'); b=d[d.kind=='base'].copy(); b['bc']=b.key.str.split('|').str[-1].astype('int64')
b['lev']=b.data.map(lambda s: json.loads(s)['leverage']); b['alev']=b.data.map(lambda s: json.loads(s)['actual_leverage']); b['aroe']=b.data.map(lambda s: json.loads(s)['actual_roe'])
t=pd.read_csv(f'{E}/{R}/trades.csv'); t['bc']=t.signal_ts+1; t['R']=t.pnl/(t.qty*(t.entry_price-t.stop_initial).abs()); t['sf']=(t.entry_price-t.stop_initial).abs()/t.entry_price
m=b.merge(t[['account_id','symbol','bc','R','sf','roe','leverage']],on=['account_id','symbol','bc'])
same=m[(m.lev==m.alev)&((m.roe-m.aroe).abs()<1e-9)]
same=same.assign(Rc=same['roe_x']/(same.lev*same.sf)) if 'roe_x' in same else same
print(len(b),len(m),len(same))
x=same.roe_x/(same.lev*same.sf)-same.R
print('median abs',np.median(np.abs(x)),'p95',np.percentile(np.abs(x),95))
