import datetime as dt
import json
import sys
from collections import defaultdict

import numpy as np

d = json.load(open(sys.argv[1]))
D0, END = d["live_d0"], d["end"]
day = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%m-%d")  # noqa: E731
LIVE_DAY = {"10-05": (12, -1.5), "10-06": (261, -1.4), "10-07": (253, 1.5), "10-08": (303, 0.6), "10-09": (233, -2.0)}
print("replay window", dt.datetime.utcfromtimestamp(D0 / 1000), "->", dt.datetime.utcfromtimestamp(END / 1000))
# per-signal (full-grid unit), signals closing in [D0, END)
for tf in ("15m", "30m", "1h", "4h"):
    x = [s[3] for c in d["cells"] if c["tf"] == tf for s in c["signals"] if D0 <= s[0] < END]
    x = np.array(x)
    print(f"signals {tf}: n {len(x)} win {np.mean(x > 0) * 100:.0f}% mean {x.mean() * 100:+.2f}%" if len(x) else tf)
# account paths
byday = defaultdict(list)
bytf = defaultdict(list)
cells = []
for c in d["cells"]:
    a = c["account"]
    for e, r in zip(a["exit_ms"], a["ret"]):
        byday[day(e)].append(r)
        bytf[c["tf"]].append(r)
    cells.append((c["name"], c["tf"], a["final_x"], a["trades"], a["max_dd"]))
for tf in ("15m", "30m", "1h", "4h"):
    r = np.array(bytf[tf])
    up = sum(1 for c in cells if c[1] == tf and c[2] > 1)
    dn = sum(1 for c in cells if c[1] == tf and c[2] < 1)
    print(f"account {tf}: trades {len(r)} win {np.mean(r > 0) * 100:.0f}% mean {r.mean() * 100:+.2f}% up/down {up}/{dn}"
          f" median wallet ${np.median([c[2] for c in cells if c[1] == tf]) * 5000:,.0f}")
print("day: replay trades mean | live trades mean")
for k in sorted(byday):
    r = np.array(byday[k])
    lv = LIVE_DAY.get(k)
    print(f"{k}: {len(r)} {r.mean() * 100:+.2f}% | " + (f"{lv[0]} {lv[1]:+.1f}%" if lv else "—"))
cells.sort(key=lambda c: -c[2])
print("top10:", " · ".join(f"{n}@{tf} ${x * 5000:,.0f}({t})" for n, tf, x, t, _ in cells[:10]))
print("bottom10:", " · ".join(f"{n}@{tf} ${x * 5000:,.0f}({t})" for n, tf, x, t, _ in cells[-10:]))
json.dump({"cells": cells}, open(sys.argv[1].replace(".json", "_cells.json"), "w"))
