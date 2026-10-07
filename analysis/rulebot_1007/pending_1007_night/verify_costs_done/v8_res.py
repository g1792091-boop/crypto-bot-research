# Does bar resolution of the ladder matter? Live-period signals (replay, v3b+v4) simulated with my simulator on
# 1m live bars vs on the same bars aggregated to the signal's timeframe (what a 5-year tf-bar backtest does).
import sys, os
D0 = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, D0)
exec(open(os.path.join(D0, 'boot.py')).read())
import numpy as np, pandas as pd
from simcore import sim
E, P = sys.argv[1], sys.argv[2]
R = pd.read_csv(P); R = R[(R.status == 'TRADED') & R.timeframe.isin(['15m', '30m', '1h'])].copy()
R['grossR'] = R.R + (R.fees + R.funding) / (R.qty * (R.entry_price - R.stop_initial).abs()) + 4e-4 * R.entry_price / (R.entry_price - R.stop_initial).abs()
RUNMAP = {'run-20261005T183457Z': 'run-20261005T183457Z', 'current': 'current'}
TFMS = {'15m': 900_000, '30m': 1_800_000, '1h': 3_600_000}
out = []
for run in RUNMAP:
    B = pd.read_csv(f'{E}/{run}/live_bars.csv', usecols=['ts', 'symbol', 'open', 'high', 'low', 'close']).drop_duplicates(['symbol', 'ts']).sort_values(['symbol', 'ts'])
    for sym, b in B.groupby('symbol'):
        ts = b.ts.values; o, h, l, c = (b[x].values for x in ['open', 'high', 'low', 'close'])
        x = R[(R.run == run) & (R.symbol == sym)]
        for tf, xx in x.groupby('timeframe'):
            et = xx.entry_time.values.astype('int64'); i1 = np.searchsorted(ts, et)
            ok = (i1 < len(ts)) & (ts[np.minimum(i1, len(ts) - 1)] == et)
            xx = xx[ok]; i1 = i1[ok]; side = xx.side.values.astype(int); atr = xx.atr.values; lev = xx.leverage.values
            if not len(xx): continue
            # 1m
            g1 = np.full(len(xx), np.nan)
            for L in np.unique(lev):
                m = lev == L; raw, xr, rs, hd = sim(o, h, l, c, i1[m], side[m], atr[m], L, H=20000); g1[m] = side[m] * (xr / raw - 1)
            # tf bars
            k = ts // TFMS[tf]; gb = pd.DataFrame(dict(k=k, o=o, h=h, l=l, c=c)).groupby('k').agg(o=('o', 'first'), h=('h', 'max'), l=('l', 'min'), c=('c', 'last'))
            kk = gb.index.values; ik = np.searchsorted(kk, et[ok] // TFMS[tf])
            gt = np.full(len(xx), np.nan)
            for L in np.unique(lev):
                m = lev == L; raw, xr, rs, hd = sim(gb.o.values, gb.h.values, gb.l.values, gb.c.values, ik[m], side[m], atr[m], L, H=5000); gt[m] = side[m] * (xr / raw - 1)
            sf = 2 * atr / xx.ref_price.values
            out.append(pd.DataFrame(dict(run=run, tf=tf, kind=xx.kind.values, g1R=g1 / sf, gtR=gt / sf, repR=xx.grossR.values)))
O = pd.concat(out)
print('parity 1m sim vs replay gross R: corr', round(np.corrcoef(O.g1R, O.repR)[0, 1], 4), 'mean abs diff', round((O.g1R - O.repR).abs().mean(), 4))
print(O.groupby(['tf', 'kind'])[['g1R', 'gtR', 'repR']].agg(['mean']).round(3).assign(n=O.groupby(['tf', 'kind']).size()).to_string())
