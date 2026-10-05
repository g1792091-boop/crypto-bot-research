"""거래 모양 (분석, v4 wave 3): when our trades were opened and how big each result was. Read-only, descriptive.

    GET /api/v4/tradeshape

- heat: closed trades of the 기존 36 (kind 'strategy') by the ENTRY time's Korea-time weekday (0 = 월) x hour (the same
  clock as paperbot/sessions.py): per cell n, wins, mean result per trade (계좌 대비 %, below), P&L sum; and the same
  timeframes' coin flips per cell as counts only (n, wins: owners' D10 / D11, the coin flips are counted, never listed
  with money). 168 cells are far too many to test: description only.
- dist: each closed trade's result against the account's balance before it (pnl / (equity_after - pnl)), counted in
  FIXED bins (BINS, decided before any data), for the 기존 36 and for the coin flips of the same timeframes (15m / 30m /
  1h / 4h; the 5m flips belong to the reel). Shares per group so the two shapes compare at a glance; liquidations
  counted apart too. Fees and funding are inside pnl.

Since the run start (checkpoint.run_facts); cached 10 minutes. One pass over the closed trades of those accounts
through trades_acct.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import time

HOUR = 3_600_000
DAY = 86_400_000
KST_MS = 9 * HOUR
TTL_S = 600.0
CORE_TFS = ("15m", "30m", "1h", "4h")
# fixed bin edges of a trade's result against the balance before it (ratio); first bin is (-inf, -0.20), last [0.20, inf)
BINS = (-0.20, -0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10, 0.20)
BIN_KO = ("−20% 밑", "−20~−10%", "−10~−5%", "−5~−2%", "−2~0%", "0~2%", "2~5%", "5~10%", "10~20%", "20% 위")
SMALL_N = 10                  # a heat cell under this many trades is shown faded (표본 적음)


def bin_of(r: float) -> int:
    """Index into BIN_KO of a result ratio (a result of exactly 0 counts as 0~2%, i.e. not a loss)."""
    i = 0
    for e in BINS:
        if r < e:
            return i
        i += 1
    return i


def kst_wd_hour(ms: int) -> tuple[int, int]:
    """(weekday 0 = Monday, hour) of ``ms`` in Korea time."""
    k = int(ms) + KST_MS
    return (k // DAY + 3) % 7, (k % DAY) // HOUR


def shape(c: sqlite3.Connection, now: int) -> dict:
    from .story import run_start
    start = run_start(c)
    if start is None:
        return {"ready": False, "trades": 0, "why": "봇이 아직 첫 계좌를 만들지 않았습니다"}
    q = ("SELECT a.kind, a.timeframe, t.entry_time, t.pnl, t.equity_after, t.exit_reason FROM trades t "
         "JOIN accounts a ON a.account_id = t.account_id "
         "WHERE t.account_id IN (SELECT account_id FROM accounts WHERE kind IN ('strategy', 'random')) "
         "AND t.exit_time >= ? AND t.exit_time <= ?")
    core_heat = [[[0, 0, 0.0, 0.0] for _ in range(24)] for _ in range(7)]       # n, wins, sum result, pnl
    flip_heat = [[[0, 0] for _ in range(24)] for _ in range(7)]
    dist = {"core": [0] * len(BIN_KO), "flip": [0] * len(BIN_KO)}
    n = {"core": 0, "flip": 0}
    liq = {"core": 0, "flip": 0}
    wins = {"core": 0, "flip": 0}
    for kind, tf, et, pnl, eq_after, reason in c.execute(q, (int(start), int(now))):
        if kind == "random" and tf not in CORE_TFS:
            continue                                      # the 5m flips are the reel's comparison, not the 36's
        g = "core" if kind == "strategy" else "flip"
        pnl = float(pnl or 0.0)
        before = float(eq_after or 0.0) - pnl
        r = pnl / before if before > 0 else None
        wd, hh = kst_wd_hour(int(et))
        win = pnl > 0
        n[g] += 1
        wins[g] += win
        liq[g] += reason == "LIQ"
        if r is not None:
            dist[g][bin_of(r)] += 1
        if g == "core":
            cell = core_heat[wd][hh]
            cell[0] += 1
            cell[1] += win
            cell[2] += r if r is not None else 0.0
            cell[3] += pnl
        else:
            cell = flip_heat[wd][hh]
            cell[0] += 1
            cell[1] += win
    heat_core = [[None if x[0] == 0 else {"n": x[0], "w": x[1], "r": round(x[2] / x[0], 6), "pnl": round(x[3], 2)}
                  for x in row] for row in core_heat]
    heat_flip = [[None if x[0] == 0 else {"n": x[0], "w": x[1]} for x in row] for row in flip_heat]
    share = lambda g: [round(v / sum(dist[g]), 6) if sum(dist[g]) else 0.0 for v in dist[g]]   # noqa: E731
    return {"ready": True, "start": int(start), "now": int(now), "tz": "Asia/Seoul (진입 시각)",
            "small_n": SMALL_N, "trades": n, "wins": wins, "liq": liq,
            "heat": {"core": heat_core, "flip": heat_flip},
            "dist": {"bins": list(BIN_KO), "edges": list(BINS), "core": dist["core"], "flip": dist["flip"],
                     "core_share": share("core"), "flip_share": share("flip")},
            "note": "설명용: 168칸은 시험하지 않았습니다 · 구간은 미리 고정 · 수수료·펀딩 포함"}


def register(app, ctx) -> dict:
    data = ctx.data
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/tradeshape")
    def get_tradeshape():
        """Weekday x hour heat of the 36's trades and the fixed-bin result distribution vs coin flips (10 min)."""
        from fastapi import HTTPException
        from ..app import json_finite
        hit = cache.get("v")
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
        with lock:
            hit = cache.get("v")
            if hit and time.time() - hit[0] < TTL_S:
                return hit[1]
            try:
                with contextlib.closing(data.conn()) as c:
                    v = json_finite(shape(c, int(time.time() * 1000)))
            except sqlite3.Error as exc:
                raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}") from None
            v["computed_at"] = int(time.time() * 1000)
            cache["v"] = (time.time(), v)
        return v

    return {"routes": ["/api/v4/tradeshape"], "cache": cache}
