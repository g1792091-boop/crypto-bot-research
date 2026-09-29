"""Independent re-computation of selected gate cells from the raw IS CSVs + cached signals.
Own window logic (PREREG section 2), own forward returns, own self-normalised return (A1), and a
brute-force np.roll null using the pre-registered shifts (sweep_lib.gate_shifts is used ONLY for
the shift draw, so that the numbers are comparable).  Descriptive check of the harness."""
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sweep_lib as L  # noqa: E402

DATA = os.path.join(os.path.dirname(HERE), "data", "is")
COINS = L.COINS
cells = [("N13_3OUTSIDE", "4h", 64), ("DOGE_L", "1h", 64), ("N01_ST_EMA", "1d", 64), ("N20_EMA9_CHOP", "1h", 64),
         ("V45_AMB", "1h", 16), ("N17_KC_RSI", "1h", 4), ("S5_DONCHIAN_MFI", "4h", 4), ("N23_HA_ST", "1d", 16)]
gate = pd.read_csv(os.path.join(HERE, "gate_cells.csv"))
out = []
for strat, tf, H in cells:
    sig = L.load_signals(os.path.join(HERE, "out", f"signals_is_{tf}.npz"))[strat]
    m = L.tf_minutes(tf)
    wu = 200 if tf == "1d" else max(300, int(np.ceil(30 * 1440 / m)))
    segs = {}
    for c in COINS:
        df = pd.read_csv(os.path.join(DATA, f"{c.lower()}-{tf}.csv"))
        ts = pd.to_datetime(df.iloc[:, 0], utc=True)
        assert ts.max() < pd.Timestamp("2024-07-01", tz="UTC"), "IS file contains post-IS bar"
        o = df["open"].to_numpy(float)
        idx = np.arange(len(df))
        adm = (ts >= pd.Timestamp("2021-08-01", tz="UTC")).to_numpy() & (idx >= wu) & (idx + 1 + H <= len(df) - 1)
        t = idx[adm]
        assert np.all(np.diff(t) == 1)
        r = o[t + 1 + H] / o[t + 1] - 1
        lo = np.log(o)
        rv = np.array([np.sqrt(np.sum(np.diff(lo[tt + 1: tt + 2 + H]) ** 2)) for tt in t])
        rn = np.where(rv > 0, np.log1p(r) / np.where(rv > 0, rv, 1.0), 0.0)
        segs[c] = (sig[c][t].astype(float), r, rn)
    n = sum(np.abs(d).sum() for d, r, rn in segs.values())
    fwd = sum(d @ r for d, r, rn in segs.values()) / n
    fvn = sum(d @ rn for d, r, rn in segs.values()) / n
    Nmin = min(len(r) for d, r, rn in segs.values())
    sh = L.gate_shifts(tf, H, Nmin, 600)
    null = np.array([sum(np.roll(d, k) @ r for d, r, rn in segs.values()) / n for k in sh])
    nullv = np.array([sum(np.roll(d, k) @ rn for d, r, rn in segs.values()) / n for k in sh])
    z = (fwd - null.mean()) / null.std(ddof=1)
    zv = (fvn - nullv.mean()) / nullv.std(ddof=1)
    eabs = np.mean(np.abs(np.concatenate([r for d, r, rn in segs.values()])))
    mu = 0.0014 + 0.0001 * H * m / 480 + 0.091 * eabs
    g = gate[(gate.strategy == strat) & (gate.tf == tf) & (gate.H == H)].iloc[0]
    out.append(dict(cell=f"{strat} {tf} H{H}", n=n, n_h=g.n, fwd=fwd, fwd_h=g.fwd, z=z, z_h=g.z, z_vn=zv, z_vn_h=g.z_vn,
                    p=norm.sf(z), p_h=g.p, null_sd=null.std(ddof=1), null_sd_h=g.null_sd, mu=mu, mu_h=g.mu_star,
                    eabs=eabs, eabs_h=g.E_abs_r, n_min=Nmin, n_min_h=g.n_min))
pd.set_option("display.width", 300)
pd.set_option("display.max_columns", 40)
r = pd.DataFrame(out)
r.to_csv(os.path.join(HERE, "out", "verify_cells.csv"), index=False)
print(r.to_string(index=False))
for a in ["n", "fwd", "z", "z_vn", "p", "null_sd", "mu", "eabs", "n_min"]:
    print(a, "max abs diff", float(np.max(np.abs(r[a] - r[a + "_h"]))))
