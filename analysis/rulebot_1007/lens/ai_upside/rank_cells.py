#!/usr/bin/env python3
"""AI-headroom table per strategy x timeframe, with the stability checks that decide whether a per-strategy ranking
means anything.

    python3 -I rank_cells.py <out_real_dir> <out_dir>

Grade rule (fixed before reading the per-cell output; see PREREG.md for the rules):
  N   fewer than 15 replayed signals (v3b+v4) AND fewer than 15 real trades: too few to say anything
  H1  exit headroom upper bound (signals, v3b+v4) >= 0.25 R/signal AND at least one of CUT05 / NP4 / NP8 / BE05 has
      mean diff > 0 in every run the cell has (core 36: v3b and v4 both with >= 5 signals; DeepSeek: v4 only, marked)
      and pooled diff >= +0.05 R
  H2  upper bound >= 0.20 R/signal but no simple exit rule captures any of it consistently ("on paper only")
  L   upper bound < 0.20 R/signal: little exit headroom
  Separate flag 'base_hopeless': every-signal mean R <= -0.25 and side-flip excess <= 0 (exits cannot fix the entry).
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True
import site  # noqa: E402
sys.path.append(site.getusersitepackages())
import os  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

DAYS = {"v3b": 0.699, "v4": 1.5, "v3a": 2.61}
EXIT_RULES = ["CUT05", "NP4", "NP8", "BE05"]


def spearman(a, b):
    a, b = pd.Series(a).rank(), pd.Series(b).rank()
    return float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 else np.nan


def main():
    oreal, out = sys.argv[1:3]
    G = pd.read_csv(os.path.join(out, "giveback_cells.csv"))
    RC = pd.read_csv(os.path.join(out, "rules_cells.csv"))
    SF = pd.read_csv(os.path.join(oreal, "coinflip_sideflip.csv"))
    SF = SF[SF["level"] == "strategy_tf"][["kind", "strategy", "timeframe", "n_pairs", "excess_R", "p_better"]]
    SF = SF.rename(columns={"timeframe": "tf", "n_pairs": "sideflip_n", "excess_R": "sideflip_excess_R",
                            "p_better": "sideflip_p_better"})
    gs = G[G["src"] == "signals"].set_index(["kind", "strategy", "tf"])
    gt = G[G["src"] == "trades"].set_index(["kind", "strategy", "tf"])
    keys = sorted(set(gs.index) | set(gt.index))
    rows = []
    for k in keys:
        kind, strat, tf = k
        r = {"kind": kind, "strategy": strat, "tf": tf}
        if k in gs.index:
            s = gs.loc[k]
            r.update(sig_n=int(s["n"]), sig_n_v3b=int(s["n_v3b"]), sig_n_v4=int(s["n_v4"]), sig_mean_R=s["mean_R"],
                     sig_mean_R_v3b=s["mean_R_v3b"], sig_mean_R_v4=s["mean_R_v4"],
                     sig_share_mfe05=s["share_mfe_ge_0.5"], sig_gb05_SL=s["share_gb05_SL"],
                     sig_dead_share_losers=s["dead_share_of_losers"], sig_ub_gb=s["ub_breakeven_gb_R"],
                     sig_ub_dead=s["ub_cut_dead_R"], sig_ub_sum=s["ub_sum_R"], sig_ub_sum_v3b=s["ub_sum_R_v3b"],
                     sig_ub_sum_v4=s["ub_sum_R_v4"], sig_oracle=s["oracle_exit_R"],
                     signals_per_day=s["n_v3b"] / DAYS["v3b"] * 0 + (s["n_v3b"] + s["n_v4"]) / (DAYS["v3b"] + DAYS["v4"])
                     if kind == "strategy" else s["n_v4"] / DAYS["v4"])
        if k in gt.index:
            t = gt.loc[k]
            r.update(tr_n=int(t["n"]), tr_n_v3a=int(t["n_v3a"]), tr_mean_R=t["mean_R"], tr_mean_R_v3a=t["mean_R_v3a"],
                     tr_mean_R_v3b=t["mean_R_v3b"], tr_mean_R_v4=t["mean_R_v4"], tr_ub_sum=t["ub_sum_R"],
                     tr_ub_sum_v3a=t["ub_sum_R_v3a"], tr_gb05_SL=t["share_gb05_SL"],
                     tr_dead_share_losers=t["dead_share_of_losers"], tr_oracle=t["oracle_exit_R"])
        rc = RC[(RC["kind"] == kind) & (RC["strategy"] == strat) & (RC["timeframe"] == tf)].set_index("rule")
        best, cons = None, []
        for rule in ["CUT05", "NP4", "NP8", "BE05", "TP1", "OPP", "OPPH"]:
            if rule in rc.index:
                x = rc.loc[rule]
                r[f"d_{rule}"] = x["mean_diff"]
                r[f"d_{rule}_v3b"] = x["diff_v3b"]
                r[f"d_{rule}_v4"] = x["diff_v4"]
                if rule in EXIT_RULES:
                    runs_ok = []
                    if kind == "strategy":
                        runs_ok = [x["n_v3b"] >= 5 and x["diff_v3b"] > 0, x["n_v4"] >= 5 and x["diff_v4"] > 0]
                    else:
                        runs_ok = [x["n_v4"] >= 5 and x["diff_v4"] > 0]
                    if all(runs_ok) and x["mean_diff"] >= 0.05:
                        cons.append(f"{rule}({x['mean_diff']:+.2f})")
        r["consistent_exit_rules"] = " ".join(cons)
        rows.append(r)
    D = pd.DataFrame(rows).merge(SF, on=["kind", "strategy", "tf"], how="left")
    ub = D["sig_ub_sum"].fillna(D["tr_ub_sum"])
    n_sig = D["sig_n"].fillna(0)
    n_tr = D["tr_n"].fillna(0)
    grade = np.where((n_sig < 15) & (n_tr < 15), "N",
             np.where((ub >= 0.25) & (D["consistent_exit_rules"] != "") & (n_sig >= 15), "H1",
             np.where(ub >= 0.20, "H2", "L")))
    D["exit_headroom_ub"] = ub
    D["grade"] = grade
    D["grade"] = np.where((D["kind"] == "ds200") & (D["grade"] == "H1"), "H1 (v4 only)", D["grade"])
    base = D["sig_mean_R"].fillna(D["tr_mean_R"])
    D["base_hopeless"] = (base <= -0.25) & (D["sideflip_excess_R"].fillna(0) <= 0)
    D["mean_R_base_best_source"] = base
    D = D.sort_values(["tf", "kind", "exit_headroom_ub"], ascending=[True, True, False])
    D.to_csv(os.path.join(out, "headroom_rank.csv"), index=False)

    # ---- stability: is per-strategy headroom a property of the strategy (same ranking across runs)?
    st = []
    for kind in ("strategy",):
        for tf in ("15m", "30m", "1h"):
            g = D[(D["kind"] == kind) & (D["tf"] == tf)]
            a = g[(g["sig_n_v3b"] >= 10) & (g["sig_n_v4"] >= 10)]
            st.append({"what": "UB v3b vs v4 (signals)", "kind": kind, "tf": tf, "cells": len(a),
                       "spearman": spearman(a["sig_ub_sum_v3b"], a["sig_ub_sum_v4"])})
            st.append({"what": "mean R v3b vs v4 (signals)", "kind": kind, "tf": tf, "cells": len(a),
                       "spearman": spearman(a["sig_mean_R_v3b"], a["sig_mean_R_v4"])})
            for rule in ("CUT05", "NP4", "BE05"):
                st.append({"what": f"{rule} diff v3b vs v4", "kind": kind, "tf": tf, "cells": len(a),
                           "spearman": spearman(a[f"d_{rule}_v3b"], a[f"d_{rule}_v4"])})
            b = g[(g["tr_n_v3a"] >= 8) & (g["sig_n_v4"] >= 10)]
            st.append({"what": "UB v3a trades vs v4 signals", "kind": kind, "tf": tf, "cells": len(b),
                       "spearman": spearman(b["tr_ub_sum_v3a"], b["sig_ub_sum_v4"])})
    ST = pd.DataFrame(st)
    # permutation null for one representative: 15m UB v3b vs v4
    ST.to_csv(os.path.join(out, "headroom_stability.csv"), index=False)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_columns", 40)
    print(ST.round(3).to_string())
    cols = ["kind", "strategy", "tf", "grade", "sig_n", "signals_per_day", "tr_n", "mean_R_base_best_source", "sig_mean_R_v3b",
            "sig_mean_R_v4", "tr_mean_R", "exit_headroom_ub", "sig_oracle", "sig_gb05_SL", "sig_dead_share_losers",
            "d_CUT05", "d_NP4", "d_BE05", "consistent_exit_rules", "sideflip_excess_R", "base_hopeless"]
    print(D[D["tf"].isin(["15m", "30m"])][cols].round(3).to_string())
    print(D.groupby(["kind", "tf", "grade"]).size().unstack(fill_value=0))


if __name__ == "__main__":
    main()
