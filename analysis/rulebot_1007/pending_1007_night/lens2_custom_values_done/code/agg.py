import sys; sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens2/custom_values/code')
from show import *
import numpy as np
d=pd.read_csv('out_R2/cell_desc.csv'); o=pd.read_csv('out/one_position.csv')
d=d.merge(o[['cell','one_pos_trades_per_week','all_signal_trades_per_week']],on='cell')
d['ratio']=d.all_signal_trades_per_week/d.one_pos_trades_per_week
W={'05':'weeks_needed_0.05','10':'weeks_needed_0.1','20':'weeks_needed_0.2'}
for k,c in W.items(): d['one'+k]=d[c]*d.ratio
def f(x):
    w=x.default_n
    return pd.Series(dict(n=w.sum(), mean_R=(x.default_mean_R*w).sum()/w.sum(), gross=(x.default_gross_R*w).sum()/w.sum(), cost=(x.default_cost_R*w).sum()/w.sum(), tpw=x.trades_per_week.mean(), onepos=x.one_pos_trades_per_week.mean(), all05=x['weeks_needed_0.05'].median(), all10=x['weeks_needed_0.1'].median(), all20=x['weeks_needed_0.2'].median(), one05=x.one05.median(), one10=x.one10.median(), one20=x.one20.median(), deff=x.deff.mean()))
print(d.groupby('tf').apply(f).round(3).to_string())
print(f(d).round(3).to_string())
print(d[['cell','one05','one10','one20','ratio']].round(1).to_string())
ps=pd.read_csv('out_R2/persistence.csv'); print(ps[['spearman_dA_dB','top10A_mean_dA','top10A_mean_dB']].mean(), (ps.top10A_mean_dB>0).sum())
