"""Dashboard 'agent rooms': read endpoints on a synthetic agents3.db (opened read-only), owner
writes that go to inbox.db only, login, same-origin check, rate limit, and the code gate."""

import hashlib
import json
import os
import sqlite3
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.agents import rooms_db as R  # noqa: E402
from paperbot.dash.app import Rooms, budget_caps, create_app, hash_password, room_schedule_ko  # noqa: E402
from paperbot.agents.rooms import DEFAULT_WEEK  # noqa: E402

SECRET = b"x" * 32
PW = "correct horse battery"
S = "N17_KC_RSI"
ROOM = f"strat:{S}"


def _agents_db(path: str, now: int) -> dict:
    """What the agents tick would have written: rooms, one finished round in a strategy room, a
    running round in team:ops, a note, a test trial with its result, two proposals, AI usage."""
    c = R.open_agents(path)
    R.ensure_rooms(c, ts=now - 10_000)
    c.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, ended_ts, status, decision, calls, tokens) "
              "VALUES (?,?,?,?,?,?,?,?,?)", (ROOM, "loss_cluster", "{}", now - 9_000, now - 1_000, "done", "{}", 4, 9000))
    c.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, status) VALUES (?,?,?,?,?)",
              ("team:ops", "incident", "{}", now - 500, "running"))
    c.commit()
    ids = [R.post(c, ROOM, 1, "loss_cluster", "code", None, "trigger", "📣 회의 시작: 손실 묶음 복기 (예시)", ts=now - 9_000),
           R.post(c, ROOM, 1, "loss_cluster", f"spec_{S}", None, "analysis", "예시: 손실 4건 중 3건이 추세 반대 진입",
                  {"turn": "specialist"}, ["loss_cards[0].tags"], ts=now - 8_000),
           R.post(c, ROOM, 1, "loss_cluster", "devils_advocate", None, "challenge", "예시: 4건은 너무 적습니다",
                  ts=now - 7_000),
           R.post(c, ROOM, 1, "loss_cluster", "code", None, "decision", "🧾 결정: 메모 남기기 (예시)",
                  {"action": "note"}, ts=now - 1_000),
           R.post(c, "team:ops", 2, "incident", "ops_auditor", None, "analysis", "예시: 데이터 끊김 확인 중", ts=now - 400)]
    R.add_note(c, ROOM, S, "예시 메모: 추세 반대 진입 30건 모이면 다시 보기", 1, ts=now - 1_500)
    tid = R.add_trial(c, ROOM, S, "test", {"template": "stop_atr", "k": 2.5, "strategy": S}, 1, ts=now - 3_000)
    R.add_trial_result(c, tid, "passed", {"gate": {"pass": True, "reasons": ["예시"]}}, ts=now - 2_900)
    ok = R.add_proposal(c, ROOM, S, tid, {"strategy": S, "test": {"template": "stop_atr", "k": 2.5}, "why": "예시"},
                        {"pass": True, "reasons": ["예시: 모든 조건 통과"]}, "awaiting_owner", ts=now - 2_000)
    blocked = R.add_proposal(c, ROOM, S, tid, {"strategy": S, "why": "예시"},
                             {"pass": False, "reasons": ["예시: 2기간 p=0.3"]}, "blocked_gate", ts=now - 1_900)
    day = R.kst_day(now)
    c.executemany("INSERT INTO agent_calls VALUES (?,?,?,?,?,?,?)",
                  [(now - 5_000, day, "loss", "spec", "sonnet", 1, 3000),
                   (now - 4_000, day, "loss", "devils_advocate", "sonnet", 1, 2000),
                   (now - 300, day, "incident", "ops_auditor", "sonnet", 0, 0),
                   (now - 86_400_000 * 3, "2000-01-01", "loss", "x", "sonnet", 1, 999_999)])
    c.commit()
    c.close()
    return {"msg_ids": ids, "trial": tid, "ok_proposal": ok, "blocked_proposal": blocked}


def _digest(path: str) -> str:
    """Content of the whole database (WAL included), not just the main file's bytes."""
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return hashlib.sha256("\n".join(c.iterdump()).encode()).hexdigest()
    finally:
        c.close()


@pytest.fixture
def env(tmp_path):
    now = int(time.time() * 1000)
    agents = str(tmp_path / "agents3.db")
    inbox = str(tmp_path / "inbox.db")
    ids = _agents_db(agents, now)
    app = create_app(str(tmp_path / "paper3.db"), hash_password(PW), SECRET, agents_db=agents, inbox_db=inbox)
    client = TestClient(app)
    return {"client": client, "agents": agents, "inbox": inbox, "now": now, **ids}


def _login(c):
    assert c.post("/api/login", json={"password": PW}).status_code == 200


def _inbox_rows(path: str, table: str) -> list:
    c = sqlite3.connect(path)
    try:
        return c.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    finally:
        c.close()


# ---------------------------------------------------------------- auth
def test_rooms_need_login(env):
    c = env["client"]
    for path in ("/api/rooms", f"/api/rooms/{ROOM}/messages", f"/api/rooms/{ROOM}/notes", "/api/trials",
                 "/api/proposals", "/api/agents/usage"):
        assert c.get(path).status_code == 401, path
    assert c.post(f"/api/rooms/{ROOM}/say", json={"text": "hi"}).status_code == 401
    assert c.post(f"/api/proposals/{env['ok_proposal']}/decide", json={"decision": "approve"}).status_code == 401
    # nothing written without a login (the dashboard's start only creates the empty inbox.db)
    assert _inbox_rows(env["inbox"], "owner_messages") == [] and _inbox_rows(env["inbox"], "approvals") == []


# ---------------------------------------------------------------- reads
def test_overview(env):
    c = env["client"]
    _login(c)
    ov = c.get("/api/rooms").json()
    assert ov["ready"] is True and len(ov["rooms"]) == 42
    by = {r["room_id"]: r for r in ov["rooms"]}
    assert [r["room_id"] for r in ov["rooms"][:5]] == ["team:market", "team:risk", "team:ops", "team:review", "team:lead"]
    r = by[ROOM]
    assert r["title"] == "켈트너·RSI" and r["kind"] == "strategy" and r["strategy"] == S
    assert r["last_id"] == env["msg_ids"][3] and r["last_kind"] == "decision" and "결정" in r["last_text"]
    assert r["rounds_today"] == 1 and r["open_proposals"] == 1 and r["running"] is False
    assert r["members"][0] == f"spec_{S}" and "approver" in r["members"]
    assert "요일 주간 검토" in r["schedule_ko"]
    assert by["team:ops"]["running"] is True
    assert by["team:market"]["last_id"] == 0 and "08:00" in by["team:market"]["schedule_ko"]
    assert ov["max_id"] == max(env["msg_ids"])


