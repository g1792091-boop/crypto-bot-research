#!/usr/bin/env python3
"""Live (v3b + v4) AI-call rates for one-position AI traders, from the validated replay (no API calls).

    python3 -P live_sim.py <export_dir> <rb_out_real_dir> <out_dir>

Inputs (read only): <rb_out_real_dir>/replay_signals.csv (every SUBMITTED signal of v3b and v4 run alone through the
repo's engine on live 1m bars: entry/exit times, initial stop), <rb_out_real_dir>/runs_meta.csv (run days),
<export_dir>/<run>/signal_log.csv (raw SUBMITTED counts) and live_bars.csv (1m bars, for >= 0.5 R move events).

Same call definitions as sim5y.py (bundles per bar-close moment; switch vs ignore; p1 per bar close of the held
timeframe; p2 every 30 minutes; ev_move >= 0.5 R from the last event price on 1m high/low; ev_otf other-timeframe
same-coin signals). Rule exits from the replay are used as the hold (AI early exits would shorten it).
Also: ev_move on the trade's own timeframe bars (built from the same 1m bars) to calibrate the 5-year proxy.
pe (AI enter probability) 0.5 is averaged over 40 seeds.
"""
from __future__ import annotations

import os
import sys
import json
import numpy as np
import pandas as pd

TF_MIN = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
TFS = ["15m", "30m", "1h", "4h"]
SETUPS = {"A": ("15m", "30m"), "B": ("15m", "30m", "1h", "4h"), "C": ("15m", "30m", "1h", "4h")}
RUNS = {"run-20261005T183457Z": "v3b", "current": "v4"}
MIN30 = 30 * 60 * 1000


