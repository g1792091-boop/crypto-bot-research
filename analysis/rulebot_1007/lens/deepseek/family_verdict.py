#!/usr/bin/env python3
"""Family verdicts + noise diagnostics + ds200 vs core-36 + variant what-ifs by family (ds200, v4).

    python3 -I family_verdict.py <out_dir> <out_real_dir>
Writes family_verdict.csv, diagnostics.csv, variants_family_ds.csv into <out_dir>.
"""
from __future__ import annotations

import math
import os
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

MIN, HOUR = 60_000, 3_600_000
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}


def cl_t(x, cl):
    x = np.asarray(x, float)
    n = len(x)
    if n < 3:
        return np.nan, np.nan, np.nan, len(np.unique(cl))
    m = x.mean()
    labs, inv = np.unique(cl, return_inverse=True)
    G = len(labs)
    s = np.bincount(inv, weights=x - m)
    se = math.sqrt((G / (G - 1)) * np.sum(s ** 2) / n ** 2) if G > 1 else np.nan
    tq = stats.t.ppf(0.975, G - 1) if G > 1 else np.nan
    return m, m - tq * se, m + tq * se, G


def main(out, out_real):
    C = pd.read_csv(os.path.join(out, "cards_deepseek.csv"))
    F = pd.read_csv(os.path.join(out, "family_tf.csv"))
    F = F[F["basis"] == "unique_signals"]
    SD = pd.read_csv(os.path.join(out, "sideflip_drift.csv"))
    SD = SD[SD["level"] == "family_tf"]
    rows = []
    for fam, g in C.groupby("family"):
        d = {"family": fam, "definitions": " ".join(sorted(g["definition"].unique())),
             "kept_representatives": " ".join(sorted({k.split("@")[0] for k in g["kept_as"]}))}
        for tf in ("15m", "30m", "1h", "4h"):
            f = F[(F["family"] == fam) & (F["timeframe"] == tf)]
            s = SD[(SD["family"] == fam) & (SD["timeframe"] == tf)]
            gg = g[g["timeframe"] == tf]
            d[f"{tf}_grades"] = " ".join(f"{a}:{b}" for a, b in zip(gg["definition"], gg["grade"]))
            if len(f):
                f0 = f.iloc[0]
                d[f"{tf}_n_unique"] = f0["n"]
                d[f"{tf}_mean_R"] = f0["mean_R"]
                d[f"{tf}_lo"], d[f"{tf}_hi"] = f0["lo"], f0["hi"]
                d[f"{tf}_p_gt0"] = f0["p_gt0"]
                d[f"{tf}_gross_R"] = f0["mean_gross_R"]
                d[f"{tf}_H1_R"], d[f"{tf}_H2_R"] = f0["H1_mean_R"], f0["H2_mean_R"]
                d[f"{tf}_signals_per_day_unique"] = f0["signals_per_day"]
                d[f"{tf}_y_is_mean_pct"] = f0["y_is_mean_pct_w"]
                d[f"{tf}_y_cf_mean_pct"] = f0["y_cf_mean_pct_w"]
                d[f"{tf}_y_pre_mean_pct"] = f0["y_pre_mean_pct_w"]
                d[f"{tf}_y_is_gross_pct"] = f0["y_is_gross_pct_w"]
            if len(s):
                d[f"{tf}_sf_excess"] = s.iloc[0]["excess_all"]
                d[f"{tf}_sf_excess_drift_neutral"] = s.iloc[0]["excess_drift_neutral"]
                d[f"{tf}_sf_p_drift_neutral"] = s.iloc[0].get("p_drift_neutral")
        rows.append(d)
    FV = pd.DataFrame(rows)
    FV.to_csv(os.path.join(out, "family_verdict.csv"), index=False)

    # ---------------- noise diagnostics
    diag = []
    T = C[(C["rp_traded"] >= 10) & (C["rp_G"] >= 8)]
    for tf in ("15m", "30m", "*"):
        t = T if tf == "*" else T[T["timeframe"] == tf]
        t = t[t["rp_H1_n"].fillna(0).ge(3) & t["rp_H2_n"].fillna(0).ge(3)]
        if len(t) >= 5:
            r, p = stats.spearmanr(t["rp_H1_mean_R"], t["rp_H2_mean_R"])
            diag.append({"what": "spearman H1 vs H2 mean R across testable cells (>=3 trades each half)", "timeframe": tf,
                         "n_cells": len(t), "rho": r, "p": p})
        t2 = (T if tf == "*" else T[T["timeframe"] == tf])
        if len(t2) >= 5:
            r, p = stats.spearmanr(t2["rp_mean_R"], t2["y_best_mean12_pct"])
            diag.append({"what": "spearman live replay mean R vs 5-year best-exit net mean (periods 1+2)", "timeframe": tf,
                         "n_cells": len(t2), "rho": r, "p": p})
            r, p = stats.spearmanr(t2["rp_mean_R"], t2["acct_mean_R"], nan_policy="omit")
            diag.append({"what": "spearman replay mean R (every signal) vs one-position account mean R", "timeframe": tf,
                         "n_cells": int(t2["acct_mean_R"].notna().sum()), "rho": r, "p": p})
    # 5-year: is the IS rank kept in CF? (all 171 definition x tf, best exit chosen on IS)
    Y = C.dropna(subset=["yx5_is_mean_pct", "yx2_is_mean_pct"]).copy()
    Y["is_best"] = Y[["yx5_is_mean_pct", "yx2_is_mean_pct"]].max(axis=1)
    Y["cf_of_is_best"] = np.where(Y["yx5_is_mean_pct"] >= Y["yx2_is_mean_pct"], Y["yx5_cf_mean_pct"], Y["yx2_cf_mean_pct"])
    Y["pre_of_is_best"] = np.where(Y["yx5_is_mean_pct"] >= Y["yx2_is_mean_pct"], Y["yx5_pre_mean_pct"], Y["yx2_pre_mean_pct"])
    for tf in ("15m", "30m", "1h", "4h"):
        y = Y[Y["timeframe"] == tf]
        r, p = stats.spearmanr(y["is_best"], y["cf_of_is_best"])
        diag.append({"what": "5-year: spearman period-1 vs period-2 net mean (exit picked on period 1)", "timeframe": tf,
                     "n_cells": len(y), "rho": r, "p": p,
                     "share_cf_positive": float((y["cf_of_is_best"] > 0).mean()),
                     "share_is_positive": float((y["is_best"] > 0).mean())})
        r, p = stats.spearmanr(y["is_best"], y["pre_of_is_best"])
        diag.append({"what": "5-year: spearman period-1 vs period-3 net mean (exit picked on period 1)", "timeframe": tf,
                     "n_cells": len(y), "rho": r, "p": p, "share_pre_positive": float((y["pre_of_is_best"] > 0).mean())})
    # ds200 vs core 36, same run, every signal replay (cluster t CI, 1h-or-tf clusters)
    R = pd.read_csv(os.path.join(out_real, "replay_signals.csv"))
    R = R[(R["run"] == "current") & (R["status"] == "TRADED") & R["kind"].isin(["ds200", "strategy"])].copy()
    blk = np.maximum(R["timeframe"].map(TFM).to_numpy() * MIN, HOUR)
    R["cl"] = R["bar_close"].to_numpy() // blk
    for (k, tf), g in R.groupby(["kind", "timeframe"]):
        m, lo, hi, G = cl_t(g["R"], g["cl"])
        nl, ns = (g["side"] > 0).sum(), (g["side"] < 0).sum()
        sb = 0.5 * (g.loc[g["side"] > 0, "R"].mean() + g.loc[g["side"] < 0, "R"].mean())
        diag.append({"what": f"replay every signal, kind {k}", "timeframe": tf, "n_cells": len(g), "rho": m, "p": np.nan,
                     "lo": lo, "hi": hi, "G": G, "long_share": nl / len(g), "side_balanced_R": sb})
    D = pd.DataFrame(diag)
    D.to_csv(os.path.join(out, "diagnostics.csv"), index=False)
    print(D.round(3).to_string())

    # ---------------- d3 nightly variants by family x tf (ds200, paired on resolved rows; biased, see summary.md)
    V = pd.read_csv(os.path.join(out_real, "variants_rows.csv"))
    V = V[(V["kind_acct"] == "ds200")].copy()
    V["family"] = V["strategy"].str.split("_").str[0]
    V = V[(V["resolved"] == 1) & (V["b_resolved"] == 1) & V["v_R"].notna() & V["b_R"].notna()]
    V["dR"] = V["v_R"] - V["b_R"]
    keep = ["lev10", "lev20", "lev40", "lock15", "lock20", "lock30", "tp1R", "tp1.5R", "tp2R", "timestop", "stopw1.5", "stopw3"]
    V = V[V["kind"].isin(keep)]
    vt = V.groupby(["kind", "timeframe"]).agg(n=("dR", "size"), diff_R=("dR", "mean"), base_R=("b_R", "mean")).reset_index()
    vt["level"] = "tf"
    vf = V[V["timeframe"].isin(["15m", "30m"])].groupby(["kind", "family"]).agg(
        n=("dR", "size"), diff_R=("dR", "mean"), base_R=("b_R", "mean")).reset_index()
    vf["level"] = "family_15m30m"
    VV = pd.concat([vt, vf], ignore_index=True)
    VV.to_csv(os.path.join(out, "variants_family_ds.csv"), index=False)
    print(vt.pivot_table(index="kind", columns="timeframe", values=["diff_R", "n"]).round(3).to_string())


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
