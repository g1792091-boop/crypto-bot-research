#!/usr/bin/env python3
"""Evidence cards for our 36 strategies at 15m and 30m (72 cells).

usage: python3 -I -B cards.py <export_dir> <out_real_dir> <repo> <out_dir>
needs <out_dir>/v3a_every_signal.csv (v3a_every_signal.py).

Every-signal sample per cell:
  v3a  = entered trades (real R) + nightly skipped shadows (ROE -> R with the engine's own fresh-account leverage,
         validated exact on 1,339 base rows), inside the shadow window 10/02 20:10 - 10/05 08:55 KST
  v3b, v4 = replay of every SUBMITTED signal alone (out_real/replay_signals.csv, status TRADED; UNRESOLVED marked to
         the last close only as a sensitivity)
Uncertainty: bootstrap over time clusters (run x 4h block of the signal bar close; also 1h for reference),
clusters resampled within each run, B = 10,000. BH over the cells tested (n >= 10 and >= 5 clusters).
"""
import json
import math
import zlib
import os
import site
import sys

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

EXP, OR, REPO, OUT = sys.argv[1:5]
B = 10_000
H = 3_600_000
RUNS = ["run-20261005T014624Z", "run-20261005T183457Z", "current"]
RN = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
TFS = ["15m", "30m"]
RT_COST = 2 * (0.0005 + 0.0002)        # house round trip (taker + slippage, both sides) as a fraction of notional
rng = np.random.default_rng(20261007)


def rd(name):
    return pd.read_csv(os.path.join(OR, name))


def bh(p):
    p = np.asarray(p, float)
    n = len(p)
    o = np.argsort(p)
    q = np.empty(n)
    q[o] = np.minimum.accumulate((p[o] * n / np.arange(1, n + 1))[::-1])[::-1]
    return np.minimum(q, 1.0)


def max_consec_losses(x):
    m = c = 0
    for v in x:
        c = c + 1 if v <= 0 else 0
        m = max(m, c)
    return m


# ------------------------------------------------------------------ every-signal rows
v3a = pd.read_csv(os.path.join(OUT, "v3a_every_signal.csv"))
v3a = v3a[v3a["timeframe"].isin(TFS) & v3a["in_shadow_window"]].copy()
v3a_unres = v3a[(v3a["source"] == "skipped_shadow") & (v3a["resolved"] == 0)].groupby(
    ["strategy", "timeframe"]).size()
v3a = v3a[v3a["R"].notna()]
v3a["status"] = "TRADED"
v3a["kind"] = "strategy"
v3a = v3a[~v3a["account_id"].str.startswith("RANDOM_")]

RP = rd("replay_signals.csv")
RP = RP[(RP["kind"] == "strategy") & RP["timeframe"].isin(TFS)].copy()
RP["source"] = np.where(RP["acct_status"] == "ENTERED", "replay_entered", "replay_skipped")
RP["cost_R"] = (RP["fees"] + RP["funding"]) / (RP["qty"] * RP["stop_frac"] * RP["entry_price"])
keep = ["run", "strategy", "timeframe", "symbol", "bar_close", "side", "status", "source", "R", "roe_per_lev",
        "leverage", "stop_frac", "mfe_R", "mae_R", "cost_R", "exit_reason"]
ES_all = pd.concat([v3a.reindex(columns=keep), RP.reindex(columns=keep + ["mark_R", "flip_R", "flip_status"])],
                   ignore_index=True)
