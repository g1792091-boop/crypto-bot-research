import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
O = sys.argv[1]
RP = pd.read_csv(O + 'replay_signals.csv', low_memory=False)
s = RP[RP.kind == 'strategy']
print(s.groupby(['run', 'timeframe', 'status']).size().unstack(fill_value=0))
x = s[s.timeframe.isin(['1h', '4h'])]
print(x.groupby(['timeframe', 'symbol', 'status']).size().unstack(fill_value=0))
print(x[x.status == 'REJECTED_SIZING'].reject_reasons.head(5).tolist())
print(x[x.status == 'TRADED'].groupby('timeframe').leverage.value_counts())
print(x[x.status == 'TRADED'].groupby(['timeframe','symbol']).stop_frac.median())
SR = pd.read_csv(O + 'sizing_rejections.csv')
SR['tf'] = SR.account_id.str.split('@').str[-1]
print(SR.groupby(['run', 'tf']).size())
print(SR[SR.tf.isin(['1h','4h'])].groupby(['run','tf','symbol']).size())
