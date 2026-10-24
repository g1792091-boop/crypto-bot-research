#!/usr/bin/env python3
"""Everything the rule bot records beyond the accounts' own trades: nightly shadow variants, every signal, the
market context at the signal, and the "+500 % in 30 days" goal path.

    python3 rb_extra.py <extracted_dir> <base_dir> <work_dir> <out_dir> [--boot 4000] [--seed 20261025]

<work_dir> holds randpool.csv, varpool_synth.csv, varpool_real.csv (randpool.py, varpool.py);
<out_dir> already holds tables/accounts_v4.csv and facts.json from rb1024.py; this adds tables/x_*.csv and
facts_extra.json.

Luck filter (the same idea as test A of rb1024.py, here in closed form so thousands of cells can be tested):
the null for a set of trades is "a coin flip with the same timeframe, coin and side on a randomly drawn day"
(one random day per real trading day, shared by the trades of that day). Its mean and variance are exact under that
null (bucket means and variances of the synthetic pool, averaged over the drawn day); p uses the normal
approximation. The pool is the same exit variant replayed on random entries (varpool_synth.csv), so an exit that
helps every entry in this market does not count as skill. BH over every cell of a family.

Conditions: first half picks, second half checks (the run is cut at its midpoint); the same picking done on the
side-flipped signals (the strategy's opposite side at the same moments) is the placebo.
Goal path: 30-day day-block bootstrap of the forward trades at a given margin share m and leverage L (wallet change
per trade = m x L x net return on notional, at least -m), trades whose stop is beyond about the liquidation
distance of L skipped.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np
import pandas as pd

MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
KST = 9 * HOUR
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
VARIANTS = ["base", "lock15", "lock20", "lock30", "timestop", "lev10", "lev20", "lev30", "lev40", "lev50",
            "stopw1.5", "stopw2.5", "stopw3", "tp1R", "tp1.5R", "tp2R", "tp3R", "ladder_cap2R",
            "lev20m20", "lev30m30", "lev40m40", "lev50m50"]
COMBOS = [(0.30, 30), (0.40, 20), (0.40, 30), (0.40, 40), (0.40, 50)]
GOAL_X = 6.0          # +500 %


def Phi(z):
    return 0.5 * (1 + np.vectorize(math.erf)(np.asarray(z, float) / math.sqrt(2)))


def bh(p):
    p = np.asarray(p, float)
    n = len(p)
    if n == 0:
        return p
    o = np.argsort(p)
    q = p[o] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    out = np.empty(n)
    out[o] = np.minimum(q, 1.0)
    return out


def kday(ms):
    return pd.to_datetime(pd.Series(ms, dtype="float64") + KST, unit="ms").dt.strftime("%m-%d").values


# ------------------------------------------------------------------------------------------------ closed-form null
class Null:
    """Pool buckets (tf, symbol, side) x KST day: mean and variance of 'value', with fallbacks."""

    def __init__(self, P: pd.DataFrame, value: str, days: list):
        P = P[np.isfinite(P[value])]
        self.days = days
        self.di = {d: i for i, d in enumerate(days)}
        D = len(days)
        P = P[P["day"].isin(self.di)]
        g = P.groupby(["timeframe", "symbol", "side", "day"])[value].agg(["mean", "var", "size"])
        g["var"] = g["var"].fillna(0.0) * (g["size"] - 1).clip(lower=0) / g["size"]
        g2 = P.groupby(["timeframe", "side", "day"])[value].agg(["mean", "var", "size"])
        g2["var"] = g2["var"].fillna(0.0) * (g2["size"] - 1).clip(lower=0) / g2["size"]
        g3 = P.groupby(["timeframe", "side"])[value].agg(["mean", "var"])
        self.keys = sorted({(a, b, int(c)) for a, b, c, _ in g.index})
        self.ki = {k: i for i, k in enumerate(self.keys)}
        K = len(self.keys)
        mu = np.full((K, D), np.nan)
        s2 = np.full((K, D), np.nan)
        for (tf, s, sd, d), r in g.iterrows():
            mu[self.ki[(tf, s, int(sd))], self.di[d]] = r["mean"]
            s2[self.ki[(tf, s, int(sd))], self.di[d]] = r["var"]
        for k, (tf, s, sd) in enumerate(self.keys):
            for d in range(D):
                if not np.isfinite(mu[k, d]):
                    key2 = (tf, sd, days[d])
                    if key2 in g2.index:
                        mu[k, d], s2[k, d] = g2.loc[key2, "mean"], g2.loc[key2, "var"]
                    else:
                        mu[k, d], s2[k, d] = g3.loc[(tf, sd), "mean"], g3.loc[(tf, sd), "var"]
        self.mu, self.s2 = mu, s2
        self.tfside = g3

    def test(self, T: pd.DataFrame, value: str) -> dict:
        """T: trades with timeframe, symbol, side, day, value."""
        T = T[np.isfinite(T[value])]
        n = len(T)
        if n < 2:
            return {"n": n}
        keys = [(tf, s, int(sd)) for tf, s, sd in zip(T["timeframe"], T["symbol"], T["side"])]
        ok = np.array([k in self.ki for k in keys])
        if not ok.all():
            T = T[ok]
            keys = [k for k, o in zip(keys, ok) if o]
            n = len(T)
            if n < 2:
                return {"n": n}
        ki = np.array([self.ki[k] for k in keys])
        M = self.mu[ki]                      # n x D
        V = self.s2[ki]
        grp = pd.factorize(T["day"].to_numpy())[0]
        G = grp.max() + 1
        Sg = np.zeros((G, M.shape[1]))
        Wg = np.zeros((G, M.shape[1]))
        np.add.at(Sg, grp, M)
        np.add.at(Wg, grp, V)
        E = Sg.mean(1).sum()
        var = Sg.var(1).sum() + Wg.mean(1).sum()
        obs = float(T[value].sum())
        sd = math.sqrt(var) if var > 0 else np.nan
        z = (obs - E) / sd if sd == sd and sd > 0 else np.nan
        return {"n": n, "obs_mean": obs / n, "null_mean": E / n, "null_sd_mean": sd / n if sd == sd else np.nan,
                "excess": (obs - E) / n, "z": z,
                "p_better": float(1 - Phi(z)) if z == z else np.nan, "p_worse": float(Phi(z)) if z == z else np.nan}


# ------------------------------------------------------------------------------------------------ helpers
def sameday_excess(S: pd.DataFrame, P: pd.DataFrame, value: str) -> dict:
    """Every signal minus the coin-flip pool mean of the same timeframe, KST day, coin and side; averaged per day,
    then the day means are compared with 0 (t over days). Stricter than the random-day null: it also removes the
    day's direction, so it measures entry timing within the day."""
    pm = P.groupby(["timeframe", "day", "side", "symbol"])[value].mean()
    key = list(zip(S["timeframe"], S["day"], S["side"], S["symbol"]))
    ex = S[value].to_numpy(float) - pm.reindex(key).to_numpy(float)
    ok = np.isfinite(ex)
    d = pd.Series(ex[ok]).groupby(S["day"].to_numpy()[ok]).mean()
    k = len(d)
    if k < 3:
        return {"days": k}
    sd = d.std(ddof=1)
    return {"days": k, "excess": float(d.mean()), "days_pos": int((d > 0).sum()),
            "t": float(d.mean() / (sd / math.sqrt(k))) if sd > 0 else np.nan}


