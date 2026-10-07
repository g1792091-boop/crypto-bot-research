"""Verifier: 4h / 1h sizing feasibility at 20x / 30x by account size (bracket MMR depends on notional).
    python3 -I vlev_eq.py <v_tf_all.pkl> <repo>"""
import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
FY, REPO = sys.argv[1:3]
sys.path.insert(0, REPO)
from paperbot.config import v3_settings
from paperbot.margin import BracketTier, Brackets
from paperbot.sizing import size_position
IB = {"BTCUSDT": [(1e12, 50, 0.004, 0.0)], "ETHUSDT": [(1e12, 50, 0.004, 0.0)],
      "SOLUSDT": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
      "DOGEUSDT": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
      "BCHUSDT": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
      "LTCUSDT": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)]}
BRK = {s: Brackets([BracketTier(*t) for t in v]) for s, v in IB.items()}
S = v3_settings()
D = pd.read_pickle(FY)
D = D[D.tf.astype(str).isin(["4h"])][["tf", "coin", "side", "atr_frac"]].copy()
D["sym"] = D.coin.astype(str) + "T"
for eq in (5000.0, 500.0):
    lv = []
    cache = {}
    for s, sd, a in zip(D.sym, D.side, D.atr_frac):
        k = (s, int(sd), round(float(a), 5))
        if k not in cache:
            fill = 100 * (1 + sd * 0.0002)
            d = size_position(S, eq, int(sd), fill, 100 - sd * 2 * a * 100, "best", BRK[s], atr=a * 100, min_notional=5.0)
            cache[k] = d.leverage if d.ok else 0
        lv.append(cache[k])
    D[f"lev_{int(eq)}"] = lv
print(D.groupby("sym").agg(n=("side", "size"), ge20_5000=("lev_5000", lambda x: (x >= 20).mean()), ge20_500=("lev_500", lambda x: (x >= 20).mean())).round(3))
print("ALL", round((D.lev_5000 >= 20).mean(), 3), round((D.lev_500 >= 20).mean(), 3))
