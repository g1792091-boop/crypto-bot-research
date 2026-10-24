"""One-position account, needed per-trade ROE and a 30-day day-block bootstrap, recomputed from the INDEPENDENT rows
(indep_rows.csv, variant ok) without the study's helpers."""
import numpy as np, pandas as pd, json
def ms(s): return int(pd.Timestamp(s, tz="UTC").value // 10**6)
DAY = 86_400_000
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
PB = 2 * 0.9 * 0.00042 * 30
a, b = ms("2024-01-01"), ms("2026-10-23")
I = pd.read_csv("indep_rows.csv")
X = I[(I["var"] == "ok") & (I.t_ms >= a) & (I.t_ms < b) & (I.why != 3) & (I.why_opp != 3)].copy()
X["ci"] = X.coin.map({c: i for i, c in enumerate(COINS)})
X = X.sort_values(["t_ms", "ci"]).reset_index(drop=True)
busy = -1; took = []
for r in X.itertuples():
    e = r.t_ms // 60000
    if e > busy:
        took.append(r.Index); busy = e + r.k
T = X.loc[took]
days = (b - a) / DAY
out = {"signals": len(X), "taken": len(T), "per_day": len(T) / days}
for pb in (False, True):
    roe = np.maximum(T.roe.to_numpy() + (PB if pb else 0), -1.0)
    for f in (0.1, 0.4):
        eq = np.cumprod(1 + f * roe); pk = np.maximum.accumulate(np.r_[1.0, eq])[1:]
        out[f"pb{int(pb)}_m{f}"] = {"mean_roe": float(roe.mean()), "final_x": float(eq[-1]), "max_dd": float((1 - eq / pk).max())}
    # needed delta for the median 30-day path to reach x6 at 40 % margin
    n30 = len(T) / days * 30
    lo, hi = -0.5, 5.0
    for _ in range(80):
        mid = (lo + hi) / 2
        g = np.mean(np.log(np.maximum(1 + 0.4 * np.maximum(roe + mid, -1.0), 1e-12)))
        lo, hi = (lo, mid) if n30 * g >= np.log(6) else (mid, hi)
    out[f"pb{int(pb)}_needed_mean_roe_m40"] = float(roe.mean() + hi)
    # day-block bootstrap 30 days, 4000 paths, margin 40 %
    d = T.t_ms.to_numpy() // DAY
    lo_d, hi_d = a // DAY, (b - 1) // DAY
    by = [roe[d == x] for x in range(lo_d, hi_d + 1)]
    rng = np.random.default_rng(7)
    hit = l50 = 0; fin = []
    for _ in range(4000):
        eq = 1.0; done = False; h50 = False
        for di in rng.integers(0, len(by), 30):
            for x in by[di]:
                eq *= 1 + 0.4 * x
                if not done and eq >= 6: hit += 1; done = True
                if not done and not h50 and eq <= 0.5: l50 += 1; h50 = True
        fin.append(eq)
    out[f"pb{int(pb)}_boot_m40"] = {"p_x6": hit / 4000, "p_lose50_first": l50 / 4000, "median_x": float(np.median(fin)),
                                     "p_x6_ever_max_path": None}
print(json.dumps(out, indent=1))
json.dump(out, open("vaccount.json", "w"), indent=1)
