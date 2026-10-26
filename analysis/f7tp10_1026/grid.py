"""Owners 10/26 follow-up: "손절거리를 늘렸으면 3패가 3승일수 있었어? ... 10% 익절이 제일 괜찮았어?" — the league account's
entries (L0: 30x, margin 30 %, the league's sizing check) with every take-profit (net ROE 5 .. 30 %) x stop (1.5 .. 4 ATR).
Chosen on 2021-2023 only, read once on 2024-2026.09; October and the league window are only read.
Run: python3 grid.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd  # noqa: E402

import study as ST  # noqa: E402

TPS = (0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30)
STOPS = (1.5, 2.0, 3.0, 4.0)
WINS = ("2021-2023", "2024-2026.09", "2026.10", "league")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = pd.read_pickle(os.path.join(a.work, "cand.pkl"))
    out = {}
    for tp in TPS:
        for sa in STOPS:
            arm = dict(exit="tp10", lev=ST.LEV30, margin=ST.M30, league_check=True, stop_atr=sa, tp_roe=tp)
            key = f"tp{round(tp * 100)}_s{sa:g}"
            out[key] = {}
            for wn in WINS:
                wa, wb = ST.WINDOWS[wn]
                out[key][wn] = ST.summary(ST.run_arm(W, cand, arm, wa, wb))
            print(key, json.dumps({w: {k: round(v, 4) if isinstance(v, float) else v for k, v in d.items()
                                       if k in ("n", "win", "mean_roe", "end", "bust")} for w, d in out[key].items()}),
                  flush=True)
    json.dump(out, open(os.path.join(a.work, "grid.json"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
