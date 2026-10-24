"""Verifier -- step 7: rebuild the study's accumulators from scratch into a SEPARATE RAM folder (the study's own SHM
was deleted), rebuild the cell table with fy_analyze.cell_table (no CSV written), and redo select_cells' family / BH /
shortlist with the SELECT columns only; check the 20 with-cells of B_sel_with20 are exactly the SELECT top 20 and that
no SELECT column depends on CONFIRM rows. The RAM folder is removed at the end.
    python3 tz_b_family.py"""
import os
import shutil
import sys
VH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(VH))
import fy_common                # noqa: E402
MY = "/dev/shm/claude_verify_tz"
os.makedirs(MY, exist_ok=True)
fy_common.SHM = MY
import build_acc                # noqa: E402
import fy_analyze as FA         # noqa: E402
from fy_common import *         # noqa: E402,F401
assert build_acc.SHM == MY and FA.SHM == MY
try:
    build_acc.main()
    meta, A, AM, B, B0, BARS = FA.load()
    D = FA.cell_table(meta, A, AM, B, BARS)
    rows = []
    for cn in ("W", "A", "N"):
        q = D[(D[f"SEL_n{cn}"] >= FA.SEL_MIN) & (D[f"SEL_M{cn}"] >= 12)]
        if cn == "N":
            q = q[q.kind != "l"]
        rows.append(pd.DataFrame({"cond": cn, "idx": q.index, "t": q[f"SEL_t{cn}"].to_numpy(),
                                  "M": q[f"SEL_M{cn}"].to_numpy(), "m": q[f"SEL_m{cn}"].to_numpy()}))
    U = D[(D.htf == "1d")].drop_duplicates(["sid", "etf"])
    U = U[(U.SEL_nALL >= FA.SEL_MIN) & (U.SEL_MALL >= 12)]
    rows.append(pd.DataFrame({"cond": "ALL", "idx": U.index, "t": U.SEL_tALL.to_numpy(), "M": U.SEL_MALL.to_numpy(),
                              "m": U.SEL_mALL.to_numpy()}))
    F = pd.concat(rows, ignore_index=True)
    F["p"] = FA.pval(F.t.to_numpy(), F.M.to_numpy())
    F["bh"] = FA.bh(F.p.to_numpy())
    print("family", len(F), F.groupby("cond").size().to_dict(), "BH pass on SEL", int(F.bh.sum()),
          "min p", float(F.p.min()), "max t", float(F.t.max()))
    F = F.join(D[["name", "etf", "htf", "kind", "source"]], on="idx")
    z = F[(F.cond == "W") & (F.m > 0)].sort_values("t", ascending=False).drop_duplicates(["name", "etf"]).head(20)
    mine = set(f"{r['name']}@{r.etf}|{r.kind}:{r.source}@{r.htf}" for _, r in z.iterrows())
    SL = pd.read_csv(os.path.join(os.path.dirname(VH), "shortlist.csv"))
    SL = SL[SL.cond == "W"]
    theirs = set(f"{r['name']}@{r.etf}|{r.source}@{r.htf}" for _, r in SL.iterrows())
    print("rebuilt SEL top-20 with-cells == shortlist W:", mine == theirs, "| only mine:", mine - theirs,
          "| only theirs:", theirs - mine)
    # ties near the cut (is the 20th clearly separated from the 21st?)
    z2 = F[(F.cond == "W") & (F.m > 0)].sort_values("t", ascending=False).drop_duplicates(["name", "etf"]).head(22)
    print(z2[["name", "etf", "htf", "kind", "source", "t", "m", "M"]].to_string())
finally:
    shutil.rmtree(MY, ignore_errors=True)
    print("removed", MY, os.path.exists(MY))