ES_all["rn"] = ES_all["run"].map(RN)
ES_all["blk4"] = ES_all["run"] + "|" + (ES_all["bar_close"] // (4 * H)).astype("int64").astype(str)
ES_all["blk1"] = ES_all["run"] + "|" + (ES_all["bar_close"] // H).astype("int64").astype(str)
ES_all["kst_day"] = pd.to_datetime(ES_all["bar_close"] + 9 * H, unit="ms").dt.strftime("%m-%d")
ES = ES_all[ES_all["status"] == "TRADED"].copy()
ES["win"] = ES["R"] > 0
ES.to_csv(os.path.join(OUT, "every_signal_rows_15_30.csv"), index=False)

# same-side benchmark: other strategies' signals of the same run, tf and side (run-level drift). The KST-day version
# (USE_DAY_BENCH = True) was tried first and rejected: inside one day the market's direction flips (10/07 crash), so a
# day-level benchmark mostly measures intraday timing differences between strategies and gave absurd adjustments
# (N17_KC_RSI@15m +0.88R).
USE_DAY_BENCH = False
grp_day = ES.groupby(["run", "timeframe", "side", "kst_day"])["R"].agg(["sum", "count"])
grp_run = ES.groupby(["run", "timeframe", "side"])["R"].agg(["sum", "count"])
own_day = ES.groupby(["strategy", "run", "timeframe", "side", "kst_day"])["R"].agg(["sum", "count"])
own_run = ES.groupby(["strategy", "run", "timeframe", "side"])["R"].agg(["sum", "count"])
bench = []
for r in ES.itertuples():
    gd, od = grp_day.loc[(r.run, r.timeframe, r.side, r.kst_day)], own_day.loc[(r.strategy, r.run, r.timeframe, r.side, r.kst_day)]
    n_o = gd["count"] - od["count"]
    if USE_DAY_BENCH and n_o >= 10:
        bench.append((gd["sum"] - od["sum"]) / n_o)
    else:
        gr, orr = grp_run.loc[(r.run, r.timeframe, r.side)], own_run.loc[(r.strategy, r.run, r.timeframe, r.side)]
        n_o = gr["count"] - orr["count"]
        bench.append((gr["sum"] - orr["sum"]) / n_o if n_o > 0 else np.nan)
ES["bench_sameside"] = bench
ES["ex_sameside"] = ES["R"] - ES["bench_sameside"]

# drift-adjusted side flip: h = (R - R_other_side) / 2 minus the mean h of the OTHER strategies' signals with the same
# side, run, tf and KST day (fallback run x tf x side). A short-only strategy in a falling market gets a positive h
# without any skill; this removes the part every same-side signal of that day got.
PR = ES[(ES["flip_status"] == "TRADED") & ES["flip_R"].notna()].copy()
PR["h"] = 0.5 * (PR["R"] - PR["flip_R"])
hd = PR.groupby(["run", "timeframe", "side", "kst_day"])["h"].agg(["sum", "count"])
hr = PR.groupby(["run", "timeframe", "side"])["h"].agg(["sum", "count"])
ohd = PR.groupby(["strategy", "run", "timeframe", "side", "kst_day"])["h"].agg(["sum", "count"])
ohr = PR.groupby(["strategy", "run", "timeframe", "side"])["h"].agg(["sum", "count"])
hb = []
for r in PR.itertuples():
    a_, o_ = hd.loc[(r.run, r.timeframe, r.side, r.kst_day)], ohd.loc[(r.strategy, r.run, r.timeframe, r.side, r.kst_day)]
    n_o = a_["count"] - o_["count"]
    if USE_DAY_BENCH and n_o >= 10:
        hb.append((a_["sum"] - o_["sum"]) / n_o)
    else:
        a2, o2 = hr.loc[(r.run, r.timeframe, r.side)], ohr.loc[(r.strategy, r.run, r.timeframe, r.side)]
        n2 = a2["count"] - o2["count"]
        hb.append((a2["sum"] - o2["sum"]) / n2 if n2 > 0 else np.nan)
PR["h_adj"] = PR["h"] - np.array(hb)
PR.to_csv(os.path.join(OUT, "sideflip_pairs_15_30.csv"), index=False)

LV = pd.read_csv(os.path.join(OUT, "levreplay_rows.csv"))
LV["Rm"] = np.where(LV["status"] == "TRADED", LV["R"], np.where(LV["status"] == "UNRESOLVED", LV["mark_R"], np.nan))


def cluster_boot(g, col="R", blk="blk4"):
    """pooled mean with clusters resampled within run. returns lo, hi, p_pos (P mean<=0), p_neg, n_clusters."""
    x = g[[col, blk, "run"]].dropna()
    if len(x) < 10:
        return np.nan, np.nan, np.nan, np.nan, x[blk].nunique()
    cs = x.groupby(blk).agg(s=(col, "sum"), c=(col, "size"), run=("run", "first"))
    if len(cs) < 5:
        return np.nan, np.nan, np.nan, np.nan, len(cs)
    tot_s = np.zeros(B)
    tot_c = np.zeros(B)
    # a fixed seed per sample (order of calls does not matter: tiers are reproducible)
    rg = np.random.default_rng(zlib.crc32(("|".join(sorted(cs.index.astype(str))) + col + str(len(x))).encode()))
    for _, cr in cs.groupby("run"):
        k = len(cr)
        idx = rg.integers(0, k, size=(B, k))
        tot_s += cr["s"].to_numpy()[idx].sum(1)
        tot_c += cr["c"].to_numpy()[idx].sum(1)
    m = tot_s / tot_c
    obs = x[col].mean()
    # percentile CI; p from the bootstrap distribution shifted to the null (mean 0)
    lo, hi = np.percentile(m, [2.5, 97.5])
    sh = m - m.mean()
    p_pos = (1 + np.sum(sh >= obs)) / (B + 1)      # one-sided: mean > 0
    p_neg = (1 + np.sum(sh <= obs)) / (B + 1)      # one-sided: mean < 0
    return lo, hi, p_pos, p_neg, len(cs)


# ------------------------------------------------------------------ other inputs
A = rd("account_stats.csv")
A = A[(A["kind"] == "strategy") & A["timeframe"].isin(TFS)]
P = rd("strategy_tf_pooled.csv")
P = P[(P["kind"] == "strategy") & P["timeframe"].isin(TFS)].set_index(["strategy", "timeframe"])
T = rd("trades_enriched.csv")
T = T[(T["kind"] == "strategy") & T["tf"].isin(TFS)]
CF = rd("coinflip_pooled.csv")
CF = CF[(CF["kind"] == "strategy") & CF["timeframe"].isin(TFS) & (CF["exits"] == "house")].set_index(["strategy", "timeframe"])
SF = rd("coinflip_sideflip.csv")
SF = SF[(SF["kind"] == "strategy") & (SF["level"] == "strategy_tf")].set_index(["strategy", "timeframe"])
F5 = rd("fiveyear_ref.csv")
F5 = F5[F5["source"] == "profiles_binance"].set_index(["strategy", "timeframe"])
RM = rd("runs_meta.csv").set_index("run")
prof = json.load(open(os.path.join(REPO, "research/strategy_profiles/out_binance/profiles.json")))["profiles"]
SIG = {}
for run in RUNS:
    s = pd.read_csv(os.path.join(EXP, run, "signal_log.csv"))
    s = s[s["status"] == "SUBMITTED"]
    SIG[run] = s.groupby(["strategy", "timeframe"]).size()

strategies = sorted(F5.index.get_level_values(0).unique())
rows, per_run_rows = [], []
for st in strategies:
    for tf in TFS:
        d = {"strategy": st, "timeframe": tf, "cell": f"{st}@{tf}"}
        # ---- account trades per run
        for run in RUNS:
            a = A[(A["run"] == run) & (A["strategy"] == st)]
            a = a[a["timeframe"] == tf]
            p = RN[run]
            if len(a):
                a = a.iloc[0]
                for k in ("n", "mean_R", "win_pct", "payoff", "profit_factor", "max_consec_losses", "realized_max_dd",
                          "hourly_dd_max", "pnl_sum"):
                    d[f"acct_{p}_{k}"] = a[k]
                d[f"acct_{p}_lev_mix"] = a["lev_mix"]
            else:
                d[f"acct_{p}_n"] = 0
        if (st, tf) in P.index:
            pp = P.loc[(st, tf)]
            for k in ("n", "mean_R", "median_R", "win_pct", "payoff", "profit_factor", "max_consec_losses",
                      "worst_realized_dd_any_run", "worst_hourly_dd_any_run", "pnl_sum", "mean_cost_R", "mean_mfe_R",
                      "mean_mae_R", "mean_hold_min", "long_n", "long_mean_R", "short_n", "short_mean_R"):
                d[f"acct_all_{k}"] = pp[k]
        else:
            d["acct_all_n"] = 0
        tt = T[(T["strategy"] == st) & (T["tf"] == tf)]
        d["acct_all_rt_cost_over_stop_median"] = tt["rt_cost_over_stop"].median() if len(tt) else np.nan
        d["acct_all_without_best_trade_mean_R"] = (tt["R"].sum() - tt["R"].max()) / (len(tt) - 1) if len(tt) > 1 else np.nan
        # ---- every signal
        g = ES[(ES["strategy"] == st) & (ES["timeframe"] == tf)]
        ga = ES_all[(ES_all["strategy"] == st) & (ES_all["timeframe"] == tf)]
        for run in RUNS:
            p = RN[run]
            x = g[g["run"] == run]
            d[f"es_{p}_n"] = len(x)
            d[f"es_{p}_mean_R"] = x["R"].mean() if len(x) else np.nan
            d[f"es_{p}_win_pct"] = 100 * x["win"].mean() if len(x) else np.nan
            d[f"es_{p}_ex_sameside"] = x["ex_sameside"].mean() if len(x) else np.nan
            d[f"es_{p}_long_share"] = (x["side"] > 0).mean() if len(x) else np.nan
            if run != "run-20261005T014624Z":
                u = ga[(ga["run"] == run) & (ga["status"] == "UNRESOLVED")]
                d[f"es_{p}_n_unresolved"] = len(u)
                y = pd.concat([x["R"], u["mark_R"]]).dropna()
                d[f"es_{p}_mean_R_incl_unres_mark"] = y.mean() if len(y) else np.nan
                fl = x[(x["flip_status"] == "TRADED") & x["flip_R"].notna()]
                d[f"sf_{p}_n_pairs"] = len(fl)
                d[f"sf_{p}_excess_R"] = (0.5 * (fl["R"] - fl["flip_R"])).mean() if len(fl) else np.nan
            else:
                d["es_v3a_n_unresolved_shadows"] = int(v3a_unres.get((st, tf), 0))
            per_run_rows.append({"strategy": st, "timeframe": tf, "run": p, "n": len(x),
                                 "mean_R": d[f"es_{p}_mean_R"], "win_pct": d[f"es_{p}_win_pct"],
                                 "acct_n": d.get(f"acct_{p}_n", 0), "acct_mean_R": d.get(f"acct_{p}_mean_R", np.nan)})
        n = len(g)
        d["es_n"] = n
        d["es_mean_R"] = g["R"].mean() if n else np.nan
        d["es_median_R"] = g["R"].median() if n else np.nan
        d["es_win_pct"] = 100 * g["win"].mean() if n else np.nan
        w, l_ = g.loc[g["R"] > 0, "R"], g.loc[g["R"] <= 0, "R"]
        d["es_payoff"] = w.mean() / -l_.mean() if len(w) and len(l_) and l_.mean() < 0 else np.nan
        d["es_pf"] = w.sum() / -l_.sum() if len(l_) and l_.sum() < 0 else np.nan
        d["es_long_share"] = (g["side"] > 0).mean() if n else np.nan
        d["es_long_mean_R"] = g.loc[g["side"] > 0, "R"].mean()
        d["es_short_mean_R"] = g.loc[g["side"] < 0, "R"].mean()
        d["es_ex_sameside"] = g["ex_sameside"].mean() if n else np.nan
        lo, hi, pp_, pn_, ncl = cluster_boot(g, "R", "blk4")
        d.update(es_ci_lo_4h=lo, es_ci_hi_4h=hi, es_p_pos_4h=pp_, es_p_neg_4h=pn_, es_clusters_4h=ncl)
        lo1, hi1, pp1, pn1, ncl1 = cluster_boot(g, "R", "blk1")
        d.update(es_ci_lo_1h=lo1, es_ci_hi_1h=hi1, es_p_pos_1h=pp1, es_clusters_1h=ncl1)
        lo2, hi2, pp2, pn2, _ = cluster_boot(g, "ex_sameside", "blk4")
        d.update(es_ex_sameside_ci_lo=lo2, es_ex_sameside_ci_hi=hi2, es_ex_sameside_p_pos=pp2)
        if n:
            cl = g.groupby("blk4")["R"].sum()
            d["es_share_4h_blocks_pos"] = (cl > 0).mean()
            best = cl.idxmax()
            rest = g[g["blk4"] != best]
            d["es_mean_R_without_best_4h_block"] = rest["R"].mean() if len(rest) else np.nan
            byday = g.groupby("kst_day")["R"].sum()
            d["es_mean_R_without_best_day"] = g[g["kst_day"] != byday.idxmax()]["R"].mean() if len(byday) > 1 else np.nan
        d["es_mean_roe_per_lev"] = g["roe_per_lev"].mean() if n else np.nan
        d["es_mean_gross_R_post_slip"] = (g["R"] + g["cost_R"]).mean() if g["cost_R"].notna().any() else np.nan
        d["es_mean_cost_R"] = g["cost_R"].mean()
        d["es_median_rt_cost_over_stop"] = (RT_COST / g["stop_frac"]).median() if n else np.nan
        d["es_median_stop_pct"] = 100 * g["stop_frac"].median() if n else np.nan
        d["es_mean_mfe_R"] = g["mfe_R"].mean()
        d["es_median_mfe_R"] = g["mfe_R"].median()
        d["es_mean_mae_R"] = g["mae_R"].mean()
        d["es_share_mfe_ge_1R"] = (g["mfe_R"] >= 1).mean() if g["mfe_R"].notna().any() else np.nan
        d["es_lev_mix"] = " ".join(f"{int(k)}:{v}" for k, v in g["leverage"].value_counts().items())
        # out-of-sample split: v3a (first) vs v3b + v4 (later)
        later = g[g["run"] != "run-20261005T014624Z"]
        d["es_later_n"] = len(later)
        d["es_later_mean_R"] = later["R"].mean() if len(later) else np.nan
        lo3, hi3, pp3, _, _ = cluster_boot(later, "R", "blk4")
        d.update(es_later_ci_lo=lo3, es_later_ci_hi=hi3)
        # ---- drift-adjusted side flip (v3b + v4)
        q = PR[(PR["strategy"] == st) & (PR["timeframe"] == tf)]
        d["sf_adj_n"] = len(q)
        d["sf_raw_excess_R_mine"] = q["h"].mean() if len(q) else np.nan
        d["sf_adj_excess_R"] = q["h_adj"].mean() if len(q) else np.nan
        loa, hia, ppa, _, _ = cluster_boot(q, "h_adj", "blk4")
        d.update(sf_adj_ci_lo=loa, sf_adj_ci_hi=hia, sf_adj_p_pos=ppa)
        # ---- fixed-leverage replay (v3b + v4; TRADED R, UNRESOLVED marked)
        for v in ("live_rule", "lev10", "lev20m20", "lev30m30", "lev40m40", "lev50m50"):
            z = LV[(LV["strategy"] == st) & (LV["timeframe"] == tf) & (LV["variant"] == v)]
            d[f"lev_{v}_sized"] = int(z["status"].isin(["TRADED", "UNRESOLVED"]).sum())
            d[f"lev_{v}_mean_R_mark"] = z["Rm"].mean() if len(z) else np.nan
        # ---- side flip (v3b + v4 pooled, pipeline)
        if (st, tf) in SF.index:
            s = SF.loc[(st, tf)]
            for k in ("n_pairs", "n_clusters", "excess_R", "p_better", "p_worse", "bh_q_better", "mde_excess_R_80pct"):
                d[f"sf_{k}"] = s[k]
        # ---- coin-flip bootstrap (account trades vs coin-flip accounts' trades)
        if (st, tf) in CF.index:
            c = CF.loc[(st, tf)]
            for k in ("n", "mean_R", "rand_pool_mean_R", "rand_pool_n", "percentile", "p_one_sided", "p_worse_one_sided",
                      "bh_q", "bh_q_worse", "low_power", "mde_R_80pct"):
                d[f"cf_{k}"] = c[k]
        # ---- 5-year
        if (st, tf) in F5.index:
            f = F5.loc[(st, tf)]
            for k in ("n_signals", "per_day", "mean_roe", "mean_roe_t", "mean_roe_is", "mean_roe_cf", "mean_lev",
                      "mean_ret_notional", "win_rate", "long_share", "median_hold_hours", "mean_best_roe"):
                d[f"y5_{k}"] = f[k]
            d["y5_gross_ret_notional"] = f["mean_ret_notional"] + RT_COST if f["mean_ret_notional"] == f["mean_ret_notional"] else np.nan
        pr = prof.get(st, {}).get(tf, {})
        fw = pr.get("fwd_mean_pct") or {}
        for h in ("4", "16"):
            v = fw.get(h)
            d[f"y5_fwd{h}bars_gross_pct"] = (v + 100 * RT_COST) if v is not None else np.nan
        d["y5_peak_t_net"] = pr.get("peak_t")
        # ---- signals per day
        for run in RUNS:
            d[f"live_{RN[run]}_sig_per_day"] = SIG[run].get((st, tf), 0) / RM.loc[run, "days"]
        tot = sum(SIG[run].get((st, tf), 0) for run in RUNS)
        d["live_sig_per_day"] = tot / sum(RM.loc[run, "days"] for run in RUNS)
        rows.append(d)

C = pd.DataFrame(rows)
# BH over cells with a bootstrap p (both tails)
m = C["es_p_pos_4h"].notna()
C.loc[m, "es_bh_q_pos_4h"] = bh(C.loc[m, "es_p_pos_4h"])
C.loc[m, "es_bh_q_neg_4h"] = bh(C.loc[m, "es_p_neg_4h"])
m3 = C["sf_adj_p_pos"].notna()
C.loc[m3, "sf_adj_bh_q_pos"] = bh(C.loc[m3, "sf_adj_p_pos"])
m2 = C["es_ex_sameside_p_pos"].notna()
C.loc[m2, "es_ex_sameside_bh_q_pos"] = bh(C.loc[m2, "es_ex_sameside_p_pos"])


# ------------------------------------------------------------------ sign consistency + tiers (rules fixed before reading results)
def tier(r):
    signs = []
    for p in ("v3a", "v3b", "v4"):
        if r[f"es_{p}_n"] >= 5:
            signs.append(np.sign(r[f"es_{p}_mean_R"]))
    k, pos, neg = len(signs), sum(s > 0 for s in signs), sum(s < 0 for s in signs)
    m_, n_ = r["es_mean_R"], r["es_n"]
    y5neg = (r.get("y5_mean_ret_notional", np.nan) < 0) and (r.get("y5_mean_roe_t", 0) < -2)
    y5_isneg = (r.get("y5_mean_roe_is", np.nan) < 0) and (r.get("y5_mean_roe_cf", np.nan) < 0)
    sf = r.get("sf_excess_R", np.nan)
    if n_ >= 30 and m_ > 0 and r["es_ci_lo_4h"] > 0 and k >= 2 and pos == k and sf > 0 and not y5neg:
        return "A", k, pos, neg, y5neg, y5_isneg
    if n_ >= 20 and m_ < 0 and y5neg and ((k >= 2 and neg == k) or r["es_ci_hi_4h"] < 0):
        return "D", k, pos, neg, y5neg, y5_isneg
    if n_ >= 20 and m_ > 0 and ((k >= 2 and pos >= 2 and neg <= 1) or (k >= 1 and pos == k)):
        return "B", k, pos, neg, y5neg, y5_isneg
    return "C", k, pos, neg, y5neg, y5_isneg


tt = C.apply(lambda r: pd.Series(tier(r), index=["tier", "runs_k", "runs_pos", "runs_neg", "y5_negative", "y5_is_and_cf_negative"]), axis=1)
C = pd.concat([C, tt], axis=1)
C["sign_v3a_v3b_v4"] = C.apply(lambda r: " ".join(
    ("+" if r[f"es_{p}_mean_R"] > 0 else "-" if r[f"es_{p}_mean_R"] < 0 else "0") + (f"({int(r[f'es_{p}_n'])})")
    if r[f"es_{p}_n"] > 0 else "na" for p in ("v3a", "v3b", "v4")), axis=1)
C["live_vs_5y_sign_notional"] = np.where(C["es_mean_roe_per_lev"].isna(), "no live",
                                         np.where(np.sign(C["es_mean_roe_per_lev"]) == np.sign(C["y5_mean_ret_notional"]),
                                                  "same", "differ"))
lead = ["cell", "strategy", "timeframe", "tier", "sign_v3a_v3b_v4", "runs_k", "runs_pos", "runs_neg", "es_n", "es_mean_R",
        "es_ci_lo_4h", "es_ci_hi_4h", "es_p_pos_4h", "es_bh_q_pos_4h", "es_p_neg_4h", "es_bh_q_neg_4h", "es_later_n",
        "es_later_mean_R", "es_ex_sameside", "sf_n_pairs", "sf_excess_R", "sf_p_better", "acct_all_n", "acct_all_mean_R",
        "y5_mean_ret_notional", "y5_mean_roe_t", "y5_negative", "live_vs_5y_sign_notional"]
C = C[lead + [c for c in C.columns if c not in lead]]
C.to_csv(os.path.join(OUT, "cards_15_30.csv"), index=False)
pd.DataFrame(per_run_rows).to_csv(os.path.join(OUT, "cards_15_30_per_run.csv"), index=False)
print(C["tier"].value_counts().to_dict())
print(C.groupby("timeframe")["tier"].value_counts().unstack().to_string())


# ------------------------------------------------------------------ pooled (all 36) per tf x run and the 5-year comparator
prow = []
for tf in TFS:
    for run in RUNS + ["ALL", "LATER"]:
        g = ES[ES["timeframe"] == tf]
        if run == "LATER":
            g = g[g["run"] != "run-20261005T014624Z"]
        elif run != "ALL":
            g = g[g["run"] == run]
        lo, hi, pp_, pn_, ncl = cluster_boot(g, "R", "blk4")
        q = PR[PR["timeframe"] == tf]
        if run == "LATER" or run == "ALL":
            pass
        else:
            q = q[q["run"] == run]
        f5 = F5.xs(tf, level="timeframe")
        w5 = f5["n_signals"].fillna(0)
        prow.append({"timeframe": tf, "run": RN.get(run, run), "n": len(g), "mean_R": g["R"].mean(), "ci_lo_4h": lo,
                     "ci_hi_4h": hi, "clusters_4h": ncl, "win_pct": 100 * (g["R"] > 0).mean(),
                     "mean_gross_R_post_slip": (g["R"] + g["cost_R"]).mean(), "mean_cost_R": g["cost_R"].mean(),
                     "median_stop_pct": 100 * g["stop_frac"].median(),
                     "median_rt_cost_over_stop": (RT_COST / g["stop_frac"]).median(),
                     "mean_ret_notional": g["roe_per_lev"].mean(), "long_share": (g["side"] > 0).mean(),
                     "mean_mfe_R": g["mfe_R"].mean(), "mean_mae_R": g["mae_R"].mean(),
                     "lev_mix": " ".join(f"{int(k)}:{v}" for k, v in g["leverage"].value_counts().items()),
                     "sf_n": len(q), "sf_raw": q["h"].mean() if len(q) else np.nan,
                     "sf_adj": q["h_adj"].mean() if len(q) else np.nan,
                     "y5_signal_weighted_ret_notional": np.average(f5["mean_ret_notional"].fillna(0), weights=w5),
                     "y5_signal_weighted_gross_ret_notional": np.average(f5["mean_ret_notional"].fillna(0), weights=w5) + RT_COST})
PO = pd.DataFrame(prow)
PO.to_csv(os.path.join(OUT, "pooled_15_30.csv"), index=False)
print(PO.round(4).to_string())

# ------------------------------------------------------------------ planning: days of every-signal data needed for a +-0.1R CI
C = pd.read_csv(os.path.join(OUT, "cards_15_30.csv"))
live_days = {}
for run in RUNS:
    g = ES[ES["run"] == run]
    live_days[run] = (g["bar_close"].max() - g["bar_close"].min()) / (24 * H) if len(g) else 0.0
tot_days = sum(live_days.values())
hw = (C["es_ci_hi_4h"] - C["es_ci_lo_4h"]) / 2
C["es_days_covered"] = tot_days
C["es_days_for_ci_halfwidth_0.1R"] = tot_days * (hw / 0.1) ** 2
C["es_days_for_ci_halfwidth_0.2R"] = tot_days * (hw / 0.2) ** 2
C.to_csv(os.path.join(OUT, "cards_15_30.csv"), index=False)
print("every-signal days covered:", {RN[k]: round(v, 2) for k, v in live_days.items()}, round(tot_days, 2))
