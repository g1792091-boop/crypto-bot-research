"""Self-checks of the data layer (writes selfcheck_report.json and match_rates.csv next to this file):

  A  forward match: the rule bot's logged signals vs the same strategies recomputed on the extended grid, per strategy x
     timeframe, over the logged window (recall = logged found by the recomputation, precision = recomputed found in the
     log, both by bar close + coin + side)
  B  judge parity: (1) paperbot/trendjudge.judge_frame on the live window (the last 300 closed bars) at random bars vs
     the state tables (full history); (2) the trend bot's own logged judgments (combo databases) vs the recomputed
     ones; (3) the trend bot's last saved judgment snapshot (state 'trend') vs the recomputed one
  C  state spot checks by hand on 5 random signals: the higher bar read (its close <= the signal close), the four judges
     and three more states recomputed with plain pandas / numpy formulas on that bar, and every condition state
     recomputed on the bars cut at that bar (no look-ahead in the indicator code)
  D  outcome grid: the forward table's direct walks vs the grid lookups (must be equal); an independent pure-Python walk
     written from the rule text vs the grid on random entries; the ladder vs paperbot/ladder.LadderSpec; the paper
     bot's house trades vs the recomputed 2 ATR + ladder (same direction, not equal: fills, leverage tier, fees differ)
  E  no NaN leakage, no look-ahead in the higher-bar mapping

    python3 selfcheck.py"""
from common import *
import rolesdata as RD
import build_states as BS

REPORT = {}
rng = np.random.default_rng(20261024)


# ====================================================================== A  forward match
def check_match():
    F = RD.forward("rule")
    REPORT["A_match_xrp_rows_skipped"] = int((F.coin < 0).sum())     # XRPUSDT: logged (RECORD), not on the grid
    F = F[F.tf.isin(TFS) & ~F.strategy.str.startswith("RANDOM") & (F.coin >= 0)]
    a, b = int(F.t.min()), int(F.t.max()) + 1
    N = RD.names()
    S = RD.signals(names=sorted(set(F.strategy) & set(N.name)), tfs=TFS, period=(a, b), min_nb=0)
    key = ["strategy", "tf", "t", "coin", "side"]
    S = S.rename(columns={"name": "strategy"})
    L = F[key].drop_duplicates().assign(logged=1)
    R = S[key].drop_duplicates().assign(recomp=1)
    M = L.merge(R, on=key, how="outer")
    opp = L.merge(R.assign(side=-R.side), on=key, how="inner")
    rows = []
    for (st, tf), g in M.groupby(["strategy", "tf"]):
        nl, nr = int(g.logged.notna().sum()), int(g.recomp.notna().sum())
        both = int((g.logged.notna() & g.recomp.notna()).sum())
        no = int(((opp.strategy == st) & (opp.tf == tf)).sum())
        rows.append({"strategy": st, "tf": tf, "set": N.set[N.name == st].iloc[0] if (N.name == st).any() else "?",
                     "logged": nl, "recomputed": nr, "both": both,
                     "recall": round(both / nl, 4) if nl else np.nan, "precision": round(both / nr, 4) if nr else np.nan,
                     "logged_opposite_side": no})
    T = pd.DataFrame(rows).sort_values(["recall", "strategy", "tf"])
    T.to_csv(os.path.join(HERE, "match_rates.csv"), index=False)
    tot_l, tot_r, tot_b = T.logged.sum(), T.recomputed.sum(), T.both.sum()
    REPORT["A_match"] = {"window_utc": [str(pd.Timestamp(a, unit="ms")), str(pd.Timestamp(b, unit="ms"))],
                         "cells": len(T), "logged": int(tot_l), "recomputed": int(tot_r), "both": int(tot_b),
                         "recall_all": round(tot_b / tot_l, 4), "precision_all": round(tot_b / tot_r, 4),
                         "cells_recall_ge_0.95": int((T.recall >= 0.95).sum()),
                         "cells_recall_lt_0.80": T[T.recall < 0.80][["strategy", "tf", "logged", "recall", "precision"]]
                         .to_dict("records")}
    by = T.groupby("set")[["logged", "recomputed", "both"]].sum()
    REPORT["A_match"]["by_set"] = {k: {"recall": round(r.both / r.logged, 4), "precision": round(r.both / r.recomputed, 4)}
                                   for k, r in by.iterrows()}
    log("A", REPORT["A_match"]["recall_all"], REPORT["A_match"]["precision_all"])


