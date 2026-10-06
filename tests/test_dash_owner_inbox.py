"""Dashboard side of the owners' '🧪 이 매매법 시험해줘' (#103) and the round-2 views (owners 10/06):

- POST /api/rooms/team:lab/say with lab_request: the server writes the text (fixed first line), refuses while the agents'
  owner budget is 0 (off), over the daily request cap, outside the lab room, without the entry;
- POST /api/lab/intake/<id>/decide: the owners' click on an approximate request goes to inbox.db's
  lab_request_decisions only (agents3.db untouched), once, only while the row waits for them;
- /api/lab/intake carries the owner block fresh on every read;
- /api/v4/nextver (후보 장부 with evidence grades, 주장별 성적표 with base rates, 못 하는 아이디어) and /api/v4/goal
  (목표 진척도 한 줄) read only;
- agents/goalline.py: today's tests, the luck numbers the luck-calc shows, the verdict D-day; the evening Telegram
  carries the line only with AGENTS_GOAL_LINE;
- the screens: the form, the cards, the goal line on 홈, the hidden #/nextver screen.
"""
import json
import os
import re
import sqlite3
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.agents import debate_factory as DF  # noqa: E402
from paperbot.agents import disputes as DS  # noqa: E402
from paperbot.agents import goalline as GL  # noqa: E402
from paperbot.agents import labintake as LI  # noqa: E402
from paperbot.agents import rooms as RM  # noqa: E402
from paperbot.agents import rooms_db as R  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import luck as LK  # noqa: E402
from paperbot.dash.more import nextver as NV  # noqa: E402

from test_dash_rooms import _digest, _inbox_rows  # noqa: E402

SECRET = b"x" * 32
PW = "correct horse battery"
LAB = R.LAB_ROOM
NOISE = {"timeframe": "4h", "entry": {"family": "bb_revert"}, "direction": "both"}
OTHER = {"timeframe": "4h", "entry": {"family": "ema_cross", "params": {"fast": 9, "slow": 21}}}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
S = "N17_KC_RSI"


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _agents(path, now, owner=3):
    c = R.open_agents(path)
    R.ensure_rooms(c, ts=now - 86_400_000)
    LI.ensure(c)
    DS.ensure(c)
    R.set_cursor(c, LI.LIMITS_CURSOR, {"debate": 0, "meeting": 0, "owner": owner})
    return c


@pytest.fixture
def env(tmp_path):
    now = int(time.time() * 1000)
    agents, inbox = str(tmp_path / "agents3.db"), str(tmp_path / "inbox.db")
    c = _agents(agents, now)
    ex = LI.enqueue_owner(c, 1, 0, {"engine": "newlab", "spec": NOISE, "entry_fidelity": "exact"}, now - 60_000)
    ap = LI.enqueue_owner(c, 2, 0, {"engine": "newlab", "spec": OTHER, "entry_fidelity": "approx", "kept": ["이평 교차"],
                                    "lost": ["EMA 8 → 9"], "reason_codes": ["param_off_grid"]}, now - 50_000)
    no = LI.enqueue_owner(c, 3, 0, {"engine": "none", "entry_fidelity": "none", "reason_codes": ["pattern"],
                                    "idea": "머리어깨 숏"}, now - 40_000)
    c.close()
    app = create_app(str(tmp_path / "paper3.db"), hash_password(PW), SECRET, agents_db=agents, inbox_db=inbox)
    client = TestClient(app)
    assert client.post("/api/login", json={"password": PW}).status_code == 200
    return {"client": client, "agents": agents, "inbox": inbox, "now": now, "exact": ex, "approx": ap, "none": no,
            "tmp": tmp_path}


SAY = f"/api/rooms/{LAB}/say"


