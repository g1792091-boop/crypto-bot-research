"""Size of the 'funding = 0 in October' simplification for the 574 pooled H2 rows: funding rates per (symbol, funding
time) recovered from the rule bot's paper trades (export trades.csv, read as data: funding / notional for trades that
cross exactly one 00/08/16 UTC funding time), then charged to each pooled row by its own entry / exit minutes at 30x.

    python3 ich_funding.py <trades.csv> <ich_rewalk.csv>"""
import sys
import numpy as np
import pandas as pd
T = pd.read_csv(sys.argv[1], usecols=["symbol", "side", "entry_time", "exit_time", "entry_price", "qty", "funding"])
T = T[T.exit_time.notna()]
H8 = 8 * 3600_000
a = (T.entry_time.to_numpy(np.int64) // H8) + 1          # first funding time index strictly after entry (approx.)
b = (T.exit_time.to_numpy(np.int64) // H8)               # last funding time index <= exit
T["nf"] = b - a + 1
T["fidx"] = a
one = T[(T.nf == 1)].copy()
one["rate_long"] = one.funding / (one.qty * one.entry_price) * np.sign(one.side)   # funding > 0 = paid (cost) ?
print("trades", len(T), "crossing one funding time", len(one), "funding nonzero", int((one.funding != 0).sum()))
R = one.groupby(["symbol", "fidx"]).rate_long.median().rename("rate").reset_index()
R["t"] = pd.to_datetime(R.fidx * H8, unit="ms")
print(R.groupby("symbol").rate.describe().to_string())
oct_ = R[R.t >= "2026-10-15 03:00"]
print("H2 mean rate per 8h by symbol (long pays if > 0):")
print(oct_.groupby("symbol").rate.mean().to_string())
C = pd.read_csv(sys.argv[2])
C = C[~C.twin & (C.mine_why != 3)]
T0 = 1577836800000
ent = T0 + C.e.to_numpy(np.int64) * 60000
ext = ent + C.mine_k.to_numpy(np.int64) * 60000
cost = []
rmap = {(s, f): r for s, f, r in zip(R.symbol, R.fidx, R.rate)}
for coin, s, e0, e1 in zip(C.coin, C.side, ent, ext):
    f = 0.0
    for fi in range(e0 // H8 + 1, e1 // H8 + 1):
        f += s * rmap.get((coin, fi), 0.0)        # long pays +rate, short pays -rate
    cost.append(f)
C["fund_r"] = cost
roe0 = np.maximum(30 * C.mine_r, -1)
roe1 = np.maximum(30 * (C.mine_r - C.fund_r), -1)
print("pooled rows", len(C), "mean ROE funding 0:", round(roe0.mean(), 5), "with recovered funding:", round(roe1.mean(), 5),
      "rows crossing a funding time:", int((C.fund_r != 0).sum()))
