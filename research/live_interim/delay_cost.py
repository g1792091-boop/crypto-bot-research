"""What the signal delay costs at entry (read-only; for the owners to run and paste).

    python3 research/live_interim/delay_cost.py [--db /var/lib/paperbot/paper3.db]

The 5-year backtest fills at the price of the minute the bar closes (research/fullgrid/kernel.py: that minute's open).
The live bot fills at the price when the signal is ready (signal_log.ref_price, delay_ms after the close). For every
signal with a recorded reference price this prints, in basis points against the signal's side (positive = the live
fill was worse than the backtest's), mean / median / share worse, by group and timeframe and by coin, next to the
delay. The coin flips pick their side at random, so their mean shows what the delay costs with no direction in it.
The bar-close price is the open of that minute in live_bars (the bars the bot stepped on). Standard library only.
"""

import argparse
import re
import sqlite3
import statistics as st
import sys
from collections import defaultdict

GROUP_KO = {"core": "규칙봇 36개", "ds200": "딥시크", "reel": "5분 단타", "flip": "동전 던지기"}


def group_of(strategy: str) -> str:
    if strategy.startswith("RANDOM_"):
        return "flip"
    if strategy.startswith("REEL"):
        return "reel"
    if re.match(r"F\d+_", strategy):
        return "ds200"
    return "core"


def line(rows: list) -> str:
    bp = [r[0] for r in rows]
    dl = [r[1] for r in rows if r[1] is not None]
    if not bp:
        return "—"
    return (f"{len(bp)}개 · 평균 {st.mean(bp):+.2f}bp · 중앙 {st.median(bp):+.2f}bp · 불리 {sum(b > 0 for b in bp) / len(bp) * 100:.0f}% "
            f"· 지연 중앙 {st.median(dl) / 1000:.0f}초" if dl else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/var/lib/paperbot/paper3.db")
    a = ap.parse_args(argv)
    c = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    opens = {}
    for ts, sym, o in c.execute("SELECT ts, symbol, open FROM live_bars"):
        opens[(ts, sym)] = o
    rows = defaultdict(list)
    coins = defaultdict(list)
    missing = 0
    for bc, tf, strat, sym, side, ref, dl in c.execute(
            "SELECT bar_close, timeframe, strategy, symbol, side, ref_price, delay_ms FROM signal_log "
            "WHERE ref_price IS NOT NULL AND side != 0"):
        o = opens.get((bc, sym))
        if not o:
            missing += 1
            continue
        bp = side * (ref / o - 1) * 10_000
        g = group_of(strat)
        rows[(g, tf)].append((bp, dl))
        rows[(g, "전체")].append((bp, dl))
        if g == "core":
            coins[sym].append((bp, dl))
    print("[신호 지연이 진입가에 준 비용, bp, +는 백테스트보다 불리] 묶음 봉: 신호 수 · 평균 · 중앙 · 불리한 비율 · 지연")
    order = ("전체", "5m", "15m", "30m", "1h", "4h")
    for g in GROUP_KO:
        for tf in order:
            if (g, tf) in rows:
                print(f"{GROUP_KO[g]} {tf}: {line(rows[(g, tf)])}")
    print("[규칙봇 36개, 코인별] " + " | ".join(f"{s.replace('USDT', '')} {line(v)}" for s, v in sorted(coins.items())))
    print(f"(봉 마감 1분봉을 못 찾은 신호 {missing}개는 뺐습니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
