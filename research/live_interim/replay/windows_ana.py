"""From the backtest (36 core x 4 tf, default numbers, live exit, 2021-01 .. 2026-09):
1. per timeframe, the pooled mean per trade over every 6-day window -> where the live 6 days sit;
2. share of cells up in a 6-day window;
3. does a cell's 6-day result predict its next 30 days? (Spearman across cells; top-10 by 6 days vs the rest)."""
import json
import sys

import numpy as np
from scipy.stats import spearmanr

D = 86_400_000
rows = json.load(open(sys.argv[1]))
LIVE = {"15m": -0.0126, "30m": 0.0005, "1h": 0.0013, "4h": 0.0092}
WIN = int(sys.argv[2]) if len(sys.argv) > 2 else 6
cells = []
for name, tf, close, x, pid, coin, side in rows:
    close, x, pid = np.array(close, np.int64), np.array(x, float), np.array(pid)
    m = ((pid == 0) | (pid == 1)) & np.isfinite(x)
    o = np.argsort(close[m], kind="stable")          # trades are stored coin by coin; windows need time order
    cells.append((name, tf, close[m][o], x[m][o]))
t0 = min(c[2].min() for c in cells if len(c[2]))
t1 = max(c[2].max() for c in cells if len(c[2]))
starts = np.arange(t0, t1 - (WIN + 30) * D, D)
print(f"window {WIN} days, {len(starts)} windows, {np.datetime64(int(t0), 'ms')} .. {np.datetime64(int(t1), 'ms')}")
res = {"win": WIN, "tf": {}}
for tf in ("15m", "30m", "1h", "4h"):
    cs = [c for c in cells if c[1] == tf]
    allc = np.concatenate([c[2] for c in cs])
    allx = np.concatenate([c[3] for c in cs])
    o = np.argsort(allc)
    allc, allx = allc[o], allx[o]
    cs_sum = np.concatenate([[0], np.cumsum(allx)])
    lo = np.searchsorted(allc, starts)
    hi = np.searchsorted(allc, starts + WIN * D)
    n = hi - lo
    ok = n >= 5
    means = (cs_sum[hi] - cs_sum[lo])[ok] / n[ok]
    ups = []
    for s in starts[::3]:
        u = t = 0
        for c in cs:
            a, b = np.searchsorted(c[2], [s, s + WIN * D])
            if b > a:
                t += 1
                u += c[3][a:b].sum() > 0
        if t:
            ups.append(u / t)
    q = np.percentile(means, [5, 25, 50, 75, 95])
    share = float((means >= LIVE[tf]).mean())
    res["tf"][tf] = {"windows": int(ok.sum()), "p5_p25_p50_p75_p95": [float(v) for v in q], "share_ge_live": share,
                     "positive_share": float((means > 0).mean()), "cells_up_median": float(np.median(ups)),
                     "cells_up_p10_p90": [float(np.percentile(ups, 10)), float(np.percentile(ups, 90))]}
    print(tf, f"windows {ok.sum()}", "pct 5/25/50/75/95:", " ".join(f"{v*100:+.2f}%" for v in q),
          f"| share >= live {LIVE[tf]*100:+.2f}%: {share*100:.0f}% | windows > 0: {(means > 0).mean()*100:.0f}%",
          f"| cells up median {np.median(ups)*100:.0f}% (p10 {np.percentile(ups,10)*100:.0f}% p90 {np.percentile(ups,90)*100:.0f}%)")
# 3. prediction: 6-day mean -> next 30-day mean, across all 144 cells
rhos, top_next, all_next, top_pct = [], [], [], []
for s in starts[::7]:
    a6, n30 = [], []
    for name, tf, c, x in cells:
        a, b = np.searchsorted(c, [s, s + WIN * D])
        b2 = np.searchsorted(c, s + (WIN + 30) * D)
        if b - a >= 3 and b2 - b >= 5:
            a6.append(x[a:b].mean())
            n30.append(x[b:b2].mean())
    if len(a6) < 20:
        continue
    a6, n30 = np.array(a6), np.array(n30)
    rhos.append(spearmanr(a6, n30)[0])
    top = np.argsort(-a6)[:10]
    top_next.append(n30[top].mean())
    all_next.append(n30.mean())
    r = (np.argsort(np.argsort(n30)) + 1) / len(n30)
    top_pct.append(r[top].mean())
res["predict"] = {"periods": len(rhos), "rho_mean": float(np.mean(rhos)), "rho_p10_p90": [float(np.percentile(rhos, 10)), float(np.percentile(rhos, 90))],
                  "top10_next30_mean": float(np.mean(top_next)), "all_next30_mean": float(np.mean(all_next)),
                  "top10_next30_rank_pct": float(np.mean(top_pct)),
                  "top10_beats_all_share": float(np.mean(np.array(top_next) > np.array(all_next)))}
print("predict:", json.dumps(res["predict"]))
json.dump(res, open(sys.argv[1].replace(".json", f"_win{WIN}.json"), "w"), indent=1)
