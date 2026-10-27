#!/usr/bin/env python3
"""VWAP 개선판 -> 딥코인: the ladder's spacing (owners 10-27: "화면 13.4%에 닿으면 손절선을 11.4%(순 8%) 자리로 하자 대신 그 위로
계단식 익절 간격 제일 좋은 간격으로 추천해줘", "친구봇이랑 vwap봇 익절 기준으로 정할생각이야").

The bot's own 5-year simulator as vwap.py runs it (research/vwap30/code: the VWAP 30m and CMO 1h signals, gates, 2 ATR stop,
96-bar cap, leverage min(30, 0.5 / (2 ATR % + 0.14 %)), margin 40 %, one position, the executor's signal light 20 / 75 %),
arm A0 only, with the ladder (vwfix2.lock_house, net ROE at 30x) replaced by trigger -> lock, then + step a step, each later
lock 2 % under its trigger:
  12 -> 10, step 5 (the ladder now; must equal lock_house), and the owners' first rung 10 -> 8 with step 2 / 3 / 4 / 5 / 7 / 10.
The paper and the executor take the same ladder here (in the live bot the executor's own ladder runs on its own fill).

Selection (fixed before the results, as research/opentime and research/mixchop_st/ladder9.py): among the 10 -> 8 arms, the
highest median month (KST months, a fresh wallet each, the executor's copied trades) of 2021-01 .. 2023-12, log growth on a
tie; 2024-01 .. 2026-09, October 2026 and the 20 days 2026-10-05 .. 10-25 (KST, one wallet; added 10-27 at the owners'
"20일 기준도", after the first run) only check it (reported, not used to choose).
    python3 -I vwap_ladder.py FIVE5M_DIR WORK OUT_DIR       (the same folders as vwap.py)  ->  OUT_DIR/vwap_ladder.json"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import otcommon as CM  # noqa: E402
import vwap as VB  # noqa: E402

import numpy as np  # noqa: E402

D20 = (CM.kst_ms("2026-10-05 00:00"), CM.kst_ms("2026-10-25 09:00"))
LADDERS = [(12, 10, 5)] + [(10, 8, step) for step in (2, 3, 4, 5, 7, 10)]


def ladder_fn(trig: float, lock: float, step: float):
    t, k, s = trig / 100.0, lock / 100.0, step / 100.0
    return lambda r: np.where(r >= t, k + s * np.floor((r - t) / s + 1e-9), np.nan)


def name(lad) -> str:
    return f"{lad[0]}→{lad[1]} 간격 {lad[2]}"


def main(argv=None) -> int:
    five, work, out = (argv or sys.argv[1:])[:3]
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    import vwmonth2  # noqa: F401  (loads the whole chain, then the names are patched)
    import vwfix2 as V2
    VB.patch(five, work)
    CM.ARMS = {"A0": ("none", 0)}
    orig = V2.lock_house
    r = np.linspace(-0.5, 3.0, 35001)
    a, b = orig(r), ladder_fn(12, 10, 5)(r)
    assert np.array_equal(np.isnan(a), np.isnan(b)) and np.allclose(a[~np.isnan(a)], b[~np.isnan(b)]), "12-10-5 != lock_house"
    parts = VB.signal_rows()
    res = {}
    try:
        for lad in LADDERS:
            V2.lock_house = ladder_fn(*lad)
            P, _ = VB.outcomes_all(parts)
            D = VB.account(P, "A0")
            L = D[D.copied].reset_index(drop=True)
            res[name(lad)] = {"ladder": list(lad), "live": {p: CM.period_metrics(L, p) for p in CM.PERIODS},
                              "paper": {p: CM.period_metrics(D, p) for p in CM.PERIODS}}
            # the 20 days of the friend bot's check (owners 10-27 "20일 기준도"): 2026-10-05 .. 10-25 KST, one wallet
            W = L[(L.t >= D20[0]) & (L.t < D20[1])]
            rr = W.ret.to_numpy(float)
            res[name(lad)]["d20"] = {"trades": int(len(rr)), "wins": int((rr > 0).sum()), "x": float(np.prod(1 + rr))}
            lv = res[name(lad)]["live"]
            print(name(lad), {p: (d["trades"], round(d["median_month"], 4), d["months_up"], round(d["win_pct"], 1))
                              for p, d in lv.items()}, f"{time.time() - t0:.0f}s", flush=True)
    finally:
        V2.lock_house = orig
    cands = [n for n in res if res[n]["ladder"][:2] == [10, 8]]
    best = max(cands, key=lambda n: (res[n]["live"]["choose"]["median_month"], res[n]["live"]["choose"]["log_growth"]))
    res["_chosen_on_2021_2023"] = best
    print("chosen on the choosing months:", best, flush=True)
    json.dump(CM.jsonable(res), open(os.path.join(out, "vwap_ladder.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