def main():
    exp, rb, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    rs = pd.read_csv(os.path.join(rb, "replay_signals.csv"))
    rs = rs[rs.kind.isin(["strategy", "ds200"]) & rs.timeframe.isin(TFS) & rs.run.isin(RUNS)].copy()
    meta = pd.read_csv(os.path.join(rb, "runs_meta.csv")).set_index("run")
    days = {r: float(meta.loc[r, "days"]) for r in RUNS}

    # raw SUBMITTED rates per strategy x tf (signal_log) -------------------------------------------
    rate_rows = []
    for run, tag in RUNS.items():
        sl = pd.read_csv(os.path.join(exp, run, "signal_log.csv"))
        sl = sl[(sl.status == "SUBMITTED") & sl.timeframe.isin(TFS)]
        g = sl.groupby(["strategy", "timeframe"])
        for (s, tf), d in g:
            rate_rows.append({"run": tag, "strategy": s, "timeframe": tf, "submitted": len(d),
                              "bundles": d.bar_close.nunique(), "days": days[run],
                              "per_day": len(d) / days[run], "bundles_per_day": d.bar_close.nunique() / days[run]})
    pd.DataFrame(rate_rows).to_csv(os.path.join(out, "live_rates.csv"), index=False)

    # 1m bars per run x symbol ---------------------------------------------------------------------
    bars = {}
    for run in RUNS:
        lb = pd.read_csv(os.path.join(exp, run, "live_bars.csv"), usecols=["ts", "symbol", "high", "low"])
        for sym, d in lb.groupby("symbol"):
            d = d.sort_values("ts").drop_duplicates("ts")
            bars[(run, sym)] = (d.ts.to_numpy(np.int64), d.high.to_numpy(float), d.low.to_numpy(float))
    end_ms = {run: max(v[0][-1] for k, v in bars.items() if k[0] == run) + 60000 for run in RUNS}

    def moves(run, sym, t0, t1, e, rdist, tfmin=None):
        ts, h, l = bars[(run, sym)]
        a, b = np.searchsorted(ts, t0, "left"), np.searchsorted(ts, t1, "left")
        if b <= a:
            return []
        ts, h, l = ts[a:b], h[a:b], l[a:b]
        if tfmin:  # aggregate to the trade's own timeframe bars (calibration of the 5-year proxy)
            k = (ts // (tfmin * 60000))
            _, idx = np.unique(k, return_index=True)
            hh = np.maximum.reduceat(h, idx)
            ll = np.minimum.reduceat(l, idx)
            ts = ts[idx]
            h, l = hh, ll
        step = 0.5 * rdist
        ref = e
        out_t = []
        for t, hi, lo in zip(ts, h, l):
            up = hi - ref
            if up >= step:
                k = int(up // step)
                out_t += [int(t)] * k
                ref += k * step
            dn = ref - lo
            if dn >= step:
                k = int(dn // step)
                out_t += [int(t)] * k
                ref -= k * step
        return out_t

    rs["stopf"] = 2 * rs.atr / rs.ref_price
    rs["tf_i"] = rs.timeframe.map(TFS.index)
    rs["tclose"] = rs.bar_close.astype(np.int64)
    res_rows = []
    calib = []
    trade_cache = {}
    for (run, kind, strat), d in rs.groupby(["run", "kind", "strategy"]):
        d = d.sort_values(["tclose", "tf_i"])
        D = days[run]
        by_ct = {(sym, ti): np.unique(x.tclose.to_numpy()) for (sym, ti), x in d.groupby(["symbol", "tf_i"])}
        for setup, tfs in SETUPS.items():
            el = d[d.timeframe.isin(tfs)]
            if setup == "C":
                el = el[~((el.timeframe == "4h") & (el.stopf > 0.032))]
            if el.empty:
                continue
            bundles = [(t, g) for t, g in el.groupby("tclose")]
            tset = {TFS.index(x) for x in tfs}
            for pe in (1.0, 0.5):
                seeds = 1 if pe == 1.0 else 40
                acc = None
                for sd in range(seeds):
                    rng = np.random.default_rng(1000 + sd)
                    c = dict.fromkeys(["entry", "switch", "p1_bar", "p1_bar_ign", "p2_30m", "p2_30m_ign",
                                       "ev_move", "ev_move_tfbars", "ev_otf_ign", "ev_otf_sw", "trades", "pos_min"], 0.0)
                    t_out = -1
                    cur = None
                    sw = []

                    def close(cur, sw):
                        tb, to = cur["tb"], cur["t_out"]
                        tfm = TF_MIN[cur["tf"]] * 60000
                        p1 = np.arange(tb + tfm, to, tfm)
                        c["p1_bar_ign"] += len(p1)
                        c["p1_bar"] += len(set(p1.tolist()) - set(sw))
                        p2 = np.arange((tb // MIN30 + 1) * MIN30, to, MIN30)
                        c["p2_30m_ign"] += len(p2)
                        c["p2_30m"] += len(set(p2.tolist()) - set(sw))
                        c["ev_move"] += cur["mv"]
                        c["ev_move_tfbars"] += cur["mv_tf"]
                        for ti in range(4):
                            if ti == cur["ti"]:
                                continue
                            arr = by_ct.get((cur["sym"], ti))
                            if arr is None:
                                continue
                            n = np.searchsorted(arr, to, "left") - np.searchsorted(arr, tb, "right")
                            c["ev_otf_ign"] += max(0, n)
                            if ti not in tset:
                                c["ev_otf_sw"] += max(0, n)
                        c["pos_min"] += (to - tb) / 60000

                    for tb, g in bundles:
                        if tb < t_out:
                            c["switch"] += 1
                            sw.append(int(tb))
                            continue
                        if cur is not None:
                            close(cur, sw)
                            cur = None
                            sw = []
                        c["entry"] += 1
                        if pe < 1.0 and rng.random() >= pe:
                            continue
                        g2 = g[g.tf_i == g.tf_i.min()]
                        r = g2.iloc[int(rng.integers(len(g2)))]
                        if r.status not in ("TRADED", "UNRESOLVED") or not np.isfinite(r.entry_time):
                            continue
                        t_in = int(r.entry_time)
                        to = int(r.exit_time) if np.isfinite(r.exit_time) else end_ms[run]
                        key = (run, int(r.sig_id))
                        if key not in trade_cache:
                            rd = abs(r.entry_price - r.stop_initial)
                            mv = moves(run, r.symbol, t_in, to, r.entry_price, rd)
                            mv_tf = moves(run, r.symbol, t_in, to, r.entry_price, rd, TF_MIN[r.timeframe])
                            trade_cache[key] = (len(mv), len(mv_tf))
                            calib.append({"run": RUNS[run], "kind": kind, "timeframe": r.timeframe,
                                          "hold_min": (to - t_in) / 60000, "mv_1m": len(mv), "mv_tfbars": len(mv_tf),
                                          "open_end": not np.isfinite(r.exit_time)})
                        mv, mv_tf = trade_cache[key]
                        c["trades"] += 1
                        t_out = to
                        cur = {"tb": int(tb), "t_out": to, "tf": r.timeframe, "ti": int(r.tf_i), "sym": r.symbol,
                               "mv": mv, "mv_tf": mv_tf}
                    if cur is not None:
                        close(cur, sw)
                    acc = {k: v / seeds for k, v in c.items()} if acc is None else {k: acc[k] + c[k] / seeds for k in c}
                row = {"run": RUNS[run], "kind": kind, "strategy": strat, "setup": setup, "pe": pe, "days": D}
                row.update({k + "_pd": v / D for k, v in acc.items()})
                res_rows.append(row)
    res = pd.DataFrame(res_rows)
    res.to_csv(os.path.join(out, "live_calls.csv"), index=False)
    pd.DataFrame(calib).to_csv(os.path.join(out, "live_move_calib.csv"), index=False)
    print("rows", len(res), "calib trades", len(calib))


if __name__ == "__main__":
    main()
