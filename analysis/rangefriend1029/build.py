#!/usr/bin/env python3
"""Arrays for run.py (PLAN.md 2): the range signals and block table of analysis/f7tp10_1026/hunt_prep.py (its grid from
2020-01, the study's started 2024-12), the coin's 1h V3.9 supertrend (10, 3) that the current trend check reads (WORK/prep/
<COIN>_trend.npz, as trendcols.py: trendjudge's exchange_supertrend on the same 1h bars), and the friend indicator's votes on
1h and 30m bars (WORK/friend/<COIN>_<tf>.npz).
    python3 -E -P analysis/rangefriend1029/build.py --bars BARS --work WORK
BARS/5m/<COIN>.npz: Binance 5m klines with volume (ts, o, h, l, c, v, fund). Research code: nothing here trades."""
from __future__ import annotations

import argparse
import os
import sys
import time
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [HERE, os.path.join(REPO, "analysis", "f7tp10_1026"), REPO]
import numpy as np  # noqa: E402

import friendtrend as FT  # noqa: E402
import hunt_prep as HP  # noqa: E402
import prep as P  # noqa: E402

FRAMES = {"1h": 3_600_000, "30m": 1_800_000}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    for d in ("prep", "friend", "hunt"):
        os.makedirs(os.path.join(a.work, d), exist_ok=True)
    t0 = time.time()
    HP.GRID_FROM = "2020-01-01"
    HP.main(["--bars", a.bars, "--work", a.work])
    from paperbot import trendjudge as TJ
    _fg, pi = TJ.lib()
    for coin in P.COINS:
        z = np.load(os.path.join(a.bars, "5m", f"{coin}.npz"))
        ts, o, h, l, c, v = (z[k] for k in ("ts", "o", "h", "l", "c", "v"))
        for tf, ms in FRAMES.items():
            b = P.bars(ts, o, h, l, c, v, ms)
            if tf == "1h":
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    _line, d = pi.exchange_supertrend(b["h"], b["l"], b["c"], 10, 3.0)
                st = np.where(np.asarray(d) == 1, 1, np.where(np.asarray(d) == -1, -1, 0)).astype(np.int8)
                np.savez(os.path.join(a.work, "prep", f"{coin}_trend.npz"), st1h=st)
            V = FT.votes(b["o"], b["h"], b["l"], b["c"], b["v"])
            np.savez(os.path.join(a.work, "friend", f"{coin}_{tf}.npz"), ts=b["ts"], **V)
            tr = V["trend"]
            print(coin, tf, f"bars {len(tr):,} up {float((tr == 1).mean()):.2f} down {float((tr == -1).mean()):.2f} "
                  f"no entry {float((tr == 0).mean()):.2f}", f"{time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
