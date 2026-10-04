"""Dashboard '회의실' (meeting room view): /api/office on a synthetic agents3.db (opened read-only): the
meeting running now, who spoke in order, the real first sentence of each one's latest message, whose turn
comes next when the meeting's order says so, today's finished meetings and counts, the fixed meeting hours
the agents published; a missing, empty or unreadable agents3.db; and that nothing is ever written."""

import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.agents import rooms_db as R  # noqa: E402
from paperbot.dash.app import Rooms, bubble_line, create_app, hash_password, office_schedule  # noqa: E402

SECRET = b"x" * 32
PW = "correct horse battery"
KST = datetime.timezone(datetime.timedelta(hours=9))
NOW = int(datetime.datetime(2026, 10, 4, 10, 30, tzinfo=KST).timestamp() * 1000)   # 10:30 KST
S = "N17_KC_RSI"
STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")


def _round(c, room, trigger, started, status="running", data=None, ended=None, decision=None, calls=0) -> int:
    cur = c.execute("INSERT INTO rounds (room_id, trigger, trigger_data, started_ts, ended_ts, status, decision, calls) "
                    "VALUES (?,?,?,?,?,?,?,?)", (room, trigger, json.dumps(data or {}, ensure_ascii=False), started,
                                                  ended, status, json.dumps(decision, ensure_ascii=False)
                                                  if decision is not None else None, calls))
    c.commit()
    return int(cur.lastrowid)


def _agents_db(path: str, now: int) -> dict:
    """A morning meeting running in team:market (two staff spoke, one turn skipped by code), a strategy
    meeting running in its room, a dead tick's 'running' row, finished meetings today and yesterday,
    the hours the tick published and today's AI calls."""
    c = R.open_agents(path)
    R.ensure_rooms(c, ts=now - 86_400_000)
    yday = _round(c, f"strat:{S}", "weekly", now - 86_400_000, "done", ended=now - 86_000_000,
                  decision={"summary_ko": "🧾 어제 회의"})
    R.post(c, f"strat:{S}", yday, "weekly", f"spec_{S}", None, "analysis", "어제 분석", ts=now - 86_100_000)
    done = _round(c, "team:review", "ranking", now - 3_600_000, "done", ended=now - 3_000_000, calls=3,
                  decision={"summary_ko": "🧾 순위 검토: 상위 3·하위 3 매매법을 비교했습니다. 다음은 30건 뒤.\n둘째 줄"})
    for role, t in (("pnl_reviewer", "상위 매매법은 추세장에서 벌었습니다."), ("risk_officer", "하위는 비용이 큽니다."),
                    ("team_lead", "1. 상위는 추세, 하위는 비용 때문입니다.")):
        R.post(c, "team:review", done, "ranking", role, None, "summary" if role == "team_lead" else "analysis", t,
               ts=now - 3_300_000)
    R.post(c, "team:review", done, "ranking", "code", None, "decision", "🧾 결정", ts=now - 3_000_000)
    dead = _round(c, "team:risk", "owner", now - 3 * 3_600_000)             # a dead tick's row: not live
    morning = _round(c, "team:market", "morning", now - 300_000, data={"summary_ko": "아침 회의 (08:00)"})
    R.post(c, "team:market", morning, "morning", "code", None, "trigger", "📣 회의 시작: 아침 회의", ts=now - 300_000)
    R.post(c, "team:market", morning, "morning", "chart_regime", None, "analysis",
           "BTC는 박스권입니다. 위아래 1% 안에서 움직였습니다.\n- [사실] 4시간봉 ADX 15", {"turn": "team"}, ts=now - 240_000)
    R.post(c, "team:market", morning, "morning", "code", None, "system",
           "파생·오더플로 분석가의 답을 읽을 수 없어 이번 차례는 건너뜁니다.", {"role": "derivs_flow", "problems": ["x"]},
           ts=now - 200_000)
    R.post(c, "team:market", morning, "morning", "strategist", None, "analysis",
           "↳ 차트·장세 분석가에게 동의: 박스권\n롱·숏 모두 허용하되 크기는 절반으로 합니다! 이유는 아래.", {"turn": "team"},
           ts=now - 120_000)
    # a note code adds after the strategist's answer (not a skipped turn)
    R.post(c, "team:market", morning, "morning", "code", None, "system",
           "전략가의 답에서 코드 검사에 걸린 1곳을 빼거나 고쳤습니다.", {"role": "strategist", "problems": ["y"]},
           ts=now - 110_000)
    strat = _round(c, f"strat:{S}", "loss_cluster", now - 60_000, data={"summary_ko": "새 손실 3건"})
    R.post(c, f"strat:{S}", strat, "loss_cluster", f"spec_{S}", None, "analysis", "손실 3건 중 2건이 추세 반대 진입입니다.",
           {"turn": "specialist", "answer": {"proposal": {"action": "note"}}}, ts=now - 30_000)
    R.set_cursor(c, "policy:hours", {"morning": 8, "ranking": 14, "tf_split": -1, "evening": 22,
                                     "weekly_report": 21, "loss_min_count": 2, "loss_min_gap_ms": 7_200_000})
    day = R.kst_day(now)
    c.executemany("INSERT INTO agent_calls VALUES (?,?,?,?,?,?,?)",
                  [(now - 5_000, day, "scheduled", "chart_regime", "sonnet", 1, 3000)] * 5
                  + [(now - 86_400_000, R.kst_day(now - 86_400_000), "loss", "x", "sonnet", 1, 10)])
    c.commit()
    c.close()
    return {"done": done, "morning": morning, "strat": strat, "dead": dead}


