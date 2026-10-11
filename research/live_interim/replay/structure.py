"""Did the market structure change in favour of this week's good-looking cells? (reference, after the live week)

    python research/live_interim/replay/structure.py core_default_trades.json good_cells.json

Per-signal means (default numbers, live exit) of all 144 core cells by calendar year and for the last three months
before the live run, and of the 21 good-looking cells for the last three months, 2026 so far and last year's crash
week (2025-10-08 .. 10-14), split by side.
"""
import datetime as dt
import json
import sys

import numpy as np


def ms(s: str) -> int:
    return int(dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


rows = json.load(open(sys.argv[1]))
good = list(json.load(open(sys.argv[2]))["cells"])
cells = {}
for name, tf, close, x, pid, coin, side in rows:
    c, x, s = np.array(close, np.int64), np.array(x, float), np.array(side)
    m = np.isfinite(x)
    o = np.argsort(c[m], kind="stable")
    cells[f"{name}@{tf}"] = (c[m][o], x[m][o], s[m][o])


def seg(k, a, b):
    c, x, s = cells[k]
    m = (c >= ms(a)) & (c < ms(b))
    return x[m], s[m]


for a, b, lab in (("2021-01-01", "2022-01-01", "2021"), ("2022-01-01", "2023-01-01", "2022"), ("2023-01-01", "2024-01-01", "2023"),
                  ("2024-01-01", "2025-01-01", "2024"), ("2025-01-01", "2026-01-01", "2025"), ("2026-01-01", "2026-07-01", "2026 H1"),
                  ("2026-07-01", "2026-10-01", "2026-07..09")):
    xs = np.concatenate([seg(k, a, b)[0] for k in cells])
    print(f"all 144 {lab}: n {len(xs)} win {np.mean(xs > 0) * 100:.0f}% mean {xs.mean() * 100:+.2f}%")
for a, b, lab in (("2026-07-01", "2026-10-01", "last 3 months"), ("2026-01-01", "2026-10-01", "2026"), ("2025-10-08", "2025-10-15", "2025-10-08..14")):
    parts = [seg(k, a, b) for k in good]
    xs = np.concatenate([p[0] for p in parts])
    sd = np.concatenate([p[1] for p in parts])
    pos = sum(1 for p in parts if len(p[0]) and p[0].mean() > 0)
    print(f"good 21 {lab}: n {len(xs)} mean {xs.mean() * 100:+.2f}% short {xs[sd < 0].mean() * 100:+.2f}% "
          f"long {xs[sd > 0].mean() * 100:+.2f}% cells positive {pos}")
