#!/usr/bin/env python3
"""Where the ROE ladder locks, in R units of the 2 ATR stop, per run x tf x leverage (from trades_enriched.csv).

    python3 -I ladder_geometry.py <trades_enriched.csv> <out_dir>

first trigger (net ROE 12%) price move = 0.12/lev + rt; first lock (10%) = 0.10/lev + rt; one ladder step (5% ROE)
= 0.05/lev; trail gap after arming = between 0.02/lev and 0.07/lev. In R: divide by stop_frac (= |entry - stop| /
entry). rt = 0.0014 (2 x (taker 0.05% + slippage 0.02%)). Also the share of trades whose MFE reached the first trigger
and the realized exit mix, and the 'what the same price geometry means at 10x / 20x / 30x / 50x'.
"""
import os
import site
import sys

sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RT = 0.0014
RUNNAME = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}


def main():
    T = pd.read_csv(sys.argv[1])
    out = sys.argv[2]
    T = T[T["kind"].isin(["strategy", "ds200", "random"]) & T["timeframe"].isin(["5m", "15m", "30m", "1h", "4h"])]
    T = T[T["exit_reason"].isin(["SL", "LOCK", "LIQ", "TIME"])]   # house exits (no reel TP)
    T["runl"] = T["run"].map(RUNNAME)
    sf = T["stop_frac"]
    for L in (10, 20, 30, 50):
        T[f"trig_R_{L}x"] = (0.12 / L + RT) / sf
        T[f"lock_R_{L}x"] = (0.10 / L + RT) / sf
        T[f"step_R_{L}x"] = (0.05 / L) / sf
    T["trig_R_own"] = (0.12 / T["leverage"] + RT) / sf
    T["lock_R_own"] = (0.10 / T["leverage"] + RT) / sf
    T["gapmax_R_own"] = (0.07 / T["leverage"]) / sf
    T["reached_trig"] = T["mfe_R"] >= T["trig_R_own"]
    rows = []
    for (runl, tf), g in T.groupby(["runl", "timeframe"]):
        r = {"run": runl, "tf": tf, "n": len(g), "median_stop_pct": 100 * g["stop_frac"].median(),
             "lev_mix": " ".join(f"{int(k)}:{v}" for k, v in g["leverage"].value_counts().items()),
             "trig_R_own_median": g["trig_R_own"].median(), "lock_R_own_median": g["lock_R_own"].median(),
             "trail_gap_max_R_own_median": g["gapmax_R_own"].median(),
             "share_LOCK": (g["exit_reason"] == "LOCK").mean(), "share_reached_trig": g["reached_trig"].mean(),
             "mean_R": g["R"].mean(), "mean_R_LOCK": g.loc[g["exit_reason"] == "LOCK", "R"].mean(),
             "mean_R_SL": g.loc[g["exit_reason"] == "SL", "R"].mean(),
             "mean_mfe_R": g["mfe_R"].mean(), "median_mfe_R_LOCK": g.loc[g["exit_reason"] == "LOCK", "mfe_R"].median(),
             "mean_giveback_R_LOCK": (g["mfe_R"] - g["R"]).loc[g["exit_reason"] == "LOCK"].mean(),
             "mean_cost_R": g["cost_R"].mean() if "cost_R" in g else np.nan}
        for L in (10, 20, 30, 50):
            r[f"trig_R_{L}x"] = g[f"trig_R_{L}x"].median()
            r[f"lock_R_{L}x"] = g[f"lock_R_{L}x"].median()
        rows.append(r)
    D = pd.DataFrame(rows)
    D.to_csv(os.path.join(out, "ladder_geometry.csv"), index=False)
    pd.set_option("display.width", 250)
    print(D.round(3).to_string())


if __name__ == "__main__":
    main()
