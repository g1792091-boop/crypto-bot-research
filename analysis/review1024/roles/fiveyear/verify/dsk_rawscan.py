"""Direction-skill verifier, part 6: data-error scan of the raw 1m files behind every outcome (fg1m, 2021-01 .. 2026-09):
duplicate / unsorted timestamps, missing minutes, non-positive or NaN prices, o/c outside [l, h], and one-minute wicks
that revert (low < 0.95 x min(previous close, next open) or high > 1.05 x max(...)) -- a bad tick would stop one side
and lock the other at the same entry, i.e. fake direction outcomes.

    python3 dsk_rawscan.py"""
import os
import numpy as np
import pandas as pd

RAWDIR = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/fg1m/1m"
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
A = int(pd.Timestamp("2021-01-01", tz="UTC").value // 10**6)
B = int(pd.Timestamp("2026-10-01", tz="UTC").value // 10**6)
rows = []
for coin in COINS:
    z = np.load(os.path.join(RAWDIR, f"{coin}.npz"))
    ts = z["ts"].astype(np.int64)
    m = (ts >= A) & (ts < B)
    t = ts[m]
    o, h, l, c = (z[k][m].astype(float) for k in ("o", "h", "l", "c"))
    d = np.diff(t)
    ref_lo = np.minimum(np.r_[c[0], c[:-1]], np.r_[o[1:], o[-1]])
    ref_hi = np.maximum(np.r_[c[0], c[:-1]], np.r_[o[1:], o[-1]])
    wick_dn = l < 0.95 * ref_lo
    wick_up = h > 1.05 * ref_hi
    rows.append({"coin": coin, "minutes": len(t), "expected": (B - A) // 60000, "dup_or_unsorted": int((d <= 0).sum()),
                 "missing": int((B - A) // 60000 - len(t)), "gaps_over_10min": int((d > 600000).sum()),
                 "max_gap_min": int(d.max() // 60000), "nonpos_or_nan": int((~np.isfinite(np.c_[o, h, l, c]) |
                                                                             (np.c_[o, h, l, c] <= 0)).any(1).sum()),
                 "ohlc_inconsistent": int(((o > h + 1e-12) | (o < l - 1e-12) | (c > h + 1e-12) | (c < l - 1e-12)).sum()),
                 "revert_wick_dn5": int(wick_dn.sum()), "revert_wick_up5": int(wick_up.sum()),
                 "wick_times": ";".join(str(pd.Timestamp(int(x), unit="ms")) for x in t[wick_dn | wick_up][:6])})
D = pd.DataFrame(rows)
print(D.to_string())
D.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dsk_rawscan.csv"), index=False)
