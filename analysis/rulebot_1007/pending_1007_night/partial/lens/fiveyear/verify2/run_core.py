"""Run my simulator on core 5-year signals (sample) and compare with the analyst's per-signal pkl.
python3 -I -B run_core.py <sig_dir> <their_out_dir> <tf> <frac> <out_csv> [seed]"""
import os
import sys
import time

sys.path.append('/root/.local/lib/python3.11/site-packages')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import mysim  # noqa: E402

sig_dir, their, tf, frac, out = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5]
seed = int(sys.argv[6]) if len(sys.argv) > 6 else 1
rng = np.random.default_rng(seed)
S0, S1 = pd.Timestamp("2021-08-01").value, pd.Timestamp("2026-09-30").value
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
rows = []
t0 = time.time()
for coin in COINS:
    z = np.load(os.path.join(sig_dir, f"sig_{tf}_{coin}.npz"))
    ts, o, h, l, c, atr = (z[k] for k in ("ts", "o", "h", "l", "c", "atr"))
    n = len(ts)
    cache = {}
    for key in [k for k in z.files if k.startswith("s__")]:
        sg = z[key]
        idx = np.nonzero(sg)[0]
        idx = idx[(ts[idx] >= S0) & (ts[idx] < S1) & (idx + 1 < n)]
        idx = idx[np.isfinite(atr[idx]) & (atr[idx] > 0)]
        if frac < 1:
            idx = idx[rng.random(len(idx)) < frac]
        for i in idx:
            side = int(sg[i])
            raw, a = float(o[i + 1]), float(atr[i])
            k = (side, round(a / raw, 7))
            if k not in cache:
                cache[k] = mysim.lev_for(side, raw, a)
            lev, _ = cache[k]
            if lev == 0:
                rows.append((key[3:], coin, int(ts[i]), side, 0, np.nan, np.nan, abs(raw * (1 + side * mysim.SLIP) - (raw - side * 2 * a)) / (raw * (1 + side * mysim.SLIP)), np.nan, ""))
                continue
            lev, liq = mysim.lev_for(side, raw, a)
            r = mysim.sim_one(o, h, l, c, i, side, a, lev, liq, tf)
            if r is None:
                continue
            ret, gross, sf, held, reason = r
            rows.append((key[3:], coin, int(ts[i]), side, lev, ret, gross, sf, held, reason))
    print(coin, len(rows), f"{time.time()-t0:.0f}s", flush=True)
D = pd.DataFrame(rows, columns=["strategy", "coin", "ts", "side", "lev", "ret", "gross", "stop_frac", "held", "reason"])
D["R"] = D["ret"] / D["stop_frac"]
D["gR"] = D["gross"] / D["stop_frac"]
D["tf"] = tf
D.to_csv(out, index=False)
# compare with the analyst's per-signal file
T = pd.read_pickle(os.path.join(their, f"fy36_{tf}.pkl.gz"))
for col in ("strategy", "coin"):
    T[col] = T[col].astype(str)
M = D.merge(T[["strategy", "coin", "ts", "side", "v4n_lev", "v4n_ret", "v4n_R", "v4n_gross", "stop_frac", "v4n_done"]],
            on=["strategy", "coin", "ts"], how="left", suffixes=("", "_t"))
print("my rows", len(D), "matched", M["v4n_lev"].notna().sum(), "side mismatch", int((M["side"] != M["side_t"]).sum()))
ok = (M["lev"] > 0) & M["v4n_done"].fillna(False).astype(bool)
print("lev agree", float((M.loc[M['v4n_lev'].notna(), 'lev'] == M.loc[M['v4n_lev'].notna(), 'v4n_lev']).mean()))
d = (M.loc[ok, "R"] - M.loc[ok, "v4n_R"]).abs()
print("R |diff| median", d.median(), "p99", d.quantile(0.99), "share>0.01", float((d > 0.01).mean()))
print("my mean R", M.loc[ok, "R"].mean(), "theirs", M.loc[ok, "v4n_R"].mean(), "n", int(ok.sum()))
gt = M.loc[ok, "v4n_gross"] / M.loc[ok, "stop_frac_t"]
print("my gross R", M.loc[ok, "gR"].mean(), "theirs", gt.mean())
print("my all-sized mean R", D.loc[D['lev'] > 0, 'R'].mean(), "gross", D.loc[D['lev'] > 0, 'gR'].mean(), "sized share", float((D['lev'] > 0).mean()))
