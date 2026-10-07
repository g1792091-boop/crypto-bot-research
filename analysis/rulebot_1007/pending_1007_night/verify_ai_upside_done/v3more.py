"""verify3 extra checks (AIH-2..6, 8, 9, 10). python3 -I v3more.py <v3sig.csv>"""
import sys, site
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
sys.path.insert(0, sys.argv[0].rsplit("/", 1)[0])
from v3st_lib import ctest

MIN = 60_000
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
R = pd.read_csv(sys.argv[1])
R = R[R["base_st"].isin(["T", "U"]) & R["kind"].isin(["strategy", "ds200"])].copy()
R["cl"] = R["run"] + "|" + (R["bar_close"] // (np.maximum(R["timeframe"].map(TFM), 60) * MIN)).astype(str)
K = {"strategy": "core", "ds200": "ds"}


def rep(lbl, g, d):
    d = np.asarray(d, float); f = np.isfinite(d)
    if f.sum() < 5:
        print(lbl, "n", f.sum()); return
    o, lo, hi, p, nc = ctest(d[f], g["cl"].to_numpy()[f])
    rr = {r: np.nanmean(d[(g["run"] == r).to_numpy() & f]) for r in ("v3b", "v4")}
    print(f"{lbl}: n={f.sum()} ncl={nc} mean={o:+.3f} CI[{lo:+.3f},{hi:+.3f}] p={p:.3f} v3b={rr['v3b']:+.3f} v4={rr['v4']:+.3f}")


print("== AIH-3 state exit at 4 bars, hold minus exit (base_R - X4_R)")
for tf in ("15m", "30m", "1h"):
    for th in (-0.3, -0.5, -0.7):
        g = R[(R.timeframe == tf) & (R.base_u4 <= th)]
        rep(f"{tf} u4<={th}", g, g.base_R - g.X4_R)
    g = R[(R.timeframe == tf) & R.base_u4.notna()]
    print(f"  {tf} open at 4 bars {len(g)}; share u4<=-0.5 {np.mean(g.base_u4 <= -0.5):.3f}")
print("== AIH-2 disposition: open at 2 bars with u2>=+0.3, hold minus exit (15m)")
for k in K:
    g = R[(R.kind == k) & (R.timeframe == "15m") & (R.base_u2 >= 0.3)]
    rep(f"{K[k]} 15m", g, g.base_R - g.X2_R)
g = R[(R.timeframe == "15m") & (R.base_u2 >= 0.3)]
rep("all 15m", g, g.base_R - g.X2_R)
print("== AIH-10 core 15m all open at 2 bars hold-exit")
g = R[(R.kind == "strategy") & (R.timeframe == "15m") & R.base_u2.notna()]
rep("core15 all open", g, g.base_R - g.X2_R)
print("== AIH-4/5 giveback + headroom")
for (k, tf), g in R[R.timeframe.isin(["15m", "30m", "1h"])].groupby(["kind", "timeframe"]):
    sl = g.base_ex.eq("SL")
    hb = np.where((g.base_R < 0) & (g.base_mfe >= 0.5), -g.base_R,
                  np.where((g.base_R < -0.5) & (g.base_mfe < 0.2), -0.5 - g.base_R, 0)).mean()
    los = g.base_R < 0
    print(f"{K[k]} {tf} n={len(g)} reach.5thenSL={np.mean(sl & (g.base_mfe >= 0.5)):.3f} reach1thenSL={np.mean(sl & (g.base_mfe >= 1)):.3f}"
          f" headroomUB={hb:.3f} MFEexitUB={np.mean(np.maximum(g.base_mfe,0) - g.base_R):.2f} losers_dead(mfe<.2)={np.mean(g.base_mfe[los] < 0.2):.2f}")
print("== AIH-6 stability of per-cell headroom and rule gain (core, >=10 per run)")
R["hb"] = np.where((R.base_R < 0) & (R.base_mfe >= 0.5), -R.base_R,
                   np.where((R.base_R < -0.5) & (R.base_mfe < 0.2), -0.5 - R.base_R, 0))
R["gCUT"] = R.CUT05_R - R.base_R
for tf in ("15m", "30m"):
    c = R[(R.kind == "strategy") & (R.timeframe == tf)].groupby(["strategy", "run"]).agg(
        n=("hb", "size"), hb=("hb", "mean"), b=("base_R", "mean"), cut=("gCUT", "mean")).unstack()
    c = c[(c["n"]["v3b"] >= 10) & (c["n"]["v4"] >= 10)]
    sp = lambda a, b: pd.Series(a).rank().corr(pd.Series(b).rank())
    print(tf, "cells", len(c), "rho headroom", round(sp(c.hb.v3b.values, c.hb.v4.values), 2),
          "rho base", round(sp(c.b.v3b.values, c.b.v4.values), 2), "rho CUTgain", round(sp(c.cut.v3b.values, c.cut.v4.values), 2))
    a = R[(R.kind == "strategy") & (R.timeframe == tf)].groupby("strategy").agg(n=("hb", "size"), b=("base_R", "mean"), cut=("gCUT", "mean"))
    a = a[a.n >= 10]
    print("   across cells rho(CUT gain, base) pooled", round(sp(a.cut.values, a.b.values), 2), "n", len(a))
print("== AIH-8 late entry minus on-time (paired, both traded)")
for k, tf in (("strategy", "15m"), ("strategy", "30m"), ("strategy", "1h"), ("ds200", "15m")):
    for L in (1, 4):
        g = R[(R.kind == k) & (R.timeframe == tf) & R[f"late{L}_st"].isin(["T", "U"])]
        rep(f"{K[k]} {tf} late{L}", g, g[f"late{L}_R"] - g.base_R)
print("== AIH-9 leverage pairs")
for k, tf in (("strategy", "15m"), ("strategy", "30m"), ("strategy", "1h"), ("ds200", "15m"), ("ds200", "30m")):
    g0 = R[(R.kind == k) & (R.timeframe == tf)]
    ok = {L: g0[f"lev{L}_st"].isin(["T", "U"]) for L in (20, 30, 40)}
    print(f"{K[k]} {tf} n={len(g0)} sizable20/30/40={ok[20].sum()}/{ok[30].sum()}/{ok[40].sum()}")
    for a, b in ((30, 20), (40, 30)):
        g = g0[ok[a] & ok[b]]
        rep(f"   {a}x-{b}x R", g, g[f"lev{a}_R"] - g[f"lev{b}_R"])