# ------------------------------------------------------------------------------------------------ helpers (2)
def one_position(df: pd.DataFrame) -> pd.DataFrame:
    """Greedy one-position account over the signals of one cell: take a signal only if the previous taken trade has
    exited (entry order). Signals at the same bar: first in table order."""
    df = df.sort_values(["entry_time", "sig_id"])
    keep, free = [], -1
    for i, e, x in zip(df.index, df["entry_time"].to_numpy(), df["exit_time"].to_numpy()):
        if e >= free:
            keep.append(i)
            free = x
    return df.loc[keep]


def goal_path(r: np.ndarray, stop: np.ndarray, day: np.ndarray, all_days: list, rng, B: int,
              shift: float = 0.0) -> list[dict]:
    """30-day day-block bootstrap for each (m, L) of COMBOS plus the needed exposure."""
    r = r + shift
    out = []
    D = len(all_days)
    di = {d: i for i, d in enumerate(all_days)}
    per = [[] for _ in range(D)]
    for k, d in enumerate(day):
        if d in di:
            per[di[d]].append(k)
    maxT = max(1, max(len(p) for p in per))
    idx = np.full((D, maxT), -1)
    for i, p in enumerate(per):
        idx[i, :len(p)] = p
    pick = rng.integers(0, D, size=(B, 30))
    I = idx[pick].reshape(B, -1)                         # B x 30*maxT trade indices (-1 = none)
    n_per_day = len(r) / D
    for m, L in COMBOS:
        allowed = stop <= (1.0 / L - 0.006)
        x = np.where(I >= 0, np.where(allowed[np.maximum(I, 0)], np.maximum(m * L * r[np.maximum(I, 0)], -m), 0.0), 0.0)
        lw = np.cumsum(np.log1p(x), axis=1)
        hit6 = lw >= math.log(GOAL_X)
        hit50 = lw <= math.log(0.5)
        hit90 = lw <= math.log(0.1)
        big = lw.shape[1] + 1
        t6 = np.where(hit6.any(1), hit6.argmax(1), big)
        t50 = np.where(hit50.any(1), hit50.argmax(1), big)
        t90 = np.where(hit90.any(1), hit90.argmax(1), big)
        fin = np.exp(lw[:, -1])
        out.append({"m": m, "L": L, "exposure": m * L, "allowed_share": float(allowed.mean()),
                    "p_final_x6": float((fin >= GOAL_X).mean()), "p_touch_x6": float((t6 < big).mean()),
                    "p_x6_before_-50": float(((t6 < big) & (t6 < t50)).mean()),
                    "p_-50_first": float(((t50 < big) & (t50 < t6)).mean()),
                    "p_-90_first": float(((t90 < big) & (t90 < t6)).mean()),
                    "median_final_x": float(np.median(fin)), "p_final_loss": float((fin < 1).mean())})
    # needed exposure for a median x6: N * E[log(1 + k r)] = ln 6 (N = 30 days of trades)
    N = 30 * n_per_day
    ks = np.linspace(0.25, 60, 240)
    lo = -1.0 / np.minimum(r.min(), -1e-9)
    g = np.array([np.mean(np.log1p(np.maximum(k * r, -0.999))) if k < lo else -np.inf for k in ks])
    kbest = ks[int(np.argmax(g))]
    need = ks[np.argmax(N * g >= math.log(GOAL_X))] if (N * g >= math.log(GOAL_X)).any() else np.nan
    for o in out:
        o.update(trades_per_day=n_per_day, kelly_exposure=float(kbest), kelly_median_x30=float(np.exp(N * g.max())),
                 needed_exposure_x6=float(need))
    return out


def ctx_features(path: str, ids: set) -> pd.DataFrame:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            i = int(d.get("id", -1))
            if i not in ids:
                continue
            c = d.get("ctx") or {}
            sr = c.get("sr") or {}
            rows.append({"sig_id": i, "regime": c.get("regime"), "htf_regime": c.get("htf_regime"),
                         "box_pos": c.get("box_pos"), "htf_box_pos": c.get("htf_box_pos"), "adx": c.get("adx"),
                         "di_plus": c.get("di_plus"), "di_minus": c.get("di_minus"),
                         "ema20_dist_atr": c.get("ema20_dist_atr"), "er": c.get("er"),
                         "room": sr.get("room"), "lvl_before_lock": sr.get("level_before_lock"),
                         "sup_before_stop": sr.get("support_before_stop"), "breakout": sr.get("breakout")})
    return pd.DataFrame(rows)


