"""Stage 7: tables behind RESULTS_KO.md (out/*.csv, out/*.json).

  pick_results.csv   per strategy x tf x variant x set (default / friend / pick1-3 / coinpick) x scope (ALL or coin)
                     x period: trades, win rate, gross R, cost R, net R, 95% week-block interval, max drawdown (R)
  crash_windows.csv  the same sets in 2020-03, 2022-05, 2022-11 (signal month)
  luck.csv           luck baseline per pick (50 random sets, best-of-grid-size 95th percentile)
  pass_rule.csv      PREREG pass rule per pick (pooled and per coin, every variant)
  neighbours.csv     TEST mean of each pick's plateau neighbours
  reopt.csv          ROLL5 / WEEKLY vs default accounts (TEST, EXTRA)
  accounts.csv       account simulations (all runs)

    python3 -B research/st_custom/s7_report.py
"""
import os
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import s2_signals as S2  # noqa: E402
import s4_detail as S4  # noqa: E402
import s5_reopt as S5  # noqa: E402

B = 2000


def tp_k(vname):
    if not vname.startswith("tpsl_"):
        return None
    return float(vname.split("_")[2].replace("atr", ""))


def load_detail():
    D = {}
    for coin in C.COINS:
        for tf in C.TFS:
            for per in C.PERIOD_ORDER:
                z = np.load(S4.det_path(coin, tf, per))
                D[(coin, tf, per)] = {k: z[k] for k in z.files}
    return D


def set_names(picks, strat, tf, vname):
    """[(set name, combo, scope list)]"""
    out = [("default", C.combo_index(strat, C.DEFAULT_IDX[strat]), None)]
    if strat in C.FRIEND_IDX:
        out.append(("friend", C.combo_index(strat, C.FRIEND_IDX[strat]), None))
    g = picks[(picks.strategy == strat) & (picks.tf == tf) & (picks.variant == vname)]
    for r in g[g.scope == "pooled"].itertuples():
        out.append((f"pick{r.rank}", int(r.combo), None))
    for r in g[g.scope == "coin"].itertuples():
        out.append(("coinpick", int(r.combo), r.coin))
    return out


def row_stats(n, w, sR, sG, wn=None, ws=None, mdd=None, seed=0):
    d = dict(trades=int(n), win_rate=w / n if n else np.nan, gross_R=sG / n if n else np.nan,
             cost_R=(sG - sR) / n if n else np.nan, net_R=sR / n if n else np.nan)
    if wn is not None:
        lo, hi = C.boot_ci(wn, ws, B, seed)
        d.update(ci_lo=lo, ci_hi=hi)
    if mdd is not None:
        d["max_dd_R"] = mdd
    return d


