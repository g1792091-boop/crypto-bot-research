"""Print two taken trades by hand from the raw 1m grid: the higher bar used, its OBV vs SMA30, entry, exit.
Run: python3 vla_show.py <trades_dir>"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "data"))
from common import *  # noqa
TD = sys.argv[1]
T = pd.read_csv(os.path.join(TD, "trades_B6.csv.gz"))
T = T[(T.t >= ms("2025-03-01")) & (T.t < ms("2025-04-01"))]
for _, r in pd.concat([T[T.tb_why == 0].head(1), T[T.tb_why == 1].head(1)]).iterrows():
    coin = COINS[int(r.coin)]
    g = grid(coin)
    htf = {"30m": "1h", "1h": "4h", "4h": "1d"}[r.tf]
    k = TF_MIN[htf]
    # last closed higher bar: minutes [b0, b0+k) with b0 + k <= e
    e = int(r.e)
    b0 = (e // k - 1) * k
    # rebuild the 30 previous higher bars' OBV from raw minutes (OBV over a long span: 400 bars)
    nb = 400
    starts = b0 - np.arange(nb)[::-1] * k
    cl = np.array([g["c"][s + k - 1] for s in starts])
    vo = np.array([np.nansum(g["v"][s:s + k]) for s in starts])
    obv = np.r_[0, np.cumsum(np.sign(np.diff(cl)) * vo[1:])]
    sma30 = obv[-30:].mean()
    lev = 40.0 if r.coin == 0 else 30.0
    p0 = g["o"][e]
    x = e + int(r.tb_k)
    print(f"{coin} {r['name']}@{r.tf} side {int(r.side):+d} signal close {kst(int(r.t))} KST; {htf} bar used "
          f"{kst(T0 + b0 * MIN)}..{kst(T0 + (b0 + k) * MIN)} KST (closes {(e - b0 - k)} min before entry); "
          f"OBV {obv[-1]:.0f} vs SMA30 {sma30:.0f} -> {int(np.sign(obv[-1] - sma30)):+d}, file j_dir {int(r.j_dir):+d}")
    side = int(r.side)
    stop_px = p0 * (1 - side * (0.5 / lev - COST))
    print(f"   entry o[e]={p0}, -50% net stop price ~{stop_px:.6g}; exit minute {kst(T0 + x * MIN)} KST "
          f"o/h/l/c {g['o'][x]}/{g['h'][x]}/{g['l'][x]}/{g['c'][x]}; why {int(r.tb_why)} roe {r.tb_roe:+.4f}")
    lo = np.nanmin(g["l"][e:x]) if side > 0 else np.nanmax(g["h"][e:x])
    print(f"   worst price before the exit minute {lo} (stop not touched earlier: {(lo > stop_px) if side > 0 else (lo < stop_px)})")
