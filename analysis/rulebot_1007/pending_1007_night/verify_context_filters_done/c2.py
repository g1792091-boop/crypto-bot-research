import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1]); sys.dont_write_bytecode = True
from lib import *

A = load(kinds=('strategy', 'ds200'))
s = A.side.values
def rs(col):
    r = A[col].astype(str).values
    return np.where(r == 'chop', 'chop', np.where(r == 'box', 'box', np.where(r == 'unknown', 'mid',
           np.where(((r == 'trend_up') & (s > 0)) | ((r == 'trend_down') & (s < 0)), 'tw', np.where(np.char.startswith(r.astype(str), 'trend'), 'ta', 'na')))))
def cut3(x, a, b): x = np.asarray(x, float); return np.where(np.isnan(x), 'na', np.where(x < a, 'lo', np.where(x < b, 'md', 'hi')))
F = {}
F['reg'] = rs('regime'); F['hreg'] = rs('htf_regime')
er = np.where(A.timeframe == '15m', cut3(A.er, .055, .13), cut3(A.er, .065, .155)); F['er'] = er
F['adx'] = cut3(A.adx, 20, 30); F['di'] = np.where(A.di_with, 'with', 'ag')
e = A.ema_s.values; F['ema'] = np.where(e < -.5, 'fade', np.where(e < .5, 'near', np.where(e < 1.5, 'with', 'ext')))
F['age'] = cut3(A.trend_age, 2.5, 10.5)
for k in ['box_s', 'htf_s', 'rng_s']: F[k] = cut3(A[k], .2, .8)
F['stop'] = A.stop_b.values; F['room'] = cut3(A.sr_room, .15, .5); F['floor'] = cut3(A.sr_floor, .15, .5)
F['lbl'] = np.where(A.sr_level_before_lock.astype(float) > .5, 'y', 'n'); F['sbs'] = np.where(A.sr_support_before_stop.astype(float) > .5, 'y', 'n')
h = A.kst_hour.values; F['sess'] = np.where((h >= 9) & (h <= 15), 'asia', np.where((h >= 16) & (h <= 21), 'eu', np.where((h >= 22) | (h <= 3), 'us', 'late')))
F['coin'] = A.symbol.values; F['q'] = A.qtier.astype(str).values
g = A.groupby(['run', 'kind', 'timeframe', 'symbol', 'bar_close', 'side']).sig_id.transform('size').values
F['cons'] = np.where(g <= 1, 'alone', np.where(g <= 3, 'few', 'many'))
key = A.run + A.kind + A.timeframe + A.symbol + A.bar_close.astype(str)
opp = A.assign(k=key).groupby('k').side.transform(lambda x: x.nunique() > 1).values
F['confl'] = np.where(opp, 'y', 'n'); F['long'] = np.where(A.long, 'y', 'n')
BIN = {'di': ['with'], 'lbl': ['n'], 'sbs': ['n'], 'confl': ['y'], 'long': ['y'], 'q': ['best', 'good', 'base']}
CON = []
for f, v in F.items():
    A[f] = v
    for b in (BIN.get(f) or [x for x in np.unique(v) if x != 'na']): CON.append((f, b))
print('n contrasts', len(CON))
def eff(X, f, b, mode=2):
    X = X[X[f] != 'na']
    if f == 'q': X = X[X.kind == 'strategy']
    return contrast(X, X[f] == b, mode=mode)
rows = []
C = A[A.kind == 'strategy']
for tf in ['15m', '30m']:
    for f, b in CON:
        r = {'tf': tf, 'f': f, 'b': b}
        for run in ['v3a', 'v3b', 'v4']:
            o = eff(C[(C.timeframe == tf) & (C.run == run)], f, b); r[run] = o['d']; r['p_' + run] = o['p']; r['n_' + run] = o['n_in']
        for nm, rr in [('v3bv4', ['v3b', 'v4']), ('v3av3b', ['v3a', 'v3b'])]:
            o = eff(C[(C.timeframe == tf) & C.run.isin(rr)], f, b); r[nm] = o['d']; r['p_' + nm] = o['p']; r['n_' + nm] = o['n_in']
        o = eff(A[(A.kind == 'ds200') & (A.timeframe == tf)], f, b); r['ds'] = o['d']; r['p_ds'] = o['p']
        rows.append(r)
T = pd.DataFrame(rows); T.to_csv(V + 'scan.csv', index=False)
MIN = 30
for tf in ['15m', '30m']:
    t = T[(T.tf == tf)].dropna(subset=['v3a', 'v4'])
    print(tf, 'omnibus corr v3a~v4', round(np.corrcoef(t.v3a, t.v4)[0, 1], 3), 'n', len(t), 'sign agree', round((np.sign(t.v3a) == np.sign(t.v4)).mean(), 3))
def onesided(p, d, sgn): return np.where(np.sign(d) == sgn, p / 2, 1 - p / 2)
allp = []
for nm, disc, test in [('A', 'v3a', 'v3bv4'), ('B', 'v4', 'v3av3b'), ('T', 'v3a', 'ds')]:
    t = T[(T['n_' + disc] >= MIN) if 'n_' + disc in T else T.index == T.index].dropna(subset=[disc])
    car = t[t['p_' + disc] < 0.05].dropna(subset=[test])
    p1 = onesided(car['p_' + test].values, car[test].values, np.sign(car[disc].values))
    q = bh(p1) if len(p1) else []
    print(nm, 'testable', len(t), 'disc p<.05', (t['p_' + disc] < .05).sum(), 'carried', len(car), 'oos p1<.05', (p1 < .05).sum(), 'q<.05', (np.array(q) < .05).sum(), 'same sign', (np.sign(car[test]) == np.sign(car[disc])).sum())
    for (i, r), pp, qq in zip(car.iterrows(), p1, q):
        if pp < 0.05: print('   ', r.tf, r.f, r.b, disc, r[disc], test, r[test], 'p1', round(pp, 4), 'q', round(qq, 4))
    allp += list(t['p_' + disc].values)
allp = np.array([p for p in allp if p == p])
print('all discovery p count', len(allp), 'BH q<.10 over all', (bh(allp) < .10).sum())
