"""Owners 10/26: "제발 내 목표 수익률을 이루는 자동매매봇을 위해 최선을 다해줘 … 내목표 수익률을 위해 다양하게 테스트해봐". The arrays
hunt.py reads, per coin -> WORK/hunt/<COIN>.npz, for F7_RF_TRIPLE (레인지 필터 3중 일치) on 15m / 30m / 1h / 4h:
  <tf>_ts _c _atr          bars (open ms), close, ATR14 (trendjudge's fg.atr)
  <tf>_<n>_state           +1 while the three agree long (range filter up, Heikin-Ashi bar up, the higher frame's Heikin-Ashi up),
                           -1 while they agree short, 0 otherwise (ds_defs._f7_triple's own pieces)
  <tf>_<n>_sig             the strategy's signal: the first bar of each run of the state (checked equal to ds_defs.signals)
numbers <n>: c = the league's custom pick of that frame (1h 80 / 9.0, 4h 50 / 4.5), d = the rule bot's defaults (100 / 3.0),
x = the 1h pick's 80 / 9.0 on a frame without its own pick (15m, 30m).
And per 5-minute grid time (WORK/hunt/blocks.npz): the NYSE-open pause (30 before / 30 after), macro +-30 min, KST weekend.
Run: python3 hunt_prep.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402

import prep as P  # noqa: E402  (puts the repository on sys.path)

FRAMES = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
NUMBERS = {"15m": {"d": {}, "x": {"rf_period": 80, "rf_mult": 9.0}},
           "30m": {"d": {}, "x": {"rf_period": 80, "rf_mult": 9.0}},
           "1h": {"c": {"rf_period": 80, "rf_mult": 9.0}, "d": {}},
           "4h": {"c": {"rf_period": 50, "rf_mult": 4.5}, "d": {}}}
GRID_FROM = "2024-12-01"


def job(args):
    coin, bars_dir, work = args
    from paperbot import trendjudge as TJ
    from research.fullgrid import ds_defs as D
    fg, pi = TJ.lib()
    z = np.load(os.path.join(bars_dir, "5m", f"{coin}.npz"))
    ts, o, h, l, c, v = (z[k] for k in ("ts", "o", "h", "l", "c", "v"))
    out = {}
    for tf, ms in FRAMES.items():
        b = P.bars(ts, o, h, l, c, v, ms)
        df = P.frame(b)
        out[f"{tf}_ts"], out[f"{tf}_c"] = b["ts"], b["c"]
        out[f"{tf}_atr"] = TJ._f(fg.atr(df, 14))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ha = D.C.heikin_bull(b["o"], b["h"], b["l"], b["c"])
            hha = D.C.htf_value(df, tf, lambda dh: D.C.heikin_bull(dh["open"].to_numpy(float), dh["high"].to_numpy(float),
                                                                    dh["low"].to_numpy(float), dh["close"].to_numpy(float)))
            for nk, nums in NUMBERS[tf].items():
                p = D._resolve("F7_RF_TRIPLE", nums)
                rf = D.range_filter_dir(b["c"], p["rf_period"], p["rf_mult"])
                up, dn = (rf == 1) & (ha == 1) & (hha == 1), (rf == -1) & (ha == 0) & (hha == 0)
                state = up.astype(np.int8) - dn.astype(np.int8)
                sig = D._first_event(up).astype(np.int8) - D._first_event(dn).astype(np.int8)
                lg, sh = D.signals(df, tf, "F7_RF_TRIPLE", coin=coin[:-4], **nums)
                ref = lg.astype(np.int8) - sh.astype(np.int8)
                if not np.array_equal(sig, ref):
                    raise SystemExit(f"{coin} {tf} {nk}: state-built signals differ from ds_defs.signals "
                                     f"({int((sig != ref).sum())} bars)")
                out[f"{tf}_{nk}_state"], out[f"{tf}_{nk}_sig"] = state, sig
    np.savez(os.path.join(work, "hunt", f"{coin}.npz"), **out)
    return coin, {k: int((out[k] != 0).sum()) for k in out if k.endswith("_sig")}


def blocks(work: str, ts_end: int) -> None:
    from paperbot import combo as C
    import study as ST
    t0 = int(np.datetime64(GRID_FROM, "ms").astype(np.int64))
    grid = np.arange(t0, ts_end, 300_000, dtype=np.int64)
    macro = ST.macro_times()
    a = np.searchsorted(macro, grid - 30 * 60_000, side="left")
    b = np.searchsorted(macro, grid + 30 * 60_000, side="right")
    us = np.fromiter((bool(C.us_open_pause(int(t), 30, 30)) for t in grid), bool, len(grid))
    wk = np.fromiter((C.kst_weekend(int(t)) for t in grid), bool, len(grid))
    np.savez(os.path.join(work, "hunt", "blocks.npz"), grid=grid, us_open=us, macro=b > a, weekend=wk)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    os.makedirs(os.path.join(a.work, "hunt"), exist_ok=True)
    t0 = time.time()
    with Pool(3) as pool:
        for coin, n in pool.imap_unordered(job, [(c, a.bars, a.work) for c in P.COINS]):
            print(coin, n, f"{time.time() - t0:.0f}s", flush=True)
    end = int(np.load(os.path.join(a.bars, "5m", "BTCUSDT.npz"))["ts"][-1]) + 300_000
    blocks(a.work, end)
    print("blocks done", f"{time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