def add_levels(X: pd.DataFrame) -> list[str]:
    side = X["side"].to_numpy()
    X["f_side"] = np.where(side > 0, "long", "short")
    X["f_coin"] = X["symbol"].str.replace("USDT", "")
    h = pd.to_datetime(X["bar_close"] + KST, unit="ms").dt.hour
    X["f_session"] = pd.cut(h, [-1, 5, 11, 17, 23], labels=["00-06", "06-12", "12-18", "18-24"]).astype(str)
    X["f_weekend"] = np.where(pd.to_datetime(X["bar_close"] + KST, unit="ms").dt.dayofweek >= 5, "weekend", "weekday")

    def rel(reg):
        r = X[reg].fillna("unknown")
        w = ((r == "trend_up") & (side > 0)) | ((r == "trend_down") & (side < 0))
        ag = ((r == "trend_up") & (side < 0)) | ((r == "trend_down") & (side > 0))
        return np.where(w, "with_trend", np.where(ag, "against_trend", r))
    X["f_regime"] = rel("regime")
    X["f_htf_regime"] = rel("htf_regime")

    def tri(v, cuts, labs):
        return pd.cut(v, cuts, labels=labs).astype(str).replace("nan", "na")
    bp = np.where(side > 0, X["box_pos"], 1 - X["box_pos"])
    X["f_boxpos"] = tri(pd.Series(bp, index=X.index), [-1e9, 0.33, 0.67, 1e9], ["cheap", "mid", "dear"])
    hb = np.where(side > 0, X["htf_box_pos"], 1 - X["htf_box_pos"])
    X["f_htf_boxpos"] = tri(pd.Series(hb, index=X.index), [-1e9, 0.33, 0.67, 1e9], ["cheap", "mid", "dear"])
    X["f_adx"] = tri(X["adx"], [-1e9, 20, 30, 1e9], ["<20", "20-30", ">=30"])
    agree = np.where(side > 0, X["di_plus"] > X["di_minus"], X["di_minus"] > X["di_plus"])
    X["f_di_agree"] = np.where(X["di_plus"].isna(), "na", np.where(agree, "agree", "disagree"))
    ext = side * X["ema20_dist_atr"]
    X["f_extension"] = tri(ext, [-1e9, 0, 1, 1e9], ["pullback", "0-1ATR", ">1ATR"])
    X["f_er"] = tri(X["er"], [-1e9, 0.2, 0.4, 1e9], ["<0.2", "0.2-0.4", ">=0.4"])
    X["f_room"] = tri(X["room"], [-1e9, 0.25, 1.0, 1e9], ["<0.25ATR", "0.25-1ATR", ">1ATR"])
    for c in ("lvl_before_lock", "sup_before_stop", "breakout"):
        X["f_" + c] = X[c].map({1: "yes", 0: "no", 1.0: "yes", 0.0: "no"}).fillna("na")
    X["f_tier"] = X["tier"].fillna("na")
    X["f_stopsize"] = X.groupby("timeframe")["stop_frac"].transform(
        lambda s: pd.qcut(s, 3, labels=["small", "mid", "large"], duplicates="drop").astype(str))
    return [c for c in X.columns if c.startswith("f_")]


