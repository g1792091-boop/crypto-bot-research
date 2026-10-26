"""친구봇: 나스닥 개장 · 횡보 대책 시험 (owners 10-26). The arms of OPENTIME_PREREG.md (= research/opentime/PREREG.md's
seven) on the friend bot's chosen live setup (both rules, 3 ATR stop, ladder 12/10/5), through the bot's own code
(study.run_window, paper mode, 1m bars): ArmBot.paper_bars is mixchop.Bot.paper_bars with the arm checked after each 1m
bar's own stop / ladder step.
    python3 -I research/mixchop_st/opentime_mix.py [--jobs 2]  ->  research/mixchop_st/opentime_mix.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import grid as Gd  # noqa: E402  (study, replay and the repository on sys.path)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

S, R, M = Gd.S, Gd.R, Gd.M
from paperbot.sessions import NYSE_HOLIDAYS  # noqa: E402

OUT = os.path.join(HERE, "opentime_mix.json")
NY = ZoneInfo("America/New_York")
ARMS = ("A0", "A1", "A2", "A3", "A4", "A5", "A6")
HOURS = {"A3": 4, "A4": 8, "A5": 12}
LADDER = (12, 10, 5)
KST_MS = 9 * 3_600_000
CHOOSE, CHECK = ("2021-10", "2023-12"), ("2024-01", "2026-09")


def open_marks(first: date, last: date) -> set:
    """Every M: 09:30:00 New York (UTC ms) of a Monday-Friday that is not in NYSE_HOLIDAYS."""
    out, d = set(), first
    while d <= last:
        if d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS:
            out.add(int(datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY).timestamp() * 1000))
        d += timedelta(days=1)
    return out


MARKS = open_marks(date(2021, 9, 1), date(2026, 11, 1))


class ArmBot(R.ReplayBot):
    """ReplayBot with the arm (``self.arm``, set by study.run_window) checked after each 1m bar."""
    arm = "A0"

    def paper_bars(self, close_ms: int) -> None:
        p = self.pos
        new_bars, tf = self.bars_since(p, close_ms)
        for _, bar in new_bars.iterrows():
            hit = bar.low <= p.stop if p.side > 0 else bar.high >= p.stop
            if hit:
                px = min(bar.open, p.stop) if p.side > 0 else max(bar.open, p.stop)
                self.finish(p, px, "ladder" if p.step > 0 else ("be_stop" if getattr(p, "be", False) else "stop"))
                return
            p.best = max(p.best, bar.high) if p.side > 0 else min(p.best, bar.low)
            p.last_bar_ms = int(bar.open_ms) + tf
            new, step = self.ladder_for(p)
            if step > 0 and new != p.stop:
                self.log("ladder", symbol=p.symbol, old=p.stop, new=new, step=step, best=p.best)
                p.stop, p.step = new, step
            if self.arm != "A0" and p.step <= 0 and self.apply_arm(p, float(bar.close), int(bar.open_ms) + tf):
                return
        self.save()

    def apply_arm(self, p, close: float, end_ms: int) -> bool:
        """True when the arm closed the position at ``close`` (the 1m bar ending at ``end_ms``)."""
        if self.arm in HOURS:
            if end_ms - int(p.opened_ms) >= HOURS[self.arm] * 3_600_000:
                self.finish(p, close, "time")
                return True
            return False
        if end_ms not in MARKS:
            return False
        fee = self.cfg.taker_fee
        net = p.side * (close / p.entry - 1.0) - 2 * fee
        if self.arm == "A1" or (self.arm == "A6" and net <= 0):
            self.finish(p, close, "open_close")
            return True
        if self.arm in ("A2", "A6") and net > 0:
            be = p.entry * (1 + p.side * 2 * fee)
            if (p.side > 0 and be > p.stop) or (p.side < 0 and be < p.stop):
                self.log("be_raise", symbol=p.symbol, old=p.stop, new=be)
                p.stop, p.be = be, True
        return False


def month_bounds_kst(first: str, last: str, data_from: int) -> list:
    out = []
    y, m = map(int, first.split("-"))
    while f"{y:04d}-{m:02d}" <= last:
        a = int(pd.Timestamp(f"{y:04d}-{m:02d}-01", tz="UTC").value // 1_000_000) - KST_MS
        y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
        b = int(pd.Timestamp(f"{y2:04d}-{m2:02d}-01", tz="UTC").value // 1_000_000) - KST_MS
        out.append((max(a, data_from), b))
        y, m = y2, m2
    return out


def stats(res: list) -> dict:
    xs = np.array([r["end_eq"] / 50.0 for r in res])
    ts = [t for r in res for t in r["trades"]]
    lg = float(sum(np.log(max(1e-12, 1 + t["ret"])) for t in ts))
    touched = sum(1 for t in ts if t["why"] in ("time", "open_close"))
    return {"months": len(xs), "median_x": round(float(np.median(xs)), 3), "log_growth": round(lg, 3),
            "up_months": int((xs > 1).sum()), "worst_x": round(float(xs.min()), 3), "trades": len(ts),
            "win": round(float(np.mean([t["ret"] > 0 for t in ts])), 3) if ts else None,
            "mean_ret_pct": round(float(np.mean([t["ret"] for t in ts]) * 100), 3) if ts else None,
            "closed_by_arm": touched, "be_stop_exits": sum(1 for t in ts if t["why"] == "be_stop"),
            "exits": {k: sum(1 for t in ts if t["why"] == k) for k in sorted({t["why"] for t in ts})}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--months", type=int, default=0, help="smoke test: the first n months only")
    a = ap.parse_args(argv)
    t0 = time.time()
    cfg = M.load_config(R.CONFIG)
    coins = list(cfg.coins)
    a30 = {c.symbol: R.read_klines(R.DATA, c.symbol, "30m") for c in coins}
    a1h = {c.symbol: R.read_klines(R.DATA, c.symbol, "1h") for c in coins}
    mos = [m for m in R.months() if "2021-10" <= m <= "2026-09"]
    m1 = {c.symbol: S.read_1m(R.DATA, c.symbol, mos) for c in coins}
    friend, _ = S.friend_decisions(coins, a30, a1h, os.path.join(R.DATA, "npy", "friend_decisions_v2.pkl"))
    lo, hi = R.T0 - 2 * 86_400_000, R.T1 + 30 * 86_400_000
    new = {c.symbol: S.new_signals(c, a30[c.symbol], a1h[c.symbol], S.MAIN, lo, hi) for c in coins}
    specs = [(arm, "both", 3.0, 3.0, LADDER, None) for arm in ARMS]
    S.G.update(coins=coins, bars30=a30, m1=m1, bot_cls=ArmBot, arm_of={arm: arm for arm in ARMS})
    Gd.plan(coins, new, friend, specs)
    data_from = int(min(m[0, 0] for m in m1.values()))
    windows = month_bounds_kst(CHOOSE[0], CHECK[1], data_from)
    if a.months:
        windows = windows[:a.months]
    res = Gd.run_names(list(ARMS), windows, a.jobs)
    print(f"runs {time.time() - t0:.0f}s", flush=True)
    kst_month = lambda r: time.strftime("%Y-%m", time.gmtime((r["t0"] + KST_MS) / 1000))  # noqa: E731
    out = {"prereg": "research/mixchop_st/OPENTIME_PREREG.md", "setup": "both rules, stop ATR x3, ladder 12/10/5",
           "arms": {}}
    for arm in ARMS:
        rs = sorted(res[arm], key=lambda r: r["t0"])
        ch = [r for r in rs if CHOOSE[0] <= kst_month(r) <= CHOOSE[1]]
        ck = [r for r in rs if CHECK[0] <= kst_month(r) <= CHECK[1]]
        out["arms"][arm] = {"choose": stats(ch) if ch else None, "check": stats(ck) if ck else None,
                            "by_month": [[kst_month(r), round(r["end_eq"] / 50.0, 3), len(r["trades"])] for r in rs]}
    base = out["arms"]["A0"]
    for arm in ARMS:
        x = out["arms"][arm]
        if arm == "A0" or not (x["choose"] and x["check"]):
            continue
        beats = []
        for per in ("choose", "check"):
            mine, ref = x[per], base[per]
            if abs(mine["median_x"] - ref["median_x"]) > 1e-12:
                beats.append(mine["median_x"] > ref["median_x"])
            else:
                beats.append(mine["log_growth"] > ref["log_growth"])
        x["helps"] = all(beats)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for arm in ARMS:
        x = out["arms"][arm]
        c, k = x["choose"], x["check"]
        if not (c and k):
            print(arm, json.dumps(c or k, ensure_ascii=False)[:300], flush=True)
            continue
        print(f"{arm} 고른 기간 med x{c['median_x']:<6} log {c['log_growth']:<8} up {c['up_months']:>2}/{c['months']} | "
              f"확인 med x{k['median_x']:<6} log {k['log_growth']:<8} up {k['up_months']:>2}/{k['months']} | "
              f"거래 {c['trades'] + k['trades']} 규칙이 닫음 {c['closed_by_arm'] + k['closed_by_arm']} "
              f"본전손절 {c['be_stop_exits'] + k['be_stop_exits']} 도움 {x.get('helps', '-')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
