import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from scipy import stats
from vlib import *
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 60); pd.set_option("display.max_rows", 300)
E = EXP + "/current"
start = int(pd.read_csv(E + "/runs.csv").started_ts.min())
end = int(pd.read_csv(E + "/live_bars.csv", usecols=["ts"]).ts.max())
mid = start + (end - start) / 2
R = load_replay()
T = R[R.status == "TRADED"].copy()
T["half"] = np.where(T.bar_close < mid, "H1", "H2")
rows = []
for (s, tf), g in T.groupby(["strategy", "timeframe"]):
    c = crse(g.R, g.cl1h); c4 = crse(g.R, g.cl4h)
    d = dict(strategy=s, tf=tf, n=c["n"], G=c["G"], mean=c["mean"], lo=c.get("lo"), hi=c.get("hi"), p_gt=c.get("p_gt"), p_lt=c.get("p_lt"),
             G4=c4["G"], p_gt4=c4.get("p_gt"), p_lt4=c4.get("p_lt"), long=(g.side > 0).mean(),
             nL=(g.side > 0).sum(), nS=(g.side < 0).sum(), mL=g[g.side > 0].R.mean(), mS=g[g.side < 0].R.mean(),
             h1=g[g.half == "H1"].R.mean(), h2=g[g.half == "H2"].R.mean(), nh1=(g.half == "H1").sum(), nh2=(g.half == "H2").sum(),
             exbest=(g.R.sum() - g.R.max()) / (len(g) - 1) if len(g) > 1 else np.nan)
    rows.append(d)
C = pd.DataFrame(rows)
C["testable"] = (C.n >= 10) & (C.G >= 8)
X = C[C.testable].copy()
print("testable by tf", X.groupby("tf").size().to_dict(), "total", len(X))
X["q_gt"] = bhq(X.p_gt.values); X["q_lt"] = bhq(X.p_lt.values)
print("min q_gt", X.q_gt.min().round(3), "min p_gt", X.p_gt.min().round(4), X.loc[X.p_gt.idxmin(), ["strategy", "tf", "n", "mean"]].tolist())
print("q_lt<=0.10:"); print(X[X.q_lt <= 0.10][["strategy", "tf", "n", "G", "mean", "lo", "hi", "p_lt", "q_lt", "long", "p_lt4"]].round(4).to_string())
# 4h-cluster BH for comparison (G4>=3)
Y4 = X[X.p_lt4.notna()].copy(); Y4["q_lt4"] = bhq(Y4.p_lt4.values); Y4["q_gt4"] = bhq(Y4.p_gt4.values)
print("with 4h clusters: q_lt4<=0.10:", Y4[Y4.q_lt4 <= 0.10][["strategy", "tf", "q_lt4"]].values.tolist(), " min q_gt4", Y4.q_gt4.min().round(3))
# long share vs mean
for tfs in (["15m", "30m"], ["15m"], ["30m"]):
    z = X[X.tf.isin(tfs)]
    r = stats.spearmanr(z.long, z["mean"]); print("long-share vs mean", tfs, len(z), np.round(r, 4))
for tfs in (["15m"], ["30m"], ["15m", "30m", "1h", "4h"]):
    z = X[X.tf.isin(tfs)].dropna(subset=["h1", "h2"])
    r = stats.spearmanr(z.h1, z.h2); print("H1 vs H2", tfs, len(z), np.round(r, 4))
# dedup check: remove merged children
kids = {"F5_BOX_HTF", "F13_RAID_PD", "F11_TSOUP", "F17_Z_HL", "F12_MSS_DISP", "F13_FVG_PD", "F10_M2022", "F16_FIB618", "F7_RF_ONLY"}
z = X[X.tf.isin(["15m", "30m"]) & ~X.strategy.isin(kids)]
print("dedup long-share vs mean", len(z), np.round(stats.spearmanr(z.long, z["mean"]), 4))
z = X[X.tf.isin(["15m"]) & ~X.strategy.isin(kids)].dropna(subset=["h1", "h2"])
print("dedup H1 vs H2 15m", len(z), np.round(stats.spearmanr(z.h1, z.h2), 4))
# null check for H1 vs H2: permutation of side labels? Simulate: within each cell, what does side composition predict?
# predicted cell mean in each half from long share x side-mean of all ds200 at tf/half
sm = T.groupby(["timeframe", "half", "side"]).R.mean()
def pred(row, h):
    g = T[(T.strategy == row.strategy) & (T.timeframe == row.tf) & (T.half == h)]
    if not len(g): return np.nan
    return np.mean([sm[(row.tf, h, s)] for s in g.side])
X["p1"] = [pred(r, "H1") for r in X.itertuples()]; X["p2"] = [pred(r, "H2") for r in X.itertuples()]
z = X[X.tf == "15m"].dropna(subset=["h1", "h2"])
print("15m predicted-by-side-composition H1 vs H2 rho", np.round(stats.spearmanr(z.p1, z.p2), 3), " resid rho", np.round(stats.spearmanr(z.h1 - z.p1, z.h2 - z.p2), 3))
z = X[X.tf.isin(["15m", "30m"])]
print("corr(mean, side-composition-predicted full-window mean)", np.round(stats.spearmanr(z["mean"], [np.mean([0]) for _ in range(len(z))]) if False else 0, 3))
C.to_csv(sys.argv[1] + "/my_cells.csv", index=False)
X.to_csv(sys.argv[1] + "/my_testable.csv", index=False)
