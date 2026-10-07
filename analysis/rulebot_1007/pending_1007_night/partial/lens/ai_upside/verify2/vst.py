import sys, site; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
V=pd.read_csv(sys.argv[1]); out=sys.argv[2]
V=V[V.base_st.isin(['TRADED','OPEN'])].copy()
V['PART1_R']=0.5*(V.base_R+V.TP1_R)
V['rs']=V.run.map({'run-20261005T183457Z':'v3b','current':'v4'})
TFM={'15m':15,'30m':30,'1h':60,'4h':240}
rng=np.random.default_rng(7)
def bh(p):
    p=np.asarray(p,float); m=len(p); o=np.argsort(p); r=p[o]*m/np.arange(1,m+1); r=np.minimum.accumulate(r[::-1])[::-1]; q=np.empty(m); q[o]=np.minimum(r,1); return q
def test(d,cl,B=10000):
    u,inv=np.unique(cl,return_inverse=True); s=np.bincount(inv,weights=d); c=np.bincount(inv); n=len(d); obs=d.mean()
    null=rng.choice([-1.,1.],size=(B,len(u)))@s/n
    p2=(np.sum(np.abs(null)>=abs(obs)-1e-15)+1)/(B+1)
    idx=rng.integers(0,len(u),size=(2000,len(u))); bs=s[idx].sum(1)/c[idx].sum(1)
    return obs,p2,np.percentile(bs,2.5),np.percentile(bs,97.5),len(u)
rules=['CUT05','CUT05C','NP4','NP8','BE05','TP1','PART1','DEEP4','OPP','OPPH']
rows=[]
for kind in ['strategy','ds200']:
  for tf in ['15m','30m','1h','4h']:
    g=V[(V.kind==kind)&(V.timeframe==tf)]
    if len(g)<10: continue
    for r in rules:
      d=(g[f'{r}_R']-g.base_R).to_numpy(); ok=np.isfinite(d)
      row=dict(kind=kind,tf=tf,rule=r,n=int(ok.sum()),base=g.base_R.mean())
      for rs in ['v3b','v4']:
        gg=g[g.rs==rs]; row[f'n_{rs}']=len(gg); row[f'd_{rs}']=(gg[f'{r}_R']-gg.base_R).mean() if len(gg) else np.nan
      for lab,hrs in [('1h',None),('4h',240),('12h',720)]:
        blk=np.maximum(TFM[tf],60) if hrs is None else hrs
        cl=(g.rs+'|'+(g.bar_close//(blk*60000)).astype(str)).to_numpy()[ok]
        obs,p2,lo,hi,k=test(d[ok],cl)
        row.update({f'p_{lab}':p2,f'lo_{lab}':lo,f'hi_{lab}':hi,f'k_{lab}':k})
      row['mean']=obs
      # resolved only
      gr=g[g.base_st=='TRADED']; row['mean_resolved']=(gr[f'{r}_R']-gr.base_R).mean()
      rows.append(row)
S=pd.DataFrame(rows)
pre=S.rule.isin(['CUT05','NP4','NP8','BE05','TP1','PART1','OPP','OPPH'])
for lab in ['1h','4h','12h']:
    S.loc[pre,f'q_{lab}']=bh(S.loc[pre,f'p_{lab}'])
S.to_csv(out,index=False)
pd.set_option('display.width',250); pd.set_option('display.max_rows',200)
print(S[['kind','tf','rule','n','base','mean','d_v3b','d_v4','lo_1h','hi_1h','p_1h','q_1h','k_1h','p_4h','k_4h','lo_12h','hi_12h','p_12h','k_12h','q_12h','mean_resolved']].round(3).to_string())
