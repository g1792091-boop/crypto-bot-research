#!/usr/bin/env python3
"""C4/C11: 5-year 2ATR stop distribution vs live; live 1m bar ranges.
python3 -I v5_vol.py <signals_dir> <v2_replay_rows.csv> <export_dir>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vboot  # noqa
import numpy as np, pandas as pd
sd, rep, ex = sys.argv[1:4]
R = pd.read_csv(rep)
R = R[R["grp"].isin(["core36", "ds200"])]
for tf in ("15m", "30m", "1h", "4h"):
    allv = []; yrs = []
    for c in ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"):
        z = np.load(os.path.join(sd, f"sig_{tf}_{c}.npz"), allow_pickle=False)
        a, o, ts = z["atr"], z["o"], z["ts"]
        sf = 2 * a[:-1] / o[1:]
        ok = np.isfinite(sf) & (sf > 0)
        allv.append(sf[ok]); yrs.append(pd.to_datetime(ts[:-1][ok]).year)
    v = np.concatenate(allv); y = np.concatenate(yrs)
    live = R.loc[R["timeframe"] == tf, "stop_frac_fill"]
    lm = live.median()
    pct = (v < lm).mean() * 100
    med5 = np.median(v)
    byy = {int(k): round(float(np.median(v[y == k])) * 100, 3) for k in np.unique(y)}
    cost_live = (0.0014 / live).mean(); cost_live_med = 0.0014 / lm; cost_5y_med = 0.0014 / med5
    share_cheap = (0.0014 / v <= 0.10).mean()
    print(tf, f"live n={len(live)} median {lm*100:.3f}% | 5y bars n={len(v)} median {med5*100:.3f}% | live pct {pct:.1f} | cost R live mean {cost_live:.3f} at-live-median {cost_live_med:.3f} at-5y-median {cost_5y_med:.3f} diff {cost_live_med-cost_5y_med:.3f} | share cost<=0.10R {share_cheap:.3f}")
    print("   by year", byy)
# 1m bar range in live bars
for run in ("run-20261005T183457Z", "current"):
    B = pd.read_csv(os.path.join(ex, run, "live_bars.csv"))
    B["rng_bp"] = (B["high"] - B["low"]) / B["open"] * 1e4
    print(run, B.groupby("symbol")["rng_bp"].median().round(2).to_dict())
