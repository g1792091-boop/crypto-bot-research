"""Owners 10/26: "익절은 고정 10%, 손절은 -50%로 가는게 맞을까? 계단 22->20 이 수익률 제일 높은데?" The leaders of pick.py read from
more sides: every start day in October (to the data's end), the rule bot window's halves, losses and streaks, and five years by
KST month (x6 months, median month, losing months).
Run: python3 tp_vs_ladder.py --bars FIVE5M_DIR --work WORK_DIR"""
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

KST = 9 * 3_600_000
CANDS = {
    "고정 +10% · −50% · 주말 쉼": ("고정 +10%", "주말 쉼"),
    "고정 +10% · −50% · 주말 포함": ("고정 +10%", "주말 포함"),
    "계단 22→20 · −50% · 주말 포함": ("계단 22→20·27→25…", "주말 포함"),
    "계단 22→20 · −50% · 주말 쉼": ("계단 22→20·27→25…", "주말 쉼"),
    "계단 12→10 · −50% · 주말 쉼": ("계단 12→10·17→15…", "주말 쉼"),
}


def arm_of(exit_name: str, wk: str) -> dict:
    return {**PK.SIZE, **PK.EXITS[exit_name], **PK.STOPS["순ROE −50%"],
            "filters": (PK.FIXED,) if wk == "주말 포함" else (PK.FIXED, PK.NOWK)}


def streak(roe) -> int:
    best = cur = 0
    for x in roe:
        cur = cur + 1 if x <= 0 else 0
        best = max(best, cur)
    return best


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = pd.read_pickle(os.path.join(a.work, "cand.pkl"))
    out = {}
    for name, (en, wk) in CANDS.items():
        arm = arm_of(en, wk)
        r = {}
        # every start day 10/01 .. 10/18 (KST 09:00) to the data's end
        starts = [int(pd.Timestamp(f"2026-10-{d:02d} 09:00", tz="Asia/Seoul").value // 1_000_000) for d in range(1, 19)]
        xs = [PK.read(ST.run_arm(W, cand, arm, s, PK.END))["x"] for s in starts]
        r["start_any_day"] = {"median": float(np.median(xs)), "worst": float(min(xs)), "best": float(max(xs)),
                              "below_1": int(sum(x < 1 for x in xs)), "n": len(xs)}
        a0, b0 = PK.LIVE["rulebot"]
        mid = a0 + (b0 - a0) // 2
        r["rulebot_first_half"] = PK.read(ST.run_arm(W, cand, arm, a0, mid))
        r["rulebot_second_half"] = PK.read(ST.run_arm(W, cand, arm, mid, b0))
        T = ST.run_arm(W, cand, arm, a0, b0)
        C = T[T.reason != "END"]
        r["rulebot_streak"] = streak(C.roe.to_numpy())
        r["rulebot_avg_win"] = float(C.roe[C.roe > 0].mean())
        r["rulebot_avg_loss"] = float(C.roe[C.roe <= 0].mean())
        # five years by KST month, fresh wallet each month (the shadow: tiny margin so nothing busts)
        sh = dict(arm, margin=lambda c: 1e-9)
        S5 = ST.run_arm(W, cand, sh, ST.ms("2021-01-01"), ST.ms("2026-10-01"))
        S5["month"] = pd.to_datetime(S5.t + KST, unit="ms").dt.strftime("%Y-%m")
        mo = {}
        for m, g in S5.groupby("month"):
            eq = 1.0
            for x in g.roe.to_numpy():
                eq *= 1 + 0.40 * max(x, -1.0)
                if eq < 0.01:
                    break
            mo[m] = eq
        s = pd.Series(mo).reindex(pd.period_range("2021-01", "2026-09", freq="M").strftime("%Y-%m")).fillna(1.0)
        r["five_year_months"] = {"months": int(len(s)), "x6": int((s >= 6).sum()), "x2": int((s >= 2).sum()),
                                 "up": int((s > 1).sum()), "half_or_worse": int((s <= 0.5).sum()), "median": float(s.median()),
                                 "best": float(s.max())}
        r["five_year_trade"] = {"n": int(len(S5)), "win": float((S5.roe > 0).mean()), "mean_roe": float(S5.roe.mean()),
                                "avg_win": float(S5.roe[S5.roe > 0].mean()), "avg_loss": float(S5.roe[S5.roe <= 0].mean())}
        out[name] = r
        print(name, json.dumps(r, ensure_ascii=False, default=float), flush=True)
    json.dump(out, open(os.path.join(a.work, "tp_vs_ladder.json"), "w"), indent=1, ensure_ascii=False, default=float)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
