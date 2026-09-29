"""Circular-shift null for pooled forward drift (15m IS, 5 symbols).
Same shift for every symbol (keeps cross-symbol co-timing and within-strategy clustering),
signals keep their side.  Family = every (strategy, gated/ungated) with >= 30 signals, horizons 4/16/64.
Reports per-member one-sided p and a family-wise max-z null."""
import os, sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "bt"))
from run import load_csv, window_bounds
from run_gap4 import strategies, GATE

D = os.path.join(HERE, "..", "data")
HZ = (4, 16, 64); REPS = 1000
rng = np.random.default_rng(20260929)
STR = strategies()
syms = ("BTCUSD", "ETHUSD", "SOLUSD", "LTCUSD", "BCHUSD")
data = {}
for sym in syms:
    df = load_csv(os.path.join(D, f"{sym.lower()}-15m-ohlcv.csv"), 15)
    lo, hi = window_bounds(df, "IS"); lo = max(lo, 1000)
    o = df.open.to_numpy(float); c = df.close.to_numpy(float); n = len(o)
    fwd = {}
    for h in HZ:
        i = np.arange(n); e = np.minimum(i + 1, n - 1); j = np.minimum(i + 1 + h, n - 1)
        fwd[h] = (o[j] / o[e] - 1.0)[lo:hi] * 100
    sides = {}
    for name, (fn, var, grp) in STR.items():
        s = fn(df, variant=var)
        L, S = s["L"], s["S"]
        with np.errstate(invalid="ignore"):
            dist = np.where(L, (c - s["stopL"]) / c, np.where(S, (s["stopS"] - c) / c, np.nan))
        g = np.isfinite(dist) & (dist > 0) & (dist <= GATE)
        sd = np.where(L, 1.0, np.where(S, -1.0, 0.0))
        sides[name] = sd[lo:hi]
        sides[name + "|gate0.6"] = np.where(g, sd, 0.0)[lo:hi]
    data[sym] = dict(fwd=fwd, sides=sides, m=hi - lo)
M = min(d["m"] for d in data.values())
names = [k for k in data["BTCUSD"]["sides"] if sum(int((data[s]["sides"][k] != 0).sum()) for s in syms) >= 30]


def pooled_mean(shift):
    out = {}
    for k in names:
        num = {h: 0.0 for h in HZ}; cnt = 0
        for s in syms:
            sd = data[s]["sides"][k]
            if shift:
                sd = np.roll(sd, shift % len(sd))
            idx = np.nonzero(sd)[0]
            cnt += len(idx)
            for h in HZ:
                num[h] += float(np.sum(sd[idx] * data[s]["fwd"][h][idx]))
        for h in HZ:
            out[(k, h)] = num[h] / cnt if cnt else np.nan
    return out


obs = pooled_mean(0)
null = {key: [] for key in obs}
for r in range(REPS):
    sh = int(rng.integers(500, M - 500))
    pm = pooled_mean(sh)
    for key, v in pm.items():
        null[key].append(v)
rows = []
Z = []
for key in obs:
    nv = np.array(null[key]); mu, sdv = nv.mean(), nv.std(ddof=1)
    rows.append(dict(strategy=key[0], h=key[1], obs=obs[key], null_mean=mu, null_sd=sdv, z=(obs[key] - mu) / sdv,
                     p_one=float((np.sum(nv >= obs[key]) + 1) / (len(nv) + 1))))
    Z.append((nv - mu) / sdv)
R = pd.DataFrame(rows).sort_values("z", ascending=False)
Zm = np.nanmax(np.vstack(Z), axis=0)  # family-wise max-z per rep
R["p_family"] = [float((np.sum(Zm >= z) + 1) / (len(Zm) + 1)) for z in R.z]
pd.set_option("display.width", 200)
print(f"family members: {len(names)} strategies x {len(HZ)} horizons = {len(R)} ; reps {REPS}")
print(R.head(15).round(4).to_string(index=False))
sel = R[R.strategy.isin(["N13_3OUTSIDE|gate0.6", "N16_BBRSI|gate0.6", "N13_3OUTSIDE", "S5_DONCHIAN_MFI", "N09_ALLIG_AROON",
                         "N20_EMA9_CHOP", "N17_KC_RSI"])]
print(sel.sort_values(["strategy", "h"]).round(4).to_string(index=False))
R.to_csv(os.path.join(HERE, "out", "fwd_null.csv"), index=False)
