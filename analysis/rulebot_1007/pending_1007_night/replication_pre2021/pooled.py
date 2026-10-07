"""Pooled pre-2021 gross / flip / net per kind x tf (all sized signals). python3 -I -B pooled.py <out_dir>"""
import os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
OD = sys.argv[1]; WK = 7 * 86400 * 10 ** 9
def ct(x, cl):
    x = np.asarray(x, float); ok = np.isfinite(x); x, cl = x[ok], np.asarray(cl)[ok]; mu = x.mean()
    s = pd.Series(x - mu).groupby(cl).sum().to_numpy(); se = np.sqrt((s ** 2).sum() * len(s) / max(len(s) - 1, 1)) / len(x)
    return mu, mu / se, len(x)
rows = []
for kind, tfs in (("core", ("5m", "15m", "30m", "1h", "4h")), ("ds", ("15m", "30m", "1h", "4h"))):
    for tf in tfs:
        T = pd.read_pickle(os.path.join(OD, f"pre_{kind}_{tf}.pkl.gz"))
        z = T[(T.v4n_lev > 0) & T.v4n_done & (T.fl_lev > 0) & T.fl_done]
        cl = z.ts.to_numpy() // WK
        g = ct(z.v4n_gross / z.stop_frac, cl); f = ct(z.fl_gross / z.stop_frac, cl); n = ct(z.v4n_R, cl)
        d = ct((z.v4n_gross - z.fl_gross) / 2 / z.stop_frac, cl)
        rows.append(dict(kind=kind, tf=tf, n=g[2], sized_share=float((T.v4n_lev > 0).mean()), gross=g[0], gross_t=g[1], flip=f[0], flip_t=f[1],
                         dir=d[0], dir_t=d[1], net=n[0], net_t=n[1], cost=float(np.nanmean(z.v4n_gross / z.stop_frac) - z.v4n_R.mean()),
                         stop_med=float(z.stop_frac.median())))
D = pd.DataFrame(rows); D.to_csv(os.path.join(OD, "pre_pooled.csv"), index=False); print(D.round(4).to_string())
