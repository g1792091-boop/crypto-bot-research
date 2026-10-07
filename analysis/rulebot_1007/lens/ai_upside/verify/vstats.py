import site,sys; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
V=sys.argv[1]
R=pd.read_csv(V+'/vsignals.csv')
R=R[R.base_st.isin(['TRADED','OPEN'])].copy()
R['PART1_R']=0.5*(R.base_R+R.TP1_R)
R['rs']=R.run.map({'run-20261005T183457Z':'v3b','current':'v4'})
H=3600000
def clus(R,hours):
    return R.rs+'|'+(R.bar_close//(hours*H)).astype(str)
rng=np.random.default_rng(1)
def test(d,cl,B=20000):
    u,inv=np.unique(cl,return_inverse=True); s=np.bincount(inv,weights=d); c=np.bincount(inv)
    k=len(u); obs=d.mean()
    sg=rng.choice([-1.,1.],size=(B,k)); null=sg@s/len(d)
    pb=(np.sum(null>=obs-1e-15)+1)/(B+1); p2=(np.sum(np.abs(null)>=abs(obs)-1e-15)+1)/(B+1)
    ix=rng.integers(0,k,size=(4000,k)); bs=s[ix].sum(1)/c[ix].sum(1)
    return k,pb,p2,np.percentile(bs,2.5),np.percentile(bs,97.5)
def bh(p):
    p=np.asarray(p,float); m=len(p); o=np.argsort(p); r=p[o]*m/np.arange(1,m+1); r=np.minimum.accumulate(r[::-1])[::-1]; q=np.empty(m); q[o]=np.minimum(r,1); return q
rows=[]
rules=['BE05','BE10','NP4','NP8','TP1','PART1','CUT05','CUT05i','OPP','OPPH']
for kind in ['strategy','ds200']:
  for tf in ['15m','30m','1h','4h']:
    g=R[(R.kind==kind)&(R.timeframe==tf)]
    for r in rules:
        d=(g[r+'_R']-g.base_R).to_numpy(float)
        row=dict(kind=kind,tf=tf,rule=r,n=len(d),base=g.base_R.mean(),diff=d.mean())
        for rs in ['v3b','v4']:
            gg=g[g.rs==rs]; row['n_'+rs]=len(gg); row['d_'+rs]=(gg[r+'_R']-gg.base_R).mean() if len(gg) else np.nan
        gr=g[g.base_st=='TRADED']; row['diff_resolved']=(gr[r+'_R']-gr.base_R).mean()
        for hrs in [1,4,12]:
            k,pb,p2,lo,hi=test(d,clus(g,hrs).to_numpy())
            row.update({f'k{hrs}':k,f'pb{hrs}':pb,f'p2_{hrs}':p2,f'lo{hrs}':lo,f'hi{hrs}':hi})
        rows.append(row)
T=pd.DataFrame(rows)
fam=~T.rule.isin(['CUT05i'])
for h in [1,4,12]:
    T.loc[fam,f'qb{h}']=bh(T.loc[fam,f'pb{h}']); T.loc[fam,f'q2_{h}']=bh(T.loc[fam,f'p2_{h}'])
T.to_csv(V+'/vrules_stats.csv',index=False)
pd.set_option('display.width',300); pd.set_option('display.max_columns',40); pd.set_option('display.max_rows',200)
cols=['kind','tf','rule','n','n_v3b','n_v4','k1','base','diff','d_v3b','d_v4','diff_resolved','lo1','hi1','pb1','p2_1','qb1','q2_1','k4','p2_4','lo4','hi4','q2_4','p2_12','q2_12']
print(T[cols].round(4).to_string())
