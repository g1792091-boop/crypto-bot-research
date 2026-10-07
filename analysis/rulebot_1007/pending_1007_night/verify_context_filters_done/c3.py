import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1]); sys.dont_write_bytecode = True
from lib import *
A = load(kinds=('strategy', 'ds200'))
C = A[A.kind == 'strategy']
pr = lambda *a: print(*a, flush=True)
pr('== CF9 regime counts')
pr(A[(A.run == 'v4') & (A.timeframe == '15m')].htf_regime.value_counts().to_dict(), A[(A.run == 'v4') & (A.timeframe == '15m')].regime.value_counts().to_dict())
pr('v3a 15m own trend', A[(A.run == 'v3a') & (A.timeframe == '15m') & A.regime.astype(str).str.startswith('trend')].shape[0])
pr('== CF11 N18 15m ER')
N = C[(C.strategy == 'N18_VWMA_MACD') & (C.timeframe == '15m')].copy()
N['er_b'] = np.where(N.er < .055, 'low', np.where(N.er < .13, 'mid', 'high'))
pr(N.groupby(['run', 'er_b']).R.agg(['size', 'mean']).round(2).to_string())
X = N[N.er_b != 'mid']
for mode in [2, 'day']: pr(mode, contrast(X, X.er_b == 'high', mode=mode, minr=3))
lo = N[N.er_b == 'low']; pr('low-ER clusters (2h blocks per run):', lo.groupby('run').bar_close.apply(lambda b: len(np.unique(b // (2 * H)))).to_dict(), 'long share', round(lo.long.mean(), 2))
pr('== CF2 design effect (mean R, v4 core 15m) and MDE')
for run in ['v3a', 'v4']:
    X = C[(C.run == run) & (C.timeframe == '15m')]; y = X.R.values; n = len(y)
    for mode in [1, 2, 4]:
        cl = clus(X.bar_close.values, mode); u, inv = np.unique(cl, return_inverse=True)
        r = np.bincount(inv, y - y.mean()); vc = np.sum(r ** 2) / n ** 2; vi = y.var() / n
        pr(run, mode, 'deff', round(vc / vi, 1))
pr('== CF12 sideflip by context (v3b+v4 core and v4 ds200)')
R = A[A.run.isin(['v3b', 'v4']) & A.flipR.notna()].copy()
R['dir'] = (R.R - R.flipR) / 2; R['any'] = (R.R + R.flipR) / 2
S = pd.read_csv(V + 'scan.csv')
P = {'R': [], 'dir': [], 'any': []}
import importlib
# rebuild bucket labels via c2 logic is heavy; use a few key binary contexts instead
ctx = {'eu': R.kst_hour.between(16, 21), 'di_with': R.di_with, 'htf_mid': R.htf_s.between(.2, .8, inclusive='left'),
       'box_far': R.box_s >= .8, 'ema_with': R.ema_s.between(.5, 1.5, inclusive='left'), 'ema_ext': R.ema_s >= 1.5, 'wide': R.stop_b == 'wide', 'tight': R.stop_b == 'tight',
       'adx30': R.adx >= 30, 'er_lo': R.er < np.where(R.timeframe == '15m', .055, .065)}
for kind in ['strategy', 'ds200']:
    for tf in ['15m', '30m']:
        X = R[(R.kind == kind) & (R.timeframe == tf)]
        for nm, m in ctx.items():
            for y in P:
                o = contrast(X, m.loc[X.index], y=y); P[y].append((kind, tf, nm, o['d'], o['p']))
for y in P:
    p = np.array([t[4] for t in P[y]]); q = bh(p)
    pr(y, 'tests', len(p), 'p<.05', int((p < .05).sum()), 'q<.10', int((q < .10).sum()))
for t in zip(P['R'], P['dir'], P['any']):
    if t[0][1] == '15m' and t[0][0] == 'strategy' and t[0][2] in ('htf_mid', 'eu', 'di_with'): pr(t[0][:3], 'dR', t[0][3], 'dir', t[1][3], t[1][4], 'any', t[2][3], t[2][4])
