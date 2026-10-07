import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
from boot import cboot
X=pd.read_csv('my_levreplay.csv')
A=pd.read_csv('my_es_rows_all.csv'); L=A[(A.rn!='v3a')&(A.status=='TRADED')][['run','strategy','tf','symbol','bar_close','R','lev','sf']].rename(columns={'R':'R_live','lev':'lev_live','sf':'sf_live'})
H=3600000
for tf in ['15m','30m']:
    for v in X.variant.unique():
        g=X[(X.tf==tf)&(X.variant==v)]
        sized=g.status.isin(['TRADED','UNRESOLVED']).mean()
        t=g[g.status=='TRADED']
        m=t.merge(L,on=['run','strategy','tf','symbol','bar_close'])
        m['d']=m.R-m.R_live; m['blk4']=m.run+'|'+(m.bar_close//(4*H)).astype(str)
        b=cboot(m,'d','blk4')
        print(tf,v,'signals',len(g),'sized %.3f'%sized,'traded',len(t),'unres',(g.status=='UNRESOLVED').sum(),'meanR %.3f'%t.R.mean(),'paired n',len(m),'diff %.3f [%.3f,%.3f]'%(m.d.mean(),b['lo'],b['hi']), 'live R on same %.3f'%m.R_live.mean(), 'median sf sized %.4f'%t.sf.median())
# lev50 sized subset: sf distribution vs all
g=X[(X.variant=='lev50m50')&(X.tf=='15m')]
print('15m all-signal median sf (lev10 run)', X[(X.variant=='lev10')&(X.tf=='15m')&(X.status=='TRADED')].sf.median())
