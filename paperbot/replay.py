"""Replay recorded bars and signals through the paper engine.

Used to check that the paper engine reproduces backtest trades before going
live, and to run what-if comparisons on the same signals.

    python -m paperbot.replay --bars DIR --signals signals.csv \
        [--funding funding.csv] [--brackets brackets.json] [--out out.json]

bars DIR: one CSV per symbol named <SYMBOL>.csv with columns
    open_time,close_time,open,high,low,close[,mark_open,mark_high,mark_low,mark_close]
signals.csv columns:
    ts,symbol,timeframe,strategy_id,side,stop_price[,tier,score,tp_roe,atr]
funding.csv columns: ts,symbol,rate   (ts = settlement time, ms)
brackets.json: Binance GET /fapi/v1/leverageBracket response (list)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from typing import Iterable, Optional

from .config import Settings
from .engine import PaperEngine
from .margin import Brackets
from .models import Bar, Signal


def _f(row: dict, key: str) -> Optional[float]:
    v = row.get(key)
    return float(v) if v not in (None, "") else None


def load_bars(directory: str, symbols: Iterable[str]) -> dict[str, list[Bar]]:
    out = {}
    for sym in symbols:
        path = os.path.join(directory, f"{sym}.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="") as fh:
            out[sym] = [Bar(sym, int(r["open_time"]), int(r["close_time"]),
                            float(r["open"]), float(r["high"]), float(r["low"]),
                            float(r["close"]), _f(r, "mark_open"), _f(r, "mark_high"),
                            _f(r, "mark_low"), _f(r, "mark_close"))
                        for r in csv.DictReader(fh)]
    return out


def load_signals(path: str) -> list[Signal]:
    with open(path, newline="") as fh:
        return sorted((Signal(
            ts=int(r["ts"]), symbol=r["symbol"], timeframe=r["timeframe"],
            strategy_id=r["strategy_id"], side=int(r["side"]),
            stop_price=float(r["stop_price"]), tier=r.get("tier") or "base",
            score=_f(r, "score") or 0.0, tp_roe=_f(r, "tp_roe"), atr=_f(r, "atr"))
            for r in csv.DictReader(fh)), key=lambda s: s.ts)


def load_funding(path: Optional[str]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = defaultdict(dict)
    if path:
        with open(path, newline="") as fh:
            for r in csv.DictReader(fh):
                out[int(r["ts"])][r["symbol"]] = float(r["rate"])
    return out


def replay(settings: Settings, bars: dict[str, list[Bar]], signals: list[Signal],
           brackets: dict[str, Brackets], funding: dict[int, dict[str, float]],
           engine: Optional[PaperEngine] = None) -> PaperEngine:
    eng = engine or PaperEngine(settings, brackets)
    by_time: dict[int, dict[str, Bar]] = defaultdict(dict)
    for sym, rows in bars.items():
        for b in rows:
            by_time[b.open_time][sym] = b
    funding_times = sorted(funding)
    fi = 0
    si = 0
    for t in sorted(by_time):
        while si < len(signals) and signals[si].ts <= t:
            eng.submit(signals[si])
            si += 1
        step_funding: dict[str, float] = {}
        while fi < len(funding_times) and funding_times[fi] <= t:
            step_funding.update(funding[funding_times[fi]])
            fi += 1
        eng.step(by_time[t], step_funding or None)
    return eng


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bars", required=True)
    ap.add_argument("--signals", required=True)
    ap.add_argument("--funding")
    ap.add_argument("--brackets", help="leverageBracket JSON; example table if omitted")
    ap.add_argument("--out")
    args = ap.parse_args(argv)

    settings = Settings()
    if args.brackets:
        with open(args.brackets) as fh:
            payload = json.load(fh)
        brackets = {p["symbol"]: Brackets.from_binance(p) for p in payload}
    else:
        brackets = {s: Brackets.example() for s in settings.symbols}
    eng = replay(settings, load_bars(args.bars, settings.symbols),
                 load_signals(args.signals), brackets, load_funding(args.funding))
    summary = eng.summary()
    summary["brackets_source"] = args.brackets or "EXAMPLE TABLE (not exchange data)"
    text = json.dumps(summary, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
