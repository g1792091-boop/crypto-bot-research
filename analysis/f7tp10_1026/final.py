"""Owners 10/26: "정말 성공하고 싶어 그나마 내 1달 목표 수익률에 가능성이 있는 조합으로 돌리고 싶어 제대로 알아봐줘". Checks of the set-up
chosen on the two live windows (pullback entry, TP +10 %, stop -50 %, BTC 40x / others 30x, margin 40 %, NYSE-open and macro blocks):
  A. its neighbourhood on the two live windows: pullback 0.15 .. 0.35 ATR, wait 1 .. 3 h, TP 8 .. 12 %, stop -45 .. -55 %, the 1h
     V3.9 supertrend check on / off, weekend on / off (a set-up is only as good as its neighbours);
  B. the recent months before the windows (2026-06 .. 2026-09, a fresh wallet each KST month) and October (10/01 ~ data end);
  C. the coin-flip twin on the two live windows (the same signals, a random side, 200 draws);
  D. the chance of x6 in 30 days, resampling the set-up's own trades (live windows; recent months).
Run: python3 final.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import pick as PK  # noqa: E402
import structure as SR  # noqa: E402
import study as ST  # noqa: E402
import timing as TM  # noqa: E402

KST = 9 * 3_600_000
MONTHS = ("2026-06", "2026-07", "2026-08", "2026-09")


def kst_month(m: str) -> tuple:
    a = pd.Timestamp(f"{m}-01 00:00", tz="Asia/Seoul")
    return int(a.value // 1_000_000), int((a + pd.offsets.MonthBegin(1)).value // 1_000_000)


def setup_kw(k, wait, tp, stop, trend, wk):
    return dict(trend="st1h" if trend else None, mode=("pull", k, wait), tp_roe=tp, stop=("roe", stop), weekend_off=wk)


def trades(W, cand, kw, a, b):
    T, s = TM.run(W, cand, a=a, b=b, **kw)
    return T, s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = SR.add_trend(W, pd.read_pickle(os.path.join(a.work, "cand.pkl")), a.work)
    out = {"A": [], "B": {}, "C": {}, "D": {}}
    # A. the neighbourhood
    grid = itertools.product((0.15, 0.20, 0.25, 0.30, 0.35), (1, 1.5, 2, 3), (0.08, 0.09, 0.10, 0.11, 0.12), (0.45, 0.50, 0.55),
                             (True, False), (True, False))
    for k, wait, tp, stop, trend, wk in grid:
        kw = setup_kw(k, wait, tp, stop, trend, wk)
        r = {"k": k, "wait": wait, "tp": tp, "stop": stop, "trend": trend, "weekend_off": wk}
        for wn, (wa, wb) in PK.LIVE.items():
            r[wn] = trades(W, cand, kw, wa, wb)[1]
        r["score"] = min(r["rulebot"]["x"], r["league"]["x"])
        out["A"].append(r)
    print("A done", len(out["A"]), flush=True)
    # B / C / D for a short list: the live leader, and the centre of each family
    short = {"L1 1시간 슈퍼트렌드 · 주말 포함": setup_kw(0.25, 2, 0.10, 0.50, True, False),
             "L2 1시간 슈퍼트렌드 · 주말 쉼": setup_kw(0.25, 2, 0.10, 0.50, True, True),
             "L3 추세 없음 · 주말 포함": setup_kw(0.25, 2, 0.10, 0.50, False, False),
             "L4 추세 없음 · 주말 쉼": setup_kw(0.25, 2, 0.10, 0.50, False, True),
             "L0 지금 구조(바로 진입 · 주말 쉼 · 추세 없음)": dict(trend=None, mode=("now",), tp_roe=0.10, stop=("roe", 0.50),
                                                    weekend_off=True)}
    for name, kw in short.items():
        b = {}
        pool = []
        for m in MONTHS:
            T, s = trades(W, cand, kw, *kst_month(m))
            b[m] = s
            pool += list(T.roe) if len(T) else []
        T, s = trades(W, cand, kw, ST.ms("2026-09-30 15:00"), PK.END)
        b["2026-10"] = s
        out["B"][name] = b
        live = []
        for wn, (wa, wb) in PK.LIVE.items():
            T, s = trades(W, cand, kw, wa, wb)
            if wn == "rulebot":
                live = list(T.roe)
                per_day = len(T) / ((wb - wa) / 86_400_000)
        rng = np.random.default_rng(20261026)
        flips = []
        for _ in range(200):
            flips.append(TM.run(W, cand, a=PK.LIVE["rulebot"][0], b=PK.LIVE["rulebot"][1], flip_rng=rng, **kw)[1]["x"])
        own = TM.run(W, cand, a=PK.LIVE["rulebot"][0], b=PK.LIVE["rulebot"][1], **kw)[1]["x"]
        out["C"][name] = {"own": own, "flip_median": float(np.median(flips)), "flip_p95": float(np.percentile(flips, 95)),
                          "beats": float(np.mean(np.array(flips) < own))}
        # D: x6 in 30 days by resampling the set-up's own trades at its own pace
        d = {}
        days_pool = sum((kst_month(m)[1] - kst_month(m)[0]) / 86_400_000 for m in MONTHS)
        for src, pool_, pace in (("live", live, per_day), ("recent4m", pool, len(pool) / days_pool)):
            if len(pool_) < 5:
                d[src] = None
                continue
            n = max(1, int(round(pace * 30)))
            draws = rng.choice(np.array(pool_), size=(20_000, n))
            x = np.prod(1 + 0.40 * np.maximum(draws, -1.0), axis=1)
            d[src] = {"trades_30d": n, "win": float(np.mean(np.array(pool_) > 0)), "p_x6": float(np.mean(x >= 6)),
                      "p_x2": float(np.mean(x >= 2)), "p_loss": float(np.mean(x < 1)), "median": float(np.median(x))}
        out["D"][name] = d
        print(name, json.dumps({"B": b, "C": out["C"][name], "D": d}, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(a.work, "final.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
