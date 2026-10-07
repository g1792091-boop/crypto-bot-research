import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
E=sys.argv[1]
A=pd.read_csv('my_es_rows_all.csv')
v=A[A.rn=='v3a']
d=pd.read_csv(f'{E}/run-20261005T014624Z/d3_shadows.csv'); sk=d[d.kind=='skipped'].copy(); sk['bc']=sk.key.str.split('|').str[-1].astype('int64')
# day end per shadow day = max bc of that day
H=3600000
for day,g in sk.groupby('day'):
    u=g[g.resolved==0]
    print(day,'n',len(g),'unres',len(u),'unres bc KST range',pd.to_datetime(u.bc.min()+9*H,unit='ms') if len(u) else None,pd.to_datetime(u.bc.max()+9*H,unit='ms') if len(u) else None, 'day bc max', pd.to_datetime(g.bc.max()+9*H,unit='ms'))
    print('   unresolved by tf', u.timeframe.value_counts().to_dict())
# later runs: mean R by hold time bucket (15m/30m)
L=A[(A.rn!='v3a')&(A.status=='TRADED')]
L['hb']=pd.cut(L.hold_min,[0,60,180,360,720,1e9])
print(L.groupby(['tf','hb']).R.agg(['size','mean']).round(3))
# per-cell unresolved share
U=A.groupby(['strategy','tf']).apply(lambda g: pd.Series({'n':len(g),'unres':(g.status=='UNRESOLVED').sum()}),include_groups=False)
U['share']=U.unres/U.n
print(U[U.n>=20].sort_values('share',ascending=False).head(10))
print('N10 30m', U.loc[('N10_HA_PSAR','30m')].to_dict())
