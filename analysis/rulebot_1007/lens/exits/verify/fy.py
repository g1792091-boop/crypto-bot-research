import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
d = json.load(open(sys.argv[1]))
cols = d["columns"]; mf = {int(k): v for k, v in d["margin_frac"].items()}
rows = []
for cell, arms in d["cells"].items():
    strat, tf = cell.split("|")
    for arm, vals in arms.items():
        lm, st = arm.split("|")
        r = dict(zip(cols, vals)); r.update(strat=strat, tf=tf, lev=lm, stop=float(st)); rows.append(r)
D = pd.DataFrame(rows)
F = D[D.lev!="tiers"].copy(); F["L"] = F.lev.astype(int)
F["pn_bps"] = F.mean_eq/(F.L.map(mf)*F.L)*1e4
for tf in ["15m","30m","1h","4h"]:
    g = F[F.tf==tf]
    piv = g.pivot_table(index=["strat","stop"], columns="L", values="pn_bps")
    sig = g.pivot_table(index=["strat","stop"], columns="L", values="signals")
    out = []
    for st in [1.5,2.0,2.5,3.0]:
        p = piv.xs(st, level="stop").dropna(); s = sig.xs(st, level="stop")[30].reindex(p.index)
        w = lambda L: np.average(p[L], weights=s)
        out.append(f"stop{st}: 30x {w(30):+.2f}bps | " + " ".join(f"{L}x-30x {w(L)-w(30):+.2f} beat {(p[L]>p[30]).sum()}/{len(p)}" for L in (10,20,40,50)))
    print(tf, "\n  " + "\n  ".join(out))
    g2 = g[(g.stop==2.0)]
    print("  liq share 2ATR by L:", g2.groupby("L").apply(lambda q: round(np.average(q.liq_share, weights=q.signals),4)).to_dict())
