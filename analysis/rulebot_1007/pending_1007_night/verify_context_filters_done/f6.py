import sys, site
sys.path.append(site.getusersitepackages()); sys.dont_write_bytecode = True
import numpy as np, pandas as pd
SC = sys.argv[1]
X = pd.read_csv(SC + '/lens/context_filters/out5y/fiveyear_signals.csv.gz', usecols=['strategy', 'tf', 'close_t', 'side', 'R', 'n_same', 'n_opp', 'ema_dist', 'age', 'dip', 'dim', 'adx', 'box_pos', 'range_pos', 'er', 'htf_pos', 'stop_pct'])
X = X[X.R.notna()]
s = X.side.values
F = pd.DataFrame({'e': s * X.ema_dist, 'age': np.log1p(X.age.clip(0)), 'di': s * (X.dip - X.dim), 'adx': X.adx, 'er': X.er,
                  'box': np.where(s > 0, X.box_pos, 1 - X.box_pos), 'rng': np.where(s > 0, X.range_pos, 1 - X.range_pos),
                  'htf': np.where(s > 0, X.htf_pos, 1 - X.htf_pos), 'stop': np.log(X.stop_pct), 'ns': X.n_same, 'no': X.n_opp})
F['e2'] = F.e ** 2; F['htfmid'] = ((F.htf - .5).abs() < .3).astype(float)
F = F.fillna(F.median())
IS = X.close_t.values < 1719792000000  # 2024-07-01
day = (X.close_t.values + 9 * 3600000) // 86400000
for tf in ['15m', '30m']:
    m = (X.tf == tf).values
    Z = F[m].values; mu, sd = Z[IS[m]].mean(0), Z[IS[m]].std(0); Z = (Z - mu) / sd; Z = np.c_[np.ones(len(Z)), Z]
    y = X.R.values[m]; i = IS[m]
    b = np.linalg.solve(Z[i].T @ Z[i] + 10 * np.eye(Z.shape[1]), Z[i].T @ y[i])
    p = Z[~i] @ b; yc = y[~i]; thr = np.quantile(p, 2 / 3); k = p >= thr
    # day-cluster bootstrap of uplift
    d = day[m][~i]; u, inv = np.unique(d, return_inverse=True); rng = np.random.default_rng(1)
    sk = np.bincount(inv, np.where(k, yc, 0)); nk = np.bincount(inv, k); sa = np.bincount(inv, yc); na = np.bincount(inv)
    bs = []
    for _ in range(300):
        w = np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u))
        bs.append((w @ sk) / (w @ nk) - (w @ sa) / (w @ na))
    print(tf, 'CF n', len(yc), 'all', round(yc.mean(), 3), 'kept', round(yc[k].mean(), 3), 'uplift', round(yc[k].mean() - yc.mean(), 3), 'CI', np.round(np.quantile(bs, [.025, .975]), 3))
    st = X.strategy.values[m][~i]
    cell = pd.DataFrame({'s': st, 'y': yc, 'p': p})
    cell['k'] = cell.p >= cell.groupby('s').p.transform(lambda q: q.quantile(2 / 3))
    r = cell[cell.k].groupby('s').y.agg(['mean', 'size']).sort_values('mean', ascending=False)
    print('  per-strategy top-third (within cell): cells', len(r), 'n>=0', int((r['mean'] >= 0).sum()), 'best', r.head(3).round(3).to_dict('index'))
    r2 = cell[k].groupby('s').y.agg(['mean', 'size']); r2 = r2[r2['size'] >= 100].sort_values('mean', ascending=False)
    print('  per-strategy global-filter kept: cells', len(r2), 'n>=0', int((r2['mean'] >= 0).sum()), 'best', r2.head(3).round(3).to_dict('index'))
