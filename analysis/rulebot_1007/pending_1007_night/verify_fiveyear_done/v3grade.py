import os, sys
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np, pandas as pd
V, TH = sys.argv[1:3]
C = pd.read_csv(os.path.join(V, "agg_cells.csv"))
L = pd.read_csv(os.path.join(V, "cells_live.csv"))[["kind", "strategy", "tf", "live_n", "live_R", "live_se"]]
T = C.merge(L, on=["kind", "strategy", "tf"], how="left")
def fyc(r):
    if not np.isfinite(r.netR) or r.n < 30: return "thin"
    if r.netR > 0 and r.net_is > 0 and r.net_cf > 0: return "P"
    g = r.grossR > 0
    if np.isfinite(r.t) and r.t <= -2: return "N+" if g else "NN"
    return "Z+" if g else "Z-"
def lc(r):
    n, mu, se = r.live_n, r.live_R, r.live_se
    if not n or not np.isfinite(n) or n < 15 or not np.isfinite(mu): return "L_thin"
    if np.isfinite(se) and mu + 2 * se < 0: return "L--"
    if np.isfinite(se) and mu - 2 * se > 0: return "L++"
    return "L+" if mu > 0 else "L-"
G = {}
for a, gr in (("P", {"L++": "A", "L+": "A", "L-": "B", "L_thin": "B", "L--": "C"}), ("Z+", {"L++": "B", "L+": "B", "L-": "C", "L_thin": "C", "L--": "D"}),
              ("N+", {"L++": "C", "L+": "C", "L-": "D", "L_thin": "D", "L--": "F"}), ("Z-", {"L++": "C", "L+": "C", "L-": "D", "L_thin": "D", "L--": "F"}),
              ("NN", {"L++": "D", "L+": "D", "L-": "F", "L_thin": "F", "L--": "F"})):
    for b, g in gr.items(): G[(a, b)] = g
T["fyc"] = T.apply(fyc, axis=1); T["lc"] = T.apply(lc, axis=1)
T["grade"] = [G.get((a, b), "thin") for a, b in zip(T.fyc, T.lc)]
T = T[T.tf != "5m"]
print("mine 15m-4h", T.grade.value_counts().to_dict())
Th = pd.read_csv(os.path.join(TH, "fy_candidates.csv"))
F = pd.read_csv(os.path.join(TH, "fiveyear_vs_live.csv"))
print("their file cols has grade?", "grade" in F.columns)
gcol = "grade"
F["kind2"] = np.where(F.kind == "strategy", "core", "ds")
F = F[F.tf != "5m"]
J = T.merge(F[["kind2", "strategy", "tf", gcol, "fy_class", "live_class"]].rename(columns={"kind2": "kind", gcol: "their_grade"}), on=["kind", "strategy", "tf"], how="outer")
print("their 15m-4h", J.their_grade.value_counts().to_dict())
print("agree", (J.grade == J.their_grade).mean(), "n", len(J))
d = J[J.grade != J.their_grade]
print(d[["kind", "strategy", "tf", "fyc", "lc", "grade", "fy_class", "live_class", "their_grade", "live_n", "live_R", "live_se"]].round(3).to_string())
B = T[T.grade.isin(["A", "B"])]; print("A/B:", B[["kind", "strategy", "tf", "fyc", "lc", "n", "per_day_sized", "netR"]].round(3).to_string())
for grp, tfs in (("15/30", ["15m", "30m"]), ("1h/4h", ["1h", "4h"])):
    x = T[T.tf.isin(tfs) & T.grade.isin(["A", "B", "C"])].copy()
    x["gboth"] = (x.g_is > 0) & (x.g_cf > 0)
    x = x.sort_values(["grade", "gboth", "netR"], ascending=[True, False, False])
    print(grp, "ABC cells", len(x)); print(x[["kind", "strategy", "tf", "grade", "fyc", "lc", "netR", "grossR", "gross_t", "gboth", "per_day_sized", "live_n", "live_R"]].head(14).round(3).to_string())
T.to_csv(os.path.join(V, "grades_mine.csv"), index=False)
