#!/usr/bin/env python3
"""Nightly d3 shadow variants vs base, per run x account group x timeframe, with time-cluster bootstrap CIs.

    python3 -I d3_paired.py <variants_rows.csv> <out_dir>

Pairs = rows where variant and base both have an ROE (resolved and entered). diff_R in base-stop R units
(rb_analyze's v_R - b_R), diff_pe = pnl on equity (variant - base). Not-entered variant rows (sizing refusal) count
as pnl 0 in diff_pe_ne0. Unresolved variant rows are reported (n_unres) with the base R of those dropped rows
(mean_bR_dropped) to show which way the pairing bias leans. Clusters: the signal bar close floored to 1 h (all coins
together); 4 h blocks as a sensitivity.
"""
import os
import site
import sys

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from statsutil import bh, cluster_boot  # noqa: E402

RUNNAME = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    X = pd.read_csv(src)
    X["runl"] = X["run"].map(RUNNAME)
    X["c1h"] = (X["bc"] // 3_600_000).astype("int64")
    X["c4h"] = (X["bc"] // 14_400_000).astype("int64")
    X["grp"] = X["kind_acct"].map({"strategy": "core36", "ds200": "ds200", "random": "random"})
    rows = []
    groups = [("core36", X["grp"] == "core36"), ("ds200", X["grp"] == "ds200"),
              ("house_all", X["grp"].isin(["core36", "ds200", "random"]))]
    for gname, gmask in groups:
        for (runl, tf, var), g in X[gmask].groupby(["runl", "timeframe", "kind"]):
            if var == "base":
                continue
            pair = g["roe"].notna() & g["b_roe"].notna() & np.isfinite(g["v_R"]) & np.isfinite(g["b_R"])
            p = g[pair]
            unres = g[g["resolved"] == 0]
            ne = g[(g["resolved"] == 1) & g["roe"].isna()]
            dR = (p["v_R"] - p["b_R"]).to_numpy()
            r1 = cluster_boot(dR, p["c1h"].to_numpy())
            r4 = cluster_boot(dR, p["c4h"].to_numpy(), seed=11)
            dpe = (p["v_pnl_eq"] - p["b_pnl_eq"]).to_numpy()
            rp = cluster_boot(dpe, p["c1h"].to_numpy(), seed=13)
            pe_all = pd.concat([p["v_pnl_eq"] - p["b_pnl_eq"], -ne["b_pnl_eq"]])
            rows.append({
                "group": gname, "run": runl, "tf": tf, "variant": var, "rows": len(g), "n_pairs": len(p),
                "n_unres": len(unres), "n_not_entered": len(ne),
                "mean_bR_pairs": p["b_R"].mean(), "mean_vR_pairs": p["v_R"].mean(),
                "mean_bR_dropped": unres["b_R"].mean() if len(unres) else np.nan,
                "diff_R": r1["mean"], "lo_R": r1["lo"], "hi_R": r1["hi"], "p_R": r1["p"], "G1h": r1["G"],
                "lo_R_4h": r4["lo"], "hi_R_4h": r4["hi"], "p_R_4h": r4["p"], "G4h": r4["G"],
                "diff_pe": rp["mean"], "lo_pe": rp["lo"], "hi_pe": rp["hi"],
                "diff_pe_ne0": pe_all.mean() if len(pe_all) else np.nan,
                "share_better": float((dR > 1e-9).mean()) if len(dR) else np.nan,
                "share_same": float((np.abs(dR) <= 1e-9).mean()) if len(dR) else np.nan,
            })
    D = pd.DataFrame(rows)
    m = D["group"] == "house_all"
    D["q_R"] = np.nan
    D.loc[m, "q_R"] = bh(D.loc[m, "p_R"].to_numpy())[1]
    D.to_csv(os.path.join(out, "d3_paired_by_run_tf.csv"), index=False)
    show = D[(D["group"] == "house_all") & D["tf"].isin(["15m", "30m", "1h", "4h"])]
    piv = show.pivot_table(index="variant", columns=["run", "tf"], values="diff_R")
    print(piv.round(3).to_string())
    pn = show.pivot_table(index="variant", columns=["run", "tf"], values="n_pairs")
    print(pn.to_string())
    pu = show.pivot_table(index="variant", columns=["run", "tf"], values="n_unres")
    print(pu.to_string())


if __name__ == "__main__":
    main()
