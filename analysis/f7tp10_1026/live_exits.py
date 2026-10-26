"""Owners 10/26: a stand-alone bot like V3.9 for this strategy; the live market first. "만약 12%도달하면 10% 계단식 익절이였으면
더 좋았을까? ... 익절이 짧은만큼 진입횟수도 중요". The league's entries with each exit, at the league's size (30x, margin 30 %,
its sizing check) and at a V3.9-style size (BTC 40x / others 30x, margin 40 %, only the liquidation check: stop + 1 ATR inside).
The live windows (the league's 10/13 ~ and October) first; the five years only for context.
Run: python3 live_exits.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd  # noqa: E402

import study as ST  # noqa: E402

EXITS = {
    "고정 익절 +10%": dict(exit="tp10", tp_roe=0.10),
    "고정 익절 +12%": dict(exit="tp10", tp_roe=0.12),
    "계단 12→10, 17→15, 22→20…": dict(exit="lad", lad=(0.12, 0.10, 0.05, 0.02)),
    "계단 12→10, 17→14, 22→19…": dict(exit="lad", lad=(0.12, 0.10, 0.05, 0.03)),
    "계단 11→10, 15→12, 20→17… (추세봇)": dict(exit="trendlad"),
    "계단 20→17, 25→22… (V3.9 투비트)": dict(exit="lad", lad=(0.20, 0.17, 0.05, 0.03)),
}
SIZES = {"리그 크기(30배·30%)": dict(lev=ST.LEV30, margin=ST.M30, league_check=True),
         "V3.9식(BTC 40배·나머지 30배·40%)": dict(lev=ST.LEVT, margin=ST.M40, liq_check=True)}
WINS = ("league", "2026.10", "2024-2026.09", "2021-2023")
DAYS = {"league": 12.4, "2026.10": 24.0, "2024-2026.09": 1004, "2021-2023": 1095}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = pd.read_pickle(os.path.join(a.work, "cand.pkl"))
    out = {}
    for sn, size in SIZES.items():
        for en, ex in EXITS.items():
            arm = {**size, **ex}
            key = f"{sn} | {en}"
            out[key] = {}
            for wn in WINS:
                T = ST.run_arm(W, cand, arm, *ST.WINDOWS[wn])
                s = ST.summary(T)
                s["per_day"] = s["n"] / DAYS[wn]
                s["losses"] = int((T.roe <= 0).sum()) if len(T) else 0
                s["wallet_x"] = s.pop("end", 1000.0) / 1000.0
                out[key][wn] = s
            print(key, json.dumps({w: {k: round(v, 3) if isinstance(v, float) else v for k, v in d.items()
                                       if k in ("n", "losses", "win", "mean_roe", "wallet_x", "per_day")}
                                   for w, d in out[key].items()}, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(a.work, "live_exits.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
