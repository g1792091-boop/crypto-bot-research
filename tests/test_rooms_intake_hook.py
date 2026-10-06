"""The lab intake queue inside the agents tick (rooms.py): the policy and env settings, the hook after the meetings,
the lab packet's 'intake' block and the --debate-db default. Everything is off by default: the tick behaves as before."""

import json
import os
import sqlite3

import pytest

from paperbot.agents import actions as A
from paperbot.agents import labintake as LI
from paperbot.agents import labtests as LT
from paperbot.agents import newlab as NL
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R

from test_labintake import CONTRACT, NOISE, OTHER
from test_newlab import _write
from test_rooms import DAY, HOUR, MIN, NOTE, QUIET, ROOM, SPEC, QueueRunner, World, analysis, challenge


@pytest.fixture(scope="module")
def noise(tmp_path_factory):
    return LT.LabData(_write(str(tmp_path_factory.mktemp("hook_noise")), coins=("BTCUSD", "ETHUSD"), pre=False))


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def debate_db(path, *specs, now=QUIET):
    d = sqlite3.connect(path)
    d.execute(CONTRACT)
    for i, s in enumerate(specs, 1):
        d.execute("INSERT INTO debate_lab_ideas (round_id, ts, engine, strategy, spec_json, claim_ko, pro_ko, con_ko, "
                  "con_check, question_ko, queue_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (10 + i, now - HOUR, "newlab", None, json.dumps(s), f"주장 {i}", "찬성", "반대", "⑥", "질문", "queued"))
    d.commit()
    d.close()
    return path


def meeting_runner():
    return QueueRunner({SPEC: [analysis(NOTE)], "devils_advocate": [challenge("agree")]})


def test_the_default_policy_runs_no_intake_test_and_creates_nothing(world, noise, tmp_path):
    path = debate_db(str(tmp_path / "debate.db"), NOISE)
    world.losses()
    for pol in (RM.RoomsPolicy(debate_db=path), RM.policy_from_env({"AGENTS_DEBATE_DB": path})):
        assert not LI.enabled(pol)
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"],
                  meeting_runner(), lab=noise, policy=RM.RoomsPolicy(), now_ms=QUIET, clock_ms=lambda: QUIET,
                  debate_db=path)
    assert [(r["room_id"], r["status"]) for r in out["rounds"]] == [(ROOM, "done")]
    assert A.newlab_count(world.agents) == 0 and not LI.exists(world.agents)
    assert not any((m["data"] or {}).get("lab_intake") for m in world.messages(R.LAB_ROOM))
    assert R.get_cursor(world.agents, LI.LIMITS_CURSOR) is None


