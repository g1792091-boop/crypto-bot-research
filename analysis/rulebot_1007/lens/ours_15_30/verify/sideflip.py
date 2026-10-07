import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
from boot import cboot
A=pd.read_csv('my_es_rows_all.csv')
P=A[(A.rn!='v3a')&(A.status=='TRADED')&(A.flip_status=='TRADED')&A.flip_R.notna()].copy()
P['h']=0.5*(P.R-P.flip_R)
for tf in ['15m','30m']:
    g=P[P.tf==tf]; b=cboot(g,'h','blk4'); bd=cboot(g,'h','blkD')
    print(tf,'n',len(g),'excess %.4f CI4h [%.3f,%.3f] CIday [%.3f,%.3f] p_le0 %.3f'%(g.h.mean(),b['lo'],b['hi'],bd['lo'],bd['hi'],b['p_le0']))
# drift adjust: benchmark mean h of OTHER strategies' same run x tf x side
grp=P.groupby(['run','tf','side']).h.agg(['sum','count'])
own=P.groupby(['strategy','run','tf','side']).h.agg(['sum','count'])
def bench(r):
    a=grp.loc[(r.run,r.tf,r.side)]; o=own.loc[(r.strategy,r.run,r.tf,r.side)]
    n=a['count']-o['count']; return (a['sum']-o['sum'])/n if n>0 else np.nan
P['bench']=P.apply(bench,axis=1); P['h_adj']=P.h-P.bench
for st,tf in [('N20_EMA9_CHOP','15m'),('N20_EMA9_CHOP','30m'),('N24_DMI','30m'),('OBV_S','30m'),('S4_BB_BBP','15m'),('N10_HA_PSAR','30m'),('N10_HA_PSAR','15m'),('N13_3OUTSIDE','15m'),('N18_VWMA_MACD','30m')]:
    g=P[(P.strategy==st)&(P.tf==tf)]
    b=cboot(g,'h_adj','blk4')
    print(st,tf,'n',len(g),'long share %.2f'%(g.side>0).mean(),'raw %.3f adj %.3f [%.3f,%.3f]'%(g.h.mean(),g.h_adj.mean(),b['lo'],b['hi']))
print(P.groupby(['run','tf','side']).h.agg(['mean','count']).round(3))
