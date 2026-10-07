#!/usr/bin/env python3
"""DeepSeek-44 (ds200, paper v4) evidence cards.

    python3 -I cards.py <out_real_dir> <export_current_dir> <results_csv> <out_dir>

Reads only. Inputs: the validated pipeline's tables (out_real), the v4 export folder (accounts / signal_log / outcomes),
research/deepseek200/out/results.csv (5-year, PREREG exits). Writes into <out_dir>:
  cards_deepseek.csv     one row per definition x timeframe (171), every number of the card
  family_tf.csv          family x tf pooled over its definitions (identical signals counted once)
  dup_pairs_ds.csv       signal-level overlap of every pair of definitions at the same tf (+ cross-tf F15)
  halves.csv             replay mean R by run half (day-1 / day-2 split) per cell
  tf_summary_ds.csv      tf level: live, replay (cluster CI), 5-year
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
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
TFS = ["15m", "30m", "1h", "4h"]
B = 4000
RNG = np.random.default_rng(20261007)


def fam_of(s: str) -> str:
    return s.split("_")[0]


def bh(p: np.ndarray, q: float = 0.10):
    p = np.asarray(p, float)
    n = len(p)
    if n == 0:
        return np.zeros(0, bool), np.zeros(0)
    o = np.argsort(p)
    ranked = p[o] * n / (np.arange(n) + 1)
    qv = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[o] = np.minimum(qv, 1)
    return out <= q, out


def cluster_stats(x: np.ndarray, cl: np.ndarray) -> dict:
    """Mean with a cluster-robust SE (CR1), t-interval with G-1 df, one-sided p (mean > 0 / mean < 0),
    and a cluster bootstrap percentile CI."""
    n = len(x)
    out = {"n": n}
    if n == 0:
        return out
    m = float(np.mean(x))
    out["mean"] = m
    labs, inv = np.unique(cl, return_inverse=True)
    G = len(labs)
    out["G"] = G
    if n < 3 or G < 3:
        return out
    e = x - m
    s = np.bincount(inv, weights=e)
    var = (G / (G - 1)) * np.sum(s ** 2) / n ** 2
    se = math.sqrt(var) if var > 0 else np.nan
    out["se"] = se
    if se == se and se > 0:
        tq = stats.t.ppf(0.975, G - 1)
        out["lo"], out["hi"] = m - tq * se, m + tq * se
        tv = m / se
        out["t"] = tv
        out["p_gt0"] = float(stats.t.sf(tv, G - 1))
        out["p_lt0"] = float(stats.t.cdf(tv, G - 1))
    # cluster bootstrap (resample clusters, mean over all signals of the drawn clusters)
    sums = np.bincount(inv, weights=x)
    cnts = np.bincount(inv)
    idx = RNG.integers(0, G, size=(B, G))
    bm = sums[idx].sum(1) / cnts[idx].sum(1)
    out["boot_lo"], out["boot_hi"] = float(np.quantile(bm, 0.025)), float(np.quantile(bm, 0.975))
    out["boot_p_le0"] = float((np.sum(bm <= 0) + 1) / (B + 1))
    return out


def clusters(df: pd.DataFrame, mode: str) -> np.ndarray:
    if mode == "tf1h":
        blk = np.maximum(df["timeframe"].map(TF_MIN).to_numpy() * MIN, HOUR)
    else:  # 4h block
        blk = np.full(len(df), 4 * HOUR)
    return (df["bar_close"].to_numpy() // blk).astype(np.int64)


def main(argv):
    out_real, cur, res_csv, out = argv[1:5]
    os.makedirs(out, exist_ok=True)
    acc = pd.read_csv(os.path.join(cur, "accounts.csv"))
    acc = acc[acc["kind"] == "ds200"][["account_id", "strategy", "timeframe"]].copy()
    sig = pd.read_csv(os.path.join(cur, "signal_log.csv"))
    span_lo = int(pd.read_csv(os.path.join(cur, "runs.csv"))["started_ts"].min())
    bars_ts = pd.read_csv(os.path.join(cur, "live_bars.csv"), usecols=["ts"])["ts"]
    span_hi = int(bars_ts.max())
    days = (span_hi - span_lo) / 86_400_000
    mid = span_lo + (span_hi - span_lo) / 2

    R = pd.read_csv(os.path.join(out_real, "replay_signals.csv"))
    R = R[(R["kind"] == "ds200") & (R["run"] == "current")].copy()
    R["fam"] = R["strategy"].map(fam_of)
    R["cl"] = clusters(R, "tf1h")
    R["cl4"] = clusters(R, "4h")
    R["half"] = np.where(R["bar_close"] < mid, "H1", "H2")
    tr = R[R["status"] == "TRADED"].copy()
    dist = (tr["entry_price"] - tr["stop_initial"]).abs()
    tr["cost_R"] = (tr["fees"] + tr["funding"]) / (tr["qty"] * dist)
    # exit price is not in replay_signals: slippage cost ~ 2 x 0.0002 x entry / stop distance (entry ~ exit)
    tr["slip_R"] = 2 * 0.0002 * tr["entry_price"] / dist
    tr["gross_R"] = tr["R"] + tr["cost_R"] + tr["slip_R"]
    tr["ret_notional_pct"] = 100 * tr["roe_per_lev"]
    um = R[R["status"] == "UNRESOLVED"]
    # peers: every TRADED replay signal of the run (ds200 + core 36) with the same tf, same side, same 4h block,
    # other strategies only: R_vs_peers = R - mean(peer R) (what the definition added beyond the moment x side)
    RA = pd.read_csv(os.path.join(out_real, "replay_signals.csv"))
    RA = RA[(RA["run"] == "current") & RA["kind"].isin(["ds200", "strategy"]) & (RA["status"] == "TRADED")].copy()
    RA["cl4"] = clusters(RA, "4h")
    grp = RA.groupby(["timeframe", "side", "cl4"])
    RA["g_sum"], RA["g_n"] = grp["R"].transform("sum"), grp["R"].transform("size")
    RA["gs_sum"] = RA.groupby(["timeframe", "side", "cl4", "strategy"])["R"].transform("sum")
    RA["gs_n"] = RA.groupby(["timeframe", "side", "cl4", "strategy"])["R"].transform("size")
    RA["peer_n"] = RA["g_n"] - RA["gs_n"]
    RA["peer_mean"] = (RA["g_sum"] - RA["gs_sum"]) / RA["peer_n"].replace(0, np.nan)
    tr = tr.merge(RA[["sig_id", "peer_mean", "peer_n"]], on="sig_id", how="left")
    tr["R_vs_peers"] = tr["R"] - tr["peer_mean"]
    tr["day"] = pd.to_datetime(tr["bar_close"], unit="ms").dt.strftime("%Y-%m-%d")

    # ------------------------------------------------------------------ account (live) stats
    A = pd.read_csv(os.path.join(out_real, "account_stats.csv"))
    A = A[(A["run"] == "current") & (A["kind"] == "ds200")]
    L = pd.read_csv(os.path.join(out_real, "luck_concentration.csv"))
    L = L[(L["run"] == "current") & (L["kind"] == "ds200")][["account_id", "best_trade_share", "pnl_ex_best_trade", "lucky_flag"]]
    SF = pd.read_csv(os.path.join(out_real, "signal_flow.csv"))
    SF = SF[(SF["run"] == "current") & (SF["kind"] == "ds200")]
    SFL = pd.read_csv(os.path.join(out_real, "coinflip_sideflip.csv"))
    SFL = SFL[(SFL["kind"] == "ds200") & (SFL["level"] == "strategy_tf")]
    ES = pd.read_csv(os.path.join(out_real, "every_signal_shadow.csv"))
    ES = ES[(ES["kind"] == "ds200") & (ES["run"] == "ALL")]
    Y = pd.read_csv(res_csv)

    rows = []
    for a in acc.itertuples(index=False):
        s, tf, aid = a.strategy, a.timeframe, a.account_id
        d = {"family": fam_of(s), "definition": s, "timeframe": tf, "account_id": aid}
        # signals per day (live): every SUBMITTED signal of the account / run days
        g_sig = sig[(sig["strategy"] == s) & (sig["timeframe"] == tf)]
        d["live_signals"] = int((g_sig["status"] == "SUBMITTED").sum())
        d["live_signals_per_day"] = d["live_signals"] / days
        # ---- account trades
        ar = A[A["account_id"] == aid]
        if len(ar):
            r0 = ar.iloc[0]
            for k in ("n", "win_pct", "pnl_sum", "mean_R", "median_R", "payoff", "profit_factor", "max_consec_losses",
                      "realized_max_dd", "hourly_dd_max", "mean_cost_R", "mean_mfe_R", "long_n", "short_n", "mean_hold_min",
                      "lev_mix", "exit_mix"):
                d[f"acct_{k}"] = r0.get(k)
        lr = L[L["account_id"] == aid]
        if len(lr):
            d["acct_best_trade_share"] = lr.iloc[0]["best_trade_share"]
            d["acct_pnl_ex_best_trade"] = lr.iloc[0]["pnl_ex_best_trade"]
        sf = SF[SF["account_id"] == aid]
        if len(sf):
            d["acct_open_at_end"] = sf.iloc[0]["open_at_end"]
            d["zero_trade_cause"] = sf.iloc[0]["zero_trade_cause"]
        # ---- replay (every submitted signal alone)
        g = R[(R["strategy"] == s) & (R["timeframe"] == tf)]
        t = tr[(tr["strategy"] == s) & (tr["timeframe"] == tf)]
        u = um[(um["strategy"] == s) & (um["timeframe"] == tf)]
        d["rp_submitted"] = len(g)
        d["rp_traded"] = len(t)
        d["rp_unresolved"] = len(u)
        d["rp_rejected_sizing"] = int((g["status"] == "REJECTED_SIZING").sum())
        if len(t):
            Rv = t["R"].to_numpy(float)
            cs = cluster_stats(Rv, t["cl"].to_numpy())
            cs4 = cluster_stats(Rv, t["cl4"].to_numpy())
            d.update(rp_mean_R=cs.get("mean"), rp_median_R=float(np.median(Rv)), rp_win_pct=100 * float((Rv > 0).mean()),
                     rp_G=cs.get("G"), rp_se=cs.get("se"), rp_lo=cs.get("lo"), rp_hi=cs.get("hi"),
                     rp_p_gt0=cs.get("p_gt0"), rp_p_lt0=cs.get("p_lt0"),
                     rp_boot_lo=cs.get("boot_lo"), rp_boot_hi=cs.get("boot_hi"),
                     rp_G4=cs4.get("G"), rp_p_gt0_4h=cs4.get("p_gt0"), rp_lo_4h=cs4.get("lo"), rp_hi_4h=cs4.get("hi"))
            w, l_ = Rv[Rv > 0], Rv[Rv <= 0]
            d["rp_payoff"] = w.mean() / -l_.mean() if len(w) and len(l_) and l_.mean() < 0 else np.nan
            d["rp_pf"] = w.sum() / -l_.sum() if l_.sum() < 0 else np.nan
            d["rp_mean_roe"] = t["roe"].mean()
            d["rp_mean_ret_notional_pct"] = t["ret_notional_pct"].mean()
            d["rp_mean_cost_R"] = t["cost_R"].mean()
            d["rp_mean_slip_R"] = t["slip_R"].mean()
            d["rp_mean_gross_R"] = t["gross_R"].mean()
            d["rp_mean_mfe_R"] = t["mfe_R"].mean()
            d["rp_mean_mae_R"] = t["mae_R"].mean()
            d["rp_lock_share"] = float((t["exit_reason"] == "LOCK").mean())
            d["rp_long_share"] = float((t["side"] > 0).mean())
            d["rp_long_mean_R"] = t.loc[t["side"] > 0, "R"].mean()
            d["rp_short_mean_R"] = t.loc[t["side"] < 0, "R"].mean()
            d["rp_mean_hold_min"] = t["hold_min"].mean()
            nl, ns = int((t["side"] > 0).sum()), int((t["side"] < 0).sum())
            d["rp_n_long"], d["rp_n_short"] = nl, ns
            d["rp_side_balanced_R"] = 0.5 * (d["rp_long_mean_R"] + d["rp_short_mean_R"]) if nl >= 3 and ns >= 3 else np.nan
            pv = t["R_vs_peers"].dropna()
            d["rp_mean_R_vs_peers"] = pv.mean() if len(pv) else np.nan
            d["rp_peers_n_valued"] = len(pv)
            if len(pv) >= 3:
                cp = cluster_stats(pv.to_numpy(float), t.loc[pv.index, "cl"].to_numpy())
                d["rp_vs_peers_p_gt0"] = cp.get("p_gt0")
            d["rp_days_utc"] = t["day"].nunique()
            d["rp_blocks_4h"] = t["cl4"].nunique()
            d["rp_median_stop_pct"] = 100 * t["stop_frac"].median()
            d["rp_coins"] = t["symbol"].nunique()
            cm = t.groupby("symbol")["R"].mean()
            d["rp_coins_pos"] = int((cm > 0).sum())
            d["rp_best_coin_share_of_sum"] = (t.groupby("symbol")["R"].sum().max() / Rv.sum()) if Rv.sum() > 0 else np.nan
            # without the single best signal
            d["rp_mean_R_ex_best"] = (Rv.sum() - Rv.max()) / (len(Rv) - 1) if len(Rv) > 1 else np.nan
            # halves
            for h in ("H1", "H2"):
                th = t[t["half"] == h]
                d[f"rp_{h}_n"] = len(th)
                d[f"rp_{h}_mean_R"] = th["R"].mean() if len(th) else np.nan
            # including unresolved marked to the last close
            allv = np.concatenate([Rv, u["mark_R"].dropna().to_numpy(float)])
            d["rp_mean_R_incl_marked"] = allv.mean()
            # entered vs skipped by the one-position account
            d["rp_mean_R_entered"] = t.loc[t["acct_status"] == "ENTERED", "R"].mean()
            d["rp_mean_R_skipped"] = t.loc[t["acct_status"] == "SKIPPED", "R"].mean()
        # ---- side flip
        f = SFL[(SFL["strategy"] == s) & (SFL["timeframe"] == tf)]
        if len(f):
            f0 = f.iloc[0]
            for k in ("n_pairs", "n_clusters", "mean_R_other_side", "excess_R", "p_better", "p_worse", "bh_q_better",
                      "mde_excess_R_80pct"):
                d[f"sf_{k}"] = f0.get(k)
        # ---- daily3 skipped shadows + entered (ROE only, nights covered)
        e = ES[(ES["strategy"] == s) & (ES["timeframe"] == tf)]
        if len(e):
            d["shadow_n_all"] = e.iloc[0]["n_all"]
            d["shadow_mean_roe_all"] = e.iloc[0]["mean_roe_all"]
        # ---- 5-year (PREREG exits, unlevered net % per trade)
        for ex, tag in (("X5_TRAIL2", "x5"), ("X2_SL15_TP3", "x2")):
            y = Y[(Y["entry"] == s) & (Y["tf"] == tf) & (Y["exit"] == ex)]
            if not len(y):
                continue
            y0 = y.iloc[0]
            for k in ("is_n", "is_mean_pct", "cf_n", "cf_mean_pct", "pre_n", "pre_mean_pct", "is_gross_mean_pct",
                      "cf_gross_mean_pct", "pre_gross_mean_pct", "is_win_pct", "is_pf", "cf_pf", "mean12_pct", "p12",
                      "boot_p12", "is_coins_pos", "cf_coins_pos", "is_long_mean_pct", "is_short_mean_pct",
                      "is_hold_mean", "max_lev"):
                d[f"y{tag}_{k}"] = y0.get(k)
            for k in ("stage1", "stage1_top", "stage2", "stage3", "bh12", "candidate", "weak_candidate", "all3_positive"):
                d[f"y{tag}_{k}"] = bool(y0.get(k))
            d[f"y{tag}_per_day"] = (y0["is_n"] + y0["cf_n"]) / ((pd.Timestamp("2026-09-30") - pd.Timestamp("2021-08-01")).days)
            d[f"y{tag}_n_periods_pos"] = int(sum(y0[c] > 0 for c in ("is_mean_pct", "cf_mean_pct", "pre_mean_pct")))
        rows.append(d)
    C = pd.DataFrame(rows)

    # BH over the replay cells (one-sided mean R > 0 and < 0), cells with >= 5 traded and >= 5 clusters
    m = C["rp_p_gt0"].notna()
    for col, qc in (("rp_p_gt0", "rp_bh_q_gt0"), ("rp_p_lt0", "rp_bh_q_lt0")):
        _, q = bh(C.loc[m, col].to_numpy(), 0.10)
        C.loc[m, qc] = q
    C["rp_cells_tested"] = int(m.sum())
    # 5-year: best exit by mean12, rank within tf (1 = least negative)
    C["y_best_mean12_pct"] = C[["yx5_mean12_pct", "yx2_mean12_pct"]].max(axis=1)
    C["y_best_exit"] = np.where(C["yx5_mean12_pct"] >= C["yx2_mean12_pct"], "X5_TRAIL2", "X2_SL15_TP3")
    C["y_rank_in_tf"] = C.groupby("timeframe")["y_best_mean12_pct"].rank(ascending=False)
    C["y_defs_in_tf"] = C.groupby("timeframe")["definition"].transform("count")
    C["y_any_stage1"] = C["yx5_stage1"].fillna(False) | C["yx2_stage1"].fillna(False)
    C["y_any_all3_positive"] = C["yx5_all3_positive"].fillna(False) | C["yx2_all3_positive"].fillna(False)
    C["y_max_gross_is_cf"] = C[["yx5_is_gross_mean_pct", "yx5_cf_gross_mean_pct", "yx2_is_gross_mean_pct",
                                "yx2_cf_gross_mean_pct"]].max(axis=1)

    # ------------------------------------------------------------------ duplicates (signal level)
    keyset = {}
    for (s, tf), g in R.groupby(["strategy", "timeframe"]):
        keyset[(s, tf)] = set(zip(g["bar_close"], g["symbol"], g["side"]))
    dp = []
    for tf in TFS:
        ks = sorted(k for k in keyset if k[1] == tf)
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                a_, b_ = keyset[ks[i]], keyset[ks[j]]
                com = len(a_ & b_)
                if com == 0:
                    continue
                dp.append({"timeframe": tf, "a": ks[i][0], "b": ks[j][0], "n_a": len(a_), "n_b": len(b_), "common": com,
                           "overlap_min": com / min(len(a_), len(b_)), "jaccard": com / len(a_ | b_),
                           "identical": a_ == b_, "a_in_b": a_ <= b_, "b_in_a": b_ <= a_})
    # cross-tf (same definition): identical streams across timeframes (key without the tf)
    for s in sorted({k[0] for k in keyset}):
        tfs = [tf for tf in TFS if (s, tf) in keyset]
        for i in range(len(tfs)):
            for j in range(i + 1, len(tfs)):
                a_, b_ = keyset[(s, tfs[i])], keyset[(s, tfs[j])]
                com = len(a_ & b_)
                if com:
                    dp.append({"timeframe": f"{tfs[i]}|{tfs[j]}", "a": s, "b": s, "n_a": len(a_), "n_b": len(b_),
                               "common": com, "overlap_min": com / min(len(a_), len(b_)),
                               "jaccard": com / len(a_ | b_), "identical": a_ == b_, "a_in_b": a_ <= b_, "b_in_a": b_ <= a_})
    DP = pd.DataFrame(dp).sort_values(["overlap_min", "common"], ascending=False)
    DP.to_csv(os.path.join(out, "dup_pairs_ds.csv"), index=False)
    # per card: strongest overlapping partner at the same tf
    for i, r in C.iterrows():
        x = DP[(DP["timeframe"] == r["timeframe"]) & ((DP["a"] == r["definition"]) | (DP["b"] == r["definition"]))]
        x = x[x["common"] >= 3]
        if len(x):
            x0 = x.iloc[0]
            other = x0["b"] if x0["a"] == r["definition"] else x0["a"]
            C.loc[i, "dup_partner"] = other
            C.loc[i, "dup_overlap_min"] = x0["overlap_min"]
            C.loc[i, "dup_jaccard"] = x0["jaccard"]
            C.loc[i, "dup_identical"] = bool(x0["identical"])
            C.loc[i, "dup_partners_ge90"] = " ".join(
                sorted((x["b"].where(x["a"] == r["definition"], x["a"]))[x["overlap_min"] >= 0.9].tolist()))

    # ------------------------------------------------------------------ halves table
    H = (tr.groupby(["strategy", "timeframe", "half"])["R"].agg(["size", "mean"]).unstack("half"))
    H.columns = [f"{a}_{b}" for a, b in H.columns]
    H = H.reset_index()
    H.to_csv(os.path.join(out, "halves.csv"), index=False)

    # ------------------------------------------------------------------ family x tf (dedup identical signals)
    fr = []
    for (fam, tf), g in tr.groupby(["fam", "timeframe"]):
        gd = g.drop_duplicates(["bar_close", "symbol", "side"])
        for lab, gg in (("all_signals", g), ("unique_signals", gd)):
            cs = cluster_stats(gg["R"].to_numpy(float), gg["cl"].to_numpy())
            cs4 = cluster_stats(gg["R"].to_numpy(float), gg["cl4"].to_numpy())
            fr.append({"family": fam, "timeframe": tf, "basis": lab, "definitions": g["strategy"].nunique(), "n": cs["n"],
                       "mean_R": cs.get("mean"), "G": cs.get("G"), "lo": cs.get("lo"), "hi": cs.get("hi"),
                       "p_gt0": cs.get("p_gt0"), "p_lt0": cs.get("p_lt0"), "p_gt0_4h": cs4.get("p_gt0"),
                       "lo_4h": cs4.get("lo"), "hi_4h": cs4.get("hi"),
                       "win_pct": 100 * (gg["R"] > 0).mean(), "mean_gross_R": gg["gross_R"].mean(),
                       "mean_cost_R": gg["cost_R"].mean() + gg["slip_R"].mean(),
                       "mean_ret_notional_pct": gg["ret_notional_pct"].mean(),
                       "H1_mean_R": gg.loc[gg["half"] == "H1", "R"].mean(), "H2_mean_R": gg.loc[gg["half"] == "H2", "R"].mean(),
                       "H1_n": int((gg["half"] == "H1").sum()), "H2_n": int((gg["half"] == "H2").sum()),
                       "signals_per_day": len(gd) / days})
    # side flip at family x tf from the replay (cluster sign-flip, unique signals)
    FR = pd.DataFrame(fr)
    sfr = []
    xx = R[(R["status"] == "TRADED") & (R["flip_status"] == "TRADED")].copy()
    xx = xx[np.isfinite(xx["R"]) & np.isfinite(xx["flip_R"])].drop_duplicates(["fam", "timeframe", "bar_close", "symbol", "side"])
    for (fam, tf), g in xx.groupby(["fam", "timeframe"]):
        h = 0.5 * (g["R"].to_numpy() - g["flip_R"].to_numpy())
        cl = pd.Series(h).groupby(g["cl"].to_numpy()).sum().to_numpy()
        obs = h.mean()
        if len(cl) >= 5:
            sims = (cl[None, :] * RNG.choice((-1.0, 1.0), size=(B, len(cl)))).sum(1) / len(h)
            p = (1 + np.sum(sims >= obs - 1e-12)) / (B + 1)
        else:
            p = np.nan
        sfr.append({"family": fam, "timeframe": tf, "sf_n": len(h), "sf_excess_R": obs, "sf_p_better": p,
                    "sf_mean_R_other_side": g["flip_R"].mean()})
    FR = FR.merge(pd.DataFrame(sfr), on=["family", "timeframe"], how="left")
    # 5-year family x tf (mean over the family's configs, both exits) from results.csv
    Y["family"] = Y["entry"].map(fam_of)
    yf = Y.groupby(["family", "tf"]).apply(lambda g: pd.Series({
        "y_configs": len(g),
        "y_is_mean_pct_w": np.average(g["is_mean_pct"].fillna(0), weights=g["is_n"].fillna(0)) if g["is_n"].sum() else np.nan,
        "y_cf_mean_pct_w": np.average(g["cf_mean_pct"].fillna(0), weights=g["cf_n"].fillna(0)) if g["cf_n"].sum() else np.nan,
        "y_pre_mean_pct_w": np.average(g["pre_mean_pct"].fillna(0), weights=g["pre_n"].fillna(0)) if g["pre_n"].sum() else np.nan,
        "y_is_gross_pct_w": np.average(g["is_gross_mean_pct"].fillna(0), weights=g["is_n"].fillna(0)) if g["is_n"].sum() else np.nan,
        "y_best_config_mean12": g["mean12_pct"].max(),
        "y_stage1": int(g["stage1"].sum()), "y_all3_positive": int(g["all3_positive"].sum())}),
        include_groups=False).reset_index().rename(columns={"tf": "timeframe"})
    FR = FR.merge(yf, on=["family", "timeframe"], how="left")
    m = (FR["basis"] == "unique_signals") & FR["p_gt0"].notna()
    _, q = bh(FR.loc[m, "p_gt0"].to_numpy(), 0.10)
    FR.loc[m, "bh_q_gt0"] = q
    FR.to_csv(os.path.join(out, "family_tf.csv"), index=False)

    # ------------------------------------------------------------------ tf summary
    ts = []
    for tf, g in tr.groupby("timeframe"):
        gd = g.drop_duplicates(["bar_close", "symbol", "side"])
        for lab, gg in (("all_signals", g), ("unique_signals", gd)):
            cs = cluster_stats(gg["R"].to_numpy(float), gg["cl"].to_numpy())
            cs4 = cluster_stats(gg["R"].to_numpy(float), gg["cl4"].to_numpy())
            yy = Y[Y["tf"] == tf]
            ts.append({"timeframe": tf, "basis": lab, "n": cs["n"], "mean_R": cs["mean"], "G": cs.get("G"),
                       "lo": cs.get("lo"), "hi": cs.get("hi"), "p_lt0": cs.get("p_lt0"), "lo_4h": cs4.get("lo"),
                       "hi_4h": cs4.get("hi"), "win_pct": 100 * (gg["R"] > 0).mean(), "mean_gross_R": gg["gross_R"].mean(),
                       "mean_cost_R": gg["cost_R"].mean(), "mean_slip_R": gg["slip_R"].mean(),
                       "mean_ret_notional_pct": gg["ret_notional_pct"].mean(), "mean_roe": gg["roe"].mean(),
                       "median_stop_pct": 100 * gg["stop_frac"].median(),
                       "y_is_mean_pct": np.average(yy["is_mean_pct"].fillna(0), weights=yy["is_n"].fillna(0)),
                       "y_cf_mean_pct": np.average(yy["cf_mean_pct"].fillna(0), weights=yy["cf_n"].fillna(0)),
                       "y_is_gross_pct": np.average(yy["is_gross_mean_pct"].fillna(0), weights=yy["is_n"].fillna(0))})
    pd.DataFrame(ts).to_csv(os.path.join(out, "tf_summary_ds.csv"), index=False)

    C.to_csv(os.path.join(out, "cards_deepseek_raw.csv"), index=False)
    print("days", round(days, 3), "mid", mid, "cards", len(C), "cells tested", int(m.sum()))


if __name__ == "__main__":
    main(sys.argv)