def test_one_debate_test_a_day_runs_after_the_meetings(world, noise, tmp_path):
    path = debate_db(str(tmp_path / "debate.db"), NOISE, OTHER)
    world.losses()
    pol = RM.RoomsPolicy(lab_intake_debate_per_day=1, debate_db=path)
    out = world.tick(meeting_runner(), QUIET, policy=pol, lab=noise)
    assert [(r["room_id"], r["status"]) for r in out["rounds"]] == [(ROOM, "done")]
    assert A.newlab_count(world.agents) == 1                                  # exactly one, counted in the ledger
    cards = LI.view(world.agents, "debate")
    assert sorted(c["status"] for c in cards) == ["queued", "tested"]
    tested = next(c for c in cards if c["status"] == "tested")
    assert tested["source_ref"] == "debate:1" and tested["trial_id"] == R.trial_history(world.agents, kinds=("newlab",))[0]["id"]
    # after the meeting: the intake's lines come after every line of the meeting
    last_meeting = max(m["id"] for m in world.messages(ROOM))
    lab_lines = [m for m in world.messages(R.LAB_ROOM) if m["meeting"] == "lab_intake" or (m["data"] or {}).get("lab_intake")]
    assert lab_lines and min(m["id"] for m in lab_lines) > last_meeting
    assert R.get_cursor(world.agents, LI.LIMITS_CURSOR) == {"debate": 1, "meeting": 0, "owner": 0}
    # the next pass the same day: the budget is used, the other idea waits; nothing is pulled twice
    world.tick(QueueRunner({}), QUIET + 15 * MIN, policy=pol, lab=noise)
    assert A.newlab_count(world.agents) == 1 and len(LI.view(world.agents, "debate")) == 2
    # the lab packet now shows the queue, so the inventor does not propose a waiting spec again
    ctx = RM.RoundContext(agents_conn=world.agents, paper_ro=None, daily_ro=None, inbox_ro=None, runner=None, lab=noise,
                          now_ms=QUIET + 20 * MIN, policy=pol)
    lab = RM.lab_overview(ctx)
    assert lab["intake"]["today"]["debate"] == {"used": 1, "limit": 1}
    assert [q["description_ko"] for q in lab["intake"]["queued"]] == [NL.describe_ko(NL.normalize_spec(OTHER))]
    assert lab["intake"]["recent"][0]["trial_id"] == tested["trial_id"]
    off = RM.RoundContext(agents_conn=world.agents, paper_ro=None, daily_ro=None, inbox_ro=None, runner=None, lab=noise,
                          now_ms=QUIET, policy=RM.RoomsPolicy())
    assert "intake" not in RM.lab_overview(off)                               # off: the packet is as before


