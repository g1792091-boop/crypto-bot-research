import sys, site
sys.path.append(site.getusersitepackages()); sys.path.insert(0, sys.argv[1])
import numpy as np, pandas as pd
from vlib import *
E = EXP + "/current"
start = int(pd.read_csv(E + "/runs.csv").started_ts.min()); end = int(pd.read_csv(E + "/live_bars.csv", usecols=["ts"]).ts.max()); mid = start + (end - start) / 2
R = load_replay()
R["half"] = np.where(R.bar_close < mid, "H1", "H2")
print("4h status by def:"); print(R[R.timeframe == "4h"].groupby("strategy").status.value_counts().unstack(fill_value=0).to_string())
print(R[(R.timeframe == "4h") & (R.status == "REJECTED_SIZING")].reject_reasons.str.slice(0, 90).value_counts().head(5).to_string())
T = R[R.status == "TRADED"]
for tf in ["15m", "30m", "1h"]:
    g = T[T.timeframe == tf]
    e = g[g.acct_status == "ENTERED"]; s = g[g.acct_status == "SKIPPED"]
    # cluster-robust difference via regression on indicator: use cluster bootstrap
    rng = np.random.default_rng(3)
    cl = g.cl1h.values; u = np.unique(cl)
    idx = {c: np.where(cl == c)[0] for c in u}
    isE = (g.acct_status == "ENTERED").values; Rv = g.R.values
    diffs = []
    for _ in range(4000):
        pick = np.concatenate([idx[c] for c in rng.choice(u, len(u))])
        a = Rv[pick][isE[pick]]; b = Rv[pick][~isE[pick]]
        if len(a) and len(b): diffs.append(a.mean() - b.mean())
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    print(tf, "entered %.3f n%d | skipped %.3f n%d | diff %.3f cluster-boot CI [%.2f, %.2f]" % (e.R.mean(), len(e), s.R.mean(), len(s), e.R.mean() - s.R.mean(), lo, hi),
          "| by half entered/skipped:", {h: (round(e[e.half == h].R.mean(), 3), round(s[s.half == h].R.mean(), 3)) for h in ["H1", "H2"]},
          "| long share entered %.2f skipped %.2f" % ((e.side > 0).mean(), (s.side > 0).mean()))
    print("   mean R by half (all signals):", g.groupby("half").R.agg(["size", "mean"]).round(3).to_dict())
# core 36 by half for comparison
C = load_replay(kind="strategy"); C["half"] = np.where(C.bar_close < mid, "H1", "H2")
CT = C[C.status == "TRADED"]
print("core36 by tf/half/side:"); print(CT.groupby(["timeframe", "half", "side"]).R.agg(["size", "mean"]).round(3).unstack("side").to_string())
