import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from scipy import stats
from vlib import *
X = pd.read_csv(sys.argv[1] + "/my_testable.csv")
TE = pd.read_csv(OUT_REAL + "/trades_enriched.csv"); TE = TE[(TE.run == "current") & (TE.kind == "ds200")]
aR = TE.groupby("account_id").R.mean()
R = load_replay(); T = R[R.status == "TRADED"].copy(); T["aid"] = T.strategy + "@" + T.timeframe
sk = T[T.acct_status != "ENTERED"].groupby("aid").R.mean()
X["aid"] = X.strategy + "@" + X.tf
X["acct"] = X.aid.map(aR); X["skip"] = X.aid.map(sk)
for tf in ["15m", "30m", None]:
    z = X if tf is None else X[X.tf == tf]
    z = z.dropna(subset=["acct"])
    print(tf, len(z), "acct vs replay", np.round(stats.spearmanr(z.acct, z["mean"]), 3), " acct vs skipped-only", np.round(stats.spearmanr(z.acct, z.skip, nan_policy="omit"), 3))
