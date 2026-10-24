"""After PREREG8: every DOGE signal of the owners' manual style (frmanual2: 35x, screen +10 % / -20 %, 1h or 4h) from 10/21 00:00 KST to
the data end, with each one's result; the owners took two of them by hand (10/21 20:15, 10/23 00:00) and the replay closes them at the
same minutes as their exchange history (22:01-22:02, 00:07).

    python3 -I frdoge.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frfamily import signals
from frmanual2 import run, LEV, REFUND
A = signals("15m"); R = A.reset_index(drop=True)
r, k = run(R, True)
a, z = ms("2026-10-21") - KST, DATA_END
m = ((R.coin == COINS.index("DOGEUSDT")) & (R.t >= a) & (R.t < z)).to_numpy()
def kst(x): return str(pd.Timestamp(int(x) + KST, unit="ms"))[5:16]
w = 0
for i in np.flatnonzero(m):
    roe = LEV * r[i] + REFUND
    w += roe > 0
    print(kst(R.t.iat[i]), "롱" if R.side.iat[i] > 0 else "숏", f"{roe * 100:+.1f}%", "→", kst(R.t.iat[i] + (k[i] + 1) * MIN), R.block.iat[i] or "")
print("DOGE signals", int(m.sum()), "wins", int(w))
