"""Cache-write count for the shared market bundle (5-minute TTL, 15-minute versions), live v4 call timestamps.
python3 -I v_cache.py <replay_signals.csv> <export_dir>
Per core strategy (setup B), one-position trader: call timestamps for policies sw_P4, ig_P2, ig_P3.
Then for random sets of N Sonnet traders (and 5 Opus twins = 5 median-rate members) count market-bundle writes:
a call writes when the current 15-min version has no live entry (last write/read of that version > 5 min ago).
Same-minute calls: 'serial' (one write, others read; needs a pre-warm/stagger) vs 'burst' (all same-minute
calls before the first answer miss: every call in the first minute of a cold version writes)."""
import sys, os, csv, collections, math, random
sys.path.insert(0, "/root/.local/lib/python3.11/site-packages")
import numpy as np
REP, EXP = sys.argv[1:3]
MIN = 60000; TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
COINS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"}
RARE = {"N14_ICHI_RSI", "N15_KC_AO", "S1_EMA_RSI_CHOP", "N21_ST_RSI_ADX"}
p = os.path.join(EXP, "current")
st = min(int(r["started_ts"]) for r in csv.DictReader(open(os.path.join(p, "runs.csv"))))
d = collections.defaultdict(list)
with open(os.path.join(p, "live_bars.csv")) as fh:
    h = fh.readline().strip().split(","); it, isym, ih, il, ic = (h.index(x) for x in ("ts", "symbol", "high", "low", "close"))
    for line in fh:
        v = line.rstrip("\n").split(","); d[v[isym]].append((int(v[it]), float(v[ih]), float(v[il]), float(v[ic])))
bars = {s: tuple(np.array(sorted(set(L)))[:, i] for i in range(4)) for s, L in d.items()}
end = max(a[0][-1] for a in bars.values()) + MIN; days = (end - st) / 86400000
def mv_times(sym, t0, t1, e, R, k=0.5):
    ts, hi, lo, cl = bars[sym]; i0, i1 = np.searchsorted(ts, t0), np.searchsorted(ts, t1); ref = e; out = []
    for i in range(i0, i1):
        if hi[i] - ref >= k * R or ref - lo[i] >= k * R: out.append(int(ts[i]) + MIN); ref = cl[i]
    return out
bys = collections.defaultdict(list)
for r in csv.DictReader(open(REP)):
    if r["run"] == "current" and r["kind"] == "strategy" and r["symbol"] in COINS and r["timeframe"] in TFM and r["strategy"] not in RARE:
        bys[r["strategy"]].append(r)
calls = {}
for strat, S in bys.items():
    sigs = []
    for r in S:
        ok = r["status"] in ("TRADED", "UNRESOLVED")
        if not ok: continue
        xt = float(r["exit_time"]) if r["exit_time"] not in ("", "nan") else end
        sigs.append((int(r["bar_close"]), TFM[r["timeframe"]], r["symbol"], float(r["entry_time"]), xt, float(r["entry_price"]), float(r["stop_initial"])))
    sigs.sort(); moments = sorted(set(s[0] for s in sigs)); bym = collections.defaultdict(list)
    for s in sigs: bym[s[0]].append(s)
    P = {"sw_P4": [], "ig_P2": [], "ig_P3": []}; pos = None
    for m in moments:
        if pos is not None and m >= pos[4]: pos = None
        if pos is None:
            s = sorted(bym[m], key=lambda x: (x[1], x[2]))[0]; pos = s
            for k in P: P[k].append(m)
            t0, t1 = s[3], min(s[4], end)
            sw = [mm for mm in moments if t0 < mm < t1]
            b30 = [k * 30 * MIN for k in range(math.floor(t0 / (30 * MIN)) + 1, math.ceil(t1 / (30 * MIN)))]
            mv = mv_times(s[2], t0, t1, s[5], abs(s[5] - s[6]))
            otf = sorted(set(x[0] for x in sigs if x[2] == s[2] and x[1] != s[1] and t0 < x[0] < t1))
            P["sw_P4"] += sorted(set(sw) | set(b30) | set(mv) | set(otf)); P["ig_P2"] += b30; P["ig_P3"] += sorted(set(mv) | set(otf))
    calls[strat] = {k: np.array(sorted(v), np.int64) for k, v in P.items()}
def writes(ts_all, mode):
    ts_all = np.sort(ts_all); w = 0; ver = None; last = -10**18
    i = 0
    while i < len(ts_all):
        t = ts_all[i]; v = t // (15 * MIN)
        same = ts_all[(ts_all >= t) & (ts_all < t + MIN)] if mode == "burst" else ts_all[i:i + 1]
        if v != ver or t - last > 5 * MIN:
            w += len(same) if mode == "burst" else 1
            ver = v
        last = t
        i += len(same) if mode == "burst" else 1
        if mode == "burst" and len(same) > 1: last = t
    return w
names = sorted(calls); rng = random.Random(3)
rate = {s: len(calls[s]["sw_P4"]) for s in names}
print("v4 days %.2f, strategies %d" % (days, len(names)))
for pol in ("sw_P4", "ig_P2", "ig_P3"):
    for n in (10, 20, 30):
        res = []
        for _ in range(30):
            sub = rng.sample(names, min(n, len(names)))
            allc = np.concatenate([calls[s][pol] for s in sub])
            mids = sorted(sub, key=lambda s: rate[s])[len(sub) // 2 - 2: len(sub) // 2 + 3]
            op = np.concatenate([calls[s][pol] for s in mids])
            res.append([len(allc) / days, writes(allc, "serial") / days, writes(allc, "burst") / days, len(op) / days, writes(op, "serial") / days, writes(op, "burst") / days])
        r = np.median(np.array(res), 0)
        print(f"{pol} n={n}: sonnet calls/day {r[0]:.0f}, market writes/day serial {r[1]:.0f} burst {r[2]:.0f} | opus5 calls/day {r[3]:.0f}, writes serial {r[4]:.0f} burst {r[5]:.0f} (write share {r[4]/r[3]:.2f}-{r[5]/r[3]:.2f})")
