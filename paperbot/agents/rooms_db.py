"""Storage for the agent rooms: agents3.db (the agents' own talk) and inbox.db (what the owners type).

Owners' words: the staff discuss, decide and resolve things by themselves; the owners may join in a
room and approve or reject proposals, but nothing waits for them to type.

One writer per database:
- agents3.db  -- written ONLY by the agents tick process (``open_agents``). The dashboard and every
                 other process open it read-only (``open_ro``).
- inbox.db    -- written ONLY by the dashboard (``open_inbox_rw``): owner messages and approvals.
                 The agents tick opens it read-only and remembers what it handled in ``cursors``.

What can change after it is written:
- messages, notes, trials, trial_results, owner_messages, approvals: append-only (SQLite triggers
  refuse UPDATE and DELETE).
- proposals: only ``status``/``decided_ts``/``decided_by`` change, only along the allowed paths
  (awaiting_owner -> approved|rejected, approved -> rejected), and a proposal can never be
  'awaiting_owner' or 'approved' unless its code gate passed (a trigger checks the stored gate JSON,
  so neither the approver agent nor an owner can overturn it). Rows are never deleted.
- rounds and cursors: bookkeeping of the tick, written by triggers.begin_round / triggers.finish_round
  (rounds are never deleted; cursors hold plain text).
- rooms: configuration derived from the roster (``ensure_rooms`` keeps them in sync).

Nothing here calls a model, places an order or runs agent output: it only stores text and JSON.
Times are epoch milliseconds; "today" is the Korea-time (KST) day.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.parse
from datetime import datetime
from typing import Any, Iterable, Optional

from ..ledger import SCHEMA as _LEDGER_SCHEMA
from ..sessions import KST
from .roster3 import ROLES, SPECIALISTS, STRATEGY_KO, TEAMS

# ---------------------------------------------------------------- vocabulary
MESSAGE_KINDS = ("trigger", "analysis", "challenge", "expert", "revision", "code_result", "verdict",
                 "decision", "action", "owner", "summary", "system")
ROUND_STATUSES = ("running", "done", "stopped_budget", "failed", "no_action")
TRIAL_KINDS = ("hypothesis", "test", "copy_proposal")
PROPOSAL_STATUSES = ("blocked_gate", "blocked_cap", "awaiting_owner", "approved", "rejected")
ACTIVE_PROPOSAL_STATUSES = ("awaiting_owner", "approved")   # count against the copy cap
APPROVAL_DECISIONS = ("approve", "reject")
# allowed status changes after a proposal is written (anything else is refused, also by a trigger)
PROPOSAL_FLOW = {"awaiting_owner": ("approved", "rejected"), "approved": ("rejected",)}

MAX_TEXT = 8_000          # a room message longer than this is cut (the full answer stays in ``data``)
MAX_OWNER_TEXT = 1_000    # what the dashboard accepts from an owner in one post

STRATEGY_ROOM_ROLES = ("entry_timing", "exit_timing", "whatif", "devils_advocate", "validator", "approver")
TEAM_ROOMS = ("market", "risk", "ops", "review", "lead")
# Roles from other teams that speak in a team room's meetings (morning: strategist, devils_advocate,
# team_lead in team:market; evening: risk_officer in team:review; incident: code_reviewer, team_lead in
# team:ops; checkpoint: league_referee, rule_keeper in team:lead). Listed after the team's own members.
TEAM_ROOM_GUESTS = {
    "market": ("strategist", "devils_advocate", "team_lead"),
    "risk": (),
    "ops": ("code_reviewer", "team_lead"),
    "review": ("risk_officer",),
    "lead": ("league_referee", "rule_keeper"),
}

ROLE_NAMES = {r[0]: r[1] for r in ROLES + SPECIALISTS}
ROLE_NAMES.update({"code": "코드(자동 계산)", "owner": "두 분", "system": "시스템"})

# ---------------------------------------------------------------- schemas
_m = re.search(r"CREATE TABLE IF NOT EXISTS agent_calls \(.*?\);", _LEDGER_SCHEMA, re.S)
assert _m is not None, "ledger.SCHEMA lost its agent_calls table"
AGENT_CALLS_SQL = _m.group(0)   # the exact definition BudgetedRunner writes to


def _append_only(table: str) -> str:
    return (f"CREATE TRIGGER IF NOT EXISTS {table}_append_only_u BEFORE UPDATE ON {table}\n"
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;\n"
            f"CREATE TRIGGER IF NOT EXISTS {table}_append_only_d BEFORE DELETE ON {table}\n"
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;\n")


def _in(values: Iterable[str]) -> str:
    return "(" + ",".join(f"'{v}'" for v in values) + ")"


_FLOW_SQL = " OR ".join(f"(OLD.status = '{a}' AND NEW.status IN {_in(bs)})" for a, bs in PROPOSAL_FLOW.items())

AGENTS_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS rooms (
    room_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('strategy', 'team')),
    strategy TEXT,
    title TEXT NOT NULL,
    members TEXT NOT NULL DEFAULT '[]',
    created_ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rounds (
    round_id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id TEXT NOT NULL,
    trigger TEXT NOT NULL,
    trigger_data TEXT,
    started_ts INTEGER NOT NULL,
    ended_ts INTEGER,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN {_in(ROUND_STATUSES)}),
    decision TEXT,
    calls INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS rounds_room ON rounds (room_id, started_ts);
CREATE INDEX IF NOT EXISTS rounds_status ON rounds (status);
CREATE TRIGGER IF NOT EXISTS rounds_no_delete BEFORE DELETE ON rounds
BEGIN SELECT RAISE(ABORT, 'rounds are never deleted'); END;
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    room_id TEXT NOT NULL,
    round_id INTEGER,
    meeting TEXT,
    role TEXT NOT NULL,
    speaker_name TEXT,
    kind TEXT NOT NULL CHECK (kind IN {_in(MESSAGE_KINDS)}),
    text TEXT NOT NULL DEFAULT '',
    data TEXT,
    evidence TEXT
);
CREATE INDEX IF NOT EXISTS messages_room ON messages (room_id, id);
{_append_only("messages")}
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    room_id TEXT NOT NULL,
    strategy TEXT,
    text TEXT NOT NULL,
    round_id INTEGER
);
CREATE INDEX IF NOT EXISTS notes_room ON notes (room_id, id);
{_append_only("notes")}
CREATE TABLE IF NOT EXISTS trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    room_id TEXT NOT NULL,
    strategy TEXT,
    kind TEXT NOT NULL CHECK (kind IN {_in(TRIAL_KINDS)}),
    spec TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    round_id INTEGER
);
CREATE INDEX IF NOT EXISTS trials_strategy ON trials (strategy, id);
CREATE INDEX IF NOT EXISTS trials_room ON trials (room_id, id);
CREATE INDEX IF NOT EXISTS trials_hash ON trials (spec_hash);
{_append_only("trials")}
CREATE TABLE IF NOT EXISTS trial_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trial_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    status TEXT NOT NULL,
    result TEXT
);
CREATE INDEX IF NOT EXISTS trial_results_trial ON trial_results (trial_id, id);
{_append_only("trial_results")}
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    room_id TEXT NOT NULL,
    strategy TEXT,
    trial_id INTEGER,
    change TEXT NOT NULL,
    gate TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN {_in(PROPOSAL_STATUSES)}),
    decided_ts INTEGER,
    decided_by TEXT
);
CREATE INDEX IF NOT EXISTS proposals_status ON proposals (status, strategy);
CREATE TRIGGER IF NOT EXISTS proposals_gate_i BEFORE INSERT ON proposals
WHEN NEW.status IN {_in(ACTIVE_PROPOSAL_STATUSES)} AND COALESCE(json_extract(NEW.gate, '$.pass'), 0) != 1
BEGIN SELECT RAISE(ABORT, 'code gate failed: a proposal cannot be awaiting_owner or approved'); END;
CREATE TRIGGER IF NOT EXISTS proposals_fixed_u
BEFORE UPDATE OF ts, room_id, strategy, trial_id, change, gate ON proposals
BEGIN SELECT RAISE(ABORT, 'only the status of a proposal can change'); END;
CREATE TRIGGER IF NOT EXISTS proposals_flow_u BEFORE UPDATE OF status ON proposals
WHEN NEW.status IS NOT OLD.status AND NOT ({_FLOW_SQL})
BEGIN SELECT RAISE(ABORT, 'proposal status change not allowed'); END;
CREATE TRIGGER IF NOT EXISTS proposals_no_delete BEFORE DELETE ON proposals
BEGIN SELECT RAISE(ABORT, 'proposals are never deleted'); END;
CREATE TABLE IF NOT EXISTS cursors (
    k TEXT PRIMARY KEY,
    v TEXT
);
{AGENT_CALLS_SQL}
CREATE INDEX IF NOT EXISTS agent_calls_day ON agent_calls (day);
"""

