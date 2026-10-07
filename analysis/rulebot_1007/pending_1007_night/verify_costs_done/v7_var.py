# Nightly per-trade variants (v4 d3_shadows) vs base, in base-R units, resolved pairs only; also share unresolved.
import sys, os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boot.py')).read())
import numpy as np, pandas as pd
E = sys.argv[1]
d = pd.read_csv(f'{E}/current/d3_shadows.csv'); d['k2'] = d.key.str.split('|', n=1).str[1]
T = pd.read_csv(f'{E}/current/trades.csv', usecols=lambda c: c != 'context'); A = pd.read_csv(f'{E}/current/accounts.csv')[['account_id', 'kind']]
T = T.merge(A, on='account_id'); T['sf'] = (T.entry_price - T.stop_initial).abs() / T.entry_price
b = d[d.kind == 'base'][['k2', 'account_id', 'symbol', 'timeframe', 'roe', 'resolved']]
print('base key sample', b.k2.iloc[0])
b['ts'] = b.k2.str.split('|').str[2].astype('int64')
for col in ['entry_time', 'signal_ts', 'exit_time']:
    j = b.merge(T[['account_id', 'symbol', col, 'leverage', 'sf', 'kind', 'roe']].rename(columns={col: 'ts', 'roe': 'roe_live'}), on=['account_id', 'symbol', 'ts'])
    if len(j): print('join on', col, len(j), 'of', len(b), 'base roe==live roe share', round((abs(j.roe - j.roe_live) < 1e-6).mean(), 3)); break
for v in ['stopw2.5', 'stopw3', 'lev10', 'lock30', 'tp1R', 'stopw1.5']:
    x = j.merge(d[d.kind == v][['k2', 'roe', 'resolved']], on='k2', suffixes=('', '_v'))
    unres = (x.resolved_v == 0).mean()
    x = x[(x.resolved == 1) & (x.resolved_v == 1)]
    lv = float(v[3:]) if v.startswith('lev') else None
    # lev variants: ROE at another leverage; per notional = roe_v / lev_v
    pn_v = x.roe_v / (lv if lv else x.leverage)
    x['dR'] = (pn_v - x.roe / x.leverage) / x.sf
    x['grp'] = x.kind.replace({'strategy': 'core36'})
    s = x[x.timeframe.isin(['15m', '30m'])].groupby(['grp', 'timeframe']).dR.agg(['size', 'mean']).round(3)
    print(v, 'unresolved share', round(unres, 3), s.reset_index().values.tolist())
