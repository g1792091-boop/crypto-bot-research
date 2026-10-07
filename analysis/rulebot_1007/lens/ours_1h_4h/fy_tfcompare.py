"""5-year: is a strategy better on 1h / 4h than on 15m / 30m? Per strategy, every sized signal under the current
live rules (fy_sim.py). Difference of mean R (net) and of mean gross R (net + round-trip cost in R) between the
higher timeframe (1h or 4h) and the pooled 15m + 30m signals, standard error clustered by UTC day (the two groups
share days; the regression-on-indicator form keeps the covariance). BH over the 36 x 2 comparisons, per measure.
IS / CF windows reported separately (a 'better on HTF' that holds in both windows is the bar).

    python3 -I fy_tfcompare.py <fy_signals.pkl> <out_csv>
"""
import site
import sys
from math import erf, sqrt

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

IN, OUT = sys.argv[1:3]
DAY = 86_400_000


def diff_cl(y, x, cl):
    """OLS of y on [1, x] (x = 1 for HTF): slope and day-clustered SE."""
    if x.sum() < 3 or (1 - x).sum() < 3:
        return np.nan, np.nan
    xm = x.mean()
    xd = x - xm
    sxx = (xd ** 2).sum()
    b = (xd * (y - y.mean())).sum() / sxx
    e = y - y.mean() - b * xd
    sc = pd.Series(xd * e).groupby(cl).sum().to_numpy()
    G = len(sc)
    se = np.sqrt(G / (G - 1) * (sc ** 2).sum()) / sxx
    return b, se


def p2(t):
    return 2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2)))) if t == t else np.nan


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


def main():
    D = pd.read_pickle(IN)
    for c in ("strategy", "tf", "coin"):
        D[c] = D[c].astype(str)
    D = D[(D["lev"] > 0) & D["R"].notna()].copy()
    D["cost_R"] = 0.0014 / (2 * D["atr_frac"].astype(float) + 0.0002)
    D["gross_R"] = D["R"] + D["cost_R"]
    D["day"] = D["close_ms"] // DAY
    rows = []
    for s, g in D.groupby("strategy"):
        ltf = g[g["tf"].isin(["15m", "30m"])]
        for htf in ("1h", "4h"):
            h = g[g["tf"] == htf]
            d = {"strategy": s, "htf": htf, "n_htf": len(h), "n_ltf": len(ltf),
                 "mean_R_htf": h["R"].mean(), "mean_R_ltf": ltf["R"].mean(),
                 "gross_R_htf": h["gross_R"].mean(), "gross_R_ltf": ltf["gross_R"].mean(),
                 "mean_R_15m": g.loc[g["tf"] == "15m", "R"].mean(), "mean_R_30m": g.loc[g["tf"] == "30m", "R"].mean()}
            both = pd.concat([ltf.assign(_x=0.0), h.assign(_x=1.0)])
            for meas in ("R", "gross_R"):
                for w, wl in ((None, "all"), (0, "is"), (1, "cf")):
                    bb = both if w is None else both[both["win"] == w]
                    b, se = diff_cl(bb[meas].to_numpy(float), bb["_x"].to_numpy(float), bb["day"].to_numpy())
                    d[f"d_{meas}_{wl}"], d[f"se_{meas}_{wl}"] = b, se
                    d[f"t_{meas}_{wl}"] = b / se if se == se and se > 0 else np.nan
            rows.append(d)
    out = pd.DataFrame(rows)
    for meas in ("R", "gross_R"):
        out[f"p_{meas}_all"] = out[f"t_{meas}_all"].map(p2)
        out[f"bh_q_{meas}_all"] = bh(out[f"p_{meas}_all"])
        out[f"holds_both_windows_{meas}"] = (np.sign(out[f"d_{meas}_is"]) == np.sign(out[f"d_{meas}_cf"])) & \
            (out[f"t_{meas}_is"].abs() > 2) & (out[f"t_{meas}_cf"].abs() > 2)
    out.to_csv(OUT, index=False)
    pd.set_option("display.width", 250)
    cols = ["strategy", "htf", "n_htf", "mean_R_htf", "mean_R_ltf", "d_R_all", "t_R_all", "gross_R_htf", "gross_R_ltf",
            "d_gross_R_all", "t_gross_R_all", "d_gross_R_is", "d_gross_R_cf", "bh_q_gross_R_all",
            "holds_both_windows_gross_R"]
    print(out[cols].round(3).to_string())
    print("net R better on HTF (BH q<0.05, d>0):", int(((out["bh_q_R_all"] < 0.05) & (out["d_R_all"] > 0)).sum()),
          "of", out["bh_q_R_all"].notna().sum())
    print("gross R better on HTF (BH q<0.05, d>0):",
          int(((out["bh_q_gross_R_all"] < 0.05) & (out["d_gross_R_all"] > 0)).sum()),
          "worse:", int(((out["bh_q_gross_R_all"] < 0.05) & (out["d_gross_R_all"] < 0)).sum()))
    print("gross holds both windows (better):", int((out["holds_both_windows_gross_R"] & (out["d_gross_R_all"] > 0)).sum()))


if __name__ == "__main__":
    main()
