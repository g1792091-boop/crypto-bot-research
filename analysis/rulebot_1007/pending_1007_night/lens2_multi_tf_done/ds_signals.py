"""DeepSeek-200 signal cache on the Binance futures bars, using the repo's own lib_c.entries (read-only import).

    python3 -I -B ds_signals.py <bars_dir> <out_dir> [procs]

Writes ds_<tf>_<coin>.npz with ts (ns) and s__<def> int8 (+1 long, -1 short, 0) for every definition of that tf.
"""
import os
import sys
import time

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', '/home/user/crypto-bot-research',
                '/home/user/crypto-bot-research/research/deepseek200']
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from multiprocessing import Pool  # noqa: E402

import lib_c  # noqa: E402


def load_main(bars_dir, tf, coin):
    E = lib_c.env()
    L = E["L"]
    p = os.path.join(bars_dir, f"{coin.lower()}-{tf}.csv.gz")
    main = L.read_ohlcv(p)
    main = main[main["ts"] < pd.Timestamp("2026-09-30", tz="UTC")].reset_index(drop=True)
    main.attrs["tf"] = tf
    return main


def job(args):
    bars_dir, out_dir, tf, coin = args
    fn = os.path.join(out_dir, f"ds_{tf}_{coin}.npz")
    if os.path.exists(fn):
        return tf, coin, 0, 0.0
    t0 = time.time()
    df = load_main(bars_dir, tf, coin)
    ctx = None if coin == "BTCUSD" else {"BTCUSD": load_main(bars_dir, tf, "BTCUSD")}
    sig = lib_c.entries(df, tf, ctx, coin)
    ts = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None).to_numpy().astype("datetime64[ns]").astype(np.int64)
    arrs = {f"s__{k}": (lg.astype(np.int8) - sh.astype(np.int8)) for k, (lg, sh) in sig.items()}
    np.savez_compressed(fn, ts=ts, **arrs)
    return tf, coin, len(df), time.time() - t0


if __name__ == "__main__":
    bars_dir, out_dir = sys.argv[1], sys.argv[2]
    procs = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    os.makedirs(out_dir, exist_ok=True)
    jobs = [(bars_dir, out_dir, tf, c) for tf in ("4h", "1h", "30m", "15m") for c in lib_c.COINS]
    with Pool(procs) as p:
        for r in p.imap_unordered(job, jobs):
            print(r, flush=True)
