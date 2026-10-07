import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd, numpy as np
X = pd.read_csv(sys.argv[1], usecols=['run','sig_id','flip','variant','status','exit_reason','entry_time','exit_time','pnl','timeframe'])
for v in ['base','time_max2x','timestop','time_neg','tp1R','tp1R_max2x']:
    g = X[X.variant==v]
    print(v, g.exit_reason.value_counts().to_dict())
b = X[X.variant=='base'].set_index(['run','sig_id','flip'])
t = X[X.variant=='time_max2x'].set_index(['run','sig_id','flip'])
j = b.join(t, rsuffix='_t', how='inner')
print((j.pnl - j.pnl_t).abs().describe())
j['hold'] = (j.exit_time - j.entry_time)/60000
print(j.groupby('timeframe').hold.max())
