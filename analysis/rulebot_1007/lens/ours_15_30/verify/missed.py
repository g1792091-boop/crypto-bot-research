import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
from scipy.stats import spearmanr, pearsonr
A=pd.read_csv('my_es_rows_all.csv'); T=A[A.status=='TRADED']
# within-run long vs short
print(T.groupby(['tf','rn','side']).R.agg(['size','mean']).round(3).unstack('side'))
# cell x run: mean R vs long share
g=T.groupby(['strategy','tf','rn']).agg(n=('R','size'),R=('R','mean'),ls=('side',lambda s:(s>0).mean())).reset_index()
g=g[g.n>=10]
for rn in ['v3a','v3b','v4']:
    x=g[g.rn==rn]; r=pearsonr(x.ls,x.R); print(rn,'cells',len(x),'pearson r(long share, mean R) %.2f p %.3g R2 %.2f'%(r[0],r[1],r[0]**2))
# duplicates: same symbol, tf, bar_close, side across strategies
k=T.groupby(['run','tf','symbol','bar_close','side']).strategy.transform('size')
print('share of traded every-signal rows sharing symbol/bar/side with >=1 other strategy: %.3f'%(k>1).mean(), ' mean group size %.2f'%k.mean())
print('unique (run,tf,symbol,bar,side) events:',T.groupby(['run','tf','symbol','bar_close','side']).ngroups,'rows',len(T))
# planned exits baseline: lev20 variant traded mean by tf (my replay) incl unresolved
X=pd.read_csv('my_levreplay.csv')
for tf in ['15m','30m']:
    x=X[(X.variant=='lev20m20')&(X.tf==tf)&(X.status=='TRADED')]
    print(tf,'lev20 (ROE ladder at 20x = planned R ladder) mean R %.3f n %d'%(x.R.mean(),len(x)))
