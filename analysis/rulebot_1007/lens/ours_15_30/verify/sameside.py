import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np, zlib
from boot import cboot, bh
A=pd.read_csv('my_es_rows_all.csv'); T=A[A.status=='TRADED'].copy()
grp=T.groupby(['run','tf','side']).R.agg(['sum','count'])
own=T.groupby(['strategy','run','tf','side']).R.agg(['sum','count'])
gs=grp.to_dict('index'); os_=own.to_dict('index')
b=[]
for r in T.itertuples():
    a=gs[(r.run,r.tf,r.side)]; o=os_[(r.strategy,r.run,r.tf,r.side)]
    n=a['count']-o['count']; b.append((a['sum']-o['sum'])/n if n>0 else np.nan)
T['bench']=b; T['ex']=T.R-T.bench
rows=[]
for (st,tf),g in T.groupby(['strategy','tf']):
    bb=cboot(g,'ex','blk4',seed=zlib.crc32(f'{st}{tf}x'.encode()))
    d=dict(strategy=st,tf=tf,n=len(g),ex=g.ex.mean(),lo=bb['lo'],hi=bb['hi'],p=bb['p_le0'],ncl=bb['ncl'])
    for rn in ['v3a','v3b','v4']:
        x=g[g.rn==rn]; d[f'ex_{rn}']=x.ex.mean() if len(x) else np.nan; d[f'n_{rn}']=len(x)
    rows.append(d)
S=pd.DataFrame(rows); t=(S.n>=10)&(S.ncl>=5); S.loc[t,'q']=bh(S.loc[t,'p'])
print('tested',t.sum()); print(S.sort_values('p').head(8).round(3).to_string())
c=S[(S.n_v3a>=5)&(S.n_v3b>=5)&(S.n_v4>=5)]
allpos=c[(c.ex_v3a>0)&(c.ex_v3b>0)&(c.ex_v4>0)]
print('eligible',len(c),'all-runs-positive relative:',allpos[['strategy','tf']].values.tolist())
print(S[S.strategy.isin(['N10_HA_PSAR'])].round(3).to_string())
# N10 30m robustness
g=T[(T.strategy=='N10_HA_PSAR')&(T.tf=='30m')]
cl=g.groupby('blk4').R.sum(); best=cl.idxmax(); print('N10@30m mean %.3f without best 4h %.3f'%(g.R.mean(), g[g.blk4!=best].R.mean()))
dd=g.groupby('blkD').R.sum(); print('without best day %.3f'%g[g.blkD!=dd.idxmax()].R.mean(), ' n blocks',g.blk4.nunique(),'days',g.blkD.nunique())
print('N10@30m stop median %.4f vs 30m all %.4f'%(g.sf.median(), T[T.tf=='30m'].sf.median()))
print('N10@30m by run:',g.groupby('rn').R.agg(['size','mean']).round(3).to_dict())
print('N10@30m exits', g.exit_reason.value_counts().to_dict(), ' unresolved v3a/v3b/v4:', A[(A.strategy=='N10_HA_PSAR')&(A.tf=='30m')&(A.status=='UNRESOLVED')].groupby('rn').size().to_dict())
S.to_csv('my_sameside.csv',index=False)
