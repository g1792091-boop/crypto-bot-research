"""실거래 › 추세 관제 (#/trend, the live site's first screen since owners 10-21 "대시보드 다시 만들어야겠네 야무지게 필요한부분들 전부다
포함해서"; 추세판단 봇, paperbot/trendbot.py): everything about the paper bot both executors follow, in one answer.

    GET /api/v4/livebots/trend   (5 s cache; the page asks every 15 s; the money and the live positions come from the
                                  site's summary /api/v4/livebots, which every tab reads anyway)
        bot      name, its first start on this database (``since``), the 2-week rule freeze (``freeze_until``), the last
                 stepped minute and how old it is (state ``heartbeat``)
        pause    the entry pause in force now by the config's own rules (KST weekend, ±N minutes of a US macro release,
                 the first N minutes after the NYSE open; combo.py's own functions), until when
        prices   each coin's last 1m close (the rule bot's live_bars, ``PAPERBOT_LIVE_RULE_DB``) and its minute
        position the paper position with the supervisor's view: the TIME deadline (entry + time_bars entry bars), the
                 higher bar's judgment now for its coin and whether it is against the position, locked or not, the
                 judgment and score it entered on
        coins    every coin's last closed 1h and 4h judgment (the bot's state ``trend``, written each minute it runs):
                 상승 / 하락 / 보류, the four judges, ADX and whether it is rising, 끝물, 힘 약함
        waits    the signals waiting for their pullback (level, until)
        pauses   the members and the coin-sides taking a break (and the daily loss stop when the config has one)
        funnel   today's (KST) entry signals: how many, passed the checks, pullback touched, entered, and what stopped the
                 rest (the bot's own reasons in categories)
        members  each entry member of the config: its role (눌림 · 자리 · 돌파 · 횡보), its signals today, its record since
                 the bot started, its pause
        trades   the paper trades since the bot started, newest first, with the exit reason and the judgment of the entry
        record   the paper account since the bot started: trades, wins, net P&L, by exit reason
        signals  the last 24 h of the entry members' signals by what became of them, with the bot's own reason
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
MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
KST_MS = 9 * HOUR
FREEZE_DAYS = L.TREND_FREEZE_DAYS          # owners 10-21 (#13 추천대로): the rules stay 2 weeks from the start, then the review
STALE_MS = 5 * MIN                   # the paper bot steps every minute
TF_MS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": HOUR, "4h": 4 * HOUR}
HTF_OF = {"30m": "1h", "1h": "4h"}
TRADES_KEEP = 30
# the entry members' roles (owners 10-21: 눌림 · 자리 · 돌파 · 횡보), in their words: one table for every live page
ROLE = L.TREND_ROLE
# what stopped a signal, grouped for the funnel (livebots.why_cat ids -> the funnel's words), in this order
BLOCK = (("trend", "추세 판단 (보류·반대·힘 약함·끝물)"), ("spot", "진입 자리 검사 (EMA20·RSI·돌파형 초입)"),
         ("chase", "추격 막기"), ("pause", "쉬는 시간 (주말·발표·나스닥)"), ("member_pause", "매매법 쉬는 중"),
         ("coin_pause", "코인·방향 쉬는 중"), ("daily", "하루 손실 한도"), ("nopull", "되돌림 안 옴"),
         ("one", "한 번에 하나 (이미 포지션)"), ("unread", "판단·조건 못 읽음"), ("other", "그 밖"))
BLOCK_OF = {"trend": "trend", "spot": "spot", "chase": "chase", "chase_unread": "chase", "weekend": "pause", "macro": "pause",
            "usopen": "pause", "member_pause": "member_pause", "coin_pause": "coin_pause", "daily": "daily", "nopull": "nopull",
            "trend_unread": "unread", "unread": "unread", "when": "other", "late": "other", "config": "other", "other": "other"}
EXIT_GROUP = (("LOCK", "계단 익절"), ("SL", "손절"), ("REV", "빠른 청산"), ("JUDGE", "감독: 추세 뒤집힘"), ("TIME", "감독: 시간 정리"),
              ("LIQ", "강제청산"), ("OTHER", "그 밖"))
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


def kst_day0(ms: int) -> int:
    return int(ms) - (int(ms) + KST_MS) % DAY


def pause_now(cfg: dict, now: int) -> dict:
    """The entry pause in force at ``now`` by the config's own rules (combo.py: kst_weekend, events.near,
    us_open_pause), the first one the bot checks: {"paused", "why", "ko", "until"}."""
    from ... import combo as C
    if cfg.get("no_weekend") and C.kst_weekend(now):
        d0 = kst_day0(now)
        wd = ((int(now) + KST_MS) // DAY + 3) % 7                 # Monday 0 .. Sunday 6 (combo.kst_weekend's count)
        return {"paused": True, "why": "weekend", "ko": "주말(한국 시간 토·일)이라 진입 쉬는 중", "until": d0 + (7 - wd) * DAY}
    mins = cfg.get("macro_blackout_min")
    if mins:
        try:
            from ... import events as EV
            near = EV.near(int(now), int(mins) * MIN, int(mins) * MIN)
        except Exception:  # noqa: BLE001  the release file unreadable: said so, never a guess
            return {"paused": None, "why": "macro_unread", "ko": "경제 발표 일정 파일을 못 읽음"}
        if near:
            e = near[0]
            return {"paused": True, "why": "macro", "ko": f"{EV.KIND_KO.get(e.kind, e.kind)} 발표 앞뒤 {int(mins)}분이라 진입 쉬는 중",
                    "until": int(e.ts_ms) + int(mins) * MIN, "event_ms": int(e.ts_ms)}
    us = cfg.get("us_open_pause_min")
    if us:
        why = C.us_open_pause(int(now), int(us))
        if why:
            t = int(now) - int(now) % MIN
            while C.us_open_pause(t, int(us)) and t < int(now) + 6 * HOUR:
                t += MIN
            return {"paused": True, "why": "usopen", "ko": why.replace(" 진입 안 함", "이라 진입 쉬는 중"), "until": t}
    return {"paused": False, "why": None, "ko": "쉬는 시간 아님"}


def prices_of(rule_db: str) -> dict:
    """{symbol: {"price", "ts"}} of the rule bot's newest stepped minute (read-only); {} when it cannot be read."""
    try:
        conn = L.open_ro(rule_db)
    except (OSError, sqlite3.Error):
        return {}
    try:
        top = conn.execute("SELECT MAX(ts) FROM live_bars").fetchone()[0]
        if top is None:
            return {}
        rows = conn.execute("SELECT symbol, close, ts FROM live_bars WHERE ts >= ?", (int(top) - 2 * MIN,)).fetchall()
        out: dict = {}
        for sym, close, ts in sorted(rows, key=lambda r: r[2]):
            out[sym] = {"price": float(close), "ts": int(ts)}
        return out
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def _trades(conn, since: Optional[int]) -> list:
    rows = conn.execute("SELECT id, data FROM trades WHERE account_id = ? AND entry_time >= ? ORDER BY exit_time DESC, id DESC",
                        (ACCOUNT, int(since or 0))).fetchall()
    out = []
    for tid, data in rows:
        t = _json(data)
        if t:
            out.append({**t, "_id": int(tid)})
    return out


