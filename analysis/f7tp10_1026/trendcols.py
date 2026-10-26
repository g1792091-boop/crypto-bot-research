"""Trend columns for the owners' question (10/26) "v3.9 매매법을 추세판단용으로 사용하고 진입 매매법을 레인지로 사용했을때": per coin and
1h bar, the V3.9 1h strategy's last signal side (research/entry_study/param_defs/V39_ALL.py, the locked V3.9 signal, latched
forward: +1 after a long signal until a short one) and the V3.9 supertrend (10, 3) direction on the 1h bar
(trendjudge.vote_arrays' own function). -> WORK/prep/<COIN>_trend.npz
Run: python3 trendcols.py --work WORK_DIR"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import warnings

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")


def v39_module():
    p = os.path.join(REPO, "research", "entry_study", "param_defs", "V39_ALL.py")
    spec = importlib.util.spec_from_file_location("v39_param_defs", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    P = v39_module()
    from paperbot import trendjudge as TJ
    fg, pi = TJ.lib()
    for c in COINS:
        z = np.load(os.path.join(a.work, "prep", f"{c}.npz"))
        df = pd.DataFrame({"ts": pd.to_datetime(z["h1_ts"], unit="ms", utc=True), "open": z["h1_o"], "high": z["h1_h"],
                           "low": z["h1_l"], "close": z["h1_c"], "volume": z["h1_v"]})
        df.attrs["tf"] = "1h"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lo, sh = P.signals(df, "1h")
            _line, d = pi.exchange_supertrend(df["high"].to_numpy(float), df["low"].to_numpy(float),
                                              df["close"].to_numpy(float), 10, 3.0)
        sig = np.asarray(lo, bool).astype(np.int8) - np.asarray(sh, bool).astype(np.int8)
        latch = pd.Series(np.where(sig != 0, sig, np.nan)).ffill().fillna(0).to_numpy(np.int8)
        st = np.where(np.asarray(d) == 1, 1, np.where(np.asarray(d) == -1, -1, 0)).astype(np.int8)
        with warnings.catch_warnings():               # the trend bot's four judges on the 1h bar itself, and EMA200
            warnings.simplefilter("ignore")
            arr = TJ.vote_arrays(df, fg, pi)
            e200 = TJ._f(fg.ema(df["close"], 200))
        close = df["close"].to_numpy(float)
        extra = {f"j1_{k}": arr[k].astype(np.int8) for k in TJ.JUDGES}
        extra["j1_raw3"] = TJ.raw_votes(arr, 3)
        extra["ema200"] = np.where(close > e200, 1, np.where(close < e200, -1, 0)).astype(np.int8)
        np.savez(os.path.join(a.work, "prep", f"{c}_trend.npz"), v39_sig=sig, v39_latch=latch, st1h=st, **extra)
        print(c, "V3.9 signals", int((sig != 0).sum()), "latch long share %.2f" % float((latch > 0).mean()), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
