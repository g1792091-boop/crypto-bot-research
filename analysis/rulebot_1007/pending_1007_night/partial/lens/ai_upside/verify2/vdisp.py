import sys, site; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
V=pd.read_csv('vr_signals.csv'); V=V[V.base_st.isin(['TRADED','OPEN'])&V.kind.isin(['strategy','ds200'])].copy()
RP=pd.read_csv(sys.argv[1],usecols=['run','sig_id','stop_frac','entry_price','stop_initial'])
V=V.merge(RP,on=['run','sig_id'],how='left')
sf=(V.entry_price-V.stop_initial).abs()/V.entry_price
V['c']=0.0012/sf
V['rs']=V.run.map({'run-20261005T183457Z':'v3b','current':'v4'})
TFM={'15m':15,'30m':30,'1h':60,'4h':240}
rng=np.random.default_rng(3)
def ci(d,cl):
    u,inv=np.unique(cl,return_inverse=True); s=np.bincount(inv,weights=d); c=np.bincount(inv)
    idx=rng.integers(0,len(u),size=(4000,len(u))); bs=s[idx].sum(1)/c[idx].sum(1)
    null=rng.choice([-1.,1.],size=(4000,len(u)))@s/len(d); p=(np.sum(np.abs(null)>=abs(d.mean()))+1)/4001
    return np.percentile(bs,2.5),np.percentile(bs,97.5),p,len(u)
rows=[]
for k in (1,2,4):
  u=V[f'u{k}']
  for st,m in (('win>=0.3',u>=0.3),('deep<=-0.5',u<=-0.5),('all_open',u.notna())):
    for kind in ('strategy','ds200','both'):
      for tf in ('15m','30m','1h'):
        g=V[m&u.notna()&(V.timeframe==tf)&((V.kind==kind) if kind!='both' else True)]
        if len(g)<5: continue
        d=(g.base_R-(g[f'u{k}']-g.c)).values
        for blk,lab in ((None,'1h'),(240,'4h')):
            b=max(TFM[tf],60) if blk is None else blk
            cl=(g.rs+'|'+(g.bar_close//(b*60000)).astype(str)).values
            lo,hi,p,kk=ci(d,cl)
            if lab=='1h': r=dict(k=k,state=st,kind=kind,tf=tf,n=len(g),hme=d.mean(),lo=lo,hi=hi,p=p,ncl=kk)
            else: r.update(lo4=lo,hi4=hi,p4=p,ncl4=kk)
        for rs in ('v3b','v4'):
            gg=g[g.rs==rs]; r[f'n_{rs}']=len(gg); r[f'hme_{rs}']=(gg.base_R-(gg[f'u{k}']-gg.c)).mean() if len(gg) else np.nan
        rows.append(r)
D=pd.DataFrame(rows); D.to_csv('vdisp.csv',index=False)
pd.set_option('display.width',250); pd.set_option('display.max_rows',300)
q=D[((D.k==2)&(D.state=='win>=0.3')&(D.kind=='strategy'))|((D.k==4)&(D.state=='deep<=-0.5'))|((D.k==2)&(D.state=='all_open')&(D.tf=='15m'))]
print(q.round(3).to_string())
# share of trades open at bar 4 in deep state
for tf in ('30m','1h'):
    g=V[(V.timeframe==tf)]; o=g.u4.notna(); print(tf,'open at 4 bars',o.sum(),'deep share',(g.u4<=-0.5).sum()/o.sum(), 'per signal',(g.u4<=-0.5).mean())