def test_a_failing_intake_never_stops_the_tick(world, noise, tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("queue broke")
    monkeypatch.setattr(LI, "run_due", boom)
    world.losses()
    out = world.tick(meeting_runner(), QUIET, policy=RM.RoomsPolicy(lab_intake_debate_per_day=1), lab=noise)
    assert out["rounds"][0]["status"] == "done" and "lab intake failed: RuntimeError" in capsys.readouterr().err


def test_policy_from_env_reads_the_intake_and_sides_settings():
    p = RM.policy_from_env({})
    assert (p.lab_intake_debate_per_day, p.lab_intake_owner_per_day, p.sides, p.dispute_expert) == (0, 0, False, False)
    assert (p.dispute_tests_per_day, p.dispute_room_gap_days, p.debate_db) == (3, 7, "")
    q = RM.policy_from_env({"AGENTS_LAB_INTAKE_DEBATE_PER_DAY": "2", "AGENTS_LAB_INTAKE_OWNER_PER_DAY": "3",
                            "AGENTS_SIDES": "1", "AGENTS_DISPUTE_EXPERT": "0", "AGENTS_DISPUTE_TESTS_PER_DAY": "2",
                            "AGENTS_DISPUTE_ROOM_GAP_DAYS": "5", "AGENTS_DEBATE_DB": " /x/debate.db "})
    assert (q.lab_intake_debate_per_day, q.lab_intake_owner_per_day, q.sides, q.dispute_expert) == (2, 3, True, False)
    assert (q.dispute_tests_per_day, q.dispute_room_gap_days, q.debate_db) == (2, 5, "/x/debate.db")
    assert LI.limits(q) == {"debate": 2, "meeting": 2, "owner": 3}
    with pytest.raises(ValueError, match="하루 2개까지"):
        RM.policy_from_env({"AGENTS_LAB_INTAKE_DEBATE_PER_DAY": "3"})
    for bad in ({"AGENTS_SIDES": "2"}, {"AGENTS_SIDES": "yes"}, {"AGENTS_DISPUTE_EXPERT": "-1"},
                {"AGENTS_LAB_INTAKE_OWNER_PER_DAY": "x"}):
        with pytest.raises(ValueError):
            RM.policy_from_env(bad)


def test_the_env_template_documents_every_new_setting_commented():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = open(os.path.join(here, "deploy", "agents.env.example"), encoding="utf-8").read()
    for name in ("AGENTS_LAB_INTAKE_DEBATE_PER_DAY", "AGENTS_LAB_INTAKE_OWNER_PER_DAY", "AGENTS_DISPUTE_TESTS_PER_DAY",
                 "AGENTS_DISPUTE_ROOM_GAP_DAYS", "AGENTS_SIDES", "AGENTS_DISPUTE_EXPERT", "AGENTS_DEBATE_DB"):
        assert f"\n#{name}=" in env, name
        assert f"\n{name}=" not in env, name
    vals = dict(line[1:].split("=", 1) for line in env.splitlines()
                if line.startswith("#AGENTS_") and "=" in line and line[1:].split("=", 1)[0] in RM.ENV_INTS)
    RM.policy_from_env({k: v for k, v in vals.items() if v})              # the documented values parse
    doc = open(os.path.join(here, "docs", "agent-rooms.md"), encoding="utf-8").read()
    assert "## 시험 대기열" in doc and "AGENTS_LAB_INTAKE_DEBATE_PER_DAY" in doc


def test_main_reads_the_debate_db_next_to_the_agents_db_by_default(tmp_path, monkeypatch):
    seen = {}

    def fake_tick(*a, **k):
        seen.update(k)
        return {"skipped": "test", "rounds": [], "due": []}
    monkeypatch.setattr(RM, "tick", fake_tick)
    monkeypatch.delenv("AGENTS_DEBATE_DB", raising=False)
    args = ["tick", "--paper-db", str(tmp_path / "p.db"), "--daily-db", str(tmp_path / "d.db"),
            "--agents-db", str(tmp_path / "a" / "agents3.db"), "--inbox-db", str(tmp_path / "i.db"), "--dry-run"]
    assert RM.main(args) == 0
    assert seen["debate_db"] == os.path.join(str(tmp_path / "a"), "debate", "debate.db")
    assert RM.main(args + ["--debate-db", "/elsewhere/debate.db"]) == 0 and seen["debate_db"] == "/elsewhere/debate.db"


def test_the_dashboard_reads_the_queue_read_only(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    from test_dash_rooms import _digest

    agents = str(tmp_path / "agents3.db")
    c = R.open_agents(agents)
    R.ensure_rooms(c, ts=QUIET)
    app = create_app(str(tmp_path / "paper3.db"), hash_password("pw pw pw pw"), b"x" * 32, agents_db=agents,
                     inbox_db=str(tmp_path / "inbox.db"))
    client = TestClient(app)
    assert client.get("/api/lab/intake").status_code == 401
    assert client.post("/api/login", json={"password": "pw pw pw pw"}).status_code == 200
    empty = client.get("/api/lab/intake?source=owner").json()                 # before the tables: nothing, no error
    assert empty["cards"] == [] and empty["why_fail"]["tests"] == 0 and empty["today"]["sources"]["debate"]["used"] == 0
    LI.ensure(c)
    R.set_cursor(c, LI.LIMITS_CURSOR, {"debate": 1, "meeting": 0, "owner": 0})
    got = LI.enqueue(c, "debate", "debate:4", "newlab", NOISE, None, "주장", {"round_id": 9}, QUIET)
    LI.enqueue(c, "debate", "debate:5", "newlab", {**NOISE, "timeframe": "5m"}, None, "", {}, QUIET)
    c.close()
    before = _digest(agents)
    d = client.get("/api/lab/intake?source=debate&limit=5").json()
    assert [x["source_ref"] for x in d["cards"]] == ["debate:5", "debate:4"]
    assert d["cards"][1]["id"] == got["id"] and d["cards"][1]["status_ko"] == "대기"
    assert d["cards"][0]["status"] == "refused" and "5분봉" in d["cards"][0]["result_ko"]
    assert d["today"]["sources"]["debate"]["limit"] == 1 and d["status_ko"]["tested"] == "시험함"
    assert client.get("/api/lab/intake?source=friend").status_code == 400
    assert _digest(agents) == before                                          # read-only
