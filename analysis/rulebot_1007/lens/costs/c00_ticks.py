"""Infer each coin's price tick from live_bars (smallest decimal step that every price is a multiple of)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _boot  # noqa
import pandas as pd, numpy as np
B = pd.read_csv(sys.argv[1])
rows = []
for s, g in B.groupby("symbol"):
    px = pd.concat([g[c] for c in ("open", "high", "low", "close")]).to_numpy(float)
    tick = None
    for k in range(0, 9):
        t = 10.0 ** -k
        if np.all(np.abs(px / t - np.round(px / t)) < 1e-6):
            tick = t
            break
    # smallest nonzero diff between distinct prices as a check
    u = np.unique(np.round(px, 9))
    md = np.min(np.diff(u)) if len(u) > 1 else np.nan
    med = float(np.median(g["close"]))
    rows.append({"symbol": s, "tick": tick, "min_diff": md, "median_price": med, "tick_bps": tick / med * 1e4,
                 "median_1m_range_bps": float(np.median((g["high"] - g["low"]) / g["close"])) * 1e4})
D = pd.DataFrame(rows)
print(D.to_string(index=False))
D.to_csv(sys.argv[2], index=False)
