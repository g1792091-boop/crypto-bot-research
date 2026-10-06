"""터미널 수익 차트의 시간별 점 (기존 36의 닫힌 거래, 읽기 전용).

    GET /api/v4/termpnl

    {"ready": true, "start": <run start ms>, "now": <ms>, "season": 0, "seasons": 1, "from": <00:00 KST of the season's first day, ms>,
     "hours": [[<hour END ms>, <realized P&L of the 36's trades that closed in that hour>, <trades>, <wins>, <losses>], ...],
     "totals": {"trades": 124, "wins": 74, "losses": 50, "pnl": -4118.17}}

Why it exists: the terminal's profit chart used one point per KST day, so on day 1 it was ONE slanted line that looked
like a crash and said "10/06 … 10/06". With the closed trades of each hour the page draws a real line from the first
hours (and the wins / losses / worst fall are counted from the same trades).

Rules (the same as 흐름 › 수익 달력, whose day sums these hours add up to):
- Only the 36 locked strategies' accounts (kind "strategy", paperbot/groups.py "core"); DeepSeek, the 5m reel, the coin flips
  and the extra accounts are never in this line.
- The current season only (a season is 31 KST days, the first through the verdict day: Flow.seasons), from 00:00 KST of
  its first day: the page's 이번 판정 구간.
- An hour holds the trades whose exit_time is in (hour start, hour end]: a close at exactly 13:00:00 belongs to the hour
  ending 13:00 (the calendar's rule for days). A win is pnl > 0, a loss pnl < 0 (a trade that closed at exactly 0 is neither).
- Only hours WITH a closed trade are listed (an hour without one is simply not there: the page keeps the line flat
  across it, which is true: nothing closed); an empty list with ``ready: true`` means "no trade has closed yet".
  ``ready: false`` means no account exists yet, or the database could not be read (503): never a made-up zero.
- Read-only over paper3.db, one indexed pass over the season's trades, cached 30 s.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Callable, Optional

HOUR = 3_600_000
TTL_S = 30.0


def build(c: sqlite3.Connection, now_ms: int) -> dict:
    """The answer from an open paper3.db connection (pure apart from reading: tested on a small database)."""
    from ...accounts import ORIGINAL_KINDS
    from .flow import Flow, kst_day, kst_day_start
    q = ",".join("?" * len(ORIGINAL_KINDS))
    r = c.execute(f"SELECT MIN(created_ts) FROM accounts WHERE kind IN ({q})", ORIGINAL_KINDS).fetchone()
    start = int(r[0]) if r and r[0] is not None else None
    if start is None:
        return {"ready": False, "hours": [], "totals": None}
    ss = Flow.seasons(start, kst_day(now_ms))
    first = ss[-1][0]
    since = kst_day_start(first)
    buckets: dict = {}
    n = w = lo = 0
    pnl = 0.0
    for ext, p in c.execute("SELECT t.exit_time, t.pnl FROM trades t JOIN accounts a ON a.account_id = t.account_id "
                            "WHERE a.kind = 'strategy' AND t.exit_time > ? AND t.exit_time <= ? ORDER BY t.exit_time",
                            (since, now_ms)):
        end = ((int(ext) - 1) // HOUR + 1) * HOUR
        b = buckets.setdefault(end, [0.0, 0, 0, 0])
        p = float(p)
        b[0] += p
        b[1] += 1
        if p > 0:
            b[2] += 1
            w += 1
        elif p < 0:
            b[3] += 1
            lo += 1
        n += 1
        pnl += p
    hours = [[t, round(b[0], 2), b[1], b[2], b[3]] for t, b in sorted(buckets.items())]
    return {"ready": True, "start": start, "now": int(now_ms), "season": len(ss) - 1, "seasons": len(ss), "from": since,
            "hours": hours, "totals": {"trades": n, "wins": w, "losses": lo, "pnl": round(pnl, 2)}}


class TermPnl:
    def __init__(self, data, ttl: float = TTL_S, clock: Callable[[], float] = time.time):
        self.data, self.ttl, self.clock = data, ttl, clock
        self.lock = threading.Lock()
        self.hit: Optional[tuple] = None

    def get(self) -> dict:
        with self.lock:
            if self.hit and self.clock() - self.hit[0] < self.ttl:
                return self.hit[1]
            now = self.clock()
            c = self.data.conn()
            try:
                out = build(c, int(now * 1000))
            finally:
                c.close()
            self.hit = (now, out)
            return out


def register(app, ctx) -> dict:
    from fastapi import HTTPException
    tp = TermPnl(ctx.data)

    @app.get("/api/v4/termpnl")
    def get_termpnl():
        """Hourly realized P&L of the 36's closed trades in the current season, with wins / losses (cached 30 s)."""
        try:
            return tp.get()
        except sqlite3.Error as exc:
            raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}")

    return {"routes": ["/api/v4/termpnl"], "termpnl": tp}
