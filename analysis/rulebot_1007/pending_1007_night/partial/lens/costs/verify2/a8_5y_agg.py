import sys
exec(open('vb.py').read())
import pandas as pd, numpy as np
D=pd.read_csv(sys.argv[1])
D['wk']=(pd.to_datetime(D.ts)-pd.to_timedelta(pd.to_datetime(D.ts).dt.dayofweek,unit='D')).dt.normalize()
D['gR']=D.g/D.stop_frac; D['gRf']=D.g_flip/D.stop_frac; D['ex']=(D.gR-D.gRf)/2; D['cf']=(D.gR+D.gRf)/2
D['f4R']=D.f4/D.stop_frac; D['f16R']=D.f16/D.stop_frac
def wb(x,w,B=1000,seed=1):
    x=np.asarray(x,float);ok=np.isfinite(x);x=x[ok];w=np.asarray(w)[ok]
    u,inv=np.unique(w,return_inverse=True);S=np.bincount(inv,weights=x);N=np.bincount(inv)
    d=np.random.default_rng(seed).integers(0,len(u),(B,len(u)));m=S[d].sum(1)/N[d].sum(1)
    return f'[{np.percentile(m,2.5):+.4f},{np.percentile(m,97.5):+.4f}]'
rows=[]
for tf,g in D.groupby('tf'):
    rows.append(dict(tf=tf,n=len(g),weeks=g.wk.nunique(),gross_bp=1e4*g.g.mean(),gross_R=g.gR.mean(),ci=wb(g.gR,g.wk),excess_R=g.ex.mean(),ci_ex=wb(g.ex,g.wk),
      coinflip_R=g.cf.mean(),f4R=g.f4R.mean(),ci_f4=wb(g.f4R,g.wk),f16R=g.f16R.mean(),ci_f16=wb(g.f16R,g.wk),med_stop_pct=100*g.stop_frac.median(),
      unres=(g.reason==3).mean(),net_bp_approx=1e4*g.g.mean()-14))
pd.set_option('display.width',250)
print(pd.DataFrame(rows).round(4).to_string())
# by year, coin, vol quintile at 15m
for tf in ['15m','30m','1h','4h']:
    g=D[D.tf==tf].copy(); g['yr']=pd.to_datetime(g.ts).dt.year
    g['q']=pd.qcut(g.stop_frac,5,labels=False)+1
    print(tf,'year gross bp',(1e4*g.groupby('yr').g.mean()).round(2).to_dict())
    print(tf,'coin gross bp',(1e4*g.groupby('coin').g.mean()).round(2).to_dict())
    print(tf,'volQ gross bp',(1e4*g.groupby('q').g.mean()).round(2).to_dict(),' coinflip R by Q',g.groupby('q').cf.mean().round(4).to_dict())
    print(tf,'period gross R',g.groupby('period').gR.mean().round(4).to_dict())
D[['tf','strategy','coin','period','wk','g','gR','ex','stop_frac','f4R','f16R']].to_csv('out/a8_slim.csv.gz',index=False)