INBOX_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS owner_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    room_id TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS owner_messages_room ON owner_messages (room_id, id);
CREATE INDEX IF NOT EXISTS owner_messages_author ON owner_messages (author, ts);
{_append_only("owner_messages")}
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    proposal_id INTEGER NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN {_in(APPROVAL_DECISIONS)}),
    author TEXT NOT NULL DEFAULT '',
    note TEXT
);
{_append_only("approvals")}
"""


# ---------------------------------------------------------------- helpers
def _now_ms() -> int:
    return int(time.time() * 1000)


def _json_default(o: Any) -> Any:
    """numpy scalars (np.bool_, np.int64, ...) become plain Python values; sets become lists."""
    item = getattr(o, "item", None)
    if callable(item):
        try:
            return item()
        except (TypeError, ValueError):
            pass
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    return str(o)


def _dumps(x: Any) -> Optional[str]:
    return None if x is None else json.dumps(x, ensure_ascii=False, default=_json_default)


def _loads(s: Optional[str]) -> Any:
    if s is None:
        return None
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return s


def _dicts(cur: sqlite3.Cursor) -> list[dict]:
    """Rows as dicts; works whatever the connection's row_factory is."""
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, tuple(r))) for r in cur.fetchall()]


def _safe(conn: Optional[sqlite3.Connection], fn, empty):
    """Read helpers used by the dashboard: a missing database or table is 'nothing yet'."""
    if conn is None:
        return empty
    try:
        return fn()
    except sqlite3.OperationalError:
        return empty


