#!/usr/bin/env python3
"""Independent minute-bar exit simulator (verifier's own code; no repo or exitlab imports).

    python3 -I mysim.py <replay_signals.csv> <export_dir> <out_csv> [procs]

Seeds every replayed signal (rb_analyze replay_signals.csv: TRADED or UNRESOLVED, runs v3b + v4) with the replay's
entry fill, entry minute, initial stop, leverage and qty, then re-runs the exit on the concatenated live_bars
(v3b + v4 1m bars) with my own implementation of the engine's exit rules:
  - entry bar: stop checked on the bar range, no lock raise (fill at ref_price mid-bar)
  - later bars: open beyond stop -> exit at open with slippage; low/high touches stop -> exit at stop with slippage;
    else the lock rule runs (applies from the next bar)
  - fees taker 0.05% each side, slippage 0.02% each side, round trip used by the ladder 0.14%
  - funding ignored, liquidation ignored (both checked by parity against the replay's R)
  - open at the end of the bars: marked at the last mark close with exit slippage and fee (OPEN_END)
R = net / (qty x |entry - base 2 ATR stop|).
"""
import math
import multiprocessing as mp
import os
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

TAKER, SLIP = 0.0005, 0.0002
RT = 2 * (TAKER + SLIP)
MIN = 60_000
TFMS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": 60 * MIN, "4h": 240 * MIN}
TSBARS = {"15m": 12, "30m": 10, "1h": 8, "4h": 6}

VARS = {
    "base": dict(lad=("roe", None, 0.10)),
    "geo10": dict(lad=("roe", 10, 0.10)),
    "geo20": dict(lad=("roe", 20, 0.10)),
    "geo40": dict(lad=("roe", 40, 0.10)),
    "geo50": dict(lad=("roe", 50, 0.10)),
    "lock30": dict(lad=("roe", None, 0.30)),
    "tp1R": dict(lad=None, tp=1.0),
    "tp1.5R": dict(lad=None, tp=1.5),
    "tp2R": dict(lad=None, tp=2.0),
    "tp3R": dict(lad=None, tp=3.0),
    "RL1_0.5": dict(lad=("R", 1.0, 0.5, 0.5)),
    "RL1.5_1": dict(lad=("R", 1.5, 1.0, 0.5)),
    "RL2_1": dict(lad=("R", 2.0, 1.0, 0.5)),
    "base_bar": dict(lad=("roe", None, 0.10), bar=True),
    "RL1_0.5_bar": dict(lad=("R", 1.0, 0.5, 0.5), bar=True),
    "be1_tp1.5": dict(lad=None, tp=1.5, be=1.0),
    "be1_tp2": dict(lad=None, tp=2.0, be=1.0),
    "be0.5_tp1": dict(lad=None, tp=1.0, be=0.5),
    "timestop": dict(lad=("roe", None, 0.10), ts="house"),
    "time_max2x": dict(lad=("roe", None, 0.10), ts="max2x"),
    "stopw1.5": dict(lad=("roe", None, 0.10), stopw=1.5),
    "stopw3": dict(lad=("roe", None, 0.10), stopw=3.0),
    "nolock": dict(lad=None),           # 2 ATR stop only, held to the end (pure direction + path)
}
FLIP_VARS = ("base", "geo10", "RL1.5_1", "tp1R", "nolock")

G = {}


def lock_for(best, first):
    trig = first + 0.02
    if not best >= trig - 1e-12:
        return None
    return first + 0.05 * math.floor((best - trig) / 0.05 + 1e-9)


