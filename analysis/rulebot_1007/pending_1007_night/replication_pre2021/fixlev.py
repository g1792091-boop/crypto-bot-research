"""Sizing-filter sensitivity: every signal of a cell (no v4 sizing filter) at a fixed 20x ladder geometry, liquidation
ignored (liq_frac 0.99), same entry/stop/ladder/costs. Gross R and net R per signal, week-clustered t.
    python3 -I -B fixlev.py <sig_dir> <tf> <start> <end> <names,comma> <label>
"""
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa
import pandas as pd  # noqa
import repl_sim as S  # noqa

sig, tf, start, end, names, label = sys.argv[1:7]
names = names.split(",")
L = S.sweepsig.lib()
WK = 7 * 86400 * 10 ** 9
slip = S.RB.SETTINGS.slippage_frac
rows = []
for coin in S.COINS:
    z = np.load(os.path.join(sig, f"sig_{tf}_{coin}.npz"))
    b = {k: z[k] for k in ("ts", "o", "h", "l", "c", "atr")}
    n = len(b["ts"])
    f_bar = S.RB.FUNDING_8H * L.tf_minutes(tf) / 480.0
    lo = max(int(np.searchsorted(b["ts"], pd.Timestamp(start).value)), L.warmup_bars(tf))
    n_end = int(np.searchsorted(b["ts"], pd.Timestamp(end).value))
    for nm in names:
        sg = z["s__" + nm]
        idx = np.nonzero(sg[lo:n_end - 1])[0] + lo
        idx = idx[np.isfinite(b["atr"][idx]) & (b["atr"][idx] > 0)]
        side = sg[idx].astype(int)
        lev = np.full(len(idx), 20.0)
        r = S.run_mode(b, idx, side, lev, np.full(len(idx), 0.99), n, f_bar)
        raw = b["o"][idx + 1]
        sf = (raw * slip + 2.0 * b["atr"][idx]) / (raw * (1 + side * slip))
        G = side * (r["exit_px"] / (1 - side * slip) / raw - 1) / sf
        R = r["roe"] / 20.0 / sf
        done = np.isfinite(r["reason"]) & (r["reason"] < 3)
        rows.append(pd.DataFrame(dict(strategy=nm, coin=coin, ts=b["ts"][idx], G=G, R=R, done=done, sf=sf)))
D = pd.concat(rows, ignore_index=True)
D = D[D.done]


def ct(x, cl):
    x = np.asarray(x, float)
    mu = x.mean()
    s = pd.Series(x - mu).groupby(cl).sum().to_numpy()
    se = np.sqrt((s ** 2).sum() * len(s) / max(len(s) - 1, 1)) / len(x)
    return mu, mu / se, len(x)


for nm, g in D.groupby("strategy"):
    a = ct(g.G.to_numpy(), g.ts.to_numpy() // WK)
    b = ct(g.R.to_numpy(), g.ts.to_numpy() // WK)
    print(f"FIX20 {label} {nm}@{tf} all signals n {a[2]} gross {a[0]:+.4f} t {a[1]:.2f} | net {b[0]:+.4f} t {b[1]:.2f} | stop med {g.sf.median():.4f}")