def kst_day_start_ms(now_ms: int) -> int:
    d = datetime.fromtimestamp(now_ms / 1000, tz=KST).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp() * 1000)


def kst_day(now_ms: int) -> str:
    """Same day key as budget.kst_day (agent_calls.day)."""
    return datetime.fromtimestamp(now_ms / 1000, tz=KST).strftime("%Y-%m-%d")


def spec_hash(spec: Any) -> str:
    """Stable hash of a trial spec (key order and spacing do not matter)."""
    canon = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def role_name(role: str) -> str:
    return ROLE_NAMES.get(role, role)


def strategy_room_id(strategy: str) -> str:
    return f"strat:{strategy}"


def team_room_id(team: str) -> str:
    return f"team:{team}"


def room_strategy(room_id: str) -> Optional[str]:
    return room_id[len("strat:"):] if room_id.startswith("strat:") else None


# ---------------------------------------------------------------- openers
def open_agents(path: str) -> sqlite3.Connection:
    """The agents tick's (only) writer connection to agents3.db. Creates the schema; safe to repeat."""
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(AGENTS_SCHEMA)
    conn.commit()
    return conn


def open_inbox_rw(path: str) -> sqlite3.Connection:
    """The dashboard's (only) writer connection to inbox.db. Creates the schema; safe to repeat."""
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(INBOX_SCHEMA)
    conn.commit()
    return conn


def open_ro(path: Optional[str]) -> Optional[sqlite3.Connection]:
    """Read-only connection (``file:...?mode=ro``), or None when the file does not exist yet.
    Rows come back as ``sqlite3.Row`` (index or name access). Writes raise OperationalError."""
    if not path or not os.path.exists(path):
        return None
    uri = "file:" + urllib.parse.quote(os.path.abspath(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


# ---------------------------------------------------------------- rooms
def room_specs() -> list[dict]:
    """The 41 rooms: 5 team rooms, then one room per strategy (roster order)."""
    team_names = dict(TEAMS)
    out = []
    for t in TEAM_ROOMS:
        own = [r[0] for r in ROLES if r[2] == t]
        members = own + [g for g in TEAM_ROOM_GUESTS.get(t, ()) if g not in own]
        name = team_names[t]                     # "① 시장분석팀" -> "시장분석팀"
        title = name.split(" ", 1)[1] if " " in name else name
        out.append({"room_id": team_room_id(t), "kind": "team", "strategy": None, "title": title,
                    "members": members})
    for s, ko in STRATEGY_KO.items():
        out.append({"room_id": strategy_room_id(s), "kind": "strategy", "strategy": s, "title": ko,
                    "members": [f"spec_{s}", *STRATEGY_ROOM_ROLES]})
    return out


def ensure_rooms(conn: sqlite3.Connection, *, ts: Optional[int] = None) -> int:
    """Create the rooms that are missing and bring titles/members in line with the roster.
    Returns how many rooms were created."""
    ts = _now_ms() if ts is None else ts
    have = {r[0]: (r[1], r[2], r[3], r[4]) for r in conn.execute(
        "SELECT room_id, kind, strategy, title, members FROM rooms")}
    created = 0
    with conn:
        for spec in room_specs():
            row = (spec["kind"], spec["strategy"], spec["title"], _dumps(spec["members"]))
            if spec["room_id"] not in have:
                conn.execute("INSERT INTO rooms (room_id, kind, strategy, title, members, created_ts) "
                             "VALUES (?,?,?,?,?,?)", (spec["room_id"], *row, ts))
                created += 1
            elif tuple(have[spec["room_id"]]) != row:
                conn.execute("UPDATE rooms SET kind = ?, strategy = ?, title = ?, members = ? WHERE room_id = ?",
                             (*row, spec["room_id"]))
    return created


def get_room(conn: Optional[sqlite3.Connection], room_id: str) -> Optional[dict]:
    def q():
        rows = _dicts(conn.execute("SELECT room_id, kind, strategy, title, members, created_ts FROM rooms "
                                   "WHERE room_id = ?", (room_id,)))
        if not rows:
            return None
        rows[0]["members"] = _loads(rows[0]["members"]) or []
        return rows[0]
    return _safe(conn, q, None)


# ---------------------------------------------------------------- messages
def post(conn: sqlite3.Connection, room_id: str, round_id: Optional[int], meeting: Optional[str], role: str,
         speaker_name: Optional[str], kind: str, text: str, data: Any = None, evidence: Any = None,
         *, ts: Optional[int] = None) -> int:
    """Append one message to a room. ``data``/``evidence`` are stored as JSON (never executed).
    An empty ``speaker_name`` is filled from the roster. Returns the message id."""
    if kind not in MESSAGE_KINDS:
        raise ValueError(f"unknown message kind: {kind!r}")
    if not room_id or not role:
        raise ValueError("room_id and role are required")
    text = "" if text is None else str(text)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT - 1] + "…"
    cur = conn.execute(
        "INSERT INTO messages (ts, room_id, round_id, meeting, role, speaker_name, kind, text, data, evidence) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (_now_ms() if ts is None else ts, room_id, round_id, meeting, role, speaker_name or role_name(role),
         kind, text, _dumps(data), _dumps(evidence)))
    conn.commit()
    return int(cur.lastrowid)


