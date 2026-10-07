#!/usr/bin/env python3
"""Per strategy x timeframe: every-signal mean R under the house exit and the candidate AI exits, per run, with
time-cluster CIs, and how far the exit choice moves the cell (exit sensitivity).

    python3 -I strat_cells.py <exitlab_rows.csv> <out_dir> [min_n]

R in base-stop units, OPEN_END marked to the last bar. Duplicated signals (several DeepSeek definitions or accounts
emitting the same coin / bar / side) are kept per account (they are what each account would trade) but clusters are
1 h blocks, so they do not add independent evidence. BH over the pooled base-R tests of the graded cells.
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

from analyze_exitlab import load  # noqa: E402
from statsutil import bh, cluster_boot  # noqa: E402

CAND = ["base", "geo20_bar", "RL1_0.5_bar", "RL1.5_1_bar", "tp1R", "be1_tp2", "timestop", "geo10"]


def main():
    src, out = sys.argv[1], sys.argv[2]
    min_n = int(sys.argv[3]) if len(sys.argv) > 3 else 25
    X = load(src)
    X = X[(X.flip == 0) & (X.entered == 1) & X.grp.isin(["core36", "ds200"])]
    key = ["run", "sig_id"]
    piv = X.pivot_table(index=key + ["runl", "grp", "strategy", "timeframe", "c1h"], columns="variant",
                        values="R").reset_index()
    allv = [c for c in piv.columns if c not in key + ["runl", "grp", "strategy", "timeframe", "c1h", "flip"]
            and c not in ("lev10", "lev20m20", "lev30m30", "lev40m40", "lev50m50")]  # leverage variants refuse entries
    rows = []
    for (grp, strat, tf), g in piv.groupby(["grp", "strategy", "timeframe"]):
        if len(g) < min_n:
            continue
        r = {"group": grp, "strategy": strat, "tf": tf, "n": len(g), "n_v3b": int((g.runl == "v3b").sum()),
             "n_v4": int((g.runl == "v4").sum())}
        b = cluster_boot(g["base"].to_numpy(), g["c1h"].to_numpy())
        r.update(R_base=b["mean"], lo_base=b["lo"], hi_base=b["hi"], p_base=b["p"], G=b["G"])
        for rl in ("v3b", "v4"):
            gg = g[g.runl == rl]
            r[f"R_base_{rl}"] = gg["base"].mean() if len(gg) else np.nan
        for v in CAND[1:]:
            if v in g:
                r[f"R_{v}"] = g[v].mean()
                for rl in ("v3b", "v4"):
                    gg = g[g.runl == rl]
                    r[f"R_{v}_{rl}"] = gg[v].mean() if len(gg) else np.nan
        means = g[allv].mean()
        r["best_exit"] = means.idxmax()
        r["R_best_exit"] = means.max()
        r["worst_exit"] = means.idxmin()
        r["R_worst_exit"] = means.min()
        r["exit_spread_R"] = means.max() - means.min()
        r["n_exits_pos"] = int((means > 0).sum())
        r["n_exits"] = int(means.notna().sum())
        r["win_base"] = float((g["base"] > 0).mean())
        rows.append(r)
    D = pd.DataFrame(rows)
    D["q_base"] = bh(D["p_base"].to_numpy())[1]

    def grade(r):
        both = [r.get("R_base_v3b"), r.get("R_base_v4")]
        both = [x for x in both if x == x]
        if r["q_base"] <= 0.10 and r["R_base"] > 0:
            return "A"
        if r["R_base"] > 0 and r["lo_base"] > -0.05 and all(x > 0 for x in both):
            return "B"
        if r["R_base"] > 0:
            return "C"
        if r["q_base"] <= 0.10 and r["R_base"] < 0:
            return "F"
        return "D"
    D["grade"] = D.apply(grade, axis=1)
    D = D.sort_values(["tf", "R_base"], ascending=[True, False])
    D.to_csv(os.path.join(out, "strategy_tf_exits.csv"), index=False)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 500)
    cols = ["group", "strategy", "tf", "n", "n_v3b", "n_v4", "R_base", "lo_base", "hi_base", "q_base", "R_base_v3b",
            "R_base_v4", "R_geo20_bar", "R_RL1_0.5_bar", "R_tp1R", "best_exit", "R_best_exit", "exit_spread_R",
            "n_exits_pos", "grade"]
    print(D[cols].round(3).to_string(index=False))
    print(D.groupby(["tf", "grade"]).size().unstack(1).fillna(0).astype(int))
    print("cells:", len(D), "with any exit mean > 0:", int((D.R_best_exit > 0).sum()),
          "base > 0:", int((D.R_base > 0).sum()))


if __name__ == "__main__":
    main()
