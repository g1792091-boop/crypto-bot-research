#!/usr/bin/env python3
"""Move-event wakes per hour in a position for thresholds 0.5R / 0.75R / 1.0R, on the live replay's traded signals
(v3b + v4, kinds strategy + ds200) with 1m live bars. Event = price moved >= k*R from the price at the last event.

    python3 -P move_threshold.py <export_dir> <rb_out_real_dir> <out_csv>
"""
import os
import sys
import numpy as np
import pandas as pd

RUNS = ["run-20261005T183457Z", "current"]


def main():
    exp, rb, out = sys.argv[1:4]
    rs = pd.read_csv(os.path.join(rb, "replay_signals.csv"))
    rs = rs[rs.kind.isin(["strategy", "ds200"]) & rs.run.isin(RUNS) & (rs.status == "TRADED")
            & rs.timeframe.isin(["15m", "30m", "1h", "4h"])]
    bars = {}
    for run in RUNS:
        lb = pd.read_csv(os.path.join(exp, run, "live_bars.csv"), usecols=["ts", "symbol", "high", "low"])
        for sym, d in lb.groupby("symbol"):
            d = d.sort_values("ts").drop_duplicates("ts")
            bars[(run, sym)] = (d.ts.to_numpy(np.int64), d.high.to_numpy(float), d.low.to_numpy(float))
    rows = []
    for r in rs.itertuples():
        ts, h, l = bars[(r.run, r.symbol)]
        a, b = np.searchsorted(ts, int(r.entry_time)), np.searchsorted(ts, int(r.exit_time))
        if b <= a:
            continue
        rd = abs(r.entry_price - r.stop_initial)
        res = {"timeframe": r.timeframe, "hours": (r.exit_time - r.entry_time) / 3.6e6}
        for k in (0.5, 0.75, 1.0):
            step = k * rd
            ref = r.entry_price
            n = 0
            for hi, lo in zip(h[a:b], l[a:b]):
                if hi - ref >= step:
                    m = int((hi - ref) // step)
                    n += m
                    ref += m * step
                if ref - lo >= step:
                    m = int((ref - lo) // step)
                    n += m
                    ref -= m * step
            res[f"ev_{k}"] = n
        rows.append(res)
    d = pd.DataFrame(rows)
    g = d.groupby("timeframe").sum()
    for k in (0.5, 0.75, 1.0):
        g[f"per_hour_{k}"] = g[f"ev_{k}"] / g.hours
    g["n_trades"] = d.groupby("timeframe").size()
    g.to_csv(out)
    print(g.round(3))


if __name__ == "__main__":
    main()