def position_view(conn, st: dict, numbers: dict, now: int) -> Optional[dict]:
    """The paper position with the supervisor's view (paperbot/trendbot.py _before_step: TIME, JUDGE, before the first
    lock only)."""
    _ts, acc = _state(conn, "accounts")
    p = (((acc or {}).get("engines") or {}).get(ACCOUNT) or {}).get("position") if isinstance(acc, dict) else None
    if not isinstance(p, dict):
        return None
    sig = p.get("signal") if isinstance(p.get("signal"), dict) else {}
    meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
    tf, sym, side = sig.get("timeframe"), p.get("symbol"), int(p.get("side") or 0)
    et = int(p.get("entry_time") or 0)
    bars = int(numbers.get("time_bars") or 4)
    deadline = et + bars * TF_MS[tf] if tf in TF_MS else None
    locked = p.get("lock_roe") is not None
    htf = HTF_OF.get(tf)
    j = ((st.get("coins") or {}).get(sym) or {}).get(htf) if htf else None
    against = bool(j and not j.get("error") and int(j.get("raw") or 0) == -side)
    tr = meta.get("trend") if isinstance(meta.get("trend"), dict) else {}
    return {"symbol": sym, "side": side, "strategy": sig.get("strategy_id"), "tf": tf, "member": meta.get("member"),
            "role": ROLE.get(sig.get("strategy_id")), "entry_time": et, "entry_price": p.get("entry_price"),
            "stop": p.get("stop_price"), "lock_roe": p.get("lock_roe"), "locked": locked, "leverage": p.get("leverage"),
            "time_bars": bars, "deadline": deadline, "time_left_ms": None if deadline is None else deadline - int(now),
            "htf": htf, "judge": j, "judge_against": against, "supervised": not locked,
            "entry_judge": tr.get("judge"), "entry_score": tr.get("score"), "pull_level": meta.get("pull_level"),
            "judge_exit": bool(numbers.get("judge_exit", True))}


