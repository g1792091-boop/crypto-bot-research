"""Verifier: one October trade printed from the bot's own 1m bars (live_bars.csv) for a by-eye time-alignment check.
Run: python3 vlh_one.py <live_bars.csv> <symbol> <entry UTC 'YYYY-MM-DD HH:MM'> <side +1/-1> <lev>"""
import sys
import numpy as np
import pandas as pd
LBF, sym, ent, side, lev = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), float(sys.argv[5])
COST = 0.00124
t = int(pd.Timestamp(ent, tz="UTC").value // 10**6)
X = pd.read_csv(LBF, usecols=["ts", "symbol", "open", "high", "low", "close"])
X = X[X.symbol == sym].sort_values("ts").reset_index(drop=True)
i = int(np.searchsorted(X.ts, t))
print("signal bar (30m) minutes before entry:"); print(X.iloc[i - 3:i].assign(utc=lambda d: pd.to_datetime(d.ts, unit="ms")).to_string())
p0 = X.open[i]
print("entry minute", pd.to_datetime(X.ts[i], unit="ms"), "open", p0)
best, lock = -9, None
for k in range(0, 3000):
    r = X.iloc[i + k]
    fav = r.high if side > 0 else r.low
    adv = r.low if side > 0 else r.high
    roe_adv = lev * (side * (adv / p0 - 1) - COST)
    fl = -0.5 if lock is None else lock
    if roe_adv <= fl:
        px = p0 * (1 + side * (fl / lev + COST))
        fill = px if (side > 0 and r.open > px) or (side < 0 and r.open < px) else r.open
        print("exit minute k", k, pd.to_datetime(r.ts, unit="ms"), "floor", round(fl, 3), "fill", round(fill, 6),
              "net ROE %.4f" % (lev * (side * (fill / p0 - 1) - COST)))
        break
    b = lev * (side * (fav / p0 - 1) - COST)
    if b > best:
        best = b
        nl = None if b < 0.11 else (0.10 if b < 0.15 else 0.12 + 0.05 * np.floor((b - 0.15) / 0.05 + 1e-9))
        if nl is not None and (lock is None or nl > lock):
            lock = nl
            print("  k", k, pd.to_datetime(r.ts, unit="ms"), "best %.3f -> lock %.2f (from next minute)" % (b, lock))
