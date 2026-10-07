#!/usr/bin/env python3
"""AI edge needed per trade just to break even, by coin x timeframe, at live and at five-year-median volatility.

    python3 -I c10_needed_edge.py <c06_live_vs_5y_stop.csv> <c03_exec_coin.csv> <c07_5y_regime.csv> <out_dir>

needed R = round-trip cost (bps) / stop (bps) - five-year gross R of the 36 strategies' signals for that coin x tf
(about 0: the strategies give the AI nothing to start from).  Menus: paper 14 bp; real taker (5+5 bp fees + measured
entry book walk + measured stop slip); maker entry + taker stop (2 + 5 bp + stop slip - one tick of spread).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa: E402,F401
import pandas as pd  # noqa: E402


def main():
    lv, ec, y5, out = sys.argv[1:5]
    L = pd.read_csv(lv)
    E = pd.read_csv(ec)
    E["coin"] = E["symbol"].str.replace("USDT", "USD")
    E = E.set_index("coin")
    Y = pd.read_csv(y5)
    Yc = Y[Y["split"] == "coin"].set_index(["tf", "key"])
    rows = []
    for r in L.itertuples():
        if r.coin == "ALL" or r.tf not in ("15m", "30m", "1h"):
            continue
        e = E.loc[r.coin]
        g5 = Yc.loc[(r.tf, r.coin), "gross_R"] if (r.tf, r.coin) in Yc.index else float("nan")
        for menu, bps in (("paper_taker", 14.0), ("real_taker", e["rt_taker_real_bps"]),
                          ("maker_entry_taker_stop", e["rt_maker_entry_real_bps"])):
            rows.append({"tf": r.tf, "coin": r.coin, "menu": menu, "round_trip_bps": bps,
                         "live_stop_pct": r.live_median_stop_pct, "y5_median_stop_pct": r.fiveyear_median_stop_pct,
                         "y5_gross_R_signals": g5,
                         "needed_R_live_vol": bps / (r.live_median_stop_pct * 100) - max(g5, 0),
                         "needed_R_5y_median_vol": bps / (r.fiveyear_median_stop_pct * 100) - max(g5, 0)})
    D = pd.DataFrame(rows)
    D.to_csv(os.path.join(out, "c10_needed_edge.csv"), index=False)
    P = D.pivot_table(index=["tf", "coin"], columns="menu", values=["needed_R_live_vol", "needed_R_5y_median_vol"])
    pd.set_option("display.width", 250)
    print(P.round(3).to_string())
    print(D.groupby(["tf", "menu"])[["needed_R_live_vol", "needed_R_5y_median_vol"]].agg(["min", "max"]).round(3))


if __name__ == "__main__":
    main()
