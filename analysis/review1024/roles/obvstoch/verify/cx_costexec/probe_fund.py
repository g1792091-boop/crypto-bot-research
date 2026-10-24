import sys
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import *
g = grid("BTCUSDT")
f = g["fund"]
nz = np.flatnonzero(f != 0)
t = T0 + nz * MIN
print(len(f), g["n"], g["n_grid"], len(nz))
print(pd.to_datetime(t[-8:], unit="ms"), f[nz[-8:]])
mod = (t % DAY) // MIN
print(pd.Series(mod).value_counts().head(6))
a = (ms("2026-09-01") - T0)//MIN; b=(ms("2026-10-01")-T0)//MIN
print("sept mean rate", f[a:b][f[a:b]!=0].mean(), "events", (f[a:b]!=0).sum())
