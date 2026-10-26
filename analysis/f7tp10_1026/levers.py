"""Owners 10/26: "37승 5패인데 수익률이 x2.04배 밖에 안돼?" The levers left on the two live windows for the fixed +10 % / -50 % /
no-weekend structure (with and without the V3.9 1h supertrend side check): a time exit after N hours (market, at the 5-minute
open), and the size (margin share 40 / 60 / 80 %; BTC 40x / others 30x, 50x / 40x, 30x / 20x).
Run: python3 levers.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd  # noqa: E402

import pick as PK  # noqa: E402
import structure as SR  # noqa: E402
import study as ST  # noqa: E402

LEVS = {"BTC40·알트30": (40.0, 30.0), "BTC50·알트40": (50.0, 40.0), "BTC30·알트20": (30.0, 20.0)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = SR.add_trend(W, pd.read_pickle(os.path.join(a.work, "cand.pkl")), a.work)
    out = {}
    for tn, tc in (("추세 없음", None), ("슈퍼트렌드 1시간", "st1h")):
        base = SR.arm_of(SR.EXITS["고정 +10%"], "주말 쉼", tc)
        for h in (None, 1, 2, 3, 4, 6, 8, 12, 24):
            arm = dict(base, time_bars=h * 12) if h else base
            out[f"time|{tn}|{h}"] = {wn: PK.read(ST.run_arm(W, cand, arm, wa, wb)) for wn, (wa, wb) in PK.LIVE.items()}
        for ln, (lb, la) in LEVS.items():
            for m in (0.4, 0.6, 0.8):
                arm = dict(base, lev=lambda c, lb=lb, la=la: lb if c == "BTCUSDT" else la, margin=lambda c, m=m: m)
                out[f"size|{tn}|{ln}|{m}"] = {wn: PK.read(ST.run_arm(W, cand, arm, wa, wb)) for wn, (wa, wb) in PK.LIVE.items()}
    for k, v in out.items():
        print(k, json.dumps({w: {x: (round(y, 3) if isinstance(y, float) else y) for x, y in d.items()} for w, d in v.items()},
                            ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(a.work, "levers.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
