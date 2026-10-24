"""Verifier part 5: (a) per-entry carry-over of the 374 cells on CONF and FWD (overlap), (b) bot G against a TRUE coin
flip (each signal's side drawn 50/50, seeded, one position at a time with that side's exit), not only the opposite twin.
    python3 xc_extra.py"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xc_gbot_costs import *         # noqa: E402,F401

F = pd.read_csv(os.path.join(FY, "flip_picked.csv"))
A = pd.read_pickle(os.path.join(SH, "cells374_rows.pkl"))
A = A[np.isfinite(A.w35_r) & np.isfinite(A.w35_opp_r)]
A["ent"] = (F.name + "@" + F.etf).to_numpy()[A.cell_i.to_numpy()]
pd.set_option("display.width", 200)
for per in ("CONF", "FWD"):
    P = period_rows(A, per)
    c = P.groupby("cell_i").agg(ent=("ent", "first"), own=("w35_r", "mean"), opp=("w35_opp_r", "mean"), n=("w35_r", "size"))
    c["beat"] = c.own > c.opp
    e = c.groupby("ent").agg(cells=("beat", "size"), beat=("beat", "mean"), n_med=("n", "median"))
    D = P.drop_duplicates(["coin", "e", "side", "name", "tf"])
    d = D.groupby("ent").agg(sig=("w35_r", "size"), own=("w35_r", "mean"), opp=("w35_opp_r", "mean"))
    e = e.join(35 * d[["own", "opp"]]).join(d.sig)
    e["gap"] = e.own - e.opp
    print(per, "cells", len(c), "beat", round(c.beat.mean(), 3), "| entries", len(e), "entries with distinct-signal gap > 0:",
          int((e.gap > 0).sum()), "| cells without S4_BB_BBP@1h beat", round(c[c.ent != "S4_BB_BBP@1h"].beat.mean(), 3))
    print(e.sort_values("cells", ascending=False).head(12).round(4).to_string())
# (b) true coin flip for bot G
S = pd.read_pickle(os.path.join(SH, "G_rows.pkl"))
S = S[np.isfinite(S.w35_r) & np.isfinite(S.w35_opp_r)]
for per in ("CONF", "LATE", "FWD"):
    P = period_rows(S, per).reset_index(drop=True)
    res = []
    for seed in range(50):
        rng = np.random.default_rng(seed)
        flip = rng.random(len(P)) < 0.5
        Q = P.assign(w35_roe=np.where(flip, P.w35_opp_roe, P.w35_roe), w35_k=np.where(flip, P.w35_opp_k, P.w35_k))
        T = Q[RD.one_position(Q, "w35", priority="prio")]
        res.append((len(T), T.w35_roe.mean()))
    R = np.array(res)
    T = P[RD.one_position(P, "w35", priority="prio")]
    print(per, f"G {T.w35_roe.mean():.4f} ({len(T)})  true coin flip over 50 seeds: mean {R[:, 1].mean():.4f} "
          f"min {R[:, 1].min():.4f} max {R[:, 1].max():.4f}  trades {R[:, 0].mean():.0f}; G beats {int((R[:, 1] < T.w35_roe.mean()).sum())}/50")
