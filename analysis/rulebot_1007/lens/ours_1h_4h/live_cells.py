"""Live evidence per strategy x timeframe for our 36 strategies (all four timeframes; the cards use 1h/4h and the
15m/30m columns for comparison).

    python3 -I live_cells.py <out_real_dir> <export_dir> <v3a_every_signal.csv> <out_dir>

Every-signal sample ("es"): v3a = entered trades (exact R) + nightly skipped shadows (R from ROE with the
reconstructed tier-walk leverage, v3a_every.py); v3b and v4 = every SUBMITTED signal replayed alone through the repo
engine on live_bars (rb_analyze replay_signals.csv, status TRADED). Unresolved signals (still open at the run end)
are left out and counted. Cluster = run x bar close floored to 4 hours (signals of one strategy on several coins in
the same 4 hours, and consecutive 1h bars, are not independent). 95% CI = cluster bootstrap (4,000 draws, ratio of
sums). Writes live_cells.csv, es_signals.csv (the pooled every-signal rows) and tf_summary_live.csv.
"""
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

O, E, V3A, OUTD = sys.argv[1:5]
RUNS = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
H4 = 4 * 3_600_000
RNG = np.random.default_rng(20261007)
B = 4000


def boot_ci(x, cl, B=B):
    x = np.asarray(x, float)
    if len(x) < 3:
        return np.nan, np.nan, len(set(cl))
    s = pd.DataFrame({"x": x, "c": cl}).groupby("c")["x"].agg(["sum", "size"])
    G = len(s)
    if G < 3:
        return np.nan, np.nan, G
    sums, ns = s["sum"].to_numpy(), s["size"].to_numpy()
    idx = RNG.integers(0, G, size=(B, G))
    m = sums[idx].sum(1) / ns[idx].sum(1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5)), G


def payoff(x):
    x = np.asarray(x, float)
    w, l_ = x[x > 0], x[x <= 0]
    return w.mean() / -l_.mean() if len(w) and len(l_) and l_.mean() < 0 else np.nan


