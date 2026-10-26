"""친구봇 새 매매법의 계단 폭 · 손절 폭 시험 (owners 10-26: "이번 친구 봇 추가하는 매매법 계단 폭 시험해줘 손절 폭도").

The new rule of study.py (supertrend 14/3 + 14/6, Stoch RSI 14/11/4/5 cross, RSI 26 on 30m and the closed 1h) through the
friend bot's own code (study.run_window: paper mode, the live config) with every pair of
  ladder (net ROE %: trigger -> lock, then +step a step) in LADDERS  x  stop in STOPS
(stop: the coin's own sl_atr x ATR(14, 30m) as now, a uniform ATR multiple, or the supertrend(14, 3) line; the liquidation
guard of evaluate() drops a signal whose stop is past the coin's leverage less 0.5 %). Leverage, margin 40 %, entry
blocks, fees, one position and the coins are the live config's.

Fixed before the results (selection):
- months 2021-10 .. 2024-09 (36) choose: the pair with the highest median monthly multiple (each month from $50, the 70 %
  floor off), the geometric mean breaking a tie;
- months 2024-10 .. 2026-09 (24) and the 20 days 2026-10-05 .. 10-25 check it; nothing is chosen on them.
- the three best pairs of the choosing months get: the coin-flip control (their signal bars, a seeded random side,
  3 seeds), the friend's rule alone with that ladder (its own stop, and that stop), and both rules (the friend's
  first) the same two ways.
    python3 -I research/mixchop_st/grid.py [--jobs 4]  ->  research/mixchop_st/grid.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import study as S  # noqa: E402  (puts the repository and the replay tools on sys.path)

from concurrent.futures import ProcessPoolExecutor  # noqa: E402

import numpy as np  # noqa: E402

R, M = S.R, S.M
OUT = os.path.join(HERE, "grid.json")
LADDERS = [(12, 10, 5), (20, 15, 5), (30, 25, 5), (30, 20, 10), (50, 40, 10), (50, 30, 10), (80, 60, 20), (100, 80, 20),
           (100, 50, 25), (150, 120, 30), (200, 150, 50), (300, 250, 50)]
STOPS = ["coin", 1.0, 1.5, 2.0, 2.5, 3.0, "st"]
SPLIT = "2024-10"                                   # months before: choose; from: check
SEEDS = (1, 2, 3)


def lname(lad) -> str:
    return "L{}-{}-{}".format(*lad)


def sname(st) -> str:
    return st if isinstance(st, str) else f"x{st:g}"


def stopped(ev: dict, co, st, side: int) -> dict:
    """``ev`` with the stop ``st`` and evaluate()'s liquidation guard; side 0 when the stop is past liquidation."""
    e = dict(ev)
    px = float(e["close"])
    if st == "coin":
        dist = float(e["atr"]) * co.sl_atr
    elif st == "st":
        dist = float(e["dist_st"])
    else:
        dist = float(e["atr"]) * float(st)
    e["stop_dist"], e["stop_pct"] = dist, round(dist / px * 100, 3)
    e["liq_ok"] = bool(0 < dist < px * (1.0 / co.leverage - M.MMR_PCT / 100.0))
    e["side"] = side if e["liq_ok"] else 0
    if not e["liq_ok"]:
        e["why"] = f"손절 폭 {dist / px * 100:.2f}%가 {co.leverage}배 청산가보다 멂"
    return e


def friend_wanted(ev: dict) -> int:
    """The friend's side at a colour change before the liquidation guard (0: its RSI conditions said no)."""
    if ev.get("side"):
        return int(ev["side"])
    if str(ev.get("why", "")).startswith("손절 폭"):
        return 1 if ev.get("to_cyan") else -1
    return 0


