"""Recount SUBMITTED signals/day per strategy x tf on the 6 tradable coins from raw signal_log (v3b, v4).
python3 -I v_rates.py <export_dir> <out_csv>"""
import sys, os, csv, collections, json
EXP, OUT = sys.argv[1], sys.argv[2]
RUNS = {"v3b": "run-20261005T183457Z", "v4": "current"}
COINS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"}
def kind(s):
    if s.startswith("RANDOM") or s.startswith("COIN"): return "flip"
    if s.startswith("F") and s[1:2].isdigit(): return "ds"
    return "core"
rows = []
summary = {}
for tag, d in RUNS.items():
    p = os.path.join(EXP, d)
    st = min(int(r["started_ts"]) for r in csv.DictReader(open(os.path.join(p, "runs.csv"))))
    # end: last 1m live bar
    end = 0
    with open(os.path.join(p, "live_bars.csv")) as fh:
        hdr = fh.readline().strip().split(",")
        ti = [i for i, h in enumerate(hdr) if h in ("ts", "open_time", "t", "time")]
        ti = ti[0] if ti else 0
        for line in fh:
            v = line.split(",")[ti]
            try: end = max(end, int(float(v)))
            except ValueError: pass
    days = (end - st) / 86400000
    cnt = collections.Counter(); bund = collections.defaultdict(set); stat = collections.Counter(); kinds = collections.Counter()
    for r in csv.DictReader(open(os.path.join(p, "signal_log.csv"))):
        stat[(r["status"], r["symbol"] in COINS)] += 1
        if r["status"] != "SUBMITTED" or r["symbol"] not in COINS: continue
        k = kind(r["strategy"]); kinds[(k, r["timeframe"])] += 1
        cnt[(r["strategy"], r["timeframe"])] += 1
        bund[(r["strategy"], r["timeframe"])].add(r["bar_close"])
    tot = collections.defaultdict(float); totb = collections.defaultdict(float)
    for (s, tf), n in cnt.items():
        rows.append(dict(run=tag, strategy=s, kind=kind(s), tf=tf, signals_per_day=round(n / days, 3), bundles_per_day=round(len(bund[(s, tf)]) / days, 3), n=n))
        tot[(kind(s), tf)] += n / days; totb[(kind(s), tf)] += len(bund[(s, tf)]) / days
    summary[tag] = dict(days=round(days, 3), start=st, end=end, status=str(dict(stat)),
                        per_day={f"{k}|{tf}": round(v, 1) for (k, tf), v in sorted(tot.items())},
                        bundles_per_day={f"{k}|{tf}": round(v, 1) for (k, tf), v in sorted(totb.items())})
with open(OUT, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(json.dumps(summary, indent=1))