# ------------------------------------------------------------------ the form's post
def test_a_request_is_stored_as_an_owner_post_with_the_fixed_first_line(env):
    c = env["client"]
    before = _digest(env["agents"])
    r = c.post(SAY, json={"lab_request": True, "fields": {"entry": "볼린저 아래에서 다시 안으로", "timeframe": "4h",
                                                          "side": "둘 다", "link": "https://youtu.be/x"}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["lab_request"] is True and d["text"].split("\n")[0] == "🧪 시험 요청" and LI.is_lab_request(d["text"])
    rows = _inbox_rows(env["inbox"], "owner_messages")
    assert rows[-1][2] == LAB and "언제 들어가나: 볼린저 아래에서 다시 안으로" in rows[-1][4]
    assert _digest(env["agents"]) == before                                    # agents3.db is never written here
    for body, code, why in (({"lab_request": True, "fields": {"timeframe": "4h"}}, 400, "언제 들어가나"),
                            ({"lab_request": True, "fields": {"entry": "x", "timeframe": "1d"}}, 400, "시간봉"),
                            ({"lab_request": True, "fields": "x"}, 400, "내용")):
        r = c.post(SAY, json=body)
        assert r.status_code == code and why in r.json()["detail"]
    r = c.post("/api/rooms/team:risk/say", json={"lab_request": True, "fields": {"entry": "x"}})
    assert r.status_code == 400 and "새 매매법 연구실" in r.json()["detail"]
    assert c.post(SAY, json={"lab_request": True, "fields": {"entry": "x"}},
                  headers={"origin": "https://evil.example"}).status_code == 403
    assert c.post(SAY, json={"text": "보통 글도 그대로"}).status_code == 200    # a plain post is unchanged


def test_the_daily_request_cap_and_the_off_switch(env, tmp_path):
    c = env["client"]
    for i in range(LI.OWNER_REQUESTS_PER_DAY):
        assert c.post(SAY, json={"lab_request": True, "fields": {"entry": f"요청 {i}"}}).status_code == 200
    r = c.post(SAY, json={"lab_request": True, "fields": {"entry": "하나 더"}})
    assert r.status_code == 429 and "하루 5번" in r.json()["detail"]
    off = str(tmp_path / "off")
    os.makedirs(off)
    _agents(os.path.join(off, "agents3.db"), env["now"], owner=0).close()
    app = create_app(os.path.join(off, "paper3.db"), hash_password(PW), SECRET, agents_db=os.path.join(off, "agents3.db"),
                     inbox_db=os.path.join(off, "inbox.db"))
    c2 = TestClient(app)
    c2.post("/api/login", json={"password": PW})
    r = c2.post(SAY, json={"lab_request": True, "fields": {"entry": "x"}})
    assert r.status_code == 409 and "꺼져" in r.json()["detail"]
    assert c2.get("/api/lab/intake").json()["owner"]["enabled"] is False
    # a waiting request cannot be clicked while off (the agents would not apply it): refused, inbox.db untouched
    a = R.open_agents(os.path.join(off, "agents3.db"))
    wait = LI.enqueue_owner(a, 9, 0, {"engine": "newlab", "spec": OTHER, "entry_fidelity": "approx"}, env["now"] - 1000)
    a.close()
    r = c2.post(f"/api/lab/intake/{wait['id']}/decide", json={"decision": "run"})
    assert r.status_code == 409 and "꺼져" in r.json()["detail"]
    ib = os.path.join(off, "inbox.db")
    if os.path.exists(ib):
        x = sqlite3.connect(ib)
        try:
            assert not x.execute("SELECT 1 FROM sqlite_master WHERE name = 'lab_request_decisions'").fetchone()
        finally:
            x.close()
    # no agents3.db at all (before the first agents pass): off, never a server error
    none = str(tmp_path / "none")
    os.makedirs(none)
    app = create_app(os.path.join(none, "paper3.db"), hash_password(PW), SECRET,
                     agents_db=os.path.join(none, "agents3.db"), inbox_db=os.path.join(none, "inbox.db"))
    c3 = TestClient(app)
    c3.post("/api/login", json={"password": PW})
    assert c3.post(SAY, json={"lab_request": True, "fields": {"entry": "x"}}).status_code == 409
    o = c3.get("/api/lab/intake").json()["owner"]
    assert o["enabled"] is False and o["cards"] == []


# ------------------------------------------------------------------ the owners' click
def test_the_click_goes_to_inbox_once_and_only_for_a_waiting_request(env):
    c = env["client"]
    before = _digest(env["agents"])
    url = lambda i: f"/api/lab/intake/{i}/decide"
    assert c.post(url(env["approx"]["id"]), json={"decision": "maybe"}).status_code == 400
    assert c.post(url(9999), json={"decision": "run"}).status_code == 404
    assert c.post(url(2 ** 70), json={"decision": "run"}).status_code in (404, 422)
    r = c.post(url(env["exact"]["id"]), json={"decision": "run"})
    assert r.status_code == 409 and "대기" in r.json()["detail"]
    assert c.post(url(env["approx"]["id"]), json={"decision": "run"}, headers={"origin": "https://evil.example"}).status_code == 403
    r = c.post(url(env["approx"]["id"]), json={"decision": "run"})
    assert r.status_code == 200 and r.json()["decision_ko"] == "시험하기" and "15분" in r.json()["message"]
    rows = _inbox_rows(env["inbox"], "lab_request_decisions")
    assert len(rows) == 1 and rows[0][2] == env["approx"]["id"] and rows[0][3] == "owner:2:0" and rows[0][4] == "run"
    r = c.post(url(env["approx"]["id"]), json={"decision": "decline"})
    assert r.status_code == 409 and "이미 '시험하기'" in r.json()["detail"]
    assert _digest(env["agents"]) == before                                    # applied later by the agents tick
    o = c.get("/api/lab/intake").json()["owner"]                               # fresh: no 60 s wait for the click
    card = next(x for x in o["cards"] if x["id"] == env["approx"]["id"])
    assert card["decision"]["decision"] == "run" and card["fidelity_ko"] == "근사로 옮김" and card["lost"] == ["EMA 8 → 9"]
    refused = next(x for x in o["cards"] if x["id"] == env["none"]["id"])
    assert refused["stage"]["done"] == ["received", "translated"] and refused["stage"]["now"] is None
    assert o["enabled"] is True and o["limit"] == 3 and o["link_note_ko"].startswith("링크는 열 수 없어요")
    # the agents tick applies it read-only and runs nothing else here
    a = R.open_agents(env["agents"])
    ib = R.open_ro(env["inbox"])
    try:
        got = LI.apply_owner_decisions(a, ib, env["now"] + 1)
        assert got == [{"intake_id": env["approx"]["id"], "decision": "run"}]
        assert LI.latest(a, env["approx"]["id"])["status"] == "queued"
        assert LI.apply_owner_decisions(a, ib, env["now"] + 2) == []             # applied once
    finally:
        a.close()
        ib.close()


# ------------------------------------------------------------------ round 2: 다음 버전 and the goal line
def _round2(env):
    """Lab passes, room what-if tests, settled disputes, debate ideas outside the grammar."""
    now = env["now"]
    a = R.open_agents(env["agents"])
    from paperbot.agents.newlab import describe_ko, normalize_spec
    for i, (sp, st) in enumerate(((NOISE, "failed"), (OTHER, "passed")), 1):
        cs = normalize_spec(sp)
        R.add_trial_with_result(a, LAB, None, "newlab", cs, st, {"description_ko": describe_ko(cs), "test_number": i,
                                                                "ledger": {"checks": {"a": st == "passed"}}}, ts=now - i * 1000)
    for k, (s, tag, good, st) in enumerate(((S, "추세 반대 진입", True, "passed"), ("V45_AMB", "추세 반대 진입", True, "failed"),
                                             ("V45_AMB", "횡보장 진입", False, "failed")), 1):
        spec = {"template": "skip_tag", "timeframe": "1h", "tag": tag, "strategy": s}
        tid = R.add_trial(a, f"strat:{s}", s, "test", spec, ts=now - 10_000 + k)
        p = {"1": {"diff": 0.003 if good else -0.001, "p": 0.001 if good else 0.5, "variant": {"trades": 900}},
             "2": {"diff": 0.002 if good else 0.001, "p": 0.01 if good else 0.4, "variant": {"trades": 400}}}
        R.add_trial_result(a, tid, st, {"result": {"ok": True, "periods": p}, "gate": {"pass": st == "passed"}, "n_trials": 1},
                           ts=now - 9_000 + k)
    for s, kind, win in ((S, "lab", "a"), ("V45_AMB", "lab", "b"), (S, "forward", "a")):
        spec = ({"kind": "lab", "test": {"template": "skip_tag", "timeframe": "1h", "tag": "추세 반대 진입", "strategy": s}}
                if kind == "lab" else {"kind": "forward", "check": "tag_gap", "tag": "추세 반대 진입", "timeframe": None, "n": 30})
        a.execute("INSERT INTO disputes (ts, room_id, strategy, source, claim_ko, side_a, side_b, kind, spec, spec_hash, status, "
                  "winner, outcome, settled_ts, data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (now - 5000, f"strat:{s}", s, "strategy_room", "추세 반대 진입이 손해", "entry_timing", f"spec_{s}", kind,
                   json.dumps(spec, ensure_ascii=False), R.spec_hash(spec), "settled", win, "결과", now - 100, "{}"))
    a.commit()
    a.close()
    deb = env["tmp"] / "debate" / "debate.db"
    os.makedirs(deb.parent)
    d = sqlite3.connect(str(deb))
    DF.ensure(d)
    d.execute("INSERT INTO debate_lab_ideas (round_id, ts, question_ko, engine, claim_ko, check_status, check_ko, queue_status) "
              "VALUES (1, ?, '오늘 손실의 공통점은?', 'none', '펀딩비가 높으면 반대로', 'cannot_express', ?, 'skipped')",
              (now - 300, DF.CHECK_KO["cannot_express"]))
    d.execute("INSERT INTO debate_lab_ideas (round_id, ts, engine, claim_ko, check_status, check_ko, queue_status) "
              "VALUES (2, ?, 'newlab', '좋은 아이디어', 'ok', '시험 후보', 'candidate')", (now - 200,))
    d.commit()
    d.close()
    return str(deb)


def test_the_next_version_views_grade_every_candidate_and_read_only(env):
    deb = _round2(env)
    before, dbefore = _digest(env["agents"]), _digest(deb)
    cands = NV.candidates_view(env["agents"], NV.os.path.join(ROOT, "paperbot", "dash", "data"))
    by = {(r["kind"], r["grade"]) for r in cands["rows"]}
    assert ("newlab", "A") in by and ("roomtest", "B") in by and ("dispute", "C") in by and ("dispute", "D") in by
    assert cands["total"] == 4 and cands["by_grade"] == {"A": 1, "B": 1, "C": 1, "D": 1, "-": 0}
    assert [r["grade"] for r in cands["rows"]] == ["A", "B", "C", "D"]                     # strongest first
    assert cands["disputes"] == {"settled": 3, "attacker": 2, "advocate": 1}
    assert cands["luck"]["newlab"]["tested"] == 2 and cands["luck"]["roomtests"]["tested"] == 3
    regime = next(s for s in cands["studies"] if s["id"] == "regime5y")
    assert regime["grade"] == "-" and "끝까지 남은 칸 0개" in regime["title"] and not regime["candidate"]
    # a study with a gate that nothing passed is '후보 없음', never called descriptive (that is size5y's label only)
    assert regime["grade_ko"] == "후보 없음" and "설명용" not in regime["grade_why"]
    size = next(s for s in cands["studies"] if s["id"] == "size5y")
    assert size["grade"] == "-" and "설명용" in size["title"] and size["grade_ko"] == "등급 없음"
    lab = next(r for r in cands["rows"] if r["kind"] == "dispute" and r["grade"] == "C")
    assert "None" not in lab["title"] and lab["quote"] == "추세 반대 진입이 손해"
    claims = NV.claims_view(env["agents"])
    top = claims["rows"][0]
    assert top["key"] == "skip_tag:추세 반대 진입" and top["claim_ko"] == "'추세 반대 진입' 붙은 진입은 건너뛰는 게 낫다"
    assert (top["tests"], top["held"], top["gate"], top["strategies"]) == (2, 2, 1, 2)
    assert (top["lab_disputes"], top["lab_attacker"], top["fwd_disputes"], top["fwd_attacker"]) == (2, 1, 1, 1)
    assert claims["base"]["tests"] == 3 and claims["base"]["held"] == 2 and claims["base"]["coin_flip"] == 0.5
    cant = NV.cantdo_view(env["agents"], deb)
    srcs = sorted(x["source"] for x in cant["items"])
    assert srcs == ["debate", "owner"] and cant["debate"] == 1 and cant["owner"] == 1
    assert cant["started"] is True                          # the queue ran (its tables) and the factory collected
    owner = next(x for x in cant["items"] if x["source"] == "owner")
    assert owner["reasons_ko"] == [LI.OWNER_REASON_KO["pattern"]] and owner["quote"] == "머리어깨 숏"
    tally = {r["code"]: (r["none"], r["approx"]) for r in cant["by_reason"]}
    assert tally == {"pattern": (1, 0), "param_off_grid": (0, 1)}
    assert _digest(env["agents"]) == before and _digest(deb) == dbefore


def test_the_cantdo_tab_says_not_started_while_no_source_ever_ran(tmp_path):
    """Every source off (the defaults): no queue tables, a classic debate.db with only the empty idea table. The
    answer carries started False (the screen says 모으기 전), never a bare 0개 that reads like a finished count."""
    agents = str(tmp_path / "agents3.db")
    c = R.open_agents(agents)
    R.ensure_rooms(c, ts=1)
    c.close()
    deb = tmp_path / "debate.db"
    d = sqlite3.connect(str(deb))
    DF.ensure(d)
    d.close()
    cant = NV.cantdo_view(agents, str(deb))
    assert cant["started"] is False and cant["total"] == 0
    assert NV.cantdo_view(None, None)["started"] is False
    nv = _read("screens", "nextver.js")
    assert "c.started === false" in nv and "아직 모으기 전입니다" in nv


def test_the_routes_answer_behind_the_login(env):
    _round2(env)
    c = env["client"]
    d = c.get("/api/v4/nextver").json()
    assert set(d) >= {"candidates", "claims", "cantdo", "label"} and d["candidates"]["total"] == 4
    g = c.get("/api/v4/goal").json()
    assert len(g["parts"]) == 3 and g["text_ko"].startswith("오늘 5년 시험") and "운만으로도 많아야" in g["text_ko"]
    anon = TestClient(c.app)
    assert anon.get("/api/v4/nextver").status_code == 401 and anon.get("/api/v4/goal").status_code == 401


def test_the_goal_line_reuses_the_luck_calc_numbers_and_counts_today(env):
    _round2(env)
    a = R.open_ro(env["agents"])
    try:
        g = GL.goal(a, None, None, env["now"])
    finally:
        a.close()
    row = next(r for r in LK.ledger_rows(env["agents"]) if r["id"] == "newlab")
    assert g["newlab"]["tested"] == row["tested"] == 2 and g["newlab"]["passed"] == row["passed"] == 1
    assert g["newlab"]["luck"] == pytest.approx(row["luck"], abs=1e-4) and g["newlab"]["tail"] == pytest.approx(row["tail"], abs=1e-4)
    assert g["tests_today"] == {"tests": 5, "passed": 2, "newlab": 2, "room": 3}
    assert g["parts"][2] == "판정 날짜는 봇이 첫 계좌를 만들면 정해짐"                    # no paper3.db
    assert "0.07개" in g["parts"][1] and "후보 1개" in g["parts"][1]
    # a candidate carries the chance luck alone gives that many (1 - 0.95 x 0.975 = 7.4%): '1 > 0.07' is not 'real'
    assert "운만으로 1개 이상 나올 확률 7%" in g["parts"][1]
    empty = GL.goal(None, None, None, env["now"])
    assert empty["parts"][:2] == ["오늘 5년 시험 0개(통과 0)", "동전보다 나은 새 매매법 후보 0개(아직 새 매매법 시험 없음)"]


def test_the_goal_line_odds_only_with_a_candidate(monkeypatch):
    """No candidate: no odds (nothing to explain); a candidate unlikely by luck says '1% 미만', never 0%."""
    for nl, want in (({"tested": 57, "passed": 0, "luck": 0.2356, "tail": 1.0}, None),
                     ({"tested": 57, "passed": 1, "luck": 0.2356, "tail": 0.2131}, "운만으로 1개 이상 나올 확률 21%"),
                     ({"tested": 57, "passed": 3, "luck": 0.2356, "tail": 0.0013}, "운만으로 3개 이상 나올 확률 1% 미만")):
        monkeypatch.setattr(GL, "newlab_luck", lambda _a, nl=nl: dict(nl))
        p2 = GL.goal(None, None, None, 1_790_000_000_000)["parts"][1]
        assert ("확률" in p2) is (want is not None) and (want is None or want in p2), p2


def test_the_goal_line_never_reads_a_failed_read_as_zero(env):
    """CONTRACT 1.6: a ledger (or paper3.db) that cannot be read says so; it never becomes '0 tests', 'no test yet' or
    'the bot has no account yet' (on 홈 and in the evening Telegram)."""
    bad = sqlite3.connect(":memory:")            # opens, but every query fails (no such table)
    try:
        g = GL.goal(bad, bad, None, env["now"])
    finally:
        bad.close()
    assert g["tests_today"].get("error") and g["newlab"].get("error") and g["verdict"].get("error")
    assert g["parts"] == ["오늘 5년 시험 수는 시험 장부를 읽지 못해 모름", "동전보다 나은 새 매매법 후보 수는 시험 장부를 읽지 못해 모름",
                          "판정 날짜는 계좌 기록을 읽지 못해 모름"]
    assert "0개" not in g["text_ko"] and "없음" not in g["text_ko"] and "정해짐" not in g["text_ko"]


def test_the_verdict_day_follows_the_checkpoint_clock(tmp_path):
    from test_rooms import START, World, kst
    w = World(tmp_path)
    p = w.paper()
    try:
        now = kst(2026, 10, 7, 15, 0)
        v = GL.verdict_day(p, None, now)
        from paperbot.checkpoint import checkpoint_ts
        assert v["k"] == 1 and v["ts"] == checkpoint_ts(START, 1) and v["left"] == GL.days_left(v["ts"], now) > 0
        late = GL.verdict_day(p, None, checkpoint_ts(START, 1) + 3_600_000)
        assert late["k"] == 2 and late["overdue"] is True                            # day passed, no verdict record yet
        assert "첫 판정일 지남" in GL.goal(None, p, None, checkpoint_ts(START, 1) + 3_600_000)["text_ko"]
        # day 180 and later: the rules give no new verdict (checkpoint.NO_VERDICT_DAYS), so no D-day is invented
        from paperbot.checkpoint import NO_VERDICT_DAYS, PERIOD_DAYS
        last = NO_VERDICT_DAYS // PERIOD_DAYS
        before = GL.verdict_day(p, None, checkpoint_ts(START, last) - 3_600_000)
        assert before["k"] == last and not before["ended"]
        after = GL.verdict_day(p, None, checkpoint_ts(START, last) + 3_600_000)
        assert after["ended"] is True and after["ts"] is None and after["left"] is None
        text = GL.goal(None, p, None, checkpoint_ts(START, last) + 3_600_000)["text_ko"]
        assert "판정 기간 끝(180일" in text and "D-" not in text
    finally:
        p.close()


def test_the_evening_telegram_carries_the_line_only_when_switched_on(tmp_path):
    from test_rooms import QUIET, World
    w = World(tmp_path)
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}
    p = w.paper()
    try:
        for on in (False, True):
            ctx = RM.RoundContext(agents_conn=w.agents, paper_ro=p, daily_ro=None, inbox_ro=None, runner=None, lab=None,
                                  now_ms=QUIET, policy=RM.RoomsPolicy(goal_line=on))
            text = RM.compose_evening(ctx, {"today": {"trades": 1, "net_pnl": 1.0}}, lead)
            assert ("🎯 목표 진척도: 오늘 5년 시험 0개" in text) is on
    finally:
        p.close()


