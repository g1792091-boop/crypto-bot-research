#!/usr/bin/env python3
"""Independent decomposition of live paper trades from the RAW export (not trades_enriched).

python3 -I v1_live_decomp.py <export_dir> <out_dir>

Entry reference = outcomes.csv ref_price of the ENTERED row (joined by account_id + sig_ts), not inferred from 2 bp.
Exit reference for stop/lock exits = exit_price / (1 - side*0.0002) (engine._close for stop-market); checked vs
the stop level for non-gap exits.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vboot  # noqa
import numpy as np
import pandas as pd

RUNS = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
SLIP = 0.0002


def cluster_ci(x, cl, n_boot=4000, seed=1):
    x = np.asarray(x, float)
    cl = np.asarray(cl)
    u, inv = np.unique(cl, return_inverse=True)
    k = len(u)
    if k < 3:
        return np.nan, np.nan, k
    sums = np.bincount(inv, weights=x, minlength=k)
    cnts = np.bincount(inv, minlength=k).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(n_boot, k))
    m = sums[idx].sum(1) / cnts[idx].sum(1)
    return np.percentile(m, 2.5), np.percentile(m, 97.5), k


def main():
    ex, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    rows = []
    for r, tag in RUNS.items():
        T = pd.read_csv(os.path.join(ex, r, "trades.csv"))
        A = pd.read_csv(os.path.join(ex, r, "accounts.csv"))
        O = pd.read_csv(os.path.join(ex, r, "outcomes.csv"))
        O = O[O["status"] == "ENTERED"][["account_id", "sig_ts", "ref_price", "symbol"]]
        T = T.merge(A[["account_id", "kind"]], on="account_id", how="left")
        T = T.merge(O.rename(columns={"sig_ts": "signal_ts", "symbol": "o_sym"}), on=["account_id", "signal_ts"],
                    how="left")
        T["run"] = tag
        rows.append(T)
    T = pd.concat(rows, ignore_index=True)
    print("trades", len(T), "missing ref", T["ref_price"].isna().sum(), "kinds", T["kind"].value_counts().to_dict())
    s = T["side"].astype(float)
    T["risk"] = T["qty"] * (T["entry_price"] - T["stop_initial"]).abs()
    T["R"] = T["pnl"] / T["risk"]
    # entry slip measured vs the outcome ref price
    T["entry_slip_bps"] = s * (T["entry_price"] / T["ref_price"] - 1) * 1e4
    print("entry slip bps vs ref (should be 2):", T.groupby("run")["entry_slip_bps"].describe().round(4).to_string())
    stop_exit = T["exit_reason"].isin(["SL", "LOCK"])
    T["exit_raw"] = np.where(stop_exit, T["exit_price"] / (1 - s * SLIP), T["exit_price"])
    T["gross_pre_R"] = s * T["qty"] * (T["exit_raw"] - T["ref_price"]) / T["risk"]
    T["fill_gross_R"] = s * T["qty"] * (T["exit_price"] - T["entry_price"]) / T["risk"]
    T["fee_R"] = T["fees"] / T["risk"]
    T["fund_R"] = T["funding"] / T["risk"]
    T["slip_R"] = T["gross_pre_R"] - T["fill_gross_R"]
    T["cost_R"] = T["gross_pre_R"] - T["R"]
    T["chk"] = T["cost_R"] - (T["fee_R"] + T["fund_R"] + T["slip_R"])
    print("identity max err", T["chk"].abs().max())
    # gap through the stop level for stop exits (raw exit beyond stop level)
    T["gap_bps"] = np.where(stop_exit, np.maximum(0, s * (T["stop_price"] - T["exit_raw"]) / T["entry_price"] * 1e4), 0)
    T["gap_R"] = np.where(stop_exit, np.maximum(0, s * T["qty"] * (T["stop_price"] - T["exit_raw"]) / T["risk"]), 0)
    T["stop_pct"] = (T["entry_price"] - T["stop_initial"]).abs() / T["entry_price"] * 100
    T["notional"] = T["qty"] * T["entry_price"]
    T["cl"] = T["run"] + "|" + (T["entry_time"] // 3600000).astype(str)
    T.to_csv(os.path.join(out, "v1_trades.csv"), index=False)

    T["grp"] = T["kind"].map({"strategy": "core36", "ds200": "ds200", "random": "coinflip", "reel": "reel"})
    res = []
    for (g, tf), d in T.groupby(["grp", "timeframe"]):
        lo, hi, k = cluster_ci(d["gross_pre_R"], d["cl"])
        res.append(dict(grp=g, tf=tf, n=len(d), clusters_1h=k, net_R=d["R"].mean(), gross_pre_R=d["gross_pre_R"].mean(),
                        gross_lo=lo, gross_hi=hi, fill_gross_R=d["fill_gross_R"].mean(), cost_R=d["cost_R"].mean(),
                        fee_R=d["fee_R"].mean(), slip_R=d["slip_R"].mean(), fund_R=d["fund_R"].mean(),
                        median_stop_pct=d["stop_pct"].median(), n_LIQ=int((d["exit_reason"] == "LIQ").sum()),
                        median_notional=d["notional"].median(), mean_lev=d["leverage"].mean()))
    D = pd.DataFrame(res)
    D.to_csv(os.path.join(out, "v1_decomp_by_tf.csv"), index=False)
    pd.set_option("display.width", 250)
    print(D.round(4).to_string(index=False))
    # per run for core36/ds200 15m/30m
    res = []
    for (rn, g, tf), d in T.groupby(["run", "grp", "timeframe"]):
        if g not in ("core36", "ds200") or tf not in ("15m", "30m", "1h"):
            continue
        lo, hi, k = cluster_ci(d["gross_pre_R"], d["cl"])
        res.append(dict(run=rn, grp=g, tf=tf, n=len(d), net_R=d["R"].mean(), gross_pre_R=d["gross_pre_R"].mean(),
                        lo=lo, hi=hi, cost_R=d["cost_R"].mean(), mean_lev=d["leverage"].mean()))
    print(pd.DataFrame(res).round(4).to_string(index=False))

    # SL decomposition (C5) and LOCK gap (C11), core36+ds200
    K = T[T["grp"].isin(["core36", "ds200"])]
    SL = K[K["exit_reason"] == "SL"]
    sg = SL.groupby("timeframe").agg(n=("R", "size"), R=("R", "mean"), fee=("fee_R", "mean"),
                                    exit_slip=("slip_R", lambda x: np.nan), gap=("gap_R", "mean"),
                                    fund=("fund_R", "mean"), exact=("gap_bps", lambda x: (x <= 0.01).mean()))
    # exit slip only: qty*|exit_raw-exit_price|/risk
    SL = SL.assign(exit_slip_R=SL["qty"] * (SL["exit_raw"] - SL["exit_price"]).abs() / SL["risk"],
                   entry_slip_R=SL["qty"] * (SL["entry_price"] - SL["ref_price"]).abs() / SL["risk"],
                   R_vs_ref=SL["pnl"] / (SL["qty"] * (SL["ref_price"] - SL["stop_initial"]).abs()))
    sg["exit_slip"] = SL.groupby("timeframe")["exit_slip_R"].mean()
    sg["entry_slip"] = SL.groupby("timeframe")["entry_slip_R"].mean()
    sg["R_if_risk_from_ref"] = SL.groupby("timeframe")["R_vs_ref"].mean()
    print("SL decomposition\n", sg.round(4).to_string())
    LK = K[K["exit_reason"] == "LOCK"]
    lg = LK.groupby("timeframe").agg(n=("R", "size"), gap_share=("gap_bps", lambda x: (x > 0.01).mean()),
                                    gap_bps=("gap_bps", "mean"), gap_p90=("gap_bps", lambda x: x.quantile(.9)),
                                    gap_bps_given_gap=("gap_bps", lambda x: x[x > 0.01].mean()),
                                    gap_R=("gap_R", "mean"), lock_R=("R", "mean"), gross=("gross_pre_R", "mean"),
                                    cost=("cost_R", "mean"), lev=("leverage", "mean"))
    lg["cost_share"] = lg["cost"] / lg["gross"]
    print("LOCK\n", lg.round(4).to_string())
    # lock gap by leverage
    print(LK.groupby(["timeframe", "leverage"]).agg(n=("R", "size"), gap_share=("gap_bps", lambda x: (x > 0.01).mean()),
                                                     gap_bps=("gap_bps", "mean")).round(3).to_string())


if __name__ == "__main__":
    main()
