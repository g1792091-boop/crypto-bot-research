import sys, site; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
V=pd.read_csv('vr_signals.csv'); V=V[V.base_st.isin(['TRADED','OPEN'])].copy()
V['rs']=V.run.map({'run-20261005T183457Z':'v3b','current':'v4'})
G=pd.read_csv(sys.argv[1]); 
rows=[]
for (kind,tf),g in V[V.kind!='random'].groupby(['kind','timeframe']):
    R=g.base_R.values; mfe=g.base_mfe.values; ex=g.base_ex.values; cost=g.base_cost.fillna(g.base_cost.median()).values
    lose=R<0; dead=lose&(mfe<0.2); gb=(mfe>=0.5)&lose
    ub_gb=np.where(gb,-R,0).sum()/len(g); rc=-0.5-cost; ub_dead=np.where(dead&(R<rc),rc-R,0).sum()/len(g)
    half=(mfe>=1)&(R>=0)&(R<0.5*mfe); ub_half=np.where(half,0.5*mfe-R,0).sum()/len(g)
    rows.append(dict(kind=kind,tf=tf,n=len(g),gb05_SL=((mfe>=0.5)&(ex=='SL')).mean(),gb10_SL=((mfe>=1)&(ex=='SL')).mean(),
      dead_of_losers=dead.sum()/lose.sum(),ub_gb=ub_gb,ub_dead=ub_dead,ub_half=ub_half,ub_gb_dead=ub_gb+ub_dead,ub_sum=ub_gb+ub_dead+ub_half,
      oracle=np.maximum(mfe-cost-R,0).mean(), reach1R=(mfe>=1).mean()))
print(pd.DataFrame(rows).round(3).to_string())
print(G[(G.src=='signals')&(G.run=='ALL')&G.kind.isin(['strategy','ds200'])][['kind','tf','n','share_gb05_SL','ub_breakeven_gb_R','ub_cut_dead_R','ub_half_mfe_R','ub_sum_R','oracle_exit_R']].round(3).to_string())
print(G[(G.src=='trades')&(G.run=='ALL')&G.kind.isin(['strategy','ds200'])&(G.tf=='15m')][['kind','tf','n','share_gb05_SL']].round(3).to_string())
