#!/usr/bin/env python3
"""Targeted contrasts between exit variants (A - B on the same signals), per run x tf, plus stop width in OWN-stop R
(what matters under risk-based sizing) and a time-block regime check.

    python3 -I contrasts.py <exitlab_rows.csv> <out_dir>

Outputs: contrasts.csv, stopwidth_own_R.csv, regime_blocks.csv (+ printed summaries).
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

CONTRASTS = [
    # breakeven added to the same exit
    ("be1_tp1.5", "tp1.5R", "BE@1R added to TP1.5R"),
    ("be1_tp2", "tp2R", "BE@1R added to TP2R"),
    ("be1_tp3", "tp3R", "BE@1R added to TP3R"),
    ("be1_RL1.5_1", "RL1.5_1", "BE@1R added to R-ladder 1.5/1"),
    # lock updates at bar close only vs every minute
    ("base_bar", "base", "house ladder: bar-close updates"),
    ("geo20_bar", "geo20", "20x-geometry ladder: bar-close updates"),
    ("RL1_0.5_bar", "RL1_0.5", "R-ladder 1/0.5: bar-close updates"),
    ("RL1.5_1_bar", "RL1.5_1", "R-ladder 1.5/1: bar-close updates"),
    # R ladders vs the 20x price ladder of the AI design
    ("RL1_0.5", "geo20", "R-ladder 1/0.5 vs 20x price ladder"),
    ("RL1_0.5_bar", "geo20_bar", "R-ladder 1/0.5 vs 20x price ladder (both bar-close)"),
    ("RL1.5_1_bar", "geo20_bar", "R-ladder 1.5/1 vs 20x price ladder (both bar-close)"),
    ("RL0.5_0.25", "base", "R-ladder 0.5/0.25 vs house"),
    # time stops on top of the house ladder
    ("timestop", "base", "time stop (house) vs house"),
    ("time_neg", "base", "time stop if losing vs house"),
    ("time_max2x", "base", "max hold 2xN bars vs house"),
    ("tp1R_max2x", "tp1R", "max hold added to TP1R"),
    # fixed TP vs house ladder
    ("tp1R", "base", "TP1R vs house"), ("tp1.5R", "base", "TP1.5R vs house"), ("tp2R", "base", "TP2R vs house"),
    ("ladder_cap2R", "base", "house + 2R cap vs house"),
    # wide vs tight in one number
    ("geo10", "geo50", "10x vs 50x price geometry (same size)"),
]


def contrast_rows(X):
    key = ["run", "sig_id", "flip"]
    rows = []
    X = X[(X.grp.isin(["core36", "ds200", "random"])) & (X.flip == 0) & (X.entered == 1)]
    piv = X.pivot_table(index=key + ["runl", "timeframe", "c1h", "grp"], columns="variant", values="R")
    piv = piv.reset_index()
    for a, b, label in CONTRASTS:
        if a not in piv or b not in piv:
            continue
        for runl in ("v3b", "v4", "pooled"):
            for tf in ("15m", "30m", "1h", "4h"):
                m = (piv.timeframe == tf) & ((piv.runl == runl) if runl != "pooled" else True)
                g = piv[m & piv[a].notna() & piv[b].notna()]
                r = cluster_boot((g[a] - g[b]).to_numpy(), g["c1h"].to_numpy())
                rows.append({"contrast": label, "A": a, "B": b, "run": runl, "tf": tf, "n": r["n"], "G": r["G"],
                             "diff_R": r["mean"], "lo": r["lo"], "hi": r["hi"], "p": r["p"]})
    C = pd.DataFrame(rows)
    m = C.run == "pooled"
    C["q_pooled"] = np.nan
    C.loc[m, "q_pooled"] = bh(C.loc[m, "p"].to_numpy())[1]
    return C


def stopwidth(X):
    """Stop width in OWN-stop R: R_own = pnl / (qty x own stop distance) = R_base x 2 / k. Under risk-based sizing
    (same $ at risk per trade) pnl is proportional to R_own."""
    key = ["run", "sig_id", "flip"]
    X = X[(X.grp.isin(["core36", "ds200", "random"])) & (X.flip == 0) & (X.entered == 1)]
    k = {"base": 2.0, "stopw1.5": 1.5, "stopw2.5": 2.5, "stopw3": 3.0}
    S = X[X.variant.isin(list(k))].copy()
    S["R_own"] = S["R"] * 2.0 / S["variant"].map(k)
    S["cost_own"] = S["costR"] * 2.0 / S["variant"].map(k)
    S["gross_own"] = S["grossR"] * 2.0 / S["variant"].map(k)
    rows = []
    piv = S.pivot_table(index=key + ["runl", "timeframe", "c1h"], columns="variant", values="R_own").reset_index()
    for runl in ("v3b", "v4", "pooled"):
        for tf in ("15m", "30m", "1h", "4h"):
            m = (piv.timeframe == tf) & ((piv.runl == runl) if runl != "pooled" else True)
            g = piv[m]
            for v in ("stopw1.5", "stopw2.5", "stopw3"):
                gg = g[g[v].notna() & g["base"].notna()]
                r = cluster_boot((gg[v] - gg["base"]).to_numpy(), gg["c1h"].to_numpy())
                sub = S[(S.timeframe == tf) & (S.variant == v) & ((S.runl == runl) if runl != "pooled" else True)]
                sb = S[(S.timeframe == tf) & (S.variant == "base") & ((S.runl == runl) if runl != "pooled" else True)]
                rows.append({"run": runl, "tf": tf, "variant": v, "n": r["n"], "R_own_base": gg["base"].mean(),
                             "R_own_var": gg[v].mean(), "diff_R_own": r["mean"], "lo": r["lo"], "hi": r["hi"],
                             "p": r["p"], "cost_own_base": sb["cost_own"].mean(), "cost_own_var": sub["cost_own"].mean(),
                             "gross_own_base": sb["gross_own"].mean(), "gross_own_var": sub["gross_own"].mean()})
    return pd.DataFrame(rows)


def regime_blocks(X, hours=12):
    """Per time block (signal bar close, UTC blocks of ``hours``) and tf group (15m+30m, 1h+4h): mean R of a wide
    exit (geo10, RL2_1, tp3R) minus the house ladder; consecutive-block correlation of that difference."""
    key = ["run", "sig_id", "flip"]
    X = X[(X.grp.isin(["core36", "ds200", "random"])) & (X.flip == 0) & (X.entered == 1)].copy()
    X["blk"] = (X["bar_close"] // (hours * 3_600_000)).astype("int64")
    X["tfg"] = X["timeframe"].map({"15m": "15m+30m", "30m": "15m+30m", "1h": "1h+4h", "4h": "1h+4h"})
    piv = X.pivot_table(index=key + ["blk", "tfg", "runl"], columns="variant", values="R").reset_index()
    rows = []
    for (tfg, blk), g in piv.groupby(["tfg", "blk"]):
        r = {"tfg": tfg, "blk": blk, "start_utc": str(pd.Timestamp(blk * hours * 3_600_000, unit="ms")),
             "runs": "+".join(sorted(g.runl.unique())), "n": len(g), "R_base": g["base"].mean()}
        for v in ("geo10", "RL2_1", "RL1_0.5", "tp3R", "tp1R", "timestop", "geo50"):
            r[f"d_{v}"] = (g[v] - g["base"]).mean()
        rows.append(r)
    B = pd.DataFrame(rows).sort_values(["tfg", "blk"])
    out = []
    for tfg, g in B.groupby("tfg"):
        g = g[g.n >= 30]
        for v in ("geo10", "RL2_1", "RL1_0.5", "tp3R", "tp1R"):
            s = g[f"d_{v}"].to_numpy()
            if len(s) > 3:
                ac = np.corrcoef(s[:-1], s[1:])[0, 1]
                signs = "".join("+" if x > 0 else "-" for x in s)
                out.append({"tfg": tfg, "variant": v, "blocks": len(s), "lag1_corr": ac, "signs_in_time_order": signs,
                            "share_pos": float(np.mean(s > 0))})
    return B, pd.DataFrame(out)


def main():
    src, out = sys.argv[1], sys.argv[2]
    X = load(src)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    C = contrast_rows(X)
    C.to_csv(os.path.join(out, "contrasts.csv"), index=False)
    pv = C.pivot_table(index=["contrast", "tf"], columns="run", values="diff_R").reset_index()
    ci = C[C.run == "pooled"].set_index(["contrast", "tf"])[["lo", "hi", "q_pooled", "n"]]
    pv = pv.join(ci, on=["contrast", "tf"])
    pv["same_sign"] = np.sign(pv["v3b"]) == np.sign(pv["v4"])
    print(pv[pv.tf.isin(["15m", "30m", "1h"])].round(3).to_string(index=False))
    S = stopwidth(X)
    S.to_csv(os.path.join(out, "stopwidth_own_R.csv"), index=False)
    print(S.round(3).to_string(index=False))
    for h in (12, 6):
        B, A = regime_blocks(X, hours=h)
        B.to_csv(os.path.join(out, f"regime_blocks_{h}h.csv"), index=False)
        A.to_csv(os.path.join(out, f"regime_blocks_{h}h_autocorr.csv"), index=False)
        print(f"--- {h}h blocks")
        print(B.round(3).to_string(index=False))
        print(A.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
