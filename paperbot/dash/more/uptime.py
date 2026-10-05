"""가동 기록 (서버·비용, v4 wave 3): did the bot really step every minute, day by day and hour by hour. Read-only.

    GET /api/v4/uptime?days=7|30

Source (nothing made up):
- paper3.db ``live_bars``: one row per coin per minute the live runner actually stepped on (store3.py). A minute counts
  as "가동" when at least one coin's 1m bar of that minute was stepped. Per Korea-time hour: how many of its minutes were
  stepped (0..60). Minutes before the run start and the last ``LAG_MIN`` minutes (a bar is stepped after it closes) are
  not expected.
- paper3.db ``runs``: every start of the live runner (append-only): the restart marks.
- daily3.db ``reports``: the nightly check of each day (accounts replayed, how many differed): the night-check marks.

Summary: share of expected minutes that were stepped, and the stops (runs of ``STOP_MIN`` or more missing minutes in a
row) with their total minutes. Cost: one index walk of live_bars' primary key (ts, symbol) over the window (30 days x 7
coins = about 300k index entries, tens of ms), cached 120 s.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
import time
from typing import Optional

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
KST_MS = 9 * HOUR
TTL_S = 120.0
LAG_MIN = 3                 # the newest minutes: their bars are not stepped yet (closed + settle)
STOP_MIN = 3                # a stop = at least this many minutes in a row with no stepped bar
STOPS_MAX = 50


def kst_day_start(ms: int) -> int:
    """00:00 KST of the Korea-time day holding ``ms``."""
    return (int(ms) + KST_MS) // DAY * DAY - KST_MS


def _ro(path: Optional[str]) -> Optional[sqlite3.Connection]:
    import os
    from ..app import _ro_uri
    if not path or not os.path.exists(path):
        return None
    c = sqlite3.connect(_ro_uri(path), uri=True, timeout=5)
    return c


def nightly(daily_db: Optional[str], t0: int) -> list[dict]:
    """[{day, ts, accounts, mismatched, ok}] of the nightly checks written since ``t0`` (oldest first). ``ok`` is the
    same "재계산 일치" count as the Telegram daily check (daily3.daily_text): accounts minus the mismatched, the
    extras' crash gaps and the early-kline ones (those were not shown to match)."""
    d = _ro(daily_db)
    if d is None:
        return []
    try:
        rows = d.execute(
            "SELECT day, ts, json_extract(data, '$.parity.accounts'), json_extract(data, '$.parity.mismatched_accounts'), "
            "json_extract(data, '$.parity.crash_gaps'), json_extract(data, '$.parity.early_kline') "
            "FROM reports WHERE ts >= ? ORDER BY day", (int(t0),)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        d.close()
    out = []
    num = lambda x: int(x) if isinstance(x, (int, float)) else None      # noqa: E731
    for day, ts, acc, mis, gaps, early in rows:
        acc, mis = num(acc), num(mis)
        ok = None if acc is None or mis is None else acc - mis - (num(gaps) or 0) - (num(early) or 0)
        out.append({"day": str(day), "ts": int(ts), "accounts": acc, "mismatched": mis, "ok": ok})
    return out


def uptime(c: sqlite3.Connection, daily_db: Optional[str], days: int, now: int) -> dict:
    """The window's Korea-time days x 24 hours (see the module docstring)."""
    from .story import run_start
    start = run_start(c)
    t_end = now - now % MIN - LAG_MIN * MIN                 # minutes up to here are expected to be stepped
    first_day = kst_day_start(now) - (days - 1) * DAY
    if start is None:
        return {"ready": False, "days": days, "now": now, "start": None, "rows": [], "restarts": [], "nightly": [],
                "why": "봇이 아직 첫 계좌를 만들지 않았습니다"}
    lo = max(first_day, int(start) - int(start) % MIN)
    mins = [int(r[0]) for r in c.execute("SELECT DISTINCT ts FROM live_bars WHERE ts >= ? AND ts < ? ORDER BY ts",
                                         (lo, t_end))]
    got: dict = {}
    for ts in mins:
        h = (ts - first_day) // HOUR
        got[h] = got.get(h, 0) + 1
    # stops: gaps of STOP_MIN+ minutes between stepped minutes (and before the first / after the last one)
    stops, missing = [], 0
    prev = lo - MIN
    for ts in mins + [t_end]:
        gap = (ts - prev) // MIN - 1
        if gap > 0:
            missing += gap
            if gap >= STOP_MIN:
                stops.append({"from": prev + MIN, "to": ts, "min": int(gap)})
        prev = ts
    expected = max(0, (t_end - lo) // MIN)
    rows = []
    for d in range(days):
        d0 = first_day + d * DAY
        cells = []
        for hh in range(24):
            h0 = d0 + hh * HOUR
            e0, e1 = max(h0, lo), min(h0 + HOUR, t_end)
            exp = max(0, (e1 - e0) // MIN)
            if h0 + HOUR <= lo:
                cells.append(None)                                     # before the run: no expectation
                continue
            if h0 >= t_end:
                cells.append(-1)                                       # not yet
                continue
            cells.append([int(got.get(d * 24 + hh, 0)), int(exp)])
        rows.append({"day": time.strftime("%Y-%m-%d", time.gmtime((d0 + KST_MS) / 1000)), "ts": d0, "h": cells})
    # restarts only: the first start writes its runs row with the accounts' creation time (live3: open_accounts and
    # add_run share one clock reading), which is the run start, so it is not a restart
    restarts = [{"ts": int(r[0]), "id": int(r[1])} for r in c.execute(
        "SELECT started_ts, id FROM runs WHERE started_ts >= ? AND started_ts > ? ORDER BY started_ts",
        (first_day, int(start)))]
    return {"ready": True, "days": days, "now": now, "start": int(start), "first_day": first_day, "until": t_end,
            "expected_min": int(expected), "stepped_min": int(len(mins)),
            "share": (len(mins) / expected) if expected else None,
            "missing_min": int(missing), "stops": stops[max(0, len(stops) - STOPS_MAX):], "stops_n": len(stops),
            "stops_min": int(sum(x["min"] for x in stops)),           # every stop's minutes (the list keeps the last 50)
            "stop_min_rule": STOP_MIN, "rows": rows, "restarts": restarts, "nightly": nightly(daily_db, first_day),
            "note": "1분봉을 실제로 처리한 분 수 (live_bars) · 재시작 = runs · 밤 점검 = daily3 보고"}


def register(app, ctx) -> dict:
    data, daily_db = ctx.data, getattr(ctx, "daily_db", None)
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/uptime")
    def get_uptime(days: int = 7):
        """The bot's stepped minutes per KST hour over the last 7 or 30 days, restarts and nightly checks (120 s)."""
        from fastapi import HTTPException
        from ..app import json_finite
        n = 30 if int(days) > 7 else 7
        hit = cache.get(n)
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
        with lock:
            hit = cache.get(n)
            if hit and time.time() - hit[0] < TTL_S:
                return hit[1]
            try:
                with contextlib.closing(data.conn()) as c:
                    v = json_finite(uptime(c, daily_db, n, int(time.time() * 1000)))
            except sqlite3.Error as exc:
                raise HTTPException(503, f"paper3.db를 읽지 못함: {type(exc).__name__}") from None
            cache[n] = (time.time(), v)
        return v

    return {"routes": ["/api/v4/uptime"], "cache": cache}
