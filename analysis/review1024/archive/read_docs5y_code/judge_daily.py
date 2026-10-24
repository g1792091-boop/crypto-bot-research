"""Daily trend judge (4h bars resampled to UTC days) on pre2021; h in days. Read-only."""
import sys
REPO = "/home/user/crypto-bot-research"
sys.path.insert(0, REPO); sys.path.append("/root/.local/lib/python3.11/site-packages")
import numpy as np, pandas as pd
from paperbot import trendjudge as tj
COINS = ["btc", "eth", "sol", "doge", "ltc", "bch"]
HS = [1, 3, 5, 10]
fg, pi = tj.lib()
res = {(h, s): [0, 0, 0.0, 0.0] for h in HS for s in (1, -1)}
for c in COINS:
    df = pd.read_csv(f"{REPO}/data/pre2021/{c}usd-4h.csv.gz"); df["ts"] = pd.to_datetime(df["ts"], utc=True)
    d = df.set_index("ts").resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
    arr = tj.vote_arrays(d, fg, pi); raw = tj.raw_votes(arr, 3).astype(int)
    lc = np.log(d["close"].to_numpy(float))
    for h in HS:
        k = np.arange(80, len(lc) - h); mv = lc[k + h] - lc[k]; drift = mv.mean(); dd = raw[k]
        for s in (1, -1):
            sel = dd == s; r = res[(h, s)]
            r[0] += int((np.sign(mv[sel]) == s).sum()); r[1] += int(sel.sum())
            r[2] += float((mv[sel] * s).sum()); r[3] += float(((mv[sel] - drift) * s).sum())
print("== 1d J4 (vote>=3) pre2021, h in days")
for h in HS:
    for s in (1, -1):
        hit, n, a, b = res[(h, s)]
        print(f"  h={h:>2}d {'long ' if s>0 else 'short'}: n={n:5d} acc={100*hit/max(n,1):5.1f}% raw={1e4*a/max(n,1):7.1f}bp demeaned={1e4*b/max(n,1):7.1f}bp")