def funnel(conn, now: int) -> dict:
    """Today's (KST) entry signals: how many came, passed the trend and spot checks (waited for their pullback),
    touched it, entered; and what stopped the rest, in BLOCK's categories."""
    d0 = kst_day0(now)
    rows = conn.execute("SELECT status, data FROM signal_log WHERE bar_close >= ? AND bar_close <= ?",
                        (d0, int(now) + MIN)).fetchall()
    n = passed = touched = 0
    block: dict = {}
    for status, data in rows:
        why = _json(data).get("why")
        if status == "SUBMITTED" and why == "되돌림 확인":
            continue                                     # the entry row of a pullback: counted at its signal
        n += 1
        cat, _ko = L.why_cat(status, why) if status != "SUBMITTED" else ("submitted", "")
        if status in ("WAITING", "BROKE") or cat == "nopull":
            passed += 1
        if status == "BROKE":
            touched += 1
        if status == "FILTERED":
            g = BLOCK_OF.get(cat, "other")
            block[g] = block.get(g, 0) + 1
    entered = conn.execute("SELECT COUNT(*) FROM outcomes WHERE account_id = ? AND status = 'ENTERED' AND step_ts >= ?",
                           (ACCOUNT, d0)).fetchone()[0]
    one = conn.execute("SELECT COUNT(*) FROM outcomes WHERE account_id = ? AND status = 'SKIPPED' AND step_ts >= ?",
                       (ACCOUNT, d0)).fetchone()[0]
    if one:
        block["one"] = block.get("one", 0) + int(one)
    return {"day0": d0, "signals": n, "passed": passed, "touched": touched, "entered": int(entered),
            "blocked": [{"id": k, "ko": ko, "n": block[k]} for k, ko in BLOCK if block.get(k)]}


def members_view(conn, cfg: dict, trades: list, pauses: dict, now: int) -> list:
    d0 = kst_day0(now)
    today: dict = {}
    for member, status, data in conn.execute("SELECT strategy, status, data FROM signal_log WHERE bar_close >= ?", (d0,)):
        if status == "SUBMITTED" and _json(data).get("why") == "되돌림 확인":
            continue
        today[member] = today.get(member, 0) + 1
    out = []
    for i, m in enumerate(cfg.get("members") or [], 1):
        if not isinstance(m, dict):
            continue
        name, tf = m.get("strategy"), m.get("tf")
        label = f"{name}@{tf}"
        mine = [t for t in trades if t.get("strategy_id") == name and t.get("timeframe") == tf]
        wins = sum(1 for t in mine if float(t.get("pnl") or 0) > 0)
        side_only = None
        for c in m.get("when") or []:
            if isinstance(c, dict) and c.get("side") in ("long", "short"):
                side_only = c["side"]
        pz = (pauses.get("members") or {}).get(label)
        last = mine[0] if mine else None
        out.append({"order": i, "label": label, "strategy": name, "tf": tf, "role": ROLE.get(name), "side_only": side_only,
                    "htf": HTF_OF.get(tf), "today": today.get(label, 0), "trades": len(mine), "wins": wins,
                    "losses": len(mine) - wins, "pnl": sum(float(t.get("pnl") or 0) for t in mine),
                    "roe_sum": sum(float(t.get("roe") or 0) for t in mine),
                    "paused": {"ko": pz[0], "until": pz[1]} if pz else None,
                    "last": {"exit_reason": last.get("exit_reason"), "roe": last.get("roe"), "exit_time": last.get("exit_time")}
                    if last else None})
    return out


