"""Owners 10/26: "이 매매법 추가하고 싶은데 내 목표 수익률이 나오긴 나왔네? 어떤식으로 보완하는게 내 목표 수익률에 근접할수 있을까?"
The goal: 한 달 ×6 (paperbot/dash/more/livegoalres.py). Every KST calendar month starts a fresh wallet; a month counts when the
wallet reached x6 by its end.

Shadows (the trade lists, no bust, every signal the rule allows; the wallet barely moves so the league's sizing check reads
the same $1,000 each time), then each month compounded at a margin share:
  photo   the league account (30x, league sizing check, stop 2 ATR, TP net +10 %)
  dayside photo + the daily judge on the trade's side (3 of 4)
Lights (a real trade only when the shadow's own last K closed trades won at least W; the trade itself is the shadow's):
  L10/8, L10/9, L5/5.
Chosen on 2021-2023 only; 2024-2026.09 read once; 2026-10 (to 10/25) only read.
Run: python3 goal.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import study as ST  # noqa: E402

KST = 9 * 3_600_000
SPAN = (ST.ms("2020-03-01"), ST.ms("2026-10-25"))
PERIODS = {"2021-2023": ("2021-01", "2023-12"), "2024-2026.09": ("2024-01", "2026-09"), "2026-10": ("2026-10", "2026-10")}
LIGHTS = {"none": None, "L10/8": (10, 8), "L10/9": (10, 9), "L5/5": (5, 5)}
MARGINS = (0.30, 0.40)
TINY = lambda c: 1e-9  # noqa: E731


def shadow(W, cand, extra_filters=()) -> pd.DataFrame:
    arm = dict(exit="tp10", lev=ST.LEV30, margin=TINY, league_check=True, filters=tuple(extra_filters))
    T = ST.run_arm(W, cand, arm, *SPAN)
    T["month"] = pd.to_datetime(T.t + KST, unit="ms").dt.strftime("%Y-%m")
    return T.reset_index(drop=True)


def lit(T: pd.DataFrame, light) -> np.ndarray:
    """True where the real account takes the shadow's trade: the last K shadow trades CLOSED before this entry won >= W."""
    if light is None:
        return np.ones(len(T), bool)
    k, w = light
    win = (T.roe > 0).to_numpy()
    ex, t = T.exit_t.to_numpy(), T.t.to_numpy()
    out = np.zeros(len(T), bool)
    for i in range(len(T)):
        done = np.flatnonzero(ex[:i] <= t[i])          # one position: every earlier trade has closed
        last = done[-k:]
        out[i] = len(last) == k and win[last].sum() >= w
    return out


def months(T: pd.DataFrame, take: np.ndarray, m: float) -> pd.Series:
    x = {}
    for mo, g in T[take].groupby("month"):
        eq = 1.0
        for r in g.roe.to_numpy():
            eq *= 1 + m * max(r, -1.0)
            if eq < 0.01:
                break
        x[mo] = eq
    return pd.Series(x, dtype=float)


def read(series: pd.Series, a: str, b: str) -> dict:
    allm = pd.period_range(a, b, freq="M").strftime("%Y-%m")
    s = series.reindex(allm).fillna(1.0)               # a month without a trade stays x1
    return {"months": int(len(s)), "x6": int((s >= 6).sum()), "x2": int((s >= 2).sum()), "up": int((s > 1).sum()),
            "half_or_worse": int((s <= 0.5).sum()), "median": float(s.median()),
            "geo_mean": float(math.exp(np.log(np.maximum(s, 1e-6)).mean())), "best": float(s.max()), "worst": float(s.min())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = pd.read_pickle(os.path.join(a.work, "cand.pkl"))
    shadows = {"photo": shadow(W, cand), "dayside": shadow(W, cand, (lambda g: g.jd_raw == g.side,))}
    res = {}
    for sn, T in shadows.items():
        T.to_pickle(os.path.join(a.work, f"shadow_{sn}.pkl"))
        for ln, light in LIGHTS.items():
            take = lit(T, light)
            for m in MARGINS:
                key = f"{sn}|{ln}|m{int(m * 100)}"
                s = months(T, take, m)
                res[key] = {p: read(s, *ab) for p, ab in PERIODS.items()}
                res[key]["trades_per_month"] = {p: float(take[(T.month >= ab[0]) & (T.month <= ab[1])].sum()
                                                         / len(pd.period_range(*ab, freq="M"))) for p, ab in PERIODS.items()}
                res[key]["win"] = {p: float((T.roe[take & (T.month >= ab[0]) & (T.month <= ab[1])] > 0).mean())
                                   for p, ab in PERIODS.items()}
                r = res[key]
                print(f"{key:22} " + " | ".join(
                    f"{p}: x6 {r[p]['x6']}/{r[p]['months']} x2 {r[p]['x2']} up {r[p]['up']} <=x0.5 {r[p]['half_or_worse']} "
                    f"med x{r[p]['median']:.2f} win {r['win'][p] * 100:.0f}% n/mo {r['trades_per_month'][p]:.0f}"
                    for p in PERIODS), flush=True)
    json.dump(res, open(os.path.join(a.work, "goal.json"), "w"), indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
