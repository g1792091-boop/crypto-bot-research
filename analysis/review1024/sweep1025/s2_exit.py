"""Sweep 2: is the monthly x5 rate the strategies' doing or the exit's? Per exit: share of goal months (x5 before
-50 % inside a KST month) over configs, real vs coin-flip directions; and the best configs of each run."""
import os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
M = np.load(os.path.join(OUTD, "meta.npz")); XN = M["XN"]; NF = len(M["FN"]); NCELL = len(M["cells"])
rows = []
best = {}
for run in ("real", "null1", "null2"):
    R = np.load(os.path.join(OUTD, f"R_{run}.npy")).astype(np.float32)        # (cell, filt, mode, exit, 13)
    act, hit, act6, hit6 = R[..., 1], R[..., 2], R[..., 4], R[..., 5]
    fx = np.exp(R[..., 8]); fn = R[..., 11]
    for x in range(len(XN)):
        a = act[..., x]; h = hit[..., x]; a6 = act6[..., x]; h6 = hit6[..., x]; ok = a >= 30; ok6 = a6 >= 6
        r = np.where(ok, h / np.maximum(a, 1), np.nan); r6 = np.where(ok6, h6 / np.maximum(a6, 1), np.nan)
        f = fx[..., x][fn[..., x] >= 10]
        rows.append(dict(run=run, exit=XN[x], configs=int(ok.sum()), goal_2025=np.nanmean(r), top1pct_2025=np.nanpercentile(r, 99),
                         best_2025=np.nanmax(r), goal_2026=np.nanmean(r6), fwd_med=np.median(f) if len(f) else np.nan,
                         fwd_x5=np.mean(f >= 5) if len(f) else np.nan))
    tot = np.where(act + act6 >= 40, (hit + hit6) / np.maximum(act + act6, 1), -1)
    o = np.argsort(-tot.ravel())[:2000]
    best[run] = tot.ravel()[o]
    del R
T = pd.DataFrame(rows)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 50)
P = T.pivot_table(index="exit", columns="run", values=["goal_2025", "top1pct_2025", "best_2025", "goal_2026", "fwd_med"])
print(P.round(3).sort_values(("goal_2025", "real"), ascending=False).to_string())
T.to_csv(os.path.join(OUTD, "per_exit.csv"), index=False)
print("\nbest goal-month rate 2020-03..2026-09 (40+ active months): rank 1 / 10 / 100 / 1000")
for run, b in best.items():
    print(f"  {run}: {b[0]:.3f} / {b[9]:.3f} / {b[99]:.3f} / {b[999]:.3f}")
