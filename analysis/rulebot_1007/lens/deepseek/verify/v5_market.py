import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from scipy import stats
from vlib import *
E = EXP + "/current"
B = pd.read_csv(E + "/live_bars.csv", usecols=["ts", "symbol", "close"])
P = B.pivot_table(index="ts", columns="symbol", values="close").sort_index().ffill()
start = int(pd.read_csv(E + "/runs.csv").started_ts.min()); end = int(B.ts.max()); mid = start + (end - start) / 2
lr = np.log(P / P.iloc[0])
ew = lr.mean(axis=1)
kst = lambda ms: (pd.to_datetime(ms, unit="ms") + pd.Timedelta(hours=9)).strftime("%m/%d %H:%M")
im = ew.index.searchsorted(mid)
print("EW log-return H1 %.2f%%  H2 %.2f%%  total %.2f%%" % (100 * ew.iloc[im], 100 * (ew.iloc[-1] - ew.iloc[im]), 100 * ew.iloc[-1]))
# path every 3h
for t in range(0, len(ew), 180):
    print(kst(ew.index[t]), "%.2f" % (100 * ew.iloc[t]))
print(kst(ew.index[-1]), "%.2f" % (100 * ew.iloc[-1]))
# max run-up/drawdown on EW
cm = ew.cummax(); print("EW max DD %.2f%%" % (100 * (ew - cm).min()))
# cell R^2 of mean on long share
X = pd.read_csv(sys.argv[1] + "/my_testable.csv")
z = X[X.tf.isin(["15m", "30m"])]
for tf, zz in z.groupby("tf"):
    w = zz.n.values; x = zz.long.values; y = zz["mean"].values
    b = np.polyfit(x, y, 1, w=np.sqrt(w)); yh = np.polyval(b, x)
    r2 = 1 - np.average((y - yh) ** 2, weights=w) / np.average((y - np.average(y, weights=w)) ** 2, weights=w)
    print(tf, "weighted R2 of cell mean on long share %.2f slope %.2f" % (r2, b[0]))
    # side-balanced vs raw correlation
    sb = 0.5 * (zz.mL + zz.mS)
    print("   rho(raw mean, side-balanced)", np.round(stats.spearmanr(zz["mean"], sb, nan_policy="omit"), 3))