def _dump(path: str) -> str:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return hashlib.sha256("\n".join(c.iterdump()).encode()).hexdigest()
    finally:
        c.close()


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "agents3.db")
    return {"path": path, **_agents_db(path, NOW)}


def test_the_running_meeting_its_speakers_and_bubbles(db):
    before = _dump(db["path"])
    o = Rooms(db["path"], None).office(now_ms=NOW)
    assert o["ready"] is True and "error" not in o
    assert [m["room_id"] for m in o["running"]] == ["team:market", f"strat:{S}"]      # the dead tick's row is not live
    m = o["running"][0]
    assert m["trigger"] == "morning" and m["trigger_ko"] == "아침 회의" and m["started_ts"] == NOW - 300_000
    assert m["why"] == "아침 회의 (08:00)" and m["title"] == "시장분석팀"
    assert [t["role"] for t in m["turns"]] == ["chart_regime", "strategist"]           # in order, code never a speaker
    # the first sentence of the real message; the reply line is skipped when the message has more
    assert m["lines"]["chart_regime"]["line"] == "BTC는 박스권입니다."
    assert m["lines"]["strategist"]["line"] == "롱·숏 모두 허용하되 크기는 절반으로 합니다!"
    assert m["last_role"] == "strategist"
    # morning order (rooms.team_plan): chart_regime, derivs_flow (skipped by code), strategist, devils_advocate, lead
    assert m["next_role"] == "devils_advocate"
    assert m["participants"] == ["chart_regime", "derivs_flow", "strategist", "devils_advocate", "team_lead"]
    s = o["running"][1]
    assert s["kind"] == "strategy" and s["title"] == "켈트너·RSI" and s["strategy"] == S
    assert s["next_role"] == "devils_advocate" and s["participants"] == [f"spec_{S}", "devils_advocate"]
    assert o["roles"][f"spec_{S}"] == {"name": "켈트너·RSI 전담", "label": "켈트너·RSI", "team": "specialist"}
    assert o["roles"]["chart_regime"]["team"] == "market" and o["roles"]["team_lead"]["team"] == "lead"
    assert _dump(db["path"]) == before                                                  # read-only


