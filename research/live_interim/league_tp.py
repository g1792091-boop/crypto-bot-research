"""Candidate league: where the take-profit and stop sit against what the trades actually did (read-only; for the owners to paste).

    python3 research/live_interim/league_tp.py [--db /var/lib/candleague/league.db] [--min-trades 1]

Opens league.db read-only (nothing is written, nothing on the server changes) and prints, in Korean, for every candidate
account that has closed trades:

  1. per strategy: trades, win rate, hold time, how often a trade reached net ROE +10 / +20 / +30 / +50% at some point
     and how often it then finished below +10% or in a loss ("익절을 못 해서 다 돌려준" trades);
  2. the same trades re-scored with a fixed take-profit at net ROE +10 / +15 / +20 / +30 / +50% and with the rule bot's
     stepped lock (12% -> lock 10%, 17% -> 15% ...), keeping each trade's own stop;
  3. how the stop worked: share of stop-outs, how far trades went against the stop before they ended, long vs short.

The re-scoring uses each closed trade's best and worst price (mfe / mae): a fixed take-profit would have been hit when the
best price reached it, because the trade was still open until then, so the stop had not fired. What it cannot see is the
order of ups and downs inside a trade and the trades that a quicker exit would have freed up to enter again, so every
re-scored number is a rough estimate, not a backtest. DeepSeek strategies are shown as counts and rates only (owners' D11:
no money figures). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics as st
import sys
from collections import defaultdict

ROUND_TRIP = 0.0014                      # paperbot/config.py: 2 x (taker 0.05% + slippage 0.02%)
THRESHOLDS = (0.10, 0.20, 0.30, 0.50)    # net ROE touched
FIXED_TPS = (0.10, 0.15, 0.20, 0.30, 0.50)
LOCK_FIRST, LOCK_STEP, LOCK_GAP = 0.10, 0.05, 0.02    # paperbot/ladder.py LadderSpec
ID_RE = re.compile(r"^(core|ds)-(.+?)-(15m|30m|1h|4h)-(\d+)(?:-([a-z0-9]+))?$")


def lock_for(best: float):
    """Highest lock armed by a best net ROE (the rule bot's stepped lock), or None below the first trigger."""
    first = LOCK_FIRST + LOCK_GAP
    if best < first - 1e-12:
        return None
    return LOCK_FIRST + LOCK_STEP * int((best - first) / LOCK_STEP + 1e-9)


def load(path: str):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows = []
    for acct, _t, data in con.execute("SELECT account, exit_time, data FROM trades ORDER BY exit_time"):
        m = ID_RE.match(acct)
        if not m:
            continue
        try:
            d = json.loads(data)
        except ValueError:
            continue
        rows.append((acct, m.group(1), m.group(2), m.group(3), m.group(5) or "", d))
    return rows


def metrics(d: dict):
    """(net roe, best net roe, worst net roe, stop distance as net roe, hold hours, equity before, margin) of a trade."""
    e, lev, side = d["entry_price"], d["leverage"], d["side"]
    mfe = side * (d["mfe_price"] / e - 1.0) * lev - ROUND_TRIP * lev
    mae = side * (d["mae_price"] / e - 1.0) * lev - ROUND_TRIP * lev
    stop = abs(side * (d["stop_price"] / e - 1.0)) * lev + ROUND_TRIP * lev
    hold = (d["exit_time"] - d["entry_time"]) / 3.6e6
    eq0 = d["equity_after"] - d["pnl"]
    return d["roe"], mfe, mae, stop, hold, eq0, d["margin"]


def rescored(roe: float, mfe: float, tp: float):
    return tp if mfe >= tp else roe


def ladder_scored(roe: float, mfe: float):
    lk = lock_for(mfe)
    return lk if (lk is not None and roe < lk) else roe


def pct(x, n):
    return f"{100.0 * x / n:.0f}%" if n else "-"


def fmt(x):
    return f"{100.0 * x:+.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/var/lib/candleague/league.db")
    ap.add_argument("--min-trades", type=int, default=1)
    a = ap.parse_args()
    rows = load(a.db)
    if not rows:
        print("거래 기록이 없습니다 (계좌 이름 형식이 다르거나 아직 거래가 없음).")
        return 0
    suffixes = sorted({r[4] for r in rows})
    print(f"후보 리그 거래 {len(rows)}건, 계좌 종류(이름 끝) {suffixes or ['(기본)']}")
    print("ROE는 수수료·슬리피지를 뺀 순수익을 증거금으로 나눈 값입니다. 다시 계산한 숫자는 '대략치'입니다(위 설명 참고).\n")

    by_suffix = defaultdict(list)
    for r in rows:
        by_suffix[r[4]].append(r)

    for suf in suffixes:
        grp = by_suffix[suf]
        print("=" * 78)
        print(f"계좌 종류: {'기본(지금 청산)' if suf == '' else '-' + suf}   거래 {len(grp)}건")
        per = defaultdict(list)
        for acct, pool, strat, tf, _s, d in grp:
            per[(pool, strat)].append((tf, d))
        print("\n[1] 매매법별: 거래 · 승률 · 보유 · 수익을 낸 적이 있는 거래의 끝")
        print("매매법 | 거래 | 승률 | 보유 중앙(시간) | 8시간+ | +10%닿음 | +20%닿음 | +50%닿음 | 닿고도 +10% 못 챙긴 | 닿고 손실")
        tot = defaultdict(float)
        for (pool, strat), items in sorted(per.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            if len(items) < a.min_trades:
                continue
            ms = [metrics(d) for _tf, d in items]
            n = len(ms)
            wins = sum(1 for m in ms if m[0] > 0)
            holds = [m[4] for m in ms]
            t10 = [m for m in ms if m[1] >= 0.10]
            t20 = sum(1 for m in ms if m[1] >= 0.20)
            t50 = sum(1 for m in ms if m[1] >= 0.50)
            miss = sum(1 for m in t10 if m[0] < 0.10)
            loss = sum(1 for m in t10 if m[0] < 0)
            label = ("[딥시크] " if pool == "ds" else "") + strat
            print(f"{label} | {n} | {pct(wins, n)} | {st.median(holds):.1f} | {pct(sum(1 for h in holds if h > 8), n)} | "
                  f"{pct(len(t10), n)} | {pct(t20, n)} | {pct(t50, n)} | {pct(miss, len(t10))} ({miss}/{len(t10)}) | "
                  f"{pct(loss, len(t10))} ({loss}/{len(t10)})")

        print("\n[2] 같은 손절로 익절만 바꿨다면 (규칙봇 36개 계열·코어만, 거래당 평균 ROE와 계좌 대비 평균 손익)")
        core = [(acct, d) for acct, pool, _s, _tf, _x, d in grp if pool == "core"]
        if core:
            ms = [metrics(d) for _a, d in core]
            n = len(ms)
            base_roe = sum(m[0] for m in ms) / n
            base_eq = sum(d["pnl"] / (d["equity_after"] - d["pnl"]) for _a, d in core) / n
            print(f"방식 | 거래당 평균 ROE | 계좌 대비 평균 | 이긴 비율   (코어 거래 {n}건)")
            print(f"지금 청산(실제) | {fmt(base_roe)} | {fmt(base_eq)} | {pct(sum(1 for m in ms if m[0] > 0), n)}")
            for tp in FIXED_TPS:
                rs = [rescored(m[0], m[1], tp) for m in ms]
                eq = [(r * m[6] / m[5]) for r, m in zip(rs, ms)]
                print(f"고정 익절 +{int(tp * 100)}% | {fmt(sum(rs) / n)} | {fmt(sum(eq) / n)} | {pct(sum(1 for r in rs if r > 0), n)}")
            rs = [ladder_scored(m[0], m[1]) for m in ms]
            eq = [(r * m[6] / m[5]) for r, m in zip(rs, ms)]
            print(f"계단 잠금(12%→10%, 5%씩) | {fmt(sum(rs) / n)} | {fmt(sum(eq) / n)} | {pct(sum(1 for r in rs if r > 0), n)}")
            print("※ 고정 익절은 '최고가가 익절가에 닿았으면 익절'로 셉니다. 계단 잠금은 '최고 구간의 잠금선 아래로 끝났으면 잠금선에서 청산'으로 셉니다.")
            print("※ 빨리 끝나면 같은 매매법이 다시 진입할 수 있어 거래 수는 늘어납니다. 그 효과는 이 표에 없습니다.")

        print("\n[3] 손절은 어떻게 작동했나 (진입 직후 반대로 간 정도)")
        print("매매법 | 손절로 끝남 | 손절 거리의 절반 넘게 역행 | 롱 승률 | 숏 승률")
        for (pool, strat), items in sorted(per.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            if len(items) < a.min_trades:
                continue
            ms = [metrics(d) for _tf, d in items]
            n = len(ms)
            sl = sum(1 for _tf, d in items if d.get("exit_reason") == "SL")
            half = sum(1 for m in ms if m[3] > 0 and -m[2] >= 0.5 * m[3])
            lg = [m for (_tf, d), m in zip(items, ms) if d["side"] == 1]
            sh = [m for (_tf, d), m in zip(items, ms) if d["side"] == -1]
            label = ("[딥시크] " if pool == "ds" else "") + strat
            print(f"{label} | {pct(sl, n)} | {pct(half, n)} | "
                  f"{pct(sum(1 for m in lg if m[0] > 0), len(lg))} ({len(lg)}) | {pct(sum(1 for m in sh if m[0] > 0), len(sh))} ({len(sh)})")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
