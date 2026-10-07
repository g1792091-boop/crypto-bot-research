"""Evidence cards for our 36 strategies at 1h and 4h (72 cells) -> cards_1h_4h.csv.

    python3 -I cards.py <work_dir>

Inputs (all in work_dir, made by the other scripts): live_cells.csv (live_cells.py), es_signals.csv, fy_cells.csv
(fy_stats.py), fy_tfcompare.csv (fy_tfcompare.py). Adds:
  * live HTF - LTF: every-signal mean R at this timeframe minus the same strategy's pooled 15m + 30m every-signal mean
    R (all runs), 95% CI by independent cluster bootstrap of the two groups (run x 4 h blocks; 4,000 draws).
  * BH q over the 72 cells of the 5-year gross-R t (day clustered).
  * grade (rule fixed here, before reading the per-cell results line by line):
      U  untestable: < 100 sized 5-year signals AND < 10 live every-signal outcomes
      A  5-year net mean R > 0 with t >= 2 in BOTH IS and CF, AND live every-signal 95% CI above 0
      B  5-year gross R > 0 with t >= 2 in BOTH IS and CF (a directional edge that survives a split), net 5-year
         mean R > -0.05, and live not contradicting (live n < 10 or live mean R > -0.10)
      D  5-year net t <= -2 with gross R <= -0.02 (direction worse than nothing), OR live every-signal 95% CI
         entirely below 0 with n >= 8
      C  the rest: no directional edge either way; net result = minus the cost (cost-limited)
"""
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

W = sys.argv[1]
RNG = np.random.default_rng(20261010)


def boot_diff(a, ca, b, cb, B=4000):
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan
    def prep(x, c):
        s = pd.DataFrame({"x": x, "c": c}).groupby("c")["x"].agg(["sum", "size"])
        return s["sum"].to_numpy(), s["size"].to_numpy()
    sa, na = prep(a, ca)
    sb, nb = prep(b, cb)
    if len(sa) < 3 or len(sb) < 3:
        return np.nan, np.nan
    ia = RNG.integers(0, len(sa), size=(B, len(sa)))
    ib = RNG.integers(0, len(sb), size=(B, len(sb)))
    d = sa[ia].sum(1) / na[ia].sum(1) - sb[ib].sum(1) / nb[ib].sum(1)
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def bh(p):
    p = np.asarray(p, float)
    q = np.full(len(p), np.nan)
    m = np.isfinite(p)
    pp = p[m]
    o = np.argsort(pp)
    qq = np.empty_like(pp)
    qq[o] = np.minimum.accumulate((pp[o] * len(pp) / np.arange(1, len(pp) + 1))[::-1])[::-1]
    q[m] = np.minimum(qq, 1)
    return q


def grade(r):
    fy_n = r.get("fy_n") if r.get("fy_n") == r.get("fy_n") else 0
    es_n = r.get("es_n", 0)
    if fy_n < 100 and es_n < 10:
        return "U"
    if (r["fy_is_t_R"] >= 2 and r["fy_cf_t_R"] >= 2 and r["fy_is_mean_R"] > 0 and r["fy_cf_mean_R"] > 0
            and r["es_ci95_lo"] > 0):
        return "A"
    if (r["fy_is_gross_t"] >= 2 and r["fy_cf_gross_t"] >= 2 and r["fy_mean_R"] > -0.05
            and (es_n < 10 or r["es_mean_R"] > -0.10)):
        return "B"
    if (r["fy_t_R"] <= -2 and r["fy_gross_R"] <= -0.02) or (es_n >= 8 and r["es_ci95_hi"] < 0):
        return "D"
    return "C"


