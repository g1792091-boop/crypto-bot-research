import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
from scipy import stats
A=pd.read_csv('my_es_rows_all.csv'); T=A[A.status=='TRADED'].copy()
def clt(g,col,blk):
    cs=g.groupby(blk)[col].agg(['sum','count']); G=len(cs); m=g[col].mean()
    u=cs['sum']-m*cs['count']; se=np.sqrt((u**2).sum()/(g[col].count()**2)*G/(G-1))
    tq=stats.t.ppf(0.975,G-1)
    return m,m-tq*se,m+tq*se,G
for tf in ['15m','30m']:
    for sel in ['ALL','LATER']:
        g=T[T.tf==tf]
        if sel=='LATER': g=g[g.rn!='v3a']
        for blk in ['blk4','blkD']:
            print(tf,sel,blk,'mean %.3f CI [%.3f,%.3f] G %d'%clt(g,'R',blk))
