"""Verifier (luck / multiple testing lens) of the a2 family TOP5 claim of fw_search.py.

Reproduces the actual a2_F top5 H2 pooled number, then splits it: per cell, long/short, coin-flip twin (same signals,
opposite side), unique entries, day-cluster bootstrap, the subset the report names (1h reversal + timing @4h
c_N07_ICHI_CMO) and baselines (same cells' unfiltered signals, follow-the-trend at every bar).
Read-only over the cached tables of fw_build.py. Run from this folder: python3 rc_actual.py"""
import os
import sys
import json

FW = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, FW)
from fw_lib import *  # noqa: F401,F403,E402
import fw_search as FS  # noqa: E402

OUTD = os.path.dirname(os.path.abspath(__file__))


def day_ci(x, d, nb=5000, seed=3):
    lo, hi = day_boot_ci(np.asarray(x, float), np.asarray(d), n_boot=nb, seed=seed)
    return lo, hi


def main():
    S = load("sig")
    S = S[S.role != "trend"].reset_index(drop=True)
    P = pd.read_csv(os.path.join(FW, "search_picks.csv"))
    P = P[(P.exit == "a2") & (P.level == "F")].sort_values("rank")
    r = roe(S, "a2")
    ro = roe(S, "a2", True)
    k = S["a2_k"].to_numpy(np.int64)
    why = S["a2_why"].to_numpy()
    h1 = S.t.to_numpy() < SPLIT
    ok2 = ~h1 & (why != 3) & np.isfinite(r) & (k >= 0)
    side = S.side.to_numpy()
    out = {"cells": []}
    allrows = []
    for _, c in P.iterrows():
        role, tf = c.key.split("|")
        m = (S.role.to_numpy() == role) & (S.tf.to_numpy() == tf)
        st = state(S, c.src, c.htf)
        al = m & (st * side == 1)
        sel = al & ok2
        un = m & ok2
        x = r[sel]
        cell = {"rank": int(c["rank"]), "cell": f"{c.key}@{c.htf}:{c.src}", "n2": int(sel.sum()),
                "m2": float(np.mean(x)), "csv_n2": float(c.n2), "csv_m2": float(c.m2),
                "twin_m2": float(np.nanmean(ro[sel])),
                "nS": int((sel & (side < 0)).sum()), "nL": int((sel & (side > 0)).sum()),
                "m2_S": float(np.mean(r[sel & (side < 0)])) if (sel & (side < 0)).any() else None,
                "m2_L": float(np.mean(r[sel & (side > 0)])) if (sel & (side > 0)).any() else None,
                "unfiltered_n2": int(un.sum()), "unfiltered_m2": float(np.nanmean(r[un])),
                "unfiltered_short_m2": float(np.nanmean(r[un & (side < 0)])),
                "against_m2": float(np.nanmean(r[m & ok2 & (st * side == -1)])),
                "days2": int(len(np.unique(S.day.to_numpy()[sel])))}
        out["cells"].append(cell)
        X = S[sel].copy()
        X["roe"] = r[sel]
        X["roe_opp"] = ro[sel]
        X["cell"] = cell["cell"]
        X["rank"] = cell["rank"]
        allrows.append(X)
    A = pd.concat(allrows, ignore_index=True)
    out["pooled"] = {"n": len(A), "mean": float(A.roe.mean()), "twin": float(A.roe_opp.mean()),
                     "ci_day": day_ci(A.roe, A.day), "ci_day_twin": day_ci(A.roe_opp, A.day),
                     "nS": int((A.side < 0).sum()), "nL": int((A.side > 0).sum()),
                     "n_days": int(A.day.nunique())}
    # per-day sums (the real number of independent units)
    g = A.groupby("day").roe.agg(["count", "mean", "sum"])
    out["per_day"] = g.reset_index().to_dict("records")
    U = A.sort_values("rank").drop_duplicates(["coin", "e", "side"])
    out["unique"] = {"n": len(U), "mean": float(U.roe.mean()), "ci_day": day_ci(U.roe, U.day),
                     "nS": int((U.side < 0).sum()), "mS": float(U.roe[U.side < 0].mean()),
                     "nL": int((U.side > 0).sum()), "mL": float(U.roe[U.side > 0].mean()) if (U.side > 0).any() else None,
                     "twin": float(U.roe_opp.mean())}
    # the subset the report names: 1h reversal + timing @4h ICHI_CMO
    sub = A[A["rank"].isin([4, 5])]
    subu = sub.drop_duplicates(["coin", "e", "side"])
    out["named_subset"] = {"n": len(sub), "mean": float(sub.roe.mean()), "n_unique": len(subu),
                           "mean_unique": float(subu.roe.mean()), "ci_day_unique": day_ci(subu.roe, subu.day),
                           "twin_unique": float(subu.roe_opp.mean()), "nS_unique": int((subu.side < 0).sum())}
    other = A[~A["rank"].isin([4, 5])]
    out["other_three"] = {"n": len(other), "mean": float(other.roe.mean())}
    # by coin
    out["by_coin"] = A.groupby("coin").roe.agg(["count", "mean"]).reset_index().to_dict("records")
    # leave-one-day-out pooled mean
    lodo = {}
    for d in sorted(A.day.unique()):
        lodo[int(d)] = float(A.roe[A.day != d].mean())
    out["leave_one_day_out"] = lodo
    # follow-the-trend at every htf... at every tf bar (base table) for the 1h@4h ICHI_CMO pair
    try:
        B = load("base")
        out["base_cols"] = [c for c in B.columns if c.startswith("a2")][:6]
        for tf, htf, src in (("1h", "4h", "c_N07_ICHI_CMO"), ("4h", "1d", "c_T5_ST10_3"), ("4h", "1d", "Jlive"),
                             ("4h", "1d", "l_OBV_S")):
            Bt = B[B.tf == tf]
            st = state(Bt, src, htf)
            res = {}
            for sd, lab in ((1, "long"), (-1, "short")):
                rr = roe(Bt, "a2", opp=False) if "side" in Bt.columns else None
                res[lab] = None
            out.setdefault("base_note", []).append(f"{tf}@{htf}:{src} base cols {list(Bt.columns)[:30]}")
            break
    except Exception as e:  # noqa: BLE001
        out["base_err"] = repr(e)
    A.to_csv(os.path.join(OUTD, "rc_a2F_top5_h2_rows.csv"), index=False,
             columns=["coin", "t", "day", "name", "role", "tf", "side", "cell", "rank", "roe", "roe_opp"])
    json.dump(out, open(os.path.join(OUTD, "rc_actual.json"), "w"), indent=1, default=float)
    print(json.dumps({k: v for k, v in out.items() if k not in ("per_day",)}, indent=1, default=float)[:6000])
    print(g)


if __name__ == "__main__":
    main()
