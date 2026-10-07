import sys, site; sys.path.append(site.getusersitepackages())
import sys, pandas as pd, numpy as np
V=pd.read_csv(sys.argv[1]); RP=pd.read_csv(sys.argv[2]); T=pd.read_csv(sys.argv[3])
print(V.groupby(['run','kind']).size())
print(V['base_st'].value_counts())
m=V.merge(RP[['run','sig_id','status','R','mark_R']],on=['run','sig_id'],how='left')
tr=m[m.base_st=='TRADED']; print('traded parity n',len(tr),'maxdiff',np.nanmax(np.abs(tr.base_R-tr.R)), 'status mismatch',(tr.status!='TRADED').sum())
op=m[m.base_st=='OPEN']; print('open parity n',len(op),'maxdiff',np.nanmax(np.abs(op.base_R-op.mark_R)))
m2=V.merge(T[['run','sig_id','base_R']+[c for c in T.columns if c.endswith('_R') and c.split('_')[0] in ('CUT05','NP4','NP8','BE05','TP1','OPP','OPPH')]],on=['run','sig_id'],how='inner',suffixes=('','_them'))
print('merged with theirs',len(m2))
for r in ['CUT05','NP4','NP8','BE05','TP1','OPP','OPPH']:
    a=m2[f'{r}_R']; b=m2[f'{r}_R_them']; ok=a.notna()&b.notna()
    print(r,'n',ok.sum(),'n |diff|>1e-6',(np.abs(a-b)[ok]>1e-6).sum(),'mean diff mine-theirs',(a-b)[ok].mean())
