"""verify3 DS per-row parity: own ATR14 + own sim (v3sim.sim). python3 -I -B v3ds.py <bars_dir> <their_out> <tf> <n>"""
import os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from v3sim import sim
bars, their, tf, n = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
T = pd.read_pickle(os.path.join(their, f"fyds_{tf}.pkl.gz")); T = T[T.v4n_lev > 0].sample(n, random_state=3)
rows = []
for coin, g in T.groupby("coin", observed=True):
    df = pd.read_csv(os.path.join(bars, f"{coin.lower()}-{tf}.csv.gz"))
    ts = pd.to_datetime(df.ts, utc=True).astype("int64").to_numpy()
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.c_[h - l, abs(h - pc), abs(l - pc)], axis=1)
    atrs = {"rma": pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy(),
            "sma": pd.Series(tr).rolling(14).mean().to_numpy()}
    pos = np.searchsorted(ts, g.ts.to_numpy())
    for (_, r), i in zip(g.iterrows(), pos):
        d = dict(R_t=r.v4n_R, sf_t=r.stop_frac, lev_t=r.v4n_lev, g_t=r.v4n_gross / r.stop_frac, match=ts[i] == r.ts)
        for k, a in atrs.items():
            lev, R, gR, sf = sim(o, h, l, i, int(r.side), a[i], tf)
            d.update({f"lev_{k}": lev, f"R_{k}": R, f"sf_{k}": sf, f"g_{k}": gR})
        rows.append(d)
D = pd.DataFrame(rows)
for k in ("rma", "sma"):
    ok = D[f"R_{k}"].notna() & D.R_t.notna()
    print(tf, k, "n", len(D), "tsmatch", D.match.mean(), "sf reldiff med", (abs(D[f"sf_{k}"] / D.sf_t - 1)).median(),
          "|dR|>1e-3", (abs(D[f"R_{k}"] - D.R_t)[ok] > 1e-3).mean(), "mine", D[f"R_{k}"][ok].mean(), "theirs", D.R_t[ok].mean(),
          "gR mine", D[f"g_{k}"].mean(), "theirs", D.g_t.mean())
