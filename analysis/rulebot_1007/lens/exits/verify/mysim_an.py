import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
M = pd.read_csv("mysim_rows.csv")
rs = pd.read_csv(sys.argv[1], low_memory=False, usecols=["run","sig_id","kind","timeframe","bar_close","stop_frac"])
M = M.merge(rs, on=["run","sig_id"])
M["runl"] = M.run.map(RUNL)
M0 = M[(M.flip==0)]
P = M0.pivot_table(index=["run","sig_id"], columns="variant", values="R").join(M0[M0.variant=="base"].set_index(["run","sig_id"])[["timeframe","runl","bar_close"]])
print("my sim (no funding): contrasts in base-stop R")
for a,b in [("geo40","base"),("geo50","base"),("geo10","base"),("RL2_1","base")]:
    for tf in ["15m","30m","1h"]:
        for rl in ["v3b","v4","pooled"]:
            g = P[(P.timeframe==tf)&((P.runl==rl) if rl!="pooled" else True)]
            d = g[a]-g[b]
            r1 = cboot(d, g.bar_close//3600_000); r6 = cboot(d, g.bar_close//(6*3600_000))
            print(f"{a}-{b} {tf} {rl:6s} n {len(d)} {r1['mean']:+.3f} 1h[{r1['lo']:+.3f},{r1['hi']:+.3f}] 6h[{r6['lo']:+.3f},{r6['hi']:+.3f}]")
# own-stop R for stop widths (risk sizing): stopw3 vs base, stopw1.5 vs base
print("own-stop R (risk sizing):")
for tf in ["15m","30m","1h"]:
    for v in ["stopw1.5","base","stopw3"]:
        s = M0[(M0.variant==v)&(M0.timeframe==tf)]
        k = {"stopw1.5":0.75,"base":1.0,"stopw3":1.5}[v]
        feeown = s.fee_R/k; slipown = s.slip_R/k
        print(f" {tf} {v:8s} R_own {s.R_own.mean():+.3f} fee_own {feeown.mean():.3f} slip_own {slipown.mean():.3f} gross_own(before all costs) {(s.R_own+feeown+slipown).mean():+.3f}")
    a = M0[(M0.variant=="stopw3")&(M0.timeframe==tf)].set_index(["run","sig_id"])
    b = M0[(M0.variant=="base")&(M0.timeframe==tf)].set_index(["run","sig_id"])
    d = (a.R_own - b.R_own)
    r6 = cboot(d, b.bar_close//(6*3600_000)); r1 = cboot(d, b.bar_close//3600_000)
    print(f"  stopw3-base own-R {tf} {r1['mean']:+.3f} 1h[{r1['lo']:+.3f},{r1['hi']:+.3f}] 6h[{r6['lo']:+.3f},{r6['hi']:+.3f}]")
