#!/usr/bin/env python3
"""Macro events (repo data/macro_events.csv) and big market-move hours vs trades / every-signal replay.

    python3 -I events.py <export_dir> <repo> <trades_enriched.csv> <out_dir>

Big-move hour: top decile of |equal-weight 6-coin 1h return| within the run (live_bars 1m, v3b / v4); v3a has no
live_bars, so its hourly prices are approximated by the signal reference prices (first/last ref of each hour).
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True
import site  # noqa: E402
sys.path.append(site.getusersitepackages())
import os  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

MIN, HOUR = 60_000, 3_600_000
RUNS = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
TAKER, SLIP = 0.0005, 0.0002
KST = 9 * HOUR


def cl_stats(d, cl, rng, B=5000):
    d = np.asarray(d, float)
    u, inv = np.unique(cl, return_inverse=True)
    sums = np.bincount(inv, weights=d)
    cnt = np.bincount(inv)
    k = len(u)
    if k < 3:
        return {"clusters": k}
    idx = rng.integers(0, k, size=(B, k))
    bs = sums[idx].sum(1) / cnt[idx].sum(1)
    return {"clusters": k, "ci_lo": np.percentile(bs, 2.5), "ci_hi": np.percentile(bs, 97.5)}


def hourly_ew(exp, run):
    p = os.path.join(exp, run)
    lb = os.path.join(p, "live_bars.csv")
    if os.path.exists(lb):
        b = pd.read_csv(lb, usecols=["ts", "symbol", "open", "close"])
        b["h"] = b["ts"] // HOUR * HOUR
        g = b.sort_values("ts").groupby(["h", "symbol"]).agg(o=("open", "first"), c=("close", "last"), n=("ts", "size"))
        g = g[g["n"] >= 50]
        src = "live_bars"
    else:
        s = pd.read_csv(os.path.join(p, "signal_log.csv"))
        s = s[s["ref_price"].notna() & s["ref_time"].notna()]
        s["h"] = s["ref_time"] // HOUR * HOUR
        g = s.sort_values("ref_time").groupby(["h", "symbol"]).agg(o=("ref_price", "first"), c=("ref_price", "last"),
                                                                    n=("ref_price", "size"))
        g = g[g["n"] >= 3]
        src = "signal ref prices (approx)"
    g["ret"] = g["c"] / g["o"] - 1
    ew = g.reset_index().groupby("h").agg(ew_ret=("ret", "mean"), coins=("ret", "size"))
    ew = ew[ew["coins"] >= 4]
    return ew, g.reset_index(), src


def main():
    exp, repo, tpath, out = sys.argv[1:5]
    rng = np.random.default_rng(3)
    ev = pd.read_csv(os.path.join(repo, "data", "macro_events.csv"), comment="#")
    ev["ts"] = pd.to_datetime(ev["ts_utc"], utc=True).astype("int64") // 10**6
    T = pd.read_csv(tpath)
    T = T[T["kind"].isin(["strategy", "ds200"]) & (T["exits"] == "house")].copy()
    T["run_s"] = T["run"].map(RUNS)
    RS = pd.read_csv(os.path.join(out, "rules_signals.csv"))
    RS = RS[RS["base_status"].isin(["TRADED", "UNRESOLVED"]) & RS["kind"].isin(["strategy", "ds200"])].copy()
    RS["run_s"] = RS["run"].map(RUNS)
    rows, hrs = [], []
    # ---- macro events inside the runs
    for run, rs in RUNS.items():
        tr = T[T["run"] == run]
        lo = min(tr["entry_time"].min(), RS[RS["run"] == run]["bar_close"].min() if (RS["run"] == run).any() else np.inf)
        hi = tr["exit_time"].max()
        for e in ev.itertuples(index=False):
            if lo - 2 * HOUR <= e.ts <= hi:
                win = (tr["entry_time"] >= e.ts - 2 * HOUR) & (tr["entry_time"] < e.ts + 2 * HOUR)
                held = (tr["entry_time"] < e.ts) & (tr["exit_time"] > e.ts)
                for name, m in (("entered_within_2h", win), ("held_through_release", held), ("other_trades", ~win & ~held)):
                    g = tr[m]
                    rows.append({"run": rs, "event": e.kind, "event_kst": pd.Timestamp(e.ts + KST, unit="ms").strftime("%m/%d %H:%M"),
                                 "group": name, "n": len(g), "mean_R": g["R"].mean(), "win_pct": 100 * (g["R"] > 0).mean(),
                                 "share_SL": (g["exit_reason"] == "SL").mean(), "mean_mfe_R": g["mfe_R"].mean(),
                                 "mean_mae_R": g["mae_R"].mean()})
    EV = pd.DataFrame(rows)
    EV.to_csv(os.path.join(out, "events_macro.csv"), index=False)
    # ---- big-move hours
    brow, hold_rows = [], []
    for run, rs in RUNS.items():
        ew, per, src = hourly_ew(exp, run)
        thr = ew["ew_ret"].abs().quantile(0.9)
        big = set(ew.index[ew["ew_ret"].abs() >= thr])
        ew_s = ew.copy()
        ew_s["big"] = ew_s.index.isin(big)
        ew_s["kst"] = [pd.Timestamp(h + KST, unit="ms").strftime("%m/%d %H:00") for h in ew_s.index]
        ew_s["run"] = rs
        ew_s["src"] = src
        hrs.append(ew_s[ew_s["big"]].reset_index())
        dirn = ew["ew_ret"].to_dict()
        # trades: entry hour big vs not; held through a big hour aligned vs against
        tr = T[T["run"] == run].copy()
        tr["eh"] = tr["entry_time"] // HOUR * HOUR
        tr["entry_in_big"] = tr["eh"].isin(big)
        tr["entry_after_big"] = (tr["eh"] - HOUR).isin(big)
        tr["cl"] = rs + "|" + tr["eh"].astype(str)
        for kind in ("strategy", "ds200"):
            for tf in ("15m", "30m", "1h", "ALL"):
                g0 = tr[(tr["kind"] == kind) & ((tr["tf"] == tf) if tf != "ALL" else True)]
                if not len(g0):
                    continue
                for name, m in (("entry_in_big_hour", g0["entry_in_big"]), ("entry_hour_after_big", g0["entry_after_big"]),
                                ("entry_other", ~g0["entry_in_big"] & ~g0["entry_after_big"])):
                    g = g0[m]
                    if not len(g):
                        continue
                    brow.append({"src": "trades", "run": rs, "kind": kind, "tf": tf, "group": name, "n": len(g),
                                 "mean_R": g["R"].mean(), "sd_R": g["R"].std(), "share_SL": (g["exit_reason"] == "SL").mean(),
                                 "mean_mfe_R": g["mfe_R"].mean(), **cl_stats(g["R"], g["cl"], rng)})
        # every-signal replay (v3b / v4)
        if (RS["run"] == run).any():
            sg = RS[RS["run"] == run].copy()
            sg["eh"] = sg["bar_close"] // HOUR * HOUR
            sg["cl"] = rs + "|" + sg["eh"].astype(str)
            for kind in ("strategy", "ds200"):
                for tf in ("15m", "30m", "1h", "ALL"):
                    g0 = sg[(sg["kind"] == kind) & ((sg["timeframe"] == tf) if tf != "ALL" else True)]
                    if not len(g0):
                        continue
                    for name, m in (("entry_in_big_hour", g0["eh"].isin(big)), ("entry_hour_after_big", (g0["eh"] - HOUR).isin(big)),
                                    ("entry_other", ~g0["eh"].isin(big) & ~(g0["eh"] - HOUR).isin(big))):
                        g = g0[m]
                        if not len(g):
                            continue
                        brow.append({"src": "signals", "run": rs, "kind": kind, "tf": tf, "group": name, "n": len(g),
                                     "mean_R": g["base_R"].mean(), "sd_R": g["base_R"].std(),
                                     "share_SL": (g["base_exit_reason"] == "SL").mean(), "mean_mfe_R": g["base_mfe_R"].mean(),
                                     **cl_stats(g["base_R"], g["cl"], rng)})
            # positions open at the END of a big hour: hold vs exit at that hour's close, aligned vs against the move
            b = pd.read_csv(os.path.join(exp, run, "live_bars.csv"), usecols=["ts", "symbol", "close"])
            cpx = {(int(a), s): c for a, s, c in zip(b["ts"], b["symbol"], b["close"])}
            for r in sg.itertuples(index=False):
                et, xt = r.base_entry_time, r.base_exit_time
                if not (et == et and xt == xt):
                    continue
                for h in big:
                    hend = h + HOUR
                    if et < hend - 15 * MIN and xt > hend:      # in position at least the last 15 min of the big hour
                        c = cpx.get((int(hend - MIN), r.symbol))
                        if c is None:
                            continue
                        dist = abs(r.base_entry_price - r.base_stop_initial)
                        side = int(r.side)
                        now = side * (c - r.base_entry_price) / dist - (2 * TAKER + SLIP) * r.base_entry_price / dist
                        aligned = np.sign(dirn[h]) == side
                        hold_rows.append({"run": rs, "kind": r.kind, "tf": r.timeframe, "hour": h,
                                          "aligned_with_move": bool(aligned), "exit_now_R": now, "hold_R": r.base_R,
                                          "hold_minus_exit": r.base_R - now, "cl": f"{rs}|{h}"})
    BH = pd.DataFrame(brow)
    BH.to_csv(os.path.join(out, "events_bighours.csv"), index=False)
    pd.concat(hrs, ignore_index=True).to_csv(os.path.join(out, "events_bighours_list.csv"), index=False)
    HR = pd.DataFrame(hold_rows)
    hs = []
    for (rs, kind, tf, al), g in HR.groupby(["run", "kind", "tf", "aligned_with_move"]):
        hs.append({"run": rs, "kind": kind, "tf": tf, "aligned_with_move": al, "n": len(g),
                   "mean_exit_now_R": g["exit_now_R"].mean(), "mean_hold_R": g["hold_R"].mean(),
                   "hold_minus_exit": g["hold_minus_exit"].mean(), **cl_stats(g["hold_minus_exit"], g["cl"], rng)})
    for (kind, tf, al), g in HR.groupby(["kind", "tf", "aligned_with_move"]):
        hs.append({"run": "ALL", "kind": kind, "tf": tf, "aligned_with_move": al, "n": len(g),
                   "mean_exit_now_R": g["exit_now_R"].mean(), "mean_hold_R": g["hold_R"].mean(),
                   "hold_minus_exit": g["hold_minus_exit"].mean(), **cl_stats(g["hold_minus_exit"], g["cl"], rng)})
    HS = pd.DataFrame(hs)
    HS.to_csv(os.path.join(out, "events_bighour_hold_vs_exit.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(EV.round(3).to_string())
    print(pd.concat(hrs)[["run", "kst", "ew_ret", "coins", "src"]].round(4).to_string())
    print(BH[BH["tf"].isin(["15m", "30m", "ALL"])].round(3).to_string())
    print(HS.round(3).to_string())


if __name__ == "__main__":
    main()
