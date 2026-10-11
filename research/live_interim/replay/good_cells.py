"""For each live cell that looks good after 6 days: its own 5-year record (default numbers, live exit, per signal),
how often it had a 6-day stretch at least this good, and what the next 30 days brought after those stretches.
Also the pooled 'hot week' test over all 144 cells."""
import json
import sys

import numpy as np

D = 86_400_000
WIN = 6
rows = json.load(open(sys.argv[1]))
live = json.load(open(sys.argv[2]))["core"]
rep = json.load(open(sys.argv[3]))
cells = {}
for name, tf, close, x, pid, coin, side in rows:
    close, x, pid, side = (np.array(close, np.int64), np.array(x, float), np.array(pid), np.array(side))
    m = ((pid == 0) | (pid == 1)) & np.isfinite(x)
    o = np.argsort(close[m])
    cells[f"{name}@{tf}"] = (close[m][o], x[m][o], side[m][o], pid[m][o])
t0 = min(c[0][0] for c in cells.values() if len(c[0]))
t1 = max(c[0][-1] for c in cells.values() if len(c[0]))
starts = np.arange(t0, t1 - (WIN + 30) * D, D)
YEARS = (t1 - t0) / (365.25 * D)


def episodes(c, x, thr, nmin=3):
    """Greedy non-overlapping 6-day stretches with mean >= thr (n >= nmin); returns (start, next30 mean, next30 sum, n30)."""
    out, last = [], -10 ** 18
    a = np.searchsorted(c, starts)
    b = np.searchsorted(c, starts + WIN * D)
    b2 = np.searchsorted(c, starts + (WIN + 30) * D)
    cs = np.r_[0, np.cumsum(x)]
    for s, i, j, k in zip(starts, a, b, b2):
        n = j - i
        if n < nmin or s < last + WIN * D:
            continue
        if (cs[j] - cs[i]) / n >= thr:
            n30 = k - j
            out.append((int(s), (cs[k] - cs[j]) / n30 if n30 else np.nan, cs[k] - cs[j], int(n30)))
            last = s
    return out


def windows_share(c, x, thr, nmin=3):
    a = np.searchsorted(c, starts)
    b = np.searchsorted(c, starts + WIN * D)
    cs = np.r_[0, np.cumsum(x)]
    n = b - a
    ok = n >= nmin
    mean = np.where(ok, (cs[b] - cs[a]) / np.maximum(n, 1), np.nan)
    return float(np.nanmean(mean >= thr) if ok.any() else np.nan), int(ok.sum())


# replay sides per cell in the live window
D0, END = rep["live_d0"], rep["end"]
rside = {}
for c in rep["cells"]:
    sig = [s for s in c["signals"] if D0 <= s[0] < END]
    lo = [s[3] for s in sig if s[2] > 0]
    sh = [s[3] for s in sig if s[2] < 0]
    rside[f"{c['name']}@{c['tf']}"] = {"long_n": len(lo), "long_mean": float(np.mean(lo)) if lo else None,
                                       "short_n": len(sh), "short_mean": float(np.mean(sh)) if sh else None,
                                       "acct_final": c["account"]["final_x"] * 5000, "acct_n": c["account"]["trades"]}