def pick_results(picks, D):
    rows, crash = [], []
    for strat in C.STRATS:
        for tf in C.TFS:
            for vname in S2.VARIANTS:
                k = f"{strat}|{vname}"
                kk = tp_k(vname)
                for set_name, c, only_coin in set_names(picks, strat, tf, vname):
                    for per in C.PERIOD_ORDER:
                        tot = np.zeros(8)
                        wn = ws = day = None
                        cr = np.zeros((3, 4))
                        for coin in C.COINS:
                            z = D[(coin, tf, per)]
                            j = int(np.flatnonzero(z[k + "|combos"] == c)[0])
                            st = z[k + "|stats"][j]
                            seed = zlib.crc32(f"{strat}{tf}{vname}{set_name}{c}{per}{coin}".encode())
                            if only_coin is None or only_coin == coin:
                                r = row_stats(st[0], st[1], st[2], st[3], z[k + "|wn"][j], z[k + "|ws"][j],
                                              float(z[k + "|mdd"][j]), seed)
                                rows.append(dict(strategy=strat, tf=tf, variant=vname, set=set_name, combo=c,
                                                 label=C.combo_label(strat, c), scope=coin, period=per,
                                                 signals=int(st[5]), **r,
                                                 net_R2=(r["net_R"] * kk / 2 if kk else np.nan)))
                            if only_coin is None:
                                tot += st
                                wn = z[k + "|wn"][j].astype(float) if wn is None else wn + z[k + "|wn"][j]
                                ws = z[k + "|ws"][j].astype(float) if ws is None else ws + z[k + "|ws"][j]
                                day = z[k + "|day"][j].astype(float) if day is None else day + z[k + "|day"][j]
                                cr += z[k + "|crash"][j]
                            elif only_coin == coin:
                                cr += z[k + "|crash"][j]
                        if only_coin is None:
                            seed = zlib.crc32(f"{strat}{tf}{vname}{set_name}{c}{per}ALL".encode())
                            r = row_stats(tot[0], tot[1], tot[2], tot[3], wn, ws, C.max_dd(day), seed)
                            rows.append(dict(strategy=strat, tf=tf, variant=vname, set=set_name, combo=c,
                                             label=C.combo_label(strat, c), scope="ALL", period=per,
                                             signals=int(tot[5]), **r, net_R2=(r["net_R"] * kk / 2 if kk else np.nan)))
                        for q, wname in enumerate(C.CRASH):
                            if cr[q, 0] > 0:
                                crash.append(dict(strategy=strat, tf=tf, variant=vname, set=set_name, combo=c,
                                                  scope=only_coin or "ALL", window=wname, period=per,
                                                  **row_stats(*cr[q])))
    return pd.DataFrame(rows), pd.DataFrame(crash)


def luck(picks, D, PR):
    rows = []
    rng = np.random.default_rng(20261009)
    for strat in C.STRATS:
        G = C.NCOMBO[strat]
        for tf in C.TFS:
            for vname in S2.VARIANTS:
                k = f"{strat}|{vname}"
                g = picks[(picks.strategy == strat) & (picks.tf == tf) & (picks.variant == vname)]
                for r in g.itertuples():
                    pid = f"{r.scope}|{r.rank}|{r.coin}"
                    s = np.zeros(S4.NLUCK)
                    n = np.zeros(S4.NLUCK)
                    for coin in C.COINS:
                        z = D[(coin, tf, "SEARCH")]
                        ids = list(z[k + "|luck_ids"])
                        if pid in ids:
                            q = ids.index(pid)
                            s += z[k + "|luck_s"][q]
                            n += z[k + "|luck_n"][q]
                    with np.errstate(invalid="ignore", divide="ignore"):
                        m = s / n
                    best = np.array([np.max(m[rng.integers(0, len(m), G)]) for _ in range(10000)])
                    p95 = float(np.percentile(best, 95))
                    mu, sd = float(np.mean(m)), float(np.std(m, ddof=1))
                    from statistics import NormalDist
                    p95_norm = mu + sd * NormalDist().inv_cdf(0.95 ** (1.0 / G))
                    scope = "ALL" if r.scope == "pooled" else r.coin
                    pr = PR[(PR.strategy == strat) & (PR.tf == tf) & (PR.variant == vname) & (PR.combo == r.combo) &
                            (PR.scope == scope) & (PR.period == "SEARCH")]
                    pr = pr[pr.set == (f"pick{r.rank}" if r.scope == "pooled" else "coinpick")]
                    sm = float(pr.net_R.iloc[0])
                    rows.append(dict(strategy=strat, tf=tf, variant=vname, scope=r.scope, rank=r.rank, coin=r.coin,
                                     combo=r.combo, label=C.combo_label(strat, r.combo), search_net_R=sm,
                                     random_mean=mu, random_sd=sd, random_max50=float(np.max(m)),
                                     random_best_of_grid_p95=p95, random_best_p95_normal_approx=p95_norm,
                                     grid_size=G, random_trades_per_set=float(np.mean(n)), beats_luck=sm > p95,
                                     beats_luck_normal_approx=sm > p95_norm))
    return pd.DataFrame(rows)


