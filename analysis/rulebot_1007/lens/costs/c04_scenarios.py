#!/usr/bin/env python3
"""Summaries of the execution-scenario replay (c02_replay_rows.csv).

    python3 -I c04_scenarios.py <c02_replay_rows.csv> <rb replay_signals.csv> <out_dir>

Rb = pnl / notional / stop_frac_base: every scenario's result in units of the BASE trade's 2 ATR stop (the same
yardstick for all scenarios; for the base scenario Rb = R). A limit order that never filled counts 0.
Uncertainty: cluster bootstrap (clusters = run x signal bar close floored to max(tf, 1h), as the pipeline's
side-flip test), 4,000 draws, percentile 95% CI; p = share of draws <= 0 (one-sided) for differences.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MIN = 60_000
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
KMAP = {"strategy": "core36", "ds200": "ds200", "random": "coinflip"}
B = 4000


def cluster_boot(vals, clus, rng, B=B):
    vals = np.asarray(vals, float)
    clus = np.asarray(clus)
    ok = np.isfinite(vals)
    vals, clus = vals[ok], clus[ok]
    if len(vals) < 3:
        return (np.nan, np.nan, np.nan, len(vals), 0)
    u, inv = np.unique(clus, return_inverse=True)
    s = np.bincount(inv, weights=vals)
    c = np.bincount(inv)
    k = len(u)
    draws = rng.integers(0, k, size=(B, k))
    ms = s[draws].sum(1) / c[draws].sum(1)
    return (float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5)), float((ms <= 0).mean()), len(vals), k)


def main():
    src, rb_rep, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(20261007)
    R = pd.read_csv(src)
    R["grp"] = R["kind"].map(KMAP)
    R = R[R["grp"].notna()].copy()
    R["notional"] = R["qty"] * R["entry_price"]
    R["stop_frac_own"] = (R["entry_price"] - R["stop_initial"]).abs() / R["entry_price"]
    R["R_own"] = R["pnl"] / (R["qty"] * (R["entry_price"] - R["stop_initial"]).abs())
    R["ret_notional"] = R["pnl"] / R["notional"]
    base = R[(R["scenario"] == "base") & (R["status"] == "TRADED")].set_index(["run", "sig_id"])
    key = list(zip(R["run"], R["sig_id"]))
    R["stop_frac_base"] = base["stop_frac_own"].reindex(key).to_numpy()
    R["R_base"] = base["R_own"].reindex(key).to_numpy()
    R["lev_base"] = base["leverage"].reindex(key).to_numpy()
    R["marked_base"] = base["marked"].reindex(key).to_numpy()
    R["Rb"] = R["ret_notional"] / R["stop_frac_base"]
    R.loc[R["status"] == "UNFILLED", "Rb"] = 0.0
    R = R[np.isfinite(R["stop_frac_base"])].copy()   # signals the base traded (sized)
    fl = (R["bar_close"] // MIN).astype(np.int64)
    m = R["timeframe"].map(TFM).clip(lower=60).astype(np.int64)
    R["cluster"] = R["run"] + "|" + (fl // m * m).astype(str)
    R.to_csv(os.path.join(out, "c04_replay_rows_rb.csv"), index=False)

    # ---- parity with the pipeline's replay
    P = pd.read_csv(rb_rep, usecols=["run", "sig_id", "status", "R", "mark_R"])
    bb = R[R["scenario"] == "base"].merge(P, on=["run", "sig_id"], how="left", suffixes=("", "_rb"))
    tr = bb[bb["marked"] == 0]
    par = {"base_traded": len(bb), "resolved": len(tr),
           "resolved_match_1e-9": int((tr["R_own"] - tr["R"]).abs().lt(1e-9).sum()),
           "resolved_max_abs_diff": float((tr["R_own"] - tr["R"]).abs().max()),
           "marked_match_1e-9": int((bb.loc[bb["marked"] == 1, "R_own"] - bb.loc[bb["marked"] == 1, "mark_R"]).abs()
                                     .lt(1e-9).sum()),
           "marked": int((bb["marked"] == 1).sum())}
    pin = R[R["scenario"] == "pin"].set_index(["run", "sig_id"])
    bse = R[R["scenario"] == "base"].set_index(["run", "sig_id"])
    j = bse.join(pin[["pnl", "status"]], rsuffix="_pin", how="inner")
    par["pin_equal_1e-6"] = int((j["pnl"] - j["pnl_pin"]).abs().lt(1e-6).sum())
    par["pin_pairs"] = len(j)
    print("parity", par)
    pd.DataFrame([par]).to_csv(os.path.join(out, "c04_parity.csv"), index=False)

    # ---- scenario table per grp x tf (and pooled 15m+30m), resolved-in-base subset and all
    W = R.pivot_table(index=["run", "sig_id"], columns="scenario", values="Rb", aggfunc="first")
    meta = R[R["scenario"] == "base"].set_index(["run", "sig_id"])[["grp", "timeframe", "strategy", "symbol",
                                                                       "cluster", "marked", "stop_frac_own",
                                                                       "leverage"]]
    W = W.join(meta)
    st = R.pivot_table(index=["run", "sig_id"], columns="scenario", values="status", aggfunc="first")
    W = W.join(st.add_prefix("st_"))
    W.to_csv(os.path.join(out, "c04_wide.csv"))
    scen = ["base", "zero", "fee", "real", "real_bnb", "mk_fee_only", "zero_lad", "fee_lad", "real_lad", "mk_touch",
            "mk10", "mk25", "mk25_shift", "w25", "w30"]
    RO = R.pivot_table(index=["run", "sig_id"], columns="scenario", values="R_own", aggfunc="first")
    W = W.join(RO.add_prefix("ro_"))
    rows = []

    def summarize(g, label_grp, label_tf, label_run):
        out = []
        for s in scen:
            x = g[s]
            lo, hi, p0, n, k = cluster_boot(x, g["cluster"], rng)
            d = g[s] - g["base"]
            dlo, dhi, dp, _, _ = cluster_boot(d, g["cluster"], rng) if s != "base" else (np.nan,) * 5
            filled = (g[f"st_{s}"] == "TRADED").mean() if f"st_{s}" in g else np.nan
            unf = g[g[f"st_{s}"] == "UNFILLED"] if f"st_{s}" in g else g.iloc[:0]
            fil = g[g[f"st_{s}"] == "TRADED"] if f"st_{s}" in g else g
            out.append({"run": label_run, "grp": label_grp, "tf": label_tf, "scenario": s, "n": n, "clusters": k,
                        "mean_Rb": float(np.nanmean(x)), "ci_lo": lo, "ci_hi": hi, "p_le0": p0,
                        "diff_vs_base": float(np.nanmean(d)), "diff_ci_lo": dlo, "diff_ci_hi": dhi,
                        "p_diff_le0": dp, "fill_or_trade_rate": filled,
                        "base_Rb_of_unfilled": float(unf["base"].mean()) if len(unf) else np.nan,
                        "n_unfilled": len(unf),
                        "base_Rb_of_filled": float(fil["base"].mean()) if len(fil) else np.nan,
                        "scen_Rb_of_filled": float(fil[s].mean()) if len(fil) else np.nan,
                        "mean_R_own": float(g[f"ro_{s}"].mean()) if f"ro_{s}" in g else np.nan,
                        "median_stop_pct": float(g["stop_frac_own"].median() * 100)})
        return out

    for (gname, tf), g in W.groupby(["grp", "timeframe"]):
        rows += summarize(g, gname, tf, "ALL")
        for run, g2 in g.groupby(level=0):
            rows += summarize(g2, gname, tf, run)
    for gname, g in W[W["timeframe"].isin(["15m", "30m"])].groupby("grp"):
        rows += summarize(g, gname, "15m+30m", "ALL")
    g = W[W["grp"].isin(["core36", "ds200"]) & W["timeframe"].isin(["15m", "30m"])]
    rows += summarize(g, "core36+ds200", "15m+30m", "ALL")
    for tf, g in W[W["grp"].isin(["core36", "ds200"])].groupby("timeframe"):
        rows += summarize(g, "core36+ds200", tf, "ALL")
    S = pd.DataFrame(rows)
    S.to_csv(os.path.join(out, "c04_scenarios.csv"), index=False)
    pd.set_option("display.width", 250)
    cols = ["run", "grp", "tf", "scenario", "n", "clusters", "mean_Rb", "ci_lo", "ci_hi", "diff_vs_base",
            "diff_ci_lo", "diff_ci_hi", "p_diff_le0", "fill_or_trade_rate", "base_Rb_of_unfilled",
            "base_Rb_of_filled", "scen_Rb_of_filled", "mean_R_own", "median_stop_pct"]
    print(S[S["run"] == "ALL"][cols].round(3).to_string(index=False))
    print(S[(S["run"] != "ALL") & S["scenario"].isin(["base", "zero", "real", "mk_touch", "mk25", "w30"]) & S["grp"].isin(["core36", "ds200"])][cols]
          .round(3).to_string(index=False))

    # ---- resolved-only sensitivity (base not marked and the scenario not marked)
    mk = R.pivot_table(index=["run", "sig_id"], columns="scenario", values="marked", aggfunc="first")
    rows = []
    for s in scen:
        ok = (W["marked"] == 0) & (mk[s].fillna(0).reindex(W.index) == 0)
        for (gname, tf), g in W[ok].groupby(["grp", "timeframe"]):
            rows.append({"grp": gname, "tf": tf, "scenario": s, "n": int(g[s].notna().sum()),
                         "mean_Rb": float(g[s].mean()), "diff_vs_base": float((g[s] - g["base"]).mean())})
    RS = pd.DataFrame(rows)
    RS.to_csv(os.path.join(out, "c04_scenarios_resolved_only.csv"), index=False)
    print(RS.pivot_table(index=["grp", "tf"], columns="scenario", values="diff_vs_base").round(3).to_string())

    # ---- per coin x tf (core36 + ds200)
    rows = []
    X = W[W["grp"].isin(["core36", "ds200"])]
    for (sym, tf), g in X.groupby(["symbol", "timeframe"]):
        r = {"symbol": sym, "tf": tf, "n": len(g), "median_stop_pct": g["stop_frac_own"].median() * 100}
        for s in scen:
            r[s] = g[s].mean()
        r["cost_paper"] = r["zero"] - r["base"]
        r["cost_real"] = r["zero"] - r["real"]
        r["cost_real_bnb"] = r["zero"] - r["real_bnb"]
        rows.append(r)
    CC = pd.DataFrame(rows)
    CC.to_csv(os.path.join(out, "c04_by_coin_tf.csv"), index=False)
    print(CC.round(3).to_string(index=False))

    # ---- per strategy x tf
    rows = []
    for (gname, strat, tf), g in W.groupby(["grp", "strategy", "timeframe"]):
        lo, hi, p0, n, k = cluster_boot(g["zero"], g["cluster"], rng, B=2000)
        rows.append({"grp": gname, "strategy": strat, "tf": tf, "n": len(g), "clusters": k,
                     "base_R": g["base"].mean(), "zero_R": g["zero"].mean(), "zero_ci_lo": lo, "zero_ci_hi": hi,
                     "p_zero_le0": p0, "real_R": g["real"].mean(), "zero_lad_R": g["zero_lad"].mean(), "mk_touch_R": g["mk_touch"].mean(),
                     "mk25_R": g["mk25"].mean(), "w30_R": g["w30"].mean(),
                     "cost_paper_R": (g["zero"] - g["base"]).mean(), "median_stop_pct": g["stop_frac_own"].median() * 100,
                     "runs": "+".join(sorted(set(g.index.get_level_values(0).str.replace("run-20261005T183457Z", "v3b")
                                                 .str.replace("current", "v4"))))})
    ST = pd.DataFrame(rows)
    ST.to_csv(os.path.join(out, "c04_by_strategy_tf.csv"), index=False)


if __name__ == "__main__":
    main()
