#!/usr/bin/env python3
"""5-year priors from the repo's pre-registered studies (read-only JSON): ladder geometry (fixed-leverage arms of
research/levstop: same signals, ROE ladder at 10/20/30/40/50x, 2 ATR stop and 1.5-3 ATR) and fixed take-profits
(research/exitstyle) per timeframe and period.

    python3 -I fiveyear_prior.py <repo> <out_dir>

levstop: per-notional mean = mean_roe / leverage (fixed arms enter every signal); period split from mean_eq_p1/p2 /
margin_frac / leverage. Average over the 36 strategies' cells of a timeframe (equal weight) and the signal-weighted
mean. exitstyle: the paired 'diff' (variant - ladder, per trade on equity) by tf and period.
"""
import json
import os
import site
import sys

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def main():
    repo, out = sys.argv[1], sys.argv[2]
    d = json.load(open(os.path.join(repo, "research/levstop/out/levstop.json")))
    cols = d["columns"]
    mf = {int(k): v for k, v in d["margin_frac"].items()}
    rows = []
    for cell, arms in d["cells"].items():
        strat, tf = cell.split("|")
        for arm, vals in arms.items():
            r = dict(zip(cols, vals))
            lev, stop = arm.split("|")
            row = {"strategy": strat, "tf": tf, "arm": arm, "lev": lev, "stop": float(stop), **r}
            if lev != "tiers":
                L = int(lev)
                row["per_notional_bps"] = 1e4 * r["mean_roe"] / L if r["mean_roe"] is not None else np.nan
                row["pn_p1_bps"] = 1e4 * r["mean_eq_p1"] / mf[L] / L if r["mean_eq_p1"] is not None else np.nan
                row["pn_p2_bps"] = 1e4 * r["mean_eq_p2"] / mf[L] / L if r["mean_eq_p2"] is not None else np.nan
            rows.append(row)
    D = pd.DataFrame(rows)
    D.to_csv(os.path.join(out, "fiveyear_levstop_cells.csv"), index=False)
    F = D[D.lev != "tiers"].copy()
    F["w"] = F["signals"]
    agg = []
    for (tf, arm), g in F.groupby(["tf", "arm"]):
        w = g["w"].to_numpy(float)

        def wav(col):
            v = pd.to_numeric(g[col], errors="coerce").to_numpy(float)
            ok = np.isfinite(v) & np.isfinite(w)
            return float(np.average(v[ok], weights=w[ok])) if ok.any() else np.nan
        agg.append({"tf": tf, "arm": arm, "cells": len(g), "signals": int(np.nansum(w)),
                    "pn_bps_eqw": g["per_notional_bps"].mean(),
                    "pn_bps_sigw": wav("per_notional_bps"), "pn_p1_bps_sigw": wav("pn_p1_bps"),
                    "pn_p2_bps_sigw": wav("pn_p2_bps"), "win_rate_sigw": wav("win_rate"),
                    "liq_share_sigw": wav("liq_share"),
                    "cells_pos": int((g["per_notional_bps"] > 0).sum())})
    A = pd.DataFrame(agg)
    # per cell: does the arm beat the 30x arm at the same stop?
    piv = F.pivot_table(index=["strategy", "tf"], columns="arm", values="per_notional_bps")
    for arm in piv.columns:
        L, st = arm.split("|")
        ref = f"30|{st}"
        if ref in piv.columns:
            for tf in A.tf.unique():
                sub = piv.xs(tf, level="tf")
                ok = sub[arm].notna() & sub[ref].notna()
                A.loc[(A.tf == tf) & (A.arm == arm), "cells_beat_30x"] = int((sub.loc[ok, arm] > sub.loc[ok, ref]).sum())
    # difference vs the 30x arm (the live 'normal' leverage) at the same stop, signal-weighted
    for stop in ("1.5", "2.0", "2.5", "3.0"):
        for tf in A.tf.unique():
            ref = A[(A.tf == tf) & (A.arm == f"30|{stop}")]
            if len(ref):
                m = (A.tf == tf) & A.arm.str.endswith(f"|{stop}")
                A.loc[m, "d_vs_30x_bps"] = A.loc[m, "pn_bps_sigw"] - ref["pn_bps_sigw"].iloc[0]
                A.loc[m, "d_vs_30x_p1_bps"] = A.loc[m, "pn_p1_bps_sigw"] - ref["pn_p1_bps_sigw"].iloc[0]
                A.loc[m, "d_vs_30x_p2_bps"] = A.loc[m, "pn_p2_bps_sigw"] - ref["pn_p2_bps_sigw"].iloc[0]
    A.to_csv(os.path.join(out, "fiveyear_levstop_by_tf_arm.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print(A[A.arm.str.endswith("|2.0")].round(2).to_string(index=False))
    print(A[A.arm.str.startswith("30|")].round(2).to_string(index=False))
    # exitstyle
    e = json.load(open(os.path.join(repo, "research/exitstyle/out/exitstyle.json")))
    ec = e["columns"]
    rows = []
    for cell, arms in e["cells"].items():
        strat, tf = cell.split("|")
        for arm, vals in arms.items():
            r = dict(zip(ec, vals))
            rows.append({"strategy": strat, "tf": tf, "arm": arm, **r})
    E = pd.DataFrame(rows)
    E.to_csv(os.path.join(out, "fiveyear_exitstyle_cells.csv"), index=False)
    g = E[E.arm != "ladder"].groupby(["tf", "arm"])
    S = g.apply(lambda x: pd.Series({
        "cells": len(x), "paired_n": x["paired_n"].sum(),
        "diff_pct_eq_w": 100 * np.average(x["diff"].fillna(0), weights=x["paired_n"].fillna(0) + 1e-9),
        "diff_p1_pct_eq_w": 100 * np.average(x["diff_p1"].fillna(0), weights=x["paired_n_p1"].fillna(0) + 1e-9),
        "diff_p2_pct_eq_w": 100 * np.average(x["diff_p2"].fillna(0), weights=x["paired_n_p2"].fillna(0) + 1e-9),
        "cells_better_p05": int((x["p_better"] < 0.05).sum()), "cells_worse_p05": int((x["p_worse"] < 0.05).sum())}),
        include_groups=False).reset_index()
    S.to_csv(os.path.join(out, "fiveyear_exitstyle_by_tf.csv"), index=False)
    print(S.round(4).to_string(index=False))
    print("exitstyle arms:", e.get("arms"), "baseline:", e.get("baseline"))


if __name__ == "__main__":
    main()
