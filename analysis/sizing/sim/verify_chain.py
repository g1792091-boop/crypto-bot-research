"""Sequential re-simulation of seeds 0-1 for a few (edge, combo) cells; compare to run_sim outputs in out/test."""
import json, numpy as np
from simlib import *
for tf in ["4h", "15m"]:
    meta = json.load(open(f"out/test/{tf}_meta.json"))
    st = np.load(f"out/test/{tf}_stats.npz"); ST = st["ST"]; names = list(st["names"])
    daily = np.load(f"out/test/{tf}_daily.npy"); dmin = np.load(f"out/test/{tf}_dmin.npy")
    P = Panel(tf)
    COMBOS = meta["combos"]; EDG = meta["edges"]; q = np.array(meta["q"])
    worst = 0
    for s in range(2):
        rng = np.random.default_rng([P.tfm, s, 20260929])
        gi, ci, ti = P.draw_candidates(rng)
        n = len(gi); u = rng.random(n); rs = np.where(rng.random(n) < 0.5, 1, -1)
        pp = P.paths(ci, ti)
        orc = np.sign(pp["rH"]).astype(int); orc = np.where(orc == 0, rs, orc)
        for e in [0, 4, 7]:
            side = np.where(u < q[e][ci], orc, rs)
            for cname in ["P0|B|10", "P3|A|10", "P4|A|10", "P5|C|10", "P6|B|none"]:
                j = COMBOS.index(cname)
                M, L, N, dl, sd, td = policy_params(cname, pp["atr"])
                k, cc, gg, r, y = outcomes(pp, side, M, L, N, dl, sd, td, P.tfm)
                free = -1; eq = 0.0; ntr = 0; nliq = 0; mn = 0.0; peak = 0.0; mdd = 0.0
                for i in range(n):
                    if P.grid[gi[i]] < free: continue
                    ntr += 1; nliq += cc[i] == 3
                    eq += np.log1p(max(r[i], -0.999999)); mn = min(mn, eq); peak = max(peak, eq); mdd = max(mdd, peak - eq)
                    free = pp["ts_bar"][i, k[i] - 1]
                got = ST[:, e, j, s]
                d = [abs(got[0] - ntr), abs(got[1] - nliq), abs(got[13] - eq), abs(got[14] - mn), abs(got[15] - mdd), abs(daily[e, j, s].sum() - eq)]
                worst = max(worst, max(d))
                if max(d) > 1e-6: print("MISMATCH", tf, s, e, cname, d)
    print(tf, "max abs diff", worst)
