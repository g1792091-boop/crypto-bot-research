#!/usr/bin/env python3
"""레인지 봇 + 4시간 신호 (PREREG.md): F1 with the 1h source alone vs 1h + 4h, 2021-01 .. 2026-10 on the public 5m bars.

    python3 -I run.py FIVE5M_PARENT WORK OUT_DIR
FIVE5M_PARENT: the folder holding 5m/<SYM>.npz; WORK: research/opentime/rangebot.py's work folder (built with its --build)."""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "opentime"))
import otcommon as CM  # noqa: E402  (puts the repository on sys.path)
import rangebot as RB  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

H, PK, S = RB.H, RB.PK, RB.S

ARMS = {"R0": ("1h_c",), "R1": ("1h_c", "4h_c"), "R2": ("1h_c", "4h_d"), "R3": ("4h_c",), "R4": ("4h_d",)}
ARM_KO = {"R0": "1시간만 (지금)", "R1": "1시간 + 4시간 찾은 값(50·4.5)", "R2": "1시간 + 4시간 기본값",
          "R3": "4시간 찾은 값 혼자", "R4": "4시간 기본값 혼자"}


def trades(W: H.World, cfg: dict, a: int, b: int) -> pd.DataFrame:
    T, _s = H.run(W, cfg, a, b)
    if not len(T):
        return pd.DataFrame(columns=["t", "ret", "roe", "reason", "coin", "src"])
    T = T.copy()
    T["ret"] = 0.40 * np.maximum(T["roe"].to_numpy(float), -1.0)
    return T


def window(T: pd.DataFrame) -> dict:
    r = T["ret"].to_numpy(float)
    return {"n": int(len(r)), "w": int((r > 0).sum()), "l": int((r <= 0).sum()), "x": float(np.prod(1 + r))}


def main(argv=None) -> int:
    bars, work, out = (argv or sys.argv[1:])[:3]
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    W = RB.world(bars, work)
    S.run_position = RB.ORIG_RUN_POSITION
    H.S.run_position = RB.ORIG_RUN_POSITION
    end = int(W.m5["BTCUSDT"]["ts"][-1]) + CM.FIVE
    res = {}
    for arm, src in ARMS.items():
        cfg = dict(RB.F1, sources=src)
        T = trades(W, cfg, CM.RUN_START, end)
        T.to_csv(os.path.join(out, f"range4h_trades_{arm}.csv.gz"), index=False)
        per = {p: CM.period_metrics(T, p) for p in CM.PERIODS}
        live = {k: window(trades(W, cfg, a, b)) for k, (a, b) in PK.LIVE.items()}
        live["oct"] = window(trades(W, cfg, *H.OCT))
        src_n = T["src"].value_counts().to_dict() if "src" in T else {}
        res[arm] = {"label": ARM_KO[arm], "sources": list(src), "periods": per, "live": live, "by_source": src_n}
        print(arm, ARM_KO[arm], {p: (d["trades"], round(d["median_month"], 4), d["months_up"]) for p, d in per.items()},
              {k: (v["w"], v["l"], round(v["x"], 3)) for k, v in live.items()}, src_n, f"{time.time() - t0:.0f}s", flush=True)
    verdict = {}
    for arm in ("R1", "R2"):
        c = CM.beats(res[arm]["periods"]["choose"], res["R0"]["periods"]["choose"])
        k = CM.beats(res[arm]["periods"]["check"], res["R0"]["periods"]["check"])
        verdict[arm] = {"beats_R0_choose": c, "beats_R0_check": k, "helps": bool(c and k)}
    out_d = {"arms": res, "verdicts": verdict}
    json.dump(CM.jsonable(out_d), open(os.path.join(out, "range4h.json"), "w"), indent=1, ensure_ascii=False)
    print(json.dumps(verdict, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
