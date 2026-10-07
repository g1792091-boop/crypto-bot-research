import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from scipy import stats
from vlib import *
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 200)
Y = pd.read_csv(sys.argv[2])
print(Y.shape, Y.entry.nunique(), Y.groupby("tf").entry.nunique().to_dict())
# pooled mean over periods 1+2: check mean12 = weighted
Y["m12chk"] = (Y.is_mean_pct * Y.is_n + Y.cf_mean_pct * Y.cf_n) / (Y.is_n + Y.cf_n)
print("mean12 check max diff", float((Y.m12chk - Y.mean12_pct).abs().max()))
for tf in ["15m", "30m"]:
    y = Y[Y.tf == tf]
    print(tf, "rows", len(y), "mean12>0:", int((y.mean12_pct > 0).sum()), "max", y.mean12_pct.max().round(4),
          y.loc[y.mean12_pct.idxmax(), ["entry", "exit"]].tolist(), " is>0", int((y.is_mean_pct > 0).sum()), "cf>0", int((y.cf_mean_pct > 0).sum()), "pre>0", int((y.pre_mean_pct > 0).sum()))
    # best per definition
    b = y.groupby("entry").mean12_pct.max()
    print("   defs", len(b), "best-of-2 >0:", int((b > 0).sum()), "max", round(b.max(), 4), b.idxmax(), "min", round(b.min(), 4), b.idxmin(), "median", round(b.median(), 4))
for c in ["stage1", "stage1_top", "stage2", "stage3", "bh12", "candidate", "weak_candidate", "all3_positive"]:
    print(c, int(Y[c].sum()))
print(Y[Y.stage1 | Y.all3_positive][["tf", "entry", "exit", "is_n", "cf_n", "pre_n", "is_mean_pct", "cf_mean_pct", "pre_mean_pct", "is_half1_mean_pct", "is_half2_mean_pct", "is_coins_pos", "is_coins_n", "is_p", "stage1", "all3_positive"]].round(3).to_string())
# tf weighted net and gross
for tf, y in Y.groupby("tf"):
    w1, w2 = y.is_n, y.cf_n
    print(tf, "net P1 %.4f P2 %.4f  gross P1 %.4f P2 %.4f  cost P1 %.4f" % (np.average(y.is_mean_pct, weights=w1), np.average(y.cf_mean_pct, weights=w2),
          np.average(y.is_gross_mean_pct, weights=w1), np.average(y.cf_gross_mean_pct, weights=w2), np.average(y.is_cost_mean_pct, weights=w1)),
          " unweighted net P1 %.4f" % y.is_mean_pct.mean())
# DS8: persistence across periods. Exit picked on period 1 per definition x tf
rows = []
for tf, y in Y.groupby("tf"):
    pick = y.loc[y.groupby("entry").is_mean_pct.idxmax()]
    r12 = stats.spearmanr(pick.is_mean_pct, pick.cf_mean_pct)
    r13 = stats.spearmanr(pick.is_mean_pct, pick.pre_mean_pct, nan_policy="omit")
    # also: same exit fixed
    out = dict(tf=tf, n=len(pick), rho12=r12[0], p12=r12[1], rho13=r13[0], p13=r13[1])
    for ex in ["X5_TRAIL2", "X2_SL15_TP3"]:
        z = y[y.exit == ex]
        out[f"rho12_{ex[:2]}"] = stats.spearmanr(z.is_mean_pct, z.cf_mean_pct)[0]
        out[f"rho23_{ex[:2]}"] = stats.spearmanr(z.cf_mean_pct, z.pre_mean_pct, nan_policy="omit")[0]
    rows.append(out)
print(pd.DataFrame(rows).round(3).to_string())
# DS9: positive best-exit mean12 cells
b = Y.groupby(["entry", "tf"]).agg(best=("mean12_pct", "max")).reset_index()
pos = b[b.best > 0].sort_values("best", ascending=False)
print("positive best mean12 cells:", len(pos)); print(pos.round(4).to_string())
print("positive mean12 configs:", int((Y.mean12_pct > 0).sum()))
