"""PREREG 7.3 (descriptive): FINAL-window values.  carried = [] so there are no carried combos; the task also asks
for the top-5 IS cells: (A) top-5 FAMILY (n>=100) IS cells by z, (B) top-5 by z as sweep_lib.persistence ranks them
(all cells with finite values, including n<100).  Gate stats IS/OOS/FINAL + best/TIME_H exit rows on OOS/FINAL."""
import os, sys, glob
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import sweep_lib as L
S = os.path.dirname(HERE); O = os.path.join(HERE, "out")
K = ["strategy", "tf", "H"]
M = pd.read_csv(os.path.join(O, "persistence_merged_cells.csv"))
A = M[M.in_family_is].sort_values("z_is", ascending=False).head(5).assign(set="A: top-5 family IS by z")
fin = np.isfinite(M.fwd_minus_hurdle_is) & np.isfinite(M.fwd_minus_hurdle_oos)
B = M[fin].sort_values("z_is", ascending=False).head(5).assign(set="B: top-5 IS by z (persistence(), incl. n<100)")
T = pd.concat([A, B], ignore_index=True)
cols = ["set"] + K + ["approx", "prev_examined"]
for s in ("is", "oos", "fin"):
    cols += [f"n_{s}", f"fwd_{s}", f"mu_star_{s}", f"ratio_{s}", f"net_time_{s}", f"z_{s}", f"p_{s}", f"p_vn_{s}", f"symbols_pos_{s}", f"n_coins_ge10_{s}"]
T = T[cols]
ex = []
for s in ("oos", "final"):
    e = pd.concat([pd.read_csv(f) for f in glob.glob(os.path.join(O, f"exits_descriptive_{s}_*.csv"))], ignore_index=True)
    e["split"] = s
    ex.append(e)
ise = pd.read_csv(os.path.join(S, "combine", "out", "exits_descriptive_nearmiss_all.csv")).assign(split="is")
E = pd.concat(ex + [ise], ignore_index=True)
E = E.merge(T[K].drop_duplicates(), on=K)
E = E[["split"] + K + ["exit", "trades", "pf", "exp_net", "sum_net", "symbols_pos", "months_pos", "months", "p_max"]]
T.to_csv(os.path.join(O, "final_top5_gate.csv"), index=False)
E.to_csv(os.path.join(O, "final_top5_exits.csv"), index=False)
pd.set_option("display.width", 300)
print(T.round(5).T.to_string())
print()
print(E[E.exit.isin(["TIME_H", "TIME_H_SL3", "ATR_SL3_TP6"])].sort_values(K + ["exit", "split"]).round(4).to_string())
