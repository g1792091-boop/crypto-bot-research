import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = load_xl(sys.argv[1])
X = X[X.flip==0]
SIZE = {"lev10","lev20m20","lev30m30","lev40m40","lev50m50"}
X = X[~X.variant.isin(SIZE)]
print("n variants incl base:", X.variant.nunique())
T = X.groupby(["timeframe","variant","runl"]).R.mean().unstack("runl")
P = X.groupby(["timeframe","variant"]).R.mean().rename("pooled")
T = T.join(P)
T.to_csv("x1_exit_means.csv")
for tf in ["15m","30m","1h","4h"]:
    t = T.loc[tf]
    both = t[(t.v3b>0)&(t.v4>0)]
    print(tf, "pooled range", round(t.pooled.min(),3), t.pooled.idxmin(), round(t.pooled.max(),3), t.pooled.idxmax(),
          "| best v3b", round(t.v3b.max(),3), t.v3b.idxmax(), "best v4", round(t.v4.max(),3), t.v4.idxmax(), "| positive both runs:", list(both.index))
# pnl-on-equity and also the share of exits better than base per run
