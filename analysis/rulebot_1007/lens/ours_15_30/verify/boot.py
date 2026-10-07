import numpy as np, pandas as pd, zlib
def cboot(df, col='R', blk='blk4', B=10000, seed=1, strat='run'):
    """cluster bootstrap of the pooled mean; clusters resampled within strata (run). returns mean, lo, hi, p_le0, p_ge0, ncl"""
    x=df[[col,blk,strat]].dropna()
    if len(x)<2: return dict(mean=x[col].mean() if len(x) else np.nan, lo=np.nan, hi=np.nan, p_le0=np.nan, p_ge0=np.nan, ncl=x[blk].nunique(), n=len(x))
    cs=x.groupby(blk).agg(s=(col,'sum'),c=(col,'size'),st=(strat,'first'))
    rg=np.random.default_rng(seed)
    ts=np.zeros(B); tc=np.zeros(B)
    for _,cr in cs.groupby('st'):
        k=len(cr); idx=rg.integers(0,k,size=(B,k))
        ts+=cr.s.to_numpy()[idx].sum(1); tc+=cr.c.to_numpy()[idx].sum(1)
    m=ts/tc
    lo,hi=np.percentile(m,[2.5,97.5])
    return dict(mean=x[col].mean(), lo=lo, hi=hi, p_le0=(1+np.sum(m<=0))/(B+1), p_ge0=(1+np.sum(m>=0))/(B+1), ncl=len(cs), n=len(x))
def bh(p):
    p=np.asarray(p,float); n=len(p); o=np.argsort(p)
    q=np.empty(n); q[o]=np.minimum.accumulate((p[o]*n/np.arange(1,n+1))[::-1])[::-1]
    return np.minimum(q,1)
