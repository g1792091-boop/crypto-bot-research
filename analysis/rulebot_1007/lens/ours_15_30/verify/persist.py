import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np
from scipy.stats import spearmanr
C=pd.read_csv('my_cells.csv')
a=C[(C.n_v3a>=10)&(C.n_later>=10)]
print('v3a vs later n>=10 both:',len(a),spearmanr(a.m_v3a,a.m_later))
print('v3a>0:',a[a.m_v3a>0][['strategy','tf','n_v3a','m_v3a','n_later','m_later']].round(3).to_string())
b=C[(C.n_v3b>=10)&(C.n_v4>=10)]; print('v3b vs v4:',len(b),spearmanr(b.m_v3b,b.m_v4))
c=C[(C.n_v3a>=5)&(C.n_v3b>=5)&(C.n_v4>=5)]
print('n>=5 all runs:',len(c),' all pos',((c.m_v3a>0)&(c.m_v3b>0)&(c.m_v4>0)).sum(),' all neg',((c.m_v3a<0)&(c.m_v3b<0)&(c.m_v4<0)).sum())
# expected all-negative count if independent with p_neg per run = share negative
for r in ['v3a','v3b','v4']:
    print(r,'share neg',(c[f'm_{r}']<0).mean().round(3))
pn=np.prod([(c[f'm_{r}']<0).mean() for r in ['v3a','v3b','v4']]); print('expected all-neg under independence',round(pn*len(c),1))
# v3a vs v4 only
d=C[(C.n_v3a>=10)&(C.n_v4>=10)]; print('v3a vs v4:',len(d),spearmanr(d.m_v3a,d.m_v4))
# pooled market: per-run pooled means
