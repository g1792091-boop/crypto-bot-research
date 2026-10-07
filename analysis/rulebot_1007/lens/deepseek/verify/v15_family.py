import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from vlib import *
R = load_replay(); T = R[R.status == "TRADED"].copy()
T["fam"] = T.strategy.str.split("_").str[0]
rng = np.random.default_rng(5)
def signflip(v, cl, B=20000):
    s = pd.Series(v).groupby(np.asarray(cl)).sum().to_numpy(); obs = v.sum()
    sims = (s[None, :] * rng.choice((-1.0, 1.0), size=(B, len(s)))).sum(1)
    return (1 + np.sum(sims >= obs - 1e-12)) / (B + 1)
for fam in ["F1", "F6", "F9", "F14", "F4", "F11", "F16", "F17", "F8", "F13"]:
    for tf in ["15m", "30m"]:
        g = T[(T.fam == fam) & (T.timeframe == tf)].drop_duplicates(["bar_close", "symbol", "side"])
        if len(g) < 3: continue
        c = crse(g.R, g.cl1h); c4 = crse(g.R, g.cl4h)
        x = g[g.flip_status == "TRADED"].copy(); x["h"] = 0.5 * (x.R - x.flip_R)
        Lm = x.side > 0
        dn = 0.5 * (x.h[Lm].mean() + x.h[~Lm].mean()) if Lm.sum() >= 3 and (~Lm).sum() >= 3 else np.nan
        w = np.where(Lm, 0.5 / max(Lm.sum(), 1), 0.5 / max((~Lm).sum(), 1))
        p_dn = signflip(x.h.values * w, x.cl1h.values) if dn == dn else np.nan
        print(fam, tf, "unique n", len(g), "per day %.1f" % (len(g) / 1.503), "mean %.3f CI1h [%.2f, %.2f] CI4h [%.2f, %.2f]" % (c["mean"], c["lo"], c["hi"], c4.get("lo", np.nan), c4.get("hi", np.nan)),
              "drift-neutral flip %.3f p %.3f" % (dn, p_dn), "long %.2f" % (g.side > 0).mean())
