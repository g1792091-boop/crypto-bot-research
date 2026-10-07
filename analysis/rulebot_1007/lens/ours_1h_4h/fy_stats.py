"""Per strategy x timeframe statistics of the 5-year every-signal simulation (fy_sim.py, current live rules).

    python3 -I fy_stats.py <fy_signals.pkl> <out_csv>

Mean R over sized, resolved signals (reason 0/1/2; the few still open after 4,096 bars are marked to the last close and
counted too: n_open). Uncertainty is cluster-robust by UTC day (all coins and signals of one day = one cluster):
se = sqrt(G/(G-1) * sum_g (sum_i (R_i - mean))^2) / N. IS = 2021-08-01..2024-07-01, CF = 2024-07-01..2026-09-30.
cost_R = round trip (2 x (taker + slippage) = 0.14%) / stop fraction (|fill - stop| / fill); gross_R = R + cost_R
(funding not added back). Also per coin: share of signals sized (not rejected for stop too close to liquidation).
"""
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

IN, OUT = sys.argv[1:3]
DAY = 86_400_000


def cl_stats(x: np.ndarray, cl: np.ndarray) -> tuple:
    n = len(x)
    if n < 3:
        return (np.nan, np.nan, np.nan, 0)
    m = x.mean()
    s = pd.Series(x - m).groupby(cl).sum().to_numpy()
    G = len(s)
    if G < 3:
        return (m, np.nan, np.nan, G)
    se = np.sqrt(G / (G - 1) * (s ** 2).sum()) / n
    return (m, se, m / se if se > 0 else np.nan, G)


def main():
    D = pd.read_pickle(IN)
    D["day"] = D["close_ms"] // DAY
    D["sized"] = D["lev"] > 0
    D["stop_frac"] = (2 * D["atr_frac"].astype(float) + 0.0002)
    D["cost_R"] = 0.0014 / D["stop_frac"]
    span = {}
    for tf, g in D.groupby("tf", observed=True):
        span[tf] = (g["close_ms"].max() - g["close_ms"].min()) / DAY
    rows = []
    for (s, tf), g in D.groupby(["strategy", "tf"], observed=True):
        z = g[g["sized"] & g["R"].notna()]
        x = z["R"].to_numpy(float)
        m, se, t, G = cl_stats(x, z["day"].to_numpy())
        d = {"strategy": s, "tf": tf, "fy_signals": len(g), "fy_per_day": len(g) / max(span[tf], 1),
             "fy_sized_share": g["sized"].mean(), "fy_n": len(z), "fy_n_open": int((z["reason"] == 3).sum()),
             "fy_mean_R": m, "fy_se_R": se, "fy_t_R": t, "fy_days": G,
             "fy_ci95_lo": m - 1.96 * se if se == se else np.nan, "fy_ci95_hi": m + 1.96 * se if se == se else np.nan,
             "fy_win_pct": 100 * (z["roe"] > 0).mean() if len(z) else np.nan,
             "fy_median_R": float(np.median(x)) if len(x) else np.nan,
             "fy_cost_R": z["cost_R"].mean(), "fy_gross_R": (z["R"] + z["cost_R"]).mean(),
             "fy_gross_t": cl_stats((z["R"] + z["cost_R"]).to_numpy(float), z["day"].to_numpy())[2],
             "fy_lock_share": (z["reason"] == 1).mean(), "fy_liq_share": (z["reason"] == 2).mean(),
             "fy_median_hold_h": float(np.median(z["held"])) * {"15m": .25, "30m": .5, "1h": 1, "4h": 4}[tf]
             if len(z) else np.nan, "fy_long_share": (z["side"] > 0).mean()}
        aw, al = x[x > 0], x[x <= 0]
        d["fy_payoff"] = aw.mean() / -al.mean() if len(aw) and len(al) and al.mean() < 0 else np.nan
        for w, lab in ((0, "is"), (1, "cf")):
            zz = z[z["win"] == w]
            mm, se2, t2, _ = cl_stats(zz["R"].to_numpy(float), zz["day"].to_numpy())
            d[f"fy_{lab}_n"], d[f"fy_{lab}_mean_R"], d[f"fy_{lab}_t_R"] = len(zz), mm, t2
            d[f"fy_{lab}_gross_R"] = (zz["R"] + zz["cost_R"]).mean() if len(zz) else np.nan
            d[f"fy_{lab}_gross_t"] = cl_stats((zz["R"] + zz["cost_R"]).to_numpy(float), zz["day"].to_numpy())[2]
        # by year (calendar, UTC): how many years positive
        yr = pd.to_datetime(z["close_ms"], unit="ms").dt.year
        ym = z.groupby(yr.to_numpy())["R"].mean()
        d["fy_years_pos"] = int((ym > 0).sum())
        d["fy_years"] = len(ym)
        for c, gc in g.groupby("coin", observed=True):
            d[f"fy_sized_{c}"] = gc["sized"].mean()
        rows.append(d)
    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(out.groupby("tf")[["fy_mean_R", "fy_gross_R", "fy_cost_R", "fy_sized_share"]].median())
    print("cells with fy_mean_R > 0:", out[out.fy_mean_R > 0][["strategy", "tf", "fy_n", "fy_mean_R", "fy_t_R",
                                                                "fy_is_mean_R", "fy_cf_mean_R"]].to_string())


if __name__ == "__main__":
    main()
