"""Same as judge_horizon.py, but split long/short and subtract the unconditional drift (bull 2020-21 bias)."""
import sys, os
REPO = "/home/user/crypto-bot-research"
sys.path.insert(0, REPO); sys.path.append("/root/.local/lib/python3.11/site-packages")
import numpy as np, pandas as pd
from paperbot import trendjudge as tj
COINS = ["btc", "eth", "sol", "doge", "ltc", "bch"]
HS = [4, 12, 24, 48]
fg, pi = tj.lib()
for tf in ["1h", "4h"]:
    res = {(h, s): [0, 0, 0.0, 0.0] for h in HS for s in (1, -1)}  # hits, n, sum move*dir, sum (move-drift)*dir
    for c in COINS:
        df = pd.read_csv(f"{REPO}/data/pre2021/{c}usd-{tf}.csv.gz"); df["ts"] = pd.to_datetime(df["ts"], utc=True)
        arr = tj.vote_arrays(df, fg, pi); raw = tj.raw_votes(arr, 3).astype(int)
        hold = 2 if tf == "1h" else 1
        held = raw.copy()
        for h in range(1, hold):
            prev = np.r_[np.zeros(h, int), raw[:-h]]; held = np.where(prev == raw, held, 0)
        lc = np.log(df["close"].to_numpy(float))
        for h in HS:
            k = np.arange(120, len(lc) - h); mv = lc[k + h] - lc[k]; drift = mv.mean(); d = held[k]
            for s in (1, -1):
                sel = d == s
                r = res[(h, s)]
                r[0] += int((np.sign(mv[sel]) == s).sum()); r[1] += int(sel.sum())
                r[2] += float((mv[sel] * s).sum()); r[3] += float(((mv[sel] - drift) * s).sum())
    print(f"== {tf} J4 split by side (pre2021); 'demeaned' = signed move minus each coin's average h-bar move")
    for h in HS:
        for s in (1, -1):
            hit, n, a, b = res[(h, s)]
            print(f"  h={h:>2} {'long ' if s>0 else 'short'}: n={n:6d} acc={100*hit/max(n,1):5.1f}% raw={1e4*a/max(n,1):7.1f}bp demeaned={1e4*b/max(n,1):7.1f}bp")
