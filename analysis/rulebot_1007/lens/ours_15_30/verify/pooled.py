import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
from boot import cboot
A=pd.read_csv('my_es_rows_all.csv')
T=A[A.status=='TRADED'].copy()
out=[]
for tf in ['15m','30m']:
    for sel in ['ALL','v3a','v3b','v4','LATER']:
        g=T[T.tf==tf]
        if sel=='LATER': g=g[g.rn!='v3a']
        elif sel!='ALL': g=g[g.rn==sel]
        r4=cboot(g,'R','blk4'); rD=cboot(g,'R','blkD')
        # mark-inclusive (v3b/v4 only have mark_R)
        out.append(dict(tf=tf,sel=sel,n=len(g),mean=g.R.mean(),win=100*(g.R>0).mean(),lo4=r4['lo'],hi4=r4['hi'],ncl4=r4['ncl'],loD=rD['lo'],hiD=rD['hi'],nclD=rD['ncl']))
P=pd.DataFrame(out); print(P.round(4).to_string())
# mark-inclusive sensitivity v3b/v4
U=A[(A.rn!='v3a')]
for tf in ['15m','30m']:
    g=U[U.tf==tf]
    y=np.where(g.status=='TRADED',g.R,g.mark_R)
    print(tf,'later traded-only',round(g[g.status=='TRADED'].R.mean(),4),'incl unresolved at mark',round(np.nanmean(y),4),'unres n',(g.status=='UNRESOLVED').sum(),'unres mean mark_R',round(g[g.status=='UNRESOLVED'].mark_R.mean(),4))
