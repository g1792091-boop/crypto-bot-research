import json
import sqlite3
from datetime import datetime

import pytest

from paperbot.agents import rooms_db as R
from paperbot.agents.roster3 import STRATEGY_KO
from paperbot.sessions import KST

NOW = int(datetime(2026, 9, 30, 10, 0, tzinfo=KST).timestamp() * 1000)   # 10:00 KST
HOUR = 3_600_000
PASS = {"pass": True, "reasons": []}
FAIL = {"pass": False, "reasons": ["기간 1 p값이 기준보다 큼"]}


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "agents3.db")
    conn = R.open_agents(path)
    R.ensure_rooms(conn, ts=NOW)
    yield path, conn
    conn.close()


@pytest.fixture
def inbox(tmp_path):
    path = str(tmp_path / "inbox.db")
    conn = R.open_inbox_rw(path)
    yield path, conn
    conn.close()


def _round(conn, room, trigger, data, ts, status="running", ended=None):
    """Rounds are written by triggers.begin_round/finish_round; plain SQL here keeps this test standalone."""
    cur = conn.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, ended_ts, status) "
                       "VALUES (?,?,?,?,?,?)", (room, trigger, None if data is None else json.dumps(data), ts,
                                                ended, status))
    conn.commit()
    return cur.lastrowid


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# ---------------------------------------------------------------- schema
def test_schema_creation_is_idempotent_and_keeps_rows(tmp_path):
    path = str(tmp_path / "agents3.db")
    c = R.open_agents(path)
    R.ensure_rooms(c, ts=NOW)
    mid = R.post(c, "team:ops", None, "incident", "ops_auditor", None, "analysis", "첫 메시지", ts=NOW)
    R.set_cursor(c, "k", 7)
    c.close()
    c = R.open_agents(path)            # reopen: schema re-run
    c.executescript(R.AGENTS_SCHEMA)   # and again, explicitly
    assert {"rooms", "rounds", "messages", "notes", "trials", "trial_results", "proposals", "cursors",
            "agent_calls"} <= _tables(c)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 41
    assert c.execute("SELECT text FROM messages WHERE id = ?", (mid,)).fetchone()[0] == "첫 메시지"
    assert R.get_cursor(c, "k") == 7
    c.close()

    ip = str(tmp_path / "inbox.db")
    i = R.open_inbox_rw(ip)
    R.add_owner_message(i, "team:lead", "owner", "안녕하세요", ts=NOW)
    i.close()
    i = R.open_inbox_rw(ip)
    assert {"owner_messages", "approvals"} <= _tables(i)
    assert i.execute("SELECT COUNT(*) FROM owner_messages").fetchone()[0] == 1
    i.close()


def test_agent_calls_is_the_ledger_table_and_budgeted_runner_feeds_usage(db):
    from paperbot.agents.budget import BudgetedRunner
    from paperbot.agents.runner import CallResult
    from paperbot.ledger import SCHEMA
    path, conn = db
    assert R.AGENT_CALLS_SQL in SCHEMA
    conn.executescript(SCHEMA)   # what BudgetedRunner runs on the same file: no clash

    class Fake:
        def call(self, model, system_prompt, instruction, packet):
            return CallResult("{}", {}, {"usage": {"input_tokens": 100, "output_tokens": 20}})

    br = BudgetedRunner(Fake(), path, max_calls=5, pipeline="owner", clock_ms=lambda: NOW)
    br.call("sonnet", "s", "i", {"role": "spec_DOGE"})
    br.call("sonnet", "s", "i", {"role": "devils_advocate"})
    br.close()
    ro = R.open_ro(path)
    u = R.usage_today(ro, NOW)
    assert u["calls"] == 2 and u["tokens"] == 240 and u["by_class"]["owner"]["calls"] == 2
    assert R.usage_today(ro, NOW + 24 * HOUR)["calls"] == 0   # next KST day
    ro.close()


def test_existing_dashboard_feed_query_still_works(db):
    path, conn = db
    R.post(conn, "team:market", 1, "morning", "chart_regime", None, "analysis", "BTC 추세 약함",
           {"headline": "x"}, ["market.btc"], ts=NOW)
    ro = R.open_ro(path)
    rows = ro.execute("SELECT id, ts, meeting, role, kind, text, data FROM messages "
                      "ORDER BY id DESC LIMIT 5").fetchall()
    assert [tuple(r) for r in rows] == [(1, NOW, "morning", "chart_regime", "analysis", "BTC 추세 약함",
                                         '{"headline": "x"}')]
    ro.close()


