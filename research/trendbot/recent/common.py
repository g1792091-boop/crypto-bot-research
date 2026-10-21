"""Shared helpers of the 추세판단 봇 recent replay: paths, the parsed 1m bars, aggregation.
Every script here is run as ``python3 -I <script> ROOT ...``: ROOT is a scratch folder (ROOT/data downloaded zips,
ROOT/cache parsed bars, ROOT/out results); the repository is this file's ../../.. ."""
import os
import sys

sys.path.append("/root/.local/lib/python3.11/site-packages")      # user site (dateutil), dropped by -I
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402,F401  (re-exported to the scripts)

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"]
MIN = 60_000
FIVE = 300_000
TF_MS = {"5m": 300_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}


def load_1m(root, coin):
    z = np.load(f"{root}/cache/{coin}-1m.npz")
    return {k: z[k] for k in ("ts", "o", "h", "l", "c", "v")}


def agg(m, ms):
    """Aggregate contiguous, gap-free 1m arrays (starting on a ``ms`` boundary) to bars of ``ms``; only complete bars."""
    k = ms // MIN
    ts = m["ts"]
    start = int(np.argmax(ts % ms == 0))
    n = (len(ts) - start) // k
    sl = slice(start, start + n * k)

    def r(a):
        return a[sl].reshape(n, k)
    return {"ts": ts[sl][::k].copy(), "o": r(m["o"])[:, 0].copy(), "h": r(m["h"]).max(1), "l": r(m["l"]).min(1),
            "c": r(m["c"])[:, -1].copy(), "v": r(m["v"]).sum(1)}
