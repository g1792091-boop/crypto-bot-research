import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
from scipy import stats
A=pd.read_csv('my_es_rows_all.csv'); T=A[A.status=='TRADED'].copy()
grp=T.groupby(['run','tf','side']).R.agg(['sum','count']).to_dict('index'); own=T.groupby(['strategy','run','tf','side']).R.agg(['sum','count']).to_dict('index')
T['ex']=[r.R-(grp[(r.run,r.tf,r.side)]['sum']-own[(r.strategy,r.run,r.tf,r.side)]['sum'])/(grp[(r.run,r.tf,r.side)]['count']-own[(r.strategy,r.run,r.tf,r.side)]['count']) for r in T.itertuples()]
def clt(g,col,blk):
    cs=g.groupby(blk)[col].agg(['sum','count']); G=len(cs); m=g[col].mean()
    u=cs['sum']-m*cs['count']; V=(u**2).sum()/(g[col].count()**2)*G/(G-1)
    t=m/np.sqrt(V); return m,t,G,stats.t.sf(t,G-1)
for st,tf in [('N10_HA_PSAR','30m'),('N10_HA_PSAR','15m'),('N13_3OUTSIDE','15m')]:
    g=T[(T.strategy==st)&(T.tf==tf)]
    for blk in ['blk4','blkD']:
        print(st,tf,blk,'ex mean %.3f t %.2f clusters %d one-sided p %.4f'%clt(g,'ex',blk))
        print('   raw R mean %.3f t %.2f clusters %d p %.4f'%clt(g,'R',blk))
