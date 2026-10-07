#!/usr/bin/env python3
"""Giveback, dead entries, time-to-MFE / time-to-stop, and upper bounds of recoverable R.

    python3 -I headroom.py <trades_enriched.csv> <rules_signals.csv> <out_dir>

Two sources:
  trades : the accounts' real closed trades (all three runs, incl. v3a; v3a is 50x tier-walk), trades_enriched.csv
  signals: every SUBMITTED signal alone (v3b + v4), base rules, from rules_signals.csv (open-at-end marked)
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True
import site  # noqa: E402
sys.path.append(site.getusersitepackages())
import os  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RUNS = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
TFM = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


def metrics(g: pd.DataFrame) -> dict:
    n = len(g)
    if not n:
        return {"n": 0}
    R, mfe, cost = g["R"].to_numpy(float), g["mfe_R"].to_numpy(float), g["cost_R"].to_numpy(float)
    er = g["exit_reason"].astype(str).to_numpy()
    lose = R < 0
    sl = er == "SL"
    gb05 = (mfe >= 0.5) & lose
    gb10 = (mfe >= 1.0) & lose
    gb05_sl = (mfe >= 0.5) & sl
    gb10_sl = (mfe >= 1.0) & sl
    half = (mfe >= 1.0) & (R >= 0) & (R < 0.5 * mfe)
    dead = lose & (mfe < 0.2)
    r_cut = -0.5 - cost
    ub_gb = np.where(gb05, -R, 0.0).sum() / n                       # perfect breakeven on the losers that saw +0.5R
    ub_half = np.where(half, 0.5 * mfe - R, 0.0).sum() / n          # keep half of MFE on small locks after +1R
    ub_dead = np.where(dead & (R < r_cut), r_cut - R, 0.0).sum() / n  # cut dead losers at -0.5R
    oracle = np.maximum(mfe - cost - R, 0).sum() / n                 # exit exactly at the best price (net of costs)
    return {"n": n, "mean_R": R.mean(), "win_pct": 100 * (R > 0).mean(), "mean_mfe_R": mfe.mean(),
            "share_mfe_ge_0.5": (mfe >= 0.5).mean(), "share_mfe_ge_1": (mfe >= 1).mean(),
            "share_gb05_loss": gb05.mean(), "share_gb10_loss": gb10.mean(),
            "share_gb05_SL": gb05_sl.mean(), "share_gb10_SL": gb10_sl.mean(),
            "share_small_lock_after_1R": half.mean(),
            "share_losers": lose.mean(), "dead_share_of_losers": dead.sum() / max(lose.sum(), 1),
            "dead_share_all": dead.mean(), "mean_R_dead": R[dead].mean() if dead.any() else np.nan,
            "mean_R_gb05_loss": R[gb05].mean() if gb05.any() else np.nan,
            "ub_breakeven_gb_R": ub_gb, "ub_half_mfe_R": ub_half, "ub_cut_dead_R": ub_dead,
            "ub_sum_R": ub_gb + ub_half + ub_dead, "oracle_exit_R": oracle, "mean_cost_R": cost.mean()}


def main():
    t_path, s_path, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    T = pd.read_csv(t_path)
    T = T[T["kind"].isin(["strategy", "ds200", "random"]) & (T["exits"] == "house")].copy()
    T["run_s"] = T["run"].map(RUNS)
    T["src"] = "trades"
    S = pd.read_csv(s_path)
    S = S[S["base_status"].isin(["TRADED", "UNRESOLVED"])].copy()
    S = S.rename(columns={"base_R": "R", "base_mfe_R": "mfe_R", "base_exit_reason": "exit_reason",
                          "base_cost_R": "cost_R", "base_hold_min": "hold_min"})
    # cost for open-at-end rows: entry fee + estimated exit (taker + slippage), in R
    st = (S["base_entry_price"] - S["base_stop_initial"]).abs() / S["base_entry_price"]
    S["cost_R"] = S["cost_R"].fillna((0.0005 + 0.0005 + 0.0002) / st)
    S["run_s"] = S["run"].map(RUNS)
    S["tf"] = S["timeframe"]
    S["src"] = "signals"
    rows = []
    for src, D in (("trades", T), ("signals", S)):
        for run_s in ["ALL"] + sorted(D["run_s"].unique()):
            Dr = D if run_s == "ALL" else D[D["run_s"] == run_s]
            for kind in ["strategy", "ds200", "random"]:
                for tf in ["5m", "15m", "30m", "1h", "4h"]:
                    g = Dr[(Dr["kind"] == kind) & (Dr["tf"] == tf)]
                    if len(g):
                        rows.append({"src": src, "run": run_s, "kind": kind, "tf": tf, **metrics(g)})
    K = pd.DataFrame(rows)
    K.to_csv(os.path.join(out, "giveback_kind_tf.csv"), index=False)
    cells = []
    for src, D in (("trades", T), ("signals", S)):
        for (kind, strat, tf), g in D[D["kind"] != "random"].groupby(["kind", "strategy", "tf"]):
            m = metrics(g)
            for rs in ("v3a", "v3b", "v4"):
                gg = g[g["run_s"] == rs]
                m[f"n_{rs}"] = len(gg)
                m[f"ub_sum_R_{rs}"] = metrics(gg)["ub_sum_R"] if len(gg) else np.nan
                m[f"mean_R_{rs}"] = gg["R"].mean() if len(gg) else np.nan
            cells.append({"src": src, "kind": kind, "strategy": strat, "tf": tf, **m})
    C = pd.DataFrame(cells)
    C.to_csv(os.path.join(out, "giveback_cells.csv"), index=False)

    # time to MFE thresholds / time to stop (every signal, base), in bars of the signal's timeframe
    S["tfm"] = S["tf"].map(TFM)
    trows = []
    for kind in ["strategy", "ds200"]:
        for tf in ["15m", "30m", "1h", "4h"]:
            g = S[(S["kind"] == kind) & (S["tf"] == tf)]
            if not len(g):
                continue
            row = {"kind": kind, "tf": tf, "n": len(g)}
            for th in ("0.3", "0.5", "1.0"):
                c = f"p_t_mfe{th}_min"
                v = g[c].dropna() / g["tfm"].iloc[0]
                row[f"reach_{th}R_share"] = g[c].notna().mean()
                row[f"bars_to_{th}R_p25"] = v.quantile(0.25) if len(v) else np.nan
                row[f"bars_to_{th}R_med"] = v.median() if len(v) else np.nan
                row[f"bars_to_{th}R_p75"] = v.quantile(0.75) if len(v) else np.nan
            sl = g[g["exit_reason"] == "SL"]
            v = sl["hold_min"] / g["tfm"].iloc[0]
            row["n_SL"] = len(sl)
            row["bars_to_SL_p25"], row["bars_to_SL_med"], row["bars_to_SL_p75"] = v.quantile([.25, .5, .75]).to_numpy()
            sl_dead = sl[sl["mfe_R"] < 0.2]
            row["SL_dead_share"] = len(sl_dead) / max(len(sl), 1)
            row["bars_to_SL_dead_med"] = (sl_dead["hold_min"] / g["tfm"].iloc[0]).median()
            lk = g[g["exit_reason"] == "LOCK"]
            row["n_LOCK"] = len(lk)
            row["bars_to_LOCK_med"] = (lk["hold_min"] / g["tfm"].iloc[0]).median()
            tmax = g["p_t_max_mfe_min"] / g["tfm"].iloc[0]
            row["bars_to_max_mfe_med"] = tmax.median()
            # where losers peaked: share of SL trades whose best moment came within the first 2 bars
            row["SL_peak_within_2bars_share"] = (sl["p_t_max_mfe_min"] / g["tfm"].iloc[0] <= 2).mean()
            # MAE before reaching +0.5R among trades that reached it
            row["mae_before_0.5R_med"] = g["p_mae_before_0.5_R"].median()
            trows.append(row)
    TT = pd.DataFrame(trows)
    TT.to_csv(os.path.join(out, "time_to_mfe_stop.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    cols = ["src", "run", "kind", "tf", "n", "mean_R", "share_mfe_ge_0.5", "share_mfe_ge_1", "share_gb05_SL",
            "share_gb10_SL", "share_small_lock_after_1R", "dead_share_of_losers", "dead_share_all",
            "ub_breakeven_gb_R", "ub_half_mfe_R", "ub_cut_dead_R", "ub_sum_R", "oracle_exit_R"]
    print(K[K["run"] == "ALL"][cols].round(3).to_string())
    print(K[(K["run"] != "ALL") & K["tf"].isin(["15m", "30m"])][cols].round(3).to_string())
    print(TT.round(2).T.to_string())


if __name__ == "__main__":
    main()
