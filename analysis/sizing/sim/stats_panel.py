import sys, time, json
import numpy as np
from simlib import *
out = {}
for tf in sys.argv[1:]:
    t0 = time.time()
    P = Panel(tf)
    rows = {}
    for c in COINS:
        d = P.coin[c]
        ok = d["ok"]
        rng_ = (d["h"] - d["l"]) / d["c"]
        med = np.nanmedian(rng_[ok])
        rows[c] = dict(n_ok=int(ok.sum()), atr_med=round(P.atr_med[c]*100, 3), Eabs_rH=round(P.Eabs[c]*100, 3),
                       range_med=round(med*100, 3), frac_range_gt_10x_med=round(float(np.mean(rng_[ok] > 10*med)), 5),
                       max_range=round(float(np.nanmax(rng_[ok]))*100, 2))
    out[tf] = dict(H=P.H, lam=P.lam, grid=len(P.grid), ndays=P.ndays, Eabs_pooled=round(P.Eabs_pooled*100, 3), coins=rows,
                   sec=round(time.time()-t0, 1))
    print(tf, json.dumps(out[tf], indent=0))
json.dump(out, open(f"out_panel_stats_{'_'.join(sys.argv[1:])}.json", "w"), indent=1)