# ====================================================================== B  judge parity
def check_judge_windows(n_per=50):
    E = libs()
    TJ = E["TJ"]
    rules = TJ.TrendRules()
    res = []
    for coin in COINS:
        for htf in HTFS:
            df = bars(coin, htf)
            Z = RD._states(coin, htf)
            idx = rng.integers(400, len(df), n_per)
            for i in idx:
                w = df.iloc[i - 299:i + 1].copy()
                w["ts"] = pd.to_datetime(w["ts"], unit="ms", utc=True)
                j = TJ.judge_frame(w.reset_index(drop=True), coin, htf, rules, E["fg"], E["pi"])
                res.append({"coin": coin, "htf": htf, "i": int(i),
                            "votes_eq": all(j.votes[k] == int(Z[f"j_{k}"][i]) for k in TJ.JUDGES),
                            "raw_eq": j.raw == int(Z["j_raw3"][i]), "dir_eq": j.dir == int(Z["j_dir"][i]),
                            "adx_diff": abs(j.adx - float(Z["j_adx"][i])),
                            "bar_close_eq": j.bar_close == int(Z["ts"][i]) + TF_MIN[htf] * MIN})
        drop(coin)
    R = pd.DataFrame(res)
    REPORT["B1_judge_300bar_window"] = {
        "n": len(R), "votes_equal": round(R.votes_eq.mean(), 4), "raw3_equal": round(R.raw_eq.mean(), 4),
        "dir_equal": round(R.dir_eq.mean(), 4), "bar_close_equal": round(R.bar_close_eq.mean(), 4),
        "adx_abs_diff_median": float(R.adx_diff.median()), "adx_abs_diff_max": float(R.adx_diff.max()),
        "by_htf_dir_equal": R.groupby("htf").dir_eq.mean().round(4).to_dict()}
    log("B1", REPORT["B1_judge_300bar_window"])


