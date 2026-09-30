"""When the agent staff meet: code-only triggers for the rooms (no model calls).

The owners do not have to type anything for a discussion to start. Every tick of
the agents process calls ``find_due``; it reads the live run (paper3.db), the
nightly check (daily3.db), the owners' inbox (inbox.db) - all opened read-only by
the caller - and the rooms' own history (agents3.db: ``rounds`` and ``cursors``),
and returns the rounds that should run now, most urgent first.

Triggers (defaults in ``TriggerPolicy``; every number is configurable):

    incident      0  team:ops      new CRITICAL alert (liquidation, engine halted), signal
                                   timeout or data-gap WARN in paper3.db alerts (by alert
                                   rowid); nightly parity mismatch, missing 00:00 snapshot or
                                   missing 1m bars in daily3.db reports (by report day).
    owner         1  <room>        new owner_messages in that room (inbox.db) since the cursor.
    loss_cluster  2  strat:<S>     since the room's last round: >= 3 new losing trades of the
                                   strategy (any timeframe), or one loss-card tag
                                   (cards.tag_stats) in >= 3 of them; >= 4h between
                                   loss_cluster rounds of a room.
    bust          2  strat:<S>     a strategy account went bust (once per account).
    checkpoint    3  team:lead     day 30 / 60 / 90 ... since the run started.
    morning       3  team:market   08:00 KST, once per KST day (window 4h).
    evening       3  team:review   22:00 KST, once per KST day (window 4h),
                     team:lead     then the lead (after the review team has met).
    weekly        4  strat:<S>     on weekday (strategy index mod 7, KST) when the strategy has
                                   >= 30 closed trades since its last weekly review.

Limits: at most 3 rounds per room per KST day (incidents exempt), one round per
room per tick, at most 4 rounds per tick. Output order: (priority, oldest evidence).

Crash safety (the caller's side of the contract; ``begin_round`` / ``finish_round``
implement it): the round row stores ``trigger_data`` = ``Due.data`` (JSON) when
it starts. ``Due.data["cursors"]`` holds the evidence high-water marks; they are
written to ``cursors`` only when the round ends as ``done`` or ``no_action``.
Until then the same evidence is found again, so a crash never loses a trigger:

- a ``running`` round younger than 2h blocks the same trigger in the same room
  (it may still be working);
- a ``running`` round older than 2h, or a ``failed`` round, counts as a failed
  attempt: the trigger fires again once (``data["retry_of"]``); after two failed
  attempts for the same evidence it waits for new evidence;
- a ``stopped_budget`` round (AI usage cap) pauses its trigger class until the
  next KST day, when the budgets reset;
- a round that ended ``done`` / ``no_action`` is never repeated for the same
  evidence key, even if its cursors were not written.

``find_due`` never writes anything. All texts for the owners (``summary_ko``)
are Korean and written by code from the numbers.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Union

from .roster3 import STRATEGY_KO

MIN_MS = 60_000
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
KST_OFFSET_MS = 9 * HOUR_MS          # Korea has no daylight saving time

STRATEGIES = tuple(STRATEGY_KO)       # fixed order: the index decides the weekly weekday
TEAM_ROOMS = ("team:market", "team:risk", "team:ops", "team:review", "team:lead")

TRIGGERS = ("incident", "owner", "loss_cluster", "bust", "checkpoint", "morning", "evening", "weekly")
PRIORITY = {"incident": 0, "owner": 1, "loss_cluster": 2, "bust": 2, "checkpoint": 3, "morning": 3,
            "evening": 3, "weekly": 4}
# Sub-budget class of each trigger (the rooms engine keeps one AI budget per class).
TRIGGER_CLASS = {"incident": "incident", "owner": "owner", "loss_cluster": "loss", "bust": "loss",
                 "checkpoint": "scheduled", "morning": "scheduled", "evening": "scheduled",
                 "weekly": "weekly"}
ENDED_OK = ("done", "no_action")      # the only statuses that advance cursors

# (kind, level, text fragment) for paper3.db alerts; the first match wins, "" matches any text.
INCIDENT_ALERTS = (
    ("liquidation", "CRITICAL", "LIQUIDATED"),
    ("engine_halted", "CRITICAL", "ENGINE HALTED"),
    ("critical", "CRITICAL", ""),
    ("signal_timeout", "WARN", "did not answer within"),
    ("data_gap", "WARN", "data gap at"),
    ("data_gap", "WARN", "no new closed bars"),
    ("data_gap", "WARN", "history incomplete"),
    ("data_gap", "WARN", "returned no bars"),
)
INCIDENT_KO = {"liquidation": "강제청산", "engine_halted": "계좌 정지", "critical": "긴급 알림",
               "signal_timeout": "신호 계산 시간 초과", "data_gap": "데이터 끊김",
               "parity_mismatch": "재계산 불일치", "no_snapshot": "재계산 못 함(00:00 상태 저장 없음)",
               "missing_bars": "빠진 1분봉"}


def strat_room(strategy: str) -> str:
    return f"strat:{strategy}"


def all_rooms() -> tuple[str, ...]:
    return tuple(strat_room(s) for s in STRATEGIES) + TEAM_ROOMS


@dataclass
class Due:
    room_id: str
    trigger: str
    priority: int            # lower = sooner
    data: dict               # JSON-safe; stored as the round's trigger_data
    meeting: str


@dataclass
class TriggerPolicy:
    enabled: tuple = TRIGGERS
    priorities: dict = field(default_factory=lambda: dict(PRIORITY))
    # rate limits
    max_rounds_per_room_day: int = 3
    cap_exempt: tuple = ("incident",)
    max_rounds_per_tick: int = 4
    max_per_room_per_tick: int = 1
    # crash safety
    stale_ms: int = 2 * HOUR_MS          # a 'running' round older than this has failed
    max_attempts: int = 2                # first try + one retry for the same evidence
    rounds_lookback_ms: int = 40 * DAY_MS
    # incident
    incident_alerts: tuple = INCIDENT_ALERTS
    incident_min_gap_ms: int = 30 * MIN_MS   # batch a burst of alerts into one round
    incident_lookback_ms: int = 2 * DAY_MS   # first scan (no cursor yet) looks this far back
    nightly_parity: bool = True
    nightly_no_snapshot: bool = True
    nightly_min_missing_bars: int = 1
    # loss cluster
    loss_min_count: int = 3
    loss_tag_min_count: int = 3
    loss_min_gap_ms: int = 4 * HOUR_MS
    loss_lookback_ms: int = 7 * DAY_MS
    any_round_resets_losses: bool = True     # "since the room's last round" (any trigger)
    # weekly / checkpoint / scheduled meetings
    weekly_min_trades: int = 30
    checkpoint_every_days: int = 30
    morning_hour_kst: int = 8
    evening_hour_kst: int = 22
    meeting_window_ms: int = 4 * HOUR_MS
    max_items: int = 30                      # evidence rows copied into Due.data


# ---------------------------------------------------------------- time (KST)
def kst_day_start(ms: int) -> int:
    """UTC ms of 00:00 KST of the KST day containing ``ms``."""
    return ms - (ms + KST_OFFSET_MS) % DAY_MS


def kst_date(ms: int) -> str:
    return dt.datetime.fromtimestamp((ms + KST_OFFSET_MS) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def kst_weekday(ms: int) -> int:
    """Monday = 0 ... Sunday = 6, in KST."""
    return dt.datetime.fromtimestamp((ms + KST_OFFSET_MS) / 1000, dt.timezone.utc).weekday()


def slot_start(now_ms: int, hour_kst: int) -> int:
    """UTC ms of the latest ``hour_kst``:00 KST at or before ``now_ms``."""
    s = kst_day_start(now_ms) + hour_kst * HOUR_MS
    return s if s <= now_ms else s - DAY_MS


# ---------------------------------------------------------------- small db helpers
def _rows(conn: Optional[sqlite3.Connection], sql: str, args: Iterable = ()) -> list:
    """Rows as tuples; a missing database or table reads as empty."""
    if conn is None:
        return []
    try:
        return [tuple(r) for r in conn.execute(sql, tuple(args)).fetchall()]
    except sqlite3.OperationalError:
        return []


def _one(conn, sql: str, args: Iterable = ()):
    rows = _rows(conn, sql, args)
    return rows[0] if rows else None


def _json(text: Any) -> dict:
    if isinstance(text, dict):
        return text
    try:
        v = json.loads(text) if text else {}
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- state of the rooms
class _Rooms:
    """Rounds and cursors of agents3.db, read once per ``find_due``."""

    def __init__(self, conn: sqlite3.Connection, now_ms: int, p: TriggerPolicy):
        self.now, self.p = now_ms, p
        self.cursors = {k: v for k, v in _rows(conn, "SELECT k, v FROM cursors")}
        self.rounds = []
        for rid, room, trig, tdata, started, status, calls in _rows(
                conn, "SELECT round_id, room_id, trigger, trigger_data, started_ts, status, calls FROM rounds "
                      "WHERE started_ts >= ? OR status = 'running' ORDER BY round_id",
                (now_ms - p.rounds_lookback_ms,)):
            d = _json(tdata)
            self.rounds.append({"round_id": rid, "room_id": room, "trigger": trig, "key": d.get("key"),
                                "started_ts": _int(started), "status": status, "calls": _int(calls)})
        self.day_start = kst_day_start(now_ms)
        self.rooms = set(all_rooms()) | {r[0] for r in _rows(conn, "SELECT room_id FROM rooms")}

    def cursor(self, k: str, default: Optional[str] = None) -> Optional[str]:
        return self.cursors.get(k, default)

    def cursor_int(self, k: str) -> int:
        return _int(self.cursors.get(k), 0)

    def stale(self, r: dict) -> bool:
        return r["status"] == "running" and self.now - r["started_ts"] >= self.p.stale_ms

    def running_fresh(self, room: str, trigger: str) -> bool:
        return any(r["room_id"] == room and r["trigger"] == trigger and r["status"] == "running"
                   and not self.stale(r) for r in self.rounds)

    def same_key(self, room: str, trigger: str, key: str) -> list[dict]:
        return [r for r in self.rounds if r["room_id"] == room and r["trigger"] == trigger and r["key"] == key]

    def handled(self, room: str, trigger: str, key: str) -> bool:
        return any(r["status"] in ENDED_OK for r in self.same_key(room, trigger, key))

    def failed_attempts(self, room: str, trigger: str, key: str) -> list[dict]:
        return [r for r in self.same_key(room, trigger, key) if r["status"] == "failed" or self.stale(r)]

    def settled(self, room: str, trigger: str, key: str) -> bool:
        """Nothing more will happen for this evidence (met, given up, or deferred by the budget)."""
        rs = self.same_key(room, trigger, key)
        return (any(r["status"] in ENDED_OK + ("stopped_budget",) for r in rs)
                or len(self.failed_attempts(room, trigger, key)) >= self.p.max_attempts)

    def last_ok_start(self, room: str, trigger: str) -> Optional[int]:
        ts = [r["started_ts"] for r in self.rounds if r["room_id"] == room and r["trigger"] == trigger
              and (r["status"] in ENDED_OK or (r["status"] == "running" and not self.stale(r)))]
        return max(ts) if ts else None

    def class_blocked(self, cls: str) -> bool:
        return any(r["status"] == "stopped_budget" and r["started_ts"] >= self.day_start
                   and TRIGGER_CLASS.get(r["trigger"]) == cls for r in self.rounds)

    def rounds_today(self, room: str) -> int:
        return sum(1 for r in self.rounds if r["room_id"] == room and r["started_ts"] >= self.day_start
                   and r["trigger"] not in self.p.cap_exempt
                   and not (r["status"] == "stopped_budget" and r["calls"] == 0))


# ---------------------------------------------------------------- paper3.db helpers
def run_start(paper_ro: Optional[sqlite3.Connection]) -> Optional[int]:
    """When the paper run started: the creation time of its original accounts (the state
    'run' row is rewritten at every restart), else the first ``runs`` row, else state 'run'."""
    r = _one(paper_ro, "SELECT MIN(created_ts) FROM accounts WHERE kind IN ('strategy', 'random')")
    if r and r[0] is not None:
        return int(r[0])
    r = _one(paper_ro, "SELECT MIN(started_ts) FROM runs")
    if r and r[0] is not None:
        return int(r[0])
    r = _one(paper_ro, "SELECT ts FROM state WHERE k = 'run'")
    return None if r is None else int(r[0])


def _trade_hwm(paper_ro) -> int:
    r = _one(paper_ro, "SELECT MAX(id) FROM trades")
    return 0 if r is None or r[0] is None else int(r[0])


def _round_trip(paper_ro) -> float:
    from ..config import v3_settings
    r = _one(paper_ro, "SELECT data FROM state WHERE k = 'run'")
    fee = _json(r[0]).get("taker_fee") if r else None
    return v3_settings(**({"taker_fee": fee} if fee else {})).round_trip_cost


def _strategy_cursors(st: _Rooms, room: str, hwm: int) -> dict:
    """Cursors every strategy-room round advances: the room has now seen these trades."""
    return {f"loss:{room}": str(hwm)} if st.p.any_round_resets_losses else {}


# ---------------------------------------------------------------- triggers
def _incident(paper_ro, daily_ro, st: _Rooms) -> list[Due]:
    p, room = st.p, "team:ops"
    items: list[dict] = []
    cur_a = st.cursor_int("incident:alert_rowid")
    hwm_a = cur_a
    since = st.now - p.incident_lookback_ms if cur_a == 0 else 0
    for rowid, ts, level, text in _rows(paper_ro, "SELECT rowid, ts, level, text FROM alerts "
                                                  "WHERE rowid > ? ORDER BY rowid", (cur_a,)):
        hwm_a = max(hwm_a, int(rowid))
        if int(ts) < since:
            continue
        kind = next((k for k, lvl, frag in p.incident_alerts
                     if level == lvl and (not frag or frag in (text or ""))), None)
        if kind:
            items.append({"source": "alert", "rowid": int(rowid), "ts": int(ts), "kind": kind,
                          "level": level, "text": (text or "")[:300]})
    cur_d = st.cursor("incident:report_day") or ""
    if not cur_d:
        cur_d = kst_date(st.now - p.incident_lookback_ms - DAY_MS)
    hwm_d = cur_d
    for day, ts, data in _rows(daily_ro, "SELECT day, ts, data FROM reports WHERE day > ? ORDER BY day",
                               (cur_d,)):
        hwm_d = max(hwm_d, day)
        rep = _json(data)
        par = rep.get("parity")
        found = []
        if isinstance(par, dict) and p.nightly_parity and _int(par.get("mismatched_accounts")) > 0:
            found.append(("parity_mismatch", {"mismatched_accounts": _int(par["mismatched_accounts"]),
                                              "accounts": _int(par.get("accounts"))}))
        elif isinstance(par, str) and p.nightly_no_snapshot:
            found.append(("no_snapshot", {"parity": par[:200]}))
        dq = rep.get("data_quality") or {}
        missing = {s: _int(q.get("missing")) for s, q in dq.items()
                   if isinstance(q, dict) and _int(q.get("missing")) >= p.nightly_min_missing_bars}
        if missing:
            found.append(("missing_bars", {"missing": missing}))
        for kind, extra in found:
            items.append({"source": "nightly", "day": day, "ts": _int(ts), "kind": kind, **extra})
    if not items:
        return []
    last = st.last_ok_start(room, "incident")
    if last is not None and st.now - last < p.incident_min_gap_ms:
        return []
    counts: dict[str, int] = {}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
    a_ids = [it["rowid"] for it in items if it["source"] == "alert"]
    d_ids = [it["day"] for it in items if it["source"] == "nightly"]
    key = f"incident:a{max(a_ids) if a_ids else cur_a}:d{max(d_ids) if d_ids else '-'}"
    cursors = {"incident:alert_rowid": str(hwm_a), "incident:report_day": hwm_d}
    text = "사고 점검: " + ", ".join(f"{INCIDENT_KO.get(k, k)} {n}건" for k, n in counts.items())
    return [_due(st, room, "incident", key, min(it["ts"] for it in items), cursors, text,
                 counts=counts, items=items[-p.max_items:], n_items=len(items))]


def _owner(inbox_ro, paper_ro, st: _Rooms) -> list[Due]:
    lo = min((st.cursor_int(f"owner:{r}") for r in st.rooms), default=0)
    by_room: dict[str, list] = {}
    for mid, ts, room, author, text in _rows(inbox_ro, "SELECT id, ts, room_id, author, text FROM owner_messages "
                                                       "WHERE id > ? ORDER BY id", (lo,)):
        if room in st.rooms and int(mid) > st.cursor_int(f"owner:{room}"):
            by_room.setdefault(room, []).append({"id": int(mid), "ts": _int(ts), "author": author,
                                                 "text": (text or "")[:1000]})
    hwm = _trade_hwm(paper_ro) if any(r.startswith("strat:") for r in by_room) else 0
    out = []
    for room, msgs in by_room.items():
        last = msgs[-1]["id"]
        cursors = {**(_strategy_cursors(st, room, hwm) if room.startswith("strat:") else {}),
                   f"owner:{room}": str(last)}
        out.append(_due(st, room, "owner", f"owner:{room}:{last}", msgs[0]["ts"], cursors,
                        f"두 분이 남긴 새 메시지 {len(msgs)}건", message_ids=[m["id"] for m in msgs],
                        messages=msgs[-10:]))
    return out


def _strategy_trades(paper_ro, since_id: int, losses_only: bool, since_ms: int = 0) -> list[tuple]:
    q = ("SELECT t.id, t.account_id, t.exit_time, t.pnl, t.data, a.strategy, a.timeframe FROM trades t "
         "JOIN accounts a ON a.account_id = t.account_id WHERE a.kind = 'strategy' AND t.id > ? "
         "AND t.exit_time >= ?")
    if losses_only:
        q += " AND t.pnl < 0"
    return _rows(paper_ro, q + " ORDER BY t.id", (since_id, since_ms))


def _loss_cluster(paper_ro, st: _Rooms) -> list[Due]:
    from ..cards import card, tag_stats
    p = st.p
    cur = {s: st.cursor_int(f"loss:{strat_room(s)}") for s in STRATEGIES}
    rows = _strategy_trades(paper_ro, min(cur.values(), default=0), True, st.now - p.loss_lookback_ms)
    by_s: dict[str, list] = {}
    for r in rows:
        if r[5] in cur and r[0] > cur[r[5]]:
            by_s.setdefault(r[5], []).append(r)
    if not by_s:
        return []
    hwm, rt = _trade_hwm(paper_ro), _round_trip(paper_ro)
    out = []
    for s, lst in by_s.items():
        room = strat_room(s)
        last = st.last_ok_start(room, "loss_cluster")
        if last is not None and st.now - last < p.loss_min_gap_ms:
            continue
        cards = []
        for r in lst:
            try:
                cards.append(card(r[1], json.loads(r[4]), rt))
            except (KeyError, TypeError, ValueError):
                pass                                  # an odd row still counts as a loss
        top = [{"tag": r["tag"], "losses": r["losses"]} for r in tag_stats(cards)
               if r["losses"] >= p.loss_tag_min_count]
        top.sort(key=lambda r: -r["losses"])
        if len(lst) < p.loss_min_count and not top:
            continue
        tfs: dict[str, int] = {}
        for r in lst:
            tfs[r[6]] = tfs.get(r[6], 0) + 1
        reasons: dict[str, int] = {}
        for c in cards:
            reasons[c["reason"]] = reasons.get(c["reason"], 0) + 1
        cursors = {**_strategy_cursors(st, room, hwm), f"loss:{room}": str(hwm)}
        text = (f"{STRATEGY_KO[s]}: 새 손실 {len(lst)}건 ("
                + ", ".join(f"{tf} {n}건" for tf, n in tfs.items()) + ")")
        if top:
            text += " · 많이 나온 특징: " + ", ".join(f"{t['tag']} {t['losses']}건" for t in top[:3])
        out.append(_due(st, room, "loss_cluster", f"loss:{s}:{lst[-1][0]}", min(r[2] for r in lst), cursors,
                        text, strategy=s, losses=len(lst), trade_ids=[r[0] for r in lst][-p.max_items:],
                        by_timeframe=tfs, exit_reasons=reasons, top_tags=top,
                        touched_first_lock=sum(bool(c.get("touched_first_lock")) for c in cards),
                        oldest_exit=min(r[2] for r in lst), newest_exit=max(r[2] for r in lst)))
    return out


def _bust(paper_ro, st: _Rooms) -> list[Due]:
    accts = {aid: (s, tf) for aid, s, tf in _rows(paper_ro, "SELECT account_id, strategy, timeframe FROM accounts "
                                                             "WHERE kind = 'strategy'")}
    busts: dict[str, int] = {}
    r = _one(paper_ro, "SELECT ts, data FROM state WHERE k = 'accounts'")
    if r is not None:
        for aid, e in (_json(r[1]).get("engines") or {}).items():
            if isinstance(e, dict) and e.get("bust"):
                busts[aid] = int(r[0])
    for ts, text in _rows(paper_ro, "SELECT ts, text FROM alerts WHERE level = 'WARN' AND text LIKE '[%] BUST:%'"):
        aid = text[1:text.find("]")]
        busts[aid] = min(int(ts), busts.get(aid, int(ts)))
    by_s: dict[str, dict] = {}
    for aid, ts in busts.items():
        if aid in accts and accts[aid][0] in STRATEGY_KO and st.cursor(f"bust:{aid}") is None:
            by_s.setdefault(accts[aid][0], {})[aid] = ts
    hwm = _trade_hwm(paper_ro) if by_s else 0
    out = []
    for s, got in by_s.items():
        room = strat_room(s)
        aids = sorted(got)
        cursors = {**_strategy_cursors(st, room, hwm), **{f"bust:{a}": str(got[a]) for a in aids}}
        out.append(_due(st, room, "bust", "bust:" + ",".join(aids), min(got.values()), cursors,
                        f"{STRATEGY_KO[s]}: 계좌 파산 " + ", ".join(aids), strategy=s, accounts=aids))
    return out


def _checkpoint(paper_ro, st: _Rooms) -> list[Due]:
    every = st.p.checkpoint_every_days
    start = run_start(paper_ro)
    if start is None or every <= 0 or st.now < start:
        return []
    days = (st.now - start) // DAY_MS
    cp = days // every * every
    if cp < every or cp <= st.cursor_int("checkpoint:day"):
        return []
    return [_due(st, "team:lead", "checkpoint", f"checkpoint:{cp}", start + cp * DAY_MS,
                 {"checkpoint:day": str(cp)}, f"{cp}일 점검: 시작 후 {days}일째",
                 day=cp, days_elapsed=int(days), run_start=start)]


def _weekly(paper_ro, st: _Rooms) -> list[Due]:
    wd, today = kst_weekday(st.now), kst_date(st.now)
    mine = [s for i, s in enumerate(STRATEGIES) if i % 7 == wd]
    if not mine:
        return []
    hwm = _trade_hwm(paper_ro)
    out = []
    for s in mine:
        room = strat_room(s)
        cur = st.cursor_int(f"weekly:{room}")
        r = _one(paper_ro, "SELECT COUNT(*), MIN(t.exit_time), MAX(t.id) FROM trades t JOIN accounts a "
                           "ON a.account_id = t.account_id WHERE a.kind = 'strategy' AND a.strategy = ? "
                           "AND t.id > ?", (s, cur))
        n = 0 if r is None else int(r[0])
        if n < st.p.weekly_min_trades:
            continue
        cursors = {**_strategy_cursors(st, room, hwm), f"weekly:{room}": str(hwm)}
        out.append(_due(st, room, "weekly", f"weekly:{s}:{today}", int(r[1]), cursors,
                        f"{STRATEGY_KO[s]} 주간 검토: 지난 검토 뒤 거래 {n}건", strategy=s, trades=n))
    return out


def _scheduled(st: _Rooms) -> list[Due]:
    p, out = st.p, []
    plan = [("morning", p.morning_hour_kst, (("team:market", "아침 회의 (08:00)"),)),
            ("evening", p.evening_hour_kst, (("team:review", "저녁 점검 (22:00): 손익 복기"),
                                            ("team:lead", "저녁 점검 (22:00): 팀장 요약")))]
    for name, hour, rooms in plan:
        if name not in p.enabled:
            continue
        s0 = slot_start(st.now, hour)
        if st.now - s0 >= p.meeting_window_ms:
            continue
        day = kst_date(s0)
        key = f"{name}:{day}"
        for seq, (room, text) in enumerate(rooms):
            ck = f"sched:{name}:{room}"
            if (st.cursor(ck) or "") >= day:
                continue
            d = _due(st, room, name, key, s0, {ck: day}, text, slot=day, slot_start=s0)
            d.data["seq"] = seq
            if seq > 0:
                d.data["after"] = {"room_id": rooms[seq - 1][0], "key": key}
            out.append(d)
    return out


def _due(st: _Rooms, room: str, trigger: str, key: str, evidence_ts: int, cursors: dict, summary_ko: str,
         **extra) -> Due:
    data = {"key": key, "evidence_ts": int(evidence_ts), "cursors": {k: str(v) for k, v in cursors.items()},
            "class": TRIGGER_CLASS[trigger], "kst_day": kst_date(st.now), "summary_ko": summary_ko,
            "retry_of": None, **extra}
    return Due(room_id=room, trigger=trigger, priority=int(st.p.priorities.get(trigger, PRIORITY[trigger])),
               data=data, meeting=trigger)


# ---------------------------------------------------------------- main entry
def find_due(paper_ro: Optional[sqlite3.Connection], daily_ro: Optional[sqlite3.Connection],
             agents_conn: sqlite3.Connection, inbox_ro: Optional[sqlite3.Connection], now_ms: int,
             policy: Optional[TriggerPolicy] = None) -> list[Due]:
    """Rounds to run now, sorted by (priority, oldest evidence). Reads only."""
    p = policy or TriggerPolicy()
    st = _Rooms(agents_conn, now_ms, p)
    found: list[Due] = []
    if "incident" in p.enabled:
        found += _incident(paper_ro, daily_ro, st)
    if "owner" in p.enabled:
        found += _owner(inbox_ro, paper_ro, st)
    if "loss_cluster" in p.enabled:
        found += _loss_cluster(paper_ro, st)
    if "bust" in p.enabled:
        found += _bust(paper_ro, st)
    if "checkpoint" in p.enabled:
        found += _checkpoint(paper_ro, st)
    if "weekly" in p.enabled:
        found += _weekly(paper_ro, st)
    found += _scheduled(st)

    ok: list[Due] = []
    for d in found:
        key = d.data["key"]
        if st.class_blocked(d.data["class"]) or st.running_fresh(d.room_id, d.trigger):
            continue
        if st.handled(d.room_id, d.trigger, key):
            continue
        failed = st.failed_attempts(d.room_id, d.trigger, key)
        if len(failed) >= p.max_attempts:
            continue
        if failed:
            d.data["retry_of"] = failed[-1]["round_id"]
            d.data["summary_ko"] = "(중단된 회의 다시 시작) " + d.data["summary_ko"]
        ok.append(d)
    ok.sort(key=lambda d: (d.priority, d.data["evidence_ts"], d.data.get("seq", 0), d.room_id))

    picked: list[Due] = []
    per_room: dict[str, int] = {}
    for d in ok:
        if len(picked) >= p.max_rounds_per_tick:
            break
        room = d.room_id
        if per_room.get(room, 0) >= p.max_per_room_per_tick:
            continue
        if d.trigger not in p.cap_exempt and st.rounds_today(room) + per_room.get(room, 0) \
                >= p.max_rounds_per_room_day:
            continue
        after = d.data.get("after")
        if after and not (st.settled(after["room_id"], d.trigger, after["key"])
                          or st.rounds_today(after["room_id"]) >= p.max_rounds_per_room_day
                          or any(x.room_id == after["room_id"] and x.data["key"] == after["key"]
                                 for x in picked)):
            continue            # the lead meets after the review team
        picked.append(d)
        per_room[room] = per_room.get(room, 0) + 1
    return picked


# ---------------------------------------------------------------- the caller's side (rounds + cursors)
def trigger_data(due: Due) -> str:
    return json.dumps(due.data, ensure_ascii=False, sort_keys=True, default=str)


def _newer(old: Optional[str], new: str) -> bool:
    if old is None:
        return True
    try:
        return int(new) > int(old)
    except (TypeError, ValueError):
        return str(new) > str(old)


def advance_cursors(agents_conn: sqlite3.Connection, due_or_data: Union[Due, dict], commit: bool = True) -> dict:
    """Write the evidence high-water marks of a finished round. Cursors only move forward
    (numbers by value, days by text). Returns what was written."""
    data = due_or_data.data if isinstance(due_or_data, Due) else _json(due_or_data)
    wrote = {}
    for k, v in (data.get("cursors") or {}).items():
        r = agents_conn.execute("SELECT v FROM cursors WHERE k = ?", (k,)).fetchone()
        if _newer(None if r is None else r[0], str(v)):
            agents_conn.execute("INSERT INTO cursors (k, v) VALUES (?, ?) "
                                "ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, str(v)))
            wrote[k] = str(v)
    if commit:
        agents_conn.commit()
    return wrote


def expire_stale_rounds(agents_conn: sqlite3.Connection, now_ms: int,
                        policy: Optional[TriggerPolicy] = None) -> list[int]:
    """Mark 'running' rounds older than ``policy.stale_ms`` as 'failed' (a tick died during
    them), so the dashboard stops showing them as live. Optional: ``find_due`` already treats
    them as failed attempts, so calling this does not change which rounds are due."""
    p = policy or TriggerPolicy()
    ids = [int(r[0]) for r in _rows(agents_conn, "SELECT round_id FROM rounds WHERE status = 'running' "
                                                 "AND started_ts <= ?", (now_ms - p.stale_ms,))]
    why = json.dumps({"reason": "stale", "detail": "회의 도중 멈춤 (2시간 넘게 진행 중)"}, ensure_ascii=False)
    for rid in ids:
        agents_conn.execute("UPDATE rounds SET status = 'failed', ended_ts = ?, decision = ? WHERE round_id = ?",
                            (int(now_ms), why, rid))
    if ids:
        agents_conn.commit()
    return ids


def begin_round(agents_conn: sqlite3.Connection, due: Due, now_ms: int) -> int:
    """Insert the 'running' round with its trigger_data (evidence and cursors) and commit,
    before the first model call."""
    cur = agents_conn.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, status, calls, "
                              "tokens) VALUES (?, ?, ?, ?, 'running', 0, 0)",
                              (due.room_id, due.trigger, trigger_data(due), int(now_ms)))
    agents_conn.commit()
    return int(cur.lastrowid)


def finish_round(agents_conn: sqlite3.Connection, round_id: int, status: str, now_ms: int,
                 decision: Optional[dict] = None, calls: Optional[int] = None,
                 tokens: Optional[int] = None) -> dict:
    """End a round; for 'done' / 'no_action' also advance the cursors stored in its
    trigger_data, in the same transaction. 'failed' and 'stopped_budget' leave the
    cursors, so the trigger fires again (once, or on the next KST day)."""
    r = agents_conn.execute("SELECT trigger_data FROM rounds WHERE round_id = ?", (round_id,)).fetchone()
    if r is None:
        raise KeyError(round_id)
    sets, args = ["ended_ts = ?", "status = ?"], [int(now_ms), status]
    if decision is not None:
        sets.append("decision = ?")
        args.append(json.dumps(decision, ensure_ascii=False, default=str))
    if calls is not None:
        sets.append("calls = ?")
        args.append(int(calls))
    if tokens is not None:
        sets.append("tokens = ?")
        args.append(int(tokens))
    agents_conn.execute(f"UPDATE rounds SET {', '.join(sets)} WHERE round_id = ?", (*args, round_id))
    wrote = advance_cursors(agents_conn, _json(r[0]), commit=False) if status in ENDED_OK else {}
    agents_conn.commit()
    return wrote
