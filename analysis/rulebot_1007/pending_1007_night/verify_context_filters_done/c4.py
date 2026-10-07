import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1]); sys.dont_write_bytecode = True
from lib import *
A = load(kinds=('strategy', 'ds200'))
s = A.side.values
F = pd.DataFrame({'e': A.ema_s, 'di': s * (A.di_plus.astype(float) - A.di_minus.astype(float)), 'box': A.box_s, 'rng': A.rng_s, 'htf': A.htf_s,
                  'age': np.log1p(A.trend_age.astype(float).clip(0)), 'adx': A.adx.astype(float), 'er': A.er.astype(float), 'stop': np.log(A.stop_pct),
                  'room': A.sr_room.astype(float).clip(0, 3), 'floor': A.sr_floor.astype(float).clip(0, 3)}, index=A.index)
F = F.fillna(F.median()); F['tf30'] = (A.timeframe == '30m').astype(float)
MOM = ['e', 'di', 'box', 'rng', 'htf']
def run(tr, te, cols, B=500):
    Z = F.loc[tr.index, cols].values; mu, sd = Z.mean(0), Z.std(0) + 1e-9
    Zt = np.c_[np.ones(len(Z)), (Z - mu) / sd]; b = np.linalg.solve(Zt.T @ Zt + 20 * np.eye(Zt.shape[1]), Zt.T @ tr.R.values)
    p = np.c_[np.ones(len(te)), (F.loc[te.index, cols].values - mu) / sd] @ b
    k = np.zeros(len(te), bool)
    for r in te.run.unique():  # top third within run
        m = (te.run == r).values; k[m] = p[m] >= np.quantile(p[m], 2 / 3)
    y = te.R.values; up = y[k].mean() - y.mean()
    cl = te.run.values + (te.bar_close.values // (2 * H)).astype(str); u, inv = np.unique(cl, return_inverse=True)
    sk, nk, sa, na = np.bincount(inv, np.where(k, y, 0)), np.bincount(inv, k), np.bincount(inv, y), np.bincount(inv)
    rng = np.random.default_rng(0); bs = []
    for _ in range(B):
        w = np.bincount(rng.integers(0, len(u), len(u)), minlength=len(u)); bs.append((w @ sk) / (w @ nk) - (w @ sa) / (w @ na))
    return round(up, 3), np.round(np.quantile(bs, [.025, .975]), 3), round(y[k].mean(), 3), round(y.mean(), 3)
C = A[A.kind == 'strategy']
allc = list(F.columns)
for nm, tr, te in [('v3a->v3b+v4', C[C.run == 'v3a'], C[C.run != 'v3a']), ('v3a->ds200', C[C.run == 'v3a'], A[A.kind == 'ds200']), ('v4->v3a+v3b', C[C.run == 'v4'], C[C.run != 'v4'])]:
    print(nm, 'chart', run(tr, te, allc), 'noMOM', run(tr, te, [c for c in allc if c not in MOM])[:1], 'v4-only target' if False else '')
# v3a leverage confound: R in v3a vs lev
V3 = C[C.run == 'v3a']
print('v3a mean R by lev', V3.groupby('lev').R.agg(['size', 'mean']).round(3).to_dict('index'))