# ------------------------------------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("extracted_dir")
    ap.add_argument("base_dir")
    ap.add_argument("work_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--boot", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=20261025)
    a = ap.parse_args(argv)
    rng = np.random.default_rng(a.seed)
    TD = os.path.join(a.out_dir, "tables")
    F0 = json.load(open(os.path.join(a.out_dir, "facts.json")))
    lo, hi, mid = F0["v4_start_ms"], F0["v4_end_ms"], F0["mid_ms"]
    days_all = sorted(set(kday(np.arange(lo, hi, HOUR))))
    FX: dict = {}

    def save(df, name):
        df.to_csv(os.path.join(TD, name), index=False)

    # -------------------------------------------------------------- data
    RP = pd.read_csv(os.path.join(a.base_dir, "replay_signals.csv"), low_memory=False)
    RP = RP[(RP["run"] == "current")].copy()
    RP["day"] = kday(RP["bar_close"])
    RP["half"] = np.where(RP["bar_close"] < mid, "H1", "H2")
    RP["grp"] = RP["kind"].map({"strategy": "core", "ds200": "ds", "random": "flip", "reel": "reel"})
    RP = RP[RP["grp"].isin(["core", "ds", "flip"]) & (RP["timeframe"] != "5m")]
    pool_sig = pd.read_csv(os.path.join(a.work_dir, "randpool.csv"))
    pool_sig["day"] = kday(pool_sig["bar_close"])
    VS = pd.read_csv(os.path.join(a.work_dir, "varpool_synth.csv"))
    VS = VS.merge(pool_sig[["sig_id", "timeframe", "symbol", "side", "day", "bar_close"]], on="sig_id")
    VR = pd.read_csv(os.path.join(a.work_dir, "varpool_real.csv"))
    VR = VR.merge(RP[["sig_id", "account_id", "grp", "strategy", "timeframe", "symbol", "side", "day", "half",
                      "bar_close", "acct_status", "stop_frac", "entry_time"]], on="sig_id")
    for V in (VS, VR):
        V["r_not"] = V["roe"] / V["leverage"]
    VR["entry_time"] = VR["entry_time"].fillna(VR["bar_close"])
    AC = pd.read_csv(os.path.join(TD, "accounts_v4.csv"))
    nulls = {}
    for v in VARIANTS:
        P = VS[(VS["variant"] == v) & (VS["status"] == "DONE")]
        nulls[v] = Null(P, "pnl_equity", days_all)
    nullR = Null(VS[(VS["variant"] == "base") & (VS["status"] == "DONE")], "R", days_all)
    nulls_r = {v: Null(VS[(VS["variant"] == v) & (VS["status"] == "DONE")], "r_not", days_all) for v in VARIANTS}

    # -------------------------------------------------------------- X1 shadow variants on the accounts' own trades
    E = VR[(VR["acct_status"] == "ENTERED") & VR["grp"].isin(["core", "ds", "flip"])]
    piv = E.pivot_table(index="sig_id", columns="variant", values="pnl_equity")
    st = E.pivot_table(index="sig_id", columns="variant", values="status", aggfunc="first")
    meta = E.drop_duplicates("sig_id").set_index("sig_id")[["grp", "day", "account_id", "timeframe"]]
    pvs = VS[VS["status"] == "DONE"].pivot_table(index="sig_id", columns="variant", values="pnl_equity")
    rows = []
    for v in VARIANTS:
        if v not in piv or v == "base":
            continue
        for g in ("core+ds", "flip"):
            m = meta["grp"].isin(["core", "ds"]) if g == "core+ds" else meta["grp"].eq("flip")
            both = piv.loc[m[m].index, ["base", v]].dropna()
            d = both[v] - both["base"]
            dd = meta.loc[both.index, "day"]
            byday = d.groupby(dd.values).sum()
            cnt = d.groupby(dd.values).size()
            k = len(byday)
            bi = rng.integers(0, k, size=(a.boot, k))
            bm = byday.to_numpy()[bi].sum(1) / cnt.to_numpy()[bi].sum(1)
            s = st.loc[m[m].index, v]
            # the same variant on random entries (synthetic pool): variant minus base
            pv = pvs[["base", v]].dropna() if v in pvs else pd.DataFrame()
            pdiff = (pv[v] - pv["base"]).mean() if len(pv) else np.nan
            rows.append({"variant": v, "accounts": g, "trades": int(len(s)), "done": int((s == "DONE").sum()),
                         "no_entry": int((s == "NOENTRY").sum()), "open": int((s == "OPEN").sum()),
                         "pairs": len(both), "base_wallet_pct": 100 * both["base"].mean(),
                         "variant_wallet_pct": 100 * both[v].mean(), "diff_pct": 100 * d.mean(),
                         "diff_ci_lo": 100 * np.percentile(bm, 5), "diff_ci_hi": 100 * np.percentile(bm, 95),
                         "p_diff_le0": float((1 + (bm <= 0).sum()) / (a.boot + 1)),
                         "share_better": float((d > 0).mean()), "share_worse": float((d < 0).mean()),
                         "coinflip_pool_diff_pct": 100 * pdiff})
    XS = pd.DataFrame(rows)
    save(XS, "x_shadow_variant_summary.csv")
    # per account x variant: shadow account curve and the luck test
    rows = []
    finals = AC.set_index("account_id")["final"]
    for (aid, v), g in E[E["grp"].isin(["core", "ds", "flip"])].groupby(["account_id", "variant"]):
        dn = g[g["status"] == "DONE"].sort_values("exit_time")
        eq, bust = 5000.0, False
        for x in dn["pnl_equity"].to_numpy(float):
            eq *= (1 + x)
            if eq < 10:
                bust = True
                break
        t = nulls[v].test(dn, "pnl_equity") if v in nulls else {}
        h1 = dn[dn["half"] == "H1"]["pnl_equity"]
        h2 = dn[dn["half"] == "H2"]["pnl_equity"]
        rows.append({"account_id": aid, "grp": g["grp"].iloc[0], "variant": v, "trades": len(g), "done": len(dn),
                     "no_entry": int((g["status"] == "NOENTRY").sum()), "open": int((g["status"] == "OPEN").sum()),
                     "mean_wallet_pct": 100 * dn["pnl_equity"].mean(), "mean_R": dn["R"].mean(),
                     "mean_r_notional_pct": 100 * dn["r_not"].mean(),
                     "win_pct": 100 * (dn["pnl_equity"] > 0).mean() if len(dn) else np.nan,
                     "shadow_final": eq, "bust": bust, "actual_final": finals.get(aid, np.nan),
                     "h1_wallet_pct": 100 * h1.mean() if len(h1) else np.nan,
                     "h2_wallet_pct": 100 * h2.mean() if len(h2) else np.nan,
                     **{f"L_{k}": t.get(k) for k in ("null_mean", "excess", "z", "p_better", "p_worse")}})
    XA = pd.DataFrame(rows)
    base_fin = XA[XA["variant"] == "base"].set_index("account_id")["shadow_final"]
    XA["base_shadow_final"] = XA["account_id"].map(base_fin)
    fam = XA["grp"].isin(["core", "ds"]) & (XA["done"] >= 10) & XA["L_p_better"].notna()
    XA.loc[fam, "L_q"] = bh(XA.loc[fam, "L_p_better"])
    save(XA, "x_shadow_account_variant.csv")
    sumv = XA[XA["grp"].isin(["core", "ds"])].groupby("variant").apply(lambda g: pd.Series({
        "accounts": len(g), "beats_actual_final": int((g["shadow_final"] > g["actual_final"]).sum()),
        "beats_base_shadow": int((g["shadow_final"] > g["base_shadow_final"]).sum()),
        "profit_accounts": int((g["shadow_final"] > 5000).sum()), "bust": int(g["bust"].sum()),
        "median_final": g["shadow_final"].median(), "best_final": g["shadow_final"].max(),
        "tested": int(g["L_q"].notna().sum()), "raw_p05": int((g["L_p_better"] < 0.05).sum()),
        "bh_pass": int((g["L_q"] < 0.05).sum())}), include_groups=False).reset_index()
    save(sumv, "x_shadow_variant_accounts.csv")
    FX["shadow_tests"] = int(fam.sum())
    FX["shadow_bh_pass"] = int((XA["L_q"] < 0.05).sum())
    FX["shadow_raw_p05"] = int((XA.loc[fam, "L_p_better"] < 0.05).sum())
    FX["shadow_expected_raw"] = 0.05 * int(fam.sum())
    FX["shadow_min_q"] = float(XA["L_q"].min()) if XA["L_q"].notna().any() else None

    # quality (d3 only) and limit (d3) -----------------------------------------------------------
    d3 = pd.read_csv(os.path.join(a.extracted_dir, "current", "d3_shadows.csv"),
                     usecols=["key", "day", "kind", "account_id", "symbol", "timeframe", "side", "filled", "roe",
                              "exit_reason", "resolved", "data"])
    FX["d3_days_utc"] = [d3["day"].min(), d3["day"].max()]
    FX["d3_rows"] = len(d3)
    FX["d3_kinds"] = d3["kind"].value_counts().to_dict()
    rep_p = os.path.join(a.extracted_dir, "current", "d3_reports.csv")
    if os.path.exists(rep_p):
        rep = pd.read_csv(rep_p)
        pars_all = [json.loads(x).get("parity") for x in rep["data"]]
        pars = [p_ for p_ in pars_all if isinstance(p_, dict)]
        FX["d3_parity_not_dict"] = [str(p_)[:120] for p_ in pars_all if not isinstance(p_, dict)]
        FX["d3_nights"] = len(pars)
        FX["d3_parity_accounts_per_night"] = int(np.median([p_.get("accounts", 0) for p_ in pars])) if pars else 0
        FX["d3_parity_mismatched_total"] = int(sum(p_.get("mismatched_accounts", 0) for p_ in pars))
        sv = {}
        for x in rep["data"]:
            shd = json.loads(x).get("shadows")
            stv = shd.get("stop_variants") if isinstance(shd, dict) else None
            for k, v in (stv if isinstance(stv, dict) else {}).items():
                o = sv.setdefault(k, {"losing_trades": 0, "better_than_actual": 0, "turned_positive": 0})
                for kk in o:
                    o[kk] += int(v.get(kk) or 0)
        FX["d3_stop_variants_losers"] = sv
    sl_p = os.path.join(a.base_dir, "stop_slips_summary.csv")
    if os.path.exists(sl_p):
        sl = pd.read_csv(sl_p)
        sl = sl[sl["run"] == "current"]
        save(sl, "x_stop_slips.csv")
        al = sl[sl["exit_reason"] == "*"]
        if len(al):
            al = al.iloc[0]
            FX["stop_slips"] = {"exits": int(al["exits"]), "with_real": int(al["with_real"]),
                                "paper_bps": float(al["paper_bps_median"]), "real_bps": float(al["real_bps_median"]),
                                "real_bps_p90": float(al["real_bps_p90"]), "diff_usd_sum": float(al["diff_usd_sum"])}
    q = d3[d3["kind"].isin(["quality", "base"])].copy()
    q["pe"] = q["data"].map(lambda s: json.loads(s).get("pnl_equity") if isinstance(s, str) else None)
    qq = q.pivot_table(index=q["key"].str.split("|", n=1).str[1], columns="kind", values="pe").dropna()
    FX["quality_pairs"] = len(qq)
    FX["quality_base_pct"] = float(100 * qq["base"].mean()) if len(qq) else None
    FX["quality_pct"] = float(100 * qq["quality"].mean()) if len(qq) else None
    lim = d3[d3["kind"] == "limit"].copy()
    lim["bc"] = lim["key"].str.split("|").str[3].astype("int64")
    mk = RP[["account_id", "symbol", "bar_close", "roe", "status", "grp", "timeframe"]].rename(columns={"roe": "mkt_roe"})
    L = lim.merge(mk, left_on=["account_id", "symbol", "bc"], right_on=["account_id", "symbol", "bar_close"], how="inner")
    L = L[(L["status"] == "TRADED") & (L["resolved"] == 1)]
    L["lim_roe0"] = np.where(L["filled"] == 1, L["roe"].fillna(0), 0.0)
    LS = L.groupby(["grp", "timeframe_x"]).agg(signals=("mkt_roe", "size"), fill_share=("filled", "mean"),
                                               market_roe=("mkt_roe", "mean"),
                                               limit_roe_if_filled=("roe", "mean"),
                                               market_roe_same_filled=("mkt_roe", lambda s: s[L.loc[s.index, "filled"] == 1].mean()),
                                               limit_roe_all=("lim_roe0", "mean")).reset_index()
    save(LS, "x_limit_entry.csv")

    # -------------------------------------------------------------- X2 every signal per cell x variant
    rows = []
    VRc = VR[VR["grp"].isin(["core", "ds"]) & (VR["status"] == "DONE")]
    for (aid, v), g in VRc.groupby(["account_id", "variant"]):
        if len(g) < 10:
            continue
        t = nulls[v].test(g, "pnl_equity")
        op = one_position(g)
        h1 = g[g["half"] == "H1"]
        h2 = g[g["half"] == "H2"]
        rows.append({"account_id": aid, "grp": g["grp"].iloc[0], "variant": v, "signals": len(g),
                     "signals_per_day": len(g) / F0["v4_days"], "one_pos_trades": len(op),
                     "one_pos_per_day": len(op) / F0["v4_days"],
                     "mean_wallet_pct": 100 * g["pnl_equity"].mean(), "mean_R": g["R"].mean(),
                     "mean_r_notional_pct": 100 * g["r_not"].mean(), "win_pct": 100 * (g["pnl_equity"] > 0).mean(),
                     "h1_n": len(h1), "h1_wallet_pct": 100 * h1["pnl_equity"].mean() if len(h1) else np.nan,
                     "h2_n": len(h2), "h2_wallet_pct": 100 * h2["pnl_equity"].mean() if len(h2) else np.nan,
                     "one_pos_wallet_pct": 100 * op["pnl_equity"].mean(),
                     **{f"L_{k}": t.get(k) for k in ("null_mean", "excess", "z", "p_better", "p_worse")}})
    XC = pd.DataFrame(rows)
    m = XC["L_p_better"].notna()
    XC.loc[m, "L_q"] = bh(XC.loc[m, "L_p_better"])
    save(XC, "x_allsig_cell_variant.csv")
    FX["allsig_tests"] = int(m.sum())
    FX["allsig_bh_pass"] = int((XC["L_q"] < 0.05).sum())
    FX["allsig_raw_p05"] = int((XC.loc[m, "L_p_better"] < 0.05).sum())
    FX["allsig_min_q"] = float(XC["L_q"].min()) if XC["L_q"].notna().any() else None
    xb = XC[XC["variant"] == "base"]
    FX["allsig_base_cells"] = len(xb)
    FX["allsig_base_positive"] = int((xb["mean_wallet_pct"] > 0).sum())
    FX["allsig_base_both_halves_positive"] = int(((xb["h1_wallet_pct"] > 0) & (xb["h2_wallet_pct"] > 0)).sum())
    FX["allsig_base_both_halves_expected"] = float(len(xb) * (xb["h1_wallet_pct"] > 0).mean() * (xb["h2_wallet_pct"] > 0).mean())
    FX["allsig_any_variant_both_halves_positive"] = int(((XC["h1_wallet_pct"] > 0) & (XC["h2_wallet_pct"] > 0)).sum())
    FX["allsig_cells_variants"] = len(XC)
    # signals the accounts took vs could not take (base exits, every signal replayed alone)
    st2 = RP[RP["status"] == "TRADED"].copy()
    st2["acct"] = st2["acct_status"].fillna("none") + ":" + st2["acct_reason"].fillna("").str.split(":").str[0]
    save(st2.groupby(["grp", "timeframe", "acct"]).agg(n=("R", "size"), mean_R=("R", "mean"),
                                                         win_pct=("roe", lambda s: 100 * (s > 0).mean()),
                                                         mean_wallet_pct=("pnl", lambda s: 100 * s.mean() / 5000)
                                                         ).reset_index(), "x_taken_vs_missed.csv")
    # pooled per tf x variant (every signal, core + ds) vs the coin-flip pool of the same variant
    rows = []
    for (tf, v), g in VRc.groupby(["timeframe", "variant"]):
        p = VS[(VS["variant"] == v) & (VS["status"] == "DONE") & (VS["timeframe"] == tf)]
        rows.append({"timeframe": tf, "variant": v, "signals": len(g), "mean_wallet_pct": 100 * g["pnl_equity"].mean(),
                     "mean_r_notional_pct": 100 * g["r_not"].mean(), "win_pct": 100 * (g["pnl_equity"] > 0).mean(),
                     "pool_n": len(p), "pool_wallet_pct": 100 * p["pnl_equity"].mean(),
                     "pool_win_pct": 100 * (p["pnl_equity"] > 0).mean()})
    XT = pd.DataFrame(rows)
    VSd = VS[VS["status"] == "DONE"].copy()
    VSd["half"] = np.where(VSd["bar_close"] < mid, "H1", "H2")
    ex_rows = []
    for (tf, v), g in VRc.groupby(["timeframe", "variant"]):
        p = VSd[(VSd["variant"] == v) & (VSd["timeframe"] == tf)]
        e = sameday_excess(g, p, "pnl_equity")
        ex_rows.append({"timeframe": tf, "variant": v,
                        "h1_wallet_pct": 100 * g.loc[g["half"] == "H1", "pnl_equity"].mean(),
                        "h2_wallet_pct": 100 * g.loc[g["half"] == "H2", "pnl_equity"].mean(),
                        "pool_h1_wallet_pct": 100 * p.loc[p["half"] == "H1", "pnl_equity"].mean(),
                        "pool_h2_wallet_pct": 100 * p.loc[p["half"] == "H2", "pnl_equity"].mean(),
                        "sameday_excess_pct": 100 * e.get("excess", np.nan), "sameday_days_pos": e.get("days_pos"),
                        "sameday_days": e.get("days"), "sameday_t": e.get("t")})
    XT = XT.merge(pd.DataFrame(ex_rows), on=["timeframe", "variant"], how="left")
    save(XT, "x_allsig_tf_variant.csv")
    FX["allsig_tf_variant_sameday_t_max"] = float(XT["sameday_t"].max())
    FX["allsig_tf_variant_sameday_pos"] = int((XT["sameday_excess_pct"] > 0).sum())
    FX["allsig_tf_variant_rows"] = len(XT)

    # -------------------------------------------------------------- X3 conditions (base exits, every signal)
    X = RP[(RP["status"] == "TRADED") & RP["grp"].isin(["core", "ds"])].copy()
    ctx = ctx_features(os.path.join(a.extracted_dir, "current", "signal_ctx.jsonl"), set(X["sig_id"].astype(int)))
    X = X.merge(ctx, on="sig_id", how="left")
    feats = add_levels(X)
    X["Rf"] = X["flip_R"]
    rows = []
    for gname, gx in (("core+ds", X), ("core", X[X["grp"] == "core"]), ("ds", X[X["grp"] == "ds"])):
        for tf in ["all", "15m", "30m", "1h", "4h"]:
            x = gx if tf == "all" else gx[gx["timeframe"] == tf]
            for f in feats:
                for lev, g in x.groupby(f):
                    h1, h2 = g[g["half"] == "H1"]["R"], g[g["half"] == "H2"]["R"]
                    rows.append({"group": gname, "tf": tf, "feature": f[2:], "level": lev, "n": len(g),
                                 "mean_R": g["R"].mean(), "n_h1": len(h1), "R_h1": h1.mean(), "n_h2": len(h2),
                                 "R_h2": h2.mean(), "R_all_tf": x["R"].mean()})
    CP = pd.DataFrame(rows)
    P0b = VS[(VS["variant"] == "base") & (VS["status"] == "DONE")]
    chk = []
    for r in CP[(CP["R_h1"] > 0) & (CP["n_h2"] >= 50) & (CP["level"] != "na")].itertuples():
        gx = X if r.group == "core+ds" else X[X["grp"] == r.group]
        x = gx if r.tf == "all" else gx[gx["timeframe"] == r.tf]
        s2 = x[(x["f_" + r.feature] == r.level) & (x["half"] == "H2")]
        e = sameday_excess(s2, P0b, "R")
        chk.append({"group": r.group, "tf": r.tf, "feature": r.feature, "level": r.level, "n_h1": r.n_h1, "R_h1": r.R_h1,
                    "n_h2": r.n_h2, "R_h2": r.R_h2, "h2_sameday_excess_R": e.get("excess"), "h2_days_pos": e.get("days_pos"),
                    "h2_days": e.get("days"), "h2_t": e.get("t")})
    CK = pd.DataFrame(chk)
    save(CK, "x_cond_pooled_h1pick_h2check.csv")
    FX["cond_pooled_picks"] = len(CK)
    FX["cond_pooled_picks_h2_pos"] = int((CK["R_h2"] > 0).sum()) if len(CK) else 0
    FX["cond_pooled_picks_h2_excess_t2"] = int((CK["h2_t"] > 2).sum()) if len(CK) else 0
    save(CP, "x_cond_pooled.csv")
    # coin-flip pool with the same simple filters (side, coin, session, weekend)
    P0 = VS[(VS["variant"] == "base") & (VS["status"] == "DONE")].copy()
    P0["half"] = np.where(P0["bar_close"] < mid, "H1", "H2")
    add_levels_simple = {"side": np.where(P0["side"] > 0, "long", "short"), "coin": P0["symbol"].str.replace("USDT", "")}
    hh = pd.to_datetime(P0["bar_close"] + KST, unit="ms")
    add_levels_simple["session"] = pd.cut(hh.dt.hour, [-1, 5, 11, 17, 23], labels=["00-06", "06-12", "12-18", "18-24"]).astype(str)
    add_levels_simple["weekend"] = np.where(hh.dt.dayofweek >= 5, "weekend", "weekday")
    rows = []
    for f, vals in add_levels_simple.items():
        P0["_f"] = vals
        for tf in ["all", "15m", "30m", "1h", "4h"]:
            x = P0 if tf == "all" else P0[P0["timeframe"] == tf]
            for lev, g in x.groupby("_f"):
                rows.append({"tf": tf, "feature": f, "level": lev, "n": len(g), "pool_R": g["R"].mean(),
                             "pool_R_h1": g.loc[g["half"] == "H1", "R"].mean(),
                             "pool_R_h2": g.loc[g["half"] == "H2", "R"].mean()})
    save(pd.DataFrame(rows), "x_cond_pool_simple.csv")
    # cell-level pick (H1) / check (H2), and the side-flip placebo, and the reverse direction
    cells = []
    for aid, g in X.groupby("account_id"):
        for f in feats:
            for lev, s in g.groupby(f):
                if lev == "na":
                    continue
                a1, a2 = s[s["half"] == "H1"], s[s["half"] == "H2"]
                if len(a1) < 15 or len(a2) < 10:
                    continue
                cells.append({"account_id": aid, "grp": s["grp"].iloc[0], "tf": s["timeframe"].iloc[0],
                              "feature": f[2:], "level": lev, "n_h1": len(a1), "n_h2": len(a2),
                              "R_h1": a1["R"].mean(), "R_h2": a2["R"].mean(),
                              "t_h1": a1["R"].mean() / (a1["R"].std(ddof=1) / math.sqrt(len(a1))) if a1["R"].std(ddof=1) > 0 else np.nan,
                              "t_h2": a2["R"].mean() / (a2["R"].std(ddof=1) / math.sqrt(len(a2))) if a2["R"].std(ddof=1) > 0 else np.nan,
                              "Rf_h1": a1["Rf"].mean(), "Rf_h2": a2["Rf"].mean(),
                              "cell_R_h1": g.loc[g["half"] == "H1", "R"].mean(),
                              "cell_R_h2": g.loc[g["half"] == "H2", "R"].mean()})
    CC = pd.DataFrame(cells)
    save(CC, "x_cond_cells.csv")
    pick = CC[(CC["R_h1"] > 0.1) & (CC["t_h1"] > 1.5)]
    plac = CC[(CC["Rf_h1"] > 0.1)]
    rev = CC[(CC["R_h2"] > 0.1) & (CC["t_h2"] > 1.5)]
    FX["cond_subsets"] = len(CC)
    FX["cond_picks"] = len(pick)
    FX["cond_picks_h1_meanR"] = float(np.average(pick["R_h1"], weights=pick["n_h1"])) if len(pick) else None
    FX["cond_picks_h2_meanR"] = float(np.average(pick["R_h2"], weights=pick["n_h2"])) if len(pick) else None
    FX["cond_picks_h2_positive_share"] = float((pick["R_h2"] > 0).mean()) if len(pick) else None
    FX["cond_all_h2_positive_share"] = float((CC["R_h2"] > 0).mean()) if len(CC) else None
    FX["cond_placebo_picks"] = len(plac)
    FX["cond_placebo_h2_positive_share"] = float((plac["Rf_h2"] > 0).mean()) if len(plac) else None
    FX["cond_placebo_h2_meanR"] = float(np.average(plac["Rf_h2"], weights=plac["n_h2"])) if len(plac) else None
    FX["cond_reverse_picks"] = len(rev)
    FX["cond_reverse_h1_positive_share"] = float((rev["R_h1"] > 0).mean()) if len(rev) else None
    FX["cond_reverse_h1_meanR"] = float(np.average(rev["R_h1"], weights=rev["n_h1"])) if len(rev) else None
    # the picks that held: positive in H2 with t_h2 > 1, then the honest luck test on H2 only
    held = pick[(pick["R_h2"] > 0)].copy()
    lrows = []
    for r in held.itertuples(index=False):
        s = X[(X["account_id"] == r.account_id) & (X["f_" + r.feature] == r.level) & (X["half"] == "H2")]
        s = s.rename(columns={"timeframe": "timeframe"})
        t = nullR.test(s, "R")
        lrows.append({**r._asdict(), **{f"L2_{k}": t.get(k) for k in ("null_mean", "excess", "z", "p_better")}})
    HD = pd.DataFrame(lrows)
    if len(HD):
        HD["L2_q"] = bh(HD["L2_p_better"].fillna(1.0))
    save(HD, "x_cond_picks_held.csv")
    FX["cond_held"] = len(HD)
    FX["cond_held_bh_pass"] = int((HD["L2_q"] < 0.05).sum()) if len(HD) else 0
    FX["cond_held_raw_p05"] = int((HD["L2_p_better"] < 0.05).sum()) if len(HD) else 0

    # -------------------------------------------------------------- X4 goal path
    T = pd.read_csv(os.path.join(a.base_dir, "trades_enriched.csv"), low_memory=False)
    T = T[T["run"] == "current"].copy()
    T["day"] = kday(T["entry_time"])
    T["r_not"] = T["roe"] / T["leverage"]
    cols = ["r_not", "stop_frac", "day", "timeframe", "symbol", "side"]
    cand = []
    for aid, g in T[T["kind"].isin(["strategy", "ds200"])].groupby("account_id"):
        if len(g) >= 10 and g["r_not"].mean() > 0:
            cand.append(("account", aid, "real trades (house exits)", "base", g[cols]))
    top_av = XA[XA["grp"].isin(["core", "ds"]) & (XA["done"] >= 10) & (XA["mean_r_notional_pct"] > 0)
                & (XA["variant"] != "base")].sort_values("L_p_better").head(20)
    for r in top_av.itertuples(index=False):
        g = E[(E["account_id"] == r.account_id) & (E["variant"] == r.variant) & (E["status"] == "DONE")]
        cand.append(("account x shadow", r.account_id, r.variant, r.variant, g[cols]))
    top_cv = XC[(XC["mean_r_notional_pct"] > 0)].sort_values("L_p_better").head(20)
    for r in top_cv.itertuples(index=False):
        g = VRc[(VRc["account_id"] == r.account_id) & (VRc["variant"] == r.variant)]
        cand.append(("every signal (one position)", r.account_id, r.variant, r.variant, one_position(g)[cols]))
    if len(HD):
        for r in HD.sort_values("L2_p_better").head(10).itertuples(index=False):
            s = X[(X["account_id"] == r.account_id) & (X["f_" + r.feature] == r.level) & (X["half"] == "H2")].copy()
            s["r_not"] = s["roe"] / s["leverage"]
            cand.append(("filter (H2 check only)", r.account_id, f"{r.feature}={r.level}", "base", one_position(s)[cols]))
    h2days = sorted(set(kday(np.arange(mid, hi, HOUR))))
    ref = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ref5y.csv"))
    ref = ref[ref["kind"] == "strategy"]
    ref5 = dict(zip(ref["strategy"] + "@" + ref["timeframe"], ref["test_mean"]))
    expo = (T["margin_frac"] * T["leverage"]).groupby(T["account_id"]).mean().to_dict()
    rows = []
    for kind, aid, what, nv, df in cand:
        df = df[np.isfinite(df["r_not"]) & np.isfinite(df["stop_frac"])]
        if len(df) < 5:
            continue
        r, stop, dd = df["r_not"].to_numpy(float), df["stop_frac"].to_numpy(float), df["day"].to_numpy()
        dl = h2days if kind.startswith("filter") else days_all
        res = goal_path(r, stop, dd, dl, rng, a.boot)
        t = nulls_r[nv].test(df, "r_not")
        shift = (t.get("null_mean", np.nan) - t.get("obs_mean", np.nan)) if t.get("n", 0) >= 2 else np.nan
        resn = goal_path(r, stop, dd, dl, rng, a.boot, shift=shift) if shift == shift else None
        t5 = ref5.get(aid)
        sh5 = (t5 / expo.get(aid, 9.0) - r.mean()) if t5 is not None and t5 == t5 else np.nan
        res5 = goal_path(r, stop, dd, dl, rng, a.boot, shift=sh5) if sh5 == sh5 else None
        for k, o in enumerate(res):
            rows.append({"kind": kind, "account_id": aid, "what": what, "n": len(r),
                         "mean_r_notional_pct": 100 * r.mean(), "median_r_notional_pct": 100 * np.median(r),
                         "null_r_notional_pct": 100 * t.get("null_mean", np.nan), "luck_p": t.get("p_better"),
                         "win_pct": 100 * (r > 0).mean(), "days": len(dl), "small_sample": len(r) < 30, **o,
                         "luck_only_p_final_x6": resn[k]["p_final_x6"] if resn else np.nan,
                         "luck_only_p_-50_first": resn[k]["p_-50_first"] if resn else np.nan,
                         "luck_only_median_final_x": resn[k]["median_final_x"] if resn else np.nan,
                         "fiveyear_r_notional_pct": 100 * (r.mean() + sh5) if sh5 == sh5 else np.nan,
                         "fiveyear_p_final_x6": res5[k]["p_final_x6"] if res5 else np.nan,
                         "fiveyear_median_final_x": res5[k]["median_final_x"] if res5 else np.nan})
    GP = pd.DataFrame(rows)
    save(GP, "x_goal_path.csv")
    if len(GP):
        g40 = GP[(GP["m"] == 0.40) & (GP["L"] == 30)]
        FX["goal_candidates"] = int(g40["account_id"].astype(str).str.cat(g40["what"].astype(str)).nunique())
        FX["goal_max_p_final_x6_40x30"] = float(g40["p_final_x6"].max())
        FX["goal_median_p_-50_first_40x30"] = float(g40["p_-50_first"].median())
        FX["goal_needed_exposure_finite"] = int(g40["needed_exposure_x6"].notna().sum())
    with open(os.path.join(a.out_dir, "facts_extra.json"), "w") as fh:
        json.dump(FX, fh, ensure_ascii=False, indent=1, default=float)
    print(json.dumps(FX, ensure_ascii=False, indent=1, default=float)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
