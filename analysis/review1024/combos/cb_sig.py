"""Per-signal families of the combinations review, on the rule bot's replayed signals (signals_sim.csv): one-position
merged bots, agreement filters (2+ strategies), fading losers, side / coin restrictions. (Agreement with the
higher-timeframe trend is left to analysis/review1024/roles/.)
Every signal of every strategy is used (taken by its account or not), with the house exits and sizing."""
from __future__ import annotations

import numpy as np
import pandas as pd

import cb_lib as L
from cb_core import (KS, MIN_PICK_SIGNALS, N_FLIP, N_RAND_MERGED, OWNERS6, RNG, Merged, Split, buckets_by_count,
                     daily_from_trades, market_numbers, matched_draw, side_baselines, sig_side_base)

N_MATCHED = 500


def prep(sig: pd.DataFrame, bars_end: int) -> pd.DataFrame:
    S = sig[sig.kind.isin(["strategy", "ds200"])].copy()
    S["exit_f"] = S.exit_time.astype(float).fillna(float(bars_end))
    S["tfo"] = S.tf.map(L.TF_ORDER)
    S["key"] = S.strategy + "@" + S.tf
    S = S.sort_values(["bar_close", "tfo", "coin"], ascending=[True, False, True]).reset_index(drop=True)
    return S


# ---------------------------------------------------------------------------------------------- features
def add_features(S: pd.DataFrame, bars: L.Bars) -> pd.DataFrame:
    """Agreement counts at each signal's bar close: distinct strategies with a signal on the same coin and side (and on
    the opposite side) within the last 1 h / 4 h, the signal itself included."""
    S = S.copy()
    strat_code = {s: i for i, s in enumerate(sorted(S.strategy.unique()))}
    code = S.strategy.map(strat_code).to_numpy()
    bc = S.bar_close.to_numpy(np.int64)
    for W, wn in ((3_600_000, "1h"), (4 * 3_600_000, "4h")):
        same = np.zeros(len(S), int)
        opp = np.zeros(len(S), int)
        for coin, gc in S.groupby("coin"):
            for sd in (1, -1):
                q = gc.index[gc.side == sd].to_numpy()
                ref_same = q
                ref_opp = gc.index[gc.side == -sd].to_numpy()
                for refs, out in ((ref_same, same), (ref_opp, opp)):
                    if len(refs) == 0:
                        continue
                    rt = bc[refs]
                    rc = code[refs]
                    lo = np.searchsorted(rt, bc[q] - W, side="left")
                    hi = np.searchsorted(rt, bc[q], side="right")
                    for qi, a, b in zip(q, lo, hi):
                        out[qi] = len(set(rc[a:b].tolist()))
        S[f"agree_{wn}"] = same
        S[f"opp_{wn}"] = opp
    return S


def agree_within(sub: pd.DataFrame, W: int) -> np.ndarray:
    """For each signal of ``sub``: distinct strategies of ``sub`` with a signal on the same coin and side within the
    last W ms (itself included)."""
    out = np.zeros(len(sub), int)
    pos = {ix: i for i, ix in enumerate(sub.index)}
    for (_c, _s), g in sub.groupby(["coin", "side"]):
        t = g.bar_close.to_numpy(np.int64)
        st = g.strategy.to_numpy()
        lo = np.searchsorted(t, t - W, side="left")
        for j, (a, ix) in enumerate(zip(lo, g.index)):
            out[pos[ix]] = len(set(st[a:j + 1].tolist()))
    return out


# ---------------------------------------------------------------------------------------------- helpers
def pick_stats(P: pd.DataFrame, base_pick: dict) -> pd.DataFrame:
    P = P[np.isfinite(P.wallet_ret)]
    b = np.array([base_pick.get(("rule", tf, sd), np.nan) for tf, sd in zip(P.tf, P.side)])
    P = P.assign(ex=P.wallet_ret.to_numpy() - b)
    g = P.groupby("key")
    st = pd.DataFrame({"n": g.size(), "mean": g.wallet_ret.mean(), "sd": g.wallet_ret.std(ddof=1),
                       "excess": g.ex.mean()})
    st["t"] = st["mean"] / st["sd"] * np.sqrt(st["n"])
    return st


