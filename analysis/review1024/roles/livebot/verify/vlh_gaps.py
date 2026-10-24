"""Verifier (data errors): missing 1m minutes in the grid and how many taken trades of B0/B3/B6/B9 span one (the walk
skips NaN minutes silently). Run (no -I): python3 vlh_gaps.py <trades_dir>"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data"))
from common import *  # noqa: E402,F401,F403

TD = sys.argv[1]
a, b = (ms("2020-03-01") - T0) // MIN, None
nanc = {}
for c in COINS:
    g = grid(c)
    bad = ~np.isfinite(g["o"]) | ~np.isfinite(g["h"]) | ~np.isfinite(g["l"])
    bad[: g["first"]] = False
    nanc[c] = np.cumsum(bad)
    i24 = (ms("2024-01-01") - T0) // MIN
    print(c, "NaN minutes after first:", int(bad.sum()), " since 2024:", int(bad[i24:].sum()))
    drop(c)
for v in ("B0", "B3", "B6", "B9"):
    T = pd.read_csv(f"{TD}/trades_{v}.csv.gz")
    hit = np.zeros(len(T), bool)
    for ci, c in enumerate(COINS):
        m = (T.coin == ci).to_numpy()
        cs = nanc[c]
        e = T.e.to_numpy()[m]
        x = e + T.tb_k.to_numpy()[m]
        hit[m] = cs[np.minimum(x, len(cs) - 1)] - cs[e - 1] > 0
    P = T[(T.t >= ms("2024-01-01"))]
    h = hit[(T.t >= ms("2024-01-01")).to_numpy()]
    print(v, "taken trades spanning a missing minute: all", int(hit.sum()), "of", len(T), "; since 2024", int(h.sum()),
          "mean roe of those %.2f%% vs all %.2f%%" % (100 * P.tb_roe[h].mean() if h.any() else np.nan, 100 * P.tb_roe.mean()))