def test_today_finished_meetings_counts_and_latest_strategy_rooms(db):
    o = Rooms(db["path"], None).office(now_ms=NOW)
    assert [r["round_id"] for r in o["recent"]] == [db["done"]]           # today's, finished; yesterday's is not
    r = o["recent"][0]
    assert r["decision"] == "🧾 순위 검토: 상위 3·하위 3 매매법을 비교했습니다." and r["status"] == "done"
    assert r["speakers"] == ["pnl_reviewer", "risk_officer", "team_lead"] and r["trigger_ko"] == "순위 검토"
    assert o["today"]["meetings"] == 4 and o["today"]["ai_calls"] == 5      # the dead row started today too
    assert o["today"]["by_room"]["team:market"] == 1
    assert [x["room_id"] for x in o["latest_strategy"]] == [f"strat:{S}", f"strat:{S}"]
    assert [z["room_id"] for z in o["zones"]] == ["team:market", "team:risk", "team:ops", "team:review", "team:lead",
                                                   "team:lab"]
    assert o["strategy_members"] == list(R.STRATEGY_ROOM_ROLES)


def test_whose_turn_is_next_follows_the_meetings_own_order(db):
    a = R.open_agents(db["path"])
    R.post(a, f"strat:{S}", db["strat"], "loss_cluster", "devils_advocate", None, "challenge", "4건은 적습니다.",
           {"turn": "challenge", "answer": {"verdict": "disagree"}}, ts=NOW - 20_000)
    a.close()
    rooms = Rooms(db["path"], None)
    s = rooms.office(now_ms=NOW)["running"][1]
    assert s["next_role"] is None            # an expert or the end: depends on the answers, not guessed
    a = R.open_agents(db["path"])
    R.post(a, f"strat:{S}", db["strat"], "loss_cluster", "exit_timing", None, "expert", "손절이 너무 가깝습니다.",
           ts=NOW - 10_000)
    a.close()
    s = rooms.office(now_ms=NOW)["running"][1]
    assert s["next_role"] == f"spec_{S}" and "exit_timing" in s["participants"]
    # the last turn of the morning meeting: the lead is next, then nobody
    a = R.open_agents(db["path"])
    R.post(a, "team:market", db["morning"], "morning", "devils_advocate", None, "challenge", "반론입니다.", ts=NOW - 5_000)
    a.close()
    assert rooms.office(now_ms=NOW)["running"][0]["next_role"] == "team_lead"
    a = R.open_agents(db["path"])
    R.post(a, "team:market", db["morning"], "morning", "team_lead", None, "summary", "1. 요약입니다.", ts=NOW - 1_000)
    R.post(a, "team:market", db["morning"], "morning", "code", None, "code_result", "텔레그램으로 보냈습니다. 끝.",
           ts=NOW - 500)
    a.close()
    m = rooms.office(now_ms=NOW)["running"][0]
    assert m["next_role"] is None and m["last_role"] == "team_lead" and m["lines"]["team_lead"]["line"] == "요약입니다."
    assert m["code"] == {"kind": "code_result", "ts": NOW - 500, "line": "텔레그램으로 보냈습니다."}


def test_the_endpoint_needs_a_login_and_is_read_only(tmp_path):
    now = int(time.time() * 1000)
    path = str(tmp_path / "agents3.db")
    _agents_db(path, now)
    before = _dump(path)
    c = TestClient(create_app(str(tmp_path / "paper3.db"), hash_password(PW), SECRET, agents_db=path,
                              inbox_db=str(tmp_path / "inbox.db")))
    assert c.get("/api/office").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    o = c.get("/api/office").json()
    assert o["ready"] is True and o["running"][0]["room_id"] == "team:market"
    assert o["running"][0]["next_role"] == "devils_advocate"
    assert o["schedule"]["source"] == "tick" and [s["hhmm"] for s in o["schedule"]["slots"]] == ["08:00", "14:00", "22:00"]
    assert c.post("/api/office").status_code == 405
    assert _dump(path) == before


