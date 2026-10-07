import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
E, O = sys.argv[1:3]
d = pd.read_csv(E + '/run-20261005T014624Z/d3_shadows.csv')
s = d[d.kind == 'skipped'].copy()
s['strategy'] = s.account_id.str.split('@').str[0]
print(pd.crosstab(s.resolved, s.roe.isna()))
print(s[s.resolved == 0].exit_reason.value_counts(dropna=False).head())
print(s[s.resolved == 0].groupby('timeframe').roe.describe())
print(s.groupby(['timeframe', 'resolved']).size().unstack())
print('dup keys', s.key.duplicated().sum())
RP = pd.read_csv(O + '/replay_signals.csv', low_memory=False)
r = RP[RP.kind == 'strategy']
print(r.groupby(['run', 'timeframe', 'status']).size().unstack(fill_value=0))
print('dup sig per account', r.duplicated(['run', 'account_id', 'sig_id']).sum(), r.duplicated(['run','strategy','timeframe','symbol','bar_close']).sum())