def sim(arr, i0, side, entry, stop0, L, tfms, v):
    """Returns (exit_price_after_slip, exit_index, reason, mfe_price)."""
    ts, o, h, lo, c, mc = arr
    lad = v.get("lad")
    tpk = v.get("tp")
    be = v.get("be")
    bar_only = v.get("bar", False)
    tsm = v.get("ts")
    dist = abs(entry - stop0)
    stop = stop0
    lock = None
    mfe = entry
    tp = None
    if tpk is not None:
        ref = G["cur_ref"]
        tp = ref + side * tpk * abs(ref - G["cur_stop_base"])
    entry_t = ts[i0]
    nb = TSBARS[G["cur_tf"]]
    t_lim = None
    if tsm == "house":
        t_lim = entry_t + nb * tfms
    elif tsm == "max2x":
        t_lim = entry_t + 2 * nb * tfms
    n = len(ts)
    for k in range(i0, n):
        eb = k == i0
        if tp is not None and not eb and (o[k] - tp) * side >= 0:
            return o[k] * (1 - side * SLIP), k, "TPGAP", mfe
        if side > 0:
            mfe = max(mfe, h[k])
        else:
            mfe = min(mfe, lo[k])
        if not eb and (o[k] - stop) * side <= 0:
            return o[k] * (1 - side * SLIP), k, "STOPGAP", mfe
        hit = (lo[k] <= stop) if side > 0 else (h[k] >= stop)
        if hit:
            return stop * (1 - side * SLIP), k, ("LOCK" if lock is not None else "SL"), mfe
        if not eb and (not bar_only or (ts[k] + MIN) % tfms == 0):
            cand = None
            mfeR = side * (mfe - entry) / dist
            if lad is not None and lad[0] == "roe":
                LL = L if lad[1] is None else lad[1]
                best = LL * (side * (mfe / entry - 1.0) - RT)
                lk = lock_for(best, lad[2])
                if lk is not None and (lock is None or lk > lock + 1e-12):
                    cand = entry * (1.0 + side * (lk / LL + RT))
                    lock = lk
            elif lad is not None and lad[0] == "R":
                arm, l0, stp = lad[1], lad[2], lad[3]
                if mfeR >= arm - 1e-12:
                    lr = l0 + stp * math.floor((mfeR - arm) / stp + 1e-9)
                    if lock is None or lr > lock + 1e-12:
                        cand = entry + side * lr * dist
                        lock = lr
            if be is not None and mfeR >= be - 1e-12:
                bep = entry * (1.0 + side * RT)
                cand = bep if cand is None else (max(cand, bep) if side > 0 else min(cand, bep))
                if lock is None:
                    lock = 0.0
            if cand is not None:
                stop = max(stop, cand) if side > 0 else min(stop, cand)
        if tp is not None and not eb:
            if (h[k] >= tp) if side > 0 else (lo[k] <= tp):
                return tp * (1 - side * SLIP), k, "TP", mfe
        if t_lim is not None and ts[k] + MIN >= t_lim:
            go = (lock is None) if tsm == "house" else True
            if go:
                return c[k] * (1 - side * SLIP), k, "TIME", mfe
            t_lim = None
    return mc[n - 1] * (1 - side * SLIP), n - 1, "OPEN_END", mfe


def run_one(r):
    arr = G["bars"][r["symbol"]]
    ts = arr[0]
    i0 = int(np.searchsorted(ts, int(r["entry_time"])))
    if i0 >= len(ts) or ts[i0] != int(r["entry_time"]):
        return []
    tf = r["timeframe"]
    tfms = TFMS[tf]
    out = []
    for flip in (0, 1):
        side = int(r["side"]) * (-1 if flip else 1)
        ref = float(r["ref_price"])
        dist_ref = abs(ref - float(r["stop_initial"]))      # 2 ATR from the ref price
        entry = ref * (1 + side * SLIP)
        stop_base = ref - side * dist_ref
        G["cur_ref"] = ref
        G["cur_stop_base"] = stop_base
        G["cur_tf"] = tf
        dist = abs(entry - stop_base)
        L = float(r["leverage"])
        for name, v in VARS.items():
            if flip and name not in FLIP_VARS:
                continue
            stop0 = stop_base
            if "stopw" in v:
                stop0 = ref - side * dist_ref * v["stopw"] / 2.0
            px, k, why, mfe = sim(arr, i0, side, entry, stop0, L, tfms, v)
            gross = side * (px - entry)
            fees = TAKER * (entry + px)
            net = gross - fees
            gross_noslip = side * (px / (1 - side * SLIP) - entry / (1 + side * SLIP))
            own = abs(entry - stop0)
            out.append(dict(run=r["run"], sig_id=int(r["sig_id"]), flip=flip, variant=name, R=net / dist,
                            R_own=net / own, grossR_fee=(gross) / dist, gross_all=gross_noslip / dist,
                            fee_R=fees / dist, slip_R=(gross_noslip - gross) / dist, reason=why,
                            hold_min=(ts[k] + MIN - ts[i0]) / MIN, mfeR=side * (mfe - entry) / dist,
                            open_end=int(why == "OPEN_END"), stop_frac=dist / entry))
    return out


def worker(rows):
    res = []
    for r in rows:
        res += run_one(r)
    return res


def main():
    rs_path, ex, outp = sys.argv[1], sys.argv[2], sys.argv[3]
    procs = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    rs = pd.read_csv(rs_path, low_memory=False)
    rs = rs[rs.status.isin(["TRADED", "UNRESOLVED"])].copy()
    bars = pd.concat([pd.read_csv(os.path.join(ex, d, "live_bars.csv"))
                      for d in ("run-20261005T183457Z", "current")], ignore_index=True)
    bars = bars.drop_duplicates(["ts", "symbol"]).sort_values(["symbol", "ts"])
    B = {}
    for s, g in bars.groupby("symbol"):
        B[s] = (g.ts.to_numpy(np.int64), g.open.to_numpy(float), g.high.to_numpy(float), g.low.to_numpy(float),
                g.close.to_numpy(float), g.mark_close.fillna(g.close).to_numpy(float))
    G["bars"] = B
    recs = rs[["run", "sig_id", "symbol", "timeframe", "side", "ref_price", "stop_initial", "entry_time",
               "leverage"]].to_dict("records")
    chunks = [recs[i::procs * 4] for i in range(procs * 4)]
    with mp.get_context("fork").Pool(procs) as pool:
        parts = pool.map(worker, chunks)
    df = pd.DataFrame([x for p in parts for x in p])
    df.to_csv(outp, index=False)
    print(df.groupby(["variant", "flip"]).size().to_string())


if __name__ == "__main__":
    main()
