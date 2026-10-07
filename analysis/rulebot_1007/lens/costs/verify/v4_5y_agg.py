#!/usr/bin/env python3
"""Aggregate v3_5y output: net / gross per notional (bp) and in R, side-choice excess, coin-flip gross, with
week-block bootstrap; splits by tf, year, coin, period, vol quintile; per strategy x tf.

python3 -I v4_5y_agg.py <v3_5y.csv.gz> <out_prefix>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vboot  # noqa
import numpy as np
import pandas as pd


def wboot(x, wk, B=2000, seed=3):
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
    return np.percentile(m, 2.5), np.percentile(m, 97.5)


def main():
    src, pre = sys.argv[1], sys.argv[2]
    D = pd.read_csv(src)
    n0 = len(D)
    D = D[(D["reason"] < 3) & (D["reason_flip"] < 3)].copy()
    print("dropped open-at-end", n0 - len(D))
    D["gross_R"] = D["gross_n"] / D["stop_frac"]
    D["net_R"] = D["net_n"] / D["stop_frac"]
    D["gross_flip_R"] = D["gross_n_flip"] / D["stop_frac"]
    D["excess_R"] = (D["gross_R"] - D["gross_flip_R"]) / 2
    D["cf_R"] = (D["gross_R"] + D["gross_flip_R"]) / 2
    D["cost_bp"] = (D["gross_n"] - D["net_n"]) * 1e4
    t = pd.to_datetime(D["ts"])
    D["week"] = (t.dt.floor("D") - pd.to_timedelta(t.dt.weekday, unit="D")).dt.strftime("%Y-%m-%d")
    D["year"] = t.dt.year
    D["stop_pct"] = D["stop_frac"] * 100

    def agg(g, lab):
        lo, hi = wboot(g["gross_R"], g["week"])
        nlo, nhi = wboot(g["net_n"] * 1e4, g["week"], seed=4)
        elo, ehi = wboot(g["excess_R"], g["week"], seed=5)
        return {**lab, "n": len(g), "weeks": g["week"].nunique(), "stop_med": g["stop_pct"].median(),
                "net_bp": g["net_n"].mean() * 1e4, "net_lo": nlo, "net_hi": nhi, "gross_bp": g["gross_n"].mean() * 1e4,
                "cost_bp": g["cost_bp"].mean(), "gross_R": g["gross_R"].mean(), "gR_lo": lo, "gR_hi": hi,
                "net_R": g["net_R"].mean(), "excess_R": g["excess_R"].mean(), "ex_lo": elo, "ex_hi": ehi,
                "cf_R": g["cf_R"].mean(), "liq_share": (g["reason"] == 2).mean()}

    rows = []
    for tf, g in D.groupby("tf"):
        rows.append(agg(g, {"tf": tf, "split": "all", "key": "*"}))
        for k, h in g.groupby("year"):
            rows.append(agg(h, {"tf": tf, "split": "year", "key": k}))
        for k, h in g.groupby("period"):
            rows.append(agg(h, {"tf": tf, "split": "period", "key": k}))
        for k, h in g.groupby("coin"):
            rows.append(agg(h, {"tf": tf, "split": "coin", "key": k}))
        q = pd.qcut(g["stop_pct"], 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
        for k, h in g.groupby(q, observed=True):
            rows.append(agg(h, {"tf": tf, "split": "volq", "key": k}))
        # per-strategy-equal-weight mean (each strategy counts once)
        ps = g.groupby("strategy").agg(net=("net_n", "mean"), gross=("gross_n", "mean"))
        rows.append({"tf": tf, "split": "strategy_equal_weight", "key": "*", "n": len(ps),
                     "net_bp": ps["net"].mean() * 1e4, "gross_bp": ps["gross"].mean() * 1e4,
                     "net_lo": ps["net"].min() * 1e4, "net_hi": ps["net"].max() * 1e4})
    S = pd.DataFrame(rows)
    S.to_csv(pre + "_splits.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print(S.round(4).to_string(index=False))
    rows = []
    for (s, tf), g in D.groupby(["strategy", "tf"]):
        r = agg(g, {"strategy": s, "tf": tf})
        for p in (1, 2):
            h = g[g["period"] == p]
            r[f"gross_R_p{p}"] = h["gross_R"].mean()
            r[f"net_bp_p{p}"] = h["net_n"].mean() * 1e4
        rows.append(r)
    ST = pd.DataFrame(rows)
    ST.to_csv(pre + "_by_strategy.csv", index=False)


if __name__ == "__main__":
    main()
