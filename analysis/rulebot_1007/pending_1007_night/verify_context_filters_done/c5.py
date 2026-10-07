import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1]); sys.dont_write_bytecode = True
from lib import *
C = load()
V3 = C[C.run == 'v3a'].copy()
for c in ['europe', 'long', 'di_with']:
    print(c, V3.groupby(c).lev.mean().round(1).to_dict())
print('stop_b', V3.groupby('stop_b').lev.mean().round(1).to_dict(), 'qtier', V3.groupby('qtier').lev.mean().round(1).to_dict())
# contrasts within leverage strata (v3a, 15m)
for tf in ['15m', '30m']:
    X = V3[V3.timeframe == tf]
    for c, m in [('europe', X.europe), ('long', X.long), ('wide', X.stop_b == 'wide')]:
        Y = X.assign(Rr=X.R - X.groupby('lev').R.transform('mean'))
        print(tf, c, 'raw', contrast(X, m)['d'], 'lev-demeaned', contrast(Y, m, y='Rr')['d'])
# v4 replay: lev by quality and R by lev
V4 = C[C.run == 'v4']; print('v4 R by lev', V4.groupby('lev').R.agg(['size', 'mean']).round(3).to_dict('index'))
# duplicates: identical (run,tf,symbol,bar,side) groups in core
g = C.groupby(['run', 'timeframe', 'symbol', 'bar_close', 'side']).size()
print('core signals', len(C), 'unique moments', len(g), 'share in dup groups', round((g[g > 1].sum()) / len(C), 3))
# Europe 15m OOS with dedup (one row per moment, mean R)
for tf in ['15m', '30m']:
    X = C[(C.timeframe == tf) & C.run.isin(['v3a', 'v3b'])]
    Dd = X.groupby(['run', 'symbol', 'bar_close', 'side'], as_index=False).agg(R=('R', 'mean'), europe=('europe', 'first'), long=('long', 'first'))
    print(tf, 'dedup europe v3a+v3b', contrast(Dd, Dd.europe), 'day', contrast(Dd, Dd.europe, mode='day'))
