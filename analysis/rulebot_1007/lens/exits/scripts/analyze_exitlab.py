#!/usr/bin/env python3
"""Paired variant-vs-base statistics from exitlab rows.

    python3 -I analyze_exitlab.py <exitlab_rows.csv> <out_dir>

R of every variant is in BASE-stop units: pnl_v / (qty_v x |entry - base 2 ATR stop|) (same entry fill for all
variants). pe = pnl on equity of a fresh $5,000 account (not entered = 0). OPEN_END rows are marked to the last bar
with exit costs (no outcome-based selection). Sets: ALL = every signal the base entered; RES = signals where every
variant closed (or was refused) before the bars ended (sensitivity, selected on resolution time).
Clusters for the bootstrap: the signal's bar close floored to 1 h (all coins and strategies together); 4 h blocks as
a sensitivity. BH over the pooled (v3b + v4) variant x tf tests of the main group.
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

RUNL = {"run-20261005T183457Z": "v3b", "current": "v4"}
EQ0 = 5000.0


def load(path):
    X = pd.read_csv(path, low_memory=False)
    X["runl"] = X["run"].map(RUNL)
    key = ["run", "sig_id", "flip"]
    b = X[X.variant == "base"][key + ["status", "entry_price", "stop_initial", "pnl", "qty", "leverage"]].rename(
        columns={"status": "b_status", "entry_price": "b_entry", "stop_initial": "b_stop", "pnl": "b_pnl",
                 "qty": "b_qty", "leverage": "b_lev"})
    X = X.merge(b, on=key, how="left")
    X = X[X.b_status.isin(["CLOSED", "OPEN_END"])].copy()
    X["dist"] = (X["b_entry"] - X["b_stop"]).abs()
    ent = X.status.isin(["CLOSED", "OPEN_END"])
    X["R"] = np.where(ent, X["pnl"] / (X["qty"] * X["dist"]), np.nan)
    X["grossR"] = np.where(ent, (X["pnl"] + X["fees"] + X["funding"]) / (X["qty"] * X["dist"]), np.nan)
    X["costR"] = X["grossR"] - X["R"]
    X["pe"] = np.where(ent, X["pnl"] / EQ0, 0.0)
    X["entered"] = ent.astype(int)
    X["open_end"] = (X.status == "OPEN_END").astype(int)
    X["hold_min"] = np.where(X.status == "CLOSED", (X["exit_time"] - X["entry_time"]) / 60000,
                             np.where(X.status == "OPEN_END", (X["bars_end"] - X["entry_time"]) / 60000, np.nan))
    X["c1h"] = (X["bar_close"] // 3_600_000).astype("int64")
    X["c4h"] = (X["bar_close"] // 14_400_000).astype("int64")
    X["grp"] = X["kind"].map({"strategy": "core36", "ds200": "ds200", "random": "random"})
    # resolved-in-all-variants flag per signal
    allres = X.groupby(key)["open_end"].max().rename("any_open").reset_index()
    X = X.merge(allres, on=key, how="left")
    X["mfe_R"] = np.where(ent, X["side"] * (X["mfe_price"] - X["b_entry"]) / X["dist"], np.nan)
    return X


def paired(X, groups, runs, tfs, sets, flips, B=3000):
    key = ["run", "sig_id", "flip"]
    base = X[X.variant == "base"].set_index(key)
    rows = []
    for gname, gsel in groups.items():
        for setname in sets:
            for fl in flips:
                Xg = X[gsel(X) & (X.flip == fl)]
                if setname == "RES":
                    Xg = Xg[Xg.any_open == 0]
                for runname, rsel in runs.items():
                    Xr = Xg[rsel(Xg)]
                    for tf in tfs:
                        Xt = Xr[Xr.timeframe == tf]
                        if not len(Xt):
                            continue
                        bt = Xt[Xt.variant == "base"].set_index(key)
                        for var, g in Xt.groupby("variant"):
                            if var == "base":
                                continue
                            g = g.set_index(key)
                            j = g.join(bt[["R", "grossR", "pe", "hold_min", "open_end"]], rsuffix="_b", how="inner")
                            pr = j[j.entered == 1]
                            dR = (pr["R"] - pr["R_b"]).to_numpy()
                            r1 = cluster_boot(dR, pr["c1h"].to_numpy(), B=B)
                            r4 = cluster_boot(dR, pr["c4h"].to_numpy(), B=B, seed=11)
                            dpe = (j["pe"] - j["pe_b"]).to_numpy()
                            rp = cluster_boot(dpe, j["c1h"].to_numpy(), B=B, seed=13)
                            wins = pr["R"] > 0
                            aw = pr.loc[wins, "R"].mean()
                            al = pr.loc[~wins, "R"].mean()
                            rows.append({
                                "group": gname, "set": setname, "flip": fl, "run": runname, "tf": tf, "variant": var,
                                "n_signals": len(j), "n_paired": len(pr), "not_entered": int((j.entered == 0).sum()),
                                "open_end_var": int(j.open_end.sum()), "open_end_base": int(j.open_end_b.sum()),
                                "R_base": pr["R_b"].mean(), "R_var": pr["R"].mean(), "diff_R": r1["mean"],
                                "lo_R": r1["lo"], "hi_R": r1["hi"], "p_R": r1["p"], "G1h": r1["G"],
                                "lo_R_4h": r4["lo"], "hi_R_4h": r4["hi"], "p_R_4h": r4["p"], "G4h": r4["G"],
                                "grossR_base": pr["grossR_b"].mean(), "grossR_var": pr["grossR"].mean(),
                                "pe_base_pct": 100 * j["pe_b"].mean(), "pe_var_pct": 100 * j["pe"].mean(),
                                "diff_pe_pct": 100 * rp["mean"], "lo_pe_pct": 100 * rp["lo"], "hi_pe_pct": 100 * rp["hi"],
                                "win_var": wins.mean(), "avgwin_var": aw, "avgloss_var": al,
                                "payoff_var": aw / -al if al and al < 0 else np.nan,
                                "share_better": float(np.mean(dR > 1e-9)) if len(dR) else np.nan,
                                "share_same": float(np.mean(np.abs(dR) <= 1e-9)) if len(dR) else np.nan,
                                "hold_base_med": j["hold_min_b"].median(), "hold_var_med": j["hold_min"].median(),
                                "exit_mix": " ".join(f"{k}:{v}" for k, v in g["exit_reason"].value_counts().items()),
                            })
    return pd.DataFrame(rows)


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    X = load(src)
    groups = {"house_all": lambda d: d.grp.isin(["core36", "ds200", "random"]),
              "core36": lambda d: d.grp == "core36", "ds200": lambda d: d.grp == "ds200"}
    runs = {"v3b": lambda d: d.runl == "v3b", "v4": lambda d: d.runl == "v4", "pooled": lambda d: d.runl.notna()}
    tfs = ["15m", "30m", "1h", "4h"]
    P = paired(X, groups, runs, tfs, sets=["ALL", "RES"], flips=[0, 1])
    m = (P.group == "house_all") & (P.set == "ALL") & (P.flip == 0) & (P.run == "pooled")
    P["q_R_main"] = np.nan
    P.loc[m, "q_R_main"] = bh(P.loc[m, "p_R"].to_numpy())[1]
    P.to_csv(os.path.join(out, "exitlab_paired.csv"), index=False)
    # robustness table: house_all, ALL, flip 0
    M = P[(P.group == "house_all") & (P.set == "ALL") & (P.flip == 0)]
    piv = M.pivot_table(index=["tf", "variant"], columns="run", values=["diff_R", "lo_R", "hi_R", "p_R", "diff_pe_pct"])
    rob = pd.DataFrame({
        "dR_v3b": piv[("diff_R", "v3b")], "dR_v4": piv[("diff_R", "v4")], "dR_pooled": piv[("diff_R", "pooled")],
        "lo_pooled": piv[("lo_R", "pooled")], "hi_pooled": piv[("hi_R", "pooled")], "p_pooled": piv[("p_R", "pooled")],
        "dpe_v3b_pct": piv[("diff_pe_pct", "v3b")], "dpe_v4_pct": piv[("diff_pe_pct", "v4")],
        "dpe_pooled_pct": piv[("diff_pe_pct", "pooled")]}).reset_index()
    q = M[M.run == "pooled"].set_index(["tf", "variant"])["q_R_main"]
    rob = rob.join(q, on=["tf", "variant"])
    F = P[(P.group == "house_all") & (P.set == "ALL") & (P.flip == 1) & (P.run == "pooled")].set_index(["tf", "variant"])
    rob = rob.join(F[["diff_R", "lo_R", "hi_R"]].rename(columns={"diff_R": "dR_flip", "lo_R": "lo_flip", "hi_R": "hi_flip"}),
                   on=["tf", "variant"])
    Rs = P[(P.group == "house_all") & (P.set == "RES") & (P.flip == 0)].pivot_table(index=["tf", "variant"], columns="run",
                                                                                   values="diff_R")
    rob = rob.join(Rs.rename(columns={"v3b": "dR_res_v3b", "v4": "dR_res_v4", "pooled": "dR_res_pooled"}),
                   on=["tf", "variant"])
    rob["same_sign_runs"] = np.sign(rob.dR_v3b) == np.sign(rob.dR_v4)
    rob["same_sign_flip"] = np.sign(rob.dR_pooled) == np.sign(rob.dR_flip)
    rob.to_csv(os.path.join(out, "exitlab_robustness.csv"), index=False)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 400)
    print(rob.round(3).to_string())
    # base levels per run x tf
    B = X[(X.variant == "base") & (X.flip == 0)]
    lv = B.groupby(["grp", "runl", "timeframe"]).agg(n=("R", "size"), R=("R", "mean"), grossR=("grossR", "mean"),
                                                      costR=("costR", "mean"), open_end=("open_end", "sum"),
                                                      win=("R", lambda s: (s > 0).mean())).reset_index()
    lv.to_csv(os.path.join(out, "exitlab_base_levels.csv"), index=False)
    print(lv.round(3).to_string())


if __name__ == "__main__":
    main()
