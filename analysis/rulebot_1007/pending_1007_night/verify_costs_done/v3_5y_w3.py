# 5-year every-signal run of the 36 strategies with my simulator (chosen side and opposite side).
import sys, os, time
D0 = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, D0)
exec(open(os.path.join(D0, 'boot.py')).read())
import numpy as np, pandas as pd
from simcore import sim
sig_dir, out, tfs, LEV = sys.argv[1], sys.argv[2], sys.argv[3].split(','), float(sys.argv[4])
LIQ = len(sys.argv) > 5 and sys.argv[5] == 'liq'
COINS = ['BTCUSD', 'ETHUSD', 'SOLUSD', 'DOGEUSD', 'LTCUSD', 'BCHUSD']
T0 = pd.Timestamp('2021-08-01').value
rows = []; t0 = time.time()
for tf in tfs:
    for coin in COINS:
        z = np.load(os.path.join(sig_dir, f'sig_{tf}_{coin}.npz'), allow_pickle=False)
        ts = z['ts']; o, h, l, c, atr = z['o'], z['h'], z['l'], z['c'], z['atr']; n = len(ts)
        for key in [k for k in z.files if k.startswith('s__')]:
            sg = z[key]; i = np.nonzero(sg)[0]
            i = i[(i + 1 < n) & (ts[i] >= T0) & np.isfinite(atr[i]) & (atr[i] > 0)]
            if not len(i): continue
            side = np.sign(sg[i]).astype(int)
            raw, xr, rs, hd = sim(o, h, l, c, i + 1, side, atr[i]*1.5, LEV, liq=LIQ)
            _, xr2, rs2, hd2 = sim(o, h, l, c, i + 1, -side, atr[i]*1.5, LEV, liq=LIQ)
            rows.append(pd.DataFrame(dict(tf=tf, coin=coin[:-3], strat=key[3:], ts=ts[i + 1] // 10**9, sf=(2 * atr[i] / raw).astype('f4'),
                                          g=(side * (xr / raw - 1)).astype('f4'), gf=(-side * (xr2 / raw - 1)).astype('f4'),
                                          rs=rs.astype('i1'), rsf=rs2.astype('i1'), hd=hd.astype('i4'))))
    print(tf, 'done', round(time.time() - t0), flush=True)
D = pd.concat(rows, ignore_index=True); del rows
print('rows', len(D), flush=True)
from agg5y import agg
agg(D, out, f'w3_lev{int(LEV)}{"_liq" if LIQ else ""}_{"_".join(tfs)}')
