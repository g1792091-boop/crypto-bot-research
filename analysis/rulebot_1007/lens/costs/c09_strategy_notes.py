#!/usr/bin/env python3
"""Per strategy x timeframe cost grade: live gross edge (every signal, v3b + v4) vs live cost, and the five-year gross.

    python3 -I c09_strategy_notes.py <c05_base_accounting.csv> <c07_5y_by_strategy.csv> <fiveyear_ref.csv> <out_dir>

Grades (cost lens; 'gross' = before fees, slippage and funding):
  A  five-year gross >= cost at live volatility, both periods  (none)
  B  five-year gross > 0 with week-block CI above 0 and > 0 in both periods: a small real pre-cost edge
     (still far below the cost; the AI must add the rest)
  C  five-year gross indistinguishable from 0: a coin flip before costs; the AI must supply the whole cost
  D  five-year gross < 0 (CI below 0, or both periods < 0): loses before costs; an AI would first have to undo it
DeepSeek: five-year gross = ds_is / ds_cf gross mean % per trade of its PREREG exits (X5_TRAIL2), unlevered.
AI edge needed (R per trade, live volatility, real taker costs) = live real cost R - max(five-year gross R, 0).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


def cboot(x, cl, B=2000, seed=5):
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    x, cl = x[ok], np.asarray(cl)[ok]
    if len(x) < 5:
        return np.nan, np.nan
    u, inv = np.unique(cl, return_inverse=True)
    s, c = np.bincount(inv, weights=x), np.bincount(inv)
    rng = np.random.default_rng(seed)
    d = rng.integers(0, len(u), size=(B, len(u)))
    m = s[d].sum(1) / c[d].sum(1)
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    acc_csv, y5_csv, ref_csv, out = sys.argv[1:5]
    A = pd.read_csv(acc_csv)
    A = A[A["grp"].isin(["core36", "ds200"])]
    Y = pd.read_csv(y5_csv).set_index(["strategy", "tf"])
    F = pd.read_csv(ref_csv)
    DS = F[(F["source"] == "deepseek200") & (F["variant"] == "X5_TRAIL2")].set_index(["strategy", "timeframe"])
    rows = []
    for (grp, strat, tf), g in A.groupby(["grp", "strategy", "timeframe"]):
        lo, hi = cboot(g["gross_R"], g["cluster"])
        r = {"grp": grp, "strategy": strat, "tf": tf, "live_n": len(g), "live_clusters": g["cluster"].nunique(),
             "live_median_stop_pct": g["stop_frac_own"].median() * 100, "live_net_R": g["R_own"].mean(),
             "live_gross_R": g["gross_R"].mean(), "live_gross_ci_lo": lo, "live_gross_ci_hi": hi,
             "live_cost_R_paper": g["cost_paper_R"].mean(), "live_cost_R_real": g["cost_real_R"].mean()}
        if grp == "core36" and (strat, tf) in Y.index:
            y = Y.loc[(strat, tf)]
            r.update({"y5_n": int(y["n"]), "y5_net_bps": y["net_bps_notional"], "y5_gross_bps": y["gross_bps_notional"],
                      "y5_gross_R": y["gross_R"], "y5_gross_ci_lo": y["gross_R_ci_lo"], "y5_gross_ci_hi": y["gross_R_ci_hi"],
                      "y5_gross_R_p1": y["gross_R_p1"], "y5_gross_R_p2": y["gross_R_p2"], "y5_side_excess_R": y["excess_side_R"],
                      "y5_cost_R": y["cost_R"]})
            pos = (y["gross_R_ci_lo"] > 0) and (y["gross_R_p1"] > 0) and (y["gross_R_p2"] > 0)
            neg = (y["gross_R_ci_hi"] < 0) or ((y["gross_R_p1"] < 0) and (y["gross_R_p2"] < 0) and y["gross_R"] < -0.005)
            cover = y["gross_R"] >= r["live_cost_R_real"]
            r["grade"] = "A" if cover else ("B" if pos else ("D" if neg else "C"))
            gross5 = y["gross_R"]
        elif grp == "ds200" and (strat, tf) in DS.index:
            d = DS.loc[(strat, tf)]
            gi, gc, cst = d["ds_is_gross_mean_pct"], d["ds_cf_gross_mean_pct"], d["ds_is_cost_mean_pct"]
            r.update({"y5_n": d["ds_is_n"], "y5_gross_bps": gi * 100, "y5_gross_bps_cf": gc * 100, "y5_cost_bps": cst * 100,
                      "y5_net_bps": d["ds_is_mean_pct"] * 100})
            r["grade"] = "B" if (gi > 0 and gc > 0) else ("D" if (gi < 0 and gc < 0) else "C")
            gross5 = np.nan
        else:
            r["grade"] = "n/a"
            gross5 = np.nan
        r["ai_edge_needed_R_real"] = r["live_cost_R_real"] - (max(gross5, 0.0) if gross5 == gross5 else 0.0)
        rows.append(r)
    N = pd.DataFrame(rows)
    N.to_csv(os.path.join(out, "c09_strategy_cost_grades.csv"), index=False)
    pd.set_option("display.width", 300)
    pd.set_option("display.max_rows", 500)
    cols = ["grp", "strategy", "tf", "grade", "live_n", "live_median_stop_pct", "live_net_R", "live_gross_R",
            "live_gross_ci_lo", "live_gross_ci_hi", "live_cost_R_real", "y5_n", "y5_net_bps", "y5_gross_bps",
            "y5_gross_R", "y5_gross_ci_lo", "y5_gross_ci_hi", "y5_gross_R_p1", "y5_gross_R_p2", "y5_gross_bps_cf",
            "ai_edge_needed_R_real"]
    X = N[N["tf"].isin(["15m", "30m"])].sort_values(["grp", "tf", "grade", "strategy"])
    print(X[cols].round(3).to_string(index=False))
    print(N.groupby(["grp", "tf", "grade"]).size().unstack(fill_value=0))


if __name__ == "__main__":
    main()
