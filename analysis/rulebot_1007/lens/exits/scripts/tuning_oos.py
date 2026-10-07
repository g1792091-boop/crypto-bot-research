#!/usr/bin/env python3
"""Does picking each strategy x tf's best exit on one period help in the next? (the 'weekly custom-value tuning'
question, for exits). In-sample pick = highest mean R; out-of-sample gain = R(picked) - R(house) on the next period.

    python3 -I tuning_oos.py <exitlab_rows.csv> <out_dir>

Splits: v3b -> v4 (core36), v4 first half -> v4 second half and the reverse (core36 + ds200), by signal time.
Menus: ALL (every exit variant run, leverage variants excluded because they refuse entries) and AI5 (house, geo20_bar,
RL1_0.5_bar, RL1.5_1_bar, tp1R). Cells need >= min_n signals in each period. The cell-level gains are averaged with a
bootstrap over cells (cells share time and are not independent: read the CI as optimistic).
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

LEV = {"lev10", "lev20m20", "lev30m30", "lev40m40", "lev50m50"}
AI5 = ["base", "geo20_bar", "RL1_0.5_bar", "RL1.5_1_bar", "tp1R"]


def main():
    src, out = sys.argv[1], sys.argv[2]
    min_n = 8
    X = load(src)
    X = X[(X.flip == 0) & (X.entered == 1) & X.grp.isin(["core36", "ds200"])]
    piv = X.pivot_table(index=["run", "sig_id", "runl", "grp", "strategy", "timeframe", "bar_close"],
                        columns="variant", values="R").reset_index()
    allv = [c for c in piv.columns if c not in ("run", "sig_id", "runl", "grp", "strategy", "timeframe", "bar_close")
            and c not in LEV]
    v4 = piv[piv.runl == "v4"]
    mid = v4.bar_close.median()
    splits = {
        "v3b->v4 (core36)": (piv[(piv.runl == "v3b") & (piv.grp == "core36")], piv[(piv.runl == "v4") & (piv.grp == "core36")]),
        "v4 H1->H2": (v4[v4.bar_close <= mid], v4[v4.bar_close > mid]),
        "v4 H2->H1": (v4[v4.bar_close > mid], v4[v4.bar_close <= mid]),
    }
    rows, summ = [], []
    rng = np.random.default_rng(5)
    for sname, (A, B) in splits.items():
        for menu_name, menu in (("ALL", allv), ("AI5", AI5)):
            gains, picks = [], []
            for (strat, tf), ga in A.groupby(["strategy", "timeframe"]):
                gb = B[(B.strategy == strat) & (B.timeframe == tf)]
                if len(ga) < min_n or len(gb) < min_n:
                    continue
                ins = ga[menu].mean()
                pick = ins.idxmax()
                oos_pick = gb[pick].mean()
                oos_base = gb["base"].mean()
                oos_best = gb[menu].mean().max()
                rows.append({"split": sname, "menu": menu_name, "strategy": strat, "tf": tf, "n_in": len(ga),
                             "n_out": len(gb), "pick": pick, "in_gain": ins[pick] - ins["base"],
                             "oos_R_pick": oos_pick, "oos_R_base": oos_base, "oos_gain": oos_pick - oos_base,
                             "oos_best_possible_gain": oos_best - oos_base})
                gains.append(oos_pick - oos_base)
                picks.append(pick)
            g = np.array(gains)
            if len(g):
                bs = [rng.choice(g, len(g)).mean() for _ in range(4000)]
                ins_g = np.array([r["in_gain"] for r in rows if r["split"] == sname and r["menu"] == menu_name])
                summ.append({"split": sname, "menu": menu_name, "cells": len(g), "mean_in_sample_gain": ins_g.mean(),
                             "mean_oos_gain": g.mean(), "lo": np.percentile(bs, 2.5), "hi": np.percentile(bs, 97.5),
                             "share_cells_oos_better": float(np.mean(g > 1e-9)),
                             "share_cells_oos_worse": float(np.mean(g < -1e-9)),
                             "picks": " ".join(f"{k}:{v}" for k, v in pd.Series(picks).value_counts().head(6).items())})
    D = pd.DataFrame(rows)
    S = pd.DataFrame(summ)
    D.to_csv(os.path.join(out, "tuning_oos_cells.csv"), index=False)
    S.to_csv(os.path.join(out, "tuning_oos_summary.csv"), index=False)
    pd.set_option("display.width", 250)
    print(S.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
