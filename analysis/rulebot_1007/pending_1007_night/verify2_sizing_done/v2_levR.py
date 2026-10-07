"""Z3 check: same signal, different leverage (fy36 tw = old tier walk vs v4n = 30/20 normal), paired R diff,
week-cluster bootstrap. python3 -I -B v2_levR.py <fy36_dir>"""
import sys, os
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
FY = sys.argv[1]
rng = np.random.default_rng(7)
for tf in ("15m", "30m", "1h", "4h"):
    d = pd.read_pickle(os.path.join(FY, f"fy36_{tf}.pkl.gz"))
    d = d[d.tw_done & d.v4n_done & (d.tw_lev > 0) & (d.v4n_lev > 0)]
    d = d[np.isfinite(d.tw_R) & np.isfinite(d.v4n_R)]
    wk = (d.ts.values // (7 * 86400 * 10**9))
    for (a, b), g in d.groupby(["tw_lev", "v4n_lev"]):
        if a == b or len(g) < 2000:
            continue
        diff = (g.tw_R - g.v4n_R).values.astype(float)
        w = wk[g.index.map(d.index.get_loc)] if False else (g.ts.values // (7 * 86400 * 10**9))
        u, inv = np.unique(w, return_inverse=True)
        s = np.bincount(inv, diff); c = np.bincount(inv)
        bs = []
        for _ in range(500):
            k = rng.integers(0, len(u), len(u))
            bs.append(s[k].sum() / c[k].sum())
        lo, hi = np.quantile(bs, [.025, .975])
        win_a = (g.tw_R > 0).mean(); win_b = (g.v4n_R > 0).mean()
        print(f"{tf} tw {a}x vs v4n {b}x n={len(g)} meanR {g.tw_R.mean():+.4f} vs {g.v4n_R.mean():+.4f} "
              f"diff {diff.mean():+.4f} [{lo:+.4f},{hi:+.4f}] win {win_a:.3f} vs {win_b:.3f} "
              f"minR {g.tw_R.min():.2f} vs {g.v4n_R.min():.2f}")
