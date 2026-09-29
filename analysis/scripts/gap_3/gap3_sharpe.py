"""Annualised Sharpe needed for a median x20/month vs realised daily-portfolio Sharpe of each candidate.
Theory (continuous-time Kelly): growth at fraction c of Kelly = (c - c^2/2) * SR^2 per unit time.
Median x20 in one month  <=>  (c - c^2/2) * SR_month^2 >= ln 20."""
import os, sys, math
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gap3_kelly as G
L20 = math.log(20)
for c in (1.0, 0.5):
    srm = math.sqrt(L20 / (c - c * c / 2)); print(f"fraction {c} of Kelly: x20/month needs SR_month {srm:.2f} = annual SR {srm*math.sqrt(12):.2f}")
for sr in (1, 2, 3, 5):
    for c in (1.0, 0.5):
        print(f"  annual SR {sr}: median monthly multiple at {c:.1f} Kelly = {math.exp((c-c*c/2)*sr*sr/12):.3f}")
A = G.load_ledgers()
order = [f"{s}|{e}" for s, e in G.WANT15 + G.WANT5] + ["B_IS|maker64_nostop", "B_OOS|maker64_nostop"]
print("\nrealised daily-portfolio Sharpe (all symbols concurrent, 1 unit notional per position, PnL booked on exit day)")
for key in order:
    g = A[A.key == key]
    days = pd.date_range(g.entry_ts.min().floor("D"), g.exit_ts.max().floor("D"), freq="D")
    Rd = g.groupby(g.exit_ts.dt.floor("D"))["net"].sum().reindex(days, fill_value=0.0)
    sr = Rd.mean() / Rd.std(ddof=1) * math.sqrt(365)
    se = math.sqrt((1 + 0.5 * (sr / math.sqrt(365)) ** 2) / len(Rd)) * math.sqrt(365)
    # same with trades mean-shifted to +0.05% / +0.10%
    out = []
    for t in (0.0005, 0.0010):
        y = g.net - g.net.mean() + t
        R2 = y.groupby(g.exit_ts.dt.floor("D")).sum().reindex(days, fill_value=0.0)
        out.append(R2.mean() / R2.std(ddof=1) * math.sqrt(365))
    print(f"  {key:32s} days {len(Rd):4d}  SR_ann realised {sr:+.2f} (+-{1.96*se:.2f})   at mu=+0.05%: {out[0]:.2f}   at +0.10%: {out[1]:.2f}")