def main():
    acc = pd.read_csv(f"{O}/account_stats.csv")
    acc = acc[acc["kind"] == "strategy"]
    ours = sorted(acc["strategy"].unique())
    pooled = pd.read_csv(f"{O}/strategy_tf_pooled.csv")
    pooled = pooled[pooled["kind"] == "strategy"]
    RP = pd.read_csv(f"{O}/replay_signals.csv", low_memory=False)
    RP = RP[RP["kind"] == "strategy"]
    sf = pd.read_csv(f"{O}/coinflip_sideflip.csv")
    sf = sf[(sf["level"] == "strategy_tf") & (sf["kind"] == "strategy")]
    vs5 = pd.read_csv(f"{O}/vs_fiveyear.csv")
    vs5 = vs5[vs5["kind"] == "strategy"]
    ref = pd.read_csv(f"{O}/fiveyear_ref.csv", low_memory=False)
    ref = ref[(ref["source"] == "profiles_binance") & (ref["variant"] == "every_signal")]
    sr = pd.read_csv(f"{O}/sizing_rejections.csv")
    sr["strategy"] = sr["account_id"].str.split("@").str[0]
    sr["tf"] = sr["account_id"].str.split("@").str[-1]
    sr = sr[sr["strategy"].isin(ours)]
    v3a = pd.read_csv(V3A)

    # ---------------- every-signal rows
    a = v3a[v3a["R"].notna()].copy()
    a = a.rename(columns={"tf": "timeframe"})
    a["status"] = "TRADED"
    a = a[["run", "strategy", "timeframe", "symbol", "bc", "side", "R", "src", "sig_id"]]
    r = RP[RP["status"] == "TRADED"][["run", "strategy", "timeframe", "symbol", "bar_close", "side", "R", "sig_id",
                                      "stop_frac", "roe", "exit_reason", "hold_min"]].rename(columns={"bar_close": "bc"})
    r["src"] = "replay"
    ES = pd.concat([a, r], ignore_index=True)
    ES["rk"] = ES["run"].map(RUNS)
    ES["cl"] = ES["run"] + "|" + (ES["bc"] // H4).astype(np.int64).astype(str)
    ES.to_csv(f"{OUTD}/es_signals.csv", index=False)

    # unresolved / rejected counts (replay) and v3a shadows without R
    v3a_nor = v3a[v3a["R"].isna()]
    rows = []
    for s in ours:
        for tf in ("15m", "30m", "1h", "4h"):
            d = {"strategy": s, "tf": tf}
            # accounts per run
            for run, rk in RUNS.items():
                g = acc[(acc["run"] == run) & (acc["strategy"] == s) & (acc["timeframe"] == tf)]
                if len(g):
                    g = g.iloc[0]
                    d[f"acct_{rk}_n"] = int(g["n"])
                    d[f"acct_{rk}_mean_R"] = g["mean_R"]
                    d[f"acct_{rk}_pnl"] = g["pnl_sum"]
                    d[f"acct_{rk}_win_pct"] = g["win_pct"]
                else:
                    d[f"acct_{rk}_n"] = 0
            p = pooled[(pooled["strategy"] == s) & (pooled["timeframe"] == tf)]
            if len(p):
                p = p.iloc[0]
                for k in ("n", "mean_R", "pnl_sum", "win_pct", "payoff", "profit_factor", "max_consec_losses",
                          "worst_realized_dd_any_run", "mean_hold_min"):
                    d[f"acct_all_{k}"] = p[k]
            else:
                d["acct_all_n"] = 0
            # every signal
            e = ES[(ES["strategy"] == s) & (ES["timeframe"] == tf)]
            for rk in ("v3a", "v3b", "v4"):
                ee = e[e["rk"] == rk]
                d[f"es_{rk}_n"] = len(ee)
                d[f"es_{rk}_mean_R"] = ee["R"].mean() if len(ee) else np.nan
            d["es_n"] = len(e)
            d["es_mean_R"] = e["R"].mean() if len(e) else np.nan
            d["es_median_R"] = e["R"].median() if len(e) else np.nan
            d["es_win_pct"] = 100 * (e["R"] > 0).mean() if len(e) else np.nan
            d["es_payoff"] = payoff(e["R"])
            lo, hi, G = boot_ci(e["R"].to_numpy(), e["cl"].to_numpy())
            d["es_ci95_lo"], d["es_ci95_hi"], d["es_clusters"] = lo, hi, G
            runs_ok = [d[f"es_{rk}_mean_R"] for rk in ("v3a", "v3b", "v4") if d[f"es_{rk}_n"] >= 3]
            d["es_runs_tested"] = len(runs_ok)
            d["es_runs_pos"] = int(sum(1 for v in runs_ok if v > 0))
            # replay detail (v3b + v4)
            rp = RP[(RP["strategy"] == s) & (RP["timeframe"] == tf)]
            d["rp_n_submitted"] = len(rp)
            d["rp_n_traded"] = int((rp["status"] == "TRADED").sum())
            d["rp_n_rej_sizing"] = int((rp["status"] == "REJECTED_SIZING").sum())
            d["rp_n_unresolved"] = int((rp["status"] == "UNRESOLVED").sum())
            d["rp_mean_mark_R_unres"] = rp.loc[rp["status"] == "UNRESOLVED", "mark_R"].mean()
            tr = rp[rp["status"] == "TRADED"]
            d["rp_lev_mix"] = " ".join(f"{int(k)}:{v}" for k, v in tr["leverage"].value_counts().items())
            d["rp_mean_hold_h"] = tr["hold_min"].mean() / 60 if len(tr) else np.nan
            d["rp_exit_mix"] = " ".join(f"{k}:{v}" for k, v in tr["exit_reason"].value_counts().items())
            d["live_cost_R_median"] = float(np.median(0.0014 / tr["stop_frac"])) if len(tr) else np.nan
            d["live_stop_pct_median"] = float(100 * np.median(tr["stop_frac"])) if len(tr) else np.nan
            rej = rp[rp["status"] == "REJECTED_SIZING"]["symbol"].value_counts()
            d["rp_rej_by_coin"] = " ".join(f"{k.replace('USDT', '')}:{v}" for k, v in rej.items())
            # coins that traded / rejected (v3b+v4 replay)
            d["rp_traded_coins"] = " ".join(f"{k.replace('USDT', '')}:{v}"
                                            for k, v in tr["symbol"].value_counts().items())
            # account-level sizing rejections, all runs
            q = sr[(sr["strategy"] == s) & (sr["tf"] == tf)]
            d["acct_rej_n"] = len(q)
            d["acct_rej_by_run_coin"] = " ".join(f"{RUNS[k[0]]}/{k[1].replace('USDT', '')}:{v}"
                                                 for k, v in q.groupby(["run", "symbol"]).size().items())
            nn = v3a_nor[(v3a_nor["strategy"] == s) & (v3a_nor["tf"] == tf)]
            d["v3a_shadow_noR"] = len(nn)
            # side flip
            f = sf[(sf["strategy"] == s) & (sf["timeframe"] == tf)]
            if len(f):
                f = f.iloc[0]
                for k in ("n_pairs", "excess_R", "p_better", "bh_q_better", "n_clusters"):
                    d[f"sideflip_{k}"] = f[k]
            # 5-year (profiles_binance, OLD tier walk leverage, ROE)
            rf = ref[(ref["strategy"] == s) & (ref["timeframe"] == tf)]
            if len(rf):
                rf = rf.iloc[0]
                for k, nk in (("n_signals", "ref5y_n"), ("per_day", "ref5y_per_day"), ("mean_roe", "ref5y_mean_roe"),
                              ("mean_roe_t", "ref5y_t"), ("mean_roe_is", "ref5y_is_roe"),
                              ("mean_roe_cf", "ref5y_cf_roe"), ("mean_ret_notional", "ref5y_ret_notional"),
                              ("win_rate", "ref5y_win"), ("sized_share", "ref5y_sized_share"),
                              ("median_hold_hours", "ref5y_median_hold_h"), ("trend_share", "ref5y_trend_share"),
                              ("style", "style"), ("acct_k2_is_final", "ref5y_acct_is_final"),
                              ("acct_k2_cf_final", "ref5y_acct_cf_final")):
                    d[nk] = rf[k]
            v = vs5[(vs5["strategy"] == s) & (vs5["timeframe"] == tf)]
            if len(v):
                d["live_signals_per_day"] = v.iloc[0]["live_signals_per_day"]
            rows.append(d)
    C = pd.DataFrame(rows)
    C.to_csv(f"{OUTD}/live_cells.csv", index=False)

    # ---------------- per tf summary (all 36 pooled) per run
    srows = []
    for tf in ("15m", "30m", "1h", "4h"):
        for rk in ("v3a", "v3b", "v4", "all"):
            e = ES[ES["timeframe"] == tf]
            if rk != "all":
                e = e[e["rk"] == rk]
            lo, hi, G = boot_ci(e["R"].to_numpy(), e["cl"].to_numpy())
            srows.append({"tf": tf, "run": rk, "n": len(e), "mean_R": e["R"].mean(), "ci95_lo": lo, "ci95_hi": hi,
                          "clusters": G, "win_pct": 100 * (e["R"] > 0).mean(), "payoff": payoff(e["R"]),
                          "strategies_with_signals": e["strategy"].nunique()})
    TS = pd.DataFrame(srows)
    TS.to_csv(f"{OUTD}/tf_summary_live.csv", index=False)
    print(TS.to_string())


if __name__ == "__main__":
    main()