def _message_rows(cur: sqlite3.Cursor) -> list[dict]:
    rows = _dicts(cur)
    for r in rows:
        r["data"] = _loads(r.get("data"))
        r["evidence"] = _loads(r.get("evidence"))
    return rows


_MSG_COLS = "id, ts, room_id, round_id, meeting, role, speaker_name, kind, text, data, evidence"


def room_messages(conn_ro: Optional[sqlite3.Connection], room_id: str, after_id: Optional[int] = 0,
                  limit: int = 200, before_id: Optional[int] = None) -> list[dict]:
    """Messages of one room in id order, ``data``/``evidence`` decoded from JSON.
    after_id > 0: the next ``limit`` messages after it (live updates, paging forward).
    otherwise: the latest ``limit`` messages (before ``before_id`` when given, for scrolling back)."""
    limit = min(max(int(limit or 1), 1), 500)

    def q():
        if after_id:
            return _message_rows(conn_ro.execute(
                f"SELECT {_MSG_COLS} FROM messages WHERE room_id = ? AND id > ? ORDER BY id LIMIT ?",
                (room_id, int(after_id), limit)))
        args: list = [room_id]
        extra = ""
        if before_id:
            extra = " AND id < ?"
            args.append(int(before_id))
        rows = _message_rows(conn_ro.execute(
            f"SELECT {_MSG_COLS} FROM messages WHERE room_id = ?{extra} ORDER BY id DESC LIMIT ?",
            (*args, limit)))
        return rows[::-1]
    return _safe(conn_ro, q, [])


def last_message_id(conn_ro: Optional[sqlite3.Connection]) -> int:
    """Highest message id in agents3.db (the dashboard's live stream polls this)."""
    return _safe(conn_ro, lambda: int(conn_ro.execute("SELECT COALESCE(MAX(id), 0) FROM messages").fetchone()[0]), 0)


def rooms_overview(conn_ro: Optional[sqlite3.Connection], now_ms: Optional[int] = None) -> list[dict]:
    """One line per room for the room list: title, members, last message (id for the unread dot),
    rounds started today (KST), proposals awaiting the owners, whether a round is running."""
    now_ms = _now_ms() if now_ms is None else now_ms
    day0 = kst_day_start_ms(now_ms)

    def q():
        rows = _dicts(conn_ro.execute(
            "SELECT r.room_id, r.kind, r.strategy, r.title, r.members, "
            "m.id AS last_id, m.ts AS last_ts, m.kind AS last_kind, m.role AS last_role, "
            "m.speaker_name AS last_speaker, m.text AS last_text "
            "FROM rooms r LEFT JOIN messages m ON m.id = (SELECT MAX(id) FROM messages WHERE room_id = r.room_id) "
            "ORDER BY r.rowid"))
        today = dict(conn_ro.execute("SELECT room_id, COUNT(*) FROM rounds WHERE started_ts >= ? "
                                     "GROUP BY room_id", (day0,)).fetchall())
        running = {r[0] for r in conn_ro.execute("SELECT DISTINCT room_id FROM rounds WHERE status = 'running'")}
        waiting = dict(conn_ro.execute("SELECT room_id, COUNT(*) FROM proposals WHERE status = 'awaiting_owner' "
                                       "GROUP BY room_id").fetchall())
        for r in rows:
            r["members"] = _loads(r["members"]) or []
            r["last_id"] = r["last_id"] or 0
            t = r["last_text"] or ""
            r["last_text"] = t if len(t) <= 140 else t[:139] + "…"
            r["rounds_today"] = int(today.get(r["room_id"], 0))
            r["open_proposals"] = int(waiting.get(r["room_id"], 0))
            r["running"] = r["room_id"] in running
        return rows
    return _safe(conn_ro, q, [])


