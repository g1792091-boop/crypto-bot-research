#!/usr/bin/env python3
"""Five years (2021-08 .. 2026-09, periods 1 and 2) of every signal of the 36 strategies, alone, through the repo's
own vectorised research engine (research/levstop/levstop.outcomes -> strategy_profiles._scan: entry next bar open
+ 2 bp, 2 ATR stop, paper ladder, taker 5 bp both sides, 2 bp slippage both sides, funding 0.01%/8h), at a FIXED
30x (margin 30%, the live quality rule's usual leverage), for the chosen side AND the opposite side at the same bar
(the timing-matched coin flip). Split by volatility regime (2 ATR stop as % of price), year, period and coin.

    python3 -I c07_5y_regime.py <repo> <signals_dir> <out_dir> [tfs=15m,30m,1h] [procs=4]

Per signal: net per notional = roe / 30;  gross per notional = net + 2*(5+2) bp + funding paid (bars held x f_bar).
In R (the 2 ATR stop): x / stop_frac.  The signal cache digests are compared with paperbot/agents/labdata_reference
.json first (no file is written outside out_dir).
Uncertainty: week-block bootstrap (Monday-UTC weeks resampled whole), 2,000 draws.
"""
import importlib.util
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

LEV = 30
RT = 0.0014
G = {}


