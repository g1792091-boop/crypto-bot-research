#!/usr/bin/env python3
"""Rule-bot paper results, every account: the numbers behind REPORT_KO.md.

    python3 rb1024.py <extracted_dir> <base_dir> <randpool.csv> <ref5y.csv> <out_dir> [--boot 4000] [--seed 20261024]

<extracted_dir>  the export extracted by extract_zip.py (run folders current/ and run-*/)
<base_dir>       output of analysis/rulebot_1007/scripts/analyze.py on the same folder (trades_enriched.csv,
                 replay_signals.csv with the side flip, signal_flow.csv, ...)
<randpool.csv>   output of randpool.py (a long and a short entry at every bar close, replayed with the house exits)
<ref5y.csv>      output of ref5y_build.py (5-year default-number results per strategy x timeframe)
<out_dir>        tables/*.csv and facts.json are written here

Reads CSVs only; imports nothing from the repository or the export.

Definitions (all money in USDT, each account starts at $5,000; times in KST = UTC+9):
  R          net P&L / (qty x |entry - initial stop|): -1R = a clean stop hit before costs
  gross R    the same before fees and funding ("direction R")
  wallet %   net P&L of a trade / wallet before the trade
  max DD     the bot's own drawdown record (equity every 5 min, open positions marked), maximum over the run
  matched coin flip (luck test A): each trade of the account is replaced by a synthetic entry of the same timeframe,
             coin and side from randpool.csv on a randomly drawn day (one draw per real trading day, shared by all
             accounts in one simulation, so the accounts' dependence on the common market is kept). It keeps the
             account's long/short mix, coins and trade count, so a short-heavy account in a falling market gets the
             same market help in the null. p = share of simulations whose mean R >= the account's.
  net-profit test (C): day-block bootstrap of the account's mean net R (resample its trading days).
  balanced side flip (B): every signal of the cell replayed with both sides (analyze.py); excess = (R_chosen -
             R_other)/2, averaged separately over long and short signals and then the two averaged, so the falling
             market's push cancels; cluster sign-flip p (clusters = signal bar floored to max(tf, 1h)).
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
EQ0 = 5000.0
CUT_1017 = 1792194000000      # 2026-10-17 08:40 KST (= 10-16 23:40 UTC): end of the data used by docs/live1019-analysis-ko.md
TFS = ["5m", "15m", "30m", "1h", "4h"]
TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}
GRP_ORDER = ["core", "ds", "reel", "flip", "flip5"]
RUN_LABEL = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}


def bh(p: np.ndarray) -> np.ndarray:
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


def longest_streak(flags) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def grp_of(kind: str, tf: str) -> str:
    if kind == "strategy":
        return "core"
    if kind == "ds200":
        return "ds"
    if kind == "reel":
        return "reel"
    if kind == "random":
        return "flip5" if tf == "5m" else "flip"
    return "other"


def kst_day(ms) -> pd.Series:
    return pd.to_datetime(pd.Series(ms, dtype="float64") + KST, unit="ms").dt.strftime("%m-%d")


# ------------------------------------------------------------------------------------------------ loading
def load(a):
    T = pd.read_csv(os.path.join(a.base_dir, "trades_enriched.csv"), low_memory=False)
    T["label"] = T["run"].map(RUN_LABEL).fillna(T["run"])
    T["grp"] = [grp_of(k, tf) for k, tf in zip(T["kind"], T["tf"])]
    T["wallet_pct"] = T["pnl"] / T["eq_before"]
    T["gross_R"] = T["gross"] / T["risk_usd"]
    T["entry_kday"] = kst_day(T["entry_time"]).values
    T["exit_kday"] = kst_day(T["exit_time"]).values
    T["dow"] = (pd.to_datetime(T["entry_time"] + KST, unit="ms")).dt.dayofweek.values
    accs = {}
    for name in os.listdir(a.extracted_dir):
        p = os.path.join(a.extracted_dir, name, "accounts.csv")
        if os.path.exists(p):
            x = pd.read_csv(p)
            x["run"] = name
            x["label"] = RUN_LABEL.get(name, name)
            x["grp"] = [grp_of(k, tf) for k, tf in zip(x["kind"], x["timeframe"])]
            accs[name] = x
    A = pd.concat(accs.values(), ignore_index=True)
    return T, A


def run_span(a, name: str) -> tuple[int, int]:
    d = os.path.join(a.extracted_dir, name)
    acc = pd.read_csv(os.path.join(d, "accounts.csv"))
    lo = int(acc["created_ts"].min())
    his = []
    for f, c in (("trades.csv", "exit_time"), ("signal_log.csv", "bar_close"), ("live_bars.csv", "ts")):
        p = os.path.join(d, f)
        if os.path.exists(p):
            x = pd.read_csv(p, usecols=[c])
            if len(x):
                his.append(int(x[c].max()))
    return lo, max(his)


# ------------------------------------------------------------------------------------------------ summaries
def summ(g: pd.DataFrame) -> dict:
    n = len(g)
    if n == 0:
        return {"n": 0}
    pnl = g["pnl"].to_numpy(float)
    w = pnl > 0
    pos, neg = pnl[w].sum(), pnl[~w].sum()
    return {"n": n, "win_pct": 100 * w.mean(), "pnl": pnl.sum(), "gross": g["gross"].sum(),
            "fees": g["fees"].sum(), "funding": g["funding"].sum(),
            "mean_R": g["R"].mean(), "mean_gross_R": g["gross_R"].mean(), "mean_cost_R": g["cost_R"].mean(),
            "mean_wallet_pct": 100 * g["wallet_pct"].mean(), "mean_roe_pct": 100 * g["roe"].mean(),
            "pf": pos / -neg if neg < 0 else np.inf,
            "avg_win_usd": pnl[w].mean() if w.any() else np.nan, "avg_loss_usd": pnl[~w].mean() if (~w).any() else np.nan,
            "long_share": float((g["side"] > 0).mean())}


def by(T: pd.DataFrame, keys) -> pd.DataFrame:
    rows = []
    for k, g in T.groupby(keys, sort=True):
        k = k if isinstance(k, tuple) else (k,)
        d = dict(zip(keys if isinstance(keys, list) else [keys], k))
        d.update(summ(g))
        rows.append(d)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------ market
def market(a, lo: int, hi: int):
    b = pd.read_csv(os.path.join(a.extracted_dir, "current", "live_bars.csv"), usecols=["ts", "symbol", "close"])
    b = b[(b["ts"] >= lo) & (b["ts"] <= hi)]
    rows = []
    for s, g in b.groupby("symbol"):
        g = g.sort_values("ts")
        c = g["close"].to_numpy(float)
        peak = np.maximum.accumulate(c)
        trough = np.minimum.accumulate(c)
        rows.append({"symbol": s, "first": c[0], "last": c[-1], "change_pct": 100 * (c[-1] / c[0] - 1),
                     "max_drop_pct": 100 * (1 - c / peak).max(), "max_rise_pct": 100 * (c / trough - 1).max(),
                     "high": c.max(), "low": c.min()})
    M = pd.DataFrame(rows)
    b["day"] = kst_day(b["ts"]).values
    piv = b.sort_values("ts").groupby(["day", "symbol"])["close"].last().unstack()
    first = b.sort_values("ts").groupby("symbol")["close"].first()
    prev = piv.shift(1)
    prev.iloc[0] = first
    D = 100 * (piv / prev - 1)
    D["eq6"] = D.mean(axis=1)
    return M, D.reset_index(), b


def window_move(bars: pd.DataFrame, lo: int, hi: int) -> float:
    x = bars[(bars["ts"] >= lo) & (bars["ts"] <= hi)].sort_values("ts").groupby("symbol")["close"]
    r = x.last() / x.first() - 1
    return 100 * float(r.mean())


# ------------------------------------------------------------------------------------------------ luck test A
class Pool:
    """Synthetic entries bucketed by (tf, symbol, side, KST entry day)."""

    def __init__(self, path: str):
        P = pd.read_csv(path)
        P = P[P["status"] == "TRADED"].copy()
        P["day"] = kst_day(P["bar_close"]).values
        self.P = P
        self.days = sorted(P["day"].unique())
        self.di = {d: i for i, d in enumerate(self.days)}
        self.keys = sorted({(tf, s, int(sd)) for tf, s, sd in zip(P["timeframe"], P["symbol"], P["side"])})
        self.ki = {k: i for i, k in enumerate(self.keys)}
        self.k2 = sorted({(tf, int(sd)) for tf, sd in zip(P["timeframe"], P["side"])})
        self.k2i = {k: i for i, k in enumerate(self.k2)}
        P["k"] = [self.ki[(tf, s, int(sd))] for tf, s, sd in zip(P["timeframe"], P["symbol"], P["side"])]
        P["k2"] = [self.k2i[(tf, int(sd))] for tf, sd in zip(P["timeframe"], P["side"])]
        P["d"] = P["day"].map(self.di)
        self.v1, self.st1, self.ct1 = self._index(P, "k", len(self.keys))
        self.v2, self.st2, self.ct2 = self._index(P, "k2", len(self.k2))
        # whole-period fallback per (tf, side)
        Q = P.sort_values("k2")
        self.v3 = Q["R"].to_numpy(float)
        c3 = Q.groupby("k2").size().reindex(range(len(self.k2)), fill_value=0).to_numpy()
        self.st3, self.ct3 = np.r_[0, np.cumsum(c3)[:-1]], c3

    def _index(self, P, kcol, nk):
        Q = P.sort_values([kcol, "d"])
        v = Q["R"].to_numpy(float)
        ct = np.zeros((nk, len(self.days)), np.int64)
        for (k, d), n in Q.groupby([kcol, "d"]).size().items():
            ct[k, d] = n
        st = np.r_[0, np.cumsum(ct.ravel())[:-1]].reshape(ct.shape)
        return v, st, ct

    def side_mean(self) -> pd.DataFrame:
        return self.P.groupby(["timeframe", "symbol", "side"])["R"].mean()


def _sim_means(pool: "Pool", k1, k2, dd, dmap, rng) -> np.ndarray:
    Dm = dmap[:, dd]                                   # B x n
    B = Dm.shape[0]
    u = rng.random(Dm.shape)
    c1 = pool.ct1[k1[None, :], Dm]
    s1 = pool.st1[k1[None, :], Dm]
    c2 = pool.ct2[k2[None, :], Dm]
    s2 = pool.st2[k2[None, :], Dm]
    c3 = pool.ct3[k2][None, :].repeat(B, 0)
    s3 = pool.st3[k2][None, :].repeat(B, 0)
    v = np.where(c1 > 0, pool.v1[np.minimum(s1 + (u * c1).astype(np.int64), len(pool.v1) - 1)],
                 np.where(c2 > 0, pool.v2[np.minimum(s2 + (u * c2).astype(np.int64), len(pool.v2) - 1)],
                          pool.v3[np.minimum(s3 + (u * c3).astype(np.int64), len(pool.v3) - 1)]))
    return v.mean(axis=1)


def luck_A(T4: pd.DataFrame, pool: Pool, B: int, rng) -> tuple[pd.DataFrame, np.ndarray, list]:
    """Matched coin flip per account (house exits, 15m..4h). p < 0.01 is refined with 100,000 more simulations
    (fresh day maps), so the smallest p can pass a BH cut over a few hundred accounts."""
    nd = len(pool.days)
    dmap = rng.integers(0, nd, size=(B, nd))          # day d -> day dmap[b, d], common to all accounts in sim b
    rows, sims, ids = [], [], []
    for aid, g in T4.groupby("account_id"):
        g = g[np.isfinite(g["R"])]
        keys = [(tf, s, int(sd)) for tf, s, sd in zip(g["tf"], g["symbol"], g["side"])]
        if not len(g) or any(k not in pool.ki for k in keys):
            continue
        k1 = np.array([pool.ki[k] for k in keys])
        k2 = np.array([pool.k2i[(k[0], k[2])] for k in keys])
        dd = np.array([pool.di.get(d, -1) for d in g["entry_kday"]])
        dd = np.where(dd < 0, 0, dd)
        m = _sim_means(pool, k1, k2, dd, dmap, rng)
        obs = float(g["R"].mean())
        eps = 1e-12
        hb, hw, nb = int((m >= obs - eps).sum()), int((m <= obs + eps).sum()), B
        if min(hb, hw) + 1 < 0.01 * (B + 1):
            for _ in range(10):
                mm = _sim_means(pool, k1, k2, dd, rng.integers(0, nd, size=(10_000, nd)), rng)
                hb += int((mm >= obs - eps).sum())
                hw += int((mm <= obs + eps).sum())
                nb += 10_000
        rows.append({"account_id": aid, "A_n": len(g), "A_obs_R": obs, "A_null_mean_R": float(m.mean()),
                     "A_null_sd_R": float(m.std(ddof=1)), "A_excess_R": obs - float(m.mean()),
                     "A_p_better": (1 + hb) / (nb + 1), "A_p_worse": (1 + hw) / (nb + 1)})
        sims.append(m)
        ids.append(aid)
    return pd.DataFrame(rows), (np.vstack(sims) if sims else np.zeros((0, B))), ids


def luck_C(T4: pd.DataFrame, B: int, rng) -> pd.DataFrame:
    """Day-block bootstrap of the mean net R: p = P*(mean <= 0)."""
    rows = []
    for aid, g in T4.groupby("account_id"):
        g = g[np.isfinite(g["R"])]
        if len(g) < 2:
            continue
        days = g.groupby("entry_kday")["R"].agg(["sum", "size"])
        s, c = days["sum"].to_numpy(float), days["size"].to_numpy(float)
        k = len(days)
        idx = rng.integers(0, k, size=(B, k))
        means = s[idx].sum(1) / c[idx].sum(1)
        le, ge, nb = int((means <= 0).sum()), int((means >= 0).sum()), B
        if min(le, ge) + 1 < 0.01 * (B + 1):
            for _ in range(10):
                ii = rng.integers(0, k, size=(10_000, k))
                mm = s[ii].sum(1) / c[ii].sum(1)
                le += int((mm <= 0).sum())
                ge += int((mm >= 0).sum())
                nb += 10_000
        rows.append({"account_id": aid, "C_days": k, "C_p_le0": (1 + le) / (nb + 1),
                     "C_p_ge0": (1 + ge) / (nb + 1),
                     "C_ci_lo": float(np.percentile(means, 5)), "C_ci_hi": float(np.percentile(means, 95))})
    return pd.DataFrame(rows)


def luck_B(base_dir: str, B: int, rng) -> pd.DataFrame:
    """Balanced side flip per cell (current run), cluster sign-flip."""
    RP = pd.read_csv(os.path.join(base_dir, "replay_signals.csv"), low_memory=False,
                     usecols=["run", "bar_close", "timeframe", "strategy", "symbol", "side", "status", "R",
                              "flip_status", "flip_R", "account_id", "kind"])
    x = RP[(RP["run"] == "current") & (RP["status"] == "TRADED") & (RP["flip_status"] == "TRADED")].copy()
    x = x[np.isfinite(x["R"]) & np.isfinite(x["flip_R"])]
    blk = np.maximum(x["timeframe"].map(TF_MIN).fillna(60).to_numpy() * MIN, HOUR)
    x["cl"] = (x["bar_close"].to_numpy() // blk).astype(np.int64)
    rows = []
    for aid, g in x.groupby("account_id"):
        h = 0.5 * (g["R"].to_numpy(float) - g["flip_R"].to_numpy(float))
        lg = g["side"].to_numpy() > 0
        nl, ns = int(lg.sum()), int((~lg).sum())
        d = {"account_id": aid, "B_pairs": len(g), "B_long": nl, "B_short": ns,
             "B_excess_plain": float(h.mean()),
             "B_excess_long": float(h[lg].mean()) if nl else np.nan,
             "B_excess_short": float(h[~lg].mean()) if ns else np.nan,
             "B_R_chosen": float(g["R"].mean()), "B_R_other": float(g["flip_R"].mean())}
        if nl >= 3 and ns >= 3:
            w = np.where(lg, 0.5 / nl, 0.5 / ns)
            wh = w * h
            obs = float(wh.sum())
            cl = pd.Series(wh).groupby(g["cl"].to_numpy()).sum().to_numpy()
            if len(cl) >= 5:
                sims = np.empty(B)
                chunk = max(1, int(4e6 // len(cl)))
                for s0 in range(0, B, chunk):
                    kk = min(chunk, B - s0)
                    sims[s0:s0 + kk] = (cl[None, :] * rng.choice((-1.0, 1.0), size=(kk, len(cl)))).sum(1)
                pb = (1 + int((sims >= obs - 1e-12).sum())) / (B + 1)
                pw = (1 + int((sims <= obs + 1e-12).sum())) / (B + 1)
                if min(pb, pw) < 0.01:          # refine small p with many more draws
                    BB, hit_b, hit_w = 200_000, 0, 0
                    for s0 in range(0, BB, 20_000):
                        sm = (cl[None, :] * rng.choice((-1.0, 1.0), size=(20_000, len(cl)))).sum(1)
                        hit_b += int((sm >= obs - 1e-12).sum())
                        hit_w += int((sm <= obs + 1e-12).sum())
                    pb, pw = (1 + hit_b) / (BB + 1), (1 + hit_w) / (BB + 1)
                z = obs / math.sqrt((cl ** 2).sum()) if (cl ** 2).sum() > 0 else np.nan
                d.update(B_balanced=obs, B_clusters=len(cl), B_z=z, B_p_better=pb, B_p_worse=pw)
        rows.append(d)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------ accounts
def account_table(T: pd.DataFrame, A: pd.DataFrame, a, label: str, lo: int, hi: int) -> pd.DataFrame:
    run = [k for k, v in RUN_LABEL.items() if v == label][0]
    acc = A[A["run"] == run]
    eqh_p = os.path.join(a.extracted_dir, run, "equity_hourly.csv")
    dd = pd.read_csv(eqh_p).groupby("account_id")["dd_max"].max() if os.path.exists(eqh_p) else pd.Series(dtype=float)
    sf = pd.read_csv(os.path.join(a.base_dir, "signal_flow.csv"))
    sf = sf[sf["run"] == run].set_index("account_id")
    mid = (lo + hi) // 2
    last3 = hi - 3 * DAY
    days = (hi - lo) / DAY
    rows = []
    Tt = T[T["run"] == run]
    for r in acc.itertuples(index=False):
        g = Tt[Tt["account_id"] == r.account_id].sort_values(["exit_time", "id"])
        d = {"run": label, "account_id": r.account_id, "grp": r.grp, "strategy": r.strategy, "tf": r.timeframe}
        n = len(g)
        d["n"] = n
        d["per_day"] = n / days
        if n == 0:
            d["zero_cause"] = sf["zero_trade_cause"].get(r.account_id, "") if len(sf) else ""
            d["signals"] = int(sf["sig_SUBMITTED"].get(r.account_id, 0)) if len(sf) else 0
            d["max_dd"] = float(dd.get(r.account_id, 0.0))
            d["final"] = EQ0
            rows.append(d)
            continue
        pnl = g["pnl"].to_numpy(float)
        w = pnl > 0
        pos, neg = pnl[w].sum(), pnl[~w].sum()
        lg, sh = g[g["side"] > 0], g[g["side"] < 0]
        h1, h2 = g[g["exit_time"] < mid], g[g["exit_time"] >= mid]
        l3 = g[g["exit_time"] >= last3]
        b17, a17 = g[g["exit_time"] < CUT_1017], g[g["exit_time"] >= CUT_1017]
        eq = np.r_[EQ0, g["equity_after"].to_numpy(float)]
        d.update({
            "win_pct": 100 * w.mean(), "pnl": pnl.sum(), "final": eq[-1], "ret_pct": 100 * (eq[-1] / EQ0 - 1),
            "avg_win_usd": pnl[w].mean() if w.any() else np.nan, "avg_loss_usd": pnl[~w].mean() if (~w).any() else np.nan,
            "avg_win_roe": 100 * g.loc[w, "roe"].mean() if w.any() else np.nan,
            "avg_loss_roe": 100 * g.loc[~w, "roe"].mean() if (~w).any() else np.nan,
            "pf": pos / -neg if neg < 0 else np.inf, "mean_roe_pct": 100 * g["roe"].mean(),
            "mean_R": g["R"].mean(), "mean_gross_R": g["gross_R"].mean(), "mean_cost_R": g["cost_R"].mean(),
            "mean_wallet_pct": 100 * g["wallet_pct"].mean(),
            "max_dd": float(dd.get(r.account_id, np.nan)),
            "long_n": len(lg), "long_pnl": lg["pnl"].sum(), "long_R": lg["R"].mean() if len(lg) else np.nan,
            "short_n": len(sh), "short_pnl": sh["pnl"].sum(), "short_R": sh["R"].mean() if len(sh) else np.nan,
            "h1_n": len(h1), "h1_pnl": h1["pnl"].sum(), "h1_R": h1["R"].mean() if len(h1) else np.nan,
            "h2_n": len(h2), "h2_pnl": h2["pnl"].sum(), "h2_R": h2["R"].mean() if len(h2) else np.nan,
            "last3_n": len(l3), "last3_pnl": l3["pnl"].sum(),
            "pre1017_n": len(b17), "pre1017_pnl": b17["pnl"].sum(), "post1017_n": len(a17),
            "post1017_pnl": a17["pnl"].sum(),
            "max_lose_streak": longest_streak((pnl <= 0).tolist()),
            "best_trade": pnl.max(), "worst_trade": pnl.min(), "pnl_ex_best": pnl.sum() - pnl.max(),
            "fees": g["fees"].sum(), "funding": g["funding"].sum(), "mean_lev": g["leverage"].mean(),
            "best_tier_share": float((g["tier"] == "best").mean()),
            "median_stop_pct": 100 * g["stop_frac"].median(), "median_hold_h": g["hold_min"].median() / 60,
            "exit_mix": " ".join(f"{k}:{v}" for k, v in g["exit_reason"].value_counts().items()),
            "days_traded": g["exit_kday"].nunique(),
            "pos_days": int((g.groupby("exit_kday")["pnl"].sum() > 0).sum()),
            "neg_days": int((g.groupby("exit_kday")["pnl"].sum() <= 0).sum()),
            "best_day_pnl": float(g.groupby("exit_kday")["pnl"].sum().max()),
        })
        rows.append(d)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("extracted_dir")
    ap.add_argument("base_dir")
    ap.add_argument("randpool")
    ap.add_argument("ref5y")
    ap.add_argument("out_dir")
    ap.add_argument("--boot", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=20261024)
    a = ap.parse_args(argv)
    rng = np.random.default_rng(a.seed)
    TD = os.path.join(a.out_dir, "tables")
    os.makedirs(TD, exist_ok=True)
    F: dict = {}

    def save(df, name):
        df.to_csv(os.path.join(TD, name), index=False)

    T, A = load(a)
    spans = {}
    for run in RUN_LABEL:
        if os.path.isdir(os.path.join(a.extracted_dir, run)):
            spans[RUN_LABEL[run]] = run_span(a, run)
    lo, hi = spans["v4"]
    F["v4_start_ms"], F["v4_end_ms"] = lo, hi
    F["v4_days"] = (hi - lo) / DAY
    F["mid_ms"] = (lo + hi) // 2
    F["cut1017_ms"] = CUT_1017

    # ---------------------------------------------------------------- 1 coverage
    rows = []
    for lab, (l0, h0) in spans.items():
        run = [k for k, v in RUN_LABEL.items() if v == lab][0]
        acc = A[A["run"] == run]
        t = T[T["run"] == run]
        rr = pd.read_csv(os.path.join(a.extracted_dir, run, "runs.csv"))
        sv = sorted({json.loads(x).get("settings_version", "") for x in rr["data"]})
        tc = sorted({json.loads(x).get("trading_code", "") for x in rr["data"]})
        rows.append({"run": lab, "folder": run, "start_ms": l0, "end_ms": h0, "days": (h0 - l0) / DAY,
                     "settings_version": " ".join(sv), "trading_code_hashes": len(tc), "restarts": len(rr) - 1,
                     "accounts": len(acc),
                     **{f"acc_{g}": int((acc["grp"] == g).sum()) for g in GRP_ORDER},
                     "acc_with_trades": t["account_id"].nunique(), "trades": len(t), "pnl": t["pnl"].sum(),
                     "lev_mix": " ".join(f"{k}x:{v}" for k, v in t["leverage"].value_counts().items())})
    COV = pd.DataFrame(rows)
    save(COV, "coverage_runs.csv")
    F["total_days_all_runs"] = (spans["v4"][1] - spans["v3a"][0]) / DAY if "v3a" in spans else F["v4_days"]
    acc4 = A[A["run"] == "current"]
    covtf = acc4.groupby(["grp", "timeframe"]).size().unstack(fill_value=0)
    covtf = covtf.reindex(columns=[c for c in TFS if c in covtf.columns])
    save(covtf.reset_index(), "coverage_v4_grp_tf.csv")
    # signals and restarts
    sl = pd.read_csv(os.path.join(a.extracted_dir, "current", "signal_log.csv"), usecols=["bar_close", "status"])
    F["v4_signal_status"] = sl["status"].value_counts().to_dict()
    al = pd.read_csv(os.path.join(a.extracted_dir, "current", "alerts.csv"))
    F["v4_alert_levels"] = al["level"].value_counts().to_dict()
    F["v4_restart_alerts"] = int(al["text"].astype(str).str.contains("재시작").sum())
    rr = pd.read_csv(os.path.join(a.extracted_dir, "current", "runs.csv"))
    ch = [json.loads(x).get("changes") or [] for x in rr["data"]]
    F["v4_restart_changes"] = {k: sum(k in c for c in ch) for k in sorted({x for c in ch for x in c})}
    F["v4_trading_code_hashes"] = len({json.loads(x).get("trading_code") for x in rr["data"]})

    T4 = T[T["run"] == "current"].copy()
    DP = T4.groupby(["account_id", "exit_kday"]).agg(pnl=("pnl", "sum"), trades=("pnl", "size")).reset_index()
    DP["day_kst"] = pd.to_datetime(T4["exit_time"].max() + KST, unit="ms").strftime("%Y-") + DP["exit_kday"]
    DP[["account_id", "day_kst", "pnl", "trades"]].to_csv(os.path.join(a.out_dir, "daily_pnl.csv"), index=False)
    F["v4_trades"] = len(T4)
    F["v4_pnl"] = float(T4["pnl"].sum())

    # ---------------------------------------------------------------- 2 whole-bot picture
    G = by(T4, ["grp"])
    na = acc4.groupby("grp").size()
    G["accounts"] = G["grp"].map(na)
    G["accounts_traded"] = G["grp"].map(T4.groupby("grp")["account_id"].nunique())
    fin = T4.sort_values(["exit_time", "id"]).groupby("account_id")["equity_after"].last()
    pnl_acc = T4.groupby("account_id")["pnl"].sum()
    G["accounts_profit"] = G["grp"].map(T4.groupby("grp").apply(
        lambda g: int((g.groupby("account_id")["pnl"].sum() > 0).sum()), include_groups=False))
    G["start_money"] = G["accounts"] * EQ0
    G["pnl_pct_of_start"] = 100 * G["pnl"] / G["start_money"]
    save(G, "v4_by_group.csv")
    save(by(T4, ["grp", "tf"]), "v4_by_group_tf.csv")
    T4["side_name"] = np.where(T4["side"] > 0, "long", "short")
    save(by(T4, ["grp", "side_name"]), "v4_by_group_side.csv")
    save(by(T4, ["grp", "tf", "side_name"]), "v4_by_group_tf_side.csv")
    save(by(T4, ["grp", "symbol"]), "v4_by_group_coin.csv")
    T4["strat"] = np.where(T4["grp"].isin(["core", "ds"]), "strategies", np.where(T4["grp"] == "flip", "flip", "5m"))
    save(by(T4[T4["strat"] != "5m"], ["strat", "entry_hour"]), "v4_by_hour.csv")
    sess = pd.cut(T4["entry_hour"], [-1, 5, 11, 17, 23], labels=["00-06", "06-12", "12-18", "18-24"])
    T4["session"] = sess.astype(str)
    save(by(T4[T4["strat"] != "5m"], ["strat", "session"]), "v4_by_session.csv")
    T4["weekend"] = np.where(T4["dow"] >= 5, "weekend", "weekday")
    save(by(T4[T4["strat"] != "5m"], ["strat", "weekend"]), "v4_by_weekend.csv")
    save(by(T4, ["grp", "exit_reason"]), "v4_by_exit.csv")
    save(by(T4[T4["grp"].isin(["core", "ds", "flip"])], ["grp", "tier", "leverage"]), "v4_by_tier_lev.csv")
    # per-day
    Dd = T4.pivot_table(index="exit_kday", columns="grp", values="pnl", aggfunc="sum").fillna(0)
    M, MD, bars = market(a, lo, hi)
    save(M, "v4_market_coins.csv")
    Dd = Dd.reset_index().rename(columns={"exit_kday": "day"}).merge(MD[["day", "eq6"]], on="day", how="left")
    Dd["all"] = Dd[[c for c in GRP_ORDER if c in Dd.columns]].sum(axis=1)
    Dd["strategies"] = Dd[[c for c in ("core", "ds") if c in Dd.columns]].sum(axis=1)
    save(Dd, "v4_by_day.csv")
    save(MD, "v4_market_daily.csv")
    F["market_eq6_pct"] = float(M["change_pct"].mean())
    F["market_coins"] = {r.symbol: round(r.change_pct, 2) for r in M.itertuples()}
    F["market_down_days"] = int((MD["eq6"] < 0).sum())
    F["market_days"] = int(len(MD))
    c = np.corrcoef(Dd["strategies"], Dd["eq6"])[0, 1] if len(Dd) > 2 else np.nan
    F["corr_daily_strategies_vs_market"] = float(c)
    # costs
    F["v4_fees"] = float(T4["fees"].sum())
    F["v4_funding"] = float(T4["funding"].sum())
    F["v4_gross"] = float(T4["gross"].sum())

    # ---------------------------------------------------------------- market effect
    pool = Pool(a.randpool)
    PM = pool.P.groupby(["timeframe", "side"])[["R", "gross_R"]].agg(["size", "mean"])
    PM.columns = ["n", "mean_R", "n2", "mean_gross_R"]
    PM = PM.drop(columns="n2").reset_index()
    save(PM, "pool_by_tf_side.csv")
    save(pool.P.groupby(["timeframe"])[["R", "gross_R", "cost_R"]].mean().reset_index(), "pool_by_tf.csv")
    sm = pool.side_mean()
    both = pool.P.groupby(["timeframe", "symbol"])["R"].mean()
    H = T4[T4["grp"].isin(["core", "ds", "flip"])].copy()
    H["pool_side_R"] = [sm.get((tf, s, int(sd)), np.nan) for tf, s, sd in zip(H["tf"], H["symbol"], H["side"])]
    H["pool_both_R"] = [both.get((tf, s), np.nan) for tf, s in zip(H["tf"], H["symbol"])]
    H["mkt_R"] = H["pool_side_R"] - H["pool_both_R"]          # what the side alone earned from the period's drift
    H["mkt_usd"] = H["mkt_R"] * H["risk_usd"]
    ME = H.groupby("grp").agg(n=("pnl", "size"), pnl=("pnl", "sum"), mkt_usd=("mkt_usd", "sum"),
                              mean_R=("R", "mean"), mean_mkt_R=("mkt_R", "mean"),
                              long_share=("side", lambda s: float((s > 0).mean()))).reset_index()
    ME["pnl_ex_market"] = ME["pnl"] - ME["mkt_usd"]
    save(ME, "v4_market_effect.csv")

    # ---------------------------------------------------------------- 3 accounts
    AC = account_table(T, A, a, "v4", lo, hi)
    mk = H.groupby("account_id")["mkt_usd"].sum()
    AC["mkt_usd"] = AC["account_id"].map(mk)
    AC["pnl_ex_market"] = AC["pnl"] - AC["mkt_usd"]

    # ---------------------------------------------------------------- 4 luck
    TH = T4[T4["grp"].isin(["core", "ds", "flip"])]
    LA, SIMS, IDS = luck_A(TH, pool, a.boot, rng)
    LC = luck_C(T4, a.boot, rng)
    LB = luck_B(a.base_dir, a.boot, rng)
    AC = AC.merge(LA, on="account_id", how="left").merge(LC, on="account_id", how="left").merge(
        LB, on="account_id", how="left")
    test = AC["grp"].isin(["core", "ds"]) & (AC["n"] >= 10) & AC["A_p_better"].notna()
    AC.loc[test, "A_q"] = bh(AC.loc[test, "A_p_better"].to_numpy())
    AC.loc[test, "A_q_worse"] = bh(AC.loc[test, "A_p_worse"].to_numpy())
    testc = AC["grp"].isin(["core", "ds", "reel"]) & (AC["n"] >= 10) & AC["C_p_le0"].notna()
    AC.loc[testc, "C_q"] = bh(AC.loc[testc, "C_p_le0"].to_numpy())
    testb = AC["grp"].isin(["core", "ds"]) & AC["B_p_better"].notna()
    AC.loc[testb, "B_q"] = bh(AC.loc[testb, "B_p_better"].to_numpy())
    AC.loc[testb, "B_q_worse"] = bh(AC.loc[testb, "B_p_worse"].to_numpy())
    F["A_tested"] = int(test.sum())
    F["A_bh_pass"] = int((AC["A_q"] < 0.05).sum())
    F["A_bh_pass_q10"] = int((AC["A_q"] < 0.10).sum())
    F["A_raw_p05"] = int((AC.loc[test, "A_p_better"] < 0.05).sum())
    F["A_bh_worse"] = int((AC["A_q_worse"] < 0.05).sum())
    F["A_raw_worse_p05"] = int((AC.loc[test, "A_p_worse"] < 0.05).sum())
    F["A_min_p"] = float(AC.loc[test, "A_p_better"].min())
    F["C_tested"] = int(testc.sum())
    F["C_bh_pass"] = int((AC["C_q"] < 0.05).sum())
    F["C_raw_p05"] = int((AC.loc[testc, "C_p_le0"] < 0.05).sum())
    F["B_tested"] = int(testb.sum())
    F["B_bh_pass"] = int((AC["B_q"] < 0.05).sum())
    F["B_raw_p05"] = int((AC.loc[testb, "B_p_better"] < 0.05).sum())
    F["B_bh_worse"] = int((AC["B_q_worse"] < 0.05).sum())
    # max-T (best of N): standardized excess, the null max across the tested accounts in the same simulation
    ids_t = [i for i in IDS if i in set(AC.loc[test, "account_id"])]
    if ids_t:
        S = SIMS[[IDS.index(i) for i in ids_t]]
        mu, sd = S.mean(1, keepdims=True), S.std(1, ddof=1, keepdims=True)
        Z = (S - mu) / sd
        obs = AC.set_index("account_id").loc[ids_t]
        zobs = ((obs["A_obs_R"].to_numpy() - mu[:, 0]) / sd[:, 0])
        maxnull = Z.max(0)
        AC.loc[AC["account_id"].isin(ids_t), "A_z"] = AC.loc[AC["account_id"].isin(ids_t), "account_id"].map(
            dict(zip(ids_t, zobs)))
        AC["A_p_maxT"] = AC["A_z"].map(lambda z: (1 + int((maxnull >= z).sum())) / (len(maxnull) + 1)
                                       if z == z else np.nan)
        F["maxT_best_account"] = ids_t[int(np.argmax(zobs))]
        F["maxT_best_z"] = float(zobs.max())
        F["maxT_null_median"] = float(np.median(maxnull))
        F["maxT_null_p95"] = float(np.percentile(maxnull, 95))
        F["maxT_p"] = float((1 + int((maxnull >= zobs.max()).sum())) / (len(maxnull) + 1))
    # flip accounts against the pool (sanity: random accounts should look like the pool)
    save(AC, "accounts_v4.csv")
    # RANDOM accounts
    save(AC[AC["grp"].isin(["flip", "flip5"])], "random_accounts_v4.csv")
    # comparison per tf: real accounts above the best / below the worst RANDOM of the same tf
    rows = []
    for tf in ["15m", "30m", "1h", "4h"]:
        r = AC[(AC["grp"] == "flip") & (AC["tf"] == tf)]
        s = AC[AC["grp"].isin(["core", "ds"]) & (AC["tf"] == tf) & (AC["n"] > 0)]
        if not len(r):
            continue
        rows.append({"tf": tf, "random_pnl_best": r["pnl"].max(), "random_pnl_worst": r["pnl"].min(),
                     "random_pnl_mean": r["pnl"].mean(), "real_accounts": len(s),
                     "real_above_best_random": int((s["pnl"] > r["pnl"].max()).sum()),
                     "real_below_worst_random": int((s["pnl"] < r["pnl"].min()).sum()),
                     "real_pnl_median": s["pnl"].median(), "real_profit": int((s["pnl"] > 0).sum()),
                     "pool_mean_R": float(pool.P.loc[pool.P["timeframe"] == tf, "R"].mean()),
                     "real_mean_R_tradeweighted": float(T4.loc[T4["grp"].isin(["core", "ds"]) & (T4["tf"] == tf), "R"].mean()),
                     "random_mean_R_tradeweighted": float(T4.loc[(T4["grp"] == "flip") & (T4["tf"] == tf), "R"].mean())})
    save(pd.DataFrame(rows), "vs_random_by_tf.csv")
    # reel vs 5m flips (bootstrap of trades)
    reel = T4[T4["grp"] == "reel"]["R"].dropna().to_numpy()
    f5 = T4[T4["grp"] == "flip5"]["R"].dropna().to_numpy()
    if len(reel) and len(f5):
        bm = f5[rng.integers(0, len(f5), size=(a.boot, len(reel)))].mean(1)
        F["reel_mean_R"], F["flip5_mean_R"] = float(reel.mean()), float(f5.mean())
        F["reel_p_better_than_flip5"] = float((1 + (bm >= reel.mean()).sum()) / (a.boot + 1))

    # ---------------------------------------------------------------- 5 stability
    S = AC[AC["grp"].isin(["core", "ds"])]
    s5 = S[(S["h1_n"] >= 5) & (S["h2_n"] >= 5)]
    F["halves_accounts"] = len(s5)
    F["halves_spearman_R"] = float(s5["h1_R"].rank().corr(s5["h2_R"].rank()))
    F["halves_spearman_pnl"] = float(s5["h1_pnl"].rank().corr(s5["h2_pnl"].rank()))
    wt = []
    for tf, x in s5.groupby("tf"):
        if len(x) >= 8:
            wt.append({"tf": tf, "accounts": len(x), "spearman_R": float(x["h1_R"].rank().corr(x["h2_R"].rank())),
                       "spearman_pnl": float(x["h1_pnl"].rank().corr(x["h2_pnl"].rank()))})
    save(pd.DataFrame(wt), "halves_within_tf.csv")
    F["halves_within_tf_mean_spearman_R"] = float(np.mean([w["spearman_R"] for w in wt])) if wt else np.nan
    F["h1_profit"] = int((S["h1_pnl"] > 0).sum())
    F["h2_profit"] = int((S["h2_pnl"] > 0).sum())
    F["both_halves_profit"] = int(((S["h1_pnl"] > 0) & (S["h2_pnl"] > 0)).sum())
    F["traded_both_halves"] = int(((S["h1_n"] > 0) & (S["h2_n"] > 0)).sum())
    # expected both-positive under independence
    tb = S[(S["h1_n"] > 0) & (S["h2_n"] > 0)]
    p1 = (tb["h1_pnl"] > 0).mean()
    p2 = (tb["h2_pnl"] > 0).mean()
    F["both_halves_profit_among_traded_both"] = int(((tb["h1_pnl"] > 0) & (tb["h2_pnl"] > 0)).sum())
    F["both_halves_expected_indep"] = float(p1 * p2 * F["traded_both_halves"])
    top_h1 = S.sort_values("h1_pnl", ascending=False).head(10)
    F["top10_h1_positive_in_h2"] = int((top_h1["h2_pnl"] > 0).sum())
    s17 = S[(S["pre1017_n"] >= 5) & (S["post1017_n"] >= 3)]
    F["cut1017_spearman_pnl"] = float(s17["pre1017_pnl"].rank().corr(s17["post1017_pnl"].rank()))
    F["cut1017_accounts"] = len(s17)
    top17 = S.sort_values("pre1017_pnl", ascending=False).head(10)
    F["top10_pre1017_positive_after"] = int((top17["post1017_pnl"] > 0).sum())
    save(top17[["account_id", "pre1017_n", "pre1017_pnl", "post1017_n", "post1017_pnl", "pnl"]], "top10_pre1017.csv")
    save(top_h1[["account_id", "h1_n", "h1_pnl", "h2_n", "h2_pnl", "pnl"]], "top10_h1.csv")
    top_all = S.sort_values("pnl", ascending=False).head(20)
    save(top_all, "top20_v4.csv")
    # per-day P&L of the top 20 accounts
    Pd = T4[T4["account_id"].isin(top_all["account_id"])].pivot_table(index="account_id", columns="exit_kday",
                                                                         values="pnl", aggfunc="sum").fillna(0)
    save(Pd.reindex(top_all["account_id"]).reset_index(), "top20_by_day.csv")
    # top list by window
    W = []
    for wname, w0, w1 in (("before_1017", lo, CUT_1017), ("after_1017", CUT_1017, hi + 1),
                          ("h1", lo, F["mid_ms"]), ("h2", F["mid_ms"], hi + 1), ("last3", hi - 3 * DAY, hi + 1)):
        x = T4[(T4["exit_time"] >= w0) & (T4["exit_time"] < w1)]
        g = by(x, ["grp"])
        g.insert(0, "window", wname)
        g["days"] = (min(w1, hi) - w0) / DAY
        g["market_eq6_pct"] = window_move(bars, w0, min(w1, hi))
        W.append(g)
    save(pd.concat(W, ignore_index=True), "v4_by_window.csv")
    # v3 persistence (same strategy@tf in the earlier runs, mean R)
    AV3 = pd.concat([account_table(T, A, a, lab, *spans[lab]) for lab in ("v3a", "v3b") if lab in spans],
                    ignore_index=True)
    save(AV3, "accounts_v3.csv")
    key = lambda d: d["strategy"] + "@" + d["tf"]  # noqa: E731
    v4R = AC.set_index("account_id")["mean_R"]
    pers = []
    for lab in ("v3a", "v3b"):
        x = AV3[(AV3["run"] == lab) & (AV3["n"] >= 5)].copy()
        x["v4_R"] = x["account_id"].map(v4R)
        x = x[x["v4_R"].notna() & x["grp"].isin(["core"])]
        pers.append({"run": lab, "cells": len(x), "spearman_meanR_vs_v4": float(x["mean_R"].rank().corr(x["v4_R"].rank())),
                     "both_positive": int(((x["mean_R"] > 0) & (x["v4_R"] > 0)).sum()),
                     "earlier_positive": int((x["mean_R"] > 0).sum())})
    save(pd.DataFrame(pers), "persistence_v3_v4.csv")
    # all 19+ days pooled per strategy x tf (R only; dollars are per run)
    TP = T[T["grp"].isin(["core", "ds", "reel"])]
    P19 = TP.groupby(["grp", "strategy", "tf"]).agg(n=("R", "size"), mean_R=("R", "mean"), sum_R=("R", "sum"),
                                                     runs=("label", lambda s: " ".join(sorted(s.unique())))).reset_index()
    save(P19, "pooled_all_runs_R.csv")

    # ---------------------------------------------------------------- 6 five-year cross-check
    ref = pd.read_csv(a.ref5y)
    ref["account_id"] = ref["strategy"] + "@" + ref["timeframe"]
    AC2 = AC.merge(ref.drop(columns=["kind", "strategy", "timeframe"]), on="account_id", how="left")
    save(AC2, "accounts_v4.csv")
    good = AC2[AC2["grp"].isin(["core", "ds"]) & (AC2["pnl"] > 0) & (AC2["n"] >= 5)].copy()
    good["five_both_plus"] = (good["select_sign"] > 0) & (good["test_sign"] > 0)
    good["five_test_plus"] = good["test_sign"] > 0
    save(good.sort_values("pnl", ascending=False), "fiveyear_check.csv")
    F["good_forward"] = len(good)
    F["good_forward_test_plus"] = int(good["five_test_plus"].sum())
    F["good_forward_both_plus"] = int(good["five_both_plus"].sum())
    allc = AC2[AC2["grp"].isin(["core", "ds"])]
    F["all_cells_test_plus"] = int((allc["test_sign"] > 0).sum())
    F["all_cells_with_ref"] = int(allc["test_sign"].notna().sum())

    # ---------------------------------------------------------------- 8 shortlist
    X = AC2[AC2["grp"].isin(["core", "ds"])].copy()
    crit = {
        "c1_n20": X["n"] >= 20,
        "c2_profit": (X["pnl"] > 0) & (X["mean_R"] > 0),
        "c3_beats_luck": X["A_q"] < 0.10,
        "c4_both_halves": (X["h1_pnl"] > 0) & (X["h2_pnl"] > 0),
        "c5_5y_both_periods": (X["select_sign"] > 0) & (X["test_sign"] > 0),
        "c6_not_one_trade": X["pnl_ex_best"] > 0,
    }
    for k, v in crit.items():
        X[k] = v.fillna(False).astype(bool)
    X["criteria_passed"] = X[list(crit)].sum(axis=1)
    X["qualifies"] = X["criteria_passed"] == len(crit)
    F["shortlist_n"] = int(X["qualifies"].sum())
    F["criteria_counts"] = {k: int(X[k].sum()) for k in crit}
    F["max_criteria"] = int(X["criteria_passed"].max())
    close = X.sort_values(["criteria_passed", "A_p_better", "pnl"], ascending=[False, True, False]).head(12)
    save(close, "shortlist_closest.csv")
    save(X[["account_id"] + list(crit) + ["criteria_passed", "qualifies"]], "shortlist_criteria.csv")

    # ---------------------------------------------------------------- 7 10/17 comparison facts
    pre = T4[T4["exit_time"] < CUT_1017]
    post = T4[T4["exit_time"] >= CUT_1017]
    F["pre1017"] = {g: float(pre.loc[pre["grp"] == g, "pnl"].sum()) for g in GRP_ORDER}
    F["post1017"] = {g: float(post.loc[post["grp"] == g, "pnl"].sum()) for g in GRP_ORDER}
    F["pre1017_meanR"] = {g: float(pre.loc[pre["grp"] == g, "R"].mean()) for g in GRP_ORDER}
    F["post1017_meanR"] = {g: float(post.loc[post["grp"] == g, "R"].mean()) for g in GRP_ORDER}
    F["pre1017_long_share"] = {g: float((pre.loc[pre["grp"] == g, "side"] > 0).mean()) for g in GRP_ORDER}
    F["post1017_long_share"] = {g: float((post.loc[post["grp"] == g, "side"] > 0).mean()) for g in GRP_ORDER}
    F["market_pre1017"] = window_move(bars, lo, CUT_1017)
    F["market_post1017"] = window_move(bars, CUT_1017, hi)
    F["market_last3"] = window_move(bars, hi - 3 * DAY, hi)
    for aid in ("V39_ALL@1h", "N09_ALLIG_AROON@1h", "OBV_S@30m", "N24_DMI@30m", "N05_PSAR_POC@30m",
                "F10_M2022@15m", "F9_BREAKER@1h", "RANDOM_3@1h", "RANDOM_1@1h"):
        r = AC2[AC2["account_id"] == aid]
        if len(r):
            r = r.iloc[0]
            F[f"acct_{aid}"] = {k: (None if (isinstance(r[k], float) and not np.isfinite(r[k])) else
                                    (float(r[k]) if isinstance(r[k], (int, float, np.floating, np.integer)) else r[k]))
                                for k in ("n", "pnl", "pre1017_n", "pre1017_pnl", "post1017_n", "post1017_pnl",
                                          "win_pct", "mean_R", "max_dd", "long_n", "short_n", "final")}
    # live trial account since 10/19 12:00 KST (paper only; the export holds no executor data)
    t19 = 1792378800000     # 2026-10-19 12:00 KST
    v = T4[(T4["account_id"] == "V39_ALL@1h") & (T4["entry_time"] >= t19)]
    F["v39_since_1019"] = {"n": len(v), "pnl": float(v["pnl"].sum()), "wins": int((v["pnl"] > 0).sum()),
                           "mean_R": float(v["R"].mean()) if len(v) else None,
                           "long": int((v["side"] > 0).sum())}

    with open(os.path.join(a.out_dir, "facts.json"), "w") as fh:
        json.dump(F, fh, ensure_ascii=False, indent=1, default=lambda o: o if not isinstance(o, (np.integer, np.floating)) else o.item())
    print(json.dumps({k: F[k] for k in ("v4_days", "v4_trades", "v4_pnl", "market_eq6_pct", "A_tested", "A_bh_pass",
                                         "A_raw_p05", "B_tested", "B_bh_pass", "C_tested", "C_bh_pass", "shortlist_n",
                                         "max_criteria")}, default=float, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
