import sys
exec(open('vb.py').read())
import pandas as pd, numpy as np, json
EXP=sys.argv[1]
d=pd.read_csv(f'{EXP}/current/d3_shadows.csv'); d=d[d.kind=='limit'].copy()
d['bar_close']=d.key.str.split('|').str[3].astype('int64')
r=pd.read_csv('out/a2_replay_rows.csv'); r=r[(r.run=='current')&(r.status=='TRADED')]
r['bar_close']=r.bar_close.astype('int64')
j=d.merge(r[['account_id','symbol','bar_close','k2','timeframe','Rn','roe','margin','risk','gross_R']],on=['account_id','symbol','bar_close'],how='inner',suffixes=('_lim',''))
print('limit rows',len(d),'joined',len(j),'resolved share',d.resolved.mean())
j=j[j.resolved==1]
j['R_lim']=np.where(j.filled==1, j.roe_lim*j.margin/j.risk, 0.0)
j['diff']=j.R_lim-j.Rn
j['cl']=j.bar_close//3600000
def boot(v,c,B=4000):
    v=np.asarray(v);c=np.asarray(c);u,inv=np.unique(c,return_inverse=True);S=np.bincount(inv,weights=v);N=np.bincount(inv)
    d=np.random.default_rng(3).integers(0,len(u),(B,len(u)));m=S[d].sum(1)/N[d].sum(1);return f'[{np.percentile(m,2.5):+.3f},{np.percentile(m,97.5):+.3f}]'
out=[]
for (k,tf),g in j.groupby(['k2','timeframe']):
    f=g[g.filled==1]; mi=g[g.filled==0]
    out.append(dict(k=k,tf=tf,n=len(g),fill=g.filled.mean(),missed_mkt_R=mi.Rn.mean(),missed_win=(mi.Rn>0).mean(),fill_improve=(f.R_lim-f.Rn).mean(),
        net_vs_mkt=g['diff'].mean(),ci=boot(g['diff'],g.cl),R_lim=g.R_lim.mean(),R_mkt=g.Rn.mean()))
print(pd.DataFrame(out).round(3).to_string())
g=j[j.k2.isin(['core36','ds200'])]
print('pooled core+ds 15m-4h', round(g['diff'].mean(),3), boot(g['diff'],g.cl), 'n',len(g))
