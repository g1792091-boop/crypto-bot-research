#!/usr/bin/env python3
"""VWAP 개선판: BTC at 40x (owners 10-27: "vwap 봇도 비트는 40배로 나머지 종목들은 30배로 가자", with the ladder they chose,
10 -> 8 then every 4 %). vwap_ladder.py's machinery (the bot's own 5-year simulator, arm A0), three arms:
  N0  12 -> 10 every 5, every coin 30x (the bot now)
  N1  10 -> 8 every 4, every coin 30x
  N2  10 -> 8 every 4, BTC 40x, the others 30x (the owners' plan)
A coin's leverage is min(its cap, 0.5 / (2 ATR % + 0.14 %)) as the paper's loss_cap "shrink" (a stop loses at most 20 % of the
wallet at margin 40 %); the ladder's net ROE is read at the coin's cap (vwfix2.LEVP set per coin). Read only (the owners have
decided): 2021-01 .. 2023-12, 2024-01 .. 2026-09, October and the 20 days 2026-10-05 .. 10-25.
    python3 -I vwap_btc40.py FIVE5M_DIR WORK OUT_DIR  ->  OUT_DIR/vwap_btc40.json"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import otcommon as CM  # noqa: E402
import vwap as VB  # noqa: E402
import vwap_ladder as VL  # noqa: E402

import numpy as np  # noqa: E402

ARMS = {"N0": ((12, 10, 5), 30), "N1": ((10, 8, 4), 30), "N2": ((10, 8, 4), 40)}
ARM_KO = {"N0": "12→10 간격 5, 모두 30배 (지금)", "N1": "10→8 간격 4, 모두 30배", "N2": "10→8 간격 4, BTC 40배 · 나머지 30배"}


def main(argv=None) -> int:
    five, work, out = (argv or sys.argv[1:])[:3]
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    import vwmonth2  # noqa: F401
    import vwfix2 as V2
    VB.patch(five, work)
    CM.ARMS = {"A0": ("none", 0)}
    lock0, lev0, arms0 = V2.lock_house, V2.LEVP, VB.outcomes_arms
    parts = VB.signal_rows()
    res = {}
    try:
        for arm, (lad, btc) in ARMS.items():
            V2.lock_house = VL.ladder_fn(*lad)

            def per_coin(coin, R, k, _btc=btc):
                V2.LEVP = float(_btc) if coin == "BTCUSDT" else 30.0
                try:
                    return arms0(coin, R, k)
                finally:
                    V2.LEVP = lev0
            VB.outcomes_arms = per_coin
            P, _ = VB.outcomes_all(parts)
            cap = np.where(np.array([VB.NL.COINS[c] for c in P.coin]) == "BTCUSDT", float(btc), 30.0)
            P["lev"] = np.minimum(cap, 0.5 / (2.0 * P.atrf.to_numpy() + V2.COST_RT))
            D = VB.account(P, "A0")
            L = D[D.copied].reset_index(drop=True)
            W = L[(L.t >= VL.D20[0]) & (L.t < VL.D20[1])]
            rr = W.ret.to_numpy(float)
            res[arm] = {"label": ARM_KO[arm], "live": {p: CM.period_metrics(L, p) for p in CM.PERIODS},
                        "d20": {"trades": int(len(rr)), "wins": int((rr > 0).sum()), "x": float(np.prod(1 + rr))},
                        "btc": {p: CM.period_metrics(L[L.symbol == "BTCUSDT"].reset_index(drop=True), p) for p in CM.PERIODS},
                        "btc_lev_mean": float(L[L.symbol == "BTCUSDT"].lev.mean())}
            lv = res[arm]["live"]
            print(arm, ARM_KO[arm], {p: (d["trades"], round(d["median_month"], 4), d["months_up"], round(d["worst_month"], 3))
                                     for p, d in lv.items()}, res[arm]["d20"], f"BTC lev {res[arm]['btc_lev_mean']:.1f}",
                  f"{time.time() - t0:.0f}s", flush=True)
    finally:
        V2.lock_house, V2.LEVP, VB.outcomes_arms = lock0, lev0, arms0
    json.dump(CM.jsonable(res), open(os.path.join(out, "vwap_btc40.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
