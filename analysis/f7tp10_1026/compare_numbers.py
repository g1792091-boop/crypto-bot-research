"""Owners 10/26: "규칙봇에 있는 레인지 필터 3중 일치 1시간(기본값)이랑 커스텀값 봇에 있는 것(찾은 값) 비교해줘". The default numbers
(rf_period 100, rf_mult 3.0; the rule bot's account F7_RF_TRIPLE@1h) against the pick's (80, 9.0), each through the same rules:
the league account's (30x, margin 30 %, its sizing check, stop 2 ATR, TP net +10 %) and the stand-alone bot chosen in pick.py
(BTC 40x / others 30x, margin 40 %, TP net +10 %, stop net ROE -50 %, no weekend, NYSE open and macro +-30 min).
Run: python3 compare_numbers.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import pick as PK  # noqa: E402
import study as ST  # noqa: E402

RULES = {"리그 규칙(사진)": dict(exit="tp10", lev=ST.LEV30, margin=ST.M30, league_check=True),
         "고른 단독 봇": dict(exit="tp10", tp_roe=0.10, lev=ST.LEVT, margin=ST.M40, liq_check=True, stop_roe=0.50,
                          filters=(PK.FIXED, PK.NOWK))}
WINS = {"rulebot": PK.LIVE["rulebot"], "league": PK.LIVE["league"], "2021-2023": ST.WINDOWS["2021-2023"],
        "2024-2026.09": ST.WINDOWS["2024-2026.09"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = {"찾은 값 (80 · 9.0)": pd.read_pickle(os.path.join(a.work, "cand.pkl"))}
    cp = os.path.join(a.work, "cand_d.pkl")
    if not os.path.exists(cp):
        W.candidates("sig_d").to_pickle(cp)
    cand["기본값 (100 · 3.0)"] = pd.read_pickle(cp)
    out = {}
    for cn, C in cand.items():
        for wn, (wa, wb) in WINS.items():
            days = (min(wb, PK.END) - wa) / 86_400_000
            n = int(((C.t >= wa) & (C.t < wb)).sum())
            out.setdefault(cn, {})[f"signals_per_day|{wn}"] = n / days
        for rn, arm in RULES.items():
            for wn, (wa, wb) in WINS.items():
                T = ST.run_arm(W, C, arm, wa, wb)
                if wn in ("rulebot", "league"):
                    r = PK.read(T)
                else:
                    s = ST.summary(T)
                    r = {k: s.get(k) for k in ("n", "win", "mean_roe", "bust")}
                out[cn][f"{rn}|{wn}"] = r
                print(cn, rn, wn, json.dumps(r, ensure_ascii=False), flush=True)
    # how often the two fire on the same coin, hour and side
    a_, b_ = cand["찾은 값 (80 · 9.0)"], cand["기본값 (100 · 3.0)"]
    ka, kb = set(zip(a_.t, a_.coin, a_.side)), set(zip(b_.t, b_.coin, b_.side))
    out["overlap"] = {"custom": len(ka), "default": len(kb), "both": len(ka & kb)}
    print(out["overlap"])
    json.dump(out, open(os.path.join(a.work, "numbers.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
