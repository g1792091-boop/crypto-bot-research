"""Quick check: does the trend judge (J4 vote>=3 of V39/S6/OBV/N12) predict the sign of the next h bars?
Independent period: data/pre2021 (2020-01 .. 2021-08), 6 coins, 1h and 4h. Read-only."""
import sys, os
REPO = "/home/user/crypto-bot-research"
sys.path.insert(0, REPO); sys.path.append("/root/.local/lib/python3.11/site-packages")
import numpy as np
import pandas as pd
from paperbot import trendjudge as tj

COINS = ["btc", "eth", "sol", "doge", "ltc", "bch"]
HS = [1, 2, 4, 8, 12, 24, 48]
fg, pi = tj.lib()
out = []
for tf in ["1h", "4h"]:
    agg = {h: [0, 0, 0.0] for h in HS}           # hits, n, sum signed log return
    per = {k: {h: [0, 0, 0.0] for h in HS} for k in tj.JUDGES}
    for c in COINS:
        p = f"{REPO}/data/pre2021/{c}usd-{tf}.csv.gz"
        if not os.path.isfile(p):
            continue
        df = pd.read_csv(p)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        arr = tj.vote_arrays(df, fg, pi)
        raw = tj.raw_votes(arr, 3).astype(int)
        # held: same raw on the last `hold` bars (1h: 2, 4h: 1)
        hold = 2 if tf == "1h" else 1
        held = raw.copy()
        for h in range(1, hold):
            prev = np.r_[np.zeros(h, int), raw[:-h]]
            held = np.where(prev == raw, held, 0)
        cl = df["close"].to_numpy(float)
        lc = np.log(cl)
        warm = 120
        for h in HS:
            k = np.arange(warm, len(cl) - h)
            mv = lc[k + h] - lc[k]
            d = held[k]
            sel = d != 0
            agg[h][0] += int((np.sign(mv[sel]) == d[sel]).sum())
            agg[h][1] += int(sel.sum())
            agg[h][2] += float((mv[sel] * d[sel]).sum())
            for j in tj.JUDGES:
                dj = np.asarray(arr[j], int)[k]
                s2 = dj != 0
                per[j][h][0] += int((np.sign(mv[s2]) == dj[s2]).sum())
                per[j][h][1] += int(s2.sum())
                per[j][h][2] += float((mv[s2] * dj[s2]).sum())
    print(f"== {tf} J4 (vote>=3, held) on pre2021 2020-01..2021-08")
    for h in HS:
        hit, n, s = agg[h]
        print(f"  h={h:>2} bars: n={n:6d} acc={100*hit/max(n,1):5.1f}%  mean signed move={1e4*s/max(n,1):7.1f} bp")
    for j in tj.JUDGES:
        row = " ".join(f"h{h}:{100*per[j][h][0]/max(per[j][h][1],1):4.1f}%/{1e4*per[j][h][2]/max(per[j][h][1],1):6.1f}bp" for h in HS)
        print(f"  {j:>4}: {row}")
