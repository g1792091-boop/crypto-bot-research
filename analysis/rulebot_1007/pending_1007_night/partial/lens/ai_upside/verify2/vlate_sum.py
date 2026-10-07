import sys,site; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
L=pd.read_csv('vlate.csv'); L['rs']=L.run.map({'run-20261005T183457Z':'v3b','current':'v4'})
TFM={'15m':15,'30m':30,'1h':60,'4h':240}
num=lambda s: pd.to_numeric(s,errors='coerce')
rng=np.random.default_rng(11)
def ci(d,cl):
    u,inv=np.unique(cl,return_inverse=True); s=np.bincount(inv,weights=d); c=np.bincount(inv)
    idx=rng.integers(0,len(u),size=(4000,len(u))); bs=s[idx].sum(1)/c[idx].sum(1); return np.percentile(bs,2.5),np.percentile(bs,97.5)
rows=[]
for (kind,tf),g in L[L.kind.isin(['strategy','ds200'])].groupby(['kind','timeframe']):
    cl=(g.rs+'|'+(g.bar_close//(max(TFM[tf],60)*60000)).astype(str)).values
    for a,b in [('late1','base'),('late2','base'),('late4','base'),('lev30','lev20'),('lev40','lev30'),('lev50','lev40')]:
        x=num(g[a]); y=num(g[b]); ok=(x.notna()&y.notna()).values
        if ok.sum()<10: continue
        d=(x-y).values[ok]; lo,hi=ci(d,cl[ok])
        r=dict(kind=kind,tf=tf,cmp=f'{a}-{b}',n=ok.sum(),mean=d.mean(),lo=lo,hi=hi)
        for rs in ['v3b','v4']:
            m=ok&(g.rs==rs).values; r[rs]=(x-y).values[m].mean() if m.sum() else np.nan
        rows.append(r)
    for lev in [20,30,40,50]:
        rows.append(dict(kind=kind,tf=tf,cmp=f'feasible lev{lev}',n=(g[f'lev{lev}']!='REJ').sum(),mean=(g[f'lev{lev}']=='REJ').mean()))
pd.set_option('display.width',200); pd.set_option('display.max_rows',200)
print(pd.DataFrame(rows).round(3).to_string())
