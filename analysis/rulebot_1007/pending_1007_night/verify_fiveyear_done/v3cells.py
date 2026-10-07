"""verify3 cell-level live vs 5y: rank agreement, live-positive count vs expected, frequency. python3 -I -B v3cells.py <out_real> <agg_cells> <their_out>"""
import os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
from math import erf, sqrt
RD, AC, TH = sys.argv[1:4]
Phi = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
C = pd.read_csv(AC)
rep = pd.read_csv(os.path.join(RD, "replay_signals.csv"))
rep = rep[rep.run.isin(["current", "run-20261005T183457Z"]) & rep.kind.isin(["strategy", "ds200"])].copy()
rep["k"] = np.where(rep.kind == "strategy", "core", "ds")
rep["cl"] = rep.bar_close // (2 * 3600 * 1000)
days = {"core": 2.202, "ds": 1.5035}
rows = []
for (k, st, tf), g in rep.groupby(["k", "strategy", "timeframe"]):
    t = g[g.status == "TRADED"]
    x = t.R.to_numpy(float); n = len(x)
    se = np.nan
    if n >= 3:
        s = pd.Series(x - x.mean()).groupby(t.cl.to_numpy()).sum().to_numpy(); G = len(s)
        se = np.sqrt((s ** 2).sum() * G / max(G - 1, 1)) / n if G > 1 else np.nan
    rows.append(dict(kind=k, strategy=st, tf=tf, live_sub=len(g), live_per_day=len(g) / days[k], live_n=n,
                     live_R=x.mean() if n else np.nan, live_se=se))
L = pd.DataFrame(rows).merge(C, on=["kind", "strategy", "tf"], how="left")
print("unmatched", L.netR.isna().sum())
L.to_csv(os.path.join(os.path.dirname(AC), "cells_live.csv"), index=False)
rng = np.random.default_rng(5)
for k in ("core", "ds"):
    x = L[(L.kind == k) & (L.live_n >= 10) & L.netR.notna()]
    r1, r2 = x.netR.rank(), x.live_R.rank()
    rho = np.corrcoef(r1, r2)[0, 1]
    perm = np.array([np.corrcoef(r1, rng.permutation(r2.to_numpy()))[0, 1] for _ in range(4000)])
    y = x[x.live_se > 0]
    exp = sum(1 - Phi(-m / s) for m, s in zip(y.netR, y.live_se))
    z = (y.live_R - y.netR) / y.live_se
    print(k, "cells", len(x), "spearman", round(rho, 3), "perm p2", round((abs(perm) >= abs(rho)).mean(), 3),
          "| se-cells", len(y), "live pos obs", int((y.live_R > 0).sum()), "exp(5y avg)", round(exp, 1),
          "z sd", round(z.std(), 2), "|z|>2", int((abs(z) > 2).sum()))
# frequency per cell (cells with >=1 5y signal/day)
f = L[(L.per_day >= 1)]
lr = np.log(f.live_per_day.clip(lower=1e-9) / f.per_day)
print("freq cells", len(f), "corr log", round(np.corrcoef(np.log(f.live_per_day.clip(lower=0.1)), np.log(f.per_day))[0, 1], 3),
      "within 0.5-2x", round(((f.live_per_day / f.per_day).between(0.5, 2)).mean(), 3))
for k in ("core", "ds"):
    for tf in ("15m", "30m", "1h", "4h"):
        a = L[(L.kind == k) & (L.tf == tf)]
        b = C[(C.kind == k) & (C.tf == tf)]
        print(k, tf, "live/5y per-day sum", round(a.live_per_day.sum() / b.per_day.sum(), 3))
# named cells
for k, st, tf in (("core", "S4_BB_BBP", "15m"), ("core", "N17_KC_RSI", "15m"), ("core", "N20_EMA9_CHOP", "30m"), ("core", "N20_EMA9_CHOP", "1h"),
                  ("core", "N01_ST_EMA", "15m"), ("ds", "F1_RSI_DIV", "15m"), ("core", "N10_HA_PSAR", "15m"), ("core", "N24_DMI", "30m"),
                  ("ds", "F7_RF_TRIPLE", "30m"), ("ds", "F7_RF_TRIPLE", "15m"), ("ds", "F9_IFVG", "15m"), ("ds", "F16_FIB382", "15m"),
                  ("ds", "F16_FIB500", "15m"), ("core", "N17_KC_RSI", "4h"), ("core", "N23_HA_ST", "4h")):
    r = L[(L.kind == k) & (L.strategy == st) & (L.tf == tf)]
    if len(r):
        r = r.iloc[0]
        print(st, tf, "live", round(r.live_R, 3), "+-", round(r.live_se, 3), "n", r.live_n, "sub/day", round(r.live_per_day, 2),
              "| 5y net", round(r.netR, 3), "gross", round(r.grossR, 4), "gt", round(r.gross_t, 2), "gIS", round(r.g_is, 4), "gCF", round(r.g_cf, 4),
              "5y/day", round(r.per_day, 2), "sized/day", round(r.per_day_sized, 2))
    else:
        print(st, tf, "no live rows")
