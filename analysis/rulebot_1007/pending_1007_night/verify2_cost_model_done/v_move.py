"""Move-trigger frequency per hour held, every replayed TRADED signal (v3b+v4, core+ds), 1m live bars.
python3 -I v_move.py <replay_signals.csv> <export_dir>"""
import sys, os, csv, collections
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REP, EXP = sys.argv[1:3]
RUNS = {"run-20261005T183457Z": "run-20261005T183457Z", "current": "current"}
def load_bars(p):
    d = collections.defaultdict(list)
    with open(os.path.join(p, "live_bars.csv")) as fh:
        h = fh.readline().strip().split(","); it, isym, ih, il, ic = (h.index(x) for x in ("ts", "symbol", "high", "low", "close"))
        for line in fh:
            v = line.rstrip("\n").split(","); d[v[isym]].append((int(v[it]), float(v[ih]), float(v[il]), float(v[ic])))
    return {s: tuple(np.array(sorted(set(L)))[:, i] for i in range(4)) for s, L in d.items()}
B = {k: load_bars(os.path.join(EXP, v)) for k, v in RUNS.items()}
acc = collections.defaultdict(lambda: np.zeros(7)); n = collections.Counter()
for r in csv.DictReader(open(REP)):
    if r["run"] not in RUNS or r["status"] != "TRADED" or r["kind"] not in ("strategy", "ds200"): continue
    ts, hi, lo, cl = B[r["run"]][r["symbol"]]
    t0, t1 = float(r["entry_time"]), float(r["exit_time"]); e = float(r["entry_price"]); R = abs(e - float(r["stop_initial"]))
    i0, i1 = np.searchsorted(ts, t0), np.searchsorted(ts, t1)
    out = []
    for k, mode, cd in ((0.5, "close", 0), (0.5, "step", 0), (0.75, "close", 0), (1.0, "close", 0), (1.0, "step", 0), (0.5, "close", 15)):
        ref = e; c = 0; last = -1e18; thr = k * R
        for i in range(i0, i1):
            up, dn = hi[i] - ref, ref - lo[i]
            if up >= thr or dn >= thr:
                if ts[i] - last >= cd * 60000: c += 1; last = ts[i]
                if mode == "close": ref = cl[i]
                else: ref = ref + thr * np.floor(up / thr) if up >= thr else ref - thr * np.floor(dn / thr)
        out.append(c)
    hours = (t1 - t0) / 3.6e6
    acc[r["timeframe"]] += np.array(out + [hours]); n[r["timeframe"]] += 1
for tf in ("15m", "30m", "1h", "4h"):
    a = acc[tf]; print(tf, n[tf], "hours", round(a[6], 1), "per hour: 0.5R close %.2f | 0.5R step %.2f | 0.75R %.2f | 1.0R close %.2f | 1.0R step %.2f | 0.5R 15min-cooldown %.2f" % tuple(a[:6] / a[6]))
