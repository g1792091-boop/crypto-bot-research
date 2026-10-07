"""Own one-position AI-trader call simulation on live replay (every SUBMITTED signal run alone, validated engine).
python3 -I v_live.py <replay_signals.csv> <export_dir> <out_csv>
Per strategy x setup (A 15m/30m, B all 4, C 15m/30m/1h + 4h if 2ATR<=3.2%): flat -> first moment with >=1
offered entry-set signal = 1 entry call (bundle), enter the lowest-tf signal (ties: first coin). Hold until its
replayed exit (UNRESOLVED -> run end). While holding count: switch bundles (entry-set signal moments), P1 held-tf
bar closes, P2 30-min boundaries, P3 events = 1m-bar move >= k*R from last event ref (ref moves by k*R steps, so a
1m bar can fire several times only via successive bars), plus other-tf same-coin signals of the strategy."""
import sys, os, csv, collections, math
import numpy as np
REP, EXP, OUT = sys.argv[1:4]
RUNS = {"run-20261005T183457Z": ("v3b", "run-20261005T183457Z"), "current": ("v4", "current")}
TFM = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
COINS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"}
MIN = 60000
def load_bars(p):
    d = collections.defaultdict(list)
    with open(os.path.join(p, "live_bars.csv")) as fh:
        h = fh.readline().strip().split(","); it, isym, ih, il, ic = (h.index(x) for x in ("ts", "symbol", "high", "low", "close"))
        for line in fh:
            v = line.rstrip("\n").split(",")
            d[v[isym]].append((int(v[it]), float(v[ih]), float(v[il]), float(v[ic])))
    out = {}
    for s, L in d.items():
        a = np.array(sorted(set(L))); out[s] = (a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3])
    return out
def moves(bars, sym, t0, t1, entry, R, k, cooldown_min=0):
    ts, hi, lo, cl = bars[sym]
    i0, i1 = np.searchsorted(ts, t0), np.searchsorted(ts, t1)
    ref = entry; n = 0; last = -10**18; thr = k * R
    for i in range(i0, i1):
        up, dn = hi[i] - ref, ref - lo[i]
        if up >= thr or dn >= thr:
            if ts[i] - last >= cooldown_min * MIN:
                n += 1; last = ts[i]
            ref = cl[i]
    return n
rows_in = collections.defaultdict(list)
for r in csv.DictReader(open(REP)):
    if r["run"] not in RUNS or r["symbol"] not in COINS or r["timeframe"] not in TFM: continue
    if r["kind"] not in ("strategy", "ds200"): continue
    rows_in[r["run"]].append(r)
res = []
for run, L in rows_in.items():
    tag, d = RUNS[run]; p = os.path.join(EXP, d)
    st = min(int(r["started_ts"]) for r in csv.DictReader(open(os.path.join(p, "runs.csv"))))
    bars = load_bars(p); end = max(a[0][-1] for a in bars.values()) + MIN
    days = (end - st) / 86400000
    bys = collections.defaultdict(list)
    for r in L: bys[r["strategy"]].append(r)
    for strat, S in bys.items():
        kind = S[0]["kind"]
        sigs = []
        for r in S:
            bc = int(r["bar_close"]); tf = r["timeframe"]
            ok = r["status"] in ("TRADED", "UNRESOLVED") and r["entry_time"] not in ("", "nan")
            et = float(r["entry_time"]) if ok else None
            xt = float(r["exit_time"]) if ok and r["exit_time"] not in ("", "nan") else end
            ep = float(r["entry_price"]) if ok else None; sp = float(r["stop_initial"]) if ok else None
            sf = 2 * float(r["atr"]) / float(r["ref_price"])
            sigs.append((bc, TFM[tf], tf, r["symbol"], ok, et, xt, ep, sp, sf))
        sigs.sort()
        for setup in "ABC":
            def inset(s):
                if setup == "A": return s[2] in ("15m", "30m")
                if setup == "B": return True
                return s[2] != "4h" or s[9] <= 0.032
            offered = [s for s in sigs if inset(s) and s[4]]
            moments = sorted(set(s[0] for s in offered))
            bym = collections.defaultdict(list)
            for s in offered: bym[s[0]].append(s)
            c = collections.Counter(); held = 0.0; tnow = -1
            pos = None
            for m in moments:
                if pos is not None and m >= pos[6]:
                    pos = None
                if pos is None:
                    c["entry"] += 1
                    s = sorted(bym[m], key=lambda x: (x[1], x[3]))[0]
                    pos = s; c["trades"] += 1
                    t0, t1 = s[5], min(s[6], end); held += max(0, t1 - t0)
                    R = abs(s[7] - s[8]); tfm = s[1]
                    sw = set(mm for mm in moments if t0 < mm < t1)
                    c["switch"] += len(sw)
                    # P1 / P2 boundaries strictly inside (t0, t1)
                    for name, step in (("p1", tfm), ("p2", 30)):
                        k0 = math.floor(t0 / (step * MIN)) + 1; k1 = math.ceil(t1 / (step * MIN)) - 1
                        b = set(k * step * MIN for k in range(k0, k1 + 1))
                        c[name + "_ign"] += len(b); c[name + "_sw"] += len(b - sw)
                    for kk, cd in ((0.5, 0), (1.0, 0), (0.5, 15)):
                        c[f"mv{kk}_cd{cd}"] += moves(bars, s[3], t0, t1, s[7], R, kk, cd)
                    otf = [x for x in sigs if x[3] == s[3] and x[2] != s[2] and t0 < x[0] < t1]
                    c["otf_ign"] += len(set(x[0] for x in otf))
                    c["otf_sw"] += len(set(x[0] for x in otf if not inset(x)))
                    opp = [x for x in offered if x[3] == s[3] and t0 < x[0] < t1]
                    c["opp_samecoin"] += len(set(x[0] for x in opp))  # design v2: only held-coin signals wake (opposite in practice)
            row = dict(run=tag, strategy=strat, kind=kind, setup=setup, days=round(days, 3), occupancy=round(held / (end - st), 3))
            for k, v in c.items(): row[k] = round(v / days, 2)
            res.append(row)
keys = sorted(set().union(*[r.keys() for r in res]), key=lambda k: (k not in ("run", "strategy", "kind", "setup", "days", "occupancy"), k))
with open(OUT, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=keys, restval=0); w.writeheader(); w.writerows(res)
print(len(res), "rows")
