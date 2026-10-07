import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
from scipy import stats
A=pd.read_csv('my_es_rows_all.csv'); T=A[A.status=='TRADED']
span=sum((g.bar_close.max()-g.bar_close.min())/86400000 for _,g in T.groupby('run')); print('span days',round(span,2))
def se(g,blk):
    cs=g.groupby(blk).R.agg(['sum','count']); G=len(cs); m=g.R.mean(); u=cs['sum']-m*cs['count']
    return np.sqrt((u**2).sum()/len(g)**2*G/(G-1)), G
for st,tf in [('N04_ST_KLINGER','15m'),('N10_HA_PSAR','30m'),('N17_KC_RSI','15m'),('S4_BB_BBP','15m')]:
    g=T[(T.strategy==st)&(T.tf==tf)]
    for blk in ['blk4','blkD']:
        s,G=se(g,blk); hw=1.96*s
        print(st,tf,blk,'SE %.3f hw(1.96) %.3f G %d days for +-0.1: %.1f'%(s,hw,G,span*(hw/0.1)**2))