def neighbours_test(picks, AT):
    rows = []
    for r in picks.itertuples():
        A = AT[r.strategy]
        ti, v = C.TFS.index(r.tf), S2.VARIANTS.index(r.variant)
        pi = C.PERIOD_ORDER.index("TEST")
        if r.scope == "pooled":
            X = A[ti, pi, :, v].sum(0)
        else:
            X = A[ti, pi, C.COINS.index(r.coin), v]
        nb = C.neighbours(r.strategy, r.combo, include_self=False)
        n, s = X[nb, 0], X[nb, 2]
        ok = n >= 1
        means = s[ok] / n[ok]
        rows.append(dict(strategy=r.strategy, tf=r.tf, variant=r.variant, scope=r.scope, rank=r.rank, coin=r.coin,
                         combo=r.combo, neighbours=int(len(nb)), neighbours_with_test_trades=int(ok.sum()),
                         neighbours_test_mean=float(np.mean(means)) if len(means) else np.nan,
                         neighbours_test_pos_share=float(np.mean(means > 0)) if len(means) else np.nan,
                         neighbours_incl_self_test_mean=float(np.mean(np.r_[means, X[r.combo, 2] / X[r.combo, 0]]))
                         if X[r.combo, 0] > 0 else np.nan))
    return pd.DataFrame(rows)


def pass_rule(picks, PR, LK, NB):
    rows = []
    for r in picks.itertuples():
        scope = "ALL" if r.scope == "pooled" else r.coin
        setn = f"pick{r.rank}" if r.scope == "pooled" else "coinpick"
        base = PR[(PR.strategy == r.strategy) & (PR.tf == r.tf) & (PR.variant == r.variant) & (PR.scope == scope)]
        me = base[(base.set == setn) & (base.combo == r.combo)].set_index("period")
        de = base[base.set == "default"].set_index("period")
        lk = LK[(LK.strategy == r.strategy) & (LK.tf == r.tf) & (LK.variant == r.variant) & (LK.scope == r.scope) &
                (LK["rank"] == r.rank) & (LK.coin == r.coin)].iloc[0]
        nb = NB[(NB.strategy == r.strategy) & (NB.tf == r.tf) & (NB.variant == r.variant) & (NB.scope == r.scope) &
                (NB["rank"] == r.rank) & (NB.coin == r.coin)].iloc[0]
        t, x = me.loc["TEST", "net_R"], me.loc["EXTRA", "net_R"]
        r1 = bool(t > 0 and x > 0)
        r2 = bool(t > de.loc["TEST", "net_R"] and x > de.loc["EXTRA", "net_R"])
        r3 = bool(lk.beats_luck)
        r4 = bool(nb.neighbours_test_mean > 0)
        rows.append(dict(strategy=r.strategy, tf=r.tf, variant=r.variant, scope=r.scope, rank=r.rank, coin=r.coin,
                         combo=r.combo, label=C.combo_label(r.strategy, r.combo),
                         search_net_R=me.loc["SEARCH", "net_R"], test_net_R=t, test_ci_lo=me.loc["TEST", "ci_lo"],
                         test_ci_hi=me.loc["TEST", "ci_hi"], extra_net_R=x, extra_ci_lo=me.loc["EXTRA", "ci_lo"],
                         extra_ci_hi=me.loc["EXTRA", "ci_hi"], default_test_net_R=de.loc["TEST", "net_R"],
                         default_extra_net_R=de.loc["EXTRA", "net_R"], luck_p95=lk.random_best_of_grid_p95,
                         neighbours_test_mean=nb.neighbours_test_mean, shrink_search_to_test=me.loc["SEARCH", "net_R"] - t,
                         rule1_test_extra_pos=r1, rule2_beats_default=r2, rule3_beats_luck=r3,
                         rule4_neighbours_pos=r4, PASS=r1 and r2 and r3 and r4))
    return pd.DataFrame(rows)