def decisions(coins, new: dict, friend: dict, rules: str, new_stop, friend_stop, seed=None) -> dict:
    """{sym: {close_ms: ev}} for ``rules`` = new | friend | both (the friend's answer first on a bar)."""
    out = {}
    for co in coins:
        d = {}
        if rules in ("new", "both"):
            rng = np.random.default_rng(seed) if seed is not None else None
            for t, e in sorted(new[co.symbol].items()):
                side = int(e["side"]) if rng is None else int(rng.choice([-1, 1]))
                d[t] = stopped(e, co, new_stop, side)
        if rules in ("friend", "both"):
            for t, e in friend[co.symbol].items():
                side = friend_wanted(e)
                if not side:
                    continue
                f = stopped(e, co, friend_stop, side) if friend_stop != "own" else dict(e)
                if f["side"]:
                    d[t] = f
        out[co.symbol] = d
    return out


def plan(coins, new, friend, specs) -> None:
    """S.G's answers, ladders and answer keys for ``specs``: [(name, rules, new_stop, friend_stop, ladder, seed)]."""
    S.G["decided"], S.G["dec_of"], S.G["ladder_of"] = {}, {}, {}
    for name, rules, ns, fs, lad, seed in specs:
        key = f"{rules}|{ns}|{fs}|{seed}"
        if key not in S.G["decided"]:
            S.G["decided"][key] = decisions(coins, new, friend, rules, ns, fs, seed)
        S.G["dec_of"][name] = key
        S.G["ladder_of"][name] = {"trigger": float(lad[0]), "lock": float(lad[1]), "step": float(lad[2])}


def run_names(names: list, windows: list, jobs: int) -> dict:
    """study.run_window for every name and window, in forked workers that share S.G (set up by plan())."""
    work = [(n, a, b) for n in names for a, b in windows]
    with ProcessPoolExecutor(jobs) as ex:
        res = list(ex.map(S._job, work, chunksize=4))
    out: dict = {}
    for r in res:
        out.setdefault(r["variant"], []).append(r)
    return out


def split_stats(res: list) -> dict:
    """study.summarize on the choosing months, the checking months, and all."""
    a = [r for r in res if time.strftime("%Y-%m", time.gmtime(r["t0"] / 1000)) < SPLIT]
    b = [r for r in res if time.strftime("%Y-%m", time.gmtime(r["t0"] / 1000)) >= SPLIT]
    out = {}
    for k, part in (("choose", a), ("check", b), ("all", res)):
        s = S.summarize(part) if part else None
        if s:
            s.pop("by_month", None)
        out[k] = s
    out["by_month"] = [[time.strftime("%Y-%m", time.gmtime(r["t0"] / 1000)), round(r["end_eq"] / 50.0, 3), len(r["trades"])]
                       for r in res]
    return out


