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
    assert not os.path.exists(env["inbox"])            # nothing written without a login


# ---------------------------------------------------------------- reads
def test_overview(env):
    c = env["client"]
    _login(c)
    ov = c.get("/api/rooms").json()
    assert ov["ready"] is True and len(ov["rooms"]) == 41
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
    R.post(a, ROOM, 3, "owner", "owner", None, "owner", "손절을 넓히면 어떨까요?", {"inbox_id": rows[0][0]})
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
    assert c.post(f"/api/proposals/{ok}/decide", json={"decision": "approve"}).status_code == 409   # already
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
    assert ov["ready"] is False and len(ov["rooms"]) == 41 and all(r["last_id"] == 0 for r in ov["rooms"])
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
    assert len(c2.get("/api/rooms").json()["rooms"]) == 41


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