# ---------------------------------------------------------------- cursors
# ``cursors.v`` is plain text, so code that reads the table directly (triggers.py compares ids with
# int(v) and KST days as text) sees exactly what was written: a str is stored as-is, anything else
# (int, float, bool, dict, list) as JSON. ``get_cursor`` decodes JSON when it can and otherwise returns
# the text, so ints/dicts come back as ints/dicts and "2026-09-30" comes back unchanged.
def _cursor_text(v: Any) -> Optional[str]:
    if v is None or isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False, default=_json_default)


def _cursor_value(text: Optional[str], default: Any = None) -> Any:
    if text is None:
        return default
    v = _loads(text)
    return default if v is None else v


def get_cursor(conn: sqlite3.Connection, k: str, default: Any = None) -> Any:
    r = conn.execute("SELECT v FROM cursors WHERE k = ?", (k,)).fetchone()
    return default if r is None else _cursor_value(r[0], default)


def set_cursor(conn: sqlite3.Connection, k: str, v: Any, *, commit: bool = True) -> None:
    conn.execute("INSERT INTO cursors (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                 (k, _cursor_text(v)))
    if commit:
        conn.commit()


def all_cursors(conn: sqlite3.Connection, prefix: str = "") -> dict:
    esc = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return {k: _cursor_value(v) for k, v in conn.execute(
        "SELECT k, v FROM cursors WHERE k LIKE ? ESCAPE '\\'", (esc + "%",))}


# ---------------------------------------------------------------- rounds (read side)
# A round's life (insert 'running' with the evidence high-water mark in trigger_data, then end it and
# advance cursors forward-only when it ended done/no_action) is written by triggers.begin_round /
# triggers.finish_round, so there is one implementation of that rule. Below: reading rounds back.
def get_round(conn: Optional[sqlite3.Connection], round_id: int) -> Optional[dict]:
    def q():
        rows = _dicts(conn.execute("SELECT * FROM rounds WHERE round_id = ?", (round_id,)))
        if not rows:
            return None
        rows[0]["trigger_data"] = _loads(rows[0]["trigger_data"])
        rows[0]["decision"] = _loads(rows[0]["decision"])
        return rows[0]
    return _safe(conn, q, None)


def rounds_of(conn: Optional[sqlite3.Connection], room_id: Optional[str] = None, trigger: Optional[str] = None,
              since_ms: int = 0, statuses: Optional[Iterable[str]] = None, limit: int = 100) -> list[dict]:
    """Rounds newest first, filtered by room / trigger / start time / status."""
    def q():
        sql, args = "SELECT * FROM rounds WHERE started_ts >= ?", [since_ms]
        if room_id is not None:
            sql += " AND room_id = ?"
            args.append(room_id)
        if trigger is not None:
            sql += " AND trigger = ?"
            args.append(trigger)
        st = list(statuses or ())
        if st:
            sql += f" AND status IN ({','.join('?' * len(st))})"
            args.extend(st)
        rows = _dicts(conn.execute(sql + " ORDER BY round_id DESC LIMIT ?", (*args, max(1, int(limit)))))
        for r in rows:
            r["trigger_data"] = _loads(r["trigger_data"])
            r["decision"] = _loads(r["decision"])
        return rows
    return _safe(conn, q, [])


def rounds_today(conn: Optional[sqlite3.Connection], room_id: str, now_ms: int,
                 exclude_triggers: Iterable[str] = ()) -> int:
    ex = list(exclude_triggers)
    sql = "SELECT COUNT(*) FROM rounds WHERE room_id = ? AND started_ts >= ?"
    if ex:
        sql += f" AND trigger NOT IN ({','.join('?' * len(ex))})"
    return _safe(conn, lambda: int(conn.execute(sql, (room_id, kst_day_start_ms(now_ms), *ex)).fetchone()[0]), 0)


# ---------------------------------------------------------------- notes
def add_note(conn: sqlite3.Connection, room_id: str, strategy: Optional[str], text: str,
             round_id: Optional[int] = None, *, ts: Optional[int] = None) -> int:
    text = str(text or "").strip()
    if not text:
        raise ValueError("empty note")
    cur = conn.execute("INSERT INTO notes (ts, room_id, strategy, text, round_id) VALUES (?,?,?,?,?)",
                       (_now_ms() if ts is None else ts, room_id, strategy, text[:MAX_TEXT], round_id))
    conn.commit()
    return int(cur.lastrowid)


def room_notes(conn_ro: Optional[sqlite3.Connection], room_id: str, limit: int = 50) -> list[dict]:
    """Newest first."""
    return _safe(conn_ro, lambda: _dicts(conn_ro.execute(
        "SELECT id, ts, room_id, strategy, text, round_id FROM notes WHERE room_id = ? ORDER BY id DESC LIMIT ?",
        (room_id, min(max(int(limit), 1), 500)))), [])


# ---------------------------------------------------------------- trials (the hypothesis ledger)
def add_trial(conn: sqlite3.Connection, room_id: str, strategy: Optional[str], kind: str, spec: Any,
              round_id: Optional[int] = None, *, ts: Optional[int] = None) -> int:
    if kind not in TRIAL_KINDS:
        raise ValueError(f"unknown trial kind: {kind!r}")
    cur = conn.execute("INSERT INTO trials (ts, room_id, strategy, kind, spec, spec_hash, round_id) "
                       "VALUES (?,?,?,?,?,?,?)",
                       (_now_ms() if ts is None else ts, room_id, strategy, kind, _dumps(spec), spec_hash(spec),
                        round_id))
    conn.commit()
    return int(cur.lastrowid)


def add_trial_result(conn: sqlite3.Connection, trial_id: int, status: str, result: Any,
                     *, ts: Optional[int] = None) -> int:
    if conn.execute("SELECT 1 FROM trials WHERE id = ?", (trial_id,)).fetchone() is None:
        raise ValueError(f"no trial {trial_id}")
    cur = conn.execute("INSERT INTO trial_results (trial_id, ts, status, result) VALUES (?,?,?,?)",
                       (trial_id, _now_ms() if ts is None else ts, str(status), _dumps(result)))
    conn.commit()
    return int(cur.lastrowid)


def _trial_rows(conn: sqlite3.Connection, where: str, args: tuple, limit: int) -> list[dict]:
    rows = _dicts(conn.execute(
        "SELECT t.id, t.ts, t.room_id, t.strategy, t.kind, t.spec, t.spec_hash, t.round_id, "
        "r.id AS result_id, r.ts AS result_ts, r.status AS result_status, r.result AS result "
        "FROM trials t LEFT JOIN trial_results r ON r.id = "
        "(SELECT MAX(id) FROM trial_results WHERE trial_id = t.id) "
        f"WHERE {where} ORDER BY t.id DESC LIMIT ?", (*args, min(max(int(limit), 1), 2000))))
    for r in rows:
        r["spec"] = _loads(r["spec"])
        rid, rts, rst, res = r.pop("result_id"), r.pop("result_ts"), r.pop("result_status"), r.pop("result")
        r["result"] = None if rid is None else {"id": rid, "ts": rts, "status": rst, "result": _loads(res)}
    return rows


def get_trial(conn: Optional[sqlite3.Connection], trial_id: int) -> Optional[dict]:
    """A trial with its latest result (``result`` is None until code has run it)."""
    def q():
        rows = _trial_rows(conn, "t.id = ?", (trial_id,), 1)
        return rows[0] if rows else None
    return _safe(conn, q, None)


def trial_history(conn: Optional[sqlite3.Connection], strategy: Optional[str] = None,
                  room_id: Optional[str] = None, kinds: Optional[Iterable[str]] = None,
                  limit: int = 50) -> list[dict]:
    """Newest first, each with its latest result."""
    where, args = ["1=1"], []
    if strategy is not None:
        where.append("t.strategy = ?")
        args.append(strategy)
    if room_id is not None:
        where.append("t.room_id = ?")
        args.append(room_id)
    ks = list(kinds or ())
    if ks:
        where.append(f"t.kind IN ({','.join('?' * len(ks))})")
        args.extend(ks)
    return _safe(conn, lambda: _trial_rows(conn, " AND ".join(where), tuple(args), limit), [])


def trial_count(conn: Optional[sqlite3.Connection], room_id: Optional[str] = None, strategy: Optional[str] = None,
                kinds: Iterable[str] = ("test",)) -> int:
    """How many trials of these kinds a room (or strategy) has made -- the Bonferroni divisor."""
    sql, args = "SELECT COUNT(*) FROM trials WHERE 1=1", []
    if room_id is not None:
        sql += " AND room_id = ?"
        args.append(room_id)
    if strategy is not None:
        sql += " AND strategy = ?"
        args.append(strategy)
    ks = list(kinds or ())
    if ks:
        sql += f" AND kind IN ({','.join('?' * len(ks))})"
        args.extend(ks)
    return _safe(conn, lambda: int(conn.execute(sql, args).fetchone()[0]), 0)


def trial_counts(conn_ro: Optional[sqlite3.Connection], strategy: Optional[str] = None) -> dict:
    """{'hypothesis': n, 'test': n, 'copy_proposal': n, 'total': n} for the hypothesis-ledger badge."""
    def q():
        sql, args = "SELECT kind, COUNT(*) FROM trials", ()
        if strategy is not None:
            sql, args = sql + " WHERE strategy = ?", (strategy,)
        got = dict(conn_ro.execute(sql + " GROUP BY kind", args).fetchall())
        out = {k: int(got.get(k, 0)) for k in TRIAL_KINDS}
        out["total"] = sum(out.values())
        return out
    return _safe(conn_ro, q, {**{k: 0 for k in TRIAL_KINDS}, "total": 0})


def find_trial(conn: Optional[sqlite3.Connection], strategy: Optional[str], spec: Any,
               kind: str = "test") -> Optional[dict]:
    """The latest trial of this strategy with the same spec (to avoid testing the same thing twice)."""
    def q():
        rows = _trial_rows(conn, "t.strategy IS ? AND t.kind = ? AND t.spec_hash = ?",
                           (strategy, kind, spec_hash(spec)), 1)
        return rows[0] if rows else None
    return _safe(conn, q, None)


# ---------------------------------------------------------------- proposals
def _gate_passed(gate: Any) -> bool:
    if not isinstance(gate, dict):
        return False
    p = gate.get("pass")
    return (p.item() if callable(getattr(p, "item", None)) else p) is True


def add_proposal(conn: sqlite3.Connection, room_id: str, strategy: Optional[str], trial_id: Optional[int],
                 change: Any, gate: dict, status: str, decided_by: Optional[str] = None,
                 *, ts: Optional[int] = None) -> int:
    """Record a copy proposal. ``gate`` is the code gate JSON copied from the trial result; a proposal
    whose gate did not pass can only be 'blocked_gate' (or 'rejected'/'blocked_cap')."""
    if status not in PROPOSAL_STATUSES:
        raise ValueError(f"unknown proposal status: {status!r}")
    if status in ACTIVE_PROPOSAL_STATUSES and not _gate_passed(gate):
        raise ValueError("code gate did not pass: the proposal can only be blocked_gate")
    if trial_id is not None and conn.execute("SELECT 1 FROM trials WHERE id = ?", (trial_id,)).fetchone() is None:
        raise ValueError(f"no trial {trial_id}")
    ts = _now_ms() if ts is None else ts
    if status == "awaiting_owner":
        decided_by, decided_ts = None, None
    else:
        decided_by = decided_by or ("code" if status.startswith("blocked") else "approver")
        decided_ts = ts
    cur = conn.execute(
        "INSERT INTO proposals (ts, room_id, strategy, trial_id, change, gate, status, decided_ts, decided_by) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, room_id, strategy, trial_id, _dumps(change), _dumps(gate), status, decided_ts, decided_by))
    conn.commit()
    return int(cur.lastrowid)


def set_proposal_status(conn: sqlite3.Connection, proposal_id: int, status: str, decided_by: Optional[str] = None,
                        *, ts: Optional[int] = None) -> bool:
    """Move a proposal along the allowed paths (awaiting_owner -> approved|rejected, approved -> rejected).
    Returns False when it already has that status; raises ValueError for any other change."""
    r = conn.execute("SELECT status FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if r is None:
        raise ValueError(f"no proposal {proposal_id}")
    old = r[0]
    if old == status:
        return False
    if status not in PROPOSAL_FLOW.get(old, ()):
        raise ValueError(f"proposal {proposal_id}: {old} -> {status} is not allowed")
    conn.execute("UPDATE proposals SET status = ?, decided_ts = ?, decided_by = ? WHERE id = ?",
                 (status, _now_ms() if ts is None else ts, decided_by, proposal_id))
    conn.commit()
    return True


def _proposal_rows(cur: sqlite3.Cursor) -> list[dict]:
    rows = _dicts(cur)
    for r in rows:
        r["change"] = _loads(r["change"])
        r["gate"] = _loads(r["gate"])
    return rows


def get_proposal(conn: Optional[sqlite3.Connection], proposal_id: int) -> Optional[dict]:
    def q():
        rows = _proposal_rows(conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)))
        return rows[0] if rows else None
    return _safe(conn, q, None)


def list_proposals(conn_ro: Optional[sqlite3.Connection], status: Optional[str] = None,
                   strategy: Optional[str] = None, room_id: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Newest first."""
    sql, args = "SELECT * FROM proposals WHERE 1=1", []
    for col, v in (("status", status), ("strategy", strategy), ("room_id", room_id)):
        if v is not None:
            sql += f" AND {col} = ?"
            args.append(v)
    return _safe(conn_ro, lambda: _proposal_rows(conn_ro.execute(
        sql + " ORDER BY id DESC LIMIT ?", (*args, min(max(int(limit), 1), 1000)))), [])


def active_proposals(conn: Optional[sqlite3.Connection], strategy: Optional[str] = None) -> int:
    """Proposals holding a copy slot ('awaiting_owner' or 'approved'); per strategy or in total."""
    sql = f"SELECT COUNT(*) FROM proposals WHERE status IN {_in(ACTIVE_PROPOSAL_STATUSES)}"
    args: tuple = ()
    if strategy is not None:
        sql, args = sql + " AND strategy = ?", (strategy,)
    return _safe(conn, lambda: int(conn.execute(sql, args).fetchone()[0]), 0)


# ---------------------------------------------------------------- usage (agent_calls)
def usage_today(conn_ro: Optional[sqlite3.Connection], now_ms: Optional[int] = None) -> dict:
    """Today's (KST) model calls and tokens, in total and per pipeline (= trigger class)."""
    day = kst_day(_now_ms() if now_ms is None else now_ms)

    def q():
        by = {}
        for pipe, calls, failed, tokens in conn_ro.execute(
                "SELECT pipeline, COUNT(*), SUM(ok = 0), COALESCE(SUM(tokens), 0) FROM agent_calls "
                "WHERE day = ? GROUP BY pipeline ORDER BY pipeline", (day,)):
            by[pipe] = {"calls": int(calls), "failed": int(failed or 0), "tokens": int(tokens)}
        return {"day": day, "calls": sum(v["calls"] for v in by.values()),
                "tokens": sum(v["tokens"] for v in by.values()), "by_class": by}
    return _safe(conn_ro, q, {"day": day, "calls": 0, "tokens": 0, "by_class": {}})


# ---------------------------------------------------------------- inbox (written by the dashboard only)
def add_owner_message(conn: sqlite3.Connection, room_id: str, author: str, text: str,
                      *, ts: Optional[int] = None) -> int:
    """Dashboard side: an owner's post in a room. Stored as data; the agents read it as data only."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("empty message")
    if len(text) > MAX_OWNER_TEXT:
        raise ValueError(f"message longer than {MAX_OWNER_TEXT} characters")
    if not room_id:
        raise ValueError("room_id is required")
    cur = conn.execute("INSERT INTO owner_messages (ts, room_id, author, text) VALUES (?,?,?,?)",
                       (_now_ms() if ts is None else ts, room_id, author or "", text))
    conn.commit()
    return int(cur.lastrowid)


def add_approval(conn: sqlite3.Connection, proposal_id: int, decision: str, author: str,
                 note: Optional[str] = None, *, ts: Optional[int] = None) -> int:
    """Dashboard side: an owner's approve/reject of a proposal. The agents tick applies it with
    ``set_proposal_status`` (a code gate failure can never be approved)."""
    if decision not in APPROVAL_DECISIONS:
        raise ValueError(f"decision must be approve or reject, not {decision!r}")
    cur = conn.execute("INSERT INTO approvals (ts, proposal_id, decision, author, note) VALUES (?,?,?,?,?)",
                       (_now_ms() if ts is None else ts, int(proposal_id), decision, author or "",
                        (note or "")[:MAX_OWNER_TEXT] or None))
    conn.commit()
    return int(cur.lastrowid)


def owner_posts_since(conn: Optional[sqlite3.Connection], author: Optional[str], since_ms: int) -> int:
    """For the dashboard's rate limit (posts by this author, or by anyone when author is None)."""
    sql, args = "SELECT COUNT(*) FROM owner_messages WHERE ts >= ?", [since_ms]
    if author is not None:
        sql += " AND author = ?"
        args.append(author)
    return _safe(conn, lambda: int(conn.execute(sql, args).fetchone()[0]), 0)


def pending_inbox(inbox_ro: Optional[sqlite3.Connection], after_id: Optional[int] = 0,
                  room_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    """Owner messages with id > after_id (oldest first), optionally for one room.
    Each: {id, ts, room_id, author, text}. The text is untrusted data."""
    sql, args = "SELECT id, ts, room_id, author, text FROM owner_messages WHERE id > ?", [int(after_id or 0)]
    if room_id is not None:
        sql += " AND room_id = ?"
        args.append(room_id)
    return _safe(inbox_ro, lambda: _dicts(inbox_ro.execute(
        sql + " ORDER BY id LIMIT ?", (*args, min(max(int(limit), 1), 1000)))), [])


def pending_approvals(inbox_ro: Optional[sqlite3.Connection], after_id: Optional[int] = 0,
                      limit: int = 200) -> list[dict]:
    """Owner approve/reject decisions with id > after_id (oldest first):
    {id, ts, proposal_id, decision, author, note}."""
    return _safe(inbox_ro, lambda: _dicts(inbox_ro.execute(
        "SELECT id, ts, proposal_id, decision, author, note FROM approvals WHERE id > ? ORDER BY id LIMIT ?",
        (int(after_id or 0), min(max(int(limit), 1), 1000)))), [])
