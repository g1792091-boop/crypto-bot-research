import site,sys; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
V,S=sys.argv[1],sys.argv[2]
v=pd.read_csv(V+'/vsignals.csv')
rp=pd.read_csv(S+'/rb_analyze/out_real/replay_signals.csv')
print(rp.columns.tolist()[:40])
rp=rp[rp.timeframe.isin(['15m','30m','1h','4h'])]
m=v.merge(rp[['run','sig_id','status','R','mark_R','exit_reason']],on=['run','sig_id'],how='left')
print(pd.crosstab(m.base_st,m.status))
t=m[m.base_st=='TRADED']; print('traded maxdiff',(t.base_R-t.R).abs().max(), len(t))
o=m[m.base_st=='OPEN']; print('open maxdiff',(o.base_R-o.mark_R).abs().max(), len(o))
L=pd.read_csv(S+'/lens/ai_upside/out/rules_signals.csv')
mm=v.merge(L,on=['run','sig_id'],how='inner',suffixes=('','_L'))
print('lens rows',len(L),'merged',len(mm))
for r in ['CUT05','NP4','NP8','BE05','BE10','TP1','OPP','OPPH']:
    a=mm[r+'_R']; b=mm[r+'_R_L']
    ok=a.notna()&b.notna()
    d=(a-b)[ok].abs()
    print(r,'n',ok.sum(),'n_diff>1e-9',(d>1e-9).sum(),'max',d.max(), 'na mismatch',(a.notna()!=b.notna()).sum())
