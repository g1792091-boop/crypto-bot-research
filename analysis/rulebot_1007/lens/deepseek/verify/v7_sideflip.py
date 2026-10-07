import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from vlib import *
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 60)
SF = pd.read_csv(OUT_REAL + "/coinflip_sideflip.csv")
print(SF[SF.level.isin(["kind_tf", "kind"]) & (SF.kind == "ds200")][["level", "timeframe", "n_pairs", "n_clusters", "excess_R", "p_better"]].round(4).to_string())
x = SF[(SF.level == "strategy_tf") & (SF.kind == "ds200")]
print("ds200 strategy_tf cells", len(x), "min bh_q_better", x.bh_q_better.min())
rng = np.random.default_rng(11)
def signflip(v, cl, B=20000):
    s = pd.Series(v).groupby(np.asarray(cl)).sum().to_numpy(); obs = v.sum()
    sims = (s[None, :] * rng.choice((-1.0, 1.0), size=(B, len(s)))).sum(1)
    return (1 + np.sum(sims >= obs - 1e-12)) / (B + 1)
for kind in ["ds200", "strategy"]:
    R = load_replay(kind=kind)
    x = R[(R.status == "TRADED") & (R.flip_status == "TRADED")].copy()
    x = x[np.isfinite(x.R) & np.isfinite(x.flip_R)]
    x["h"] = 0.5 * (x.R - x.flip_R)
    for tf, g in list(x.groupby("timeframe")) + [("all", x)]:
        L = g.side > 0; nL, nS = L.sum(), (~L).sum()
        raw = g.h.mean()
        dn = 0.5 * (g.h[L].mean() + g.h[~L].mean())
        w = np.where(L, 0.5 / nL, 0.5 / nS)
        p_raw = signflip(g.h.values / len(g), g.cl1h.values)
        p_dn = signflip(g.h.values * w, g.cl1h.values)
        p_dn4 = signflip(g.h.values * w, g.cl4h.values)
        print(kind, tf, "n", len(g), "G", g.cl1h.nunique(), "long", round(L.mean(), 3), "raw %.4f p %.3f | drift-neutral %.4f p %.3f (4h-cl p %.3f) | exL %.3f exS %.3f" % (raw, p_raw, dn, p_dn, p_dn4, g.h[L].mean(), g.h[~L].mean()))
