"""verify3: my own per-signal house-exit simulator (written from paperbot/ladder.py docstring + engine semantics).
Sampled per-row parity vs the lens pickles.  python3 -I -B v3sim.py <sigdir> <their_out> <tf> <n> <outcsv>
"""
import math
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
sys.path.insert(0, '/home/user/crypto-bot-research')
import numpy as np  # noqa
import pandas as pd  # noqa
from paperbot.config import v3_settings  # noqa
from paperbot.sizing import size_position  # noqa
from paperbot.margin import Brackets  # noqa

ST = v3_settings()
BR = Brackets.example()
SL, FEE = ST.slippage_frac, ST.taker_fee
RT = 2 * (SL + FEE)
MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


def lock(best):
    if best < 0.12 - 1e-12:
        return None
    return 0.10 + 0.05 * math.floor((best - 0.12) / 0.05 + 1e-9)


def sim(o, h, l, i, side, atr, tf):
    raw = o[i + 1]
    fill = raw * (1 + side * SL)
    stop = raw - side * 2 * atr
    d = size_position(ST, 5000.0, side, fill, stop, "normal", BR, atr=atr, min_notional=5.0)
    if not d.ok:
        return 0, np.nan, np.nan, np.nan
    lev, liq = d.leverage, d.liq_price
    sf = abs(fill - stop) / fill
    fb = 0.0001 * MIN[tf] / 480
    best = fill
    lk = None
    for k, j in enumerate(range(i + 1, min(len(o), i + 6000))):
        fu = fb * (k + 1)
        px = None
        if k > 0 and side * (o[j] - stop) <= 0:
            px = o[j]
        elif (l[j] <= stop if side > 0 else h[j] >= stop):
            px = stop
        if px is not None:
            ex = px * (1 - side * SL)
            ret = side * (ex / fill - 1) - FEE - FEE * ex / fill - fu
            ret = max(ret, -1 / lev)
            return lev, ret / sf, side * (px / raw - 1) / sf, sf
        if (l[j] <= liq if side > 0 else h[j] >= liq):
            return lev, -1 / lev / sf, np.nan, sf
        best = max(best, h[j]) if side > 0 else min(best, l[j])
        nl = lock(lev * (side * (best / fill - 1) - RT - fu))
        if nl is not None and (lk is None or nl > lk + 1e-12):
            lk = nl
            c = fill * (1 + side * (nl / lev + RT + fu))
            stop = max(stop, c) if side > 0 else min(stop, c)
    return lev, np.nan, np.nan, sf


def main(sigdir, their, tf, n, out, kind="fy36"):
    T = pd.read_pickle(os.path.join(their, f"{kind}_{tf}.pkl.gz"))
    T = T[T.v4n_lev > 0]
    smp = T.sample(int(n), random_state=7)
    rows = []
    for coin, g in smp.groupby("coin", observed=True):
        z = np.load(os.path.join(sigdir, f"sig_{tf}_{coin}.npz"))
        ts, o, h, l, a = z["ts"], z["o"], z["h"], z["l"], z["atr"]
        pos = np.searchsorted(ts, g.ts.to_numpy())
        for (_, r), i in zip(g.iterrows(), pos):
            if kind == "fy36":
                atr = a[i]
            else:   # DS: ATR14 (Wilder RMA of TR) of the signal bar, my own computation
                atr = np.nan
            lev, R, gR, sf = sim(o, h, l, i, int(r.side), atr, tf) if np.isfinite(atr) else (0, np.nan, np.nan, np.nan)
            rows.append(dict(strategy=r.strategy, coin=coin, ts=r.ts, lev_t=r.v4n_lev, R_t=r.v4n_R,
                             g_t=r.v4n_gross / r.stop_frac, sf_t=r.stop_frac, lev=lev, R=R, gR=gR, sf=sf))
    D = pd.DataFrame(rows)
    D.to_csv(out, index=False)
    ok = D.R.notna() & D.R_t.notna()
    print(tf, kind, "n", len(D), "both", ok.sum(), "lev agree", (D.lev == D.lev_t).mean(),
          "|dR|>1e-3 share", (abs(D.R - D.R_t)[ok] > 1e-3).mean(), "my mean R", D.R[ok].mean(), "theirs", D.R_t[ok].mean(),
          "my gR", D.gR.mean(), "their gR", D.g_t.mean())


if __name__ == "__main__":
    main(*sys.argv[1:6])