# ---------------------------------------------------------------- rooms
def test_ensure_rooms_creates_41_rooms_with_the_right_members(db):
    path, conn = db
    rooms = {r[0]: r for r in conn.execute("SELECT room_id, kind, strategy, title, members, created_ts FROM rooms")}
    assert len(rooms) == 41
    assert {k for k in rooms if k.startswith("team:")} == {"team:market", "team:risk", "team:ops", "team:review",
                                                          "team:lead"}
    for s, ko in STRATEGY_KO.items():
        r = R.get_room(conn, f"strat:{s}")
        assert r["kind"] == "strategy" and r["strategy"] == s and r["title"] == ko
        assert r["members"] == [f"spec_{s}", "entry_timing", "exit_timing", "whatif", "devils_advocate",
                                "validator", "approver"]
    for t in ("market", "risk", "ops", "review", "lead"):
        r = R.get_room(conn, f"team:{t}")
        assert r["kind"] == "team" and r["strategy"] is None
        assert r["members"] == list(R.TEAM_ROOM_MEMBERS[t])  # the roles that speak there (rooms.team_plan)
        assert set(r["members"]) <= set(R.ROLE_NAMES)    # every member is a real role
    assert R.get_room(conn, "team:market")["title"] == "시장분석팀"
    assert "team_lead" in R.get_room(conn, "team:lead")["members"]
    assert {"league_referee", "rule_keeper"} <= set(R.get_room(conn, "team:lead")["members"])
    # idempotent, and roster drift is repaired
    assert R.ensure_rooms(conn, ts=NOW + 1) == 0
    conn.execute("UPDATE rooms SET members = '[]' WHERE room_id = 'strat:DOGE'")
    conn.commit()
    assert R.ensure_rooms(conn, ts=NOW + 2) == 0
    assert R.get_room(conn, "strat:DOGE")["members"][0] == "spec_DOGE"
    assert R.get_room(conn, "strat:DOGE")["created_ts"] == NOW
    assert conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 41


def test_room_id_helpers():
    assert R.strategy_room_id("N18_VWMA_MACD") == "strat:N18_VWMA_MACD"
    assert R.room_strategy("strat:N18_VWMA_MACD") == "N18_VWMA_MACD"
    assert R.room_strategy("team:ops") is None
    assert R.role_name("spec_DOGE") == "도지 봇(친구분) 전담" and R.role_name("code") == "코드(자동 계산)"
    assert R.role_name("unknown_role") == "unknown_role"


# ---------------------------------------------------------------- messages
def test_post_validates_kind_and_room_messages_pages(db):
    path, conn = db
    with pytest.raises(ValueError):
        R.post(conn, "team:ops", None, "incident", "ops_auditor", None, "shell", "rm -rf /")
    ids = [R.post(conn, "strat:DOGE", 1, "loss_cluster", "spec_DOGE", "", "analysis", f"m{i}",
                  {"i": i}, [f"losses[{i}]"], ts=NOW + i) for i in range(5)]
    R.post(conn, "team:ops", None, "incident", "ops_auditor", None, "analysis", "다른 방", ts=NOW)
    long_id = R.post(conn, "strat:DOGE", 1, "loss_cluster", "code", None, "code_result", "x" * 20_000, ts=NOW + 9)
    ro = R.open_ro(path)
    last2 = R.room_messages(ro, "strat:DOGE", after_id=0, limit=2)
    assert [m["id"] for m in last2] == [ids[4], long_id]          # latest, oldest first
    nxt = R.room_messages(ro, "strat:DOGE", after_id=ids[1], limit=2)
    assert [m["text"] for m in nxt] == ["m2", "m3"]
    assert nxt[0]["data"] == {"i": 2} and nxt[0]["evidence"] == ["losses[2]"]
    assert nxt[0]["speaker_name"] == "도지 봇(친구분) 전담"
    back = R.room_messages(ro, "strat:DOGE", before_id=ids[2], limit=10)
    assert [m["id"] for m in back] == ids[:2]
    long = R.room_messages(ro, "strat:DOGE", after_id=ids[4])[0]
    assert len(long["text"]) == R.MAX_TEXT and long["text"].endswith("…")
    assert R.last_message_id(ro) == long_id
    ro.close()


