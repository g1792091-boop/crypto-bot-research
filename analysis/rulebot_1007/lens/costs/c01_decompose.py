#!/usr/bin/env python3
"""Cost decomposition of every live paper trade (trades_enriched.csv).

    python3 -I c01_decompose.py <trades_enriched.csv> <out_dir>

Paper fill model (paperbot/engine.py): entry = ref * (1 + side * 2bp) where ref = ask (long) / bid (short) at the
moment the signal was ready (sigservice.compute), taker 5 bp; stop / lock exits = stop * (1 - side * 2bp) or the 1m
bar open if it gapped through, taker 5 bp; TP (reel only) = limit price, maker 2 bp; funding paid at 00/08/16 UTC.

R (pipeline) = pnl / (qty * |entry_fill - stop_initial|).  Components below are in the same R units:
    gross_ref_R   = side * qty * (exit_raw - entry_ref) / risk     price move between the two reference prices
    entry_slip_R  = qty * |entry_fill - entry_ref| / risk           paper's 2 bp entry slippage
    exit_slip_R   = qty * |exit_fill - exit_raw| / risk             paper's 2 bp exit slippage (stop-market exits)
    gap_R         = for stop exits: side * qty * (stop_level - exit_raw) / risk   (bar opened through the stop)
    fee_R, funding_R
    R = gross_ref_R - entry_slip_R - exit_slip_R - fee_R - funding_R   (checked per trade)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SLIP = 0.0002


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    T = pd.read_csv(src)
    T = T[T["kind"].isin(["strategy", "ds200", "random", "reel"])].copy()
    s = T["side"].astype(float)
    risk = T["risk_usd"]
    T["entry_ref"] = T["entry_price"] / (1 + s * SLIP)
    stop_exit = T["exit_reason"].isin(["SL", "LOCK"])
    T["exit_raw"] = np.where(stop_exit, T["exit_price"] / (1 - s * SLIP), T["exit_price"])
    T["entry_slip_R"] = T["qty"] * (T["entry_price"] - T["entry_ref"]).abs() / risk
    T["exit_slip_R"] = np.where(stop_exit, T["qty"] * (T["exit_raw"] - T["exit_price"]).abs() / risk, 0.0)
    T["gross_ref_R"] = s * T["qty"] * (T["exit_raw"] - T["entry_ref"]) / risk
    T["fee_R"] = T["fees"] / risk
    T["funding_R"] = T["funding"] / risk
    T["check"] = T["gross_ref_R"] - T["entry_slip_R"] - T["exit_slip_R"] - T["fee_R"] - T["funding_R"] - T["R"]
    # gap: stop exits whose raw exit is beyond the stop level (stop_price = the level live at exit)
    lvl = T["stop_price"]
    T["gap_R"] = np.where(stop_exit, np.maximum(0.0, s * T["qty"] * (lvl - T["exit_raw"]) / risk), 0.0)
    T["gap_bps"] = np.where(stop_exit, np.maximum(0.0, s * (lvl - T["exit_raw"]) / T["entry_price"] * 1e4), 0.0)
    T["fee_bps"] = T["fees"] / (T["qty"] * T["entry_price"]) * 1e4
    T["cost_paper_R"] = T["entry_slip_R"] + T["exit_slip_R"] + T["fee_R"] + T["funding_R"]
    T["stop_bps"] = T["stop_frac"] * 1e4
    T["notional"] = T["qty"] * T["entry_price"]
    T["cost_eq"] = (T["fees"] + T["funding"] + SLIP * T["notional"] * (1 + stop_exit.astype(float))) / T["eq_before"]
    T["grp"] = T["kind"].map({"strategy": "core36", "ds200": "ds200", "random": "coinflip", "reel": "reel"})
    T.to_csv(os.path.join(out, "c01_trades_decomposed.csv"), index=False)
    print("max |check| (R identity):", float(T["check"].abs().max()))

    def agg(g):
        sl = g[g["exit_reason"] == "SL"]
        lk = g[g["exit_reason"] == "LOCK"]
        return pd.Series({
            "n": len(g), "n_SL": len(sl), "n_LOCK": len(lk), "n_TP": int((g["exit_reason"] == "TP").sum()),
            "n_LIQ": int((g["exit_reason"] == "LIQ").sum()),
            "median_stop_pct": g["stop_frac"].median() * 100,
            "mean_R": g["R"].mean(), "mean_gross_ref_R": g["gross_ref_R"].mean(),
            "mean_cost_R": g["cost_paper_R"].mean(),
            "fee_R": g["fee_R"].mean(), "entry_slip_R": g["entry_slip_R"].mean(), "exit_slip_R": g["exit_slip_R"].mean(),
            "funding_R": g["funding_R"].mean(), "gap_R": g["gap_R"].mean(),
            "cost_share_of_loss": (g["cost_paper_R"].mean() / -g["R"].mean()) if g["R"].mean() < 0 else np.nan,
            "SL_mean_R": sl["R"].mean(), "SL_fee_R": sl["fee_R"].mean(), "SL_exit_slip_R": sl["exit_slip_R"].mean(),
            "SL_gap_R": sl["gap_R"].mean(), "SL_funding_R": sl["funding_R"].mean(),
            "SL_gap_share": (sl["gap_R"] > 1e-9).mean() if len(sl) else np.nan,
            "SL_p90_R": sl["R"].quantile(0.1) if len(sl) else np.nan,
            "LOCK_mean_R": lk["R"].mean(), "LOCK_mean_gross_ref_R": lk["gross_ref_R"].mean(),
            "LOCK_cost_share_of_gross": (lk["cost_paper_R"].sum() / lk["gross_ref_R"].sum()) if len(lk) else np.nan,
            "mean_fee_bps_notional": g["fee_bps"].mean(), "mean_cost_pct_equity": g["cost_eq"].mean() * 100,
            "mean_leverage": g["leverage"].mean(), "mean_hold_min": g["hold_min"].mean(),
        })

    rows = []
    for keys, g in T.groupby(["grp", "tf"]):
        rows.append({"run": "ALL", "grp": keys[0], "tf": keys[1], **agg(g)})
    for keys, g in T.groupby(["run", "grp", "tf"]):
        rows.append({"run": keys[0], "grp": keys[1], "tf": keys[2], **agg(g)})
    D = pd.DataFrame(rows)
    order = {"5m": 0, "15m": 1, "30m": 2, "1h": 3, "4h": 4}
    D["o"] = D["tf"].map(order)
    D = D.sort_values(["run", "grp", "o"]).drop(columns="o")
    D.to_csv(os.path.join(out, "c01_decomp_by_tf.csv"), index=False)

    # by coin x tf (core36 + ds200 pooled, all runs)
    S = T[T["grp"].isin(["core36", "ds200"])]
    rows = []
    for (sym, tf), g in S.groupby(["symbol", "tf"]):
        rows.append({"symbol": sym, "tf": tf, **agg(g)})
    C = pd.DataFrame(rows)
    C["o"] = C["tf"].map(order)
    C = C.sort_values(["o", "symbol"]).drop(columns="o")
    C.to_csv(os.path.join(out, "c01_decomp_by_coin_tf.csv"), index=False)

    # by stop-width bin (strategy kinds, all runs, 15m-4h + 5m)
    bins = [0, 30, 45, 60, 80, 100, 130, 170, 250, 10000]
    S = S.assign(stop_bin=pd.cut(S["stop_bps"], bins))
    rows = []
    for (tf, b), g in S.groupby(["tf", "stop_bin"], observed=True):
        rows.append({"tf": tf, "stop_bin_bps": str(b), **agg(g)})
    for b, g in S.groupby("stop_bin", observed=True):
        rows.append({"tf": "*", "stop_bin_bps": str(b), **agg(g)})
    B = pd.DataFrame(rows)
    B.to_csv(os.path.join(out, "c01_decomp_by_stopbin.csv"), index=False)

    # LOCK exits that filled beyond the lock level (the 1m bar opened through it) and the SL loss decomposition
    K = T[T["grp"].isin(["core36", "ds200"])]
    L = K[K["exit_reason"] == "LOCK"]
    LG = L.groupby("tf").agg(n=("R", "size"), gap_share=("gap_bps", lambda x: (x > 0.01).mean()),
                             gap_bps_mean=("gap_bps", "mean"), gap_bps_p90=("gap_bps", lambda x: x.quantile(0.9)),
                             gap_R=("gap_R", "mean"), lock_R=("R", "mean"), lock_gross=("gross_ref_R", "mean"),
                             lock_cost=("cost_paper_R", "mean"))
    LG.to_csv(os.path.join(out, "c01_lock_gap_by_tf.csv"))
    SLx = K[K["exit_reason"] == "SL"]
    SG = SLx.groupby("tf").agg(n=("R", "size"), R=("R", "mean"), fee=("fee_R", "mean"), exit_slip=("exit_slip_R", "mean"),
                               gap=("gap_R", "mean"), funding=("funding_R", "mean"),
                               entry_slip_inside_1R=("entry_slip_R", "mean"),
                               exact_fill_share=("gap_bps", lambda x: (x <= 0.01).mean()),
                               median_stop_pct=("stop_frac", lambda x: 100 * x.median()))
    SG.to_csv(os.path.join(out, "c01_sl_decomposition_by_tf.csv"))
    print(LG.round(4).to_string())
    print(SG.round(4).to_string())
    pd.set_option("display.width", 250)
    cols = ["run", "grp", "tf", "n", "median_stop_pct", "mean_R", "mean_gross_ref_R", "mean_cost_R", "fee_R",
            "entry_slip_R", "exit_slip_R", "funding_R", "gap_R", "SL_mean_R", "SL_fee_R", "SL_exit_slip_R", "SL_gap_R",
            "SL_gap_share", "LOCK_mean_R", "LOCK_mean_gross_ref_R", "LOCK_cost_share_of_gross", "n_LIQ",
            "mean_cost_pct_equity", "mean_leverage"]
    print(D[D["run"] == "ALL"][cols].round(4).to_string(index=False))
    print(D[(D["run"] != "ALL") & D["grp"].isin(["core36", "ds200"])][cols[:8]].round(4).to_string(index=False))
    print(C[["symbol", "tf", "n", "median_stop_pct", "mean_R", "mean_gross_ref_R", "mean_cost_R", "SL_mean_R"]]
          .round(4).to_string(index=False))
    print(B[["tf", "stop_bin_bps", "n", "mean_R", "mean_gross_ref_R", "mean_cost_R", "SL_mean_R"]].round(4)
          .to_string(index=False))


if __name__ == "__main__":
    main()