# ------------------------------------------------------------------ the screens
def test_the_lab_room_form_and_cards():
    kit = _read("screens", "labreq-kit.js")
    assert 'ctx.post(`/api/rooms/${encodeURIComponent(LAB)}/say`, {lab_request: true, fields})' in kit
    assert "ctx.post(`/api/lab/intake/${encodeURIComponent(c.id)}/decide`, {decision: confirm.dec})" in kit
    for words in ("언제 들어가나", "언제 나오나", "시간봉", "코인", "롱·숏", "링크는 열 수 없어요(에이전트는 인터넷 없음), 규칙을 글로 적어 주세요",
                  "시험하기", "그만두기", "청산은 시험되지 않습니다"):
        assert words in kit, words
    assert "innerHTML" not in kit and "ui.stepStrip(" in kit
    chat = _read("screens", "rooms-chat.js")
    assert 'import {labRequestForm} from "./labreq-kit.js";' in chat and 'ctx.api("/api/lab/intake?limit=1")' in chat
    # CONTRACT 1.7: the form is hidden unless the server says the owners' budget is on (never a dead form while off)
    assert "labForm.hidden = !(owner && owner.enabled);" in chat
    side = _read("screens", "rooms-side.js")
    assert "ownerRequests(ctx, intake && intake.owner" in side
    assert '@import url("labreq-kit.css");' in _read("screens", "rooms.css")


def test_the_goal_line_and_the_next_version_screen():
    home = _read("screens", "home.js")
    assert 'import {goalLine} from "./goal-kit.js";' in home and "goalLine(ctx" in home
    assert '@import url("goal-kit.css");' in _read("screens", "home.css")
    gk = _read("screens", "goal-kit.js")
    assert re.findall(r"[\"'`](/api/[^\"'`]*)", gk) == ["/api/v4/goal"] and 'ctx.href("nextver")' in gk
    nv = _read("screens", "nextver.js")
    assert re.findall(r"[\"'`](/api/[^\"'`]*)", nv) == ["/api/v4/nextver"]
    assert "USDT" not in nv and "fmt.money" not in nv and "export function unmount(" in nv
    routes = _read("core", "routes.js")
    assert 'nextver: {ko: "다음 버전", group: "strat", title: "다음 버전 후보", hidden: true},' in routes
    assert 'ctx.href("nextver")' in _read("screens", "path.js")
    inv = _read("INVENTORY.md")
    assert "#/nextver" in inv and "/api/v4/goal" in inv and "lab_request_decisions" in inv
    from paperbot.dash import more
    assert "nextver" in more.MODULES