def test_a_missing_empty_or_unreadable_agents_db(tmp_path):
    missing = str(tmp_path / "missing.db")
    o = Rooms(missing, None).office(now_ms=NOW)
    assert o["ready"] is False and o["running"] == [] and o["recent"] == [] and o["today"]["meetings"] == 0
    assert o["schedule"]["source"] == "defaults" and o["schedule"]["next"]["hhmm"] == "14:00"
    assert len(o["zones"]) == 6 and "team_lead" in o["roles"] and not os.path.exists(missing)
    empty = str(tmp_path / "empty.db")
    sqlite3.connect(empty).close()                  # a database with no tables yet: nothing to show, no error
    o = Rooms(empty, None).office(now_ms=NOW)
    assert o["ready"] is True and o["running"] == [] and "error" not in o
    junk = str(tmp_path / "junk.db")
    with open(junk, "wb") as fh:
        fh.write(b"not a database" * 100)
    assert Rooms(junk, None).office(now_ms=NOW)["ready"] is False
    odd = str(tmp_path / "odd.db")                  # a 'rounds' table this code cannot read: said, not a crash
    c = sqlite3.connect(odd)
    c.execute("CREATE TABLE rounds (x)")
    c.commit()
    c.close()
    o = Rooms(odd, None).office(now_ms=NOW)
    assert o["error"].startswith("agents3.db를 읽지 못함") and o["running"] == []
    app = create_app(str(tmp_path / "paper3.db"), None, SECRET, agents_db=odd)
    assert TestClient(app).get("/api/office").status_code == 200


def test_the_next_fixed_meeting_comes_from_the_published_hours():
    h = {"morning": 9, "ranking": -1, "tf_split": 18, "evening": 21}
    at = lambda hh, mm: int(datetime.datetime(2026, 10, 4, hh, mm, tzinfo=KST).timestamp() * 1000)  # noqa: E731
    s = office_schedule(at(10, 30), h)
    assert [x["hhmm"] for x in s["slots"]] == ["09:00", "18:00", "21:00"]            # -1 = off
    assert s["next"]["hhmm"] == "18:00" and s["next"]["trigger_ko"] == "봉 비교 회의" and s["next"]["tomorrow"] is False
    assert s["next"]["at_ms"] == at(18, 0)
    s = office_schedule(at(21, 5), h)
    assert s["next"]["hhmm"] == "09:00" and s["next"]["tomorrow"] is True
    assert s["next"]["at_ms"] == at(9, 0) + 86_400_000
    assert office_schedule(at(8, 59), h)["next"]["hhmm"] == "09:00"
    assert office_schedule(at(9, 0), h)["next"]["hhmm"] == "18:00"                    # 09:00 itself is under way


def test_a_bubble_is_only_the_first_sentence_of_the_real_message():
    assert bubble_line("") == ""
    assert bubble_line("손실 0.4%가 났습니다. 다음은 비용.") == "손실 0.4%가 났습니다."
    assert bubble_line("↳ 전략가에게 반대: 표본이 적음") == "↳ 전략가에게 반대: 표본이 적음"
    assert bubble_line("1. 첫째 줄 요약\n2. 둘째") == "첫째 줄 요약"
    long = "가" * 200
    assert bubble_line(long) == "가" * 89 + "…" and len(bubble_line(long, 20)) == 20


def test_the_page_has_the_meeting_room_view():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert '<button data-v="office">회의실</button>' in html and 'id="v-office"' in html
    assert html.index("/static/rooms.js") < html.index("/static/office.js")       # uses openRoom, hm, ROLE_AV
    with open(os.path.join(STATIC, "office.js"), encoding="utf-8") as fh:
        js = fh.read()
    assert "http" not in js.replace("/api/office", "")                              # no outside images or libraries
    assert "실시간 타이핑이 아닙니다" in js and "/api/office" in js
    assert "ofVisible()" in js and 'state.view === "office"' in js                  # polls only while it is shown


def test_the_kept_meeting_hours_follow_the_published_hours():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    import re
    with open(os.path.join(STATIC, "rooms.js"), encoding="utf-8") as fh:
        src = fh.read()
    fns = [re.search(r"^function %s\(.*?^}$" % n, src, re.S | re.M).group(0) for n in ("keptHoursKo", "pendingHint")]
    body = """console.log(JSON.stringify({a: keptHoursKo({morning_hour_kst: 9, ranking_hour_kst: -1, evening_hour_kst: 21}),
  b: keptHoursKo(null), c: pendingHint("ok", "budget", 3, keptHoursKo({morning_hour_kst: 7, ranking_hour_kst: 13,
  evening_hour_kst: 23}))}));"""
    r = subprocess.run([node, "-e", "\n".join(fns) + "\n" + body], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["a"] == "09:00·21:00" and got["b"] == "08:00·14:00·22:00" and "07:00·13:00·23:00" in got["c"]
