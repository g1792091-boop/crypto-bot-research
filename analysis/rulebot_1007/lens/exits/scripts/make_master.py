#!/usr/bin/env python3
"""One table per variant x tf: v3a (nightly d3, entered trades, unresolved dropped: biased against wide exits),
v3b and v4 (exitlab re-run, every signal, open marked), pooled v3b+v4 with 1 h-cluster CI and BH q, the
side-flipped (coin-flip) difference, and pnl on equity.

    python3 -I make_master.py <out_dir>
"""
import os
import site
import sys

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MAP_D3 = {"lev20": "lev20m20", "lev30": "lev30m30"}   # same thing at the margin share used in v4 (R identical)


def main():
    out = sys.argv[1]
    D = pd.read_csv(os.path.join(out, "d3_paired_by_run_tf.csv"))
    D = D[(D.group == "house_all") & (D.run == "v3a")].copy()
    D["variant"] = D["variant"].replace(MAP_D3)
    d3 = D.set_index(["tf", "variant"])[["n_pairs", "n_unres", "diff_R", "lo_R", "hi_R", "diff_pe"]].add_prefix("v3a_")
    P = pd.read_csv(os.path.join(out, "exitlab_paired.csv"))
    M = P[(P.group == "house_all") & (P.set == "ALL") & (P.flip == 0)]
    parts = []
    for run in ("v3b", "v4", "pooled"):
        x = M[M.run == run].set_index(["tf", "variant"])[["n_paired", "diff_R", "lo_R", "hi_R", "diff_pe_pct"]]
        parts.append(x.add_prefix(f"{run}_"))
    q = M[M.run == "pooled"].set_index(["tf", "variant"])[["q_R_main"]]
    F = P[(P.group == "house_all") & (P.set == "ALL") & (P.flip == 1) & (P.run == "pooled")].set_index(
        ["tf", "variant"])[["diff_R"]].rename(columns={"diff_R": "flip_diff_R"})
    T = pd.concat(parts + [q, F], axis=1).join(d3, how="left").reset_index()
    T["v3a_diff_pe_pct"] = 100 * T["v3a_diff_pe"]
    T = T.drop(columns=["v3a_diff_pe"])

    def signs(r):
        s = ""
        for c in ("v3a_diff_R", "v3b_diff_R", "v4_diff_R"):
            v = r[c]
            s += "." if v != v else ("+" if v > 0.005 else ("-" if v < -0.005 else "0"))
        return s
    T["signs_v3a_v3b_v4"] = T.apply(signs, axis=1)
    order = {"15m": 0, "30m": 1, "1h": 2, "4h": 3}
    T = T.sort_values(["tf", "variant"], key=lambda s: s.map(order) if s.name == "tf" else s)
    T.to_csv(os.path.join(out, "master_variant_tf.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 300)
    cols = ["tf", "variant", "v3a_n_pairs", "v3a_diff_R", "v3b_n_paired", "v3b_diff_R", "v4_n_paired", "v4_diff_R",
            "pooled_diff_R", "pooled_lo_R", "pooled_hi_R", "q_R_main", "flip_diff_R", "v3a_diff_pe_pct",
            "v3b_diff_pe_pct", "v4_diff_pe_pct", "signs_v3a_v3b_v4"]
    print(T[cols].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
