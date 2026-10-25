"""Hunt 10/25 step 3: read the single-member scores. Persistence (does a good first half predict the second half?),
robust candidates (both halves, every quarter), exit plateaus. Writes out/single_top.csv and prints a summary."""
import os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
R = np.load(os.path.join(OUTD, "single_R.npy"), mmap_mode="r")
Gp = pd.read_csv(os.path.join(OUTD, "groups.csv")); EX = pd.read_csv(os.path.join(OUTD, "exits.csv"))
G, X, _ = R.shape
eq, dd, n, wn, e1, e2, n1, n2 = (R[:, :, k] for k in range(8))
q = R[:, :, 8:12]; worst = R[:, :, 12]
print("configs", G * X, "groups", G, "exits", X)
ok = (n >= 10) & (n1 >= 4) & (n2 >= 4)
print("with >= 10 trades and >= 4 in each half:", int(ok.sum()))
for thr in (1, 2, 6, 20):
    print(f"  19-day >= x{thr}: {int((ok & (eq >= thr)).sum())}  | both halves >= x{thr ** 0.5:.2f}: "
          f"{int((ok & (e1 >= thr ** 0.5) & (e2 >= thr ** 0.5)).sum())}")
allq = ok & (q.min(axis=2) >= 1.0)
print("every quarter >= x1:", int(allq.sum()), "| and 19-day >= x6:", int((allq & (eq >= 6)).sum()))

# persistence: rank on one half, read the other
l1 = np.log(np.maximum(e1, 1e-6))[ok]; l2 = np.log(np.maximum(e2, 1e-6))[ok]
r1 = pd.Series(l1).rank().to_numpy(); r2 = pd.Series(l2).rank().to_numpy()
print("Spearman H1 vs H2 over configs:", round(float(np.corrcoef(r1, r2)[0, 1]), 3))
for a, b, lab in ((e1, e2, "H1->H2"), (e2, e1, "H2->H1")):
    A = a[ok]; B = b[ok]; o = np.argsort(-A)
    base = np.median(B)
    print(f" {lab}: all configs median x{base:.2f}; top1 x{B[o[0]]:.2f}; top10 median x{np.median(B[o[:10]]):.2f}; "
          f"top100 x{np.median(B[o[:100]]):.2f}; top1000 x{np.median(B[o[:1000]]):.2f}; top10000 x{np.median(B[o[:10000]]):.2f}"
          f" | share>1: top1000 {np.mean(B[o[:1000]] > 1):.0%} vs all {np.mean(B > 1):.0%}")

# robust candidates: >= 10 trades, every quarter >= x1, ranked by the weaker half
gi, xi = np.nonzero(allq)
rows = pd.DataFrame({"g": gi, "x": xi, "eq": eq[gi, xi], "h1": e1[gi, xi], "h2": e2[gi, xi], "n": n[gi, xi],
                     "win": wn[gi, xi] / n[gi, xi], "dd": dd[gi, xi], "worst": worst[gi, xi],
                     "q1": q[gi, xi, 0], "q2": q[gi, xi, 1], "q3": q[gi, xi, 2], "q4": q[gi, xi, 3]})
rows["weak"] = np.minimum(rows.h1, rows.h2)
# plateau: share of the group's 330 exits with both halves >= x1 (a lone lucky exit scores low)
plat = ((e1 >= 1) & (e2 >= 1) & ok).mean(axis=1)
rows["plateau"] = plat[rows.g]
rows = rows.join(Gp, on="g").merge(EX, left_on="x", right_on="exit", how="left")
rows = rows.sort_values("weak", ascending=False)
rows.to_csv(os.path.join(OUTD, "single_top.csv"), index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 60)
cols = ["cell", "mode", "filter", "name", "eq", "h1", "h2", "q1", "q2", "q3", "q4", "n", "win", "dd", "plateau"]
print(rows[cols].head(40).round(2).to_string())
print("\nbest per cell (top 40 cells by weaker half):")
print(rows.drop_duplicates("cell")[cols].head(40).round(2).to_string())
