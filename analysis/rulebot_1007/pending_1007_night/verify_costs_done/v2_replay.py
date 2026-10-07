# Every-signal replay (pipeline replay_signals.csv, v3b+v4): gross/net/cost by group x tf, per coin, dedup check. Own code.
import sys, os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boot.py')).read())
import numpy as np, pandas as pd
P, OUT = sys.argv[1], sys.argv[2]
D = pd.read_csv(P)
D = D[D.status == 'TRADED'].copy()
s = D.side.astype(float)
risk = D.qty * (D.entry_price - D.stop_initial).abs()
D['Rchk'] = D.pnl / risk
print('R identity max err', float((D.Rchk - D.R).abs().max()), 'n', len(D))
D['costR'] = (D.fees + D.funding) / risk + 2 * 2e-4 * D.entry_price / (D.entry_price - D.stop_initial).abs()
D['grossR'] = D.R + D.costR
D['stop_pct'] = 100 * (D.entry_price - D.stop_initial).abs() / D.entry_price
D['grp'] = D.kind.replace({'strategy': 'core36'})
D['cl'] = D.run + '_' + (D.bar_close // 7_200_000).astype(str)
rng = np.random.default_rng(2)
def ci(d, col, B=1000):
    g = d.groupby('cl')[col].agg(['sum', 'count']); S = g['sum'].values; N = g['count'].values; k = len(g)
    if k < 3: return (np.nan, np.nan), k
    bs = [S[i].sum() / N[i].sum() for i in (rng.integers(0, k, k) for _ in range(B))]
    return tuple(np.percentile(bs, [2.5, 97.5])), k
rows = []
for (g, tf), d in D.groupby(['grp', 'timeframe']):
    (lo, hi), k = ci(d, 'grossR')
    rows.append(dict(grp=g, tf=tf, n=len(d), cl=k, net=d.R.mean(), gross=d.grossR.mean(), lo=lo, hi=hi, cost=d.costR.mean(), cost_med=d.costR.median(), stop_med=d.stop_pct.median()))
# core36+ds200 pooled
for tf, d in D[D.grp.isin(['core36', 'ds200'])].groupby('timeframe'):
    (lo, hi), k = ci(d, 'grossR')
    rows.append(dict(grp='core+ds', tf=tf, n=len(d), cl=k, net=d.R.mean(), gross=d.grossR.mean(), lo=lo, hi=hi, cost=d.costR.mean(), cost_med=d.costR.median(), stop_med=d.stop_pct.median()))
    # dedupe identical signals (same coin, tf, side, bar) across definitions
    dd = d.drop_duplicates(['run', 'symbol', 'side', 'bar_close'])
    (lo, hi), k = ci(dd, 'grossR')
    rows.append(dict(grp='core+ds_dedup', tf=tf, n=len(dd), cl=k, net=dd.R.mean(), gross=dd.grossR.mean(), lo=lo, hi=hi, cost=dd.costR.mean(), cost_med=dd.costR.median(), stop_med=dd.stop_pct.median()))
O = pd.DataFrame(rows); O.to_csv(f'{OUT}/v2_replay_by_tf.csv', index=False)
print(O.round(3).to_string())
c = D[D.grp == 'core36'].groupby(['timeframe', 'symbol']).agg(n=('R', 'size'), stop=('stop_pct', 'median'), cost=('costR', 'median'), gross=('grossR', 'mean')).round(3)
c.to_csv(f'{OUT}/v2_replay_coin.csv'); print(c[c.index.get_level_values(0).isin(['15m', '30m'])].to_string())
# side-flip: chosen vs flipped (both replayed); gross = R + cost (same cost on both sides, approx)
f = D[D.grp.isin(['core36', 'ds200', 'random']) & D.flip_R.notna()]
print(f.groupby(['grp', 'timeframe']).apply(lambda d: pd.Series(dict(n=len(d), chosen=d.R.mean(), flip=d.flip_R.mean(), both=(d.R.mean() + d.flip_R.mean()) / 2))).round(3).to_string())
