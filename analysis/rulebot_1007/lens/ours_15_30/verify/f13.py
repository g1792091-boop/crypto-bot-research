import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
A=pd.read_csv('my_es_rows_all.csv'); T=A[(A.status=='TRADED')]
for tf in ['15m','30m']:
    for rn in ['v3a','v3b','v4']:
        g=T[(T.tf==tf)&(T.rn==rn)]
        print(tf,rn,'n',len(g),'lev',g.lev.value_counts().to_dict(),'median stop %.3f%%'%(100*g.sf.median()),'long share %.3f'%(g.side>0).mean(),'mean R %.3f'%g.R.mean(), 'mean R long %.3f short %.3f'%(g[g.side>0].R.mean(),g[g.side<0].R.mean()))
    g=T[(T.tf==tf)&(T.rn!='v3a')]; print(tf,'later lev',g.lev.value_counts().to_dict())
# v3a: R by leverage
for tf in ['15m','30m']:
    g=T[(T.tf==tf)&(T.rn=='v3a')]
    print(tf, g.groupby('lev').agg(n=('R','size'),R=('R','mean'),sf=('sf','median')).round(4).to_string())
