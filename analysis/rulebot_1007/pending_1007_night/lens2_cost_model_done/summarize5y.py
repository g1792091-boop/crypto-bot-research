#!/usr/bin/env python3
"""Per-strategy daily call counts from sim5y outputs -> calls_5y_per_strategy.csv and daily arrays (npz).

    python3 -P summarize5y.py <sim5y_out_dir> <out_dir>

Call bundles per trader-day:
  entry-type calls  = entry (+ switch in switch mode)
  holding checks    = P1 (bar close of held tf) / P2 (every 30 min) / P3 (events: 0.5R moves x calibration
                      + other-tf same-coin signals + macro releases) / P4 = P2 + P3 (the PLAN_ATTACH draft)
MOVE_CAL: 1m-resolution / tf-bar-resolution move-event ratio measured on the live replay (live_move_calib.csv).
MACRO: 2 calls (30 min before, right after) per release x 4 releases per 30 days (data/macro_events.csv, Oct-Dec 2026:
11 releases over ~86 days = 3.8 / 30 days) x share of the day in a position.
Days: 2021-08-01 .. 2026-09-29 KST days (first and last partial days dropped).
"""
import os
import sys
import json
import numpy as np
import pandas as pd

MOVE_CAL = float(os.environ.get("MOVE_CAL", "0.86"))
MACRO_PER_DAY = 2 * 3.8 / 30


def main():
    src, out = sys.argv[1:3]
    rows = []
    daily = {}
    for fn in sorted(os.listdir(src)):
        if not fn.startswith("sim5y_"):
            continue
        strat = fn[6:-5]
        d = json.load(open(os.path.join(src, fn)))
        for key, v in d.items():
            setup, pe = key.split("|")
            c = {k: np.array(x, dtype=float)[1:-2] for k, x in v["cnt"].items()}
            occ = np.array(v["pos_min"], dtype=float)[1:-2] / 1440.0
            macro = MACRO_PER_DAY * occ
            mv = MOVE_CAL * c["ev_move"]
            for mode in ("switch", "ignore"):
                ent = c["entry"] + (c["switch"] if mode == "switch" else 0)
                p1 = c["p1_bar"] if mode == "switch" else c["p1_bar_ign"]
                p2 = c["p2_30m"] if mode == "switch" else c["p2_30m_ign"]
                p3 = mv + macro + (c["ev_otf_sw"] if mode == "switch" else c["ev_otf_ign"])
                hold = {"P1": p1, "P2": p2, "P3": p3, "P4": p2 + p3}
                for pol, h in hold.items():
                    daily[(strat, setup, pe, mode, pol)] = np.vstack([ent, h])
                    n = len(ent)
                    last = slice(n - 365, n)
                    rows.append({"strategy": strat, "setup": setup, "pe": float(pe), "mode": mode, "policy": pol,
                                 "entry_calls_mean": ent.mean(), "hold_calls_mean": h.mean(),
                                 "total_mean": (ent + h).mean(), "total_median": np.median(ent + h),
                                 "total_p90": np.percentile(ent + h, 90),
                                 "total_mean_last365": (ent + h)[last].mean(),
                                 "total_p90_last365": np.percentile((ent + h)[last], 90),
                                 "trades_per_day": c["trades"].mean(), "occupancy": occ.mean(),
                                 "signals_bundles_per_day": (c["entry"] + c["switch"]).mean(),
                                 "hold_med_min": v["hold_med_min"], "hold_mean_min": v["hold_mean_min"],
                                 "days": n})
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out, "calls_5y_per_strategy.csv"), index=False)
    np.savez_compressed(os.path.join(out, "calls_5y_daily.npz"),
                        **{"|".join(map(str, k)): v for k, v in daily.items()})
    print(len(df), "rows")


if __name__ == "__main__":
    main()