def reopt():
    rows = []
    for strat in C.STRATS:
        for tf in C.TFS:
            z = np.load(os.path.join(S5.RE_DIR, f"{strat}_{tf}.npz"))
            d = C.combo_index(strat, C.DEFAULT_IDX[strat])
            for per in S5.RUN_PERIODS:
                base = z[f"{per}|DEFAULT|trades"]
                for method in S5.METHODS:
                    tr = z[f"{per}|{method}|trades"]
                    pk = z[f"{per}|{method}|picks"]
                    row = dict(strategy=strat, tf=tf, period=per, method=method, trades=len(tr),
                               net_R=float(tr[:, 2].mean()) if len(tr) else np.nan,
                               sum_R=float(tr[:, 2].sum()) if len(tr) else 0.0,
                               win_rate=float((tr[:, 2] > 0).mean()) if len(tr) else np.nan,
                               repicks=len(pk) - 1, distinct_combos=len(set(pk[:, 1].tolist())),
                               share_trades_on_default=float((tr[:, 3] == d).mean()) if len(tr) else np.nan,
                               default_net_R=float(base[:, 2].mean()), default_trades=len(base))
                    # paired week-block bootstrap of the difference in mean net R per trade
                    if method != "DEFAULT" and len(tr):
                        wk_a = C.week_of(S5.T0 + tr[:, 0].astype(np.int64) * S5.STEP)
                        wk_b = C.week_of(S5.T0 + base[:, 0].astype(np.int64) * S5.STEP)
                        w0 = min(wk_a.min(), wk_b.min())
                        W = max(wk_a.max(), wk_b.max()) - w0 + 1
                        na = np.bincount(wk_a - w0, minlength=W)
                        sa = np.bincount(wk_a - w0, weights=tr[:, 2], minlength=W)
                        nb_ = np.bincount(wk_b - w0, minlength=W)
                        sb = np.bincount(wk_b - w0, weights=base[:, 2], minlength=W)
                        ok = (na + nb_) > 0
                        na, sa, nb_, sb = na[ok], sa[ok], nb_[ok], sb[ok]
                        rng = np.random.default_rng(zlib.crc32(f"{strat}{tf}{per}{method}".encode()))
                        idx = rng.integers(0, len(na), size=(B, len(na)))
                        diff = sa[idx].sum(1) / na[idx].sum(1) - sb[idx].sum(1) / nb_[idx].sum(1)
                        row.update(diff_vs_default=row["net_R"] - row["default_net_R"],
                                   diff_ci_lo=float(np.percentile(diff, 2.5)),
                                   diff_ci_hi=float(np.percentile(diff, 97.5)))
                    rows.append(row)
    return pd.DataFrame(rows)


def accounts():
    parts = []
    for strat in C.STRATS:
        for tf in C.TFS:
            p = os.path.join(C.WORK, "accounts", f"{strat}_{tf}.csv")
            if os.path.exists(p):
                parts.append(pd.read_csv(p))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def main(only=None):
    C.check_prereg()
    picks = pd.read_csv(os.path.join(C.OUT, "picks.csv"))
    if only in (None, "detail"):
        D = load_detail()
        AT = dict(np.load(os.path.join(C.WORK, "agg_totals.npz")))
        PR, CR = pick_results(picks, D)
        PR.to_csv(os.path.join(C.OUT, "pick_results.csv"), index=False, float_format="%.5g")
        CR.to_csv(os.path.join(C.OUT, "crash_windows.csv"), index=False, float_format="%.5g")
        LK = luck(picks, D, PR)
        LK.to_csv(os.path.join(C.OUT, "luck.csv"), index=False, float_format="%.5g")
        NB = neighbours_test(picks, AT)
        NB.to_csv(os.path.join(C.OUT, "neighbours.csv"), index=False, float_format="%.5g")
        PS = pass_rule(picks, PR, LK, NB)
        PS.to_csv(os.path.join(C.OUT, "pass_rule.csv"), index=False, float_format="%.5g")
        C.log("pass rule: pooled main\n", PS[(PS.variant == "main")].to_string())
    if only in (None, "reopt"):
        RO = reopt()
        RO.to_csv(os.path.join(C.OUT, "reopt.csv"), index=False, float_format="%.5g")
        C.log(RO.to_string())
    if only in (None, "accounts"):
        AC = accounts()
        AC.to_csv(os.path.join(C.OUT, "accounts.csv"), index=False, float_format="%.5g")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
