# Nightly limit-entry shadow (v4) vs the same signal at market (pipeline replay), in market-R units, 2h-cluster bootstrap.
import sys, os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boot.py')).read())
import numpy as np, pandas as pd
E, P = sys.argv[1], sys.argv[2]
d = pd.read_csv(f'{E}/current/d3_shadows.csv'); L = d[d.kind == 'limit'].copy()
L['ts'] = L.key.str.split('|').str[3].astype('int64')
R = pd.read_csv(P); R = R[(R.run == 'current') & (R.status == 'TRADED')]
print('runs in replay', pd.read_csv(P, usecols=['run']).run.unique())
best = None
for col in ['sig_ts', 'bar_close', 'entry_time']:
    m = L.merge(R, left_on=['account_id', 'symbol', 'ts'], right_on=['account_id', 'symbol', col], how='inner', suffixes=('', '_m'))
    print(col, 'matched', len(m), 'of', len(L))
    if best is None or len(m) > len(best): best = m
m = best
print('unresolved among matched', int((m.resolved == 0).sum()), 'filled share', round(m.filled.mean(), 3))
m = m[m.resolved == 1].copy()
m['Rl'] = np.where(m.filled == 1, m.roe / m.leverage / m.stop_frac, 0.0)
m['d'] = m.Rl - m.R
m['grp'] = m.kind_m.replace({'strategy': 'core36'}) if 'kind_m' in m else m.account_id
m['cl'] = (m.bar_close // 7_200_000)
rng = np.random.default_rng(3)
for (g, tf), x in m[m.timeframe.isin(['15m', '30m', '1h', '4h'])].groupby(['grp', 'timeframe']):
    gs = x.groupby('cl').d.agg(['sum', 'count']); S_, N = gs['sum'].values, gs['count'].values; k = len(gs)
    bs = [S_[i].sum() / N[i].sum() for i in (rng.integers(0, k, k) for _ in range(1000))]
    miss = x[x.filled == 0]
    print(g, tf, 'n', len(x), 'cl', k, 'fill', round(x.filled.mean(), 3), 'missed mktR', round(miss.R.mean(), 3), 'missed win', round((miss.R > 0).mean(), 2),
          'filled improve', round((x.Rl - x.R)[x.filled == 1].mean(), 3), 'net vs mkt', round(x.d.mean(), 3), np.round(np.percentile(bs, [2.5, 97.5]), 3), 'limit net/signal', round(x.Rl.mean(), 3))
