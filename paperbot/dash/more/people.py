"""Today's code record for the 회의실 상황판 and the strategy rooms before their first meeting (fill-people).

    GET /api/v4/people/today            closed trades since 00:00 KST per group (+ the 36 / 5분봉's losses = loss cards)
    GET /api/v4/people/strats           each of the 36's latest real event (its newest closed trade, newest signal)
    GET /api/v4/people/strat?name=S     one strategy's record: today per timeframe, latest trades, latest signals

Read-only SQL over paper3.db (analysis.ro_connect: ``file:...?mode=ro``), cached ``TTL_S``; no Binance call.
HONESTY (CONTRACT.md section 1): DeepSeek (ds200) and the coin flips (random) are COUNTED ONLY here: their groups
carry ``n`` and ``wins``, never a P&L. A loss card is made by code at every losing close of the 36 and the 5-minute
strategy (cards.py, CARD_STATS_KINDS), so today's loss cards = today's losing closes of those two groups.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Optional

TTL_S = 30.0
KST_MS = 9 * 3600_000
DAY_MS = 86_400_000
GROUP_OF = {"strategy": "core", "ds200": "ds", "reel": "m5", "random": "coin", "copy": "extra", "newlab": "extra"}
MONEY = ("core", "m5", "extra")          # groups that may show money outside their own screen
CARD_GROUPS = ("core", "m5")
STATUS_KO = {"SUBMITTED": "진입 신호", "RECORD": "기록만", "FILTERED": "규칙으로 건너뜀", "SKIPPED": "건너뜀",
             "REJECTED": "거절"}


def kst_midnight(now_ms: int) -> int:
    """00:00 KST of today (ms)."""
    return (now_ms + KST_MS) // DAY_MS * DAY_MS - KST_MS


def _unread(exc: Exception) -> str:
    """The honest empty state when paper3.db opened but a read failed (locked past the timeout, a schema change)."""
    return f"paper3.db를 읽지 못함 ({type(exc).__name__})"


def _side(raw) -> Optional[int]:
    try:
        s = int((json.loads(raw or "{}") or {}).get("side") or 0)
    except (TypeError, ValueError, AttributeError):
        return None
    return s if s in (1, -1) else None


def today_view(paper_db: str, now_ms: int) -> dict:
    from ..analysis import _close, ro_connect
    since = kst_midnight(now_ms)
    out: dict = {"since": since, "groups": {}, "loss_cards": 0, "computed_at": int(now_ms), "money_groups": list(MONEY)}
    c = ro_connect(paper_db)
    if c is None:
        out["error"] = "paper3.db 없음"
        return out
    try:
        rows = c.execute("SELECT a.kind, COUNT(*), SUM(t.pnl > 0), SUM(t.pnl < 0), SUM(t.pnl) FROM trades t "
                         "JOIN accounts a ON a.account_id = t.account_id WHERE t.exit_time >= ? GROUP BY a.kind",
                         (since,)).fetchall()
    except sqlite3.Error as exc:
        out["error"] = _unread(exc)
        return out
    finally:
        _close(c)
    groups: dict = {}
    for kind, n, wins, losses, pnl in rows:
        g = GROUP_OF.get(kind)
        if not g:
            continue
        x = groups.setdefault(g, {"n": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        x["n"] += int(n or 0)
        x["wins"] += int(wins or 0)
        x["losses"] += int(losses or 0)
        x["pnl"] += float(pnl or 0.0)
    for g, x in groups.items():
        if g not in MONEY:
            x.pop("pnl", None)               # D10/D11: DeepSeek and the coin flips are counted only
        else:
            x["pnl"] = round(x["pnl"], 2)
    out["groups"] = groups
    out["loss_cards"] = sum(groups.get(g, {}).get("losses", 0) for g in CARD_GROUPS)
    return out


def strats_view(paper_db: str, now_ms: int) -> dict:
    """{strategy: {trade: {...}, signal: {...}}} for the 36 (kind 'strategy' accounts only)."""
    from ..analysis import _close, ro_connect
    out: dict = {"strats": {}, "computed_at": int(now_ms)}
    c = ro_connect(paper_db)
    if c is None:
        out["error"] = "paper3.db 없음"
        return out
    try:
        names = [r[0] for r in c.execute("SELECT DISTINCT strategy FROM accounts WHERE kind = 'strategy'")]
        res: dict = {n: {} for n in names}
        q = ("SELECT a.strategy, a.timeframe, t.symbol, t.exit_time, t.exit_reason, t.roe, t.leverage, t.data "
             "FROM trades t JOIN accounts a ON a.account_id = t.account_id "
             "WHERE a.kind = 'strategy' AND t.id IN (SELECT MAX(t2.id) FROM trades t2 JOIN accounts a2 "
             "ON a2.account_id = t2.account_id WHERE a2.kind = 'strategy' GROUP BY a2.strategy)")
        for s, tf, sym, xt, why, roe, lev, raw in c.execute(q):
            res.setdefault(s, {})["trade"] = {"timeframe": tf, "symbol": sym, "exit_time": xt, "exit_reason": why,
                                              "roe": roe, "leverage": lev, "side": _side(raw)}
        since = int(now_ms) - 2 * DAY_MS
        q2 = ("SELECT strategy, timeframe, symbol, side, status, MAX(bar_close) FROM signal_log "
              "WHERE bar_close >= ? GROUP BY strategy")
        for s, tf, sym, side, status, bc in c.execute(q2, (since,)):
            if s in res:
                res[s]["signal"] = {"timeframe": tf, "symbol": sym, "side": side, "status": status, "bar_close": bc,
                                    "status_ko": STATUS_KO.get(status, status)}
        out["strats"] = res
    except sqlite3.Error as exc:
        out["error"] = _unread(exc)
    finally:
        _close(c)
    return out


def strat_view(paper_db: str, name: str, now_ms: int) -> dict:
    from ..analysis import _close, ro_connect
    since = kst_midnight(now_ms)
    out: dict = {"strategy": name, "since": since, "today": {}, "trades": [], "signals": [], "closed": 0,
                 "computed_at": int(now_ms)}
    c = ro_connect(paper_db)
    if c is None:
        out["error"] = "paper3.db 없음"
        return out
    try:
        for tf, n, wins, pnl in c.execute(
                "SELECT a.timeframe, COUNT(*), SUM(t.pnl > 0), SUM(t.pnl) FROM trades t JOIN accounts a "
                "ON a.account_id = t.account_id WHERE a.kind = 'strategy' AND a.strategy = ? AND t.exit_time >= ? "
                "GROUP BY a.timeframe", (name, since)):
            out["today"][tf] = {"n": int(n or 0), "wins": int(wins or 0), "pnl": round(float(pnl or 0.0), 2)}
        out["closed"] = int(c.execute("SELECT COUNT(*) FROM trades t JOIN accounts a ON a.account_id = t.account_id "
                                      "WHERE a.kind = 'strategy' AND a.strategy = ?", (name,)).fetchone()[0])
        for tf, sym, xt, why, roe, lev, raw in c.execute(
                "SELECT a.timeframe, t.symbol, t.exit_time, t.exit_reason, t.roe, t.leverage, t.data FROM trades t "
                "JOIN accounts a ON a.account_id = t.account_id WHERE a.kind = 'strategy' AND a.strategy = ? "
                "ORDER BY t.exit_time DESC LIMIT 5", (name,)):
            out["trades"].append({"timeframe": tf, "symbol": sym, "exit_time": xt, "exit_reason": why, "roe": roe,
                                  "leverage": lev, "side": _side(raw)})
        for bc, tf, sym, side, status in c.execute(
                "SELECT bar_close, timeframe, symbol, side, status FROM signal_log WHERE strategy = ? "
                "ORDER BY bar_close DESC LIMIT 6", (name,)):
            out["signals"].append({"bar_close": bc, "timeframe": tf, "symbol": sym, "side": side, "status": status,
                                   "status_ko": STATUS_KO.get(status, status)})
    except sqlite3.Error as exc:
        out["error"] = _unread(exc)
        out["signals"] = None                # not read: the page says 수집 전, not 아직 없음
    finally:
        _close(c)
    return out


def register(app, ctx) -> dict:
    lock = threading.Lock()
    cache: dict = {}

    def cached(key, fn):
        now = time.time()
        with lock:
            hit = cache.get(key)
            if hit and now - hit[0] < TTL_S:
                return hit[1]
        v = fn(int(now * 1000))
        with lock:
            if len(cache) > 64:
                cache.clear()
            cache[key] = (now, v)
        return v

    @app.get("/api/v4/people/today")
    def people_today():
        return cached("today", lambda now: today_view(ctx.db, now))

    @app.get("/api/v4/people/strats")
    def people_strats():
        return cached("strats", lambda now: strats_view(ctx.db, now))

    @app.get("/api/v4/people/strat")
    def people_strat(name: str = ""):
        name = str(name or "")[:64]
        if not name:
            return {"error": "name 없음"}
        return cached("s:" + name, lambda now: strat_view(ctx.db, name, now))

    return {"routes": ["/api/v4/people/today", "/api/v4/people/strats", "/api/v4/people/strat"]}