def check_judge_logged():
    T = RD.forward("trendbot")
    T = T[T.log_j_tf.notna()].copy()
    out = {"rows_with_logged_judge": len(T)}
    if len(T):
        h = T.log_j_tf.astype(str)
        mine = {}
        for k in ("V39", "S6", "OBV", "N12", "raw3", "dir", "adx", "bar_close"):
            v = np.full(len(T), np.nan)
            for htf in HTFS:
                m = (h == htf).to_numpy()
                v[m] = T[f"j{htf}_{k}"].to_numpy(float)[m]
            mine[k] = v
        eq = lambda a, b: float(np.mean(np.asarray(a, float) == np.asarray(b, float)))
        out.update({"bar_close_equal": eq(mine["bar_close"], T.log_j_bar_close),
                    "votes_equal": float(np.mean(np.all([np.asarray(mine[k]) == T[f"log_j_{k}"].to_numpy(float)
                                                         for k in ("V39", "S6", "OBV", "N12")], axis=0))),
                    "raw3_equal": eq(mine["raw3"], T.log_j_raw), "dir_equal": eq(mine["dir"], T.log_j_dir),
                    "adx_abs_diff_median": float(np.nanmedian(np.abs(mine["adx"] - T.log_j_adx.to_numpy(float)))),
                    "adx_abs_diff_max": float(np.nanmax(np.abs(mine["adx"] - T.log_j_adx.to_numpy(float)))),
                    "spot_rsi_abs_diff_max": float(np.nanmax(np.abs(T.spot_rsi.to_numpy(float) - T.log_spot_rsi.to_numpy(float)))),
                    "spot_ema20_rel_diff_max": float(np.nanmax(np.abs(T.spot_ema20 / T.log_spot_ema20 - 1)))})
        # the bot's own reason vs the recomputed check, with the config in force at the row: the 10-21 design (보류 = no
        # entry) until the first logged '보류지만 반대 아님' pass, the 10-22 design (보류 allowed) from then on
        tw = T.why.astype(str)
        passed = T.status.isin(["SUBMITTED", "BROKE"]).to_numpy()
        kind = np.where(passed, "pass", np.where(tw.str.contains("추세가"), "against", np.where(tw.str.contains("보류"), "hold",
                        np.where(tw.str.contains("힘 약함"), "weak", np.where(tw.str.contains("끝물"), "tired",
                        np.where(tw.str.contains("초입"), "breakout", np.where(tw.str.contains("EMA20에서"), "far",
                        np.where(tw.str.contains("RSI"), "rsi", "other"))))))))
        hold_ok = tw.str.contains("보류지만")
        t_1022 = int(T.t[hold_ok].min()) if hold_ok.any() else 2**62
        mine_w = np.where(T.t.to_numpy() >= t_1022, T.tj_why_1022.fillna("").to_numpy(), T.tj_why_1021.fillna("").to_numpy())
        mine_w = pd.Series(mine_w).replace({"far_htf": "far", "far_etf": "far", "": "pass"}).to_numpy()
        sel = kind != "other"
        out["design_1022_from_kst"] = str(kst([t_1022])[0]) if t_1022 < 2**62 else None
        out["reason_rows"] = int(sel.sum())
        out["reason_equal"] = float(np.mean(mine_w[sel] == kind[sel])) if sel.any() else None
        out["reason_mismatches"] = T.loc[sel & (mine_w != kind), ["t_kst", "symbol", "tf", "strategy", "side", "status", "why",
                                                                  "tj_why_1021", "tj_why_1022"]].head(20).to_dict("records")
    REPORT["B2_judge_vs_trendbot_log"] = out
    log("B2", {k: v for k, v in out.items() if k != "reason_mismatches"})
    import sqlite3
    con = sqlite3.connect(f"file:{os.path.join(XD, 'extra', 'db__paperbot__combo__live-ac.db')}?mode=ro&immutable=1", uri=True)
    snap = json.loads(con.execute("select data from state where k = 'trend'").fetchone()[0])
    con.close()
    rows = []
    for coin, d in snap.get("coins", {}).items():
        for htf, j in d.items():
            if htf not in HTFS or not isinstance(j, dict) or "votes" not in j:
                continue
            Z = RD._states(coin, htf)
            i = int(np.searchsorted(Z["ts"] + TF_MIN[htf] * MIN, int(j["bar_close"])))
            if i >= len(Z["ts"]) or Z["ts"][i] + TF_MIN[htf] * MIN != int(j["bar_close"]):
                rows.append({"coin": coin, "htf": htf, "found": False})
                continue
            rows.append({"coin": coin, "htf": htf, "found": True, "bar_close_kst": str(kst([j["bar_close"]])[0]),
                         "votes_eq": all(j["votes"][k] == int(Z[f"j_{k}"][i]) for k in ("V39", "S6", "OBV", "N12")),
                         "raw_eq": j["raw"] == int(Z["j_raw3"][i]), "dir_eq": j["dir"] == int(Z["j_dir"][i]),
                         "adx_diff": round(abs(j["adx"] - float(Z["j_adx"][i])), 4)})
    REPORT["B3_judge_vs_trendbot_snapshot"] = {"ts_kst": str(kst([snap.get("ts", 0)])[0]), "rows": rows}
    log("B3", rows)


