import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1]); sys.dont_write_bytecode = True
from lib import *
A = load(kinds=('strategy', 'ds200'))
C = A[A.kind == 'strategy']; DS = A[A.kind == 'ds200']
pr = lambda *a: print(*a, flush=True)
pr('== CF5 long-short per run')
for tf in ['15m', '30m']:
    for run in ['v3a', 'v3b', 'v4']:
        X = C[(C.timeframe == tf) & (C.run == run)]
        pr(tf, run, contrast(X, X.long), 'longshare', round(X.long.mean(), 2))
    X = DS[DS.timeframe == tf]; pr(tf, 'ds200', contrast(X, X.long))
pr('== CF7 europe')
for tf in ['15m', '30m']:
    for run in ['v3a', 'v3b', 'v4']:
        X = C[(C.timeframe == tf) & (C.run == run)]; pr(tf, run, contrast(X, X.europe))
    X = C[(C.timeframe == tf) & C.run.isin(['v3a', 'v3b'])]
    for mode in [2, 4, 'day']: pr(tf, 'v3a+v3b', mode, contrast(X, X.europe, mode=mode))
    # within side
    for sd in [True, False]:
        Y = X[X.long == sd]; pr(tf, 'v3a+v3b long' if sd else 'v3a+v3b short', contrast(Y, Y.europe))
    # per evening: europe minus same-day rest
    X = C[C.timeframe == tf]
    for (run, day), g in X.groupby(['run', 'kst_day']):
        e = g[g.europe]
        if len(e) >= 10: pr('  ev', tf, run, day, 'n', len(e), 'eu', round(e.R.mean(), 3), 'rest', round(g[~g.europe].R.mean(), 3), 'eu long share', round(e.long.mean(), 2))
pr('== CF8 quality')
for tf in ['15m', '30m']:
    X = C[C.timeframe == tf]
    pr(tf, 'best-rest', contrast(X, X.qtier == 'best'), X.qtier.value_counts().to_dict())
    pr(tf, 'lev by qtier', X.groupby(['run', 'qtier']).lev.mean().round(1).to_dict())
pr('== CF10 wide-tight live')
for tf in ['15m', '30m']:
    X = C[(C.timeframe == tf) & C.stop_b.isin(['wide', 'tight'])]
    pr(tf, 'all', contrast(X, X.stop_b == 'wide'))
    for run in ['v3a', 'v3b', 'v4']:
        Y = X[X.run == run]; pr(tf, run, contrast(Y, Y.stop_b == 'wide'), 'median stop%', round(C[(C.timeframe == tf) & (C.run == run)].stop_pct.median(), 3))
pr('== CF13 sr shares')
pr(A.groupby(['run', 'timeframe']).agg(lbl=('sr_level_before_lock', 'mean'), sbs=('sr_support_before_stop', 'mean'), room=('sr_room', 'median')).round(3).to_string())
