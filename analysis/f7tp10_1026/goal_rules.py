"""Owners 10/26 ("내목표 수익률을 위해 다양하게 테스트해봐"): how often the leading set-ups of hunt.py reach the goal, x6 in 30 days,
and whether a simple month rule (no signal light) raises that: stop the month at x6 (keep the goal once reached), stop the month at
a floor (x0.5 / x0.7), a pause after a loss (12 / 24 h), a pause of 24 h after two losses in a row.
Read on every 30-day window starting each KST day from 2025-01-01 to 2026-09-25 (the window ends by the data's end) and on the
calendar months; the trades come from one continuous run of each set-up (hunt.run), a fresh wallet at each window's start.
Run: python3 goal_rules.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import hunt as H  # noqa: E402
import pick as PK  # noqa: E402

DAY, HOUR = 86_400_000, 3_600_000
RULES = {"규칙 없음": {}, "×6 닿으면 그 달 멈춤": {"lock": 6.0}, "×0.5 아래면 그 달 멈춤": {"floor": 0.5},
         "×0.7 아래면 그 달 멈춤": {"floor": 0.7}, "×6 멈춤 + ×0.5 멈춤": {"lock": 6.0, "floor": 0.5},
         "1패 뒤 12시간 쉼": {"cool": 12}, "1패 뒤 24시간 쉼": {"cool": 24}, "2연패 뒤 24시간 쉼": {"cool2": 24}}
SETUPS = {"추천: 1시간 · BTC · 한 신호씩 · 주말 쉼": dict(H.BASE, commit=True, btc=True),
          "1시간 · BTC · 한 신호씩 · 주말 포함": dict(H.BASE, commit=True, btc=True, weekend_off=False),
          "1시간 + 4시간 찾은 값 · BTC · 한 신호씩 · 주말 쉼": dict(H.BASE, commit=True, btc=True, sources=("1h_c", "4h_c")),
          "지금 구조(BTC 없음) · 한 신호씩 · 주말 쉼": dict(H.BASE, commit=True)}


def window(t, roe, ex, a, b, rule, m=0.40) -> tuple:
    """(end multiple, highest multiple) of a fresh wallet over trades entered in [a, b) under ``rule``."""
    eq, top, stop, pause, losses = 1.0, 1.0, False, -1, 0
    lo, hi = np.searchsorted(t, a), np.searchsorted(t, b)
    for i in range(lo, hi):
        if stop or t[i] < pause:
            continue
        eq *= 1 + m * max(roe[i], -1.0)
        top = max(top, eq)
        if roe[i] <= 0:
            losses += 1
            if rule.get("cool"):
                pause = ex[i] + rule["cool"] * HOUR
            if rule.get("cool2") and losses >= 2:
                pause, losses = ex[i] + rule["cool2"] * HOUR, 0
        else:
            losses = 0
        if (rule.get("lock") and eq >= rule["lock"]) or (rule.get("floor") and eq <= rule["floor"]):
            stop = True
    return eq, top


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--extra", default="", help="JSON file of {label: cfg} added to the set-ups (hunt.py stage E leaders)")
    a = ap.parse_args(argv)
    W = H.World(a.bars, a.work)
    setups = dict(SETUPS)
    if a.extra:
        for k, v in json.load(open(a.extra)).items():
            setups[k] = {kk: (tuple(vv) if isinstance(vv, list) else vv) for kk, vv in v.items()}
    t0 = H.kst_month("2025-01")[0]
    starts = np.arange(t0, H.ST.ms("2026-09-25 15:00") + 1, DAY)
    out = {}
    for sn, cfg in setups.items():
        T, s = H.run(W, cfg, t0, PK.END)
        t, roe = T.t.to_numpy(), T.roe.to_numpy()
        ex = (T.t + T.hold_h * HOUR).to_numpy()
        out[sn] = {"trades": s, "rules": {}}
        for rn, rule in RULES.items():
            ends, tops = zip(*(window(t, roe, ex, d, d + 30 * DAY, rule) for d in starts))
            ends, tops = np.array(ends), np.array(tops)
            months = [window(t, roe, ex, *H.kst_month(m), rule)[0] for m in H.MONTHS]
            octx = window(t, roe, ex, *H.OCT, rule)[0]
            oct_starts = (starts >= H.ST.ms("2026-08-26 15:00"))     # windows that end in October
            r = {"windows": int(len(starts)), "p_end_x6": float((ends >= 6).mean()), "p_touch_x6": float((tops >= 6).mean()),
                 "p_end_x2": float((ends >= 2).mean()), "p_loss": float((ends < 1).mean()), "median": float(np.median(ends)),
                 "p_half": float((ends <= 0.5).mean()), "months_x6": int(sum(x >= 6 for x in months)),
                 "months_x2": int(sum(x >= 2 for x in months)), "months_up": int(sum(x > 1 for x in months)),
                 "oct": float(octx), "late_windows_end_x6": float((ends[oct_starts] >= 6).mean()) if oct_starts.any() else None,
                 "late_windows_median": float(np.median(ends[oct_starts])) if oct_starts.any() else None}
            out[sn]["rules"][rn] = r
            print(f"{sn[:40]:40} | {rn:16} | 30일 ×6 끝 {r['p_end_x6'] * 100:.1f}% 닿음 {r['p_touch_x6'] * 100:.1f}% ×2 "
                  f"{r['p_end_x2'] * 100:.1f}% 손실 {r['p_loss'] * 100:.0f}% ≤×0.5 {r['p_half'] * 100:.0f}% 가운데 ×{r['median']:.2f} | "
                  f"달 ×6 {r['months_x6']} ×2 {r['months_x2']} 플러스 {r['months_up']}/21 | 10월 ×{octx:.2f} | 10월에 끝나는 창 ×6 "
                  f"{(r['late_windows_end_x6'] or 0) * 100:.0f}% 가운데 ×{r['late_windows_median']:.2f}", flush=True)
    # for information only (the owners' rule is margin 40 %): what the same trades give at a bigger margin
    sn = next(iter(SETUPS))
    T, s = H.run(W, SETUPS[sn], t0, PK.END)
    t, roe = T.t.to_numpy(), T.roe.to_numpy()
    ex = (T.t + T.hold_h * HOUR).to_numpy()
    out["margin"] = {}
    for m in (0.40, 0.60, 0.80, 1.00):
        ends, tops = map(np.array, zip(*(window(t, roe, ex, d, d + 30 * DAY, {}, m) for d in starts)))
        r = {"p_end_x6": float((ends >= 6).mean()), "p_touch_x6": float((tops >= 6).mean()), "p_bust": float((ends <= 0.05).mean()),
             "median": float(np.median(ends)), "oct": float(window(t, roe, ex, *H.OCT, {}, m)[0]),
             "rulebot": float(window(t, roe, ex, *PK.LIVE["rulebot"], {}, m)[0])}
        out["margin"][m] = r
        print(f"증거금 {m:.0%} | 30일 ×6 끝 {r['p_end_x6'] * 100:.1f}% 닿음 {r['p_touch_x6'] * 100:.1f}% | 사실상 파산(×0.05 이하) "
              f"{r['p_bust'] * 100:.0f}% | 가운데 ×{r['median']:.2f} | 10월 ×{r['oct']:.2f} | 규칙봇 기간 ×{r['rulebot']:.2f}", flush=True)
    json.dump(out, open(os.path.join(a.work, "goal_rules.json"), "w"), ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