def line(name: str, st: dict, d20: dict | None) -> str:
    c, k = st["choose"], st["check"]
    w = f"20일 x{d20['median_x']:<6}" if d20 else ""
    return (f"{name:34s} 고른3년 med x{c['median_x']:<6} geo x{c['geo_x']:<6} up {c['up_months']:>2}/36 | "
            f"확인2년 med x{k['median_x']:<6} geo x{k['geo_x']:<6} up {k['up_months']:>2}/24 x2 {k['x2_months']:>2} | "
            f"{w} 거래/월 {st['all']['trades_per_month']:<6} 승률 {st['all']['win']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=R.DATA)
    ap.add_argument("--data20", default=os.path.join(R.SCRATCH, "mixchop20d_data"))
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args(argv)
    t_start = time.time()
    cfg = M.load_config(R.CONFIG)
    coins = list(cfg.coins)
    # ---------------------------------------------------------------- data: 5 years, then the 20 days
    a30 = {c.symbol: R.read_klines(a.data, c.symbol, "30m") for c in coins}
    a1h = {c.symbol: R.read_klines(a.data, c.symbol, "1h") for c in coins}
    mos = [m for m in R.months() if "2021-10" <= m <= "2026-09"]
    m1 = {c.symbol: S.read_1m(a.data, c.symbol, mos) for c in coins}
    friend, _ = S.friend_decisions(coins, a30, a1h, os.path.join(a.data, "npy", "friend_decisions_v2.pkl"))
    lo, hi = R.T0 - 2 * 86_400_000, R.T1 + 30 * 86_400_000
    new = {c.symbol: S.new_signals(c, a30[c.symbol], a1h[c.symbol], S.MAIN, lo, hi) for c in coins}

    import ladder20 as L
    b30 = {c.symbol: L.read(a.data20, c.symbol, "30m") for c in coins}
    b1h = {c.symbol: L.read(a.data20, c.symbol, "1h") for c in coins}
    b1m = {c.symbol: L.read(a.data20, c.symbol, "1m") for c in coins}
    keep = R.T0, R.T1
    R.T0, R.T1 = L.T0, L.T1
    friend20 = {}
    for c in coins:
        d, _ = R.decisions(c, b30[c.symbol], b1h[c.symbol], sample=10)
        for e in d.values():
            e["rule"] = "friend"
        friend20[c.symbol] = d
    R.T0, R.T1 = keep
    new20 = {c.symbol: S.new_signals(c, b30[c.symbol], b1h[c.symbol], S.MAIN, L.T0 - 86_400_000, L.T1) for c in coins}
    print(f"data {time.time() - t_start:.0f}s", flush=True)

    def run(specs):
        S.G.update(coins=coins, bars30=a30, m1=m1)
        plan(coins, new, friend, specs)
        five = run_names([n for n, *_ in specs], S.month_bounds(), a.jobs)
        S.G.update(bars30=b30, m1=b1m)
        plan(coins, new20, friend20, specs)
        d20 = run_names([n for n, *_ in specs], [(L.T0, L.T1)], a.jobs)
        return ({n: split_stats(r) for n, r in five.items()},
                {n: {**{k: v for k, v in S.summarize(r).items() if k != "by_month"}} for n, r in d20.items()})

    # ---------------------------------------------------------------- the grid (the new rule alone)
    specs = [(f"B {lname(l)} {sname(s)}", "new", s, "own", l, None) for l in LADDERS for s in STOPS]
    grid5, grid20 = run(specs)
    print(f"grid {time.time() - t_start:.0f}s", flush=True)
    rank = sorted(grid5, key=lambda n: (grid5[n]["choose"]["median_x"], grid5[n]["choose"]["geo_x"]), reverse=True)
    for n in rank:
        print(line(n, grid5[n], grid20.get(n)), flush=True)
    top = rank[:3]
    # ---------------------------------------------------------------- the three chosen: controls and the friend's rule
    more = []
    for n in top:
        _, _, s, _, l, _ = next(x for x in specs if x[0] == n)
        tag = f"{lname(l)} {sname(s)}"
        more += [(f"flip{sd} {tag}", "new", s, "own", l, sd) for sd in SEEDS]
        more += [(f"A {lname(l)} 친구손절", "friend", s, "own", l, None),
                 (f"C {lname(l)} 친구손절+{sname(s)}", "both", s, "own", l, None)]
        if s != "st":                                   # the friend's answers have no supertrend line
            more += [(f"A {tag}", "friend", s, s, l, None), (f"C {tag}", "both", s, s, l, None)]
    more += [("A 지금 L12-10-5 친구손절", "friend", "coin", "own", (12, 10, 5), None)]
    seen, uniq = set(), []
    for x in more:
        if x[0] not in seen:
            seen.add(x[0])
            uniq.append(x)
    more5, more20 = run(uniq)
    print("\n== the three chosen, controls, the friend's rule", flush=True)
    for n in top:
        print(line(n, grid5[n], grid20.get(n)), flush=True)
    for n in more5:
        print(line(n, more5[n], more20.get(n)), flush=True)
    chk = [grid5[n]["check"]["median_x"] for n in grid5]
    out = {"rule": "study.py MAIN (supertrend 14/3 + 14/6, Stoch RSI 14/11/4/5 cross, RSI26 30m + closed 1h)",
           "ladders": LADDERS, "stops": STOPS, "choose_months": f"2021-10 .. {SPLIT} (before)", "check_months": f"{SPLIT} .. 2026-09",
           "chosen": top, "grid_check_median_above_1": int(sum(x > 1 for x in chk)), "grid_cells": len(chk),
           "grid": grid5, "grid_20d": grid20, "more": more5, "more_20d": more20}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"cells with check-period median > x1: {out['grid_check_median_above_1']}/{len(chk)}; total {time.time() - t_start:.0f}s",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
