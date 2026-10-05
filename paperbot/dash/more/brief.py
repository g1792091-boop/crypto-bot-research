"""오늘의 회의 결론 보고판 (v4 additions, wave 2 ⑥): today's finished meetings in three lines. Read-only.

    GET /api/v4/brief/meetings          today (Korea time): what the home's 보고판 and the 대표실 desk show

One small answer (agents3.db, read-only; nothing is ever written):

- n: meetings that started today; finished: meetings that ended today (whenever they started); decided: of those, the
  ones that ended with a decision (status 'done'); split: of those, the ones whose lead left a disagreement open (the
  summary turn's answer.open_disagreement, what 회의 요약 shows in amber).
- lines: the newest finished meetings (at most 3): room title, kind, end time, status and action, and the conclusion
  line = the lead's first summary line, else the code summary's first line, else the meeting kind. ``dis`` is the
  disagreement left open (cut), ``lead_n`` how many summary lines the lead wrote (the rest is in 회의 요약).
- more: how many finished meetings today are not in ``lines`` (회의 결론 전체 lists them all).

Every text is a stored line (the lead's or the code's), never written here. Meetings still running are not counted
as finished; the page takes 회의 중 from /api/office ``running`` (real state).

Cost: one scan of today's rounds and one indexed read (messages_room) of the finished meetings' summary turns.
Cached 30 s.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Optional

from .story import DAY_MS, _action, _loads, _strip, day_start, kst_day

TTL_S = 30.0
SHOW = 3
DIS_MAX = 160


def _summaries(a: sqlite3.Connection, rows: list) -> dict:
    """{round_id: (lead lines, open disagreement)} from each meeting's last 'summary' turn."""
    if not rows:
        return {}
    rooms = sorted({r[1] for r in rows})
    ids = [r[0] for r in rows]
    out: dict = {}
    for i in range(0, len(ids), 400):
        part = ids[i:i + 400]
        q = (f"SELECT round_id, data FROM messages WHERE room_id IN ({','.join('?' * len(rooms))}) "
             f"AND round_id IN ({','.join('?' * len(part))}) AND kind = 'summary' ORDER BY id")
        for rid, data in a.execute(q, (*rooms, *part)):
            ans = (_loads(data) or {}).get("answer") if data else None
            if not isinstance(ans, dict):
                continue
            lines = [_strip(x) for x in ans.get("summary") or [] if str(x or "").strip()] \
                if isinstance(ans.get("summary"), list) else []
            out[rid] = (lines, str(ans.get("open_disagreement") or "").strip()[:DIS_MAX])
    return out


def meetings_brief(a: Optional[sqlite3.Connection], now: int, show: int = SHOW) -> dict:
    """Today's board (Korea-time day of ``now``): counts and the newest ``show`` conclusions."""
    day = kst_day(now)
    t0 = day_start(day)
    t1 = t0 + DAY_MS
    out: dict = {"ready": False, "day": day, "now": now, "n": 0, "finished": 0, "decided": 0, "split": 0,
                 "lines": [], "more": 0}
    if a is None:
        out["error"] = "agents3.db 없음"
        return out
    try:
        if not a.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rounds'").fetchone():
            out["ready"] = True
            return out
        out["n"] = int(a.execute("SELECT COUNT(*) FROM rounds WHERE started_ts >= ? AND started_ts < ?",
                                 (t0, t1)).fetchone()[0])
        rows = a.execute(
            "SELECT r.round_id, r.room_id, r.trigger, r.started_ts, r.ended_ts, r.status, r.decision, m.title "
            "FROM rounds r LEFT JOIN rooms m ON m.room_id = r.room_id WHERE r.status != 'running' "
            "AND r.ended_ts >= ? AND r.ended_ts < ? ORDER BY r.ended_ts DESC, r.round_id DESC", (t0, t1)).fetchall()
        summ = _summaries(a, rows)
    except sqlite3.Error as exc:
        out["error"] = f"agents3.db를 읽지 못함: {type(exc).__name__}"
        return out
    from ..app import _trigger_ko           # the meeting kinds in Korean (the office and the digest use the same table)
    tko = _trigger_ko()
    out["ready"] = True
    out["finished"] = len(rows)
    out["decided"] = sum(1 for r in rows if r[5] == "done")
    out["split"] = sum(1 for r in rows if (summ.get(r[0]) or ((), ""))[1])
    for rid, room, trig, st_ts, en_ts, status, dec, title in rows[:max(0, int(show))]:
        d = _loads(dec) or {}
        d = d if isinstance(d, dict) else {}
        lead, dis = summ.get(rid) or ([], "")
        kind = tko.get(trig, trig)
        out["lines"].append({
            "round_id": int(rid), "room_id": room, "title": title or room, "trigger": trig, "trigger_ko": kind,
            "started_ts": st_ts, "ts": en_ts, "status": status, "action": _action(d),
            "line": (lead[0] if lead else "") or _strip(d.get("summary_ko")) or kind,
            "from": "lead" if lead else "code" if _strip(d.get("summary_ko")) else "kind",
            "lead_n": len(lead), "dis": dis})
    out["more"] = max(0, out["finished"] - len(out["lines"]))
    return out


def register(app, ctx) -> dict:
    rooms = ctx.rooms
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/brief/meetings")
    def get_brief_meetings():
        """Today's meeting conclusions board (counts + the newest three; cached 30 s)."""
        now = int(time.time() * 1000)
        key = kst_day(now)
        hit = cache.get(key)
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
        with lock:                           # one computation at a time (two phones opening together)
            hit = cache.get(key)
            if hit and time.time() - hit[0] < TTL_S:
                return hit[1]
            with rooms.ro(rooms.agents_db) as a:
                v = meetings_brief(a, now)
            cache.clear()                    # only today is ever asked for
            cache[key] = (time.time(), v)
        return v

    return {"routes": ["/api/v4/brief/meetings"], "cache": cache}
