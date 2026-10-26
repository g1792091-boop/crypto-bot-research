"""Owners 10/26: the stand-alone bot for 레인지 필터 3중 일치 · 1시간 (custom 80 / 9.0): BTC 40x, others 30x, margin 40 %,
no entry 30 min before / after the NYSE open and macro releases (fixed). Compared: take-profit (fixed +10 %, steps 12 -> 10 ·
17 -> 15 ..., fixed +20 %, steps 22 -> 20 · 27 -> 25 ...) x stop (1.5 / 2 / 2.5 / 3 ATR, net ROE -25 / -35 / -50 %) x weekend
(on / off), on the rule bot's live period (10/06 03:35 KST ~) and the custom-value league's (10/13 21:00 KST ~), both to the
data's end (10/25 09:00 KST). Ranked by the lower of the two windows' wallet multiples (closed trades; a trade still open at
the data's end is left out). The five-year periods are read for the leaders only as context.
Run: python3 pick.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import study as ST  # noqa: E402

END = int(pd.Timestamp("2026-10-25 09:00", tz="Asia/Seoul").value // 1_000_000)
LIVE = {"rulebot": (int(pd.Timestamp("2026-10-06 03:35", tz="Asia/Seoul").value // 1_000_000), END),
        "league": (int(pd.Timestamp("2026-10-13 21:00", tz="Asia/Seoul").value // 1_000_000), END)}
EXITS = {"고정 +10%": dict(exit="tp10", tp_roe=0.10), "계단 12→10·17→15…": dict(exit="lad", lad=(0.12, 0.10, 0.05, 0.02)),
         "고정 +20%": dict(exit="tp10", tp_roe=0.20), "계단 22→20·27→25…": dict(exit="lad", lad=(0.22, 0.20, 0.05, 0.02))}
STOPS = {"1.5 ATR": dict(stop_atr=1.5), "2 ATR": dict(stop_atr=2.0), "2.5 ATR": dict(stop_atr=2.5), "3 ATR": dict(stop_atr=3.0),
         "순ROE −25%": dict(stop_roe=0.25), "순ROE −35%": dict(stop_roe=0.35), "순ROE −50%": dict(stop_roe=0.50)}
FIXED = lambda g: ~g.us_open & ~g.macro  # noqa: E731
NOWK = lambda g: ~g.weekend  # noqa: E731
SIZE = dict(lev=ST.LEVT, margin=ST.M40, liq_check=True)


def read(T: pd.DataFrame) -> dict:
    C = T[T.reason != "END"]
    if not len(C):
        return {"n": 0, "w": 0, "l": 0, "x": 1.0, "mdd": 0.0, "open": int((T.reason == "END").sum())}
    eq = np.cumprod(1 + C.margin.to_numpy() * np.maximum(C.roe.to_numpy(), -1))
    curve = np.r_[1.0, eq]
    return {"n": int(len(C)), "w": int((C.roe > 0).sum()), "l": int((C.roe <= 0).sum()), "x": float(eq[-1]),
            "mdd": float(np.max(1 - curve / np.maximum.accumulate(curve))), "open": int((T.reason == "END").sum())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = pd.read_pickle(os.path.join(a.work, "cand.pkl"))
    rows = []
    for en, ex in EXITS.items():
        for sn, st in STOPS.items():
            for wk in ("주말 포함", "주말 쉼"):
                arm = {**SIZE, **ex, **st, "filters": (FIXED,) if wk == "주말 포함" else (FIXED, NOWK)}
                r = {"exit": en, "stop": sn, "weekend": wk}
                for wn, (wa, wb) in LIVE.items():
                    r[wn] = read(ST.run_arm(W, cand, arm, wa, wb))
                r["score"] = min(r["rulebot"]["x"], r["league"]["x"])
                rows.append(r)
                print(json.dumps(r, ensure_ascii=False), flush=True)
    rows.sort(key=lambda r: (-r["score"], -max(r["rulebot"]["x"], r["league"]["x"])))
    for r in rows[:5]:                                   # context: the leaders over five years
        arm = {**SIZE, **EXITS[r["exit"]], **STOPS[r["stop"]],
               "filters": (FIXED,) if r["weekend"] == "주말 포함" else (FIXED, NOWK)}
        for wn in ("2021-2023", "2024-2026.09"):
            s = ST.summary(ST.run_arm(W, cand, arm, *ST.WINDOWS[wn]))
            r[wn] = {k: s.get(k) for k in ("n", "win", "mean_roe", "bust")}
    json.dump(rows, open(os.path.join(a.work, "pick.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
