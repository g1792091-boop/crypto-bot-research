#!/usr/bin/env python3
"""Strategy x timeframe decision rates: live (v3b, v4 SUBMITTED, 6 tradable coins) vs 5-year, plus trader-level
calls/day per strategy (setup A and B, pe 1) from the 5-year simulation and the live replay simulation.

    python3 -P rates_table.py <signals_dir> <rb_out_real_dir> <work_dir>
Writes <work_dir>/rates_strategy_tf.csv, trader_calls_per_strategy.csv, live_vs_5y.csv.
"""
import os
import sys
import numpy as np
import pandas as pd

COINS = ["BTC", "ETH", "SOL", "BCH", "LTC", "DOGE"]
TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
START = np.datetime64("2021-08-01T00:00", "ns").astype(np.int64)
END = np.datetime64("2026-09-30T00:00", "ns").astype(np.int64)
DAYS = (END - START) / 86400e9
MOVE_CAL = 0.86
MACRO_PER_DAY = 2 * 3.8 / 30


def main():
    sig, rb, work = sys.argv[1:4]
    # 5-year bundles (unique close moments across the 6 coins) per strategy x tf
    rows = []
    for tf, m in TF_MIN.items():
        zs = {c: np.load(os.path.join(sig, f"sig_{tf}_{c}USD.npz")) for c in COINS}
        strats = [k[3:] for k in zs["BTC"].files if k.startswith("s__")]
        for s in strats:
            ts_all, n = [], 0
            for c, z in zs.items():
                a = z["s__" + s]
                t = z["ts"][a != 0] + m * 60 * 10**9
                t = t[(t >= START) & (t < END)]
                n += len(t)
                ts_all.append(t)
            u = np.unique(np.concatenate(ts_all)) if ts_all else []
            rows.append({"strategy": s, "timeframe": tf, "y5_signals_per_day": n / DAYS, "y5_bundles_per_day": len(u) / DAYS})
    y5 = pd.DataFrame(rows)
    ref = pd.read_csv(os.path.join(rb, "fiveyear_ref.csv"))
    ds = ref[(ref.source == "deepseek200") & (ref.variant == "X5_TRAIL2")][["strategy", "timeframe", "per_day"]]
    ds = ds.rename(columns={"per_day": "y5_ds_trades_per_day_own_exits"})
    lr = pd.read_csv(os.path.join(work, "outlive", "live_rates.csv"))
    piv = lr.pivot_table(index=["strategy", "timeframe"], columns="run", values=["per_day", "bundles_per_day"])
    piv.columns = [f"live_{b}_{a}" for a, b in piv.columns]
    piv = piv.reset_index()
    pooled = lr.groupby(["strategy", "timeframe"]).agg(sub=("submitted", "sum"), bun=("bundles", "sum")).reset_index()
    days_by = lr.groupby(["strategy", "timeframe"]).days.sum().reset_index()
    pooled = pooled.merge(days_by, on=["strategy", "timeframe"])
    # pooled over the runs in which the strategy x tf existed with >= 1 signal (lower bound of exposure days)
    tab = piv.merge(y5, on=["strategy", "timeframe"], how="outer").merge(ds, on=["strategy", "timeframe"], how="left")
    tab["kind"] = np.where(tab.strategy.str.match(r"^F\d"), "ds200", "strategy")
    tab = tab[~tab.strategy.str.startswith("RANDOM") & (tab.strategy != "REEL_H1")]
    tab.to_csv(os.path.join(work, "rates_strategy_tf.csv"), index=False)

    # trader-level calls/day per strategy -----------------------------------------------------------
    per = pd.read_csv(os.path.join(work, "calls_5y_per_strategy.csv"))
    p5 = per[(per.pe == 1.0)].pivot_table(index=["strategy", "setup"], columns=["mode", "policy"],
                                           values=["total_mean", "total_p90"])
    p5.columns = [f"y5_{a}_{b}_{c}" for a, b, c in p5.columns]
    p5 = p5.reset_index()
    lc = pd.read_csv(os.path.join(work, "outlive", "live_calls.csv"))
    lc = lc[lc.pe == 1.0].copy()
    macro = MACRO_PER_DAY * lc.pos_min_pd / 1440
    lc["live_switch_P2"] = lc.entry_pd + lc.switch_pd + lc.p2_30m_pd
    lc["live_switch_P4"] = lc.entry_pd + lc.switch_pd + lc.p2_30m_pd + lc.ev_move_pd + lc.ev_otf_sw_pd + macro
    lc["live_ignore_P2"] = lc.entry_pd + lc.p2_30m_ign_pd
    lc["live_ignore_P4"] = lc.entry_pd + lc.p2_30m_ign_pd + lc.ev_move_pd + lc.ev_otf_ign_pd + macro
    lc["live_switch_P1"] = lc.entry_pd + lc.switch_pd + lc.p1_bar_pd
    lc["live_switch_P3"] = lc.entry_pd + lc.switch_pd + lc.ev_move_pd + lc.ev_otf_sw_pd + macro
    lc["live_ignore_P1"] = lc.entry_pd + lc.p1_bar_ign_pd
    lc["live_ignore_P3"] = lc.entry_pd + lc.ev_move_pd + lc.ev_otf_ign_pd + macro
    keep = ["run", "kind", "strategy", "setup", "days", "entry_pd", "switch_pd", "trades_pd", "pos_min_pd"] + \
           [c for c in lc.columns if c.startswith("live_")]
    lc[keep].to_csv(os.path.join(work, "trader_calls_live.csv"), index=False)
    lw = lc.pivot_table(index=["strategy", "setup"], columns="run",
                        values=["live_switch_P4", "live_ignore_P4", "live_switch_P2", "live_ignore_P2", "entry_pd", "switch_pd"])
    lw.columns = [f"{a}_{b}" for a, b in lw.columns]
    lw = lw.reset_index()
    tc = lw.merge(p5, on=["strategy", "setup"], how="outer")
    tc.to_csv(os.path.join(work, "trader_calls_per_strategy.csv"), index=False)

    # medians by kind/setup: live vs 5y
    med = []
    for (run, kind, setup), d in lc.groupby(["run", "kind", "setup"]):
        r = {"source": f"live_{run}", "kind": kind, "setup": setup, "n_strategies": len(d)}
        for c in ["live_switch_P1", "live_switch_P2", "live_switch_P3", "live_switch_P4", "live_ignore_P1",
                  "live_ignore_P2", "live_ignore_P3", "live_ignore_P4", "entry_pd", "switch_pd", "trades_pd"]:
            r[c.replace("live_", "")] = d[c].median()
        r["occupancy"] = (d.pos_min_pd / 1440).median()
        med.append(r)
    ours = set(lc[lc.kind == "strategy"].strategy)
    for setup in "ABC":
        d = per[(per.pe == 1.0) & (per.setup == setup)]
        r = {"source": "5y_sim", "kind": "strategy", "setup": setup, "n_strategies": d.strategy.nunique()}
        for mode in ("switch", "ignore"):
            for pol in ("P1", "P2", "P3", "P4"):
                r[f"{mode}_{pol}"] = d[(d["mode"] == mode) & (d.policy == pol)].total_mean.median()
        x = d[(d["mode"] == "ignore") & (d.policy == "P2")]
        r["entry_pd"] = x.entry_calls_mean.median()
        r["switch_pd"] = (x.signals_bundles_per_day - x.entry_calls_mean).median()
        r["trades_pd"] = x.trades_per_day.median()
        r["occupancy"] = x.occupancy.median()
        med.append(r)
        d2 = d[d.strategy.isin(ours)]
        r2 = dict(r, source="5y_sim_live_overlap", n_strategies=d2.strategy.nunique())
        for mode in ("switch", "ignore"):
            for pol in ("P1", "P2", "P3", "P4"):
                r2[f"{mode}_{pol}"] = d2[(d2["mode"] == mode) & (d2.policy == pol)].total_mean.median()
        med.append(r2)
    pd.DataFrame(med).to_csv(os.path.join(work, "live_vs_5y.csv"), index=False)
    print(pd.DataFrame(med).round(2).to_string())


if __name__ == "__main__":
    main()
