"""Design check (context-free): how much do signal outcomes cluster in time? Variance of the run-level mean R
under cluster bootstrap with blocks of 1h/2h/4h/8h vs the iid SE, per run x tf (core36 + ds200)."""
import sys, site
sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
D = pd.read_csv(sys.argv[1], low_memory=False)
D = D[(D.has_ctx == 1) & D.R.notna() & D.kind.isin(['strategy', 'ds200']) & D.timeframe.isin(['15m', '30m', '1h'])]
rng = np.random.default_rng(1)
rows = []
for (run, tf), g in D.groupby(['run', 'timeframe']):
    y = g.R.to_numpy(); n = len(y)
    se_iid = y.std(ddof=1) / np.sqrt(n)
    r = {'run': run, 'tf': tf, 'n': n, 'mean_R': y.mean(), 'sd_R': y.std(ddof=1), 'se_iid': se_iid}
    for h in [0.25, 1, 2, 4, 8]:
        cl = (g.bar_close // int(h * 3600000)).to_numpy()
        u, inv = np.unique(cl, return_inverse=True)
        G = len(u)
        sums = np.bincount(inv, weights=y, minlength=G); cnt = np.bincount(inv, minlength=G)
        bs = []
        for b in range(2000):
            idx = rng.integers(0, G, G)
            bs.append(sums[idx].sum() / cnt[idx].sum())
        se = np.std(bs, ddof=1)
        r[f'G_{h}h'] = G; r[f'deff_{h}h'] = (se / se_iid) ** 2
    rows.append(r)
print(pd.DataFrame(rows).round(3).to_string())
pd.DataFrame(rows).to_csv('out/design_effect_by_block.csv', index=False)
print(D.R.describe(percentiles=[.001, .01, .05, .5, .95, .99, .999]))
try:
    import sklearn; print('sklearn', sklearn.__version__)
except Exception as e: print('no sklearn', e)
try:
    import scipy; print('scipy', scipy.__version__)
except Exception as e: print('no scipy', e)
