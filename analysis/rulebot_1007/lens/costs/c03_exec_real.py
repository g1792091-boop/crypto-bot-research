#!/usr/bin/env python3
"""Real execution cost per coin vs the paper model.

    python3 -I c03_exec_real.py <export_dir> <ticks.csv> <out_dir>

Entry: paper fills at ref * (1 + 2 bp), ref = ask (long) / bid (short) when the signal was ready, so the spread is
already in paper; the real extra cost of a market order is the order-book walk beyond the best level at the paper
size (fill_costs.slip_best, recorded a few seconds after the minute, notional = the paper order, ~$45k in v4).
Exit: d3_stop_slips (v4 nights only): real_bps = where a real STOP_MARKET of the trade's size would have filled
(aggTrades after the trigger, or the recorded book), adverse bps vs the stop price; paper_bps = what paper charged
(2 bp, more on a gapped open). Rows with status 'cap' have no real estimate (nightly fetch cap) and are excluded.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RUNS = ["run-20261005T014624Z", "run-20261005T183457Z", "current"]


def main():
    root, ticks_csv, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    F = []
    for r in RUNS:
        f = pd.read_csv(os.path.join(root, r, "fill_costs.csv"))
        f["run"] = r
        F.append(f)
    F = pd.concat(F, ignore_index=True)
    F = F[F["status"] == "ok"].copy()
    F["bps"] = F["slip_best"] * 1e4
    rows = []
    for (sym, ev), g in F.groupby(["symbol", "event"]):
        rows.append({"symbol": sym, "event": ev, "n": len(g), "notional_median": g["notional"].median(),
                     "bps_mean": g["bps"].mean(), "bps_median": g["bps"].median(), "bps_p90": g["bps"].quantile(0.9),
                     "bps_max": g["bps"].max(), "share_gt_2bp": (g["bps"] > 2).mean()})
    for (r, sym, ev), g in F.groupby(["run", "symbol", "event"]):
        rows.append({"run": r, "symbol": sym, "event": ev, "n": len(g), "notional_median": g["notional"].median(),
                     "bps_mean": g["bps"].mean(), "bps_median": g["bps"].median(), "bps_p90": g["bps"].quantile(0.9),
                     "bps_max": g["bps"].max(), "share_gt_2bp": (g["bps"] > 2).mean()})
    FC = pd.DataFrame(rows)
    FC.to_csv(os.path.join(out, "c03_fill_costs_by_coin.csv"), index=False)

    # bps per $10k of notional (depth slope), to rescale to other sizes: slip_best / notional
    F["bps_per_10k"] = F["bps"] / (F["notional"] / 1e4)
    slope = F[F["event"] == "entry"].groupby("symbol")["bps_per_10k"].median()

    S = pd.read_csv(os.path.join(root, "current", "d3_stop_slips.csv"))
    S["tf"] = S["timeframe"]
    ok = S[S["status"] == "ok"].copy()
    ok["excess_bps"] = ok["real_bps"] - ok["paper_bps"]
    rows = []
    for keys, g in list(ok.groupby(["symbol"])) + [(("*",), ok)]:
        sym = keys[0] if isinstance(keys, tuple) else keys
        rows.append({"symbol": sym, "tf": "*", "exit_reason": "*", "n_ok": len(g),
                     "n_all": int((S["symbol"] == sym).sum()) if sym != "*" else len(S),
                     "paper_bps_mean": g["paper_bps"].mean(), "real_bps_mean": g["real_bps"].mean(),
                     "real_bps_median": g["real_bps"].median(), "real_bps_p90": g["real_bps"].quantile(0.9),
                     "real_bps_max": g["real_bps"].max(), "share_real_gt_2bp": (g["real_bps"] > 2).mean(),
                     "share_real_gt_paper": (g["real_bps"] > g["paper_bps"]).mean(),
                     "diff_usd_sum": g["diff_usd"].sum()})
    for (sym, er), g in ok.groupby(["symbol", "exit_reason"]):
        rows.append({"symbol": sym, "tf": "*", "exit_reason": er, "n_ok": len(g),
                     "paper_bps_mean": g["paper_bps"].mean(), "real_bps_mean": g["real_bps"].mean(),
                     "real_bps_median": g["real_bps"].median(), "real_bps_p90": g["real_bps"].quantile(0.9),
                     "real_bps_max": g["real_bps"].max(), "share_real_gt_2bp": (g["real_bps"] > 2).mean(),
                     "share_real_gt_paper": (g["real_bps"] > g["paper_bps"]).mean(), "diff_usd_sum": g["diff_usd"].sum()})
    for (tf, er), g in ok.groupby(["tf", "exit_reason"]):
        rows.append({"symbol": "*", "tf": tf, "exit_reason": er, "n_ok": len(g),
                     "paper_bps_mean": g["paper_bps"].mean(), "real_bps_mean": g["real_bps"].mean(),
                     "real_bps_median": g["real_bps"].median(), "real_bps_p90": g["real_bps"].quantile(0.9),
                     "real_bps_max": g["real_bps"].max(), "share_real_gt_2bp": (g["real_bps"] > 2).mean(),
                     "share_real_gt_paper": (g["real_bps"] > g["paper_bps"]).mean(), "diff_usd_sum": g["diff_usd"].sum()})
    SS = pd.DataFrame(rows)
    SS.to_csv(os.path.join(out, "c03_stop_slips_by_coin.csv"), index=False)

    # was the 'cap' subset different? (it is the coin-minutes with the most exit notional first -> ok = largest)
    capmix = S.groupby(["symbol", "status"]).size().unstack(fill_value=0)

    tk = pd.read_csv(ticks_csv).set_index("symbol")
    ent = FC[FC["run"].isna() & (FC["event"] == "entry")].set_index("symbol")
    # exit slippage parameter: SL exits only (paper charged exactly 2 bp there, no gap), so real_bps is the pure
    # slippage beyond the trigger; LOCK rows include the 1m-open gaps that the engine already charges itself
    ext = SS[(SS["tf"] == "*") & (SS["exit_reason"] == "SL") & (SS["symbol"] != "*")].set_index("symbol")
    ext_all = SS[(SS["tf"] == "*") & (SS["exit_reason"] == "*") & (SS["symbol"] != "*")].set_index("symbol")
    rows = []
    for sym in sorted(ent.index):
        e_slip = float(ent.loc[sym, "bps_mean"])
        x_slip = float(ext.loc[sym, "real_bps_mean"]) if sym in ext.index else 2.0
        rows.append({"symbol": sym, "tick_bps": float(tk.loc[sym, "tick_bps"]),
                     "entry_slip_bps": e_slip, "exit_slip_bps": x_slip,
                     "entry_depth_bps_per_10k_median": float(slope.get(sym, np.nan)),
                     "rt_taker_paper_bps": 2 * (5 + 2),
                     "rt_taker_real_bps": 5 + e_slip + 5 + x_slip,
                     # maker entry joining the other side of the spread: saves the spread (one tick) + depth walk,
                     # pays 2 bp; exit stays a stop-market (taker + real slip)
                     "rt_maker_entry_real_bps": 2 + 5 + x_slip - float(tk.loc[sym, "tick_bps"]),
                     "rt_maker_both_bps": 2 + 2,
                     "stop_slip_n_ok_SL": int(ext.loc[sym, "n_ok"]) if sym in ext.index else 0,
                     "stop_slip_all_real_minus_paper_bps": float(ext_all.loc[sym, "real_bps_mean"] - ext_all.loc[sym, "paper_bps_mean"])
                     if sym in ext_all.index else np.nan})
    EC = pd.DataFrame(rows)
    EC.to_csv(os.path.join(out, "c03_exec_coin.csv"), index=False)
    pd.set_option("display.width", 250)
    print(FC[FC["run"].isna()].round(3).to_string(index=False))
    print(SS.round(3).to_string(index=False))
    print(capmix)
    print(EC.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
