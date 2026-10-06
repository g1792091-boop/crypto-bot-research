"""원본 vs 복제 (계좌 화면, review addition 10): an approved copy account next to its parent over the SAME period, from the
copy's start to now. Read-only over paper3.db (the dashboard never writes it).

    GET /api/v4/copycmp/<copy account id>

A copy starts later than its parent, so the board's returns (each from its own start) cannot be compared; here both
are measured from the copy's ``created_ts``, on the closed-trade balance the board and the account page use (the
engine wallet: an open position's unrealised profit or loss is never in it):

- balance at the copy's start: the balance after each one's last trade that ended at or before it (before any trade:
  the wallet the first trade was entered with, ``equity_after - pnl``; no trade at all: the run's starting wallet);
  balance now: the engine wallet (as on the board), else the balance after the last trade
- ``curve``: hourly points from the copy's start (plus now), each one's closed-trade balance over its balance at the
  start, minus 1; the last point is the balance now
- per side: the trades that ENDED in the period (so the return and the trade rows count the same trades; a parent
  trade that was open when the copy started is in both): count, win rate, mean ROE per trade, fees and funding as a
  share of the balance at the start, forced liquidations
- ``flips``: the same-timeframe coin flips over the same period, the same way (their median and count, 참고)
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


def _state(c: sqlite3.Connection, k: str) -> dict:
    r = c.execute("SELECT data FROM state WHERE k = ?", (k,)).fetchone()
    try:
        return (json.loads(r["data"]) or {}) if r else {}
    except (TypeError, ValueError):
        return {}


def _wallets(c: sqlite3.Connection) -> dict:
    eng = _state(c, "accounts").get("engines") or {}
    return {a: e.get("wallet") for a, e in eng.items() if isinstance(e, dict)}


def _initial(c: sqlite3.Connection) -> float:
    """The run's starting wallet (what the running bot recorded, else the rule), as app.Data.initial."""
    v = _state(c, "run").get("initial_equity")
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    from ...config import V3_INITIAL
    return float(V3_INITIAL)


def _trades(c: sqlite3.Connection, aid: str) -> list:
    return [dict(r) for r in c.execute(
        "SELECT entry_time, exit_time, pnl, roe, exit_reason, equity_after, data FROM trades WHERE account_id = ? "
        "ORDER BY exit_time, id", (aid,))]


def _balance_at(trades: list, t: int, initial: float) -> float:
    """The closed-trade balance at ``t`` (``trades`` in exit order)."""
    last = None
    for r in trades:
        if int(r["exit_time"]) > t:
            break
        last = r
    if last is not None:
        return float(last["equity_after"])
    if trades:                                   # the wallet the first trade was entered with
        return float(trades[0]["equity_after"]) - float(trades[0]["pnl"])
    return initial


def _steps(trades: list, grid: list, base: float) -> list:
    out, j, cur = [], 0, base
    for t in grid:
        while j < len(trades) and int(trades[j]["exit_time"]) <= t:
            cur = float(trades[j]["equity_after"])
            j += 1
        out.append(cur)
    return out


def _trade_stats(rows: list, base: Optional[float]) -> dict:
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


def _side(trades: list, since: int, now: int, initial: float, wallet) -> dict:
    base = _balance_at(trades, since, initial)
    w = float(wallet) if isinstance(wallet, (int, float)) else _balance_at(trades, now, initial)
    period = [r for r in trades if since < int(r["exit_time"]) <= now]
    return {"base": base, "wallet": w, "ret": (w / base - 1) if base else None, "trades": trades,
            "stats": _trade_stats(period, base)}


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
        wallets, initial = _wallets(c), _initial(c)
        count_only = par["kind"] == "ds200"
        out: dict = {"account_id": aid, "parent_id": acc["parent"], "parent_kind": par["kind"], "timeframe": acc["timeframe"],
                     "since": since, "now": now, "rule": data.get("rule"),
                     "rule_ko": rule_ko(data.get("rule")) if data.get("rule") else None,
                     "label_ko": data.get("label_ko"), "count_only": count_only, "small_n": SMALL}
        sides = {key: _side(_trades(c, a), since, now, initial, wallets.get(a)) for key, a in (("copy", aid), ("parent", acc["parent"]))}
        # the same-timeframe coin flips over the same period (참고), measured the same way
        flips = []
        for r in c.execute("SELECT account_id FROM accounts WHERE kind = 'random' AND timeframe = ?", (acc["timeframe"],)).fetchall():
            f = _side(_trades(c, r["account_id"]), since, now, initial, wallets.get(r["account_id"]))
            if f["ret"] is not None:
                flips.append(f["ret"])
    finally:
        c.close()
    # the curve: hourly from the copy's start (plus now), both as a return from their balance at the start
    grid = list(range(since, now, HOUR_MS)) + [now]
    if len(grid) > MAX_POINTS:
        step = len(grid) / MAX_POINTS
        grid = [grid[int(i * step)] for i in range(MAX_POINTS)] + [now]
    curve = {"t": grid}
    for key, sd in sides.items():
        vals = _steps(sd["trades"], grid, sd["base"])
        vals[-1] = sd["wallet"]
        curve[key] = [None if v is None or not sd["base"] else round(v / sd["base"] - 1, 5) for v in vals]
    for key, sd in sides.items():
        st = sd["stats"]
        side = {"trades": st["trades"], "wins": st["wins"], "win_rate": st["win_rate"], "liquidations": st["liquidations"],
                "small": st["small"]}
        if not count_only:
            side.update(ret=sd["ret"], mean_roe=st["mean_roe"], fees_share=st["fees_share"],
                        funding_share=st["funding_share"], start_balance=sd["base"], balance=sd["wallet"])
        out[key] = side
    if count_only:
        out["flips"] = {"n": len(flips), "median_ret": None}
    else:
        out["flips"] = {"n": len(flips), "median_ret": statistics.median(flips) if flips else None}
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
