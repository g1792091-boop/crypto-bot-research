"""Descriptive anatomy of the best near-miss cell (N13_3OUTSIDE 4h, approx port). IS only. No decision."""
import os, sys
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["SWEEP_DATA"] = os.path.join(HERE, "data")
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as SL
g = pd.read_csv("out/gate_all_is_applied.csv")
r = g[(g.strategy == "N13_3OUTSIDE") & (g.tf == "4h")]
cols = ["H", "n", "n_long", "n_short", "fwd", "fwd_long", "fwd_short", "mu_star", "z", "p", "z_vn", "p_vn"] + \
       [f"n_{c}" for c in SL.COINS] + [f"fwd_{c}" for c in SL.COINS]
pd.set_option("display.width", 250)
print(r[cols].T.to_string())
panel = SL.load_panel("4h", "is")
sigs = SL.compute_signals(panel, "4h", ["N13_3OUTSIDE"])
rows = []
for c, df in panel.items():
    lo, hi = SL.signal_window(df, "4h", "is", 16)
    d = sigs["N13_3OUTSIDE"][c]
    o = df["open"].to_numpy()
    for t in np.flatnonzero(d[lo:hi]) + lo:
        rows.append(dict(sym=c, ts=df["ts"].iloc[t], side=int(d[t]), r16=d[t] * (o[t + 17] / o[t + 1] - 1),
                         bar_range=(df["high"].iloc[t] - df["low"].iloc[t]) / df["close"].iloc[t]))
x = pd.DataFrame(rows)
x["year"] = x.ts.dt.year
x["half"] = x.ts.dt.year.astype(str) + "H" + ((x.ts.dt.month > 6) + 1).astype(str)
print("\nH16 signed fwd by half-year (mean %, n):")
print(x.groupby("half").r16.agg(["count", "mean"]).assign(mean=lambda d: 100 * d["mean"]).round(3).to_string())
print("\nH16 by side:"); print(x.groupby("side").r16.agg(["count", "mean", "median"]).round(4).to_string())
print("\ntop-10 signals' share of total signed return (H16): %.2f" % (x.r16.nlargest(10).sum() / x.r16.sum()))
print("median H16 signed return (%%): %.3f ; mean: %.3f" % (100 * x.r16.median(), 100 * x.r16.mean()))
# volatility timing: signal bar range vs coin median bar range
med = {c: ((df.high - df.low) / df.close).median() for c, df in panel.items()}
x["range_rel"] = x.apply(lambda q: q.bar_range / med[q.sym], axis=1)
print("signal bar range / coin median bar range: median %.2f, mean %.2f" % (x.range_rel.median(), x.range_rel.mean()))
x.to_csv("out/diag_n13_4h_signals_h16.csv", index=False)