# ====================================================================== C  spot checks by hand
def wilder(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def check_spots():
    S = RD.signals(names=["O4_STOCHRSI_ZONE", "F4_PULL", "N17_KC_RSI", "V45_AMB", "F9_OB"], tfs=["15m", "30m", "1h", "4h"],
                   period="five")
    pick = S.groupby("name", group_keys=False).apply(lambda g: g.iloc[[int(rng.integers(len(g)))]]).sort_values("t")
    out = []
    names = roles()["roles"]["trend_incl_dual"]
    for _, r in pick.iterrows():
        coin = COINS[int(r.coin)]
        htf = RD.TJ_HTF[r.tf]
        hb = bars(coin, htf)
        hc = close_ms(hb, htf)
        i = int(last_closed(hc, int(r.t)))
        Z = RD._states(coin, htf)
        c, h, l, v = (hb[k].to_numpy(float)[: i + 1] for k in ("close", "high", "low", "volume"))
        e20 = pd.Series(c).ewm(span=20, adjust=False).mean().to_numpy()
        up, dn = np.r_[np.nan, np.diff(h)], -np.r_[np.nan, np.diff(l)]
        pdm = np.where((up > dn) & (up > 0), up, 0.0)
        mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
        pc = np.r_[np.nan, c[:-1]]
        tr = np.nanmax(np.c_[h - l, np.abs(h - pc), np.abs(l - pc)], axis=1)
        atr = wilder(tr, 14)
        pdi, mdi = 100 * wilder(pdm, 14) / atr, 100 * wilder(mdm, 14) / atr
        s6 = 1 if (c[-1] > e20[-1] and pdi[-1] > mdi[-1]) else -1 if (c[-1] < e20[-1] and mdi[-1] > pdi[-1]) else 0
        obv = np.r_[0.0, np.cumsum(np.sign(np.diff(c)) * v[1:])]
        obv_ma = pd.Series(obv).rolling(30).mean().to_numpy()
        obv_s = 1 if obv[-1] > obv_ma[-1] else -1 if obv[-1] < obv_ma[-1] else 0
        e50 = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()
        e200 = pd.Series(c).ewm(span=200, adjust=False).mean().to_numpy()
        t1 = int(np.sign(e50[-1] - e200[-1]))
        roc9 = 100 * (c[-1] / c[-10] - 1)
        # every condition state on the bars cut at bar i (the code itself: no look-ahead if equal)
        cut = hb.iloc[: i + 1].reset_index(drop=True)
        nx = BS.NEXT_HTF[htf]
        nxt = None
        if nx is not None:
            nb_ = bars(coin, nx)
            nb_ = nb_[close_ms(nb_, nx) <= hc[i]].reset_index(drop=True)
            nxt = (nx, nb_)
        Scut = BS.cond_states(cut, htf, nxt)
        diff = [k for k in names if int(Scut[k][-1]) != int(Z[f"c_{k}"][i])]
        Jc = BS.judge_arrays(cut, htf)
        jdiff = [k for k in ("j_V39", "j_S6", "j_OBV", "j_N12", "j_raw3") if int(Jc[k][-1]) != int(Z[k][i])]
        out.append({"signal": f"{r['name']} {r.tf} {coin} {'롱' if r.side > 0 else '숏'} 봉마감 {kst([r.t])[0]} KST",
                    "htf_bar": f"{htf} 봉 {kst([hb.ts.iloc[i]])[0]} ~ {kst([hc[i]])[0]} KST (마감 <= 신호 마감: {hc[i] <= r.t})",
                    "next_htf_bar_close_after_signal": bool(i + 1 >= len(hc) or hc[i + 1] > r.t),
                    "S6_by_hand": s6, "S6_table": int(Z["j_S6"][i]), "OBV_by_hand": obv_s, "OBV_table": int(Z["j_OBV"][i]),
                    "EMA50_200_by_hand": t1, "EMA50_200_table": int(Z["c_T1_EMA50_200"][i]),
                    "ROC9_sign_by_hand": int(np.sign(roc9)), "ROC9_table": int(Z["c_O8_ROC9"][i]),
                    "close": c[-1], "ema20": round(e20[-1], 6), "+DI": round(pdi[-1], 3), "-DI": round(mdi[-1], 3),
                    "adx_table": round(float(Z["j_adx"][i]), 3),
                    "judge_votes_table": {k: int(Z[f"j_{k}"][i]) for k in ("V39", "S6", "OBV", "N12")},
                    "raw3": int(Z["j_raw3"][i]), "dir": int(Z["j_dir"][i]),
                    "cut_at_bar_states_differ": diff, "cut_at_bar_judges_differ": jdiff})
        drop(coin)
    REPORT["C_spot_checks"] = out
    for o in out:
        log("C", o["signal"], "|", o["htf_bar"], "| S6", o["S6_by_hand"], o["S6_table"], "OBV", o["OBV_by_hand"],
            o["OBV_table"], "EMA50/200", o["EMA50_200_by_hand"], o["EMA50_200_table"], "ROC9", o["ROC9_sign_by_hand"],
            o["ROC9_table"], "| cut differs:", o["cut_at_bar_states_differ"], o["cut_at_bar_judges_differ"])


# ====================================================================== D  outcome grid
def ref_walk(o, h, l, c, cumf, e, s, lev, cost, roe_stop, n, atr_dist=None):
    """Pure Python, from the rule text: enter at o[e]; each minute the stop is the net-ROE stop (or 2 ATR from the
    entry when atr_dist is given, floored at -100 % net), raised to the ladder's lock (armed by the best net ROE of the
    earlier minutes); filled at the level, or at the minute's open if it opened beyond it; net = side x move - cost -
    funding; at the data end the trade is open (marked at the last close)."""
    p0, f0 = o[e], cumf[e - 1]
    best, lock = -1e9, None
    k = 0
    while True:
        i = e + k
        if i >= n:
            i = n - 1
            return max(s * (c[i] / p0 - 1) - cost - s * (cumf[i] - f0), -1 / lev), i - e, 3
        Fp, F = s * (cumf[i - 1] - f0), s * (cumf[i] - f0)
        level = roe_stop / lev + cost + Fp
        if atr_dist is not None:
            level = max(level, -atr_dist)
        if lock is not None:
            level = max(level, lock / lev + cost + Fp)
        up = (h[i] / p0 - 1) if s > 0 else (1 - l[i] / p0)
        dn = (l[i] / p0 - 1) if s > 0 else (1 - h[i] / p0)
        op = s * (o[i] / p0 - 1)
        if dn <= level:
            return max(min(level, op) - cost - F, -1 / lev), k, (1 if lock is not None else 0)
        r_up = lev * (up - cost - F)
        if r_up > best:
            best = r_up
            if best >= FL + GAP - 1e-12:
                lock = FL + STEP * np.floor((best - FL - GAP) / STEP + 1e-9)
        k += 1


def check_grid():
    out = {}
    from frcore import check_lock
    out["ladder_equals_LadderSpec"] = bool(check_lock())
    F = RD.forward("rule")
    F15 = F[F.tf.isin(TFS)].copy()
    G = RD.add_outcomes(F15[["t", "e", "coin", "side", "tf"]].copy(), list(VARIANTS), opp=True)
    eq = {}
    for v in VARIANTS:
        for sfx in ("", "_opp"):
            a, b = F15[f"{v}{sfx}_r"].to_numpy(float), G[f"{v}{sfx}_r"].to_numpy(float)
            ka, kb = F15[f"{v}{sfx}_k"].to_numpy(), G[f"{v}{sfx}_k"].to_numpy()
            fin = np.isfinite(a) | np.isfinite(b)
            eq[f"{v}{sfx}"] = {"rows": int(fin.sum()),
                               "r_equal": float(np.mean(np.isclose(a[fin], b[fin], rtol=0, atol=1e-7))),
                               "k_equal": float(np.mean(ka[fin] == kb[fin]))}
    out["forward_direct_vs_grid"] = eq
    res = []
    for ci, coin in enumerate(COINS):
        g = grid(coin)
        o, h, l, c = g["o"], g["h"], g["l"], g["c"]
        cumf = np.cumsum(g["fund"])
        Gz = RD._grid(coin)
        valid = np.flatnonzero(Gz["valid15"])
        for j in rng.choice(valid, 40, replace=False):
            e = int((j + 1) * 15)
            for v, (kind, lev, stop) in VARIANTS.items():
                if kind != "walk3":
                    continue
                for s, lab in ((1, "L"), (-1, "S")):
                    r, k, w = ref_walk(o, h, l, c, cumf, e, s, lev, COST, stop, g["n"])
                    res.append({"coin": coin, "v": v, "r_eq": abs(r - float(Gz[f"{v}_{lab}_r"][j])) < 1e-6,
                                "k_eq": k == int(Gz[f"{v}_{lab}_k"][j]), "why_eq": w == int(Gz[f"{v}_{lab}_why"][j])})
            jt = j * 15 // 60
            if Gz["valid15"][j] and (e % 60 == 0) and np.isfinite(Gz["atr14_1h"][e // 60 - 1]):
                j1 = e // 60 - 1
                ad = 2 * Gz["atr14_1h"][j1] / o[e]
                for s, lab in ((1, "L"), (-1, "S")):
                    r, k, w = ref_walk(o, h, l, c, cumf, e, s, 30.0, COST, -1.0, g["n"], atr_dist=ad)
                    res.append({"coin": coin, "v": "a2_1h", "r_eq": abs(r - float(Gz[f"a2_1h_{lab}_r"][j1])) < 1e-6,
                                "k_eq": k == int(Gz[f"a2_1h_{lab}_k"][j1]), "why_eq": w == int(Gz[f"a2_1h_{lab}_why"][j1])})
        drop(coin)
    R = pd.DataFrame(res)
    out["reference_walk_vs_grid"] = {"n": len(R), "r_equal": float(R.r_eq.mean()), "k_equal": float(R.k_eq.mean()),
                                     "why_equal": float(R.why_eq.mean()),
                                     "by_variant": R.groupby("v")[["r_eq", "k_eq", "why_eq"]].mean().round(4).to_dict("index")}
    T = F[F.tr_roe.notna() & F.tf.isin(TFS) & F.a2_r.notna()].copy()
    hs = np.sign(T.tr_roe)
    ms_ = np.sign(T.a2_r)
    xr = T.tr_exit_reason.astype(str)
    out["house_trades_vs_a2"] = {
        "trades": len(T), "same_sign": float(np.mean(hs == ms_)),
        "roe_corr": float(np.corrcoef(T.tr_roe, T.a2_r * 30)[0, 1]),
        "house_mean_roe": float(T.tr_roe.mean()), "a2_30x_mean_roe": float((T.a2_r * 30).mean()),
        "house_leverage_counts": T.tr_leverage.value_counts().to_dict(),
        "house_exit_reasons": xr.value_counts().to_dict(),
        "note": "not expected equal: the paper bot fills at its reference price + slippage, uses quality leverage "
                "(20-50x), Binance taker fees and real funding; a2 is 30x with the WOO cost and no funding in October"}
    REPORT["D_grid"] = out
    log("D", json.dumps({k: v for k, v in out.items() if k != "house_trades_vs_a2"}, default=str)[:800])
    log("D house", out["house_trades_vs_a2"])


# ====================================================================== E  NaN / look-ahead
def check_nan():
    out = {}
    for coin in COINS:
        G = RD._grid(coin)
        v = G["valid15"]
        bad = {}
        for k in G:
            if k.endswith("_r") and not k.startswith("a2_"):
                bad[k] = int(np.isnan(G[k][v]).sum()) + int((~np.isnan(G[k][~v])).sum())
        out[f"grid_{coin}_nan_or_leak"] = int(sum(bad.values()))
        for htf in HTFS:
            Z = RD._states(coin, htf)
            nan_adx = np.flatnonzero(np.isnan(Z["j_adx"]))
            out[f"states_{coin}_{htf}_adx_nan_last_index"] = int(nan_adx.max()) if len(nan_adx) else -1
            out[f"states_{coin}_{htf}_ema20_nan"] = int(np.isnan(Z["j_ema20"]).sum())
    F = RD.forward("rule")
    la = {}
    for htf in HTFS:
        bc = F[f"j{htf}_bar_close"].to_numpy(float)
        la[htf] = int(np.sum(bc > F.t.to_numpy(float)))
    out["forward_rule_htf_bar_after_signal"] = la
    nn = F[F.tf.isin(TFS)][["w35_r", "w30_r", "w35s20_r", "a2_r", "w35_opp_r", "j1h_dir", "j4h_dir", "j1d_dir"]].isna().sum()
    out["forward_rule_nan_counts_15m_4h"] = nn.astype(int).to_dict()
    out["forward_rule_open_at_end_w35"] = int((F.w35_why == 3).sum())
    S = RD.signals(names=["O4_STOCHRSI_ZONE"], tfs=["1h"], period="five")
    S = RD.add_states(S, "4h", ["OBV_S"])
    idx = RD.htf_index(S, "4h")
    bad = 0
    for ci, coin in enumerate(COINS):
        m = S.coin.to_numpy() == ci
        Z = RD._states(coin, "4h")
        bc = Z["ts"][idx[m]] + 240 * MIN
        bad += int(np.sum(bc > S.t.to_numpy()[m]))
        nxt = np.minimum(idx[m] + 1, len(Z["ts"]) - 1)
        bad += int(np.sum((Z["ts"][nxt] + 240 * MIN <= S.t.to_numpy()[m]) & (idx[m] + 1 < len(Z["ts"]))))
    out["loader_states_lookahead_or_stale"] = bad
    REPORT["E_nan_lookahead"] = out
    log("E", out)


if __name__ == "__main__":
    t0 = time.time()
    for f in (check_nan, check_grid, check_judge_logged, check_judge_windows, check_spots, check_match):
        try:
            f()
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            REPORT[f.__name__ + "_ERROR"] = repr(exc)
        json.dump(REPORT, open(os.path.join(HERE, "selfcheck_report.json"), "w"), ensure_ascii=False, indent=1,
                  default=lambda x: x.item() if hasattr(x, "item") else str(x))
    log("selfcheck done", f"{time.time() - t0:.0f}s")
