import csv, sys, statistics as st
from collections import defaultdict
rows=list(csv.DictReader(open(sys.argv[1])))
core_ds=defaultdict(list)
ds=set("F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F11 F12 F13 F14 F15 F16 F17".split())
by_b=defaultdict(lambda: {"core":[], "ds":[]})
for r in rows:
    if r["status"]!="SUBMITTED" or r["timeframe"]=="5m" or r["strategy"].startswith("RANDOM") : continue
    g="ds" if r["strategy"].split("_")[0] in ds else "core"
    d=int(r["delay_ms"]); by_b[(r["bar_close"],r["timeframe"])][g].append(d)
    core_ds[(g,r["timeframe"])].append(d)
for k,v in sorted(core_ds.items()):
    v=sorted(v); print(k, len(v), "median", v[len(v)//2], "p90", v[int(len(v)*.9)], "max", v[-1])
# per boundary: max delay across all groups (commit happens after the last group)
bm=defaultdict(int)
for (b,tf),g in by_b.items():
    m=max(g["core"]+g["ds"]); bm[b]=max(bm[b],m)
v=sorted(bm.values()); print("per-boundary max delay", len(v), "median", v[len(v)//2], "p90", v[int(len(v)*.9)], "max", v[-1])