good = sorted([k for k, v in live.items() if v["n"] >= 3 and v["wallet"] >= 5500], key=lambda k: -live[k]["wallet"])
res = {"years": YEARS, "cells": {}}
for k in good:
    c, x, side, pid = cells[k]
    lv = live[k]
    test = x[pid == 1]
    yrs = {}
    for y in range(2021, 2027):
        lo_, hi_ = np.datetime64(f"{y}-01-01").astype("datetime64[ms]").astype(np.int64), np.datetime64(f"{y + 1}-01-01").astype("datetime64[ms]").astype(np.int64)
        xs = x[(c >= lo_) & (c < hi_)]
        yrs[y] = float(xs.sum()) if len(xs) else None
    ep = episodes(c, x, lv["mean"])
    nxt = [e for e in ep if e[3] >= 3]
    share, nw = windows_share(c, x, lv["mean"])
    allnext = []  # unconditional 30-day mean for comparison
    a = np.searchsorted(c, starts + WIN * D)
    b = np.searchsorted(c, starts + (WIN + 30) * D)
    cs = np.r_[0, np.cumsum(x)]
    for i, j in zip(a, b):
        if j - i >= 3:
            allnext.append((cs[j] - cs[i]) / (j - i))
    res["cells"][k] = {
        "live": lv, "replay": rside.get(k),
        "five_year": {"n": int(len(x)), "mean": float(x.mean()), "win": float((x > 0).mean()),
                      "test_mean": float(test.mean()) if len(test) else None, "sum": float(x.sum()),
                      "years_sum": yrs, "years_pos": sum(1 for v in yrs.values() if v is not None and v > 0),
                      "long_mean": float(x[side > 0].mean()) if (side > 0).any() else None,
                      "short_mean": float(x[side < 0].mean()) if (side < 0).any() else None},
        "like_this": {"window_share": share, "windows": nw, "episodes": len(ep), "per_year": len(ep) / YEARS,
                      "next30_mean_after": float(np.nanmean([e[1] for e in nxt])) if nxt else None,
                      "next30_pos_share": float(np.mean([e[2] > 0 for e in nxt])) if nxt else None,
                      "next30_unconditional": float(np.mean(allnext)) if allnext else None,
                      "n_followed": len(nxt)}}
# pooled hot-week test: any cell, 6-day mean >= +1% per trade with >= 3 trades
after, base = [], []
for k, (c, x, side, pid) in cells.items():
    if len(x) < 30:
        continue
    for e in episodes(c, x, 0.01):
        if e[3] >= 3:
            after.append(e[1])
    a = np.searchsorted(c, starts + WIN * D)
    b = np.searchsorted(c, starts + (WIN + 30) * D)
    cs = np.r_[0, np.cumsum(x)]
    for i, j in zip(a, b):
        if j - i >= 3:
            base.append((cs[j] - cs[i]) / (j - i))
res["hot_week_pooled"] = {"episodes": len(after), "next30_mean": float(np.mean(after)), "next30_pos": float(np.mean(np.array(after) > 0)),
                          "base_next30_mean": float(np.mean(base)), "base_pos": float(np.mean(np.array(base) > 0))}
json.dump(res, open(sys.argv[4], "w"), indent=1, default=float)
print(json.dumps(res["hot_week_pooled"]))
for k, v in res["cells"].items():
    f, lt = v["five_year"], v["like_this"]
    r = v["replay"] or {}
    print(f"{k:22s} live {v['live']['n']:>2}건 {v['live']['mean']*100:+5.1f}% ${v['live']['wallet']:,.0f} | replay ${r.get('acct_final',0):,.0f}({r.get('acct_n')}) "
          f"L{r.get('long_n')} {('%+.1f%%' % (r['long_mean']*100)) if r.get('long_mean') is not None else '—'} S{r.get('short_n')} {('%+.1f%%' % (r['short_mean']*100)) if r.get('short_mean') is not None else '—'} | "
          f"5y {f['n']}건 {f['mean']*100:+.2f}% test {f['test_mean']*100 if f['test_mean'] is not None else float('nan'):+.2f}% yrs+ {f['years_pos']}/6 L {f['long_mean']*100:+.2f}% S {f['short_mean']*100:+.2f}% | "
          f"like-this {lt['per_year']:.1f}/yr ({lt['window_share']*100:.0f}% win) next30 {lt['next30_mean_after']*100 if lt['next30_mean_after'] is not None else float('nan'):+.2f}% (pos {lt['next30_pos_share']*100 if lt['next30_pos_share'] is not None else float('nan'):.0f}%) vs {lt['next30_unconditional']*100:+.2f}%")