def ordered(Tsub: pd.DataFrame, rank: dict) -> np.ndarray:
    x = Tsub.assign(rk=Tsub.key.map(rank).fillna(999))
    x = x.sort_values(["bar_close", "tfo", "rk", "coin"], ascending=[True, False, True, True])
    return x.index.to_numpy()


def row_merged(fam, sp, how, K, n_pool, members, eng, idx_pick, idx_test, base, day_edges, rand=None, flip_runs=True,
               flip_all=False, extra=None, rand_m=None):
    flip_t = np.ones(len(idx_test), bool) if flip_all else None
    flip_p_ = np.ones(len(idx_pick), bool) if flip_all else None
    Wp = eng.run(idx_pick, flip_p_)[0] if len(idx_pick) else np.nan
    W, rows_, rets, sides, exits = eng.run(idx_test, flip_t)
    t0 = sp.mid if sp.name == "half" else sp.a
    mdd, daily = daily_from_trades(exits, rets, t0, day_edges)
    tfs = eng.S.tf.to_numpy()[rows_] if rows_ else []
    mk = market_numbers(rets, sides, tfs, ["rule"] * len(rets), base)
    roe = eng.S.f_roe.to_numpy()[rows_] if flip_all else eng.S.roe.to_numpy()[rows_]
    fl = None
    if flip_runs and len(idx_test):
        fl = np.array([eng.run(idx_test, RNG.random(len(idx_test)) < 0.5)[0] for _ in range(N_FLIP)])
    r = dict(family=fam, universe="rule", split=sp.name, how=how, weight="one_position", K=K, n_pool=n_pool,
             members=members, is_growth=Wp - 1 if np.isfinite(Wp) else np.nan, oos_growth=W - 1, oos_growth_check=W - 1,
             oos_mdd=mdd, oos_trades=len(rets), oos_days=sp.test_days(), oos_trades_per_day=len(rets) / sp.test_days(),
             oos_mean_trade=float(np.mean(rets)) if rets else np.nan,
             oos_mean_roe=float(np.mean(roe)) if len(roe) else np.nan,
             rand_mean=float(rand.mean() - 1) if rand is not None else np.nan,
             rand_p=float((rand >= W).mean()) if rand is not None else np.nan,
             rand_m_mean=float(rand_m.mean() - 1) if rand_m is not None else np.nan,
             rand_p_m=float((rand_m >= W).mean()) if rand_m is not None else np.nan,
             coin_same_build=float(fl.mean() - 1) if fl is not None else np.nan,
             flip_p=float((fl >= W).mean()) if fl is not None else np.nan, **mk)
    if extra:
        r.update(extra)
    keep = {"daily": daily, "trades": list(rets), "sides": list(sides), "tfs": list(tfs), "bots": ["rule"] * len(rets),
            "base": base, "kind": "merged", "K": K}
    return r, keep


