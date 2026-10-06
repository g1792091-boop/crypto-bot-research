"""원본 vs 복제 (계좌 화면, review addition 10): an approved copy account next to its parent over the SAME period, from the
copy's start to now. Read-only over paper3.db (the dashboard never writes it).

    GET /api/v4/copycmp/<copy account id>

A copy starts later than its parent, so the board's returns (each from its own start) cannot be compared; here both
are measured from the copy's ``created_ts``:

- ``curve``: hourly points from the copy's start; each account's balance divided by its balance at that start (the
  parent's last equity row at or before the start, carried forward; the copy's own starting balance), minus 1
- ``stats``: the trades each one ENTERED in the period (the parent's trades that began before the copy existed are
  left out): count, win rate, mean ROE per trade, fees and funding as a share of the balance at the start, forced
  liquidations; and the return over the period (balance now from the engine state, else the last equity row)
- ``flips``: the same-timeframe coin flips' returns over the same period (their median and count, 참고)
- ``rule_ko``: the one rule the copy changed (agents/extra_accounts.rule_ko); ``small``: fewer than ``SMALL`` trades

A copy of a DeepSeek account (none exists today: the lab copies the 36) would get counts only (owners' D10 / D11):
``count_only`` and no return or money field. 404 for an account that is not a copy. Cached ``TTL_S`` per account.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import threading
import time
from typing import Optional

from fastapi import HTTPException

HOUR_MS = 3_600_000
TTL_S = 30.0
SMALL = 30                       # checkpoint.MIN_TRADES: the page says '표본 적음' below it
MAX_POINTS = 24 * 120            # an hourly curve of 120 days at most (thinned evenly beyond)


def _ro(path: str) -> sqlite3.Connection:
    from ..app import _ro_uri
    c = sqlite3.connect(_ro_uri(path), uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def _wallets(c: sqlite3.Connection) -> dict:
    r = c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
    try:
        eng = (json.loads(r["data"]) or {}).get("engines") or {} if r else {}
    except (TypeError, ValueError):
        eng = {}
    return {a: e.get("wallet") for a, e in eng.items() if isinstance(e, dict)}


def _equity(c: sqlite3.Connection, aid: str, since: int) -> tuple[Optional[float], list]:
    """(balance at ``since``: the last row at or before it, else the first after it; rows after it [(ts, equity)])."""
    before = c.execute("SELECT equity FROM equity WHERE account_id = ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                       (aid, since)).fetchone()
    rows = [(int(r["ts"]), float(r["equity"])) for r in c.execute(
        "SELECT ts, equity FROM equity WHERE account_id = ? AND ts > ? ORDER BY ts", (aid, since))]
    base = float(before["equity"]) if before else (rows[0][1] if rows else None)
    return base, rows


def _carry(rows: list, grid: list, base: Optional[float]) -> list:
    out, j, cur = [], 0, base
    for t in grid:
        while j < len(rows) and rows[j][0] <= t:
            cur = rows[j][1]
            j += 1
        out.append(cur)
    return out


def _trade_stats(c: sqlite3.Connection, aid: str, since: int, base: Optional[float]) -> dict:
    rows = c.execute("SELECT pnl, roe, exit_reason, data FROM trades WHERE account_id = ? AND entry_time >= ? ORDER BY id",
                     (aid, since)).fetchall()
    n = len(rows)
    fees = funding = 0.0
    for r in rows:
        try:
            d = json.loads(r["data"])
        except (TypeError, ValueError):
            d = {}
        fees += float(d.get("fees") or 0.0)
        funding += float(d.get("funding") or 0.0)
    wins = sum(1 for r in rows if float(r["pnl"]) > 0)
    return {"trades": n, "wins": wins, "win_rate": wins / n if n else None,
            "mean_roe": sum(float(r["roe"]) for r in rows) / n if n else None,
            "liquidations": sum(1 for r in rows if r["exit_reason"] == "LIQ"),
            "pnl": sum(float(r["pnl"]) for r in rows),
            "fees_share": fees / base if base else None, "funding_share": funding / base if base else None,
            "small": n < SMALL}


def compare(db: str, aid: str, now_ms: Optional[int] = None) -> dict:
    from ...agents.extra_accounts import rule_ko
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    c = _ro(db)
    try:
        acc = c.execute("SELECT account_id, strategy, timeframe, kind, created_ts, parent, data FROM accounts "
                        "WHERE account_id = ?", (aid,)).fetchone()
        if acc is None or acc["kind"] != "copy" or not acc["parent"]:
            raise HTTPException(404, "복제 계좌가 아닙니다")
        par = c.execute("SELECT account_id, kind, timeframe FROM accounts WHERE account_id = ?", (acc["parent"],)).fetchone()
        if par is None:
            raise HTTPException(404, "원본 계좌를 찾지 못했습니다")
        try:
            data = json.loads(acc["data"] or "{}") or {}
        except (TypeError, ValueError):
            data = {}
        since = int(acc["created_ts"])
        wallets = _wallets(c)
        count_only = par["kind"] == "ds200"
        out: dict = {"account_id": aid, "parent_id": acc["parent"], "parent_kind": par["kind"], "timeframe": acc["timeframe"],
                     "since": since, "now": now, "rule": data.get("rule"),
                     "rule_ko": rule_ko(data.get("rule")) if data.get("rule") else None,
                     "label_ko": data.get("label_ko"), "count_only": count_only, "small_n": SMALL}
        sides = {}
        for key, a in (("copy", aid), ("parent", acc["parent"])):
            base, rows = _equity(c, a, since)
            st = _trade_stats(c, a, since, base)
            w = wallets.get(a)
            w = float(w) if isinstance(w, (int, float)) else (rows[-1][1] if rows else base)
            ret = (w / base - 1) if base and w is not None else None
            sides[key] = {"base": base, "rows": rows, "stats": st, "wallet": w, "ret": ret}
        # the curve: hourly from the copy's start (plus now), both as a return from their balance at the start
        grid = list(range(since, now, HOUR_MS)) + [now]
        if len(grid) > MAX_POINTS:
            step = len(grid) / MAX_POINTS
            grid = [grid[int(i * step)] for i in range(MAX_POINTS)] + [now]
        curve = {"t": grid}
        for key, sd in sides.items():
            vals = _carry(sd["rows"], grid, sd["base"])
            vals[-1] = sd["wallet"] if sd["wallet"] is not None else vals[-1]
            curve[key] = [None if v is None or not sd["base"] else round(v / sd["base"] - 1, 5) for v in vals]
        # the same-timeframe coin flips over the same period (참고)
        flips = []
        for r in c.execute("SELECT account_id FROM accounts WHERE kind = 'random' AND timeframe = ?", (acc["timeframe"],)):
            base, rows = _equity(c, r["account_id"], since)
            w = wallets.get(r["account_id"])
            w = float(w) if isinstance(w, (int, float)) else (rows[-1][1] if rows else base)
            if base and w is not None:
                flips.append(w / base - 1)
    finally:
        c.close()
    out["flips"] = {"n": len(flips), "median_ret": statistics.median(flips) if flips else None}
    for key, sd in sides.items():
        st = dict(sd["stats"])
        side = {"trades": st["trades"], "wins": st["wins"], "win_rate": st["win_rate"], "liquidations": st["liquidations"],
                "small": st["small"]}
        if not count_only:
            side.update(ret=sd["ret"], mean_roe=st["mean_roe"], fees_share=st["fees_share"],
                        funding_share=st["funding_share"], start_balance=sd["base"], balance=sd["wallet"])
        out[key] = side
    if count_only:
        out["flips"] = {"n": len(flips), "median_ret": None}
    else:
        out["curve"] = curve
        out["diff"] = (out["copy"]["ret"] - out["parent"]["ret"]
                       if out["copy"].get("ret") is not None and out["parent"].get("ret") is not None else None)
    return out


def register(app, ctx) -> dict:
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/copycmp/{aid}")
    def get_copycmp(aid: str):
        """An approved copy next to its parent over the same period (the copy's start to now)."""
        hit = cache.get(aid)
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
        try:
            v = compare(ctx.db, aid)
        except sqlite3.Error:
            raise HTTPException(503, "paper3.db를 읽지 못했습니다")
        with lock:
            if len(cache) > 200:
                cache.clear()
            cache[aid] = (time.time(), v)
        return v

    return {"routes": ["/api/v4/copycmp/{aid}"], "cache": cache}