def record_view(trades: list, initial: Optional[float]) -> dict:
    n = len(trades)
    wins = sum(1 for t in trades if float(t.get("pnl") or 0) > 0)
    by: dict = {}
    for t in trades:
        r = t.get("exit_reason") if t.get("exit_reason") in dict(EXIT_GROUP) else "OTHER"
        b = by.setdefault(r, {"n": 0, "wins": 0, "pnl": 0.0})
        b["n"] += 1
        b["wins"] += float(t.get("pnl") or 0) > 0
        b["pnl"] += float(t.get("pnl") or 0)
    return {"n": n, "wins": wins, "losses": n - wins, "win_rate": wins / n if n else None,
            "pnl": sum(float(t.get("pnl") or 0) for t in trades), "roe_sum": sum(float(t.get("roe") or 0) for t in trades),
            "best": max((float(t.get("roe") or 0) for t in trades), default=None),
            "worst": min((float(t.get("roe") or 0) for t in trades), default=None), "initial": initial,
            "by_exit": [{"id": k, "ko": ko, **by[k]} for k, ko in EXIT_GROUP if k in by]}


def trades_view(trades: list) -> list:
    out = []
    for t in trades[:TRADES_KEEP]:
        ctx = t.get("context") if isinstance(t.get("context"), dict) else {}
        tr = ctx.get("trend") if isinstance(ctx.get("trend"), dict) else {}
        out.append({"id": t.get("_id"), "symbol": t.get("symbol"), "side": t.get("side"), "strategy": t.get("strategy_id"),
                    "tf": t.get("timeframe"), "role": ROLE.get(t.get("strategy_id")), "entry_time": t.get("entry_time"),
                    "exit_time": t.get("exit_time"), "entry_price": t.get("entry_price"), "exit_price": t.get("exit_price"),
                    "reason": t.get("exit_reason"), "reason_ko": L.EXIT_KO.get(t.get("exit_reason"), t.get("exit_reason")),
                    "why": ctx.get("exit_why"), "roe": t.get("roe"), "pnl": t.get("pnl"), "lock_roe": t.get("lock_roe"),
                    "entry_judge": tr.get("judge"), "entry_score": tr.get("score")})
    return out


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
        since = st.get("since")
        numbers = st.get("numbers") or {}
        hb_ts, hb = _state(conn, "heartbeat")
        last_step = (hb or {}).get("last_step") if isinstance(hb, dict) else None
        out = {**base, "state": "ok", "ts": ts, "age_ms": now - int(ts), "coins": st.get("coins") or {},
               "waits": st.get("waits") or [], "pauses": st.get("pauses") or {}, "rules": st.get("rules") or [],
               "numbers": numbers, "since": since,
               "bot": {"name": base["name"], "since": since,
                       "freeze_until": int(since) + FREEZE_DAYS * DAY if since else None, "freeze_days": FREEZE_DAYS,
                       "last_step": last_step, "heartbeat_ms": hb_ts,
                       "stale": hb_ts is None or now - int(hb_ts) > STALE_MS},
               "pause": pause_now(cfg, now)}
        tables = L._tables(conn)
        trades = _trades(conn, since) if "trades" in tables else []
        out["prices"] = prices_of(L.paths_more()["rule_db"])
        out["position"] = position_view(conn, st, numbers, now)
        out["funnel"] = funnel(conn, now) if {"signal_log", "outcomes"} <= tables else None
        out["members"] = members_view(conn, cfg, trades, st.get("pauses") or {}, now) if "signal_log" in tables else []
        out["trades"] = trades_view(trades)
        out["record"] = record_view(trades, cfg.get("initial_equity"))
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
