"""Step 1 (PLAN.md section 4): statistics of all 1,080 cells on SEL (2021-01-01 .. 2024-01-01) ONLY, controls on SEL,
BH, the whole-search day sign-flip permutation (Westfall-Young maxT), and the picks. Writes sel_cells.csv,
sel_controls.csv, picks.csv (with the time it was written). Nothing outside SEL is read here.

    python3 select_sel.py
"""
import json
import oscore as O
from oscore import *

D = O.load_all()
PER = "SEL"
NMIN = 200
recs, dmat = [], []
a, b = O.P[PER]
day0 = a // DAY
ndays = (b - a) // DAY
for (tf, htf, T, Ot, X) in O.cells():
    R = O.rows(D, tf, htf, T, Ot, X, PER)
    s = O.summarize(R)
    s.update(cell=O.cell_id(tf, htf, T, Ot, X), tf=tf, htf=htf, trend=T, timing=Ot, exit=X,
             per_day=s["n"] / ndays, family_A=(T in O.OBV_TRENDS and Ot in O.SRSI))
    Ra = O.rows(D, tf, htf, T, Ot, X, PER, against=True)
    s["n_against"], s["mean_against"] = len(Ra["roe"]), float(Ra["roe"].mean()) if len(Ra["roe"]) else np.nan
    recs.append(s)
    d = R["roe"] - R["opp"]
    dm = np.bincount(R["day"].astype(np.int64) - day0, weights=d, minlength=ndays)[:ndays]
    dmat.append(dm)
C = pd.DataFrame(recs)
dmat = np.array(dmat)

# controls on SEL
ctl = []
for (tf, htf) in O.MAPS:
    for X in O.EXITS:
        for T in O.TRENDS:
            R = O.rows(D, tf, htf, T, None, X, PER, trend_only=True)
            s = O.summarize(R)
            s.update(kind="trend_only", tf=tf, htf=htf, trend=T, timing="", exit=X)
            ctl.append(s)
for tf in O.ENTRY_TFS:
    for X in O.EXITS:
        for Ot in O.TIMINGS:
            R = O.rows(D, tf, None, None, Ot, X, PER, timing_only=True)
            s = O.summarize(R)
            s.update(kind="timing_only", tf=tf, htf="", trend="", timing=Ot, exit=X)
            ctl.append(s)
CT = pd.DataFrame(ctl)
CT.to_csv("sel_controls.csv", index=False)
to = CT[CT.kind == "trend_only"].set_index(["tf", "htf", "trend", "exit"]).mean_roe
ti = CT[CT.kind == "timing_only"].set_index(["tf", "timing", "exit"]).mean_roe
C["trend_only_roe"] = [to[(r.tf, r.htf, r.trend, r.exit)] for r in C.itertuples()]
C["timing_only_roe"] = [ti[(r.tf, r.timing, r.exit)] for r in C.itertuples()]

# multiplicity
pa = np.where(C.n >= NMIN, C.p_abs, 1.0)
pdd = np.where(C.n >= NMIN, C.p_d, 1.0)
C["q_abs_F"] = O.bh(pa)
C["q_d_F"] = O.bh(pdd)
A = C.family_A.to_numpy()
C["q_abs_A"] = np.nan
C["q_d_A"] = np.nan
C.loc[A, "q_abs_A"] = O.bh(pa[A])
C.loc[A, "q_d_A"] = O.bh(pdd[A])

# whole-search permutation: sign flips by UTC day (all coins and cells together), self-normalised statistic
rng = np.random.default_rng(20261024)
NP = 2000
nrm = np.sqrt((dmat ** 2).sum(1))
nrm[nrm == 0] = np.inf
Tobs = dmat.sum(1) / nrm
Tobs[C.n.to_numpy() < NMIN] = -np.inf
mx_F, mx_A = np.empty(NP), np.empty(NP)
for i in range(0, NP, 250):
    eps = rng.choice([-1.0, 1.0], size=(ndays, 250))
    Ts = (dmat @ eps) / nrm[:, None]
    Ts[C.n.to_numpy() < NMIN] = -np.inf
    mx_F[i:i + 250] = Ts.max(0)
    mx_A[i:i + 250] = Ts[A].max(0)
C["T_perm"] = Tobs
C["p_wy_F"] = [(1 + (mx_F >= t).sum()) / (1 + NP) for t in Tobs]
C["p_wy_A"] = np.where(A, [(1 + (mx_A >= t).sum()) / (1 + NP) for t in Tobs], np.nan)
C.to_csv("sel_cells.csv", index=False)

# picks (PLAN.md): n >= 200, mean > 0, d > 0, BH(F, q = 0.10) on p_abs; top 10 by t_abs; none -> top 5 by t_abs (labelled)
elig = C[(C.n >= NMIN) & (C.mean_roe > 0) & (C.mean_d > 0) & (C.q_abs_F <= 0.10)].sort_values("t_abs", ascending=False)
if len(elig):
    picks = elig.head(10).assign(pick_kind="BH_pass")
else:
    picks = C[C.n >= NMIN].sort_values("t_abs", ascending=False).head(5).assign(pick_kind="best_not_significant")
lit = C[C.cell.isin(["OBV30@1h>SRSI_KD@30m|w35", "OBV30@4h>SRSI_KD@1h|w35"])].assign(pick_kind="literal")
picks = pd.concat([picks, lit[~lit.cell.isin(picks.cell)]])
picks["written_utc"] = pd.Timestamp.utcnow().isoformat()
picks.to_csv("picks.csv", index=False)

summ = {
    "cells": len(C), "cells_n_ge_200": int((C.n >= NMIN).sum()),
    "positive_mean_roe": int(((C.n >= NMIN) & (C.mean_roe > 0)).sum()),
    "bh_abs_F_pass": int((C.q_abs_F <= 0.10).sum()), "bh_d_F_pass": int((C.q_d_F <= 0.10).sum()),
    "bh_abs_A_pass": int((C.q_abs_A <= 0.10).sum()), "bh_d_A_pass": int((C.q_d_A <= 0.10).sum()),
    "wy_F_pass_05": int((C.p_wy_F <= 0.05).sum()), "wy_A_pass_05": int((C.p_wy_A <= 0.05).sum()),
    "mean_of_cell_means": float(C[C.n >= NMIN].mean_roe.mean()), "mean_of_opp": float(C[C.n >= NMIN].mean_opp.mean()),
    "share_d_pos": float((C[C.n >= NMIN].mean_d > 0).mean()),
    "perm_max_T_95": float(np.quantile(mx_F, 0.95)), "obs_max_T": float(Tobs.max()),
    "pick_kind": picks.pick_kind.iloc[0],
}
json.dump(summ, open("sel_summary.json", "w"), indent=1)
print(json.dumps(summ, indent=1))
cols = ["cell", "n", "per_day", "mean_roe", "t_abs", "q_abs_F", "mean_opp", "mean_d", "t_d", "q_d_F", "p_wy_F",
        "trend_only_roe", "timing_only_roe", "long_share", "pick_kind"]
print(picks[cols].to_string())
