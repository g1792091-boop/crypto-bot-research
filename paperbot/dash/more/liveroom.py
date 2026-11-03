"""실거래 › 회의실 (#/room; owners 2026-11-01, with a picture and a video of someone's 'AI office' trading dashboard: "이렇게
가능할까?"): one round table, each seat one real program on the server, read-only from its own files and systemd.

HONESTY: a seat is a program this repo installs (deploy/, its systemd unit) and what it shows is read from that
program's own files (the three mix bots and their paper twins through dash/more/livemix.py, their checks' folders,
paperbot/liveteam.py's liveteam.db, systemd's own answer); the AI 분석팀's four members are the ones liveteam.py runs (they
read the records and explain them; they never trade). No invented staff, no made-up number: a program the server does
not have is said to be off, a file that cannot be read is said so.

    GET /api/v4/livebots/room

    {now_ms,
     seats: [{id, group ("bot" | "paper" | "check" | "ai" | "ops"), group_ko, name_ko, role_ko, bot, unit,
              state ("live" | "wait" | "idle" | "off" | "error"), state_ko, last_ms, last_ko}],
     feed:  [{ts, seat, who_ko, kind, kind_ko, text}] (newest first: the bots' logs, the paper twins' entries and exits,
             the morning checks, the team's meetings),
     pulse: {signals, entries, exits, checks, meetings} (the last 24 hours, from the same rows),
     team:  livedeck.totals_view (the three live bots), positions: [{bot, bot_ko, coin, side, entry, stop, step, opened_ms}],
     goal:  livedeck.goal_view (the owners' monthly ×6 against each bot's record this month: the 회의실's 목표 회의, the same
            arithmetic as each bot's 목표 연구),
     coins: [{symbol, coin, state, last, chg24, spark, trend (the last closed 30m bar's 추세 MACD side of 0, owners 11-02), tm30, hist (the 3합 histogram), cross}] (the six
            coins from livedeck.coins_view: Binance's closed bars and the bots' own formulas, read once a minute; the 3D
            room's floating screens)}

The states: live = doing something now (a bot holding a position, a meeting under way, this site), wait = running and
waiting for its next bar, idle = a scheduled program between its runs, off = not installed or turned off, error = it
should be running and its record says it is not (or it cannot be read).
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Callable, Optional

from . import livebots as L
from . import livedeck as D
from . import livemix as MX

ROUTE = "/api/v4/livebots/room"
MIN = 60_000
HOUR = 60 * MIN
DAY = 24 * HOUR
FEED_N = 40
PULSE_MS = DAY
CHECK_FRESH_MS = 15 * MIN                    # the checks' pass runs every 5 minutes (paperbot/mixcheck.py)
CHECK_UNITS = {"mix": "paperbot-mixcheck", "bybit": "paperbot-mixbybitcheck", "range": "paperbot-mixrangecheck"}
BACKUP_UNIT, BACKUP_SERVICE = "paperbot-backup.timer", "paperbot-backup.service"
SITE_UNIT = "paperbot-livedash"
GROUP_KO = {"bot": "실거래 봇", "paper": "모의 봇", "check": "점검", "ai": "AI 분석팀", "ops": "운영"}
STATE_KO = {"live": "일하는 중", "wait": "기다리는 중", "idle": "쉬는 중", "off": "꺼짐", "error": "확인 필요"}
SIDE_KO = {1: "롱", -1: "숏"}


def _i(x: Any) -> Optional[int]:
    return D._i(x)


def _mtime_ms(path: str) -> Optional[int]:
    try:
        return int(os.path.getmtime(path) * 1000)
    except OSError:
        return None


def _ago_ko(now: int, ts: Optional[int]) -> str:
    if ts is None:
        return "기록 없음"
    m = max(0, (now - ts) // MIN)
    return "방금" if m < 1 else f"{m}분 전" if m < 60 else f"{m // 60}시간 전" if m < 24 * 60 else f"{m // (24 * 60)}일 전"


def _last_text(rows: list) -> tuple:
    """(ts, words) of the newest row worth saying (a plain signal row without a side or a cross is the bar's routine)."""
    for r in reversed(rows or []):
        k = r.get("kind")
        if k not in D.TAPE_KINDS or (k == "signal" and not (r.get("side") or r.get("x0") or r.get("turn"))):
            continue
        return _i(r.get("ts")), f"{D.TAPE_KINDS[k]} · {D._tape_text(r)}"
    return (_i(rows[-1].get("ts")), "봉마다 판단 기록") if rows else (None, "아직 기록이 없어요")


# ---------------------------------------------------------------- the seats
def bot_seats(b: dict, prof: Any, now: int) -> list:
    """The live bot and its paper twin."""
    st = b.get("status") or {}
    words = f"{b.get('tf_ko') or '?'}봉 진입 · {b.get('trend_tf_ko') or '?'}봉 추세"
    live = {"id": f"{prof.id}-live", "group": "bot", "name_ko": b.get("name_ko") or prof.name, "bot": prof.id,
            "role_ko": f"{prof.account_ko} 실거래 · {words}", "unit": st.get("unit")}
    s = st.get("state")
    pos = b.get("position") if isinstance(b.get("position"), dict) else None
    if s == "off":
        live.update(state="off", state_ko=st.get("ko") or "설치 안 됨")
    elif s == "error":
        live.update(state="error", state_ko=st.get("ko") or "상태를 읽지 못했어요")
    elif s == "stopped":
        live.update(state="error", state_ko=st.get("ko") or "기록이 멈췄어요")
    elif pos and pos.get("state") == "ok":
        live.update(state="live", state_ko=f"보유 중 · {pos.get('coin') or MX.coin_ko(pos.get('symbol'))} {SIDE_KO.get(_i(pos.get('side')), '')}")
    else:
        live.update(state="wait", state_ko=f"신호 기다리는 중 ({b.get('tf_ko') or '?'}봉 마감마다)")
    live["last_ms"], live["last_ko"] = _last_text(b.get("_rows") or [])
    ps = (b.get("paper") or {}).get("status") or {}
    paper = {"id": f"{prof.id}-paper", "group": "paper", "name_ko": f"모의 {b.get('name_ko') or prof.name}", "bot": prof.id,
             "role_ko": "같은 규칙 · 진짜 돈 아님", "unit": ps.get("unit")}
    p = ps.get("state")
    if not ps or p == "off":
        paper.update(state="off", state_ko=ps.get("ko") or "모의 봇이 아직 없어요")
    elif p in ("error", "stopped"):
        paper.update(state="error", state_ko=ps.get("ko") or "기록이 멈췄어요")
    else:
        paper.update(state="wait", state_ko="같은 신호 기다리는 중")
    paper["last_ms"], paper["last_ko"] = _last_text(b.get("_prows") or [])
    return [live, paper]


def check_seat(b: dict, prof: Any, now: int) -> dict:
    """paperbot/mixcheck.py for this bot: the 5-minute pass (its state.json) and the morning check (last-morning.json)."""
    d = os.environ.get(prof.check_env) or prof.check_dir
    seat = {"id": f"{prof.id}-check", "group": "check", "name_ko": f"{b.get('name_ko') or prof.name} 점검", "bot": prof.id,
            "role_ko": "5분마다 손실 카드 · 아침 9:07 점검 (텔레그램)", "unit": CHECK_UNITS.get(prof.id)}
    pass_ms = _mtime_ms(os.path.join(d, "state.json"))
    morning_ms = _mtime_ms(os.path.join(d, "last-morning.json"))
    last = max([t for t in (pass_ms, morning_ms) if t is not None], default=None)
    seat["last_ms"] = last
    seat["last_ko"] = ("아침 점검을 보냈어요" if morning_ms is not None and morning_ms == last else
                       "손실 카드 확인" if last is not None else "아직 점검 기록이 없어요")
    if (b.get("status") or {}).get("state") == "off" or last is None:
        seat.update(state="off", state_ko="점검 기록이 없어요" if (b.get("status") or {}).get("state") != "off" else "봇이 설치 안 됨")
    elif pass_ms is not None and now - pass_ms <= CHECK_FRESH_MS:
        seat.update(state="idle", state_ko="다음 5분 확인 기다리는 중")
    else:
        seat.update(state="error", state_ko=f"마지막 5분 확인: {_ago_ko(now, pass_ms)} (멈췄을 수 있어요)" if pass_ms else "5분 확인 기록이 없어요")
    return seat


def team_seats(now: int, units: Callable) -> tuple:
    """The 실거래 분석 팀 (paperbot/liveteam.py): its four members, each one's newest words, a meeting under way; and its
    meetings for the feed."""
    from ... import liveteam as T
    path = os.environ.get(T.DB_ENV) or T.DB_DEFAULT
    active, _enabled = units(L.TEAM_UNIT)
    last: dict = {}
    running = False
    meetings: list = []
    err = None
    try:
        conn = L.open_ro(path)
        try:
            tabs = L._tables(conn)
            if "messages" in tabs:
                for role, ts, text in conn.execute("SELECT role, ts, text FROM messages m WHERE id = (SELECT MAX(id) FROM messages "
                                                    "WHERE role = m.role)"):
                    last[role] = (_i(ts), str(text or ""))
            if "meetings" in tabs:
                running = conn.execute("SELECT COUNT(*) FROM meetings WHERE state = 'running'").fetchone()[0] > 0
                meetings = [{"ts": _i(f or s), "title": t, "headline": hl, "state": stt} for s, f, t, hl, stt in conn.execute(
                    "SELECT started_ts, finished_ts, title, headline, state FROM meetings ORDER BY id DESC LIMIT 10")]
        finally:
            conn.close()
    except FileNotFoundError:
        err = None
    except (OSError, sqlite3.Error) as exc:
        err = f"{type(exc).__name__}: {exc}"[:200]
    seats = []
    for role, r in T.ROLES.items():
        ts, text = last.get(role, (None, ""))
        seat = {"id": f"team-{role}", "group": "ai", "name_ko": r["name"], "role_ko": f"{r['title']} · 읽고 설명만 해요 (거래 안 함)",
                "bot": None, "unit": L.TEAM_UNIT, "last_ms": ts,
                "last_ko": (text.splitlines()[0][:120] if text else "아직 회의에서 한 말이 없어요")}
        if err:
            seat.update(state="error", state_ko="분석팀 기록을 읽지 못했어요", reason=err)
        elif running:
            seat.update(state="live", state_ko="회의 중")
        elif active in ("active", "activating"):
            # (owners 11-01: the team meets on the three live bots: 하루 회의 every morning, 손실 회의, 주간 보고)
            seat.update(state="idle", state_ko="다음 회의 기다리는 중 (하루 · 손실 · 주간)")
        elif active:
            seat.update(state="off", state_ko="분석팀 타이머가 꺼져 있어요")
        else:
            seat.update(state="off", state_ko="systemd에 물어볼 수 없어요")
        seats.append(seat)
    return seats, meetings


def ops_seats(now: int, units: Callable, started: Callable) -> list:
    active, _e = units(BACKUP_UNIT)
    ran = started(BACKUP_SERVICE)
    backup = {"id": "ops-backup", "group": "ops", "name_ko": "백업", "role_ko": "매일 기록 파일 백업", "bot": None, "unit": BACKUP_UNIT,
              "last_ms": ran, "last_ko": "백업을 했어요" if ran else "systemd가 마지막 백업 시각을 말하지 않았어요"}
    if active in ("active", "activating"):
        backup.update(state="idle", state_ko="다음 백업 기다리는 중")
    elif active:
        backup.update(state="off", state_ko=f"백업 타이머: {active}")
    else:
        backup.update(state="off", state_ko="systemd에 물어볼 수 없어요")
    site = {"id": "ops-site", "group": "ops", "name_ko": "사이트", "role_ko": "이 화면을 보여 주는 프로그램 (읽기만)", "bot": None,
            "unit": SITE_UNIT, "state": "live", "state_ko": "지금 이 화면을 보여 주는 중", "last_ms": now, "last_ko": "이 답을 만들었어요"}
    return [backup, site]


# ---------------------------------------------------------------- the feed, the pulse
def feed_of(bots: list, checks: list, meetings: list) -> list:
    rows = []
    for r in D.tape_view(bots):
        rows.append({"ts": r["ts"], "seat": f"{r['bot']}-live", "who_ko": r["bot_ko"], "kind": r["kind"], "kind_ko": r["kind_ko"],
                     "text": f"{r['coin'] + ' · ' if r.get('coin') else ''}{r['text']}"})
    for b in bots:
        for r in b.get("_prows") or []:
            if r.get("kind") in ("entry", "exit") and _i(r.get("ts")) is not None:
                rows.append({"ts": _i(r["ts"]), "seat": f"{b['id']}-paper", "who_ko": f"모의 {b.get('name_ko')}", "kind": "paper_" + r["kind"],
                             "kind_ko": "모의 " + D.TAPE_KINDS[r["kind"]],
                             "text": f"{MX.coin_ko(r['symbol']) + ' · ' if r.get('symbol') else ''}{D._tape_text(r)}"})
    for c in checks:
        if c.get("last_ko") == "아침 점검을 보냈어요" and c.get("last_ms") is not None:
            rows.append({"ts": c["last_ms"], "seat": c["id"], "who_ko": c["name_ko"], "kind": "check", "kind_ko": "점검",
                         "text": "아침 점검을 텔레그램으로 보냈어요"})
    for m in meetings:
        if m.get("ts") is not None:
            rows.append({"ts": m["ts"], "seat": "team-lead", "who_ko": "AI 분석팀", "kind": "meeting", "kind_ko": "회의",
                         "text": f"{m.get('title') or '회의'}{' · ' + m['headline'] if m.get('headline') else ''}"})
    rows = [r for r in rows if r["ts"] is not None]
    rows.sort(key=lambda r: r["ts"], reverse=True)
    return rows[:FEED_N]


def pulse_of(bots: list, checks: list, meetings: list, now: int) -> dict:
    since = now - PULSE_MS
    out = {"signals": 0, "entries": 0, "exits": 0, "checks": 0, "meetings": 0}
    for b in bots:
        for r in b.get("_rows") or []:
            t = _i(r.get("ts"))
            if t is None or t < since:
                continue
            k = r.get("kind")
            if k == "signal" and (r.get("side") or r.get("x0") or r.get("turn")):
                out["signals"] += 1
            elif k in ("entry", "adopted"):
                out["entries"] += 1
            elif k == "exit":
                out["exits"] += 1
    out["checks"] = sum(1 for c in checks if c.get("last_ms") is not None and c["last_ms"] >= since)
    out["meetings"] = sum(1 for m in meetings if m.get("ts") is not None and m["ts"] >= since)
    return out


def coins_of(candles: Optional[Callable], now: int) -> list:
    """The six coins, small: their price, 24-hour change, 24-hour line, the 30m trend bar's 종합 and the last 15m bar's
    histogram and 0 cross (livedeck.coins_view: the same numbers as the 관제실)."""
    out = []
    for c in D.coins_view(candles, now):
        x = {k: c.get(k) for k in ("symbol", "coin", "state", "ko", "last", "chg24")}
        if c.get("state") == "ok":
            tr = c.get("trend30") or []
            hist = [h for h in (c.get("hist") or []) if h is not None]
            x.update(spark=(c.get("spark") or [])[-48:], trend=tr[-1][1] if tr else None, tm30=c.get("tm30"),
                     hist=hist[-1] if hist else None, cross=(c.get("cross") or [0])[-1])
        out.append(x)
    return out


def build(now: int, units: Callable, started: Callable, candles: Optional[Callable] = None) -> dict:
    bots, seats, checks = [], [], []
    for bid in D.bot_order():
        prof = MX.PROFILES[bid]
        try:
            b = D.bot_view(prof, now)
        except Exception as exc:  # noqa: BLE001  one bot's broken file never hides the others
            b = {"id": bid, "name_ko": prof.name, "status": {"state": "error", "ko": "기록을 읽지 못했어요"},
                 "reason": f"{type(exc).__name__}: {exc}"[:200]}
        bots.append(b)
        seats += bot_seats(b, prof, now)
        c = check_seat(b, prof, now)
        checks.append(c)
        seats.append(c)
    team, meetings = team_seats(now, units)
    seats += team + ops_seats(now, units, started)
    for s in seats:
        s["group_ko"] = GROUP_KO[s["group"]]
    positions = [{"bot": b["id"], "bot_ko": b.get("name_ko"), **{k: b["position"].get(k) for k in
                                                                 ("coin", "symbol", "side", "entry", "stop", "step", "opened_ms", "leverage")}}
                 for b in bots if isinstance(b.get("position"), dict) and b["position"].get("state") == "ok"]
    try:
        goal = D.goal_view(now, {b["id"]: b.get("name_ko") for b in bots})
    except Exception as exc:  # noqa: BLE001  the goal's arithmetic never hides the room
        goal = {"state": "error", "ko": "목표 숫자를 만들지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    try:
        coins = coins_of(candles, now)
    except Exception as exc:  # noqa: BLE001  the coins never hide the room
        coins = [{"symbol": s, "coin": MX.coin_ko(s), "state": "error", "ko": "코인 값을 만들지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:200]}
                 for s in D.COINS]
    return {"now_ms": now, "seats": seats, "feed": feed_of(bots, checks, meetings), "pulse": pulse_of(bots, checks, meetings, now),
            "team": D.totals_view(bots), "positions": positions, "coins": coins, "goal": goal, "states_ko": STATE_KO, "groups_ko": GROUP_KO}


def register(app, ctx) -> dict:
    import time

    from ... import livecheck as LC
    from ..app import json_finite
    candles = getattr(ctx, "candles", None)

    @app.get("/api/v4/livebots/room")                   # (= ROUTE: written out for tests/test_dash_v4.py's route list)
    def get_livebots_room():
        """실거래 › 회의실: the real programs round one table (read-only, 5 s cache)."""
        key = "room:" + json.dumps([MX.paths(bot=b) for b in D.bot_order()], sort_keys=True)
        return L._cached(key, lambda: json_finite(build(int(time.time() * 1000), LC.unit_state, LC.unit_started, candles)))

    return {"routes": [ROUTE]}