def per_signal_row(fam, sp, how, sub_test, sub_pick, base, n_pool=np.nan, members="", ret_col="wallet_ret",
                   side_col="side", extra=None):
    r = sub_test[ret_col].to_numpy(float)
    ok = np.isfinite(r)
    sides = sub_test[side_col].to_numpy(int)[ok]
    mk = market_numbers(r[ok], sides, sub_test.tf.to_numpy()[ok], ["rule"] * int(ok.sum()), base)
    rp = sub_pick[ret_col].to_numpy(float)
    roe_col = "f_roe" if ret_col.startswith("f_") else "roe"
    out = dict(family=fam, universe="rule", split=sp.name, how=how, weight="per_signal", K=np.nan, n_pool=n_pool,
               members=members, is_growth=np.nan, is_mean_trade=float(np.nanmean(rp)) if np.isfinite(rp).any() else np.nan,
               oos_growth=np.nan, oos_growth_check=np.nan, oos_mdd=np.nan, oos_trades=int(ok.sum()),
               oos_days=sp.test_days(), oos_trades_per_day=int(ok.sum()) / sp.test_days(),
               oos_mean_trade=float(r[ok].mean()) if ok.any() else np.nan,
               oos_mean_roe=float(np.nanmean(sub_test[roe_col])) if ok.any() else np.nan,
               oos_t=L.tstat(r[ok]), rand_mean=np.nan, rand_p=np.nan, coin_same_build=np.nan, **mk)
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------------------------- the families
def signal_families(sig, trades, S, splits, rows, keep):
    eng = Merged(S)
    for sp in splits:
        pm, tm = sp.masks(S.bar_close, S.exit_f)
        P, T = S[pm], S[tm]
        base = side_baselines(sig, trades, sp, "rule")
        pm_all, _ = sp.masks(sig.bar_close, sig.exit_time.astype(float).fillna(sp.b))
        base_pick = sig_side_base(sig, pm_all)
        st = pick_stats(P, base_pick)
        elig = st[st.n >= MIN_PICK_SIGNALS]
        keys = list(elig.index)
        day_edges = sp.test_day_edges()
        # actual account growth in the pick part (rule bot trades)
        rt = trades[trades.bot == "rule"]
        pmt, _ = sp.masks(rt.entry_time, rt.exit_time)
        acct_g = rt[pmt].groupby("account").wallet_ret.apply(lambda x: float(np.prod(1 + x.values) - 1))
        # test-part arrays for random draws
        T_idx = T.index.to_numpy()
        T_key = T.key.to_numpy()
        P_idx = P.index.to_numpy()
        P_key = P.key.to_numpy()
        rand_cache = {}

        def rand_dist(K, flip_all=False):
            if (K, flip_all) in rand_cache:
                return rand_cache[(K, flip_all)]
            if len(keys) < K:
                return None
            out = []
            for _ in range(N_RAND_MERGED):
                ch = RNG.choice(len(keys), K, replace=False)
                idx = T_idx[np.isin(T_key, [keys[i] for i in ch])]
                fl = np.ones(len(idx), bool) if flip_all else None
                out.append(eng.run(idx, fl)[0])
            rand_cache[(K, flip_all)] = np.array(out)
            return rand_cache[(K, flip_all)]

        def matched_dist(mem, pool_counts, X_idx, X_key, flip_all=False, n=N_MATCHED):
            """Random sets drawn from the same signal-count quintiles as ``mem`` (frequency-matched luck filter)."""
            bucket = buckets_by_count(pool_counts)
            members_of = {}
            for k_, b_ in bucket.items():
                members_of.setdefault(b_, []).append(k_)
            out = []
            for _ in range(n):
                ch = matched_draw(mem, bucket, members_of)
                idx = X_idx[np.isin(X_key, ch)]
                out.append(eng.run(idx, np.ones(len(idx), bool) if flip_all else None)[0])
            return np.array(out)

        cnt_all = {k: int(elig.n[k]) for k in keys}

        crits = {
            "sig_mean": elig["mean"],
            "sig_t": elig["t"].dropna(),
            "acct_pnl": pd.Series({k: acct_g.get(k, np.nan) for k in keys}).dropna(),
            "excess": elig["excess"],
        }
        # ---- (b) one-position merged bots of the top-K strategies
        for crit, sc in crits.items():
            order = list(sc.sort_values(ascending=False).index)
            for K in KS:
                if len(order) < K:
                    continue
                mem = order[:K]
                rank = {k: i for i, k in enumerate(mem)}
                r, kp = row_merged("b_merged", sp, crit, K, len(keys), ";".join(mem), eng,
                                   ordered(P[P.key.isin(mem)], rank), ordered(T[T.key.isin(mem)], rank), base,
                                   day_edges, rand=rand_dist(K), rand_m=matched_dist(mem, cnt_all, T_idx, T_key))
                rows.append(r)
                keep[len(rows) - 1] = kp
        # all eligible strategies in one wallet, and the owners' combo members (fixed set, not picked here)
        for how, mem in (("all_eligible", keys), ("owners6", [f"{s}@{tf}" for s, tf in OWNERS6])):
            rank = {k: i for i, k in enumerate(mem)}
            r, kp = row_merged("b_merged", sp, how, len(mem), len(keys), ";".join(mem) if how == "owners6" else "(all)",
                               eng, ordered(P[P.key.isin(mem)], rank), ordered(T[T.key.isin(mem)], rank), base,
                               day_edges, rand=rand_dist(len(mem)) if len(mem) <= 10 else None,
                               rand_m=matched_dist([m for m in mem if m in cnt_all], cnt_all, T_idx, T_key)
                               if how == "owners6" else None)
            rows.append(r)
            keep[len(rows) - 1] = kp
        # coin-flip accounts' signals as one merged bot (RANDOM_1..3, 15m-4h)
        Rsig = sig[sig.kind == "random"].copy()
        Rsig["tfo"] = Rsig.tf.map(L.TF_ORDER)
        Rsig["key"] = Rsig.strategy + "@" + Rsig.tf
        Rsig = Rsig.sort_values(["bar_close", "tfo"], ascending=[True, False]).reset_index(drop=True)
        reng = Merged(Rsig)
        rp_, rt_ = sp.masks(Rsig.bar_close, Rsig.exit_time.astype(float).fillna(sp.b))
        r, kp = row_merged("b_merged_coin", sp, "random_accounts_signals", 12, 12, "RANDOM_1..3@15m-4h", reng,
                           Rsig.index[rp_].to_numpy(), Rsig.index[rt_].to_numpy(), base, day_edges, flip_runs=False)
        rows.append(r)
        keep[len(rows) - 1] = kp

        # ---- (c1) agreement filters. Agreement is very common here (median: 9 different strategies on the same coin
        # and side within 1 h), so "2+ agree" is almost every signal; the variants use higher counts, net counts
        # (same side minus opposite side) and agreement among the pick part's best strategies only.
        variants = [("all", "1h", n) for n in (10, 15, 20, 25)] + [("all", "4h", n) for n in (25, 30, 35, 40)] + \
                   [("net", "1h", d) for d in (5, 10, 15)] + [("net", "4h", d) for d in (10, 15, 20)] + \
                   [("top", w, k) for w in ("1h", "4h") for k in (10, 20, 40)]
        top_order = list(elig["mean"].sort_values(ascending=False).index)

        def agree_mask(X, v):
            kind_, wn, n = v
            if kind_ == "all":
                return (X[f"agree_{wn}"] >= n).to_numpy()
            if kind_ == "net":
                return ((X[f"agree_{wn}"] - X[f"opp_{wn}"]) >= n).to_numpy()
            mem = set(top_order[:n])
            sub = X[X.key.isin(mem)]
            cnt = agree_within(sub, 3_600_000 if wn == "1h" else 4 * 3_600_000)
            ok = np.zeros(len(X), bool)
            ok[np.searchsorted(X.index.to_numpy(), sub.index.to_numpy()[cnt >= 2])] = True
            return ok

        res_pick = {v: eng.run(P.index[agree_mask(P, v)].to_numpy())[0] for v in variants}
        best = max(res_pick, key=lambda v: res_pick[v])
        for v in variants:
            ct, cp = agree_mask(T, v), agree_mask(P, v)
            idx_t = T.index[ct].to_numpy()
            n_c = len(idx_t)
            rnd = np.array([eng.run(np.sort(RNG.choice(T_idx, min(n_c, len(T_idx)), replace=False)))[0]
                            for _ in range(300)]) if n_c else None
            how = f"agree_{v[0]}_{v[1]}_{v[2]}"
            r, kp = row_merged("c_agree", sp, how, v[2], len(variants), "(top strategies)" if v[0] == "top" else
                               "(all strategies)", eng, P.index[cp].to_numpy(), idx_t, base, day_edges, rand=rnd,
                               extra={"picked_on_pick_part": v == best, "n_candidates_test": n_c})
            rows.append(r)
            keep[len(rows) - 1] = kp
            rows.append(per_signal_row("c_agree_signal", sp, how, T[ct], P[cp], base,
                                       extra={"picked_on_pick_part": v == best}))
        # (c2, agreement with the higher-timeframe trend, is studied separately in analysis/review1024/roles/)
        # ---- (c3) fade the losers (opposite side, same exits and costs)
        order_lo = list(elig["mean"].sort_values(ascending=True).index)
        for K in (1, 3, 5, 10):
            if len(order_lo) < K:
                continue
            mem = order_lo[:K]
            rank = {k: i for i, k in enumerate(mem)}
            r, kp = row_merged("c_fade", sp, f"fade_bottom{K}", K, len(keys), ";".join(mem), eng,
                               ordered(P[P.key.isin(mem)], rank), ordered(T[T.key.isin(mem)], rank), base, day_edges,
                               rand=rand_dist(K, flip_all=True), flip_runs=True, flip_all=True,
                               rand_m=matched_dist(mem, cnt_all, T_idx, T_key, flip_all=True))
            rows.append(r)
            keep[len(rows) - 1] = kp
            rows.append(per_signal_row("c_fade_signal", sp, f"fade_bottom{K}", T[T.key.isin(mem)], P[P.key.isin(mem)],
                                       base, ret_col="f_wallet_ret", side_col="f_side"))
        rows.append(per_signal_row("c_fade_signal", sp, "fade_all", T, P, base, ret_col="f_wallet_ret",
                                   side_col="f_side"))
        # ---- (e) side / coin restriction chosen per strategy on the pick part
        Pv = P[np.isfinite(P.wallet_ret)]
        choice = {}
        for k, g in Pv.groupby("key"):
            opts = {}
            if len(g) >= MIN_PICK_SIGNALS:
                opts["both"] = g.wallet_ret.mean()
            for sd, nm in ((1, "long"), (-1, "short")):
                gs = g[g.side == sd]
                if len(gs) >= MIN_PICK_SIGNALS:
                    opts[nm] = gs.wallet_ret.mean()
            side_c = max(opts, key=opts.get) if opts else None
            coins = [c for c, gc in g.groupby("coin") if len(gc) >= 3 and gc.wallet_ret.mean() > 0]
            choice[k] = (side_c, set(coins), opts.get(side_c, np.nan))

        def restrict(X, mode):
            ok = np.zeros(len(X), bool)
            for i, (k, sd, cn) in enumerate(zip(X.key, X.side, X.coin)):
                c = choice.get(k)
                if c is None or c[0] is None:
                    continue
                s_ok = c[0] == "both" or (c[0] == "long" and sd > 0) or (c[0] == "short" and sd < 0)
                c_ok = cn in c[1]
                ok[i] = (s_ok if mode in ("side", "side_coin") else True) and (c_ok if mode in ("coin", "side_coin") else True)
            return ok

        rows.append(per_signal_row("e_restrict_signal", sp, "unrestricted", T[T.key.isin(choice)],
                                   P[P.key.isin(choice)], base))
        for mode in ("side", "coin", "side_coin"):
            ft, fp = restrict(T, mode), restrict(P, mode)
            rows.append(per_signal_row("e_restrict_signal", sp, f"per_strategy_{mode}", T[ft], P[fp], base))
            # top-K strategies by their restricted pick mean, merged
            stR = pick_stats(P[fp], base_pick)
            stR = stR[stR.n >= MIN_PICK_SIGNALS]
            order = list(stR["mean"].sort_values(ascending=False).index)
            kR = list(stR.index)
            TR_idx, TR_key = T.index[ft].to_numpy(), T.key[ft].to_numpy()
            for K in (1, 3, 5, 10):
                if len(order) < K:
                    continue
                mem = order[:K]
                rank = {k: i for i, k in enumerate(mem)}
                rnd = np.array([eng.run(TR_idx[np.isin(TR_key, list(RNG.choice(kR, K, replace=False)))])[0]
                                for _ in range(300)])
                r, kp = row_merged("e_restrict_merged", sp, f"{mode}_top{K}", K, len(kR), ";".join(mem), eng,
                                   ordered(P[fp & P.key.isin(mem)], rank), ordered(T[ft & T.key.isin(mem)], rank),
                                   base, day_edges, rand=rnd,
                                   rand_m=matched_dist(mem, {k: int(stR.n[k]) for k in kR}, TR_idx, TR_key))
                rows.append(r)
                keep[len(rows) - 1] = kp
        # global side choice on the pick part
        pl, ps = P[P.side > 0].wallet_ret.mean(), P[P.side < 0].wallet_ret.mean()
        g_side = 1 if pl > ps else -1
        for sd, nm in ((1, "all_long_only"), (-1, "all_short_only")):
            rows.append(per_signal_row("e_restrict_signal", sp, nm, T[T.side == sd], P[P.side == sd], base,
                                       extra={"picked_on_pick_part": sd == g_side}))
        print(f"  signal families {sp.name}: eligible strategies {len(keys)}", flush=True)
    return rows, keep
