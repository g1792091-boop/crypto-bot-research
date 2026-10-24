"""S3 exploratory track (PLAN.md change log 2): take the OPPOSITE side of every cell's signals. Select on SEL with the
same rule (with and without payback), write picks_reverse.csv, then read the picks once on CONF (+ PRE / YTD / FWD /
FIVE, descriptive). Writes sel_reverse.csv, picks_reverse.csv, conf_reverse.csv."""
import oscore as O
from oscore import *
from scipy.stats import norm
parse, holm = O.parse, O.holm

D = O.load_all()


def rev_stats(R, add):
    x = R["opp"] + add
    n, m, se, t = O.cl_stats(x, R["day"])
    return n, m, se, t


recs = []
for (tf, htf, T, Ot, X) in O.cells():
    R = O.rows(D, tf, htf, T, Ot, X, "SEL")
    n, m, se, t = rev_stats(R, 0.0)
    pb = PAYBACK * O.LEVX[X]
    recs.append({"cell": O.cell_id(tf, htf, T, Ot, X), "n": n, "mean_rev": m, "se": se, "t_rev": t,
                 "mean_rev_pb": m + pb, "t_rev_pb": (m + pb) / se if se > 0 else np.nan})
S = pd.DataFrame(recs)
S["p_rev"] = norm.sf(S.t_rev)
S["p_rev_pb"] = norm.sf(S.t_rev_pb)
S["q_rev"] = O.bh(np.where(S.n >= 200, S.p_rev, 1.0))
S["q_rev_pb"] = O.bh(np.where(S.n >= 200, S.p_rev_pb, 1.0))
S.to_csv("sel_reverse.csv", index=False)
picks = []
for lab, mc, tc, qc in (("R", "mean_rev", "t_rev", "q_rev"), ("Rpb", "mean_rev_pb", "t_rev_pb", "q_rev_pb")):
    el = S[(S.n >= 200) & (S[mc] > 0) & (S[qc] <= 0.10)].sort_values(tc, ascending=False)
    kind = "BH_pass" if len(el) else "best_not_significant"
    k = (el.head(10) if len(el) else S[S.n >= 200].sort_values(tc, ascending=False).head(5)).copy()
    k["track"], k["pick_kind"] = lab, kind
    picks.append(k)
    print(lab, "positive:", int(((S.n >= 200) & (S[mc] > 0)).sum()), "BH pass:", len(el))
P_ = pd.concat(picks)
P_["written_utc"] = pd.Timestamp.utcnow().isoformat()
P_.to_csv("picks_reverse.csv", index=False)
print(P_[["track", "cell", "n", "mean_rev", "mean_rev_pb", "t_rev", "t_rev_pb", "q_rev", "q_rev_pb", "pick_kind"]].round(4).to_string())

# the one CONF read of the picks
out = []
for r in P_.itertuples():
    tf, htf, T, Ot, X = parse(r.cell)
    add = PAYBACK * O.LEVX[X] if r.track == "Rpb" else 0.0
    row = {"track": r.track, "cell": r.cell, "pick_kind": r.pick_kind,
           "sel_mean": r.mean_rev_pb if r.track == "Rpb" else r.mean_rev}
    for per in ("CONF", "PRE", "YTD", "FWD", "FIVE"):
        R = O.rows(D, tf, htf, T, Ot, X, per)
        n, m, se, t = rev_stats(R, add)
        row.update({f"{per}_n": n, f"{per}_mean": m, f"{per}_t": t, f"{per}_p": float(norm.sf(t)) if np.isfinite(t) else 1.0,
                    f"{per}_short_share": float((R["side"] > 0).mean()) if n else np.nan})
    out.append(row)
C = pd.DataFrame(out)
for tr in C.track.unique():
    m = C.track == tr
    C.loc[m, "CONF_p_holm"] = holm(C.loc[m, "CONF_p"].to_numpy())
C["confirmed"] = (C.CONF_mean > 0) & (C.CONF_p_holm < 0.05)
C.to_csv("conf_reverse.csv", index=False)
pd.set_option("display.width", 250)
print(C[["track", "cell", "sel_mean", "CONF_n", "CONF_mean", "CONF_t", "CONF_p_holm", "confirmed", "PRE_mean", "YTD_mean",
         "FWD_n", "FWD_mean", "FIVE_mean"]].round(4).to_string())
