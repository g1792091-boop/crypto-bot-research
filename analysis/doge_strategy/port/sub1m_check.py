"""How much does Astral's coarse 5m TSL approximation (O->H->L, fill at bar close) differ from a
1-minute path walk?  Long window = Astral run bt_eabbc51538b849c6 (135 trades)."""
import numpy as np, pandas as pd
import doge_strategy as ds
d5 = ds.load_ohlcv('dogeusd-5m-last40k.csv')
m1 = ds.load_ohlcv('dogeusd-1m-merged.csv')
# alignment check of 1m->5m aggregation over the long window
g = m1.loc['2026-05-13 03:05':'2026-09-28 23:59'].resample('5min', label='left', closed='left')
a = pd.DataFrame(dict(open=g.open.first(), high=g.high.max(), low=g.low.min(), close=g.close.last(), n=g.open.count())).dropna()
j = a.join(d5, rsuffix='_5', how='inner')
print('1m->5m agg vs 5m: bars', len(j), {k: round(float(np.mean(np.isclose(j[k], j[k + '_5'], rtol=1e-9))), 4) for k in ['open', 'high', 'low', 'close']},
      ' 5m bars with <5 minutes of 1m data:', int((j.n < 5).sum()))
rows = []
for name, (a0, b0) in {'long 05-13..09-28': ('2026-05-13 03:05', '2026-09-28 23:55'),
                       'orig 09-11..09-28': ('2026-09-11 00:00', '2026-09-28 23:55')}.items():
    w = d5.loc[a0:b0]
    ind = ds.compute_indicators(w); sig = ds.compute_signals(w, ind)
    for side in ['long', 'short', 'both']:
        for mode, extra in [('astral', {}), ('ohl_stop', {}), ('olh_stop', {}), ('close_only', {}),
                            ('sub1m', dict(sub1m_path='ohl_stop')), ('sub1m', dict(sub1m_path='olh_stop')),
                            ('sub1m', dict(sub1m_path='astral'))]:
            tr = ds.simulate(w, extra or None, side=side, tsl_eval=mode, df_1m=m1, ind=ind, sig=sig)
            s = ds.summarize(tr, col='gross')
            net = ds.simulate(w, extra or None, side=side, tsl_eval=mode, df_1m=m1, ind=ind, sig=sig,
                              costs=dict(fee_side=0.0005, slip_side=0.00015, funding_8h=0.0001))
            sn = ds.summarize(net, col='net')
            label = mode + ('/' + extra['sub1m_path'] if extra else '')
            rows.append(dict(window=name, side=side, tsl=label, n=s['n'], wr=round(s['win_rate'], 3), mean_gross_pct=round(s['mean_pct'], 4),
                             t=round(s['t_stat'], 2), pf_gross=round(s['pf'], 3), tr25_gross_pct=round(s['total_ret_pct'], 3),
                             mean_net_binance_pct=round(sn['mean_pct'], 4), pf_net=round(sn['pf'], 3), wr_net=round(sn['win_rate'], 3)))
res = pd.DataFrame(rows)
res.to_csv('sub1m_check.csv', index=False)
print(res.to_string())
