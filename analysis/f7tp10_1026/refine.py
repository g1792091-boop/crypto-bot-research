"""Owners 10/26: "짧게 먹고 나오는 매매법이니까 손절 기준이랑 진입타점 기준이 굉장히 중요할꺼 같은데 ... 다른 추세판단 매매법을 썼을땐
어땠어? 아니면 추세판단 매매법을 빼야되나? 그리고 12%도달하면 10%익절 17%도달하면 15% 익절 22%도달하면 20%익절 ... 고정 10%보다
나았어?" The two live windows only, custom numbers, BTC 40x / others 30x, margin 40 %, NYSE-open and macro blocks.
  A. trend checks (each judge of the trend bot on the 1h bar, on the last closed 4h bar, the 3-of-4 vote, the daily vote, EMA200),
     with the entry now and with the 0.25 ATR / 2 h pullback; TP +10 %, stop -50 %; weekend on / off.
  B. stops (net ROE -30 .. -70 %, 1.5 / 2 / 3 ATR from the entry) for the leading set-ups.
  C. the steps 12 -> 10, 17 -> 15, 22 -> 20 ... (and the trend bot's 11 -> 10, 15 -> 12 ...) against the fixed +10 %.
Run: python3 refine.py --bars FIVE5M_DIR --work WORK_DIR"""
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
import timing as TM  # noqa: E402

TRENDS = {
    "없음": None,
    "1시간 V3.9 슈퍼트렌드": "j1_V39", "1시간 EMA20·DMI": "j1_S6", "1시간 OBV": "j1_OBV", "1시간 일목·AO": "j1_N12",
    "1시간 4개 중 3개": "j1_raw3", "1시간 3개 반대만 아니면": (lambda g: g.j1_raw3 != -g.side),
    "4시간 V3.9 슈퍼트렌드": "st4h", "4시간 EMA20·DMI": "j4_S6", "4시간 OBV": "j4_OBV", "4시간 일목·AO": "j4_N12",
    "4시간 4개 중 3개": "j4_raw3", "4시간 3개 반대만 아니면": (lambda g: g.j4_raw3 != -g.side),
    "일봉 4개 중 3개": "jd_raw", "1시간 EMA200 위/아래": "ema200",
}
ENTRIES = {"바로 진입": ("now",), "되돌림 0.25 ATR · 2시간": ("pull", 0.25, 2)}


def both(W, cand, **kw) -> dict:
    r = {wn: TM.run(W, cand, a=wa, b=wb, **kw)[1] for wn, (wa, wb) in PK.LIVE.items()}
    r["score"] = min(r["rulebot"]["x"], r["league"]["x"])
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = SR.add_trend(W, pd.read_pickle(os.path.join(a.work, "cand.pkl")), a.work)
    out = {"A": [], "B": [], "C": []}
    for tn, tc in TRENDS.items():
        for en, mo in ENTRIES.items():
            for wk in (True, False):
                r = {"trend": tn, "entry": en, "weekend_off": wk, **both(W, cand, trend=tc, mode=mo, weekend_off=wk)}
                out["A"].append(r)
                print("A", json.dumps(r, ensure_ascii=False), flush=True)
    lead = sorted(out["A"], key=lambda r: -r["score"])[:4]
    stops = {"순ROE −30%": ("roe", 0.30), "순ROE −40%": ("roe", 0.40), "순ROE −50%": ("roe", 0.50), "순ROE −60%": ("roe", 0.60),
             "순ROE −70%": ("roe", 0.70), "1.5 ATR": ("atr", 1.5), "2 ATR": ("atr", 2.0), "3 ATR": ("atr", 3.0)}
    exits = {"고정 +10%": ("tp10", 0.10, None), "계단 12→10·17→15·22→20": ("lad", 0.10, (0.12, 0.10, 0.05, 0.02)),
             "계단 11→10·15→12·20→17 (추세봇)": ("trendlad", 0.10, None), "고정 +15%": ("tp10", 0.15, None)}
    for L in lead:
        tc, mo = TRENDS[L["trend"]], ENTRIES[L["entry"]]
        for sn, st in stops.items():
            r = {"trend": L["trend"], "entry": L["entry"], "weekend_off": L["weekend_off"], "stop": sn,
                 **both(W, cand, trend=tc, mode=mo, weekend_off=L["weekend_off"], stop=st)}
            out["B"].append(r)
            print("B", json.dumps(r, ensure_ascii=False), flush=True)
        for xn, (ek, tp, lad) in exits.items():
            r = {"trend": L["trend"], "entry": L["entry"], "weekend_off": L["weekend_off"], "exit": xn,
                 **both(W, cand, trend=tc, mode=mo, weekend_off=L["weekend_off"], exit_kind=ek, tp_roe=tp, lad=lad)}
            out["C"].append(r)
            print("C", json.dumps(r, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(a.work, "refine.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
