"""Path-resolution check: the same 5-year 15m/30m/1h signals simulated on their own bars vs on 5m bars (closer to live,
which steps the engine every 1m). python3 -I -B finebar.py <sig_dir> <tf> <frac> <out_csv>"""
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import mysim  # noqa: E402

sig_dir, tf, frac, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
rng = np.random.default_rng(7)
S0, S1 = pd.Timestamp("2021-08-01").value, pd.Timestamp("2026-09-30").value
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
TFNS = mysim.TFMIN[tf] * 60 * 10 ** 9
rows = []
for coin in COINS:
    z = np.load(os.path.join(sig_dir, f"sig_{tf}_{coin}.npz"))
    f = np.load(os.path.join(sig_dir, f"sig_5m_{coin}.npz"))
    ts, o, h, l, c, atr = (z[k] for k in ("ts", "o", "h", "l", "c", "atr"))
    fts, fo, fh, fl, fc = (f[k] for k in ("ts", "o", "h", "l", "c"))
    for key in [k for k in z.files if k.startswith("s__")]:
        sg = z[key]
        idx = np.nonzero(sg)[0]
        idx = idx[(ts[idx] >= S0) & (ts[idx] < S1) & (idx + 1 < len(ts))]
        idx = idx[np.isfinite(atr[idx]) & (atr[idx] > 0)]
        idx = idx[rng.random(len(idx)) < frac]
        for i in idx:
            side, raw, a = int(sg[i]), float(o[i + 1]), float(atr[i])
            lev, liq = mysim.lev_for(side, raw, a)
            if lev == 0:
                continue
            r1 = mysim.sim_one(o, h, l, c, i, side, a, lev, liq, tf)
            # 5m path: the bar index whose next bar opens at the signal tf bar's next open
            j = int(np.searchsorted(fts, ts[i + 1]))
            if j >= len(fts) or fts[j] != ts[i + 1] or abs(fo[j] / raw - 1) > 1e-9:
                continue
            r2 = mysim.sim_one(fo, fh, fl, fc, j - 1, side, a, lev, liq, "5m", maxbars=200000)
            if r1 is None or r2 is None:
                continue
            rows.append((key[3:], coin, int(ts[i]), side, lev, r1[0] / r1[2], r2[0] / r2[2], r1[1] / r1[2], r2[1] / r2[2], r1[4], r2[4]))
    print(coin, len(rows), flush=True)
D = pd.DataFrame(rows, columns=["strategy", "coin", "ts", "side", "lev", "R_tf", "R_5m", "gR_tf", "gR_5m", "why_tf", "why_5m"])
D.to_csv(out, index=False)
d = D["R_5m"] - D["R_tf"]
wk = (D["ts"] // (86400 * 10 ** 9) + 3) // 7
s = pd.Series(d - d.mean()).groupby(wk).sum()
se = np.sqrt((s ** 2).sum()) / len(d)
print(tf, "n", len(D), "mean R tf-bars", D["R_tf"].mean(), "5m-bars", D["R_5m"].mean(), "diff", d.mean(), "week-cl se", se,
      "gross tf", D["gR_tf"].mean(), "gross 5m", D["gR_5m"].mean())
print(pd.crosstab(D["why_tf"], D["why_5m"]))
