"""How fast does each policy hit a -20 % drawdown from the start / from the peak when the true edge is 0 or small?
Moving-block bootstrap (block 10 d) of 1-year paths from out/base daily series. Reports P(hit within 30/90/365 d) and
median days to hit, and the equity at which a -20 %-from-peak kill switch would stop the account (median over paths)."""
import json, os
import numpy as np
import pandas as pd

rng = np.random.default_rng(11)
rows = []
for tf in ["5m", "15m", "1h", "4h", "1d"]:
    d = "out/base"
    meta = json.load(open(os.path.join(d, f"{tf}_meta.json")))
    daily = np.load(os.path.join(d, f"{tf}_daily.npy"), mmap_mode="r")
    dmin = np.load(os.path.join(d, f"{tf}_dmin.npy"), mmap_mode="r")
    E, C, S, D = daily.shape
    T, B, NP = 365, 10, 4000
    nb = -(-T // B)
    s0 = rng.integers(0, S, size=(NP, nb)); d0 = rng.integers(0, D, size=(NP, nb))
    sidx = np.repeat(s0, B, axis=1)[:, :T]
    didx = ((d0[:, :, None] + np.arange(B)[None, None, :]) % D).reshape(NP, -1)[:, :T]
    for e_val in [0.0, 0.001, 0.002]:
        e = [i for i, x in enumerate(meta["edges"]) if abs(x - e_val) < 1e-12][0]
        for c in ["P0|B|10", "P3|A|10", "P3|C|10", "P4|A|10", "P5|A|10", "P6|B|none", "P6h|B|none"]:
            j = meta["combos"].index(c)
            X = np.asarray(daily[e, j])[sidx, didx].astype(np.float64)
            Mn = np.asarray(dmin[e, j])[sidx, didx]
            cum = np.cumsum(X, axis=1); low = cum - X + Mn
            peak = np.maximum(np.maximum.accumulate(cum, axis=1), 0.0)
            peak_prev = np.concatenate([np.zeros((NP, 1)), peak[:, :-1]], axis=1)
            dd = low - peak_prev                                  # log drawdown from running peak (intraday)
            hit = dd <= np.log(0.8)
            first = np.where(hit.any(1), hit.argmax(1) + 1, 10**6)
            # equity when the kill switch fires (approx: the intraday low of the day it fires, relative to start)
            eq_at = np.where(first < 10**6, np.exp(low[np.arange(NP), np.minimum(first - 1, T - 1)]), np.nan)
            rows.append(dict(tf=tf, edge_pct=e_val * 100, combo=c,
                             p_dd20_30d=np.mean(first <= 30), p_dd20_90d=np.mean(first <= 90), p_dd20_1y=np.mean(first <= 365),
                             median_days_to_dd20=float(np.median(first)) if np.mean(first <= 365) >= 0.5 else np.nan,
                             median_equity_when_fired=float(np.nanmedian(eq_at)) if np.isfinite(eq_at).any() else np.nan))
df = pd.DataFrame(rows)
df.to_csv("out/killswitch.csv", index=False)
print(df.to_string(index=False, float_format=lambda v: f"{v:.3g}"))