def test_messages_paging_and_room_info(env):
    c = env["client"]
    _login(c)
    d = c.get(f"/api/rooms/{ROOM}/messages").json()
    assert [m["id"] for m in d["messages"]] == env["msg_ids"][:4]
    assert d["messages"][1]["kind"] == "analysis" and d["messages"][1]["evidence"] == ["loss_cards[0].tags"]
    assert d["messages"][1]["speaker_name"] == "켈트너·RSI 전담" and d["messages"][1]["data"] == {"turn": "specialist"}
    assert d["pending_owner"] == [] and d["has_more"] is False
    info = d["room"]
    assert [m["name"] for m in info["members_info"]][:2] == ["켈트너·RSI 전담", "진입 타점 분석가"]
    after = c.get(f"/api/rooms/{ROOM}/messages", params={"after_id": env["msg_ids"][1]}).json()
    assert [m["id"] for m in after["messages"]] == env["msg_ids"][2:4] and "room" not in after
    two = c.get(f"/api/rooms/{ROOM}/messages", params={"limit": 2}).json()
    assert [m["id"] for m in two["messages"]] == env["msg_ids"][2:4] and two["has_more"] is True
    older = c.get(f"/api/rooms/{ROOM}/messages", params={"limit": 2, "before_id": env["msg_ids"][2]}).json()
    assert [m["id"] for m in older["messages"]] == env["msg_ids"][:2]
    assert c.get("/api/rooms/strat:NOPE/messages").status_code == 404
    assert c.get("/api/rooms/nope/notes").status_code == 404


def test_notes_trials_proposals_usage(env):
    c = env["client"]
    _login(c)
    notes = c.get(f"/api/rooms/{ROOM}/notes").json()
    assert len(notes) == 1 and notes[0]["text"].startswith("예시 메모")
    t = c.get("/api/trials", params={"strategy": S}).json()
    assert t["counts"]["test"] == 1 and t["counts"]["total"] == 1
    assert t["trials"][0]["id"] == env["trial"] and t["trials"][0]["result"]["status"] == "passed"
    assert c.get("/api/trials", params={"strategy": "S1_EMA_RSI_CHOP"}).json()["counts"]["total"] == 0
    ps = c.get("/api/proposals").json()
    assert {p["id"] for p in ps} == {env["ok_proposal"], env["blocked_proposal"]}
    wait = c.get("/api/proposals", params={"status": "awaiting_owner"}).json()
    assert [p["id"] for p in wait] == [env["ok_proposal"]]
    assert wait[0]["strategy_ko"] == "켈트너·RSI" and wait[0]["gate"]["pass"] is True
    assert wait[0]["owner_decision"] is None and wait[0]["effective_status"] == "awaiting_owner"
    assert c.get("/api/proposals", params={"status": "bogus"}).status_code == 400
    u = c.get("/api/agents/usage").json()
    assert u["calls"] == 3 and u["tokens"] == 5000                     # today only (KST)
    cls = {x["class"]: x for x in u["classes"]}
    assert list(cls)[:5] == ["incident", "owner", "loss", "scheduled", "weekly"]
    assert cls["loss"]["calls"] == 2 and cls["incident"]["failed"] == 1 and cls["owner"]["calls"] == 0
    assert cls["loss"]["name_ko"] == "손실·파산 복기"


# ---------------------------------------------------------------- writes: inbox.db only
def test_say_writes_inbox_only(env):
    c = env["client"]
    _login(c)
    before = _digest(env["agents"])
    r = c.post(f"/api/rooms/{ROOM}/say", json={"text": "  손절을 넓히면 어떨까요?  "})
    assert r.status_code == 200, r.text
    assert r.json()["pending"] is True
    rows = _inbox_rows(env["inbox"], "owner_messages")
    assert len(rows) == 1 and rows[0][2] == ROOM and rows[0][4] == "손절을 넓히면 어떨까요?"
    d = c.get(f"/api/rooms/{ROOM}/messages").json()
    assert [m["text"] for m in d["pending_owner"]] == ["손절을 넓히면 어떨까요?"]
    assert c.get("/api/rooms/team:ops/messages").json()["pending_owner"] == []
    # once the tick has copied it into the room it is no longer pending
    a = R.open_agents(env["agents"])
    R.post(a, ROOM, 3, "owner", "owner", None, "owner", "손절을 넓히면 어떨까요?", {"inbox_id": rows[0][0]},
           ts=rows[0][1])                                      # the tick copies the post with its own time
    a.close()
    assert c.get(f"/api/rooms/{ROOM}/messages").json()["pending_owner"] == []
    before = _digest(env["agents"])
    assert c.post(f"/api/rooms/{ROOM}/say", json={"text": "x" * 1001}).status_code == 400
    assert c.post(f"/api/rooms/{ROOM}/say", json={"text": "   "}).status_code == 400
    assert c.post(f"/api/rooms/{ROOM}/say", json={"text": 5}).status_code == 400
    assert c.post(f"/api/rooms/{ROOM}/say", content=b"text=hi",
                  headers={"content-type": "application/x-www-form-urlencoded"}).status_code == 400
    assert c.post("/api/rooms/strat:NOPE/say", json={"text": "hi"}).status_code == 404
    assert c.post(f"/api/rooms/{ROOM}/say", json={"text": "y" * 1000}).status_code == 200
    assert len(_inbox_rows(env["inbox"], "owner_messages")) == 2
    assert _digest(env["agents"]) == before                            # agents3.db untouched


