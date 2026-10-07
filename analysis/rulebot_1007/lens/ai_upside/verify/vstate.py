import site,sys; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
V=sys.argv[1]
R=pd.read_csv(V+'/vsignals.csv')
R=R[R.base_st.isin(['TRADED','OPEN'])&R.kind.isin(['strategy','ds200'])].copy()
R['rs']=R.run.map({'run-20261005T183457Z':'v3b','current':'v4'})
H=3600000
rng=np.random.default_rng(5)
def ci(d,cl,B=10000):
    u,inv=np.unique(cl,return_inverse=True); s=np.bincount(inv,weights=d); c=np.bincount(inv); k=len(u)
    if k<3: return k,np.nan,np.nan,np.nan
    ix=rng.integers(0,k,size=(B,k)); bs=s[ix].sum(1)/c[ix].sum(1)
    null=rng.choice([-1.,1.],size=(B,k))@s/len(d); p=(np.sum(np.abs(null)>=abs(d.mean())-1e-15)+1)/(B+1)
    return k,np.percentile(bs,2.5),np.percentile(bs,97.5),p
pd.set_option('display.width',250); pd.set_option('display.max_columns',30)
print('== tradeoff (helped/hurt) ==')
for r in ['BE05','TP1','CUT05','NP4']:
  for kind in ['strategy','ds200']:
    for tf in ['15m','30m','1h']:
        g=R[(R.kind==kind)&(R.timeframe==tf)]; d=g[r+'_R']-g.base_R
        he=d>1e-9; hu=d< -1e-9
        be=(-d[hu].mean())/(d[he].mean()-d[hu].mean())
        print(r,kind,tf,'n',len(g),'helped',he.sum(),round(d[he].mean(),3),'hurt',hu.sum(),round(d[hu].mean(),3),'BEprec',round(be,3),'actual',round(he.sum()/(he.sum()+hu.sum()),3),'net',round(d.mean(),4))
print('== disposition: state at k bars; hold (base_R) - exit now (p_nowk, exact net incl funding) ==')
rows=[]
for k in [1,2,4]:
  for st,f in [('win>=0.3',lambda x: x>=0.3),('deep<=-0.5',lambda x: x<=-0.5)]:
    for kind in ['strategy','ds200','both']:
      for tf in ['15m','30m','1h']:
        g=R[(R.timeframe==tf)&((R.kind==kind) if kind!='both' else True)]
        g=g[g[f'p_gross{k}'].notna()]
        g=g[f(g[f'p_gross{k}'])]
        if len(g)<5: continue
        d=(g.base_R-g[f'p_now{k}']).to_numpy(float)
        for ch in [1,4]:
            cl=(g.rs+'|'+(g.bar_close//(ch*H)).astype(str)).to_numpy()
            kk,lo,hi,p=ci(d,cl)
            if ch==1: row=dict(k=k,state=st,kind=kind,tf=tf,n=len(g),hme=d.mean(),k1=kk,lo1=lo,hi1=hi,p1=p)
            else: row.update(k4=kk,lo4=lo,hi4=hi,p4=p)
        for rs in ['v3b','v4']:
            gg=g[g.rs==rs]; row['n_'+rs]=len(gg); row['hme_'+rs]=(gg.base_R-gg[f'p_now{k}']).mean() if len(gg) else np.nan
        # share of open-at-k trades in this state
        g0=R[(R.timeframe==tf)&((R.kind==kind) if kind!='both' else True)&R[f'p_gross{k}'].notna()]
        row['share_of_open']=len(g)/len(g0); row['share_of_signals']=len(g)/len(R[(R.timeframe==tf)&((R.kind==kind) if kind!='both' else True)])
        rows.append(row)
D=pd.DataFrame(rows); D.to_csv(V+'/vdisposition.csv',index=False)
print(D.round(3).to_string())