def main():
    C = pd.read_csv(f"{W}/live_cells.csv")
    F = pd.read_csv(f"{W}/fy_cells.csv")
    T = pd.read_csv(f"{W}/fy_tfcompare.csv").rename(columns={"htf": "tf"})
    ES = pd.read_csv(f"{W}/es_signals.csv")
    LT = C[C["tf"].isin(["15m", "30m"])]
    ltf = LT.groupby("strategy").apply(lambda g: pd.Series({
        "es_15m_n": g.loc[g["tf"] == "15m", "es_n"].sum(), "es_15m_mean_R": g.loc[g["tf"] == "15m", "es_mean_R"].mean(),
        "es_30m_n": g.loc[g["tf"] == "30m", "es_n"].sum(), "es_30m_mean_R": g.loc[g["tf"] == "30m", "es_mean_R"].mean()}),
        include_groups=False).reset_index()
    M = C[C["tf"].isin(["1h", "4h"])].merge(F, on=["strategy", "tf"], how="left")
    M = M.merge(T[["strategy", "tf", "mean_R_ltf", "gross_R_ltf", "mean_R_15m", "mean_R_30m", "d_R_all", "t_R_all",
                   "d_gross_R_all", "t_gross_R_all", "d_gross_R_is", "d_gross_R_cf", "bh_q_gross_R_all"]].rename(
        columns={"mean_R_ltf": "fy_ltf_mean_R", "gross_R_ltf": "fy_ltf_gross_R", "mean_R_15m": "fy_15m_mean_R",
                 "mean_R_30m": "fy_30m_mean_R", "d_R_all": "fy_htf_minus_ltf_R", "t_R_all": "fy_htf_minus_ltf_t",
                 "d_gross_R_all": "fy_htf_minus_ltf_gross_R", "t_gross_R_all": "fy_htf_minus_ltf_gross_t",
                 "d_gross_R_is": "fy_htf_minus_ltf_gross_R_is", "d_gross_R_cf": "fy_htf_minus_ltf_gross_R_cf",
                 "bh_q_gross_R_all": "fy_htf_minus_ltf_gross_bh_q"}), on=["strategy", "tf"], how="left")
    M = M.merge(ltf, on="strategy", how="left")
    # live HTF - pooled LTF every-signal difference
    lo_, hi_, d_ = [], [], []
    for r in M.itertuples():
        a = ES[(ES["strategy"] == r.strategy) & (ES["timeframe"] == r.tf)]
        b = ES[(ES["strategy"] == r.strategy) & ES["timeframe"].isin(["15m", "30m"])]
        d_.append(a["R"].mean() - b["R"].mean() if len(a) and len(b) else np.nan)
        lo, hi = boot_diff(a["R"].to_numpy(), a["cl"].to_numpy(), b["R"].to_numpy(), b["cl"].to_numpy())
        lo_.append(lo)
        hi_.append(hi)
    M["live_htf_minus_ltf_R"], M["live_htf_minus_ltf_ci_lo"], M["live_htf_minus_ltf_ci_hi"] = d_, lo_, hi_
    # BH over the 72 cells of the 5-year gross t (two-sided normal p)
    from math import erf, sqrt
    p = M["fy_gross_t"].map(lambda t: 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2)))) if t == t else np.nan)
    M["fy_gross_bh_q"] = bh(p)
    pn = M["fy_t_R"].map(lambda t: 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2)))) if t == t else np.nan)
    M["fy_net_bh_q"] = bh(pn)
    M["grade"] = [grade(r) for r in M.to_dict("records")]
    # tradability flags
    for c in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"):
        if f"fy_sized_{c}" not in M:
            M[f"fy_sized_{c}"] = np.nan
    M["fy_sized_by_coin"] = M.apply(lambda r: " ".join(
        f"{c[:-3]}:{r[f'fy_sized_{c}']:.2f}" for c in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
        if r[f"fy_sized_{c}"] == r[f"fy_sized_{c}"]), axis=1)
    M["fy_sized_per_day"] = M["fy_per_day"] * M["fy_sized_share"]

    def flags(r):
        f = []
        if (r["grade"] == "C" and r["fy_gross_bh_q"] < 0.05 and r["fy_gross_R"] > 0
                and r["fy_is_gross_t"] > 1.9 and r["fy_cf_gross_t"] > 1.9):
            f.append(f"borderline B: 5y gross {r['fy_gross_R']:+.3f}R (72-cell BH q {r['fy_gross_bh_q']:.3f}), IS gross t "
                     f"{r['fy_is_gross_t']:.4f} just under the preset 2.0, CF t {r['fy_cf_gross_t']:.2f}")
        if r["tf"] == "4h":
            f.append("4h at 20x: sizable mostly on BTC/ETH (live v3b+v4: every BCH/DOGE/LTC 4h signal rejected)")
        if r["es_n"] and r["es_n"] < 10:
            f.append(f"live every-signal n={int(r['es_n'])}: no inference")
        if r["rp_n_unresolved"] and r["rp_n_traded"] and r["rp_n_unresolved"] / (r["rp_n_unresolved"] + r["rp_n_traded"]) > 0.25:
            f.append(f"{int(r['rp_n_unresolved'])} of {int(r['rp_n_unresolved'] + r['rp_n_traded'])} replayed signals still open at run end (censoring)")
        if r["fy_n"] == r["fy_n"] and r["fy_n"] < 300:
            f.append(f"near-silent: {int(r['fy_n'])} sized signals in 5 years")
        return "; ".join(f)
    M["flags"] = [flags(r) for r in M.to_dict("records")]
    cols = ["strategy", "tf", "grade", "flags", "style",
            # accounts
            "acct_v3a_n", "acct_v3a_mean_R", "acct_v3a_pnl", "acct_v3b_n", "acct_v3b_mean_R", "acct_v3b_pnl",
            "acct_v4_n", "acct_v4_mean_R", "acct_v4_pnl", "acct_all_n", "acct_all_mean_R", "acct_all_pnl_sum",
            "acct_all_win_pct", "acct_all_payoff", "acct_all_profit_factor", "acct_all_max_consec_losses",
            "acct_all_worst_realized_dd_any_run", "acct_rej_n", "acct_rej_by_run_coin",
            # every signal
            "es_v3a_n", "es_v3a_mean_R", "es_v3b_n", "es_v3b_mean_R", "es_v4_n", "es_v4_mean_R", "es_n", "es_mean_R",
            "es_ci95_lo", "es_ci95_hi", "es_clusters", "es_runs_tested", "es_runs_pos", "es_win_pct", "es_payoff",
            "es_median_R", "v3a_shadow_noR",
            # replay detail
            "rp_n_submitted", "rp_n_traded", "rp_n_rej_sizing", "rp_rej_by_coin", "rp_traded_coins",
            "rp_n_unresolved", "rp_mean_mark_R_unres", "rp_lev_mix", "rp_exit_mix", "rp_mean_hold_h",
            "live_cost_R_median", "live_stop_pct_median", "live_signals_per_day",
            # side flip
            "sideflip_n_pairs", "sideflip_n_clusters", "sideflip_excess_R", "sideflip_p_better", "sideflip_bh_q_better",
            # 5-year, current rules (own sim)
            "fy_signals", "fy_per_day", "fy_sized_share", "fy_sized_per_day", "fy_sized_by_coin", "fy_n", "fy_mean_R",
            "fy_ci95_lo", "fy_ci95_hi", "fy_t_R", "fy_net_bh_q", "fy_is_mean_R", "fy_is_t_R", "fy_cf_mean_R",
            "fy_cf_t_R", "fy_gross_R", "fy_gross_t", "fy_gross_bh_q", "fy_is_gross_R", "fy_is_gross_t",
            "fy_cf_gross_R", "fy_cf_gross_t", "fy_cost_R", "fy_win_pct", "fy_payoff", "fy_lock_share",
            "fy_liq_share", "fy_median_hold_h", "fy_years_pos", "fy_years",
            # 5-year reference (profiles_binance, old tier walk)
            "ref5y_n", "ref5y_per_day", "ref5y_mean_roe", "ref5y_t", "ref5y_is_roe", "ref5y_cf_roe",
            "ref5y_ret_notional", "ref5y_win", "ref5y_sized_share", "ref5y_median_hold_h", "ref5y_trend_share",
            "ref5y_acct_is_final", "ref5y_acct_cf_final",
            # vs 15m / 30m
            "es_15m_n", "es_15m_mean_R", "es_30m_n", "es_30m_mean_R", "live_htf_minus_ltf_R",
            "live_htf_minus_ltf_ci_lo", "live_htf_minus_ltf_ci_hi", "fy_15m_mean_R", "fy_30m_mean_R",
            "fy_ltf_mean_R", "fy_ltf_gross_R", "fy_htf_minus_ltf_R", "fy_htf_minus_ltf_t", "fy_htf_minus_ltf_gross_R",
            "fy_htf_minus_ltf_gross_t", "fy_htf_minus_ltf_gross_R_is", "fy_htf_minus_ltf_gross_R_cf",
            "fy_htf_minus_ltf_gross_bh_q"]
    for c in cols:
        if c not in M:
            M[c] = np.nan
    out = M[cols].sort_values(["tf", "grade", "fy_mean_R"], ascending=[True, True, False])
    out.to_csv(f"{W}/cards_1h_4h.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print(out.groupby(["tf", "grade"]).size())
    print(out[["strategy", "tf", "grade", "es_n", "es_mean_R", "es_ci95_lo", "es_ci95_hi", "fy_n", "fy_mean_R",
               "fy_t_R", "fy_gross_R", "fy_gross_t", "fy_is_gross_t", "fy_cf_gross_t", "fy_gross_bh_q",
               "fy_sized_per_day", "live_htf_minus_ltf_R", "fy_htf_minus_ltf_gross_R"]].round(3).to_string())
    # sanity: own-sim return per unit notional vs the reference profiles (different leverage rule, same sign expected)
    F2 = F.copy()


if __name__ == "__main__":
    main()
