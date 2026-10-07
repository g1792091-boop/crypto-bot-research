import sys,site; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
D=pd.read_csv('vsw.csv').rename(columns={'eq':'equity'}); D['rs']=D.run.map({'run-20261005T183457Z':'v3b','current':'v4'})
b=D[D.pol=='base']
B=b.set_index(['run','account_id'])
rows=[]
rng=np.random.default_rng(1)
for pol in ['ANY','UNDER','OPP']:
    P=D[D.pol==pol].set_index(['run','account_id']).join(B[['equity','cost','n_trades']],rsuffix='_b')
    P['d']=P.equity-P.equity_b; P['dc']=P.cost-P.cost_b
    for (kind,tf),g in list(P.groupby(['kind','tf']))+[(('core+ds','all'),P[P.kind!='random'])]:
        if kind=='random': continue
        ns=g.n_switch.sum()
        if ns==0: continue
        # account bootstrap of d per switch
        d=g.d.values; n=g.n_switch.values; idx=rng.integers(0,len(g),size=(4000,len(g))); bs=d[idx].sum(1)/np.maximum(n[idx].sum(1),1)
        r=dict(pol=pol,kind=kind,tf=tf,accts=len(g),switches=ns,d_per_sw=g.d.sum()/ns,lo=np.percentile(bs,2.5),hi=np.percentile(bs,97.5),extra_cost_per_sw=g.dc.sum()/ns,gross_per_sw=(g.d.sum()+g.dc.sum())/ns,
               worse=(g.d<-1e-6).mean(),better=(g.d>1e-6).mean())
        for rs in ['v3b','v4']:
            gg=g[g.rs==rs]; n2=gg.n_switch.sum(); r['d_'+rs]=gg.d.sum()/n2 if n2 else np.nan; r['sw_'+rs]=n2
        rows.append(r)
pd.set_option('display.width',250); print(pd.DataFrame(rows).round(2).to_string())
pd.DataFrame(rows).to_csv('vsw_summary.csv',index=False)
