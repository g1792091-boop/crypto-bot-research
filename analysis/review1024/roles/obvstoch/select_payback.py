"""S2 track (PLAN.md change log 1): the same SEL selection rule on ROE + TetherMax payback (PAYBACK x leverage per trade).
Reads sel_cells.csv (SEL only), writes picks_payback.csv."""
import oscore as O
from oscore import *
from scipy.stats import norm
C = pd.read_csv("sel_cells.csv")
lev = C.exit.map(O.LEVX)
C["mean_roe_pb"] = C.mean_roe + PAYBACK * lev
C["t_abs_pb"] = C.mean_roe_pb / C.se
C["p_abs_pb"] = norm.sf(C.t_abs_pb)
C["q_abs_pb_F"] = O.bh(np.where(C.n >= 200, C.p_abs_pb, 1.0))
el = C[(C.n >= 200) & (C.mean_roe_pb > 0) & (C.mean_d > 0) & (C.q_abs_pb_F <= 0.10)].sort_values("t_abs_pb", ascending=False)
if len(el):
    pk = el.head(10).assign(pick_kind="BH_pass_payback")
else:
    pk = C[C.n >= 200].sort_values("t_abs_pb", ascending=False).head(5).assign(pick_kind="best_not_significant_payback")
pk["written_utc"] = pd.Timestamp.utcnow().isoformat()
pk.to_csv("picks_payback.csv", index=False)
print("positive with payback:", int(((C.n >= 200) & (C.mean_roe_pb > 0)).sum()), "of", int((C.n >= 200).sum()),
      "| BH pass:", int((C.q_abs_pb_F <= 0.10).sum()), "| BH pass with d>0:", len(el))
print(pk[["cell", "n", "per_day", "mean_roe", "mean_roe_pb", "t_abs_pb", "q_abs_pb_F", "mean_d", "t_d", "pick_kind"]].to_string())