def test_origin_check(env):
    c = env["client"]
    _login(c)
    say = f"/api/rooms/{ROOM}/say"
    assert c.post(say, json={"text": "a"}, headers={"origin": "https://evil.example"}).status_code == 403
    assert c.post(say, json={"text": "a"}, headers={"origin": "null"}).status_code == 403
    assert c.post(say, json={"text": "a"}, headers={"origin": "http://testserver.evil"}).status_code == 403
    assert c.post(say, json={"text": "a"}, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    dec = f"/api/proposals/{env['ok_proposal']}/decide"
    assert c.post(dec, json={"decision": "approve"}, headers={"origin": "https://evil.example"}).status_code == 403
    assert not os.path.exists(env["inbox"]) or _inbox_rows(env["inbox"], "owner_messages") == []
    assert c.post(say, json={"text": "a"}, headers={"origin": "http://testserver"}).status_code == 200
    assert c.post(say, json={"text": "b"}).status_code == 200            # no Origin header (same-origin fetch)


def test_rate_limit(env):
    c = env["client"]
    _login(c)
    for i in range(20):
        assert c.post(f"/api/rooms/{ROOM}/say", json={"text": f"m{i}"}).status_code == 200
    r = c.post("/api/rooms/team:lead/say", json={"text": "one more"})
    assert r.status_code == 429 and "20" in r.json()["detail"]
    assert len(_inbox_rows(env["inbox"], "owner_messages")) == 20
    # posts older than an hour do not count
    rooms = Rooms(env["agents"], env["inbox"], say_per_hour=20)
    assert rooms.say("team:lead", "later", "", now_ms=int(time.time() * 1000) + 3_700_000)["ok"]


def test_decide(env):
    c = env["client"]
    _login(c)
    before = _digest(env["agents"])
    ok, blocked = env["ok_proposal"], env["blocked_proposal"]
    r = c.post(f"/api/proposals/{blocked}/decide", json={"decision": "approve"})
    assert r.status_code == 409 and "코드 관문" in r.json()["detail"]      # nobody can overturn the code gate
    assert c.post(f"/api/proposals/{blocked}/decide", json={"decision": "reject"}).status_code == 409
    assert c.post("/api/proposals/999/decide", json={"decision": "approve"}).status_code == 404
    assert c.post(f"/api/proposals/{ok}/decide", json={"decision": "maybe"}).status_code == 400
    assert c.post(f"/api/proposals/{ok}/decide", json={"decision": "approve", "note": "z" * 1001}).status_code == 400
    r = c.post(f"/api/proposals/{ok}/decide", json={"decision": "approve", "note": "좋아요"})
    assert r.status_code == 200 and r.json()["decision"] == "approve"
    rows = _inbox_rows(env["inbox"], "approvals")
    assert [(x[2], x[3], x[5]) for x in rows] == [(ok, "approve", "좋아요")]
    p = next(x for x in c.get("/api/proposals").json() if x["id"] == ok)
    assert p["status"] == "awaiting_owner" and p["effective_status"] == "approved"
    assert p["owner_decision"]["decision"] == "approve" and p["owner_decision"]["applied"] is False
    room = next(r for r in c.get("/api/rooms").json()["rooms"] if r["room_id"] == ROOM)
    assert room["open_proposals"] == 0                                 # decided: no longer waits for the owners
    r = c.post(f"/api/proposals/{ok}/decide", json={"decision": "approve"})
    assert r.status_code == 409 and r.json()["detail"].endswith("(승인됨)")                    # already; in Korean
    assert c.post(f"/api/proposals/{ok}/decide", json={"decision": "reject"}).status_code == 200    # changed mind
    assert c.post(f"/api/proposals/{ok}/decide", json={"decision": "approve"}).status_code == 409   # reject is final
    assert c.post(f"/api/proposals/{ok}/decide", json={"decision": "reject"}).status_code == 409
    assert len(_inbox_rows(env["inbox"], "approvals")) == 2
    assert _digest(env["agents"]) == before                            # agents3.db untouched
    # the tick applies it (agents3.db): the decision now shows as applied
    a = R.open_agents(env["agents"])
    R.set_proposal_status(a, ok, "approved", "owner")
    R.set_proposal_status(a, ok, "rejected", "owner")
    a.close()
    p = next(x for x in c.get("/api/proposals").json() if x["id"] == ok)
    assert p["status"] == "rejected" and p["owner_decision"]["applied"] is True


# ---------------------------------------------------------------- live stream helper, missing databases
def test_since_for_stream(env):
    rooms = Rooms(env["agents"], env["inbox"])
    top, changed = rooms.since(0)
    assert top == max(env["msg_ids"]) and changed == {ROOM: env["msg_ids"][3], "team:ops": env["msg_ids"][4]}
    a = R.open_agents(env["agents"])
    new = R.post(a, "team:lead", None, "evening", "team_lead", None, "summary", "예시 요약")
    a.close()
    assert rooms.since(top) == (new, {"team:lead": new})
    assert rooms.since(new) == (new, {})
    assert rooms.since(new + 100) == (new, {ROOM: env["msg_ids"][3], "team:ops": env["msg_ids"][4], "team:lead": new})


def test_without_agents_db(tmp_path):
    inbox = str(tmp_path / "inbox.db")
    app = create_app(str(tmp_path / "paper3.db"), hash_password(PW), SECRET,
                     agents_db=str(tmp_path / "missing.db"), inbox_db=inbox)
    c = TestClient(app)
    _login(c)
    ov = c.get("/api/rooms").json()
    assert ov["ready"] is False and len(ov["rooms"]) == 42 and all(r["last_id"] == 0 for r in ov["rooms"])
    assert c.get(f"/api/rooms/{ROOM}/messages").json()["messages"] == []
    assert c.get("/api/proposals").json() == [] and c.get("/api/trials").json()["counts"]["total"] == 0
    assert c.get("/api/agents/usage").json()["calls"] == 0
    assert c.post(f"/api/rooms/{ROOM}/say", json={"text": "먼저 남겨 둡니다"}).status_code == 200
    assert [m["text"] for m in c.get(f"/api/rooms/{ROOM}/messages").json()["pending_owner"]] == ["먼저 남겨 둡니다"]
    assert not os.path.exists(tmp_path / "missing.db")
    assert c.post("/api/proposals/1/decide", json={"decision": "approve"}).status_code == 404
    # no inbox configured: owner writes are refused, reads still work
    c2 = TestClient(create_app(str(tmp_path / "paper3.db"), None, SECRET))
    assert c2.post(f"/api/rooms/{ROOM}/say", json={"text": "hi"}).status_code == 503
    assert len(c2.get("/api/rooms").json()["rooms"]) == 42


def test_budget_caps_and_schedule(monkeypatch):
    caps = budget_caps("incident=5:1000, total=50;weekly=x")
    assert caps["incident"] == {"calls": 5, "tokens": 1000}
    assert caps["total"]["calls"] == 50
    assert "weekly" not in caps or caps["weekly"]["calls"] != "x"
    assert "강제청산" in room_schedule_ko("team:ops") and room_schedule_ko("team:nope") == ""
    # weekly review weekday = strategy index mod 7 (Monday first), as in triggers.py
    assert "월요일" in room_schedule_ko("strat:S1_EMA_RSI_CHOP")
    assert "화요일" in room_schedule_ko("strat:S2_ST_ROC")
    assert json.dumps(room_schedule_ko(ROOM), ensure_ascii=False)


# ---------------------------------------------------------------- review fixes (regression tests)
def test_write_bodies_are_capped_before_parsing(env):
    c = env["client"]
    _login(c)
    r = c.post(f"/api/rooms/{ROOM}/say", json={"text": "hi", "pad": "x" * 20_000_000})
    assert r.status_code == 413
    r = c.post(f"/api/proposals/{env['ok_proposal']}/decide", json={"decision": "approve", "pad": "x" * 20_000})
    assert r.status_code == 413
    assert not os.path.exists(env["inbox"]) or _inbox_rows(env["inbox"], "owner_messages") == []
    assert c.post(f"/api/rooms/{ROOM}/say", json={"text": "가" * 1000}).status_code == 200    # a full post fits


def test_text_sqlite_cannot_store_is_refused(env):
    c = env["client"]
    _login(c)
    r = c.post(f"/api/rooms/{ROOM}/say", content='{"text": "hi \\ud800"}', headers={"content-type": "application/json"})
    assert r.status_code == 400
    r = c.post(f"/api/proposals/{env['ok_proposal']}/decide", content='{"decision": "reject", "note": "\\udfff"}',
               headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_author_is_one_of_the_configured_owners_or_nobody(tmp_path, monkeypatch):
    now = int(time.time() * 1000)
    agents, inbox = str(tmp_path / "agents3.db"), str(tmp_path / "inbox.db")
    _agents_db(agents, now)
    monkeypatch.setenv("DASH_OWNERS", "민수, 지영")
    c = TestClient(create_app(str(tmp_path / "paper3.db"), hash_password(PW), SECRET, agents_db=agents,
                              inbox_db=inbox))
    _login(c)
    assert c.post(f"/api/rooms/{ROOM}/say", json={"text": "a", "author": "코드(자동 계산)"}).status_code == 200
    assert c.post(f"/api/rooms/{ROOM}/say", json={"text": "b", "author": "지영"}).status_code == 200
    assert [r[3] for r in _inbox_rows(inbox, "owner_messages")] == ["", "지영"]


def test_origin_must_match_the_scheme_too(env):
    c = env["client"]
    _login(c)
    say = f"/api/rooms/{ROOM}/say"
    assert c.post(say, json={"text": "a"}, headers={"origin": "https://testserver"}).status_code == 403
    assert c.post(say, json={"text": "a"}, headers={"origin": "http://testserver"}).status_code == 200


def test_usage_shows_the_seven_day_cap(env):
    c = env["client"]
    _login(c)
    u = c.get("/api/agents/usage").json()
    assert u["week"]["calls"] == 3 and u["week"]["cap_calls"] == DEFAULT_WEEK[0]      # the 2000-01-01 row is outside
    assert budget_caps("week=100:9")["week"] == {"calls": 100, "tokens": 9}


def test_decisions_older_than_this_agents_db_are_not_shown(env):
    c = env["client"]
    _login(c)
    ib = R.open_inbox_rw(env["inbox"])
    R.add_approval(ib, env["ok_proposal"], "reject", "", "옛 agents3.db의 제안에 대한 클릭")
    ib.close()
    a = R.open_agents(env["agents"])
    R.set_cursor(a, "inbox:approvals_base", "1")          # the tick found that click already there
    a.close()
    p = next(x for x in c.get("/api/proposals").json() if x["id"] == env["ok_proposal"])
    assert p["owner_decision"] is None and p["effective_status"] == "awaiting_owner"
    assert c.post(f"/api/proposals/{env['ok_proposal']}/decide", json={"decision": "approve"}).status_code == 200


# ---------------------------------------------------------------- round-2 guards
def test_huge_ids_are_not_found_not_a_server_error(env):
    c = env["client"]
    _login(c)
    huge = "99999999999999999999999"
    assert c.post(f"/api/proposals/{huge}/decide", json={"decision": "reject"}).status_code == 404
    r = c.get(f"/api/rooms/{ROOM}/messages?after_id={huge}")
    assert r.status_code == 200 and r.json()["messages"] == []           # nothing after it
    r = c.get(f"/api/rooms/{ROOM}/messages?before_id={huge}")
    assert r.status_code == 200 and len(r.json()["messages"]) == 4       # everything is before it
    assert _inbox_rows(env["inbox"], "approvals") == []


def test_pages_cannot_be_framed(env):
    c = env["client"]
    for r in (c.get("/login"), c.get("/api/rooms")):                   # before and after login
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
    _login(c)
    assert c.get("/api/rooms").headers["X-Frame-Options"] == "DENY"


def test_approve_is_refused_when_code_now_judges_the_gate_failed(env):
    c = env["client"]
    _login(c)
    ok = env["ok_proposal"]
    a = R.open_agents(env["agents"])                                   # what the tick stores after re-judging
    R.set_cursor(a, "proposals:gate_now", {str(ok): {"pass": False, "n_trials": 4}})
    a.close()
    p = next(x for x in c.get("/api/proposals").json() if x["id"] == ok)
    assert p["gate_now"] == {"pass": False, "n_trials": 4} and p["gate"]["pass"] is True
    r = c.post(f"/api/proposals/{ok}/decide", json={"decision": "approve"})
    assert r.status_code == 409 and "다시 판정" in r.json()["detail"]
    assert c.post(f"/api/proposals/{ok}/decide", json={"decision": "reject"}).status_code == 200   # rejecting is fine
    blocked = next(x for x in c.get("/api/proposals").json() if x["id"] == env["blocked_proposal"])
    assert blocked["gate_now"] is None                                 # only open proposals are re-judged


def test_the_dashboard_start_creates_an_empty_inbox(tmp_path):
    """The live runner refuses every new extra account while inbox.db is missing (it cannot see a reject click):
    the dashboard creates the empty file when it starts, not only at the owners' first post or click."""
    inbox = str(tmp_path / "inbox.db")
    create_app(str(tmp_path / "paper3.db"), hash_password(PW), SECRET, agents_db=str(tmp_path / "agents3.db"),
               inbox_db=inbox)
    assert _inbox_rows(inbox, "approvals") == [] and _inbox_rows(inbox, "owner_messages") == []
    create_app(str(tmp_path / "paper3.db"), hash_password(PW), SECRET, inbox_db=str(tmp_path / "no" / "inbox.db"))
    assert not os.path.exists(tmp_path / "no")                        # a missing folder is not created


def test_inbox_db_must_be_its_own_file(tmp_path):
    agents = str(tmp_path / "agents3.db")
    paper = str(tmp_path / "paper3.db")
    link = str(tmp_path / "link.db")
    os.symlink(agents, link)
    for bad in (agents, paper, link):
        with pytest.raises(ValueError):
            create_app(paper, hash_password(PW), SECRET, agents_db=agents, inbox_db=bad)
    assert not os.path.exists(agents)                                  # nothing created in the wrong file
    from paperbot.dash.__main__ import main
    os.environ["DASH_PASSWORD_HASH"], os.environ["DASH_SECRET"] = hash_password(PW), "s" * 32
    try:
        assert main(["--db", paper, "--agents-db", agents, "--inbox-db", agents]) == 2
    finally:
        del os.environ["DASH_PASSWORD_HASH"], os.environ["DASH_SECRET"]


# ---------------------------------------------------------------- confirmation review
ROOMS_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static",
                        "rooms.js")


def _js(names: tuple, body: str) -> dict:
    """Run pure helpers of rooms.js (extracted by name) in node with ``body``; returns what it prints."""
    import re
    import shutil
    import subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    with open(ROOMS_JS, encoding="utf-8") as fh:
        src = fh.read()
    parts = ["const esc = (s) => String(s == null ? '' : s).replace(/[&<>\"']/g, (c) => '&#' + c.charCodeAt(0) + ';');"]
    for n in names:
        m = re.search(r"^(?:function %s\(.*?^}|const %s = .*?;)$" % (n, n), src, re.S | re.M)
        assert m, n
        parts.append(m.group(0))
    r = subprocess.run([node, "-e", "\n".join(parts) + "\n" + body], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_the_page_shows_when_the_agents_have_stopped(env, monkeypatch):
    from paperbot.agents import rooms as RM
    c = env["client"]
    _login(c)
    assert c.get("/api/rooms").json()["last_tick"] is None           # never ran with this code: unknown
    assert c.post(f"/api/rooms/{ROOM}/say", json={"text": "왜 계속 지나요?"}).status_code == 200
    for k in range(3):                                                  # every tick refused by the login check
        out = RM.tick(None, None, env["agents"], env["inbox"], None, now_ms=env["now"] + k * 900_000,
                      preflight=lambda: (False, "Claude Code would use an API key (ANTHROPIC_API_KEY)"))
        assert out["skipped"].startswith("preflight")
    ov = c.get("/api/rooms").json()
    assert ov["last_tick"]["ok"] is False and ov["last_tick"]["why"] == "login"
    assert ov["last_tick"]["ts"] == env["now"] + 2 * 900_000 and ov["tick_every_ms"] == 900_000
    assert len(c.get(f"/api/rooms/{ROOM}/messages").json()["pending_owner"]) == 1
    # a 'running' round a dead tick left behind is not shown as a live meeting
    a = R.open_agents(env["agents"])
    a.executemany("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, status) VALUES (?,?,?,?,?)",
                  [("team:risk", "owner", "{}", env["now"] - 3 * 3_600_000, "running"),
                   ("team:market", "morning", "{}", env["now"] - 60_000, "running")])
    a.commit()
    a.close()
    by = {r["room_id"]: r for r in c.get("/api/rooms", params={}).json()["rooms"]}
    assert by["team:risk"]["running"] is False and by["team:market"]["running"] is True


def test_the_page_logic_for_a_stopped_agent():
    got = _js(("agentsState", "agoKo", "pendingHint"), """
const now = 1e12, H = 3600000, T = 900000;
const ov = (last_tick, running, ready) => ({ready: ready !== false, now, tick_every_ms: T, last_tick,
  rooms: [{running: !!running}]});
const st = (o) => agentsState(o).st;
console.log(JSON.stringify({
  ok: st(ov({ts: now - 60000, ok: true})), stale: st(ov({ts: now - 2 * H, ok: true})),
  long_meeting: st(ov({ts: now - 2 * H, ok: true}, true)), missing: st(ov(null)),
  login: st(ov({ts: now - 60000, ok: false, why: "login"})), error: st(ov({ts: now, ok: false, why: "error"})),
  never: st(ov(null, false, false)), hint_ok: pendingHint("ok"), hint_stopped: pendingHint("stopped"),
  hint_login: pendingHint("login"), ago: agoKo(2 * H)}));
""")
    assert (got["ok"], got["stale"], got["long_meeting"], got["missing"], got["login"], got["error"], got["never"]) == (
        "ok", "stopped", "ok", "stopped", "login", "error", "new")
    assert got["hint_ok"] == "직원들이 다음 차례에 읽고 답합니다"
    assert got["hint_stopped"] == got["hint_login"] == "에이전트가 멈춰 있어 아직 전달되지 않습니다"
    assert got["ago"] == "마지막 점검 120분 전"
    with open(ROOMS_JS, encoding="utf-8") as fh:
        src = fh.read()
    assert "'<div class=\"hint\">직원들이 다음 차례에 읽고 답합니다</div>'" not in src     # never promised unconditionally
    assert "자동 토론이 멈춰 있습니다" in src and "로그인 확인에서 멈춤" in src


@pytest.mark.parametrize("error", ["Invalid API key · Please run /login", "API Error: Connection error."])
def test_the_page_says_when_every_ai_call_fails(env, tmp_path, error):
    """A revoked or expired Claude login, or no route to Claude: every call fails before the model answers and leaves
    no agent_calls row (ClassBudget.call: nothing ran), while the tick itself still runs and marks itself OK. The page
    reads the meetings that failed in a row for it (/api/rooms ai, the streak of the tick's own WARN) and shows the
    staff stopped after 6 hours, red on a phone too."""
    from paperbot.agents.runner import AgentCallError
    from paperbot.notify import ListNotifier
    from test_rooms import MIN, QUIET, World

    class Refused:
        def call(self, model, system_prompt, instruction, packet):
            raise AgentCallError(error)

    c = env["client"]
    _login(c)
    assert c.get("/api/rooms").json()["ai"] == {"failed": 0, "since": None}      # the fixture's last call was answered
    (tmp_path / "w").mkdir()
    w = World(tmp_path / "w")
    w.say("team:lead", "질문", QUIET - 10 * MIN)
    rm, ov = Rooms(w.paths["agents"], w.paths["inbox"]), {}
    for k in range(7 * 4 + 1):                           # the 15-minute timer for 7 hours
        t = QUIET + k * 15 * MIN
        w.tick(Refused(), t, notifier=ListNotifier())
        o = rm.overview(t)
        ov[k * 15] = {**{x: o[x] for x in ("ready", "now", "last_tick", "ai", "tick_every_ms")},
                      "rooms": [{"running": r["running"]} for r in o["rooms"]]}
    assert w.q("SELECT COUNT(*) FROM agent_calls") == [(0,)] and len(w.rounds()) >= 3
    assert ov[420]["ai"] == {"failed": len(w.rounds()), "since": QUIET}
    w.agents.execute("INSERT INTO agent_calls VALUES (?,?,?,?,?,?,?)",
                     (QUIET + 7 * 60 * MIN, R.kst_day(QUIET), "owner", "team_lead", "sonnet", 1, 1000))
    w.agents.commit()
    assert rm.overview(QUIET + 7 * 60 * MIN)["ai"] == {"failed": 0, "since": None}    # answered since: not stopped
    got = _js(("agentsState", "agoKo", "aiChip"), """
const now = 1e12, H = 3600000, chips = [];
const $ = () => ({classList: {toggle() {}}, innerHTML: ""});
function chip(id, ok, text) { chips.push([id, ok, text]); }
const ov = (ai, tick) => ({ready: true, now, tick_every_ms: 900000, last_tick: tick || {ts: now - 60000, ok: true},
  rooms: [{running: false}], ai});
const st = (o) => agentsState(o).st;
const real = %s;
const rs = {ov: real[420]};
aiChip();
rs.ov = ov(undefined, {ts: now - 2 * H, ok: true});
aiChip();
console.log(JSON.stringify({failing: agentsState(real[420]), at6: st(real[360]), before6: st(real[345]),
  short: st(ov({failed: 9, since: now - 2 * H})), few: st(ov({failed: 2, since: now - 9 * H})),
  answered: st(ov({failed: 0, since: null})), old_server: st(ov(undefined)),
  tick_gone: st(ov({failed: 3, since: now - 7 * H}, {ts: now - 2 * H, ok: true})), chips}));
""" % json.dumps(ov))
    assert got["failing"] == {"st": "noai", "age": 7 * 3_600_000}
    assert (got["at6"], got["before6"]) == ("noai", "ok")
    assert (got["short"], got["few"], got["answered"], got["old_server"], got["tick_gone"]) == (
        "ok", "ok", "ok", "ok", "stopped")
    assert got["chips"] == [["chip-ai", False, "에이전트 멈춤 (AI 응답 없음 7시간)"],
                            ["chip-ai", False, "에이전트 멈춤 (마지막 점검 120분 전)"]]
    css = open(os.path.join(os.path.dirname(ROOMS_JS), "style.css"), encoding="utf-8").read()
    phone = css[css.index("@media (max-width: 720px)"):]
    assert ".chips span.opt { display: none; }" in phone and ".chips #chip-ai.bad { display: inline; }" in phone


def test_room_members_and_duties_are_what_the_room_staff_do():
    rm = Rooms(None, None)
    risk = rm.room_info("team:risk")["members_info"]
    assert [m["id"] for m in risk] == ["risk_officer", "team_lead"]
    assert "승인·변경하지 못함" in risk[0]["duty"] and "계획 승인·축소·거부" not in risk[0]["duty"]
    val = next(m for m in rm.room_info(ROOM)["members_info"] if m["id"] == "validator")
    assert "통과·불통과는 코드가 정함" in val["duty"]
    market = [m["id"] for m in rm.room_info("team:market")["members_info"]]
    assert "macro_corr" not in market and "similar_pattern" not in market


def test_the_ledger_names_a_copy_proposal_by_its_proposal_number(env):
    c = env["client"]
    _login(c)
    a = R.open_agents(env["agents"])
    now = env["now"]
    t2 = R.add_trial(a, ROOM, S, "test", {"template": "stop_atr", "k": 1.5, "strategy": S}, 1, ts=now - 800)
    R.add_trial_result(a, t2, "failed", {"gate": {"pass": False, "reasons": ["x"]}}, ts=now - 790)
    R.add_trial(a, ROOM, S, "copy_proposal", {"from_trial": t2, "test": {"template": "stop_atr", "k": 1.5}}, 1,
                ts=now - 700)
    blocked = R.add_proposal(a, ROOM, S, t2, {"strategy": S, "test": {"template": "stop_atr", "k": 1.5}},
                             {"pass": False, "reasons": ["x"]}, "blocked_gate", ts=now - 700)
    R.add_trial(a, ROOM, S, "copy_proposal", {"from_trial": env["trial"], "test": {"template": "stop_atr", "k": 2.5}},
                1, ts=now - 2_000)                       # written with the awaiting proposal (same time)
    a.close()
    rows = [t for t in c.get("/api/trials", params={"strategy": S}).json()["trials"] if t["kind"] == "copy_proposal"]
    by = {t["spec"]["from_trial"]: t for t in rows}
    assert (by[t2]["proposal_id"], by[t2]["proposal_status"]) == (blocked, "blocked_gate")
    assert (by[env["trial"]]["proposal_id"], by[env["trial"]]["proposal_status"]) == (env["ok_proposal"],
                                                                                       "awaiting_owner")
    shown = _js(("PSTATUS_KO", "TRIAL_KIND_KO", "TRIAL_ST_KO", "testKo", "ledgerRow"),
                "console.log(JSON.stringify(%s.map(ledgerRow)));" % json.dumps([by[t2], by[env["trial"]]]))
    assert f"복제 제안 #{blocked}" in shown[0] and "(시험 #%d)" % t2 in shown[0] and "코드 관문에서 막힘" in shown[0]
    assert f"#{by[t2]['id']} 복제 제안" not in shown[0]      # never the ledger row's own number as '#N'
    assert f"복제 제안 #{env['ok_proposal']}" in shown[1] and "두 분 확인 대기" in shown[1]


def _raw_status(app, method: str, path: str) -> int:
    """One request straight to the ASGI app: the path exactly as a client may send it (no normalising)."""
    import asyncio
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
             "headers": [(b"host", b"testserver")], "client": ("127.0.0.1", 1), "server": ("testserver", 80)}
    sent: list = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        sent.append(m)
    asyncio.run(app(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_only_the_login_page_files_are_public(env):
    app = env["client"].app
    assert _raw_status(app, "GET", "/static/login.css") == 200
    for path in ("/static/login/../app.js", "/static/login/../rooms.js", "/static/loginx.js"):
        assert _raw_status(app, "GET", path) in (302, 307, 401), path


def test_a_huge_login_body_is_refused_before_it_is_parsed(env):
    r = env["client"].post("/api/login", content=b'{"password": "' + b"x" * 40_000 + b'"}',
                           headers={"content-type": "application/json"})
    assert r.status_code == 413


# ---------------------------------------------------------------- confirmation review, round 2
def test_a_post_that_waits_for_midnight_is_told_so():
    got = _js(("pendingHint",), """
console.log(JSON.stringify({ok: pendingHint("ok"), full: pendingHint("ok", "room_full", 3),
  budget: pendingHint("ok", "budget", 3), stopped: pendingHint("stopped", "room_full", 3)}));
""")
    assert got["ok"] == "직원들이 다음 차례에 읽고 답합니다"
    assert "자정" in got["full"] and "하루 3번" in got["full"] and "다음 차례에" not in got["full"]
    assert "자정" in got["budget"] and "AI 한도" in got["budget"]
    assert got["stopped"] == "에이전트가 멈춰 있어 아직 전달되지 않습니다"


def test_every_gate_reason_and_whole_member_duties_are_shown():
    """Check 6 (the leverage-adjusted check of stop tests) was cut from the proposal card, and the member
    duties were cut with an ellipsis, hiding what a member cannot do."""
    got = _js(("agentsState", "decisionWhen", "decideButtons", "testKo", "propCard"), """
const now = 1e12;
const reasons = ["r1", "r2", "r3", "r4", "r5", "r6 레버리지 차이를 뺀 수익률"];
const prop = {id: 2, status: "awaiting_owner", effective_status: "awaiting_owner", change: {test: {template: "stop_atr", k: 3}},
  gate: {pass: false, n_trials: 2, reasons}, gate_now: {pass: false, n_trials: 2}, owner_decision: null, trial_id: 3,
  strategy_ko: "켈트너·RSI"};
var rs = {confirm: null, ov: {ready: true, now, tick_every_ms: 900000, last_tick: {ts: now, ok: true}, rooms: []}};
console.log(JSON.stringify({card: propCard(prop)}));
""")
    assert "r6 레버리지 차이를 뺀 수익률" in got["card"]
    with open(os.path.join(os.path.dirname(ROOMS_JS), "style.css"), encoding="utf-8") as fh:
        rule = next(line for line in fh if line.startswith(".mem .du"))
    assert "ellipsis" not in rule and "nowrap" not in rule


def test_a_post_the_budget_or_a_pause_defers_is_told_so():
    """/api/rooms owner_wait 'budget' (the day's or the 7-day AI allowance left after the kept shares) and
    'paused' (a Claude plan limit or an outage): never the next-turn promise."""
    got = _js(("pendingHint",), """
console.log(JSON.stringify({budget: pendingHint("ok", "budget", 3), paused: pendingHint("ok", "paused", 3),
  stopped: pendingHint("stopped", "paused", 3)}));
""")
    assert "다음 차례" not in got["budget"] and "7일" in got["budget"] and "08:00·14:00·22:00" in got["budget"]
    assert "다음 차례" not in got["paused"] and "멈췄습니다" in got["paused"] and "1시간" in got["paused"]
    assert got["stopped"] == "에이전트가 멈춰 있어 아직 전달되지 않습니다"


def test_the_owner_post_ai_budget_used_up_is_shown_for_every_room(env):
    a = R.open_agents(env["agents"])
    day = R.kst_day(env["now"])
    a.executemany("INSERT INTO agent_calls VALUES (?,?,?,?,?,?,?)",
                  [(env["now"] - 1_000, day, "owner", "x", "sonnet", 1, 1000)] * 20)     # the default cap: 20
    a.commit()
    a.close()
    ov = Rooms(env["agents"], env["inbox"]).overview(now_ms=env["now"])
    assert {r["owner_wait"] for r in ov["rooms"]} == {"budget"} and ov["rounds_per_room_day"] == 4
    assert {r["owner_wait"] for r in Rooms(env["agents"], env["inbox"]).overview(
        now_ms=env["now"] + 86_400_000)["rooms"]} == {None}                             # a new KST day


def test_an_owner_decision_is_not_promised_while_the_agents_are_stopped():
    """Timer off for 2 hours: the owners' approve click must not say it is applied on the next turn (the
    page already says their posts are not delivered). In the 'login' state apply_approvals still runs."""
    got = _js(("agentsState", "decisionWhen", "decideButtons", "testKo", "propCard"), """
const now = 1e12;
const prop = {id: 2, status: "awaiting_owner", effective_status: "approved", change: {test: {template: "stop_atr", k: 3}},
  gate: {pass: true, n_trials: 2, reasons: []}, gate_now: {pass: true, n_trials: 2},
  owner_decision: {decision: "approve", ts: now - 60000, note: "", applied: false}, trial_id: 3, strategy_ko: "켈트너·RSI"};
const ov = (tick) => ({ready: true, now, tick_every_ms: 900000, last_tick: tick, rooms: [{running: false}]});
var rs = {confirm: null, ov: ov({ts: now - 120 * 60000, ok: true})};
const stopped = propCard(prop);
rs.ov = ov({ts: now - 60000, ok: true});
const ok = propCard(prop);
rs.ov = ov({ts: now - 60000, ok: false, why: "login"});
const login = propCard(prop);
console.log(JSON.stringify({stopped, ok, login}));
""")
    assert "다음 차례" not in got["stopped"] and "멈춰 있어 아직 반영되지 않습니다" in got["stopped"]
    assert "다음 차례(15분 안)에 코드가 반영합니다" in got["ok"] and "다음 차례(15분 안)에 코드가 반영합니다" in got["login"]
    with open(ROOMS_JS, encoding="utf-8") as fh:
        src = fh.read()
    assert "직원들이 다음 차례에 반영합니다" not in src


def test_the_newest_owner_decisions_are_read_after_a_thousand_older_ones(env):
    """_decisions read at most 1,000 clicks, oldest first: after years of clicks the page missed the newest."""
    ib = R.open_inbox_rw(env["inbox"])
    ib.executemany("INSERT INTO approvals (ts, proposal_id, decision, author, note) VALUES (?,?,?,?,?)",
                   [(env["now"] - 10_000 + k, 10_000 + k, "reject", "", None) for k in range(1_005)])
    ib.commit()
    R.add_approval(ib, 77_777, "approve", "", ts=env["now"])
    ib.close()
    decs = Rooms(env["agents"], env["inbox"])._decisions()
    assert len(decs) == 1_006 and decs[77_777]["decision"] == "approve"


def test_the_proposal_hint_names_no_fixed_starting_amount():
    """The hint under every approve/reject card said a copy starts as a new $1,000 account after paper v3
    accounts moved to $5,000: it names no amount now (a copy starts like its original)."""
    with open(ROOMS_JS, encoding="utf-8") as fh:
        src = fh.read()
    assert "$1,000" not in src and "$1000" not in src
    assert "원본 계좌와 같은 시작 자금" in src


def test_timeouts_of_an_outage_are_labelled_in_the_usage_panel(env):
    """Calls that timed out with no model activity are counted under no meeting kind ('timeout'): the usage
    panel names them in Korean."""
    from paperbot.agents.rooms import TIMEOUT_PIPELINE
    a = sqlite3.connect(env["agents"])
    a.execute("INSERT INTO agent_calls (ts, day, pipeline, role, model, ok, tokens) VALUES (?,?,?,?,?,0,?)",
              (env["now"], R.kst_day(env["now"]), TIMEOUT_PIPELINE, "ops_auditor", "sonnet", 17_000))
    a.commit()
    a.close()
    c = env["client"]
    _login(c)
    got = {x["class"]: x for x in c.get("/api/agents/usage").json()["classes"]}
    assert got["timeout"]["calls"] == 1 and "시간 초과" in got["timeout"]["name_ko"]


def test_a_class_bar_fills_by_whichever_cap_is_nearer():
    """The usage panel drew each meeting kind's bar by calls only, while a token cap often binds first."""
    got = _js(("bar", "classBar"), """
console.log(JSON.stringify({tok: classBar({calls: 5, cap_calls: 20, tokens: 480000, cap_tokens: 500000}),
  calls: classBar({calls: 18, cap_calls: 20, tokens: 1000, cap_tokens: 500000}),
  none: classBar({calls: 3, tokens: 50000})}));
""")
    assert "width:96%" in got["tok"] and "width:90%" in got["calls"] and got["none"] == ""


def test_proposal_cards_for_new_strategies_started_accounts_and_runtime_refusals():
    """A new-strategy proposal card (its proposal number, ledger number, the lab's count), a proposal whose
    account started (no reject button), one the runner waits on for a fresh click ('다시 승인'), and the
    approve confirmation once the runner's feature is deployed."""
    got = _js(("RE_APPROVE", "agentsState", "decisionWhen", "decideButtons", "newlabKo", "testKo", "propCard"), """
const now = 1e12;
var DIR_KO = {long: "롱만", short: "숏만", both: "롱·숏"};
var rs = {confirm: null, ov: {ready: true, now, tick_every_ms: 900000, last_tick: {ts: now, ok: true}, rooms: []}};
const lab = {id: 5, kind: "newlab", status: "awaiting_owner", effective_status: "awaiting_owner", trial_id: 57,
  change: {kind: "newlab", proposal: {description_ko: "1시간 RSI 되돌림 (롱만)"}, account: {spec: {timeframe: "1h"}}},
  gate: {pass: true, n_tests: 3, reasons: ["① 통과"]}, gate_now: {pass: true, n_trials: 4}, owner_decision: null,
  runtime_ready: true, account_running: null, runtime_refusal: null};
const run = {id: 6, kind: "copy", status: "approved", effective_status: "approved", trial_id: 3, strategy_ko: "켈트너·RSI",
  change: {test: {template: "stop_atr", k: 2.5}, account: {parent: "N17_KC_RSI@15m"}}, gate: {pass: true, n_trials: 1},
  gate_now: {pass: true, n_trials: 1}, owner_decision: null, runtime_ready: true,
  account_running: {account_id: "N17_KC_RSI@15m~c1", label_ko: "켈트너·RSI 15분 복제 c1", extra_status: "suspended"}};
const stale = {...run, id: 7, account_running: null,
  runtime_refusal: {code: "stale_ok", text_ko: "한 번 더 승인해야 시작합니다", proposal_ts: 1}};
const lost = {...stale, id: 8, runtime_refusal: {code: "owner_click_missing", text_ko: "승인 클릭을 찾지 못했습니다",
  proposal_ts: 1}};
rs.confirm = {id: 5, dec: "approve"};
const confirm = propCard(lab);
rs.confirm = null;
console.log(JSON.stringify({lab: propCard(lab), run: propCard(run), stale: propCard(stale), lost: propCard(lost),
                            confirm}));
""")
    assert "새 매매법 제안 #5 · 장부 #57" in got["lab"] and "1시간 RSI 되돌림 (롱만)" in got["lab"]
    assert "새 매매법 시험 4번 기준" in got["lab"] and "새 매매법 시험 5번 기준" in got["lab"]
    assert 'data-dec="approve"' in got["lab"]
    assert "계좌 시작됨" in got["run"] and "N17_KC_RSI@15m~c1" in got["run"] and "멈춤(보류)" in got["run"]
    assert 'data-dec="reject"' not in got["run"] and "원본 계좌 N17_KC_RSI@15m" in got["run"]
    assert "다시 승인" in got["stale"] and "실행기: 한 번 더 승인해야 시작합니다" in got["stale"]
    assert "다시 승인" in got["lost"] and 'data-dec="approve"' in got["lost"]      # a lost click: one more click
    assert "다음 5분 봉 경계" in got["confirm"] and "거절로 멈출 수 없습니다" in got["confirm"]
