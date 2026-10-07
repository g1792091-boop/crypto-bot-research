#!/usr/bin/env python3
"""Own simulator of the house exit (2 ATR stop + net-ROE lock ladder 10% / +5% / gap 2%) on the live 1m bars,
for every replayed (TRADED, resolved) 15m / 30m signal of v3b + v4. Runs it twice on the same entries:
  (a) 1m bars (as the live engine)      -> parity check vs the pipeline replay R
  (b) signal-timeframe bars (15m / 30m) built from the same 1m bars (as the 5-year research engine)
and reports mean R and pre-cost gross R for both. Funding and liquidation ignored.

python3 -I v9_granularity.py <export_dir> <v2_replay_rows.csv>
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vboot  # noqa
import numpy as np
import pandas as pd
from v2_replay_gross import cboot

FIRST, STEP, GAP, RT, FEE, SLIP = 0.10, 0.05, 0.02, 0.0014, 0.0005, 0.0002
TFMS = {"15m": 900_000, "30m": 1_800_000}


def lock_for(best):
    ft = FIRST + GAP
    if best < ft - 1e-12:
        return None
    return FIRST + STEP * math.floor((best - ft) / STEP + 1e-9)


def sim(bars, side, fill, stop0, lev, entry_ts):
    """bars: list of (ts, o, h, l) starting with the entry bar. Returns (exit_raw, exit_fill, reason)."""
    stop = stop0
    mfe = fill
    lock = None
    for k, (ts, o, h, l) in enumerate(bars):
        entry_bar = k == 0
        mfe = max(mfe, h) if side > 0 else min(mfe, l)
        if not entry_bar and (o - stop) * side <= 0:
            return o, o * (1 - side * SLIP), ("LOCK" if lock is not None else "SL")
        hit = (l <= stop) if side > 0 else (h >= stop)
        if hit:
            return stop, stop * (1 - side * SLIP), ("LOCK" if lock is not None else "SL")
        if not entry_bar:
            best = lev * (side * (mfe / fill - 1) - RT)
            lk = lock_for(best)
            if lk is not None and (lock is None or lk > lock + 1e-12):
                px = fill * (1 + side * (lk / lev + RT))
                stop = max(stop, px) if side > 0 else min(stop, px)
                lock = lk
    return None, None, "OPEN"


def main():
    ex, rep = sys.argv[1:3]
    R = pd.read_csv(rep)
    R = R[(R["status"] == "TRADED") & R["timeframe"].isin(["15m", "30m"]) & R["grp"].isin(["core36", "ds200", "coinflip"])]
    out = []
    for run in ("run-20261005T183457Z", "current"):
        B = pd.read_csv(os.path.join(ex, run, "live_bars.csv"), usecols=["ts", "symbol", "open", "high", "low"])
        by = {s: g.sort_values("ts").reset_index(drop=True) for s, g in B.groupby("symbol")}
        agg = {}
        for s, g in by.items():
            for tf, ms in TFMS.items():
                k = g["ts"] // ms * ms
                a = g.groupby(k).agg(o=("open", "first"), h=("high", "max"), l=("low", "min")).reset_index()
                a.columns = ["ts", "o", "h", "l"]
                agg[(s, tf)] = a
        for r in R[R["run"] == run].itertuples():
            g = by[r.symbol]
            side, fill, stop0, lev = int(r.side), float(r.entry_price), float(r.stop_initial), float(r.leverage)
            i0 = int(np.searchsorted(g["ts"].to_numpy(), int(r.entry_time)))
            b1 = list(zip(g["ts"].to_numpy()[i0:], g["open"].to_numpy()[i0:], g["high"].to_numpy()[i0:], g["low"].to_numpy()[i0:]))
            x1, f1, why1 = sim(b1, side, fill, stop0, lev, r.entry_time)
            a = agg[(r.symbol, r.timeframe)]
            j0 = int(np.searchsorted(a["ts"].to_numpy(), int(r.entry_time) // TFMS[r.timeframe] * TFMS[r.timeframe]))
            bT = list(zip(a["ts"].to_numpy()[j0:], a["o"].to_numpy()[j0:], a["h"].to_numpy()[j0:], a["l"].to_numpy()[j0:]))
            xT, fT, whyT = sim(bT, side, fill, stop0, lev, r.entry_time)
            risk = abs(fill - stop0)
            ref = fill / (1 + side * SLIP)

            def rr(xf):
                return None if xf is None else (side * (xf - fill) - FEE * (fill + xf)) / risk

            def gg(xr):
                return None if xr is None else side * (xr - ref) / risk
            out.append(dict(run=run, grp=r.grp, tf=r.timeframe, R_pipe=r.R, why_pipe=r.exit_reason, R_1m=rr(f1), why_1m=why1,
                            R_tf=rr(fT), why_tf=whyT, g_1m=gg(x1), g_tf=gg(xT), cl4h=r.cl4h, cl1h=r.cl1h))
    O = pd.DataFrame(out)
    O.to_csv(os.path.join(os.path.dirname(rep), "v9_rows.csv"), index=False)
    ok = O["R_1m"].notna()
    print("signals", len(O), "1m resolved", ok.sum(), "parity |R_1m - R_pipe| < 0.02:", (abs(O.loc[ok, "R_1m"] - O.loc[ok, "R_pipe"]) < 0.02).mean().round(4),
          "same reason", (O.loc[ok, "why_1m"] == O.loc[ok, "why_pipe"]).mean().round(4),
          "median abs diff", abs(O.loc[ok, "R_1m"] - O.loc[ok, "R_pipe"]).median())
    B = O[O["R_1m"].notna() & O["R_tf"].notna()].copy()
    B["dg"] = B["g_tf"] - B["g_1m"]
    rows = []
    for (g, tf), x in B.groupby(["grp", "tf"]):
        lo, hi, k = cboot(x["dg"], x["cl4h"])
        rows.append(dict(grp=g, tf=tf, n=len(x), R_1m=x["R_1m"].mean(), R_tf=x["R_tf"].mean(), gross_1m=x["g_1m"].mean(),
                         gross_tf=x["g_tf"].mean(), diff_tf_minus_1m=x["dg"].mean(), ci4h=f"[{lo:+.3f},{hi:+.3f}]",
                         lock_share_1m=(x["why_1m"] == "LOCK").mean(), lock_share_tf=(x["why_tf"] == "LOCK").mean()))
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    for tf in ("15m", "30m"):
        x = B[(B.tf == tf) & B.grp.isin(["core36", "ds200"])]
        lo, hi, k = cboot(x["dg"], x["cl4h"])
        print(tf, "core36+ds200 n", len(x), "gross 1m %.4f tf-bars %.4f diff %.4f [%.3f,%.3f]" % (x.g_1m.mean(), x.g_tf.mean(), x.dg.mean(), lo, hi))


if __name__ == "__main__":
    main()
