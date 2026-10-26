"""Owners 10/26 (photo of the candidate league account ds-F7_RF_TRIPLE-1h-1-tp10, 21 wins 3 losses): the arrays every
later step reads, from Binance USD-M 5-minute bars of the six coins (2020-01 .. 2026-10-24, public data.binance.vision,
checksums verified by analysis/v39_1h/fetch_bars.py five, volume kept).

Per coin -> WORK/prep/<COIN>.npz:
  h1_*   1-hour bars (open ms, o h l c v), complete hours only
  sig_c  F7_RF_TRIPLE 1h with the pick's custom numbers (rf_period 80, rf_mult 9.0): +1 long / -1 short / 0 at the bar
  sig_d  the same with the rule bot's default numbers (100, 3.0)  (control)
  s_*    the entry bar (1h): EMA20, ATR14, RSI14, range (trendjudge.spot_frame's functions)
  j4_*   the trend bot's judge on the last closed 4h bar (trendjudge.vote_arrays: V39 S6 OBV N12, ADX, EMA20, ATR, raw3)
  jd_*   the same on the daily bar (for reading only)

Signals and judges on the full series at once (the trend bot's own five-year study measured this equal to the live
trailing windows for its members and judges: research/trendbot/fiveyear/RESULTS_KO.md 1장).
Run: python3 -I prep.py --bars FIVE5M_DIR --work WORK_DIR   (the repository is put on sys.path explicitly)"""
from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from multiprocessing import Pool

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
sys.path.append("/root/.local/lib/python3.11/site-packages")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
HOUR = 3_600_000
CUSTOM = {"rf_period": 80, "rf_mult": 9.0}


def bars(ts, o, h, l, c, v, ms):
    """Complete bars of ``ms`` from 5-minute bars (a bar with any 5-minute bar missing still counts: Binance drops
    zero-volume bars, so a missing one is a no-trade bar)."""
    k = ts // ms
    starts = np.r_[0, np.flatnonzero(np.diff(k)) + 1]
    ends = np.r_[starts[1:], len(k)]
    out = {"ts": k[starts] * ms, "o": o[starts], "h": np.maximum.reduceat(h, starts), "l": np.minimum.reduceat(l, starts),
           "c": c[ends - 1], "v": np.add.reduceat(v, starts)}
    last_full = (ts[-1] + 300_000) // ms * ms          # the bar holding the last 5m bar is complete only at its end
    keep = out["ts"] + ms <= last_full
    return {kk: a[keep] for kk, a in out.items()}


def frame(b):
    return pd.DataFrame({"ts": pd.to_datetime(b["ts"], unit="ms"), "open": b["o"], "high": b["h"], "low": b["l"],
                         "close": b["c"], "volume": b["v"]})


def job(args):
    coin, bars_dir, work = args
    from paperbot import trendjudge as TJ
    from research.fullgrid import ds_defs as D
    fg, pi = TJ.lib()
    z = np.load(os.path.join(bars_dir, "5m", f"{coin}.npz"))
    ts, o, h, l, c, v = (z[k] for k in ("ts", "o", "h", "l", "c", "v"))
    out = {}
    h1 = bars(ts, o, h, l, c, v, HOUR)
    for k, a in h1.items():
        out[f"h1_{k}"] = a
    df1 = frame(h1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for key, nums in (("sig_c", CUSTOM), ("sig_d", {})):
            lg, sh = D.signals(df1, "1h", "F7_RF_TRIPLE", coin=coin[:-4], **nums)
            out[key] = (lg.astype(np.int8) - sh.astype(np.int8))
        out["s_ema20"] = TJ._f(fg.ema(df1["close"], 20))
        out["s_atr"] = TJ._f(fg.atr(df1, 14))
        out["s_rsi"] = TJ._f(fg.rsi(df1["close"], 14))
        out["s_range"] = h1["h"] - h1["l"]
        for tag, ms in (("j4", 4 * HOUR), ("jd", 24 * HOUR)):
            b = bars(ts, o, h, l, c, v, ms)
            arr = TJ.vote_arrays(frame(b), fg, pi)
            out[f"{tag}_ts"] = b["ts"]
            for k in TJ.JUDGES:
                out[f"{tag}_{k}"] = arr[k].astype(np.int8)
            out[f"{tag}_raw3"] = TJ.raw_votes(arr, 3)
            for k in ("adx", "ema20", "atr", "close"):
                out[f"{tag}_{k}"] = arr[k]
    np.savez(os.path.join(work, "prep", f"{coin}.npz"), **out)
    return coin, int((out["sig_c"] != 0).sum()), int((out["sig_d"] != 0).sum()), len(h1["ts"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    os.makedirs(os.path.join(a.work, "prep"), exist_ok=True)
    t0 = time.time()
    with Pool(3) as pool:
        for coin, nc, nd, nh in pool.imap_unordered(job, [(c, a.bars, a.work) for c in COINS]):
            print(f"{coin}: {nh:,} hours, custom signals {nc:,}, default {nd:,} ({time.time() - t0:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