def test_rooms_overview(db):
    path, conn = db
    R.post(conn, "strat:DOGE", None, "loss_cluster", "code", None, "trigger", "손절 3건 발생", ts=NOW - HOUR)
    R.post(conn, "strat:DOGE", None, "loss_cluster", "spec_DOGE", None, "analysis", "가" * 300, ts=NOW)
    _round(conn, "strat:DOGE", "loss_cluster", {"hw": 3}, NOW - HOUR, "done", NOW)   # today (KST)
    _round(conn, "strat:DOGE", "weekly", None, NOW - 11 * HOUR, "done", NOW)         # yesterday 23:00 KST
    r3 = _round(conn, "strat:DOGE", "owner", None, NOW - 30 * 60_000)
    t = R.add_trial(conn, "strat:DOGE", "DOGE", "test", {"template": "stop_atr", "k": 2.5}, r3, ts=NOW)
    R.add_proposal(conn, "strat:DOGE", "DOGE", t, {"template": "stop_atr", "k": 2.5}, PASS, "awaiting_owner", ts=NOW)
    ro = R.open_ro(path)
    ov = R.rooms_overview(ro, NOW)
    assert len(ov) == 41 and ov[0]["room_id"] == "team:market"
    d = next(o for o in ov if o["room_id"] == "strat:DOGE")
    assert d["title"] == "도지 봇(친구분)" and d["last_kind"] == "analysis" and d["last_id"] == 2
    assert len(d["last_text"]) == 140 and d["last_text"].endswith("…")
    assert d["rounds_today"] == 2 and d["open_proposals"] == 1 and d["running"] is True
    e = next(o for o in ov if o["room_id"] == "team:lead")
    assert e["last_id"] == 0 and e["last_text"] == "" and e["rounds_today"] == 0 and e["running"] is False
    ro.close()


