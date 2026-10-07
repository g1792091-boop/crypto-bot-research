import sys,site; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
X=sys.argv[1]; A=pd.read_csv(sys.argv[2])
V=pd.read_csv('vr_signals.csv'); V=V[V.base_st.isin(['TRADED','OPEN'])&V.kind.isin(['strategy','ds200'])].copy()
V['rs']=V.run.map({'run-20261005T183457Z':'v3b','current':'v4'})
W=15*60000
out=[]
for run in ['run-20261005T183457Z','current']:
    sg=pd.read_csv(f'{X}/{run}/signal_log.csv'); sg=sg[sg.status=='SUBMITTED']
    acc=pd.read_csv(f'{X}/{run}/accounts.csv').set_index('account_id')['kind']
    sg['kind']=(sg.strategy+'@'+sg.timeframe).map(acc)
    sg=sg[sg.kind.isin(['strategy','ds200'])]
    g=V[V.run==run].copy()
    by={s:d[['id','bar_close','side']].to_numpy() for s,d in sg.groupby('symbol')}
    for leaky in (False,True):
        ns=[];no=[]
        for r in g.itertuples():
            a=by.get(r.symbol); 
            lo=r.bar_close-W; hi=r.bar_close+W if leaky else r.bar_close
            m=(a[:,1]>=lo)&(a[:,1]<=hi)&(a[:,0]!=r.sig_id)
            ns.append(int((a[m,2]==r.side).sum())); no.append(int((a[m,2]==-r.side).sum()))
        g['ns'+('L' if leaky else '')]=ns; g['no'+('L' if leaky else '')]=no
    out.append(g)
V=pd.concat(out)
TFM={'15m':15,'30m':30,'1h':60,'4h':240}
rng=np.random.default_rng(2)
for leaky in ('','L'):
    ns,no=V['ns'+leaky],V['no'+leaky]
    V['grp']=np.where((ns==0)&(no==0),'alone',np.where(ns>no,'agree','conflict'))
    print('LEAKY' if leaky else 'AI-visible')
    for (kind,tf),g in V.groupby(['kind','timeframe']):
        if tf=='4h': continue
        r={k:(len(x),round(x.base_R.mean(),3)) for k,x in g.groupby('grp')}
        a=g[g.grp=='agree']; c=g[g.grp=='conflict']
        byrun={rs:round(gg[gg.grp=='conflict'].base_R.mean()-gg[gg.grp=='agree'].base_R.mean(),3) for rs,gg in g.groupby('rs')}
        # cluster bootstrap of conflict-agree
        gg=g[g.grp.isin(['agree','conflict'])].copy(); gg['cl']=gg.rs+'|'+(gg.bar_close//(max(TFM[tf],60)*60000)).astype(str)
        cls=gg.cl.unique(); grp={c:x for c,x in gg.groupby('cl')}
        bs=[]
        for _ in range(1000):
            s=pd.concat([grp[c] for c in rng.choice(cls,len(cls))]); bs.append(s[s.grp=='conflict'].base_R.mean()-s[s.grp=='agree'].base_R.mean())
        print(' ',kind,tf,r,'conf-agree',round(c.base_R.mean()-a.base_R.mean(),3),'CI',np.round(np.nanpercentile(bs,[2.5,97.5]),2),byrun)
print(A[A.kind.isin(['strategy','ds200'])].round(3).to_string()[:3000])
