import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = pd.read_pickle("xl.pkl")
X = X[(X.flip==0) & X.kind.isin(["strategy","ds200"]) & X.R.notna()]
LEV = {"lev10","lev20m20","lev30m30","lev40m40","lev50m50"}
X = X[~X.variant.isin(LEV)]
P = X.pivot_table(index=["run","sig_id"], columns="variant", values="R")
meta = X[X.variant=="base"].drop_duplicates(["run","sig_id"]).set_index(["run","sig_id"])[["runl","kind","strategy","timeframe","bar_close","symbol","side","atr"]]
P = P.join(meta, how="inner")
menu_all = [c for c in P.columns if c not in meta.columns]
AI5 = ["base","geo20_bar","RL1_0.5_bar","RL1.5_1_bar","tp1R"]
v4 = P[P.runl=="v4"]; mid = v4.bar_close.median()
splits = {"v3b->v4 core": (P[(P.runl=="v3b")&(P.kind=="strategy")], P[(P.runl=="v4")&(P.kind=="strategy")]),
          "v4 H1->H2": (v4[v4.bar_close<=mid], v4[v4.bar_close>mid]),
          "v4 H2->H1": (v4[v4.bar_close>mid], v4[v4.bar_close<=mid])}
rng = np.random.default_rng(11)
for min_n in (8, 15):
  for sname,(A,B) in splits.items():
    for mname, menu in (("ALL", menu_all), ("AI5", AI5)):
        ga_ = A.groupby(["strategy","timeframe"]); gb_ = dict(list(B.groupby(["strategy","timeframe"])))
        ins, oos, pooled_pick = [], [], []
        # global (pooled) pick: one exit for all cells chosen on A
        gpick = A[menu].mean().idxmax()
        for key, ga in ga_:
            gb = gb_.get(key)
            if gb is None or len(ga) < min_n or len(gb) < min_n: continue
            m = ga[menu].mean(); pk = m.idxmax()
            ins.append(m[pk]-m["base"]); oos.append(gb[pk].mean()-gb["base"].mean()); pooled_pick.append(gb[gpick].mean()-gb["base"].mean())
        o = np.array(oos); bs = [rng.choice(o, len(o)).mean() for _ in range(3000)]
        print(f"min_n {min_n} {sname:13s} {mname} cells {len(o):3d} IS {np.mean(ins):+.3f} OOS {o.mean():+.3f} [{np.percentile(bs,2.5):+.3f},{np.percentile(bs,97.5):+.3f}] share better {np.mean(o>1e-9):.2f} | global pick {gpick} OOS {np.mean(pooled_pick):+.3f}")