# ---------------------------------------------------------------- append-only
def test_append_only_tables_refuse_update_and_delete(db, inbox):
    path, conn = db
    R.post(conn, "strat:DOGE", None, "m", "spec_DOGE", None, "analysis", "a", ts=NOW)
    R.add_note(conn, "strat:DOGE", "DOGE", "추세 반대 진입이 손실에 자주 보임 (가설)", ts=NOW)
    tid = R.add_trial(conn, "strat:DOGE", "DOGE", "hypothesis", {"idea": "x"}, ts=NOW)
    R.add_trial_result(conn, tid, "recorded", {"note": "x"}, ts=NOW)
    for table in ("messages", "notes", "trials", "trial_results"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(f"UPDATE {table} SET ts = ts + 1")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(f"DELETE FROM {table}")
        conn.rollback()
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
    rid = _round(conn, "strat:DOGE", "owner", None, NOW)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM rounds WHERE round_id = ?", (rid,))
    conn.rollback()

    ipath, ic = inbox
    R.add_owner_message(ic, "strat:DOGE", "owner", "왜 손절이 많아요?", ts=NOW)
    R.add_approval(ic, 1, "approve", "owner", ts=NOW)
    for table in ("owner_messages", "approvals"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            ic.execute(f"UPDATE {table} SET ts = 0")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            ic.execute(f"DELETE FROM {table}")
        ic.rollback()


# ---------------------------------------------------------------- cursors
def test_cursor_round_trip(db):
    path, conn = db
    assert R.get_cursor(conn, "missing") is None and R.get_cursor(conn, "missing", 0) == 0
    R.set_cursor(conn, "loss:strat:DOGE", 123)
    R.set_cursor(conn, "weekly:strat:DOGE", "2026-09-30")
    R.set_cursor(conn, "inbox:owner", "abc")
    R.set_cursor(conn, "evening", {"day": "2026-09-30", "ids": [1, 2]})
    assert R.get_cursor(conn, "loss:strat:DOGE") == 123
    assert R.get_cursor(conn, "weekly:strat:DOGE") == "2026-09-30"
    assert R.get_cursor(conn, "inbox:owner") == "abc"
    assert R.get_cursor(conn, "evening") == {"day": "2026-09-30", "ids": [1, 2]}
    # stored as plain text, so readers of the raw table (triggers.py: int(v), day text >= day) agree
    raw = dict(conn.execute("SELECT k, v FROM cursors").fetchall())
    assert raw["loss:strat:DOGE"] == "123" and raw["weekly:strat:DOGE"] == "2026-09-30"
    assert raw["inbox:owner"] == "abc"
    conn.execute("INSERT INTO cursors VALUES ('written_raw', '456')")   # e.g. by triggers.advance_cursors
    assert R.get_cursor(conn, "written_raw") == 456
    R.set_cursor(conn, "loss:strat:DOGE", 130)
    assert R.get_cursor(conn, "loss:strat:DOGE") == 130
    assert R.all_cursors(conn, "loss:") == {"loss:strat:DOGE": 130}
    assert R.all_cursors(conn, "loss_") == {}                         # '_' is not a wildcard
    R.set_cursor(conn, "loss:strat:DOGE", None)
    assert R.get_cursor(conn, "loss:strat:DOGE", -1) == -1


def test_round_read_helpers(db):
    path, conn = db
    a = _round(conn, "strat:DOGE", "loss_cluster", {"key": "loss:DOGE:9", "cursors": {"loss:strat:DOGE": "9"}},
               NOW, "done", NOW + 60_000)
    conn.execute("UPDATE rounds SET decision = ?, calls = 3, tokens = 900 WHERE round_id = ?",
                 (json.dumps({"action": "note"}), a))
    conn.commit()
    b = _round(conn, "strat:DOGE", "owner", None, NOW + 1)
    _round(conn, "team:ops", "incident", None, NOW - 20 * HOUR, "failed", NOW)
    r = R.get_round(conn, a)
    assert r["trigger_data"]["cursors"] == {"loss:strat:DOGE": "9"} and r["decision"] == {"action": "note"}
    assert (r["status"], r["calls"], r["tokens"]) == ("done", 3, 900)
    assert R.get_round(conn, 999) is None
    assert R.rounds_today(conn, "strat:DOGE", NOW) == 2
    assert R.rounds_today(conn, "strat:DOGE", NOW, exclude_triggers=["owner"]) == 1
    assert R.rounds_today(conn, "team:ops", NOW) == 0                   # started the previous KST day
    assert [x["round_id"] for x in R.rounds_of(conn, "strat:DOGE")] == [b, a]
    assert [x["round_id"] for x in R.rounds_of(conn, statuses=["running"])] == [b]
    assert [x["round_id"] for x in R.rounds_of(conn, trigger="loss_cluster")] == [a]
    assert R.rounds_of(conn, since_ms=NOW + 2) == []
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO rounds (room_id, trigger, started_ts, status) VALUES ('x', 'y', 1, 'maybe')")
    conn.rollback()


# ---------------------------------------------------------------- trials
def test_trials_ledger(db):
    path, conn = db
    assert R.spec_hash({"template": "stop_atr", "k": 2.5}) == R.spec_hash({"k": 2.5, "template": "stop_atr"})
    assert R.spec_hash({"k": 2.5}) != R.spec_hash({"k": 3.0})
    with pytest.raises(ValueError):
        R.add_trial(conn, "strat:DOGE", "DOGE", "execute", {})
    with pytest.raises(ValueError):
        R.add_trial_result(conn, 999, "done", {})
    h = R.add_trial(conn, "strat:DOGE", "DOGE", "hypothesis", {"idea": "추세 반대 진입 빼기"}, 1, ts=NOW)
    t1 = R.add_trial(conn, "strat:DOGE", "DOGE", "test", {"template": "stop_atr", "k": 2.5}, 1, ts=NOW)
    t2 = R.add_trial(conn, "strat:DOGE", "DOGE", "test", {"template": "lock_start", "first_lock": 0.2}, 2, ts=NOW)
    R.add_trial(conn, "strat:S1_EMA_RSI_CHOP", "S1_EMA_RSI_CHOP", "test", {"template": "stop_atr", "k": 2.5})
    R.add_trial_result(conn, t1, "done", {"gate": FAIL}, ts=NOW + 1)
    R.add_trial_result(conn, t1, "done", {"gate": PASS}, ts=NOW + 2)   # latest wins
    assert R.trial_count(conn, room_id="strat:DOGE") == 2
    assert R.trial_count(conn, strategy="DOGE", kinds=("test", "hypothesis")) == 3
    hist = R.trial_history(conn, strategy="DOGE")
    assert [x["id"] for x in hist] == [t2, t1, h]
    assert hist[0]["result"] is None
    assert hist[1]["result"]["result"] == {"gate": PASS} and hist[1]["spec"]["k"] == 2.5
    assert R.get_trial(conn, t1)["result"]["ts"] == NOW + 2
    assert R.find_trial(conn, "DOGE", {"k": 2.5, "template": "stop_atr"})["id"] == t1
    assert R.find_trial(conn, "DOGE", {"template": "stop_atr", "k": 1.5}) is None
    ro = R.open_ro(path)
    assert R.trial_counts(ro, "DOGE") == {"hypothesis": 1, "test": 2, "copy_proposal": 0, "total": 3}
    assert R.trial_counts(ro)["total"] == 4
    ro.close()


# ---------------------------------------------------------------- proposals
def test_proposal_status_transitions(db):
    path, conn = db
    t = R.add_trial(conn, "strat:DOGE", "DOGE", "test", {"template": "stop_atr", "k": 2.5}, ts=NOW)
    change = {"template": "stop_atr", "k": 2.5}
    # the code gate cannot be overturned: failing gate -> only blocked_gate
    for st in ("awaiting_owner", "approved"):
        with pytest.raises(ValueError):
            R.add_proposal(conn, "strat:DOGE", "DOGE", t, change, FAIL, st)
    with pytest.raises(ValueError):
        R.add_proposal(conn, "strat:DOGE", "DOGE", t, change, PASS, "live")
    with pytest.raises(ValueError):
        R.add_proposal(conn, "strat:DOGE", "DOGE", 999, change, PASS, "awaiting_owner")
    with pytest.raises(sqlite3.IntegrityError, match="code gate"):     # the database refuses it too
        conn.execute("INSERT INTO proposals (ts, room_id, strategy, trial_id, change, gate, status) "
                     "VALUES (1, 'strat:DOGE', 'DOGE', ?, '{}', '{\"pass\": false}', 'approved')", (t,))
    conn.rollback()

    blocked = R.add_proposal(conn, "strat:DOGE", "DOGE", t, change, FAIL, "blocked_gate", ts=NOW)
    assert R.get_proposal(conn, blocked)["decided_by"] == "code"
    for st in ("approved", "awaiting_owner", "rejected"):
        with pytest.raises(ValueError):
            R.set_proposal_status(conn, blocked, st, "owner")

    p = R.add_proposal(conn, "strat:DOGE", "DOGE", t, change, PASS, "awaiting_owner", ts=NOW)
    got = R.get_proposal(conn, p)
    assert got["gate"] == PASS and got["change"] == change and got["decided_ts"] is None
    assert R.active_proposals(conn, "DOGE") == 1 and R.active_proposals(conn) == 1
    assert R.set_proposal_status(conn, p, "approved", "owner:민수", ts=NOW + 5) is True
    assert R.set_proposal_status(conn, p, "approved", "owner:민수") is False          # already there
    got = R.get_proposal(conn, p)
    assert (got["status"], got["decided_by"], got["decided_ts"]) == ("approved", "owner:민수", NOW + 5)
    assert R.set_proposal_status(conn, p, "rejected", "owner:지훈") is True            # owners can still veto
    assert R.active_proposals(conn) == 0
    with pytest.raises(ValueError):
        R.set_proposal_status(conn, p, "approved", "approver")                         # rejected is final
    with pytest.raises(ValueError):
        R.set_proposal_status(conn, 999, "approved", "owner")
    # direct SQL cannot bypass the rules either
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE proposals SET status = 'approved' WHERE id = ?", (blocked,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE proposals SET gate = '{\"pass\": true}' WHERE id = ?", (blocked,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM proposals")
    conn.rollback()

    auto = R.add_proposal(conn, "strat:DOGE", "DOGE", t, change, PASS, "approved", ts=NOW)
    assert R.get_proposal(conn, auto)["decided_by"] == "approver"
    capped = R.add_proposal(conn, "strat:DOGE", "DOGE", t, change, PASS, "blocked_cap", ts=NOW)
    ro = R.open_ro(path)
    assert [x["id"] for x in R.list_proposals(ro, status="blocked_cap")] == [capped]
    assert [x["id"] for x in R.list_proposals(ro, strategy="DOGE")] == [capped, auto, p, blocked]
    ro.close()


# ---------------------------------------------------------------- read-only access
def test_read_only_opener_refuses_writes(db, inbox, tmp_path):
    path, conn = db
    ro = R.open_ro(path)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO cursors VALUES ('x', '1')")
    with pytest.raises(sqlite3.OperationalError):
        R.post(ro, "team:ops", None, "m", "ops_auditor", None, "system", "x")
    with pytest.raises(sqlite3.OperationalError):
        R.set_cursor(ro, "x", 1)
    assert ro.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 41
    ro.close()
    ipath, ic = inbox
    iro = R.open_ro(ipath)
    with pytest.raises(sqlite3.OperationalError):
        R.add_owner_message(iro, "team:ops", "owner", "hi")
    iro.close()
    missing = str(tmp_path / "nope.db")
    assert R.open_ro(missing) is None and R.open_ro(None) is None
    assert not (tmp_path / "nope.db").exists()
    # read helpers treat a missing database or table as empty
    assert R.rooms_overview(None) == [] and R.room_messages(None, "team:ops") == []
    assert R.pending_inbox(None, 0) == [] and R.last_message_id(None) == 0
    assert R.usage_today(None, NOW)["calls"] == 0 and R.trial_counts(None)["total"] == 0
    empty = sqlite3.connect(str(tmp_path / "empty.db"))
    empty.execute("CREATE TABLE other (x)")
    empty.commit()
    empty.close()
    e = R.open_ro(str(tmp_path / "empty.db"))
    assert R.rooms_overview(e, NOW) == [] and R.room_notes(e, "team:ops") == []
    assert R.list_proposals(e) == [] and R.pending_approvals(e) == []
    e.close()


# ---------------------------------------------------------------- inbox
def test_inbox_owner_messages_and_approvals(inbox):
    path, ic = inbox
    with pytest.raises(ValueError):
        R.add_owner_message(ic, "strat:DOGE", "owner", "   ")
    with pytest.raises(ValueError):
        R.add_owner_message(ic, "strat:DOGE", "owner", "가" * (R.MAX_OWNER_TEXT + 1))
    with pytest.raises(ValueError):
        R.add_approval(ic, 1, "maybe", "owner")
    a = R.add_owner_message(ic, "strat:DOGE", "owner", "  손절 폭 넓히면 어때요?  ", ts=NOW - 2 * HOUR)
    b = R.add_owner_message(ic, "team:lead", "owner", "오늘 요약 부탁", ts=NOW - 10 * 60_000)
    c = R.add_owner_message(ic, "strat:DOGE", "friend", "'; DROP TABLE messages; --", ts=NOW)
    R.add_approval(ic, 3, "approve", "owner", "좋아요", ts=NOW)
    R.add_approval(ic, 4, "reject", "owner", ts=NOW)
    ro = R.open_ro(path)
    assert [m["id"] for m in R.pending_inbox(ro, 0)] == [a, b, c]
    assert R.pending_inbox(ro, 0)[0]["text"] == "손절 폭 넓히면 어때요?"
    assert [m["id"] for m in R.pending_inbox(ro, a)] == [b, c]
    assert [m["id"] for m in R.pending_inbox(ro, 0, room_id="strat:DOGE")] == [a, c]
    assert R.pending_inbox(ro, 0)[2]["text"] == "'; DROP TABLE messages; --"   # stored as plain data
    ap = R.pending_approvals(ro, 0)
    assert [(x["proposal_id"], x["decision"], x["note"]) for x in ap] == [(3, "approve", "좋아요"),
                                                                         (4, "reject", None)]
    assert R.pending_approvals(ro, ap[0]["id"])[0]["proposal_id"] == 4
    assert R.owner_posts_since(ro, "owner", NOW - HOUR) == 1
    assert R.owner_posts_since(ro, None, NOW - 3 * HOUR) == 3
    ro.close()


def test_notes_newest_first(db):
    path, conn = db
    with pytest.raises(ValueError):
        R.add_note(conn, "strat:DOGE", "DOGE", "  ")
    R.add_note(conn, "strat:DOGE", "DOGE", "첫 메모", 1, ts=NOW)
    R.add_note(conn, "strat:DOGE", "DOGE", "둘째 메모", 2, ts=NOW + 1)
    R.add_note(conn, "team:ops", None, "다른 방", ts=NOW)
    ro = R.open_ro(path)
    assert [n["text"] for n in R.room_notes(ro, "strat:DOGE")] == ["둘째 메모", "첫 메모"]
    assert R.room_notes(ro, "strat:DOGE", limit=1)[0]["round_id"] == 2
    ro.close()


def test_numpy_values_from_lab_code_are_stored_as_plain_json(db):
    np = pytest.importorskip("numpy")
    path, conn = db
    gate = {"pass": np.bool_(True), "reasons": [], "p1": np.float64(0.01), "n1": np.int64(412)}
    t = R.add_trial(conn, "strat:DOGE", "DOGE", "test", {"template": "stop_atr", "k": np.float64(2.5)}, ts=NOW)
    R.add_trial_result(conn, t, "done", {"gate": gate}, ts=NOW)
    p = R.add_proposal(conn, "strat:DOGE", "DOGE", t, {"template": "stop_atr", "k": 2.5}, gate, "awaiting_owner",
                       ts=NOW)
    got = R.get_proposal(conn, p)
    assert got["gate"] == {"pass": True, "reasons": [], "p1": 0.01, "n1": 412}
    assert R.get_trial(conn, t)["result"]["result"]["gate"]["n1"] == 412
    assert R.find_trial(conn, "DOGE", {"template": "stop_atr", "k": 2.5})["id"] == t
    with pytest.raises(ValueError):
        R.add_proposal(conn, "strat:DOGE", "DOGE", t, {}, {"pass": np.bool_(False)}, "approved")
    R.post(conn, "strat:DOGE", None, "m", "code", None, "code_result", "결과", {"trades": np.int64(301)}, ts=NOW)
    assert R.room_messages(conn, "strat:DOGE")[-1]["data"] == {"trades": 301}


# ---------------------------------------------------------------- restore: a stale -wal next to the copy
def _restored_with_stale_wal(tmp_path, name, opener):
    """A live WAL-mode database, last night's VACUUM INTO backup, more writes (a pass killed with its WAL
    left behind), then the backup copied over the file while the old -wal stays next to it."""
    import os
    import shutil
    path, bk = str(tmp_path / name), str(tmp_path / f"backup-{name}")
    conn = opener(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (x)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(100)])
    conn.commit()
    conn.execute("VACUUM INTO ?", (bk,))
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(3000)])
    conn.commit()
    shutil.copy(path + "-wal", str(tmp_path / "old-wal"))       # what a killed pass leaves behind
    conn.close()
    shutil.copy(bk, path)                                      # the restore, -wal not deleted
    for sfx in ("-wal", "-shm"):
        if os.path.exists(path + sfx):
            os.remove(path + sfx)
    shutil.copy(str(tmp_path / "old-wal"), path + "-wal")
    assert os.path.getsize(path + "-wal") > 0
    return path


