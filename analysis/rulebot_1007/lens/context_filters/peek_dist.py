import sys, site
sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
D = pd.read_csv(sys.argv[1], low_memory=False)
D = D[D.has_ctx == 1]
print(pd.crosstab([D.run, D.kind], D.timeframe))
print(pd.crosstab([D.run, D.kind], [D.timeframe, D.R.notna()]))
x = D[D.timeframe.isin(['15m', '30m'])]
for c in ['er', 'box_pos', 'htf_box_pos', 'ema20_dist_atr', 'trend_age', 'range_pct', 'adx', 'sr_room', 'sr_floor', 'stop_pct', 'q_score', 'n_same', 'n_opp']:
    print(c, x.groupby('timeframe')[c].describe(percentiles=[.1, .25, .33, .5, .67, .75, .9]).round(3).to_string())
for c in ['regime', 'htf_regime', 'sr_level_before_lock', 'sr_support_before_stop', 'sr_breakout', 'q_tier', 'family', 'sr_room_type']:
    print(pd.crosstab([x.run, x.timeframe], x[c].fillna('NA')))
