"""Owners 10/26: "이 매매법 특징이 짧게 먹고 나오는 전략인가?" Every signal on its own (no one-position rule), at the planned size
(BTC 40x / others 30x, net ROE), followed for 48 h from the next 5-minute open: the best net ROE reached before a -50 % stop,
and how long the +10 % / +20 % / +50 % took. NYSE-open and macro blocks applied as the bot would.
Run: python3 reach.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import pick as PK  # noqa: E402
import sim as S  # noqa: E402
import study as ST  # noqa: E402

H = 576                                   # 48 h of 5-minute bars
LEVELS = (0.05, 0.10, 0.20, 0.30, 0.50, 1.00)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = pd.read_pickle(os.path.join(a.work, "cand.pkl"))
    cand = cand[~cand.us_open & ~cand.macro & (cand.t >= ST.ms("2021-01-01"))]
    rows = []
    for r in cand.itertuples():
        m = W.m5[r.coin]
        i0 = int(r.e5)
        if i0 + H >= len(m["o"]):
            continue
        lev = 40.0 if r.coin == "BTCUSDT" else 30.0
        side = int(r.side)
        fill = m["o"][i0] * (1 + side * S.SLIP)
        fav = (m["h"] if side > 0 else m["l"])[i0:i0 + H]
        adv = (m["l"] if side > 0 else m["h"])[i0:i0 + H]
        roe_f = lev * (side * (fav / fill - 1) - S.RT)
        roe_a = lev * (side * (adv / fill - 1) - S.RT)
        hit = np.flatnonzero(roe_a <= -0.50)
        end = hit[0] if len(hit) else H                    # the stop's bar counts as stopped (stop first inside a bar)
        best = float(roe_f[:end].max()) if end > 0 else -0.5
        row = {"t": int(r.t), "coin": r.coin, "weekend": bool(r.weekend), "best": best, "stopped": bool(len(hit)),
               "stop_h": (end * 5 / 60) if len(hit) else None}
        for lv in LEVELS:
            k = np.flatnonzero(roe_f[:end] >= lv)
            row[f"h{int(lv * 100)}"] = (k[0] * 5 / 60) if len(k) else None
        rows.append(row)
    D = pd.DataFrame(rows)
    D["oct"] = D.t >= ST.ms("2026-10-01")
    out = {}
    for name, g in (("2021-2026.09", D[~D.oct]), ("2026-10", D[D.oct])):
        o = {"signals": int(len(g)), "stopped_48h": float(g.stopped.mean())}
        for lv in LEVELS:
            col = f"h{int(lv * 100)}"
            o[f"reach_{int(lv * 100)}"] = float(g[col].notna().mean())
            o[f"median_hours_{int(lv * 100)}"] = float(g[col].median()) if g[col].notna().any() else None
        o["median_best"] = float(g.best.median())
        o["weekend_reach_10"] = float(g[g.weekend]["h10"].notna().mean())
        o["weekday_reach_10"] = float(g[~g.weekend]["h10"].notna().mean())
        o["weekend_reach_20"] = float(g[g.weekend]["h20"].notna().mean())
        o["weekday_reach_20"] = float(g[~g.weekend]["h20"].notna().mean())
        out[name] = o
        print(name, json.dumps(o), flush=True)
    json.dump(out, open(os.path.join(a.work, "reach.json"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