@pytest.mark.parametrize("name,opener", [("agents3.db", R.open_agents), ("inbox.db", R.open_inbox_rw)])
def test_a_restored_database_with_an_old_wal_next_to_it_is_not_opened(tmp_path, name, opener):
    import os
    path = _restored_with_stale_wal(tmp_path, name, opener)
    before = open(path, "rb").read()
    with pytest.raises(RuntimeError, match="-wal"):
        opener(path)                                           # SQLite would replay the old WAL onto the copy
    assert R.open_ro(path) is None                             # the tick reads it as missing instead
    assert open(path, "rb").read() == before                   # the restored bytes are untouched
    for sfx in ("-wal", "-shm"):                               # the documented restore: delete them first
        if os.path.exists(path + sfx):
            os.remove(path + sfx)
    conn = opener(path)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 100
    other = opener(path)                                       # a live WAL database with its own -wal: fine
    other.execute("INSERT INTO t VALUES (1)")
    other.commit()
    ro = R.open_ro(path)
    assert ro is not None and ro.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 101
    ro.close()
    other.close()
    conn.close()


def test_an_unopenable_path_reads_as_missing(tmp_path):
    (tmp_path / "paper3.db").mkdir()                           # e.g. a restore gone wrong: a directory
    assert R.open_ro(str(tmp_path / "paper3.db")) is None
