import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = load_xl(sys.argv[1])
SLIP = 0.0002
B = X[(X.variant=="base")]
# slippage in R: entry fill = ref*(1+s*slip) so entry slip = ref*slip; exit slip = exit_raw*slip ~ exit*slip
# exit price not stored; approx: exit_px from pnl: pnl = s*qty*(px-entry) - fees - funding -> px
B = B.copy()
B["px"] = B.entry_price + B.side*(B.pnl + B.fees + B.funding)/B.qty
B["slipR"] = (B.ref_price*SLIP + B.px/(1-B.side*SLIP)*SLIP)/B.dist
B["grossR_fee"] = B.R + B.feeR + B.fundR        # their gross: before fees and funding (slippage still inside)
B["grossR_all"] = B.grossR_fee + B.slipR
B["costR_all"] = B.feeR + B.fundR + B.slipR
B["c6h"] = B.bar_close//(6*3600_000); B["c24h"] = B.bar_close//(24*3600_000); B["c1h"] = B.bar_close//3600_000
for fl in (0,1):
  print("=== flip", fl)
  for grpname, sel in [("house_all", B.kind.isin(["strategy","ds200","random"])), ("core+ds (no random)", B.kind.isin(["strategy","ds200"]))]:
    for tf in ["15m","30m","1h","4h"]:
        g = B[sel & (B.timeframe==tf) & (B.flip==fl)]
        w = g.R>0
        aw, al = g.R[w].mean(), g.R[~w].mean()
        be = -al/(aw-al)
        r6 = cboot(g.R, g.c6h); r1 = cboot(g.R, g.c1h); r24 = cboot(g.R, g.c24h)
        print(f"{grpname:20s} {tf:4s} n {len(g):5d} R {g.R.mean():+.3f} grossR(fee) {g.grossR_fee.mean():+.3f} feeR+fund {(g.feeR+g.fundR).mean():.3f} | slipR {g.slipR.mean():.3f} grossR_all {g.grossR_all.mean():+.3f} costR_all {g.costR_all.mean():.3f} | win {w.mean():.3f} avgW {aw:+.3f} avgL {al:+.3f} BE {be:.3f} | CI1h [{r1['lo']:+.3f},{r1['hi']:+.3f}] CI6h [{r6['lo']:+.3f},{r6['hi']:+.3f}] G6 {r6['G']} CI24h [{r24['lo']:+.3f},{r24['hi']:+.3f}] G24 {r24['G']} open {g.open_end.sum()}")
# per run
print("=== per run, house_all, flip 0")
for (r,tf),g in B[B.flip==0].groupby(["runl","timeframe"]):
    print(r, tf, len(g), round(g.R.mean(),3), round(g.grossR_fee.mean(),3), round(g.grossR_all.mean(),3))
