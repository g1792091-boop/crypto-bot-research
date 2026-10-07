import sys, site
sys.path.append(site.getusersitepackages()); sys.dont_write_bytecode = True
import numpy as np, pandas as pd
SC = sys.argv[1]; V = SC + '/lens/context_filters/verify3/'
X = pd.read_csv(SC + '/lens/context_filters/out5y/fiveyear_signals.csv.gz')
pr = lambda *a: print(*a, flush=True)
pr('rows', len(X), 'R nonnull', round(X.R.notna().mean(), 4), X.tf.value_counts().to_dict())
X = X[X.R.notna()].copy()
# build check vs pipeline 5y reference (every-signal counts, mean ret on notional)
ref = pd.read_csv(SC + '/rb_analyze/out_real/fiveyear_ref.csv', low_memory=False)
ref = ref[(ref.source == 'profiles_binance') & (ref.variant == 'every_signal') & ref.timeframe.isin(['15m', '30m'])][['strategy', 'timeframe', 'n_signals', 'mean_ret_notional']]
g = X.groupby(['strategy', 'tf']).agg(n=('R', 'size'), rn=('roe', lambda r: 0)).reset_index()
g['rn'] = X.assign(rn=X.roe / X.lev).groupby(['strategy', 'tf']).rn.mean().values
m = g.merge(ref, left_on=['strategy', 'tf'], right_on=['strategy', 'timeframe'])
pr('build check: cells', len(m), 'n ratio median', round((m.n / m.n_signals).median(), 3), 'min', round((m.n / m.n_signals).min(), 3),
   'corr ret_notional', round(np.corrcoef(m.rn, m.mean_ret_notional)[0, 1], 3), 'mean diff', round((m.rn - m.mean_ret_notional).mean(), 5))
X['day'] = (X.close_t + 9 * 3600000) // 86400000
X['year'] = pd.to_datetime(X.close_t, unit='ms').dt.year
X['strat'] = X.strategy + X.tf + X.year.astype(str) + X.side.astype(str)
s = X.side.values
X['di_with'] = s * (X.dip - X.dim) > 0
X['box_far'] = np.where(s > 0, X.box_pos, 1 - X.box_pos) >= .8
X['rng_far'] = np.where(s > 0, X.range_pos, 1 - X.range_pos) >= .8
hp = np.where(s > 0, X.htf_pos, 1 - X.htf_pos); X['htf_mid'] = (hp >= .2) & (hp < .8)
e = s * X.ema_dist; X['ema_with'] = (e >= .5) & (e < 1.5)
X['eu'] = X.kst_hour.between(16, 21); X['adx30'] = X.adx >= 30; X['cons4'] = X.n_same >= 4
cut = {'15m': (0.5, 0.7), '30m': (0.74, 1.0)}
X['wide'] = False; X['tight'] = False
for tf, (a, b) in cut.items():
    mm = X.tf == tf; X.loc[mm, 'wide'] = X.stop_pct >= b; X.loc[mm, 'tight'] = X.stop_pct < a
def within(Y, col, y='R'):
    x = Y[col].astype(float); xr = x - x.groupby(Y.strat).transform('mean'); yr = Y[y] - Y[y].groupby(Y.strat).transform('mean')
    b = (xr * yr).sum() / (xr ** 2).sum()
    u = (xr * (yr - b * xr)).groupby(Y.day).sum(); se = np.sqrt((u ** 2).sum()) / (xr ** 2).sum()
    return round(b, 3), round(b / se, 1)
for tf in ['15m', '30m']:
    Y = X[X.tf == tf]
    pr(tf, 'n', len(Y), 'mean R', round(Y.R.mean(), 3))
    for c in ['eu', 'adx30', 'htf_mid', 'ema_with', 'di_with', 'box_far', 'rng_far', 'cons4', 'wide']:
        b, z = within(Y, c); yrs = [np.sign(within(Y[Y.year == yy], c)[0]) for yy in sorted(Y.year.unique())]
        pr('  ', c, 'R', b, 'z', z, 'roe', within(Y, c, 'roe')[0], 'yrs+', int(sum(v > 0 for v in yrs)), '/', len(yrs))
    Z = Y[Y.wide | Y.tight]; pr('   wide-vs-tight', within(Z, 'wide'))
    N = Y[(Y.strategy == 'N18_VWMA_MACD')]
    lo, hi = (.055, .13) if tf == '15m' else (.065, .155)
    N = N[(N.er < lo) | (N.er >= hi)].assign(hiER=lambda d: d.er >= hi); pr('   N18 high-low ER', within(N, 'hiER'))
X.to_pickle(V + 'fy.pkl')
