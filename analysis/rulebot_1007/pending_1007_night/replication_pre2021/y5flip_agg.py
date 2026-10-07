"""5y flip benchmark for the primary cells: direction content = mean((gross - gross_flipped)/2), week-clustered.
    python3 -I -B y5flip_agg.py <out_dir>
"""
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa
import pandas as pd  # noqa

OD = sys.argv[1]
WK = 7 * 86400 * 10 ** 9


def ct(x, cl):
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    x, cl = x[ok], np.asarray(cl)[ok]
    mu = x.mean()
    s = pd.Series(x - mu).groupby(cl).sum().to_numpy()
    se = np.sqrt((s ** 2).sum() * len(s) / max(len(s) - 1, 1)) / len(x)
    return mu, mu / se, len(x)


rows = []
for kind, tfs in (("core", ("5m", "15m", "30m", "1h", "4h")), ("ds", ("15m", "30m", "1h", "4h"))):
    for tf in tfs:
        T = pd.read_pickle(os.path.join(OD, f"y5fl_{kind}_{tf}.pkl.gz"))
        for st, g in T.groupby("strategy", observed=True):
            z = (g.v4n_lev > 0) & g.v4n_done
            a = g[z]
            G = (a.v4n_gross / a.stop_frac).to_numpy(float)
            gm, gt, n = ct(G, a.ts.to_numpy() // WK)
            f = g[z & (g.fl_lev > 0) & g.fl_done]
            Ga = (f.v4n_gross / f.stop_frac).to_numpy(float)
            Gf = (f.fl_gross / f.stop_frac).to_numpy(float)
            dm, dt, dn = ct((Ga - Gf) / 2, f.ts.to_numpy() // WK)
            fm, ft, _ = ct(Gf, f.ts.to_numpy() // WK)
            rows.append(dict(kind=kind, strategy=st, tf=tf, y5_n_chk=n, y5_gross_chk=gm, y5_gt_chk=gt, y5_g_flip=fm, y5_g_flip_t=ft,
                             y5_dir=dm, y5_dir_t=dt, y5_n_pair=dn))
D = pd.DataFrame(rows)
D.to_csv(os.path.join(OD, "y5_flip_cells.csv"), index=False)
pd.set_option("display.width", 200)
print(D.round(4).to_string())
