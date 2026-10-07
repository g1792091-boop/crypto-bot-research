# Aggregates of the 5-year rows with week-block bootstrap (weeks resampled whole). Writes small CSVs only.
import numpy as np, pandas as pd
RT = 0.0014
T1 = pd.Timestamp('2024-07-01').value // 10**9
def wboot(d, cols, B=1000, seed=0):
    w = d.groupby('wk')[cols].sum(); n = d.groupby('wk').size().values
    S = w.values; k = len(n); rng = np.random.default_rng(seed)
    I = rng.integers(0, k, (B, k))
    bs = np.stack([S[ii].sum(0) / n[ii].sum() for ii in I])
    return np.percentile(bs, 2.5, axis=0), np.percentile(bs, 97.5, axis=0)
def agg(D, out, tag):
    D['wk'] = (D.ts - 345600) // 604800  # Monday-UTC weeks
    D['gbp'] = D.g * 1e4; D['gR'] = D.g / D.sf; D['xR'] = (D.g - D.gf) / D.sf; D['bothR'] = (D.g + D.gf) / 2 / D.sf
    D['netbp'] = D.gbp - 14.0
    D['yr'] = pd.to_datetime(D.ts, unit='s').dt.year; D['per'] = np.where(D.ts < T1, 1, 2)
    D['q'] = D.groupby('tf').sf.transform(lambda x: pd.qcut(x, 5, labels=False))
    cols = ['gbp', 'gR', 'xR', 'bothR']
    res = []
    def row(split, key, d, ci=False):
        r = dict(split=split, key=key, n=len(d), weeks=d.wk.nunique(), netbp=d.netbp.mean(), gbp=d.gbp.mean(), gR=d.gR.mean(),
                 xR=d.xR.mean(), bothR=d.bothR.mean(), sf_med=100 * d.sf.median(), liq_share=(d.rs == 2).mean(), lock_share=(d.rs == 1).mean())
        if ci:
            lo, hi = wboot(d, cols)
            for c_, a, b in zip(cols, lo, hi): r[c_ + '_lo'] = a; r[c_ + '_hi'] = b
        res.append(r)
    for tf, d in D.groupby('tf'):
        row('all', tf, d, True)
        for sp in ['yr', 'coin', 'q', 'per']:
            for k, dd in d.groupby(sp): row(sp, f'{tf}|{k}', dd)
    pd.DataFrame(res).to_csv(f'{out}/v3_agg_{tag}.csv', index=False)
    st = []
    for (tf, s_), d in D.groupby(['tf', 'strat']):
        lo, hi = wboot(d, ['gR', 'gbp'], B=600, seed=1)
        st.append(dict(tf=tf, strat=s_, n=len(d), gbp=d.gbp.mean(), gR=d.gR.mean(), gR_lo=lo[0], gR_hi=hi[0],
                       gR_p1=d.gR[d.per == 1].mean(), gR_p2=d.gR[d.per == 2].mean(), xR=d.xR.mean(), sf_med=100 * d.sf.median()))
    pd.DataFrame(st).to_csv(f'{out}/v3_strat_{tag}.csv', index=False)
    print(pd.DataFrame(res).query("split=='all'").round(4).T.to_string(), flush=True)