def load_levstop(repo):
    sys.path.insert(0, repo)
    spec = importlib.util.spec_from_file_location("levstop_ro", os.path.join(repo, "research", "levstop", "levstop.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def job(args):
    strategy, tf = args
    LS = G["LS"]
    from paperbot import sweepsig
    RB = LS._profiles().RB
    L = sweepsig.lib()
    f_bar = RB.FUNDING_8H * L.tf_minutes(tf) / 480.0
    p_edges = [(LS._ns(a), LS._ns(b)) for _p, a, b in LS.PERIODS]
    out = []
    for c in LS.COINS:
        got = LS._bars(G["sig_dir"], tf).get(c)
        if got is None or f"s__{strategy}" not in got[1].files:
            continue
        b, z = got
        sg = z[f"s__{strategy}"]
        n = len(b["ts"])
        lo = RB.window_bounds(L, b, tf, "is")[0]
        n_end = RB.window_bounds(L, b, tf, "cf")[1]
        idx = np.nonzero(sg[lo:max(lo, n_end - 1)])[0] + lo
        ok = np.isfinite(b["atr"][idx]) & (b["atr"][idx] > 0) & np.isfinite(b["o"][np.minimum(idx + 1, n - 1)])
        idx = idx[ok]
        ts = b["ts"][idx]
        period = np.zeros(len(idx), int)
        for k, (a, e) in enumerate(p_edges, 1):
            period[(ts >= a) & (ts < e)] = k
        keep = period > 0
        idx, ts, period = idx[keep], ts[keep], period[keep]
        if not len(idx):
            continue
        side = sg[idx].astype(int)
        o1 = LS.outcomes(b, idx, side, tf, LEV, 2.0)
        o2 = LS.outcomes(b, idx, -side, tf, LEV, 2.0)
        raw = b["o"][idx + 1]
        stop_frac = 2.0 * b["atr"][idx] / raw
        df = pd.DataFrame({"strategy": strategy, "tf": tf, "coin": c, "ts": ts, "period": period, "side": side,
                           "stop_frac": stop_frac, "roe": o1["roe"], "reason": o1["reason"], "held": o1["held"],
                           "done": o1["done"], "roe_flip": o2["roe"], "held_flip": o2["held"], "done_flip": o2["done"]})
        df["fund"] = f_bar * df["held"].fillna(0)
        df["fund_flip"] = f_bar * df["held_flip"].fillna(0)
        out.append(df)
    return pd.concat(out) if out else pd.DataFrame()


def week_boot(x, wk, B=2000, seed=1):
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    x, wk = x[ok], np.asarray(wk)[ok]
    if len(x) < 10:
        return np.nan, np.nan
    u, inv = np.unique(wk, return_inverse=True)
    s, c = np.bincount(inv, weights=x), np.bincount(inv)
    rng = np.random.default_rng(seed)
    d = rng.integers(0, len(u), size=(B, len(u)))
    m = s[d].sum(1) / c[d].sum(1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    repo, sig_dir, out = sys.argv[1:4]
    tfs = (sys.argv[4] if len(sys.argv) > 4 else "15m,30m,1h").split(",")
    procs = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    os.makedirs(out, exist_ok=True)
    LS = load_levstop(repo)
    G.update(LS=LS, sig_dir=sig_dir)
    # data check (no write): content digests vs the lab reference
    from paperbot.agents import labdata
    ref = labdata.reference()
    chk = []
    for tf in tfs:
        for c in LS.COINS:
            p = os.path.join(sig_dir, f"sig_{tf}_{c}.npz")
            z = np.load(p, allow_pickle=False)
            dg = labdata.content_digest({k: z[k] for k in z.files})
            want = ref["main"].get(f"{tf}_{c}", {}).get("digest")
            chk.append({"file": os.path.basename(p), "digest": dg, "reference": want, "same": dg == want})
    CK = pd.DataFrame(chk)
    CK.to_csv(os.path.join(out, "c07_data_check.csv"), index=False)
    print("cache identical to the lab reference:", int(CK["same"].sum()), "/", len(CK))
    strategies = sorted({k[3:] for k in np.load(os.path.join(sig_dir, f"sig_15m_BTCUSD.npz")).files if k.startswith("s__")})
    jobs = [(s, tf) for tf in tfs for s in strategies]
    t0 = time.time()
    import multiprocessing as mp
    with mp.get_context("fork").Pool(procs) as pool:
        parts = pool.map(job, jobs, chunksize=1)
    D = pd.concat([p for p in parts if len(p)], ignore_index=True)
    print("signals", len(D), "s", round(time.time() - t0, 1))
    D = D[D["done"] & D["done_flip"]].copy()
    D["net_n"] = D["roe"] / LEV
    D["gross_n"] = D["net_n"] + RT + D["fund"]
    D["gross_flip_n"] = D["roe_flip"] / LEV + RT + D["fund_flip"]
    D["gross_R"] = D["gross_n"] / D["stop_frac"]
    D["net_R"] = D["net_n"] / D["stop_frac"]
    D["cost_R"] = (RT + D["fund"]) / D["stop_frac"]
    D["gross_flip_R"] = D["gross_flip_n"] / D["stop_frac"]
    D["excess_R"] = (D["gross_R"] - D["gross_flip_R"]) / 2       # what the side choice added (coin flip = 0)
    D["coinflip_gross_R"] = (D["gross_R"] + D["gross_flip_R"]) / 2  # the exit structure's own drift at these moments
    tsd = pd.to_datetime(D["ts"])
    D["week"] = (tsd - pd.to_timedelta(tsd.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    D["year"] = tsd.dt.year
    D["stop_pct"] = D["stop_frac"] * 100
    D.to_parquet(os.path.join(out, "c07_signals.parquet")) if False else None
    bins = [0, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.25, 1.5, 2.0, 3.0, 100]
    D["stop_bin"] = pd.cut(D["stop_pct"], bins).astype(str)

    def agg(g, label):
        lo, hi = week_boot(g["gross_R"], g["week"])
        elo, ehi = week_boot(g["excess_R"], g["week"], seed=2)
        nlo, nhi = week_boot(g["net_n"] * 1e4, g["week"], seed=3)
        return {**label, "n": len(g), "weeks": g["week"].nunique(), "median_stop_pct": g["stop_pct"].median(),
                "net_bps_notional": g["net_n"].mean() * 1e4, "net_bps_ci_lo": nlo, "net_bps_ci_hi": nhi,
                "gross_bps_notional": g["gross_n"].mean() * 1e4,
                "net_R": g["net_R"].mean(), "gross_R": g["gross_R"].mean(), "gross_R_ci_lo": lo, "gross_R_ci_hi": hi,
                "cost_R": g["cost_R"].mean(), "excess_side_R": g["excess_R"].mean(), "excess_ci_lo": elo,
                "excess_ci_hi": ehi, "coinflip_gross_R": g["coinflip_gross_R"].mean(),
                "win_rate": (g["roe"] > 0).mean(), "stop_exit_share": (g["reason"] == 0).mean()}

    rows = []
    for tf, g in D.groupby("tf"):
        rows.append(agg(g, {"tf": tf, "split": "all", "key": "*"}))
        for k, h in g.groupby("stop_bin"):
            rows.append(agg(h, {"tf": tf, "split": "stop_bin", "key": k}))
        for k, h in g.groupby("year"):
            rows.append(agg(h, {"tf": tf, "split": "year", "key": str(k)}))
        for k, h in g.groupby("period"):
            rows.append(agg(h, {"tf": tf, "split": "period", "key": str(k)}))
        for k, h in g.groupby("coin"):
            rows.append(agg(h, {"tf": tf, "split": "coin", "key": k}))
        q = g["stop_pct"].quantile([0.2, 0.4, 0.6, 0.8]).to_numpy()
        qb = pd.cut(g["stop_pct"], [0, *q, 100], labels=["Q1 quietest", "Q2", "Q3", "Q4", "Q5 most volatile"])
        for k, h in g.groupby(qb, observed=True):
            rows.append(agg(h, {"tf": tf, "split": "vol_quintile", "key": str(k)}))
    S = pd.DataFrame(rows)
    S.to_csv(os.path.join(out, "c07_5y_regime.csv"), index=False)
    # per strategy x tf (net per notional, gross R, side excess), with period split
    rows = []
    for (s, tf), g in D.groupby(["strategy", "tf"]):
        r = agg(g, {"strategy": s, "tf": tf})
        for p in (1, 2):
            h = g[g["period"] == p]
            r[f"gross_R_p{p}"] = h["gross_R"].mean()
            r[f"excess_R_p{p}"] = h["excess_R"].mean()
            r[f"net_bps_p{p}"] = h["net_n"].mean() * 1e4
        hv = g[g["stop_pct"] >= g["stop_pct"].quantile(0.8)]
        r["gross_R_top_vol_quintile"] = hv["gross_R"].mean()
        r["net_bps_top_vol_quintile"] = hv["net_n"].mean() * 1e4
        rows.append(r)
    ST = pd.DataFrame(rows)
    ST.to_csv(os.path.join(out, "c07_5y_by_strategy.csv"), index=False)
    pd.set_option("display.width", 250)
    cols = ["tf", "split", "key", "n", "weeks", "median_stop_pct", "net_bps_notional", "net_bps_ci_lo", "net_bps_ci_hi",
            "gross_bps_notional", "net_R", "gross_R", "gross_R_ci_lo", "gross_R_ci_hi", "cost_R", "excess_side_R",
            "excess_ci_lo", "excess_ci_hi", "coinflip_gross_R", "win_rate"]
    print(S[cols].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
