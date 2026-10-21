"""실거래 › 추세 (#/trend, owners 10-21 추세판단 봇, paperbot/trendbot.py): what the paper bot both executors follow judged.

    GET /api/v4/livebots/trend   (5 s cache; the page asks every 30 s)
        coins    every coin's last closed 1h and 4h judgment (the bot's state ``trend``, written each minute it runs):
                 상승 / 하락 / 보류, the four judges, ADX and whether it is rising, 끝물, 힘 약함
        waits    the signals waiting for their pullback (level, until)
        pauses   the daily loss stop, the members and the coin-sides taking a break
        signals  the last 24 h of the entry members' signals by what became of them (되돌림 기다림 / 되돌림 확인 / 되돌림 안 옴
                 / 추세 판단 / 진입 자리 / 쉬기 / 쉬는 시간 …) with the bot's own reason, newest first
        sup      the supervisor's exits (감독 청산: 추세 판단 뒤집힘 · 시간 정리) of the last 7 days
        rules    the rules in the owners' words, as the bot describes them

The paper bot's database is PAPERBOT_LIVE_PAPER_DB (livebots.paths, the one both executors follow), read-only
(livebots.open_ro: mode=ro, query_only), one snapshot. ``state``: "ok"; "off" when the bot running there is not the trend
bot (its start record ``combo_run`` has no ``trend``); "missing" / "error" as every live page (CONTRACT §1.6: never a
zero for an unread value).
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Optional

from . import livebots as L

ACCOUNT = L.ACCOUNT
DAY = 86_400_000
SIG_SPAN_MS = DAY
SUP_SPAN_MS = 7 * DAY
SIG_KEEP = 200
TREND_CATS = {"waiting", "broke", "pullback_wait", "pulled", "nopull", "trend", "spot", "trend_unread", "daily",
              "member_pause", "coin_pause"}


def _json(x) -> dict:
    try:
        d = json.loads(x) if isinstance(x, (str, bytes)) and x else {}
    except (TypeError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def _state(conn, key: str):
    try:
        r = conn.execute("SELECT ts, data FROM state WHERE k = ?", (key,)).fetchone()
    except sqlite3.Error:
        return None, None
    return (int(r[0]), _json(r[1])) if r else (None, None)


def signals(conn, now: int) -> dict:
    """The last 24 h of signal_log rows the bot decided on (FILTERED / WAITING / BROKE / SUBMITTED), newest first."""
    rows = conn.execute("SELECT bar_close, timeframe, strategy, symbol, side, status, data FROM signal_log WHERE bar_close >= ? "
                        "ORDER BY bar_close DESC, id DESC LIMIT ?", (int(now) - SIG_SPAN_MS, SIG_KEEP)).fetchall()
    out, counts = [], {}
    for bc, tf, member, sym, side, status, data in rows:
        d = _json(data)
        why = d.get("why")
        if status == "SUBMITTED":
            cat, ko = ("entered", "진입 신호") if why == "되돌림 확인" else ("submitted", "바로 진입 신호")
        else:
            cat, ko = L.why_cat(status, why)
        tr = d.get("trend") if isinstance(d.get("trend"), dict) else {}
        judge = tr.get("judge") if isinstance(tr.get("judge"), dict) else {}
        counts[cat] = counts.get(cat, 0) + 1
        out.append({"bar_close": int(bc), "tf": tf, "member": member, "strategy": d.get("strategy") or str(member).split("@")[0],
                    "symbol": sym, "side": int(side), "status": status, "cat": cat, "cat_ko": ko,
                    "why": L.why_words(why) if why else None, "judge": judge.get("text"), "score": tr.get("score")})
    return {"rows": out, "counts": counts, "span_ms": SIG_SPAN_MS}


def supervisor_exits(conn, now: int) -> list:
    rows = conn.execute("SELECT data FROM trades WHERE account_id = ? AND exit_reason IN ('JUDGE', 'TIME') AND exit_time >= ? "
                        "ORDER BY exit_time DESC LIMIT 50", (ACCOUNT, int(now) - SUP_SPAN_MS)).fetchall()
    out = []
    for (data,) in rows:
        t = _json(data)
        ctx = t.get("context") if isinstance(t.get("context"), dict) else {}
        out.append({"symbol": t.get("symbol"), "side": t.get("side"), "strategy": t.get("strategy_id"), "tf": t.get("timeframe"),
                    "entry_time": t.get("entry_time"), "exit_time": t.get("exit_time"), "reason": t.get("exit_reason"),
                    "reason_ko": L.EXIT_KO.get(t.get("exit_reason"), t.get("exit_reason")), "why": ctx.get("exit_why"),
                    "roe": t.get("roe"), "pnl": t.get("pnl")})
    return out


def build(p: dict, now_ms: Optional[int] = None) -> dict:
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    path = p["paper"]
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return {"state": "missing", "reason_ko": L.MISSING_KO, "now_ms": now}
    except (OSError, sqlite3.Error) as exc:
        return {"state": "error", "reason_ko": "페이퍼 봇 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200],
                "now_ms": now}
    try:
        conn.execute("BEGIN")
        if "state" not in L._tables(conn):
            return {"state": "missing", "reason_ko": L.NO_TABLE_KO, "now_ms": now}
        _rt, run = _state(conn, "combo_run")
        cfg = (run or {}).get("config") if isinstance(run, dict) else None
        trend_on = isinstance(cfg, dict) and cfg.get("trend") is not None
        ts, st = _state(conn, "trend")
        base = {"now_ms": now, "name": (cfg or {}).get("name") if isinstance(cfg, dict) else None}
        if not trend_on:
            return {**base, "state": "off", "reason_ko": "지금 돌고 있는 페이퍼 봇은 추세판단 봇이 아니에요 (설정에 추세 판단이 없음)",
                    "saved_ts": ts}
        if st is None:
            return {**base, "state": "missing", "reason_ko": "추세판단 봇이 아직 첫 판단을 기록하지 않았어요 (켠 뒤 1~2분)"}
        out = {**base, "state": "ok", "ts": ts, "age_ms": now - int(ts), "coins": st.get("coins") or {},
               "waits": st.get("waits") or [], "pauses": st.get("pauses") or {}, "rules": st.get("rules") or [],
               "numbers": st.get("numbers") or {}, "since": st.get("since")}
        tables = L._tables(conn)
        out["signals"] = signals(conn, now) if "signal_log" in tables else {"rows": [], "counts": {}, "span_ms": SIG_SPAN_MS}
        out["sup"] = supervisor_exits(conn, now) if "trades" in tables else []
        return out
    except sqlite3.Error as exc:
        return {"state": "error", "reason_ko": "페이퍼 봇 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200],
                "now_ms": now}
    finally:
        conn.close()


def register(app, ctx) -> dict:
    from ..app import json_finite

    @app.get("/api/v4/livebots/trend")
    def get_livebots_trend():
        """실거래 › 추세: the trend bot's judgments, waits, pauses, last 24 h of signals and supervisor exits (5 s cache)."""
        p = L.paths()
        return L._cached("trend:" + json.dumps(p, sort_keys=True), lambda: json_finite(build(p)))

    return {"routes": ["/api/v4/livebots/trend"]}
