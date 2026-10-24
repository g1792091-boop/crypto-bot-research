"""Step 2 of the combinations review: every combination type, picked on one part of the forward period and checked
on the other part, with luck filters (random picks of the same size, coin-flip constructions), market-drift removal
and the goal path (+500 % in 30 days).

usage (run from this folder, without -I):
    python3 cb_combos.py <rule bot export zip> <league export zip> <work folder used by cb_build.py> [out folder]
cb_build.py runs first if its tables are missing. Writes into the out folder (default: this folder):
    combos_all.csv        one row per combination tried (family, split, how picked, K, in-sample, out-of-sample,
                          luck percentiles, long/short, market-removed numbers)
    goal_path.csv         goal-path numbers for the best out-of-sample combinations
    default_vs_custom.csv rule bot (default numbers) vs league (custom numbers) per strategy, same window
    market.csv            coin moves per window part, coin-flip baselines per side
    combos_summary.json   numbers quoted in REPORT_KO.md
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

import cb_lib as L

from cb_core import *  # noqa: F401,F403  (Split, side_baselines, market_numbers, path_from_events, constants)
from cb_core import RNG, KS, N_RAND_SETS, MIN_PICK_TRADES, buckets_by_count, matched_draw, sig_side_base


# ============================================================================================== (a) portfolios
def coin_twin(acct: str, kind: str, pick: str) -> str:
    return pick + ("-fqc" if kind in ("fq", "fqt", "fqv") else "-ldc")


def acct_stats(tr: pd.DataFrame, mask) -> pd.DataFrame:
    g = tr[mask].groupby("account").wallet_ret
    st = pd.DataFrame({"n": g.size(), "G": g.apply(lambda x: float(np.prod(1 + x.values) - 1)),
                       "mean": g.mean(), "sd": g.std(ddof=1)})
    st["t"] = st["mean"] / st["sd"] * np.sqrt(st["n"])
    return st


def portfolio_family(trades, accounts, sig, splits_by_uni, rows, keep):
    for uni, splits in splits_by_uni.items():
        if uni == "rule":
            pool_acc = accounts[(accounts.bot == "rule") & accounts.kind.isin(["strategy", "ds200", "reel"])]
            coin_acc = accounts[(accounts.bot == "rule") & (accounts.kind == "random")
                                & ~accounts.account.str.endswith("@5m")]
        elif uni == "league":
            pool_acc = accounts[(accounts.bot == "league") & ~accounts.is_coin]
            coin_acc = accounts[(accounts.bot == "league") & accounts.is_coin]
        else:
            pool_acc = accounts[((accounts.bot == "rule") & accounts.kind.isin(["strategy", "ds200", "reel"]))
                                | ((accounts.bot == "league") & ~accounts.is_coin)]
            coin_acc = accounts[((accounts.bot == "rule") & (accounts.kind == "random")
                                 & ~accounts.account.str.endswith("@5m"))
                                | ((accounts.bot == "league") & accounts.is_coin)]
        info = accounts.set_index("account")
        for sp in splits:
            tr = trades[trades.account.isin(set(pool_acc.account) | set(coin_acc.account))]
            pm, tm = sp.masks(tr.entry_time, tr.exit_time)
            pst = acct_stats(tr, pm)
            tst = tr[tm]
            F = tst.groupby("account").wallet_ret.apply(lambda x: float(np.prod(1 + x.values)))
            base = {}
            for bot in ("rule", "league"):
                base.update(side_baselines(sig, trades, sp, bot))
            # coin baseline for "beat its coin flips" (pick part)
            rule_coin = {}
            for tf in ("15m", "30m", "1h", "4h"):
                cs = [f"RANDOM_{k}@{tf}" for k in (1, 2, 3)]
                rule_coin[tf] = float(np.mean([pst.G.get(c, 0.0) for c in cs]))

            def coin_base(a):
                r = info.loc[a]
                if r.bot == "rule":
                    return rule_coin.get(r.tf, 0.0) if r.tf in rule_coin else 0.0
                return float(pst.G.get(coin_twin(a, r.kind, r.pick), 0.0))

            elig = [a for a in pool_acc.account if pst.n.get(a, 0) >= MIN_PICK_TRADES]
            elig_coin = [a for a in coin_acc.account if pst.n.get(a, 0) >= MIN_PICK_TRADES]
            Fe = np.array([F.get(a, 1.0) for a in elig])
            Fc = np.array([F.get(a, 1.0) for a in elig_coin])
            sd_med = float(np.nanmedian([pst.sd.get(a, np.nan) for a in elig])) if elig else np.nan
            scores = {
                "pnl": {a: pst.G[a] for a in elig},
                "sharpe": {a: pst.t[a] for a in elig if np.isfinite(pst.t[a])},
                "beat_coin": {a: pst.G[a] - coin_base(a) for a in elig if pst.G[a] - coin_base(a) > 0},
            }
            coin_scores = {"pnl": {a: pst.G[a] for a in elig_coin},
                           "sharpe": {a: pst.t[a] for a in elig_coin if np.isfinite(pst.t[a])}}
            # random K-sets from the same eligible pool, weighted like the pick; and frequency-matched sets
            Fmap = {a: F.get(a, 1.0) for a in elig}
            sdv = {a: (pst.sd.get(a, np.nan) if np.isfinite(pst.sd.get(a, np.nan)) else sd_med) for a in elig}
            wrisk = {a: 1.0 / max(sdv[a], 1e-4) for a in elig}
            bucket = buckets_by_count({a: pst.n.get(a, 0) for a in elig}, {a: info.loc[a, "bot"] for a in elig})
            members_of = {}
            for a, b_ in bucket.items():
                members_of.setdefault(b_, []).append(a)

            def set_value(accs, wmode):
                w = np.array([1.0 if wmode == "eq" else wrisk[a] for a in accs])
                return float((w * np.array([Fmap[a] for a in accs])).sum() / w.sum())

            rand = {}
            for K in KS + ("all",):
                k = len(elig) if K == "all" else K
                if k == 0 or k > len(elig):
                    continue
                for wmode in ("eq", "risk"):
                    rand[(K, wmode)] = np.array([set_value([elig[i] for i in RNG.choice(len(elig), k, replace=False)],
                                                           wmode) for _ in range(N_RAND_SETS)])
            day_edges = sp.test_day_edges()
            for crit, sc in scores.items():
                order = sorted(sc, key=lambda a: (-sc[a], -pst.n.get(a, 0)))
                for K in KS:
                    if len(order) < K:
                        continue
                    picked = order[:K]
                    for wmode in ("eq", "risk"):
                        if wmode == "risk" and K == 1:
                            continue
                        if wmode == "eq":
                            wts = {a: 1.0 for a in picked}
                        else:
                            wts = {a: 1.0 / max(pst.sd.get(a, sd_med) if np.isfinite(pst.sd.get(a, np.nan)) else sd_med,
                                                1e-4) for a in picked}
                        evs = [(int(r.exit_time), r.account, float(r.wallet_ret))
                               for r in tst[tst.account.isin(picked)].itertuples()]
                        fin, mdd, daily = path_from_events(evs, sp.mid if sp.name == 'half' else sp.a, day_edges, wts)
                        tw = sum(wts.values())
                        fin_check = sum(wts[a] * F.get(a, 1.0) for a in picked) / tw
                        sub = tst[tst.account.isin(picked)]
                        mk = market_numbers(sub.wallet_ret, sub.side, sub.tf, sub.bot, base)
                        rd = rand.get((K, wmode))
                        rdm = np.array([set_value(matched_draw(picked, bucket, members_of), wmode)
                                        for _ in range(N_RAND_SETS)])
                        # same construction from coin-flip accounts
                        csc = coin_scores.get(crit)
                        coin_fin = np.nan
                        if csc is not None and len(csc) >= K:
                            co = sorted(csc, key=lambda a: -csc[a])[:K]
                            coin_fin = float(np.mean([F.get(a, 1.0) for a in co]))
                        is_val = float(np.mean([pst.G[a] for a in picked]))
                        row = dict(family="a_portfolio", universe=uni, split=sp.name, how=crit, weight=wmode, K=K,
                                   n_pool=len(elig), members=";".join(picked), is_growth=is_val,
                                   oos_growth=fin - 1.0, oos_growth_check=fin_check - 1.0, oos_mdd=mdd,
                                   oos_trades=len(sub), oos_days=sp.test_days(),
                                   oos_trades_per_day=len(sub) / sp.test_days(),
                                   oos_mean_trade=float(sub.wallet_ret.mean()) if len(sub) else np.nan,
                                   oos_mean_roe=float(sub.roe.mean()) if len(sub) else np.nan,
                                   rand_mean=float(rd.mean() - 1) if rd is not None else np.nan,
                                   rand_p=float((rd >= fin_check).mean()) if rd is not None else np.nan,
                                   rand_m_mean=float(rdm.mean() - 1), rand_p_m=float((rdm >= fin_check).mean()),
                                   coin_same_build=coin_fin - 1.0 if np.isfinite(coin_fin) else np.nan,
                                   **mk)
                        rows.append(row)
                        keep[len(rows) - 1] = {"daily": daily, "trades": sub.wallet_ret.tolist(),
                                               "sides": sub.side.tolist(), "tfs": sub.tf.tolist(),
                                               "bots": sub.bot.tolist(), "base": base, "kind": "portfolio",
                                               "K": K}
            # references: all eligible equal weight, coin pool, coin constructions alone
            for label, accs in (("all_eligible", elig), ("all_coin", elig_coin)):
                if not accs:
                    continue
                sub = tst[tst.account.isin(accs)]
                evs = [(int(r.exit_time), r.account, float(r.wallet_ret)) for r in sub.itertuples()]
                fin, mdd, daily = path_from_events(evs, sp.mid if sp.name == 'half' else sp.a, day_edges, {a: 1.0 for a in accs})
                mk = market_numbers(sub.wallet_ret, sub.side, sub.tf, sub.bot, base)
                rows.append(dict(family="a_portfolio", universe=uni, split=sp.name, how=label, weight="eq",
                                 K=len(accs), n_pool=len(accs), members="(all)", is_growth=np.nan,
                                 oos_growth=fin - 1.0, oos_growth_check=float(np.mean([F.get(a, 1.0) for a in accs])) - 1,
                                 oos_mdd=mdd, oos_trades=len(sub), oos_days=sp.test_days(),
                                 oos_trades_per_day=len(sub) / sp.test_days(),
                                 oos_mean_trade=float(sub.wallet_ret.mean()) if len(sub) else np.nan,
                                 oos_mean_roe=float(sub.roe.mean()) if len(sub) else np.nan,
                                 rand_mean=np.nan, rand_p=np.nan, coin_same_build=np.nan, **mk))
            for crit, csc in coin_scores.items():
                co_order = sorted(csc, key=lambda a: -csc[a])
                for K in KS:
                    if len(co_order) < K:
                        continue
                    co = co_order[:K]
                    sub = tst[tst.account.isin(co)]
                    mk = market_numbers(sub.wallet_ret, sub.side, sub.tf, sub.bot, base)
                    rdc = np.array([Fc[RNG.choice(len(elig_coin), K, replace=False)].mean()
                                    for _ in range(500)]) if len(elig_coin) >= K else None
                    fin = float(np.mean([F.get(a, 1.0) for a in co]))
                    rows.append(dict(family="a_portfolio_coin", universe=uni, split=sp.name, how=crit, weight="eq",
                                     K=K, n_pool=len(elig_coin), members=";".join(co),
                                     is_growth=float(np.mean([pst.G[a] for a in co])), oos_growth=fin - 1,
                                     oos_growth_check=fin - 1, oos_mdd=np.nan, oos_trades=len(sub),
                                     oos_days=sp.test_days(), oos_trades_per_day=len(sub) / sp.test_days(),
                                     oos_mean_trade=float(sub.wallet_ret.mean()) if len(sub) else np.nan,
                                     oos_mean_roe=float(sub.roe.mean()) if len(sub) else np.nan,
                                     rand_mean=float(rdc.mean() - 1) if rdc is not None else np.nan,
                                     rand_p=float((rdc >= fin).mean()) if rdc is not None else np.nan,
                                     coin_same_build=np.nan, **mk))
            # group picks: the best exit kind (league) / group x timeframe (rule) on the pick part
            grp_col = accounts.set_index("account")
            gkey = (lambda a: grp_col.loc[a, "kind"]) if uni == "league" else \
                   (lambda a: f"{grp_col.loc[a, 'bot']}:{grp_col.loc[a, 'kind']}@{grp_col.loc[a, 'tf']}")
            groups = {}
            for a in pool_acc.account:
                groups.setdefault(gkey(a), []).append(a)
            pick_val = {}
            for gname, accs in groups.items():
                vals = [pst.G.get(a, 0.0) for a in accs if pst.n.get(a, 0) > 0]
                if len(vals) >= 3:
                    pick_val[gname] = float(np.mean([pst.G.get(a, 0.0) for a in accs]))
            if pick_val:
                order = sorted(pick_val, key=lambda g: -pick_val[g])
                for rank_i, gname in enumerate(order[:3] + order[-1:]):
                    accs = groups[gname]
                    sub = tst[tst.account.isin(accs)]
                    fin = float(np.mean([F.get(a, 1.0) for a in accs]))
                    mk = market_numbers(sub.wallet_ret, sub.side, sub.tf, sub.bot, base)
                    oos_all = {g: float(np.mean([F.get(a, 1.0) for a in groups[g]])) for g in pick_val}
                    rank_oos = sorted(oos_all, key=lambda g: -oos_all[g]).index(gname) + 1
                    rows.append(dict(family="a_group", universe=uni, split=sp.name,
                                     how=f"group_rank{order.index(gname) + 1}_of{len(order)}", weight="eq",
                                     K=len(accs), n_pool=len(order), members=gname, is_growth=pick_val[gname],
                                     oos_growth=fin - 1, oos_growth_check=fin - 1, oos_mdd=np.nan,
                                     oos_trades=len(sub), oos_days=sp.test_days(),
                                     oos_trades_per_day=len(sub) / sp.test_days(),
                                     oos_mean_trade=float(sub.wallet_ret.mean()) if len(sub) else np.nan,
                                     oos_mean_roe=float(sub.roe.mean()) if len(sub) else np.nan,
                                     rand_mean=float(np.mean(list(oos_all.values())) - 1),
                                     rand_p=float(np.mean([v >= fin for v in oos_all.values()])),
                                     coin_same_build=np.nan, oos_rank=rank_oos, **mk))
            print(f"  portfolios {uni} {sp.name}: pool {len(elig)} coin {len(elig_coin)}", flush=True)


# ============================================================================================== (d) default vs custom
def default_vs_custom(trades, accounts, sig, sp_half: Split, rows, keep):
    """Rule bot account (default numbers, house exits, $5,000) vs the league accounts of the same strategy x timeframe
    (custom numbers; -ld = ladder + stop max 2 ATR, -e = the candidate's own exits; -ldc its coin twin), same window."""
    a, b, mid = sp_half.a, sp_half.b, sp_half.mid
    picks = sorted(accounts[(accounts.bot == "league")].pick.unique())
    out = []
    for p in picks:
        pool, rest = p.split("-", 1)
        strat, tf, _rank = rest.rsplit("-", 2)
        racc = f"{strat}@{tf}"
        rec = {"pick": p, "rule_account": racc, "strategy": strat, "tf": tf, "pool": pool}
        for lab, acc in (("default", racc), ("custom_ld", p + "-ld"), ("custom_e", p + "-e"), ("coin_ldc", p + "-ldc")):
            t = trades[(trades.account == acc) & (trades.entry_time >= a) & (trades.exit_time <= b)]
            for part, m in (("all", np.ones(len(t), bool)), ("h1", (t.entry_time < mid) & (t.exit_time < mid)),
                            ("h2", t.entry_time >= mid)):
                tt = t[np.asarray(m)]
                rec[f"{lab}_{part}_n"] = len(tt)
                rec[f"{lab}_{part}_growth"] = float(np.prod(1 + tt.wallet_ret.values) - 1) if len(tt) else 0.0
                rec[f"{lab}_{part}_mean_roe"] = float(tt.roe.mean()) if len(tt) else np.nan
                rec[f"{lab}_{part}_mean_wallet"] = float(tt.wallet_ret.mean()) if len(tt) else np.nan
        s = sig[(sig.strategy == strat) & (sig.tf == tf) & (sig.bar_close >= a) & (sig.bar_close < b)]
        rec["default_all_signals_n"] = int(np.isfinite(s.wallet_ret).sum())
        rec["default_all_signals_mean_roe"] = float(np.nanmean(s.roe)) if len(s) else np.nan
        rec["default_all_signals_mean_wallet"] = float(np.nanmean(s.wallet_ret)) if len(s) else np.nan
        out.append(rec)
    d = pd.DataFrame(out)
    base = {}
    for bot in ("rule", "league"):
        base.update(side_baselines(sig, trades, sp_half, bot))
    # portfolios: all default vs all custom, and "keep the side that won the first half" per strategy
    day_edges = sp_half.test_day_edges()
    sets = {"all_default": list(d.rule_account), "all_custom_ld": list(d.pick + "-ld"),
            "all_custom_e": list(d.pick + "-e"), "all_coin_ldc": list(d.pick + "-ldc")}
    win1 = np.where(d.custom_ld_h1_growth > d.default_h1_growth, d.pick + "-ld", d.rule_account)
    sets["first_half_winner"] = list(win1)
    for nm, accs in sets.items():
        t = trades[trades.account.isin(accs)]
        pm, tm = sp_half.masks(t.entry_time, t.exit_time)
        g1 = t[pm].groupby("account").wallet_ret.apply(lambda x: float(np.prod(1 + x.values)))
        sub = t[tm]
        evs = [(int(r.exit_time), r.account, float(r.wallet_ret)) for r in sub.itertuples()]
        fin, mdd, daily = path_from_events(evs, mid, day_edges, {x: 1.0 for x in accs})
        mk = market_numbers(sub.wallet_ret, sub.side, sub.tf, sub.bot, base)
        rows.append(dict(family="d_default_custom", universe="both", split="half", how=nm, weight="eq", K=len(accs),
                         n_pool=len(accs), members="(47 picks)",
                         is_growth=float(np.mean([g1.get(x, 1.0) for x in accs]) - 1), oos_growth=fin - 1,
                         oos_growth_check=fin - 1, oos_mdd=mdd, oos_trades=len(sub), oos_days=sp_half.test_days(),
                         oos_trades_per_day=len(sub) / sp_half.test_days(),
                         oos_mean_trade=float(sub.wallet_ret.mean()) if len(sub) else np.nan,
                         oos_mean_roe=float(sub.roe.mean()) if len(sub) else np.nan, rand_mean=np.nan, rand_p=np.nan,
                         coin_same_build=np.nan, **mk))
        keep[len(rows) - 1] = {"daily": daily, "trades": sub.wallet_ret.tolist(), "sides": sub.side.tolist(),
                               "tfs": sub.tf.tolist(), "bots": sub.bot.tolist(), "base": base, "kind": "portfolio",
                               "K": len(accs)}
    return d


# ============================================================================================== (e) league side restriction
def league_restrict(trades, splits, rows):
    lt = trades[(trades.bot == "league") & ~trades.is_coin]
    for sp in splits:
        pm, tm = sp.masks(lt.entry_time, lt.exit_time)
        P, T = lt[pm], lt[tm]
        base = side_baselines(None, trades, sp, "league")
        choice = {}
        for acc, g in P.groupby("account"):
            opts = {}
            if len(g) >= MIN_PICK_TRADES:
                opts["both"] = g.wallet_ret.mean()
            for sd, nm in ((1, "long"), (-1, "short")):
                gs = g[g.side == sd]
                if len(gs) >= MIN_PICK_TRADES:
                    opts[nm] = gs.wallet_ret.mean()
            if opts:
                choice[acc] = max(opts, key=opts.get)
        Tc = T[T.account.isin(choice)]
        ok = np.array([choice[a] == "both" or (choice[a] == "long" and s > 0) or (choice[a] == "short" and s < 0)
                       for a, s in zip(Tc.account, Tc.side)], bool)
        for nm, sub in (("unrestricted", Tc), ("per_account_side", Tc[ok]), ("all_short_only", T[T.side < 0]),
                        ("all_long_only", T[T.side > 0])):
            mk = market_numbers(sub.wallet_ret, sub.side, sub.tf, sub.bot, base)
            rows.append(dict(family="e_restrict_league", universe="league", split=sp.name, how=nm, weight="per_trade",
                             K=np.nan, n_pool=len(choice), members="", is_growth=np.nan, oos_growth=np.nan,
                             oos_growth_check=np.nan, oos_mdd=np.nan, oos_trades=len(sub), oos_days=sp.test_days(),
                             oos_trades_per_day=len(sub) / sp.test_days(),
                             oos_mean_trade=float(sub.wallet_ret.mean()) if len(sub) else np.nan,
                             oos_mean_roe=float(sub.roe.mean()) if len(sub) else np.nan,
                             oos_t=L.tstat(sub.wallet_ret), rand_mean=np.nan, rand_p=np.nan, coin_same_build=np.nan,
                             **mk))


# ============================================================================================== (4) goal path
def path_probs(path):
    hit6 = path >= GOAL_X
    first6 = np.where(hit6.any(1), hit6.argmax(1), 10 ** 9)
    out = {"p_final_x6": float((path[:, -1] >= GOAL_X).mean()), "p_touch_x6": float(hit6.any(1).mean()),
           "median_final": float(np.median(path[:, -1])), "p_final_loss": float((path[:, -1] < 1).mean())}
    for lvl, nm in ((0.5, "p_minus50_first"), (0.1, "p_minus90_first")):
        lo = path <= lvl
        firstlo = np.where(lo.any(1), lo.argmax(1), 10 ** 9)
        out[nm] = float(((firstlo < first6) & lo.any(1)).mean())
    return out


M_FULL = 10 / 3          # 30x with 100 % of the wallet as margin (now 30 %): the most the same exits allow
M_MAX = 50 / 9           # 50x with 100 % margin: beyond this the 2 ATR stop sits past liquidation for nearly every signal


def boot_trades_k(r, per_day, m, k_eff=1, n_paths=20000, days=GOAL_DAYS):
    """30-day paths from the out-of-sample trades: each day a Poisson number of trades (the observed rate), each drawn
    with replacement. k_eff > 1: separate wallets, one trade moves the total by r / k_eff (summed per day)."""
    r = np.asarray(r, float)
    if len(r) == 0 or per_day <= 0:
        return {}
    n = RNG.poisson(per_day, size=(n_paths, days))
    nmax = int(n.max())
    if nmax > 60:
        n_paths = max(2000, int(n_paths * 60 / nmax))
        n = n[:n_paths]
    if nmax == 0:
        return path_probs(np.ones((n_paths, days)))
    draws = r[RNG.integers(0, len(r), size=(n_paths, days, nmax))]
    live = np.arange(nmax)[None, None, :] < n[:, :, None]
    if k_eff == 1:
        step = np.where(live, np.maximum(1.0 + m * draws, 0.0), 1.0).prod(axis=2)
    else:
        step = np.maximum(1.0 + m * np.where(live, draws, 0.0).sum(axis=2) / k_eff, 0.0)
    return path_probs(np.cumprod(step, axis=1))


def log_growth_30(r, per_day, m, k_eff=1):
    x = 1.0 + m * np.asarray(r, float) / k_eff
    if (x <= 0).any():
        return -np.inf
    return float(GOAL_DAYS * per_day * np.mean(np.log(x)))


def goal_path(res: pd.DataFrame, keep: dict, cons: pd.DataFrame = None) -> pd.DataFrame:
    wallet = res[res.weight.isin(["eq", "risk", "one_position"]) & res.index.isin(list(keep))]
    cands = []
    for fam, g in wallet[wallet.split == "half"].groupby("family"):
        cands += list(g.sort_values("oos_growth", ascending=False).head(3).index)
    pm = wallet.rand_p_m.where(wallet.rand_p_m.notna(), wallet.rand_p)
    lucky = wallet[(wallet.split == "half") & (pm <= 0.05) & (wallet.oos_growth > 0)]
    cands += list(lucky.index)
    if cons is not None and len(cons):
        for _, c in cons[cons.all_positive].iterrows():
            m = wallet[(wallet.split == "half") & (wallet.family == c.family) & (wallet.universe == c.universe)
                       & (wallet.how == c.how) & (wallet.weight == c.weight) & (wallet.K == c.K)]
            cands += list(m.index)
    cands = list(dict.fromkeys(cands))
    out = []
    grid = np.concatenate([np.linspace(0.1, 3, 30), np.linspace(3.1, M_MAX, 25)])
    for i in cands:
        r = res.loc[i]
        k = keep[i]
        d = np.asarray(k["daily"], float)
        tr = np.asarray(k["trades"], float)
        lam = float(r.oos_trades_per_day)
        k_eff = int(k["K"]) if k["kind"] == "portfolio" else 1
        n = len(tr)
        se = tr.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
        rec = {"row": int(i), "family": r.family, "universe": r.universe, "split": r.split, "how": r.how, "K": r.K,
               "weight": r.weight, "members": r.members, "oos_growth": r.oos_growth, "oos_days": r.oos_days,
               "n_days": len(d), "oos_trades": n, "trades_per_day": lam, "k_eff": k_eff, "mean_trade": r.oos_mean_trade,
               "mean_trade_lo90": float(tr.mean() - 1.645 * se) if n > 1 else np.nan,
               "mean_trade_hi90": float(tr.mean() + 1.645 * se) if n > 1 else np.nan,
               "worst_trade": float(tr.min()) if n else np.nan, "losing_trades": int((tr < 0).sum()),
               "daily_mean": float(d.mean()) if len(d) else np.nan, "daily_min": float(d.min()) if len(d) else np.nan,
               "daily_max": float(d.max()) if len(d) else np.nan, "days_up": int((d > 0).sum()),
               "rand_p": r.rand_p, "rand_p_m": r.get("rand_p_m", np.nan), "flip_p": r.get("flip_p", np.nan),
               "excess": r.excess, "neutral": r.neutral, "n_long": r.n_long, "n_short": r.n_short}
        if n >= 2 and lam > 0:
            g = np.array([log_growth_30(tr, lam, m, k_eff) for m in grid])
            rec["x30_at_now"] = float(np.exp(log_growth_30(tr, lam, 1.0, k_eff)))
            j = int(np.argmax(g))
            rec["m_best"] = float(grid[j])
            rec["x30_at_best"] = float(np.exp(g[j])) if np.isfinite(g[j]) else 0.0
            reach = grid[g >= np.log(GOAL_X)]
            rec["m_needed"] = float(reach.min()) if len(reach) else np.nan
            for tag, m in (("now", 1.0), ("full", M_FULL), ("max50x", M_MAX)):
                for kk, v in boot_trades_k(tr, lam, m, k_eff).items():
                    rec[f"{tag}_{kk}"] = v
            # market-neutral: each trade minus its side's drift (side baseline - average of both side baselines)
            base = k["base"]
            adj = []
            for x, sd, tf, bo in zip(tr, k["sides"], k["tfs"], k["bots"]):
                key = (bo, tf if bo == "rule" else "*")
                bl, bs = base.get(key + (1,), np.nan), base.get(key + (-1,), np.nan)
                drift = (bl if sd > 0 else bs) - np.nanmean([bl, bs]) if np.isfinite(bl) and np.isfinite(bs) else 0.0
                adj.append(x - drift)
            adj = np.array(adj)
            rec["neutral_mean_trade"] = float(adj.mean())
            rec["neutral_x30_at_now"] = float(np.exp(log_growth_30(adj, lam, 1.0, k_eff)))
            for tag, m in (("nnow", 1.0), ("nfull", M_FULL)):
                for kk, v in boot_trades_k(adj, lam, m, k_eff).items():
                    rec[f"{tag}_{kk}"] = v
        out.append(rec)
    return pd.DataFrame(out)


def goal_path_pooled(res: pd.DataFrame, keep: dict, gp: pd.DataFrame) -> pd.DataFrame:
    """The same construction on every cut it was tested on (half, even days, odd days, and the league window for the
    rule-bot signal families), all its out-of-sample trades pooled: a less lucky goal path than its best cut alone."""
    r = res[res.index.isin(list(keep))].copy()
    r["ugroup"] = r.universe.replace({"rule@league_window": "rule"})
    key = ["family", "ugroup", "how", "weight", "K"]
    want = set()
    for i in gp.row:
        x = r.loc[i]
        want.add(tuple(x[k] for k in key))
    out = []
    grid = np.concatenate([np.linspace(0.1, 3, 30), np.linspace(3.1, M_MAX, 25)])
    for kk, g in r.groupby(key, dropna=False):
        if kk not in want:
            continue
        tr = np.concatenate([np.asarray(keep[i]["trades"], float) for i in g.index])
        days = float(g.oos_days.sum())
        lam = len(tr) / days if days else 0.0
        k_eff = int(keep[g.index[0]]["K"]) if keep[g.index[0]]["kind"] == "portfolio" else 1
        rec = dict(zip(key, kk))
        rec.update({"cuts": ";".join(f"{u}:{sp}" for u, sp in zip(g.universe, g.split)),
                    "oos_by_cut": ";".join(f"{v:+.3f}" for v in g.oos_growth), "n_cuts": len(g),
                    "cuts_positive": int((g.oos_growth > 0).sum()), "days": days, "trades": len(tr),
                    "trades_per_day": lam, "k_eff": k_eff})
        if len(tr) >= 2 and lam > 0:
            se = tr.std(ddof=1) / np.sqrt(len(tr))
            rec.update({"mean_trade": float(tr.mean()), "mean_trade_lo90": float(tr.mean() - 1.645 * se),
                        "mean_trade_hi90": float(tr.mean() + 1.645 * se), "losing_share": float((tr < 0).mean()),
                        "x30_at_now": float(np.exp(log_growth_30(tr, lam, 1.0, k_eff)))})
            g30 = np.array([log_growth_30(tr, lam, m, k_eff) for m in grid])
            reach = grid[g30 >= np.log(GOAL_X)]
            rec["m_needed"] = float(reach.min()) if len(reach) else np.nan
            j = int(np.argmax(g30))
            rec["m_best"], rec["x30_at_best"] = float(grid[j]), float(np.exp(g30[j])) if np.isfinite(g30[j]) else 0.0
            for tag, m in (("now", 1.0), ("full", M_FULL), ("max50x", M_MAX)):
                for k2, v in boot_trades_k(tr, lam, m, k_eff).items():
                    rec[f"{tag}_{k2}"] = v
            # drift removed (each trade minus its side's market drift in its own cut)
            adj = np.concatenate([neutral_trades(keep[i]) for i in g.index])
            rec["neutral_mean_trade"] = float(adj.mean())
            rec["neutral_x30_at_now"] = float(np.exp(log_growth_30(adj, lam, 1.0, k_eff)))
            for tag, m in (("nnow", 1.0), ("nfull", M_FULL), ("nmax50x", M_MAX)):
                for k2, v in boot_trades_k(adj, lam, m, k_eff).items():
                    rec[f"{tag}_{k2}"] = v
        out.append(rec)
    return pd.DataFrame(out)


def neutral_trades(k: dict) -> np.ndarray:
    base = k["base"]
    adj = []
    for x, sd, tf, bo in zip(k["trades"], k["sides"], k["tfs"], k["bots"]):
        key = (bo, tf if bo == "rule" else "*")
        bl, bs = base.get(key + (1,), np.nan), base.get(key + (-1,), np.nan)
        drift = (bl if sd > 0 else bs) - np.nanmean([bl, bs]) if np.isfinite(bl) and np.isfinite(bs) else 0.0
        adj.append(x - drift)
    return np.asarray(adj, float)


# ============================================================================================== market table
def market_table(bars: L.Bars, splits_by_uni, sig, trades) -> pd.DataFrame:
    out = []
    seen = set()
    for uni, splits in splits_by_uni.items():
        for sp in splits:
            if (sp.name, sp.a) in seen:
                continue
            seen.add((sp.name, sp.a))
            parts = [("pick", sp.a, sp.mid), ("test", sp.mid, sp.b)] if sp.name == "half" else [("all", sp.a, sp.b)]
            for part, lo, hi in parts:
                mv = {c: bars.close_at(c, hi) / bars.close_at(c, lo) - 1 for c in L.SYMS}
                rec = {"window": "rule" if sp.a < 1791800000000 else "league", "split": sp.name, "part": part,
                       "from_kst": L.kst(lo), "to_kst": L.kst(hi), "days": (hi - lo) / L.DAY_MS,
                       "avg6_move": float(np.mean(list(mv.values()))), **{f"move_{c[:-4]}": v for c, v in mv.items()}}
                out.append(rec)
            if sp.name == "half":
                b = {}
                b.update(side_baselines(sig, trades, sp, "rule"))
                b.update(side_baselines(sig, trades, sp, "league"))
                for (bot, tf, sd), v in b.items():
                    out.append({"window": "rule" if sp.a < 1791800000000 else "league", "split": "half",
                                "part": "test_baseline", "bot": bot, "tf": tf, "side": sd, "coin_flip_mean_wallet": v})
    return pd.DataFrame(out)


# ============================================================================================== persistence
def persistence(sig, trades, splits_by_uni) -> pd.DataFrame:
    """Does being good in the pick part predict being good in the test part? Rank correlation across strategies
    (rule bot replayed signals, market-removed per signal) and across accounts (real trades, growth)."""
    from scipy.stats import spearmanr
    out = []
    S = sig[sig.kind.isin(["strategy", "ds200"])].copy()
    S["key"] = S.strategy + "@" + S.tf
    for sp in splits_by_uni["rule"]:
        pm, tm = sp.masks(S.bar_close, S.exit_time.astype(float).fillna(sp.b))
        pm_all, tm_all = sp.masks(sig.bar_close, sig.exit_time.astype(float).fillna(sp.b))
        bp, bt = sig_side_base(sig, pm_all), sig_side_base(sig, tm_all)
        for unit in ("strategy", "strategy_side"):
            stats_ = {}
            for part, m, b in (("pick", pm, bp), ("test", tm, bt)):
                X = S[m & np.isfinite(S.wallet_ret)]
                ex = X.wallet_ret.to_numpy() - np.array([b.get(("rule", tf, sd), np.nan) for tf, sd in zip(X.tf, X.side)])
                X = X.assign(ex=ex, u=X.key if unit == "strategy" else X.key + np.where(X.side > 0, ":L", ":S"))
                g = X.groupby("u")
                stats_[part] = pd.DataFrame({"n": g.size(), "mean": g.wallet_ret.mean(), "ex": g.ex.mean(),
                                             "t": g.ex.mean() / g.ex.std(ddof=1) * np.sqrt(g.size())})
            j = stats_["pick"].join(stats_["test"], lsuffix="_p", rsuffix="_t", how="inner")
            j = j[(j.n_p >= 5) & (j.n_t >= 5)]
            top = j[j.ex_p >= j.ex_p.quantile(0.9)]
            jj = j[(j.n_p >= 10) & (j.n_t >= 10)]
            joint = {}
            for th in (1.5, 2.0):
                a_, b_ = (jj.t_p > th), (jj.t_t > th)
                joint[f"units_n10"] = len(jj)
                joint[f"t{th}_pick"] = int(a_.sum())
                joint[f"t{th}_test"] = int(b_.sum())
                joint[f"t{th}_both"] = int((a_ & b_).sum())
                joint[f"t{th}_both_expected_if_independent"] = float(a_.mean() * b_.mean() * len(jj)) if len(jj) else np.nan
            out.append({"level": f"rule_signals_{unit}", "split": sp.name, "n_units": len(j), **joint,
                        "rho_raw": spearmanr(j.mean_p, j.mean_t)[0], "rho_market_removed": spearmanr(j.ex_p, j.ex_t)[0],
                        "top10pct_test_excess": float(top.ex_t.mean()), "all_test_excess": float(j.ex_t.mean()),
                        "top10pct_test_positive_share": float((top.ex_t > 0).mean())})
    for uni, bot, coin in (("rule", "rule", False), ("league", "league", False)):
        tr = trades[(trades.bot == bot) & (trades.is_coin == coin)]
        if bot == "rule":
            tr = tr[tr.kind.isin(["strategy", "ds200"])]
        for sp in splits_by_uni[uni]:
            pm, tm = sp.masks(tr.entry_time, tr.exit_time)
            gp = tr[pm].groupby("account").wallet_ret.agg(["size", "mean"])
            gt = tr[tm].groupby("account").wallet_ret.agg(["size", "mean"])
            j = gp.join(gt, lsuffix="_p", rsuffix="_t", how="inner")
            j = j[(j.size_p >= 3) & (j.size_t >= 3)]
            top = j[j.mean_p >= j.mean_p.quantile(0.9)]
            out.append({"level": f"{bot}_accounts_mean_trade", "split": sp.name, "n_units": len(j),
                        "rho_raw": spearmanr(j.mean_p, j.mean_t)[0], "rho_market_removed": np.nan,
                        "top10pct_test_excess": float(top.mean_t.mean()), "all_test_excess": float(j.mean_t.mean()),
                        "top10pct_test_positive_share": float((top.mean_t > 0).mean())})
    return pd.DataFrame(out)


# ============================================================================================== consistency
def consistency(res: pd.DataFrame) -> pd.DataFrame:
    """The same construction on the three cuts (half, even days, odd days): does it hold up on all three?"""
    w = res[res.weight.isin(["eq", "risk", "one_position"]) & res.universe.isin(["rule", "league", "both"])].copy()
    w["pm"] = w.rand_p_m.where(w.rand_p_m.notna(), w.rand_p)
    key = ["family", "universe", "how", "weight", "K"]
    out = []
    for k, g in w.groupby(key, dropna=False):
        g = g.set_index("split")
        if not {"half", "altE", "altO"} <= set(g.index):
            continue
        rec = dict(zip(key, k))
        for sp in ("half", "altE", "altO"):
            rec[f"oos_{sp}"] = g.loc[sp, "oos_growth"]
            rec[f"trades_{sp}"] = g.loc[sp, "oos_trades"]
            rec[f"p_{sp}"] = g.loc[sp, "pm"]
            rec[f"excess_{sp}"] = g.loc[sp, "excess"]
        rec["all_positive"] = all(rec[f"oos_{sp}"] > 0 for sp in ("half", "altE", "altO"))
        rec["all_beat_random_10pct"] = all(rec[f"p_{sp}"] <= 0.10 for sp in ("half", "altE", "altO"))
        rec["all_excess_positive"] = all(rec[f"excess_{sp}"] > 0 for sp in ("half", "altE", "altO"))
        out.append(rec)
    return pd.DataFrame(out)


def summary(res: pd.DataFrame, cons: pd.DataFrame, gp: pd.DataFrame, meta: dict) -> dict:
    w = res[res.weight.isin(["eq", "risk", "one_position"])].copy()
    w["pm"] = w.rand_p_m.where(w.rand_p_m.notna(), w.rand_p)
    out = {"rows_total": int(len(res)), "wallet_rows": int(len(w)), "by_split": {}}
    for sp, g in w.groupby("split"):
        g2 = g[g.pm.notna()]
        out["by_split"][sp] = {"rows": int(len(g)), "oos_positive": int((g.oos_growth > 0).sum()),
                               "with_luck_test": int(len(g2)), "beat_random_p05": int((g2.pm <= 0.05).sum()),
                               "beat_random_p05_and_positive": int(((g2.pm <= 0.05) & (g2.oos_growth > 0)).sum()),
                               "expected_by_chance_p05": round(0.05 * len(g2), 1),
                               "excess_positive": int((g.excess > 0).sum())}
    out["consistency"] = {"constructions": int(len(cons)), "positive_all_three": int(cons.all_positive.sum()),
                          "beat_random_all_three": int(cons.all_beat_random_10pct.sum()),
                          "positive_and_beat_all_three": int((cons.all_positive & cons.all_beat_random_10pct).sum()),
                          "excess_positive_all_three": int(cons.all_excess_positive.sum())}
    out["goal_rows"] = int(len(gp))
    if "now_p_touch_x6" in gp:
        out["goal_max_p_touch_x6_now"] = float(gp.now_p_touch_x6.max())
        out["goal_max_p_touch_x6_full"] = float(gp.full_p_touch_x6.max())
    out["meta"] = {k: meta[k] for k in ("rule_run_started", "rule_bars_end", "league_start", "league_done",
                                        "n_trades", "n_accounts", "open_positions_excluded", "replay_check")}
    return out


# ============================================================================================== main
def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    rule_zip, league_zip, work = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/")
    out = (sys.argv[4] if len(sys.argv) > 4 else L.HERE).rstrip("/")
    if not all(os.path.exists(f"{out}/{f}") for f in ("trades_all.csv", "signals_sim.csv", "build_meta.json")):
        subprocess.run([sys.executable, os.path.join(L.HERE, "cb_build.py"), rule_zip, league_zip, work, out],
                       check=True, cwd=L.HERE)
    import cb_sig
    meta = json.load(open(out + "/build_meta.json"))
    trades = pd.read_csv(out + "/trades_all.csv")
    accounts = pd.read_csv(out + "/accounts_all.csv")
    sig = pd.read_csv(out + "/signals_sim.csv")
    sig["f_side"] = -sig.side
    bars = L.Bars(pd.read_csv(work + "/rule/current/live_bars.csv",
                              usecols=["ts", "symbol", "open", "high", "low", "close", "close_time"]))
    ra, rb = meta["rule_run_started"], meta["rule_bars_end"]
    la, lb = meta["league_start"], meta["league_done"]
    splits_R = [Split(n, ra, rb) for n in ("half", "altE", "altO")]
    splits_L = [Split(n, la, lb) for n in ("half", "altE", "altO")]
    rows, keep = [], {}
    print("(a) portfolios", flush=True)
    portfolio_family(trades, accounts, sig, {"rule": splits_R, "league": splits_L, "both": splits_L}, rows, keep)
    print("(b, c, e) signal families", flush=True)
    S = cb_sig.prep(sig, rb)
    S["f_side"] = -S.side
    S = cb_sig.add_features(S, bars)
    cb_sig.signal_families(sig, trades, S, splits_R, rows, keep)
    print("(c, e) same on the league window", flush=True)
    n0 = len(rows)
    cb_sig.signal_families(sig, trades, S, [Split("half", la, lb)], rows, keep)
    for i in range(n0, len(rows)):
        rows[i]["universe"] = "rule@league_window"
    print("(d) default vs custom", flush=True)
    dvc = default_vs_custom(trades, accounts, sig, Split("half", la, lb), rows, keep)
    dvc.to_csv(out + "/default_vs_custom.csv", index=False, float_format="%.6g")
    print("(e) league side restriction", flush=True)
    league_restrict(trades, splits_L, rows)
    res = pd.DataFrame(rows)
    res.index.name = "row"
    pers = persistence(sig, trades, {"rule": splits_R, "league": splits_L})
    pers.to_csv(out + "/persistence.csv", index=False, float_format="%.6g")
    print(pers.round(3).to_string(), flush=True)
    w = res[res.weight.isin(["eq", "risk", "one_position"])].copy()
    w["pm"] = w.rand_p_m.where(w.rand_p_m.notna(), w.rand_p)
    fo = w.groupby(["family", "universe", "split"]).agg(
        variants=("oos_growth", "size"), median_oos=("oos_growth", "median"),
        share_positive=("oos_growth", lambda v: float((v > 0).mean())),
        share_beat_random_p05=("pm", lambda v: float((v <= 0.05).mean())), best_oos=("oos_growth", "max"),
        worst_oos=("oos_growth", "min"), median_random_sets=("rand_mean", "median"),
        median_excess=("excess", "median")).reset_index()
    fo.to_csv(out + "/family_overview.csv", index=False, float_format="%.6g")
    cons = consistency(res)
    cons.to_csv(out + "/combos_consistency.csv", index=False, float_format="%.6g")
    print("(4) goal path", flush=True)
    gp = goal_path(res, keep, cons)
    gp.to_csv(out + "/goal_path.csv", index=False, float_format="%.6g")
    gpp = goal_path_pooled(res, keep, gp)
    gpp.to_csv(out + "/goal_path_pooled.csv", index=False, float_format="%.6g")
    res.to_csv(out + "/combos_all.csv", float_format="%.6g")
    mt = market_table(bars, {"rule": splits_R, "league": splits_L}, sig, trades)
    mt.to_csv(out + "/market.csv", index=False, float_format="%.6g")
    # daily returns of the goal-path rows (for the report)
    json.dump({str(int(i)): {"daily": keep[int(i)]["daily"]} for i in gp.row}, open(out + "/goal_daily.json", "w"))
    json.dump(summary(res, cons, gp, meta), open(out + "/combos_summary.json", "w"), indent=1, default=float)
    print("rows", len(res), "goal rows", len(gp))


if __name__ == "__main__":
    main()
