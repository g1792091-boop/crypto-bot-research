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
    owner         1  <room>        new owner_messages in that room (inbox.db) since the cursor (the
                                   oldest ``owner_batch`` (10) per meeting; the rest open the next one).
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
                                   >= 30 closed trades since its last weekly review; a review
                                   the budget deferred or stopped stays due on the next days
                                   until it has run (same slot key).

Limits: at most 3 rounds per room per KST day (incidents exempt; one of the 3 is kept
for the owners' posts until they have used one that day), one round per room per tick,
at most 4 rounds per tick. Output order: (priority, bust before loss_cluster, oldest
evidence).

Crash safety (the caller's side of the contract; ``begin_round`` / ``finish_round``
implement it): the round row stores ``trigger_data`` = ``Due.data`` (JSON) when
it starts. ``Due.data["cursors"]`` holds the evidence high-water marks; they are
written to ``cursors`` only when the round ends as ``done`` or ``no_action``.
Until then the same evidence is found again, so a crash never loses a trigger:

- a ``running`` round younger than 2h blocks the same trigger in the same room
  (it may still be working; the rooms tick, which holds the tick lock, first marks every
  'running' round it finds as failed, since no live pass can own one then);
- a ``running`` round older than 2h, or a ``failed`` round, counts as a failed
  attempt: the trigger fires again once (``data["retry_of"]``); after two failed
  attempts for the same evidence it waits for new evidence;
- a ``stopped_budget`` round pauses what its stop says (``decision.stopped``): a class
  cap its own class, the total / weekly cap every class, the reserve for incidents and
  scheduled meetings the other classes, until the next KST day (the budgets reset); a
  Claude plan usage limit pauses everything for ``usage_backoff_ms`` (1h from when the round
  stopped), because the plan's window resets within hours, not at midnight. A loss_cluster or
  non-critical incident round stopped at its reduced cap (``budget_subcap``) pauses nothing: the
  reserve for busts / liquidations stays usable. A stopped round does not count
  against the room's daily cap;
- a ``failed`` round marked ``transient`` (the runner never answered: outage, CLI error)
  is not a failed attempt: the same evidence fires again. Nothing is due for
  ``transient_backoff_ms`` after it (from when it failed), doubling with each transient failure
  in a row (at most ``transient_backoff_max_ms``), so a long outage does not fill a room with notices;
- a round that ended ``done`` / ``no_action`` is never repeated for the same
  evidence key, even if its cursors were not written.

Evidence keys carry times (a trade's exit time, an alert's time, the run start), and
``reconcile_paper_cursors`` pulls the cursors back when paper3.db was replaced (restore from
a backup, new run): ids restart then, and new evidence must never look like handled evidence.

``find_due`` never writes anything. All texts for the owners (``summary_ko``)
are Korean and written by code from the numbers.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Union

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
CLASSES = ("incident", "owner", "loss", "scheduled", "weekly")
# What a stopped_budget round pauses until the next KST day, by decision.stopped (when the
# decision has no explicit 'blocks' list). None = only the round's own class.
STOP_BLOCKS = {"budget_class": None, "budget_total": CLASSES, "budget_week": CLASSES,
               "budget_reserve": ("owner", "loss", "weekly"),
               "budget_subcap": ()}      # a reduced cap (class minus the bust / critical reserve): nothing

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
    owner_reserved_per_room_day: int = 1     # slots of the daily cap only an owner post may use
    max_rounds_per_tick: int = 4
    max_per_room_per_tick: int = 1
    # crash safety
    stale_ms: int = 2 * HOUR_MS          # a 'running' round older than this has failed
    max_attempts: int = 2                # first try + one retry for the same evidence
    usage_backoff_ms: int = HOUR_MS      # after a Claude plan usage limit, nothing is due for this long
    transient_backoff_ms: int = 10 * MIN_MS      # after a transient failure (runner down): wait, doubling
    transient_backoff_max_ms: int = 4 * HOUR_MS  # per failure in a row, up to this
    transient_same_key: int = 3          # this many in a row for ONE meeting: it waits alone (not an outage)
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
    owner_batch: int = 10                    # owner posts one owner meeting answers (oldest first)
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
    except sqlite3.DatabaseError:        # missing table, or not a database file (bad restore)
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
        for rid, room, trig, tdata, started, ended, status, calls, decision in _rows(
                conn, "SELECT round_id, room_id, trigger, trigger_data, started_ts, ended_ts, status, calls, decision "
                      "FROM rounds WHERE started_ts >= ? OR status = 'running' ORDER BY round_id",
                (now_ms - p.rounds_lookback_ms,)):
            d, dec = _json(tdata), _json(decision)
            blocks = dec.get("blocks")
            self.rounds.append({"round_id": rid, "room_id": room, "trigger": trig, "key": d.get("key"),
                                "class": d.get("class") or TRIGGER_CLASS.get(trig),
                                "started_ts": _int(started), "ended_ts": _int(ended, _int(started)),
                                "status": status, "calls": _int(calls),
                                "stopped": dec.get("stopped"), "transient": dec.get("transient") is True,
                                "calls_ok": _int(dec.get("calls_ok"), _int(calls)),
                                "blocks": tuple(blocks) if isinstance(blocks, list) else None})
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
        """Rounds that tried this evidence and failed. A 'transient' failure (the runner never
        answered: outage, CLI error) is not an attempt: the evidence fires again next tick."""
        return [r for r in self.same_key(room, trigger, key)
                if (r["status"] == "failed" and not r["transient"]) or self.stale(r)]

    def settled(self, room: str, trigger: str, key: str) -> bool:
        """Nothing more will happen for this evidence (met, given up, or deferred by the budget)."""
        rs = self.same_key(room, trigger, key)
        return (any(r["status"] in ENDED_OK + ("stopped_budget",) for r in rs)
                or len(self.failed_attempts(room, trigger, key)) >= self.p.max_attempts)

    def last_ok_start(self, room: str, trigger: str) -> Optional[int]:
        ts = [r["started_ts"] for r in self.rounds if r["room_id"] == room and r["trigger"] == trigger
              and (r["status"] in ENDED_OK or (r["status"] == "running" and not self.stale(r)))]
        return max(ts) if ts else None

    def blocks(self, r: dict) -> tuple:
        """Classes a stopped_budget round pauses for the rest of its KST day."""
        if r["blocks"] is not None:
            return r["blocks"]
        got = STOP_BLOCKS.get(r["stopped"] or "budget_class", None)
        if r["stopped"] == "usage_limit":
            return ()                      # handled by usage_paused (hours, not the whole day)
        return (r["class"],) if got is None else got

    def class_blocked(self, cls: str) -> bool:
        return any(r["status"] == "stopped_budget" and r["started_ts"] >= self.day_start
                   and cls in self.blocks(r) for r in self.rounds)

    def usage_paused(self) -> bool:
        """A round hit the Claude plan's usage limit less than ``usage_backoff_ms`` ago (measured from
        when it stopped, not from when it started)."""
        return any(r["status"] == "stopped_budget" and r["stopped"] == "usage_limit"
                   and self.now - r["ended_ts"] < self.p.usage_backoff_ms for r in self.rounds)

    def _backoff(self, k: int) -> int:
        return min(self.p.transient_backoff_max_ms, self.p.transient_backoff_ms * 2 ** min(max(k, 1) - 1, 20))

    def transient_run(self, room: str, trigger: str, key: str) -> list[dict]:
        """This evidence's latest rounds, newest first, while they are transient failures."""
        out = []
        for r in reversed(self.same_key(room, trigger, key)):
            if r["status"] == "failed" and r["transient"]:
                out.append(r)
            elif r["status"] != "running":
                break
        return out

    def key_waiting(self, room: str, trigger: str, key: str) -> bool:
        """This meeting failed 'transiently' ``transient_same_key`` times in a row (its first speaker's
        model is refused, its packet always times out) while the others may be fine: it waits on its
        own, with the same growing pause, instead of pausing every room."""
        run = self.transient_run(room, trigger, key)
        if len(run) < self.p.transient_same_key:
            return False
        return self.now - run[0]["ended_ts"] < self._backoff(len(run))

    def transient_paused(self) -> bool:
        """The latest finished rounds failed because the runner never answered: back off. Not when
        they are all the same meeting failing ``transient_same_key`` times or more (``key_waiting``)."""
        k, last, keys = 0, None, set()
        for r in reversed(self.rounds):
            if r["status"] == "running":
                continue
            if not (r["status"] == "failed" and r["transient"]):
                break
            k += 1
            keys.add((r["room_id"], r["trigger"], r["key"]))
            last = r["ended_ts"] if last is None else last      # the pause runs from when it failed
        if not k:
            return False
        if len(keys) == 1 and len(self.transient_run(*next(iter(keys)))) >= self.p.transient_same_key:
            return False            # one meeting keeps failing by itself: it waits alone (key_waiting)
        pause = self._backoff(k)
        return self.now - last < pause

    def _counted(self, r: dict) -> bool:
        """Does this round use one of its room's daily slots? Budget/usage stops and transient
        failures without any answered call do not (the same evidence runs again later)."""
        if r["status"] == "stopped_budget":
            return False
        return not (r["transient"] and r["calls_ok"] == 0)

    def rounds_today(self, room: str, trigger: Optional[str] = None) -> int:
        return sum(1 for r in self.rounds if r["room_id"] == room and r["started_ts"] >= self.day_start
                   and r["trigger"] not in self.p.cap_exempt and (trigger is None or r["trigger"] == trigger)
                   and self._counted(r))

    def room_full(self, room: str, trigger: str, extra: int = 0) -> bool:
        """The room's daily cap. Until an owner round has run today, ``owner_reserved_per_room_day``
        slots are kept for the owners' posts (other triggers stop earlier)."""
        if trigger in self.p.cap_exempt:
            return False
        cap = self.p.max_rounds_per_room_day
        if trigger != "owner":
            cap -= max(0, self.p.owner_reserved_per_room_day - self.rounds_today(room, "owner"))
        return self.rounds_today(room) + extra >= cap


# ---------------------------------------------------------------- paper3.db helpers
def run_start(paper_ro: Optional[sqlite3.Connection], strict: bool = False) -> Optional[int]:
    """When the paper run started: the creation time of its original accounts (the state
    'run' row is rewritten at every restart), else the first ``runs`` row, else state 'run'.
    ``strict``: a read error (e.g. 'database is locked') raises LookupError instead of reading as
    'no rows' and falling back to a restart time (the cursor reconciliation would take that for a
    new run and reset every trigger cursor); only a missing table reads as empty."""
    one = _q1_tables if strict else _one
    r = one(paper_ro, "SELECT MIN(created_ts) FROM accounts WHERE kind IN ('strategy', 'random')")
    if r and r[0] is not None:
        return int(r[0])
    r = one(paper_ro, "SELECT MIN(started_ts) FROM runs")
    if r and r[0] is not None:
        return int(r[0])
    r = one(paper_ro, "SELECT ts FROM state WHERE k = 'run'")
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
    top = _one(paper_ro, "SELECT MAX(rowid) FROM alerts")       # read BEFORE the scan (no row is skipped)
    hwm_a = max(cur_a, _int(top[0]) if top else 0)
    since = st.now - p.incident_lookback_ms if cur_a == 0 else 0
    levels = sorted({lvl for _k, lvl, _f in p.incident_alerts})
    # only the levels an incident can have: the INFO rows (every exit of 195 accounts) are never read
    for rowid, ts, level, text in _rows(paper_ro, "SELECT rowid, ts, level, text FROM alerts WHERE rowid > ? "
                                                  f"AND level IN ({','.join('?' * len(levels))}) ORDER BY rowid",
                                        (cur_a, *levels)):
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
    # the newest item's time is part of the key: after paper3.db is restored alert rowids restart
    key = f"incident:a{max(a_ids) if a_ids else cur_a}@{max(it['ts'] for it in items)}:d{max(d_ids) if d_ids else '-'}"
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
        # one meeting answers the oldest posts it can show the staff (the packet holds the last 10, the
        # room shows at most 50 copied posts); the rest open the next owner meeting of that room
        batch = max(1, st.p.owner_batch)
        # a batch given up after max_attempts failed meetings stays given up (like any evidence), but the
        # posts after it are new evidence: they get their own meeting instead of waiting behind it forever
        # (the batch's key never changes while it has a full batch in front of the newer posts)
        while len(msgs) > batch:
            head = msgs[batch - 1]
            if len(st.failed_attempts(room, "owner", f"owner:{room}:{head['id']}@{head['ts']}")) < st.p.max_attempts:
                break
            msgs = msgs[batch:]
        msgs = msgs[:batch]
        last = msgs[-1]["id"]
        cursors = {**(_strategy_cursors(st, room, hwm) if room.startswith("strat:") else {}),
                   f"owner:{room}": str(last)}
        # the post's time is part of the key: after inbox.db is replaced ids restart, and a new post
        # with an old id must not look like evidence that was already handled
        out.append(_due(st, room, "owner", f"owner:{room}:{last}@{msgs[-1]['ts']}", msgs[0]["ts"], cursors,
                        f"두 분이 남긴 새 메시지 {len(msgs)}건", message_ids=[m["id"] for m in msgs],
                        messages=msgs[-10:]))
    return out


def _strategy_trades(paper_ro, since_id: int, losses_only: bool, since_ms: int = 0,
                     upto_id: Optional[int] = None) -> list[tuple]:
    q = ("SELECT t.id, t.account_id, t.exit_time, t.pnl, t.data, a.strategy, a.timeframe FROM trades t "
         "JOIN accounts a ON a.account_id = t.account_id WHERE a.kind = 'strategy' AND t.id > ? "
         "AND t.exit_time >= ?")
    args: tuple = (since_id, since_ms)
    if upto_id is not None:
        q += " AND t.id <= ?"
        args += (int(upto_id),)
    if losses_only:
        q += " AND t.pnl < 0"
    return _rows(paper_ro, q + " ORDER BY t.id", args)


def _loss_cluster(paper_ro, st: _Rooms) -> list[Due]:
    from ..cards import card, tag_stats
    p = st.p
    cur = {s: st.cursor_int(f"loss:{strat_room(s)}") for s in STRATEGIES}
    # the high-water mark is read BEFORE the scan and bounds it: a loss the live runner commits in
    # between is neither in this cluster nor behind the cursor this meeting writes (it counts next time)
    hwm = _trade_hwm(paper_ro)
    rows = _strategy_trades(paper_ro, min(cur.values(), default=0), True, st.now - p.loss_lookback_ms, upto_id=hwm)
    by_s: dict[str, list] = {}
    for r in rows:
        if r[5] in cur and r[0] > cur[r[5]]:
            by_s.setdefault(r[5], []).append(r)
    if not by_s:
        return []
    rt = _round_trip(paper_ro)
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
        # trade id AND its exit time: after paper3.db is restored ids restart, and new trades with old
        # ids must not look like evidence that was already handled
        out.append(_due(st, room, "loss_cluster", f"loss:{s}:{lst[-1][0]}@{lst[-1][2]}", min(r[2] for r in lst), cursors,
                        text, strategy=s, losses=len(lst), trade_ids=[r[0] for r in lst][-p.max_items:],
                        by_timeframe=tfs, exit_reasons=reasons, top_tags=top,
                        touched_first_lock=sum(bool(c.get("touched_first_lock")) for c in cards),
                        oldest_exit=min(r[2] for r in lst), newest_exit=max(r[2] for r in lst)))
    return out


def busts_of(paper_ro) -> dict[str, int]:
    """{account_id: bust time} of the accounts paper3.db shows as bust. Evidence time: the first BUST
    alert; for a bust only seen in the saved state (whose row time changes at every save), the
    account's last closed trade (the one that emptied it)."""
    busts: dict[str, int] = {}
    for ts, text in _rows(paper_ro, "SELECT ts, text FROM alerts WHERE level = 'WARN' AND text LIKE '[%] BUST:%'"):
        aid = text[1:text.find("]")]
        busts[aid] = min(int(ts), busts.get(aid, int(ts)))
    r = _one(paper_ro, "SELECT ts, data FROM state WHERE k = 'accounts'")
    if r is not None:
        for aid, e in (_json(r[1]).get("engines") or {}).items():
            if isinstance(e, dict) and e.get("bust") and aid not in busts:
                last = _one(paper_ro, "SELECT MAX(exit_time) FROM trades WHERE account_id = ?", (aid,))
                busts[aid] = int(last[0]) if last and last[0] is not None else int(r[0])
    return busts


def _bust(paper_ro, st: _Rooms) -> list[Due]:
    accts = {aid: (s, tf) for aid, s, tf in _rows(paper_ro, "SELECT account_id, strategy, timeframe FROM accounts "
                                                             "WHERE kind = 'strategy'")}
    busts = busts_of(paper_ro)
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
        # the bust times are part of the key: after paper3.db is restored an account can go bust again,
        # and that new bust must not look like evidence that was already handled
        out.append(_due(st, room, "bust", "bust:" + ",".join(f"{a}@{got[a]}" for a in aids), min(got.values()), cursors,
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
    return [_due(st, "team:lead", "checkpoint", f"checkpoint:{start}:{cp}", start + cp * DAY_MS,
                 {"checkpoint:day": str(cp)}, f"{cp}일 점검: 시작 후 {days}일째",
                 day=cp, days_elapsed=int(days), run_start=start)]


def weekly_slot(now_ms: int, index: int) -> int:
    """00:00 KST of the latest weekly-review day of the strategy with this index (index mod 7 =
    KST weekday, Monday = 0), today included."""
    return kst_day_start(now_ms) - ((kst_weekday(now_ms) - index % 7) % 7) * DAY_MS


def _weekly(paper_ro, st: _Rooms) -> list[Due]:
    """A strategy's weekly review is due on its weekday when it has >= weekly_min_trades closed trades
    since its last review. The evidence key is that weekday's date: a review that could not run on
    its day (AI budget used up, or stopped midway) stays due on the following days, until a round
    for that slot ends done / no_action; the next weekday opens a new slot. A strategy that only
    reaches the trade count after its day waits for its next weekday (reviews stay spread out)."""
    hwm = _trade_hwm(paper_ro)
    out = []
    for i, s in enumerate(STRATEGIES):
        room = strat_room(s)
        slot = weekly_slot(st.now, i)
        slot_day = kst_date(slot)
        key = f"weekly:{s}:{slot_day}"
        if st.handled(room, "weekly", key):
            continue
        cur = st.cursor_int(f"weekly:{room}")
        # trades closed by the end of the slot day decide whether the slot was due at all
        r = _one(paper_ro, "SELECT COUNT(*), MIN(t.exit_time) FROM trades t JOIN accounts a "
                           "ON a.account_id = t.account_id WHERE a.kind = 'strategy' AND a.strategy = ? "
                           "AND t.id > ? AND t.exit_time < ?", (s, cur, slot + DAY_MS))
        n_slot = 0 if r is None else int(r[0])
        if n_slot < st.p.weekly_min_trades:
            continue
        n = _one(paper_ro, "SELECT COUNT(*) FROM trades t JOIN accounts a ON a.account_id = t.account_id "
                           "WHERE a.kind = 'strategy' AND a.strategy = ? AND t.id > ?", (s, cur))
        n = n_slot if n is None else int(n[0])
        cursors = {**_strategy_cursors(st, room, hwm), f"weekly:{room}": str(hwm)}
        late = "" if slot_day == kst_date(st.now) else f" ({slot_day} 검토를 미뤘던 것)"
        out.append(_due(st, room, "weekly", key, slot, cursors,
                        f"{STRATEGY_KO[s]} 주간 검토: 지난 검토 뒤 거래 {n}건{late}", strategy=s, trades=n,
                        slot_day=slot_day))
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
             policy: Optional[TriggerPolicy] = None, *, defer_classes: Iterable[str] = (),
             defer_triggers: Iterable[str] = (), skip_rooms: Iterable[str] = (),
             can_start: Optional[Callable[[Due], bool]] = None) -> list[Due]:
    """Rounds to run now, sorted by (priority, bust before loss_cluster, oldest evidence). Reads only.
    ``defer_classes`` / ``defer_triggers``: what the caller cannot start now (its AI budget is used
    up or paced), left out before the per-tick pick so it never hides other meetings;
    ``can_start``: the caller's exact check of one meeting (e.g. its AI budget can carry that
    meeting's shortest form); meetings it refuses are left out BEFORE the per-tick cut, so meetings
    that cannot start never take the slots of ones that can;
    ``skip_rooms``: rooms that already met in the caller's current tick."""
    p = policy or TriggerPolicy()
    st = _Rooms(agents_conn, now_ms, p)
    if st.usage_paused() or st.transient_paused():
        return []
    defer, skip = set(defer_classes), set(skip_rooms)
    defer_t = set(defer_triggers)
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
        if d.data["class"] in defer or d.trigger in defer_t or d.room_id in skip:
            continue
        if st.class_blocked(d.data["class"]) or st.running_fresh(d.room_id, d.trigger):
            continue
        if st.handled(d.room_id, d.trigger, key):
            continue
        failed = st.failed_attempts(d.room_id, d.trigger, key)
        if len(failed) >= p.max_attempts:
            continue
        if st.key_waiting(d.room_id, d.trigger, key):
            continue            # this meeting keeps failing by itself: it waits its own pause
        if can_start is not None and not can_start(d):
            continue            # e.g. its AI budget cannot carry it now: found again on a later tick
        if failed:
            d.data["retry_of"] = failed[-1]["round_id"]
            d.data["summary_ko"] = "(중단된 회의 다시 시작) " + d.data["summary_ko"]
        ok.append(d)
    # within a priority a bust (an account at zero) goes before routine loss clusters
    ok.sort(key=lambda d: (d.priority, 0 if d.trigger == "bust" else 1, d.data["evidence_ts"],
                           d.data.get("seq", 0), d.room_id))

    picked: list[Due] = []
    per_room: dict[str, int] = {}
    for d in ok:
        if len(picked) >= p.max_rounds_per_tick:
            break
        room = d.room_id
        if per_room.get(room, 0) >= p.max_per_room_per_tick:
            continue
        if st.room_full(room, d.trigger, per_room.get(room, 0)):
            continue
        after = d.data.get("after")
        if after and not (st.settled(after["room_id"], d.trigger, after["key"])
                          or st.room_full(after["room_id"], d.trigger)
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
                        policy: Optional[TriggerPolicy] = None, *, stale_ms: Optional[int] = None,
                        detail: str = "회의 도중 멈춤 (2시간 넘게 진행 중)") -> list[int]:
    """Mark 'running' rounds older than ``policy.stale_ms`` (or ``stale_ms``) as 'failed' (a tick died
    during them), so the dashboard stops showing them as live; each counts as one failed attempt (the
    evidence is tried once more). The rooms tick calls it with ``stale_ms=0`` once it holds the tick
    lock: no other pass can own a 'running' round then."""
    p = policy or TriggerPolicy()
    age = p.stale_ms if stale_ms is None else int(stale_ms)
    ids = [int(r[0]) for r in _rows(agents_conn, "SELECT round_id FROM rounds WHERE status = 'running' "
                                                 "AND started_ts <= ?", (now_ms - age,))]
    why = json.dumps({"reason": "stale", "detail": detail}, ensure_ascii=False)
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


# ---------------------------------------------------------------- paper3.db replaced (restore, new run)
PAPER_FP = "paper:fingerprint"
TRADE_CURSOR_PREFIXES = ("loss:", "weekly:")
ALERT_CURSOR = "incident:alert_rowid"


def _q1(paper_ro: sqlite3.Connection, sql: str, args: Iterable = ()) -> Optional[tuple]:
    """One row; raises LookupError when paper3.db cannot be read (never mistaken for 'empty')."""
    try:
        r = paper_ro.execute(sql, tuple(args)).fetchone()
    except sqlite3.DatabaseError as exc:
        raise LookupError(str(exc)) from None
    return tuple(r) if r else None


def _q1_tables(paper_ro: Optional[sqlite3.Connection], sql: str, args: Iterable = ()) -> Optional[tuple]:
    """``_q1`` where a missing table (an older or brand-new paper3.db) reads as no row."""
    if paper_ro is None:
        return None
    try:
        return _q1(paper_ro, sql, args)
    except LookupError as exc:
        if "no such table" in str(exc):
            return None
        raise


def _paper_cursors(agents_conn: sqlite3.Connection) -> dict[str, str]:
    return {k: v for k, v in _rows(agents_conn, "SELECT k, v FROM cursors WHERE k LIKE 'loss:%' OR k LIKE 'weekly:%' "
                                                "OR k LIKE 'bust:%' OR k IN (?, 'checkpoint:day')", (ALERT_CURSOR,))}


def paper_fingerprint(paper_ro: Optional[sqlite3.Connection], agents_conn: sqlite3.Connection) -> Optional[dict]:
    """What the trigger cursors stand on in paper3.db: the run start, the newest trade [id, exit_time]
    and alert [rowid, ts], and the time of the row each trade / alert cursor points at ("at").
    None when paper3.db is missing or cannot be read."""
    if paper_ro is None:
        return None
    try:
        t = _q1(paper_ro, "SELECT id, exit_time FROM trades ORDER BY id DESC LIMIT 1")
        a = _q1(paper_ro, "SELECT rowid, ts FROM alerts ORDER BY rowid DESC LIMIT 1")
        at: dict[str, int] = {}
        for k, v in _paper_cursors(agents_conn).items():
            n = _int(v)
            if n <= 0:
                continue
            if k.startswith(TRADE_CURSOR_PREFIXES):
                r = _q1(paper_ro, "SELECT exit_time FROM trades WHERE id = ?", (n,))
            elif k == ALERT_CURSOR:
                r = _q1(paper_ro, "SELECT ts FROM alerts WHERE rowid = ?", (n,))
            else:
                continue
            if r is not None and r[0] is not None:
                at[k] = int(r[0])
        run = run_start(paper_ro, strict=True)
    except LookupError:
        return None
    return {"run": run, "t": [_int(t[0]), _int(t[1])] if t else [0, 0],
            "a": [_int(a[0]), _int(a[1])] if a else [0, 0], "at": at}


def reconcile_paper_cursors(agents_conn: sqlite3.Connection, paper_ro: Optional[sqlite3.Connection]) -> dict:
    """paper3.db replaced by an older copy (restore from backup) or by a new run: its trade ids and
    alert rowids restart, so new losses, busts and incidents could carry ids the cursors already
    count as seen, and no meeting would open. Detected when the newest trade / alert seen last tick
    (``PAPER_FP``) is gone or has another time, the run start changed, or the highest id is below a
    cursor. Then (``set_cursor``-style, backwards too):
      - every loss:* / weekly:* cursor moves to the last trade not newer (by exit time) than the one
        it stood on (0 when the run changed): handled trades stay handled, newer ones are read;
      - incident:alert_rowid likewise by alert time;
      - bust:<account> cursors whose bust is no longer in paper3.db are dropped (all of them when
        the run changed), so a new bust opens a meeting; checkpoint:day restarts at 0 for a new run.
    The evidence keys carry times (triggers above), so new evidence never matches a handled key.
    An unreadable paper3.db changes nothing. Returns what changed ({key: new value or None})."""
    if paper_ro is None:
        return {}
    row = _one(agents_conn, "SELECT v FROM cursors WHERE k = ?", (PAPER_FP,))
    fp = _json(row[0]) if row else {}
    try:
        top_t = _int(_q1(paper_ro, "SELECT COALESCE(MAX(id), 0) FROM trades")[0])
        top_a = _int(_q1(paper_ro, "SELECT COALESCE(MAX(rowid), 0) FROM alerts")[0])

        def moved(key: str, sql: str) -> bool:
            old = fp.get(key)
            if not (isinstance(old, list) and len(old) == 2 and _int(old[0]) > 0):
                return False
            r = _q1(paper_ro, sql, (_int(old[0]),))
            return r is None or _int(r[0]) != _int(old[1])
        run = run_start(paper_ro, strict=True)          # unreadable: change nothing (LookupError)
        run_changed = fp.get("run") is not None and run is not None and fp.get("run") != run
        curs = _paper_cursors(agents_conn)
        trade_keys = [k for k in curs if k.startswith(TRADE_CURSOR_PREFIXES)]
        replaced = (run_changed or moved("t", "SELECT exit_time FROM trades WHERE id = ?")
                    or moved("a", "SELECT ts FROM alerts WHERE rowid = ?")
                    or any(_int(curs[k]) > top_t for k in trade_keys) or _int(curs.get(ALERT_CURSOR)) > top_a)
        if not replaced:
            return {}
        at = fp.get("at") if isinstance(fp.get("at"), dict) else {}
        last_t = fp["t"][1] if isinstance(fp.get("t"), list) and len(fp["t"]) == 2 and _int(fp["t"][0]) > 0 else None
        last_a = fp["a"][1] if isinstance(fp.get("a"), list) and len(fp["a"]) == 2 and _int(fp["a"][0]) > 0 else None
        changed: dict[str, Optional[str]] = {}
        for k in trade_keys:
            ref = None if run_changed else at.get(k, last_t)
            if run_changed:
                new = 0
            elif ref is None:              # nothing known about its time: what is there now counts as seen
                new = min(_int(curs[k]), top_t)
            else:
                new = _int(_q1(paper_ro, "SELECT COALESCE(MAX(id), 0) FROM trades WHERE exit_time <= ?",
                               (_int(ref),))[0])
            if str(new) != str(curs[k]):
                changed[k] = str(new)
        if ALERT_CURSOR in curs:
            ref = at.get(ALERT_CURSOR, last_a)
            new = (min(_int(curs[ALERT_CURSOR]), top_a) if ref is None else
                   _int(_q1(paper_ro, "SELECT COALESCE(MAX(rowid), 0) FROM alerts WHERE ts <= ?", (_int(ref),))[0]))
            if str(new) != str(curs[ALERT_CURSOR]):
                changed[ALERT_CURSOR] = str(new)
        still = {} if run_changed else busts_of(paper_ro)
        for k in curs:
            if k.startswith("bust:") and k[len("bust:"):] not in still:
                changed[k] = None
        if run_changed and _int(curs.get("checkpoint:day")) != 0:
            changed["checkpoint:day"] = "0"
    except LookupError:
        return {}
    for k, v in changed.items():
        if v is None:
            agents_conn.execute("DELETE FROM cursors WHERE k = ?", (k,))
        else:
            agents_conn.execute("INSERT INTO cursors (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                                (k, v))
    agents_conn.commit()
    return changed


def store_paper_fingerprint(agents_conn: sqlite3.Connection, paper_ro: Optional[sqlite3.Connection]) -> Optional[dict]:
    """Remember what the cursors stand on now (``paper_fingerprint``), for the next tick's check.
    While paper3.db has no run start yet (a new run's file before its accounts are committed, or a
    crash loop at that point) the run start of the last fingerprint is kept, so the tick that first
    sees the new accounts still finds the run changed (checkpoint:day back to 0)."""
    fp = paper_fingerprint(paper_ro, agents_conn)
    if fp is None:
        return None
    r = _one(agents_conn, "SELECT v FROM cursors WHERE k = ?", (PAPER_FP,))
    if fp.get("run") is None and r is not None:
        fp["run"] = _json(r[0]).get("run")
    text = json.dumps(fp, sort_keys=True)
    if r is None or r[0] != text:
        agents_conn.execute("INSERT INTO cursors (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                            (PAPER_FP, text))
        agents_conn.commit()
    return fp
