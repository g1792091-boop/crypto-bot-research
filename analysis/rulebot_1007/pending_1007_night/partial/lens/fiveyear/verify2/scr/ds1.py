import sys; sys.path.append('/root/.local/lib/python3.11/site-packages')
import pandas as pd, numpy as np
d=pd.read_csv(sys.argv[1])
print(d['exit'].value_counts())
for (tf,x),g in d.groupby(['tf','exit']):
    n=g.is_n+g.cf_n
    w=(g.is_mean_pct*g.is_n+g.cf_mean_pct*g.cf_n).sum()/n.sum()
    gw=(g.is_gross_mean_pct*g.is_n+g.cf_gross_mean_pct*g.cf_n).sum()/n.sum()
    pos_both=((g.is_mean_pct>0)&(g.cf_mean_pct>0)).sum()
    print(tf,x,'w_mean_net%',round(w,4),'w_gross%',round(gw,4),'entries',len(g),'pos both IS&CF',pos_both, 'trades/day', round(n.sum()/1886,1))
s=d[d.stage1]
print(s[['tf','entry','exit','is_mean_pct','cf_mean_pct','pre_mean_pct','stage2','stage3','candidate']])
print('any candidate', d.candidate.any(), 'weak', d.weak_candidate.sum(), 'cand20x', d.candidate_20x.sum())
# DS entries positive in both halves (either exit) at 15m/30m/1h
x=d[(d.tf.isin(['15m','30m','1h']))&(d.is_mean_pct>0)&(d.cf_mean_pct>0)]
print('pos both halves at 15m-1h (prereg):'); print(x[['tf','entry','exit','is_mean_pct','cf_mean_pct','is_n','cf_n']])
