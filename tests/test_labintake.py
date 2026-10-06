"""The shared lab intake queue (paperbot/agents/labintake.py): ideas from the 24-hour debate room, meeting disputes
and the owners' requests become real, counted 5-year tests through actions.newlab_test / request_test (never a side
channel), within daily budgets, de-duplicated against the ledger, and never proposed from here.

The newlab runs use the real engine on small synthetic 4-hour caches (test_newlab.py's writer); the labtest runs use
test_rooms.StubLab (the real templates, spec rules and gate, fixed numbers).
"""

import hashlib
import json
import sqlite3
import time

import pytest

from paperbot.agents import actions as A
from paperbot.agents import labintake as LI
from paperbot.agents import labtests as LT
from paperbot.agents import newlab as NL
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.config import DS200_FAMILY, REEL_NAME
from paperbot.notify import ListNotifier

from test_newlab import _write
from test_rooms import DAY, HOUR, MIN, StubLab, kst

S, S2 = "N17_KC_RSI", "V45_AMB"
ROOM = f"strat:{S}"
NOW = kst(2026, 10, 8, 23, 0)                  # Thursday 23:00 KST
NOISE = {"timeframe": "4h", "entry": {"family": "bb_revert"}, "direction": "both"}
OTHER = {"timeframe": "4h", "entry": {"family": "ema_cross", "params": {"fast": 9, "slow": 21}}}
EDGE = {"timeframe": "4h", "entry": {"family": "volume_spike"}, "direction": "long"}     # passes on `planted`
TAGS = LT.SKIP_TAGS


def skip(tag=TAGS[0], tf="1h"):
    return {"template": "skip_tag", "timeframe": tf, "tag": tag}


@pytest.fixture(scope="module")
def noise(tmp_path_factory):
    return LT.LabData(_write(str(tmp_path_factory.mktemp("li_noise")), coins=("BTCUSD", "ETHUSD"), pre=False))


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    return LT.LabData(_write(str(tmp_path_factory.mktemp("li_planted")), events=True))


@pytest.fixture
def conn(tmp_path):
    c = R.open_agents(str(tmp_path / "agents3.db"))
    R.ensure_rooms(c, ts=NOW - DAY)
    LI.ensure(c)
    yield c
    c.close()


@pytest.fixture
def stub(monkeypatch):
    lab = StubLab(good=False)
    monkeypatch.setattr(A, "_lab", lab)
    return lab


def make_ctx(conn, lab, now=NOW, notifier=None, **pol):
    return RM.RoundContext(agents_conn=conn, paper_ro=None, daily_ro=None, inbox_ro=None, runner=None, lab=lab,
                           now_ms=now, policy=RM.RoomsPolicy(**pol), notifier=notifier or ListNotifier(),
                           clock_ms=lambda: now)


def debate(conn, ref, engine, spec, strategy=None, now=NOW - HOUR, **meta):
    return LI.enqueue(conn, "debate", f"debate:{ref}", engine, spec, strategy, f"아이디어 {ref}",
                      {"round_id": 7, "origin_ts": now, **meta}, now)


def status(conn, iid):
    return LI.latest(conn, iid)


def messages(conn, room):
    return R.room_messages(conn, room, limit=500)


# ------------------------------------------------------------------ storage
def test_both_tables_are_append_only_and_checked(conn):
    got = debate(conn, 1, "newlab", NOISE)
    LI.event(conn, got["id"], "expired", NOW)
    for sql in ("UPDATE lab_intake SET description_ko = 'x'", "DELETE FROM lab_intake",
                "UPDATE lab_intake_events SET status = 'tested'", "DELETE FROM lab_intake_events"):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql)
        conn.rollback()
    with pytest.raises(sqlite3.DatabaseError):            # the CHECK holds too (not swallowed by the upsert)
        conn.execute("INSERT INTO lab_intake (ts, source, source_ref, room_id, engine, spec, spec_hash, description_ko) "
                     "VALUES (1, 'friend', 'x', 'team:lab', 'newlab', '{}', 'h', 'd')")
    conn.rollback()
    with pytest.raises(ValueError):
        LI.enqueue(conn, "friend", "x:1", "newlab", NOISE)
    with pytest.raises(ValueError):
        LI.event(conn, got["id"], "maybe", NOW)
    assert [r[0] for r in conn.execute("SELECT status FROM lab_intake_events ORDER BY id")] == ["queued", "expired"]


def test_enqueue_is_idempotent_and_remakes_the_spec_in_code(conn):
    raw = {"timeframe": "4H", "entry": {"family": "EMA_CROSS", "params": {"fast": 9.0, "slow": 21}}, "name": "모델 이름"}
    a = debate(conn, 5, "newlab", raw)
    b = debate(conn, 5, "newlab", NOISE)                      # same source_ref: nothing new, the first one stays
    assert a == {"id": a["id"], "status": "queued", "created": True}
    assert b == {"id": a["id"], "status": "queued", "created": False}
    row = status(conn, a["id"])
    assert row["spec"] == NL.normalize_spec(OTHER) and row["spec_hash"] == NL.spec_hash(NL.normalize_spec(OTHER))
    assert row["description_ko"] == NL.describe_ko(NL.normalize_spec(OTHER)) and row["room_id"] == R.LAB_ROOM
    assert row["idea_ko"] == "아이디어 5" and row["meta"]["round_id"] == 7 and row["strategy"] is None
    assert conn.execute("SELECT COUNT(*) FROM lab_intake").fetchone()[0] == 1
    t = LI.enqueue(conn, "meeting", "dispute:3", "labtest", {**skip(), "strategy": S}, None, "말", {"by_role": "whatif"})
    trow = status(conn, t["id"])
    assert trow["room_id"] == ROOM and trow["strategy"] == S and trow["spec"]["strategy"] == S
    assert trow["spec_hash"] == R.spec_hash(LT.normalize_spec(skip(), S))      # the hash find_trial uses


def test_5m_timeframe_only_and_names_outside_the_36_are_refused(conn):
    bad = [("newlab", {**NOISE, "timeframe": "5m"}, None, "refused", "5분봉"),
           ("labtest", skip(tf="5m"), S, "refused", "5분봉"),
           ("labtest", {"template": "timeframe_only"}, S, "refused", "설명용"),
           ("labtest", skip(), "RANDOM_1", "refused", "36개만"),
           ("labtest", skip(), next(iter(DS200_FAMILY)), "refused", "36개만"),
           ("labtest", skip(), REEL_NAME, "refused", "36개만"),
           ("labtest", {**skip(), "tag": "아무 태그"}, S, "bad_spec", "tag"),
           ("newlab", {**NOISE, "exit": "tp2"}, None, "bad_spec", "청산"),
           ("newlab", "not json", None, "bad_spec", "JSON"),
           ("none", {}, None, "bad_spec", "engine")]
    for i, (engine, spec, s, want, word) in enumerate(bad):
        got = debate(conn, 100 + i, engine, spec, s)
        assert got["status"] == want and word in got["why"], (engine, spec, got)
        row = status(conn, got["id"])
        assert row["description_ko"].startswith("(시험 안 함)") and LI.result_ko(row["detail"], want).startswith(
            LI.STATUS_KO[want])
    # none of them is ever run
    ctx = make_ctx(conn, None, lab_intake_debate_per_day=2)
    out = LI.run_due(ctx, NOW)
    assert out["ran"] == [] and A.newlab_count(conn) == 0 and R.trial_count(conn) == 0


# ------------------------------------------------------------------ the debate's hand-off
CONTRACT = ("CREATE TABLE debate_lab_ideas (id INTEGER PRIMARY KEY AUTOINCREMENT, round_id INTEGER NOT NULL, "
            "ts INTEGER NOT NULL, engine TEXT NOT NULL, strategy TEXT, spec_json TEXT, claim_ko TEXT, pro_ko TEXT, "
            "con_ko TEXT, con_check TEXT, question_ko TEXT, queue_status TEXT NOT NULL DEFAULT 'candidate')")


def debate_db(path, rows):
    d = sqlite3.connect(path)
    d.execute("PRAGMA journal_mode=DELETE")
    d.execute(CONTRACT)
    for r in rows:
        d.execute("INSERT INTO debate_lab_ideas (round_id, ts, engine, strategy, spec_json, claim_ko, pro_ko, con_ko, "
                  "con_check, question_ko, queue_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)", r)
    d.commit()
    d.close()
    return path


def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_pull_debate_reads_the_contract_read_only_and_is_idempotent(conn, tmp_path):
    rows = [(3, NOW - HOUR, "newlab", None, json.dumps(NOISE), "주장", "찬성 근거", "반대 근거", "⑥", "질문", "queued"),
            (4, NOW - HOUR, "labtest", S, json.dumps(skip()), "건너뛰면 덜 잃음", "p", "c", "①", "q", "queued"),
            (5, NOW - HOUR, "newlab", None, json.dumps({**NOISE, "timeframe": "5m"}), "5분", "", "", "", "", "queued"),
            (6, NOW - HOUR, "newlab", None, json.dumps(OTHER), "후보", "", "", "", "", "candidate"),     # not picked
            (7, NOW - 4 * DAY, "newlab", None, json.dumps(OTHER), "옛 것", "", "", "", "", "queued")]   # too old
    path = debate_db(str(tmp_path / "debate.db"), rows)
    before = digest(path)
    ctx = make_ctx(conn, None, lab_intake_debate_per_day=1)
    assert LI.pull_debate(ctx, path, NOW) == 3
    assert LI.pull_debate(ctx, path, NOW) == 0                                 # idempotent, no cursor needed
    assert digest(path) == before                                              # never written
    cards = {c["source_ref"]: c for c in LI.view(conn, "debate")}
    assert set(cards) == {"debate:1", "debate:2", "debate:3"}
    assert cards["debate:1"]["status"] == "queued" and cards["debate:1"]["meta"]["con_check"] == "⑥"
    assert cards["debate:1"]["meta"]["question_ko"] == "질문" and cards["debate:1"]["idea_ko"] == "주장"
    assert cards["debate:2"]["room_id"] == ROOM and cards["debate:2"]["engine_ko"] == "5년 시험·36개 고쳐 보기"
    assert cards["debate:3"]["status"] == "refused"                            # debate.db is never trusted
    # a missing file, a missing table, no path: nothing (tried again next pass)
    empty = str(tmp_path / "empty.db")
    sqlite3.connect(empty).execute("CREATE TABLE other (x)").connection.close()
    assert LI.pull_debate(ctx, empty, NOW) == 0
    assert LI.pull_debate(ctx, str(tmp_path / "nope.db"), NOW) == 0 and LI.pull_debate(ctx, "", NOW) == 0


# ------------------------------------------------------------------ counted runs
def test_a_newlab_run_is_counted_in_the_ledger_and_a_repeat_is_free(conn, noise):
    note = ListNotifier()
    ctx = make_ctx(conn, noise, notifier=note, lab_intake_debate_per_day=1)
    first = debate(conn, 1, "newlab", NOISE, question_ko="오늘 가장 크게 잃은 거래")
    out = LI.run_due(ctx, NOW)
    assert out["ran"] == [first["id"]] and A.newlab_count(conn) == 1
    row = status(conn, first["id"])
    [t] = R.trial_history(conn, kinds=("newlab",))
    assert row["status"] == "tested" and row["trial_id"] == t["id"] and t["room_id"] == R.LAB_ROOM
    assert t["spec_hash"] == row["spec_hash"] and t["result"]["status"] == "failed"
    body = t["result"]["result"]
    assert body["notes"]["idea"].startswith("[토론방 #1(회차 7)]") and body["test_number"] == 1
    d = row["detail"]
    assert d["engine"] == "newlab" and d["verdict"] == "failed" and d["test_number"] == 1 and d["n_before"] == 0
    assert d["threshold"] == pytest.approx(0.05) and d["failed_checks"] and set(d["checks"]) == set("abcdef")
    assert LI.result_ko(d, "tested").startswith("불통과: ") and "새 매매법 시험 #1, 기준 p<0.05" in LI.result_ko(d, "tested")
    msgs = messages(conn, R.LAB_ROOM)
    ann = next(m for m in msgs if (m["data"] or {}).get("lab_intake") == first["id"])
    assert ann["kind"] == "system" and ann["role"] == "code" and "🗣️ 24시간 토론방 아이디어 #1(회차 7)" in ann["text"]
    assert "오늘 토론방 몫 1/1" in ann["text"] and NL.describe_ko(NL.normalize_spec(NOISE)) in ann["text"]
    assert "아이디어 1" not in ann["text"]                                       # never the model's words as code
    res = next(m for m in msgs if m["kind"] == "code_result")
    assert res["id"] > ann["id"] and res["data"]["trial_id"] == t["id"]
    assert note.messages == [] and R.list_proposals(conn) == []
    # the same spec again (another idea), with today's budget used up: answered at once from the ledger, not run,
    # not counted, outside the budget
    again = debate(conn, 2, "newlab", NOISE)
    out = LI.run_due(ctx, NOW + 10 * MIN)
    assert out["free"] == [again["id"]] and out["ran"] == []
    dup = status(conn, again["id"])
    assert dup["status"] == "duplicate" and dup["trial_id"] == t["id"] and A.newlab_count(conn) == 1
    assert dup["detail"]["verdict"] == "failed" and LI.result_ko(dup["detail"], "duplicate").startswith("이미 시험함 · 불통과")
    assert LI.used_today(conn, "debate", NOW) == 1
    # why it failed: the board counts the stored checks
    wf = LI.why_fail(conn)
    assert wf["tests"] == 1 and sum(wf["failed"].values()) == len(d["failed_checks"]) and "미달" in wf["text_ko"]


def test_a_labtest_run_is_counted_in_its_room_and_an_identical_trial_is_reused(conn, stub, noise):
    ctx = make_ctx(conn, noise, lab_intake_debate_per_day=1)
    a = debate(conn, 1, "labtest", skip(TAGS[0]), S)
    out = LI.run_due(ctx, NOW)
    assert out["ran"] == [a["id"]] and R.trial_count(conn, room_id=ROOM) == 1 and len(stub.runs) == 1
    row = status(conn, a["id"])
    assert row["status"] == "tested" and row["detail"]["engine"] == "labtest" and row["detail"]["verdict"] == "failed"
    assert row["detail"]["n_trials"] == 1 and "이 방 시험 1번째" in LI.result_ko(row["detail"], "tested")
    assert any((m["data"] or {}).get("lab_intake") == a["id"] for m in messages(conn, ROOM))
    # an identical test stored earlier (another tag, final result): reused for free, outside the used-up budget
    old_spec = LT.normalize_spec(skip(TAGS[1]), S)
    tid = R.add_trial(conn, ROOM, S, "test", old_spec, ts=NOW - DAY)
    R.add_trial_result(conn, tid, "failed", {"result": None, "gate": {"pass": False, "reasons": ["예전"]}, "n_trials": 1},
                       ts=NOW - DAY)
    b = debate(conn, 2, "labtest", skip(TAGS[1]), S)
    c = debate(conn, 3, "labtest", skip(TAGS[2]), S)                           # a new one: waits for tomorrow
    out = LI.run_due(ctx, NOW + MIN)
    assert out["free"] == [b["id"]] and out["ran"] == []
    assert status(conn, b["id"])["status"] == "reused" and status(conn, b["id"])["trial_id"] == tid
    assert status(conn, c["id"])["status"] == "queued"
    assert R.trial_count(conn, room_id=ROOM) == 2 and len(stub.runs) == 1          # the reuse ran nothing
    assert LI.used_today(conn, "debate", NOW) == 1


def test_the_debate_budget_of_one_a_day_holds_across_kst_midnight(conn, stub, noise):
    ids = [debate(conn, i, "labtest", skip(TAGS[i]), S)["id"] for i in range(3)]
    ctx = make_ctx(conn, noise, lab_intake_debate_per_day=1)
    assert LI.run_due(ctx, NOW)["ran"] == [ids[0]]
    late = make_ctx(conn, noise, now=NOW + 50 * MIN, lab_intake_debate_per_day=1)       # 23:50 KST, same day
    assert LI.run_due(late, NOW + 50 * MIN)["ran"] == []
    tomorrow = kst(2026, 10, 9, 0, 10)
    nxt = make_ctx(conn, noise, now=tomorrow, lab_intake_debate_per_day=1)
    assert LI.run_due(nxt, tomorrow)["ran"] == [ids[1]]
    assert LI.used_today(conn, "debate", tomorrow) == 1 and LI.used_today(conn, "debate", NOW) == 1
    assert status(conn, ids[2])["status"] == "queued" and R.trial_count(conn, room_id=ROOM) == 2
    # a value above the hard maximum of 2 is still 2
    assert LI.limits(RM.RoomsPolicy(lab_intake_debate_per_day=5))["debate"] == 2


def test_a_test_that_runs_past_midnight_counts_in_the_new_day_and_the_pass_stops(conn, stub, noise):
    """The budget's day is the day a test starts by the clock: a pass that began at 23:59 and whose first test ended
    after midnight must not start a second test 'for yesterday' (both would land in the new day: 2 of 1)."""
    ids = [debate(conn, i, "labtest", skip(TAGS[i]), S)["id"] for i in range(3)]
    late = kst(2026, 10, 8, 23, 59)
    clock = {"t": late}
    ctx = make_ctx(conn, noise, now=late, lab_intake_debate_per_day=1)
    ctx.clock_ms = lambda: clock["t"]
    run = stub.run_test

    def slow(*a, **k):
        clock["t"] += 2 * MIN                          # this 5-year test ends at 00:01
        return run(*a, **k)
    stub.run_test = slow
    out = LI.run_due(ctx, late)
    assert out["ran"] == [ids[0]] and len(stub.runs) == 1
    tomorrow = kst(2026, 10, 9, 9, 0)
    assert LI.used_today(conn, "debate", tomorrow) == 1                   # it counts in the day it ended
    assert LI.run_due(make_ctx(conn, noise, now=tomorrow, lab_intake_debate_per_day=1), tomorrow)["ran"] == []
    assert R.trial_count(conn, room_id=ROOM) == 1


def test_a_labtest_that_errors_keeps_its_number_and_costs_the_budget(conn, stub, noise):
    """request_test numbers a trial before it runs and keeps the number when the run fails: that trial is in the
    room's n (the Bonferroni divisor), so it costs the daily budget, and the line never says it was not counted."""
    ids = [debate(conn, i, "labtest", skip(TAGS[i]), S)["id"] for i in range(3)]

    def boom(*a, **k):
        raise RuntimeError("bad cache")
    stub.run_test = boom
    out = LI.run_due(make_ctx(conn, noise, lab_intake_debate_per_day=1), NOW)
    assert out["ran"] == [ids[0]] and R.trial_count(conn, room_id=ROOM) == 1       # one number, not one per row
    row = status(conn, ids[0])
    assert row["status"] == "error" and row["trial_id"] is not None and row["detail"]["numbered"] is True
    line = LI.result_ko(row["detail"], row["status"], row["trial_id"])
    assert f"장부 #{row['trial_id']}에 번호가 남아" in line and "시험 수에 넣지 않음" not in line
    assert LI.used_today(conn, "debate", NOW) == 1 and status(conn, ids[1])["status"] == "queued"
    # a meeting dispute's error also holds its room for the gap
    m = LI.enqueue(conn, "meeting", "dispute:1", "labtest", skip(TAGS[3]), S, "", {}, NOW - HOUR)
    m2 = LI.enqueue(conn, "meeting", "dispute:2", "labtest", skip(TAGS[4]), S, "", {}, NOW - HOUR)
    out = LI.run_due(make_ctx(conn, noise, sides=True), NOW)
    assert out["ran"] == [m["id"]] and status(conn, m2["id"])["status"] == "queued"
    # an exception that escapes after the trial was numbered is still marked (the number is in the room's n)
    def numbered_then_raise(env, a):
        R.add_trial(env.conn, env.room_id, env.strategy, "test", {**a["test"], "strategy": env.strategy},
                    ts=env.now_ms)
        raise sqlite3.OperationalError("disk I/O error")
    import unittest.mock as um
    with um.patch.object(A, "request_test", numbered_then_raise):
        out = LI.run_due(make_ctx(conn, noise, now=NOW + DAY, lab_intake_debate_per_day=1), NOW + DAY)
    got = status(conn, out["ran"][0])
    assert got["status"] == "error" and got["trial_id"] is not None and got["detail"]["numbered"] is True
    # an error before any number (no trial row): nothing in the room's n, the line says so
    assert LI.result_ko({"error": "x"}, "error").startswith("오류: 시험 수에 넣지 않음")


def test_lab_blocked_and_the_wall_time_keep_rows_queued(conn, stub, noise, monkeypatch):
    n = debate(conn, 1, "newlab", NOISE)
    t = debate(conn, 2, "labtest", skip(), S)
    out = LI.run_due(make_ctx(conn, None, lab_intake_debate_per_day=2), NOW)      # no 5-year cache on this server
    assert out["blocked"] == "no_data" and out["ran"] == []
    assert status(conn, n["id"])["status"] == "queued" and status(conn, t["id"])["status"] == "queued"
    today = LI.today(conn, NOW, {"debate": 2})
    assert today["blocked"]["why"] == "no_data" and "5년 시험 자료" in today["blocked_ko"]
    assert today["sources"]["debate"] == {"source_ko": "토론방", "used": 0, "limit": 2, "waiting": 2}
    # the tick's wall time: no test starts that could outlive the pass
    ctx = make_ctx(conn, noise, lab_intake_debate_per_day=2)
    ctx.cache["tick_t0"] = time.monotonic() - ctx.policy.tick_wall_s
    out = LI.run_due(ctx, NOW)
    assert out["stopped"] == "tick_wall" and out["ran"] == [] and status(conn, n["id"])["status"] == "queued"
    # no new-strategy test can pass any more: the newlab row waits, the labtest runs
    monkeypatch.setattr(A, "newlab_exhausted", lambda c: True)
    out = LI.run_due(make_ctx(conn, noise, lab_intake_debate_per_day=2), NOW)
    assert out["blocked"] == "exhausted" and out["ran"] == [t["id"]] and status(conn, n["id"])["status"] == "queued"
    assert A.newlab_count(conn) == 0 and R.get_cursor(conn, LI.BLOCKED_CURSOR)["why"] == "exhausted"


def test_a_killed_running_row_is_recovered_and_debate_rows_expire(conn):
    lost = debate(conn, 1, "newlab", NOISE)
    LI.event(conn, lost["id"], "running", NOW - 10 * MIN)
    done = debate(conn, 2, "labtest", skip(), S)
    LI.event(conn, done["id"], "running", NOW - 10 * MIN)
    tid = R.add_trial(conn, ROOM, S, "test", LT.normalize_spec(skip(), S), ts=NOW - 9 * MIN)
    R.add_trial_result(conn, tid, "failed", {"result": None, "gate": {"pass": False, "checks": {"a": False}}, "n_trials": 1},
                       ts=NOW - 8 * MIN)
    old = debate(conn, 3, "newlab", OTHER)
    oid = R.add_trial_with_result(conn, R.LAB_ROOM, None, "newlab", NL.normalize_spec(OTHER), "failed",
                                  {"test_number": 1, "gate": {"checks": {"f": False}}}, ts=NOW - DAY)
    LI.event(conn, old["id"], "running", NOW - 10 * MIN)
    assert LI.reconcile(conn, NOW) == 3
    assert status(conn, lost["id"])["status"] == "queued"
    got = status(conn, done["id"])
    assert got["status"] == "tested" and got["trial_id"] == tid and got["detail"]["reconciled"] is True
    dup = status(conn, old["id"])
    assert dup["status"] == "duplicate" and dup["trial_id"] == oid
    assert LI.reconcile(conn, NOW) == 0
    # 72 hours after the idea a queued debate row expires (a meeting dispute waits 14 days)
    stale = debate(conn, 4, "labtest", skip(TAGS[3]), S, now=NOW - 73 * HOUR)
    fresh = debate(conn, 5, "labtest", skip(TAGS[4]), S, now=NOW - 71 * HOUR)
    meet = LI.enqueue(conn, "meeting", "dispute:1", "labtest", skip(TAGS[5]), S, "", {}, NOW - 73 * HOUR)
    out = LI.run_due(make_ctx(conn, None, lab_intake_debate_per_day=1), NOW)
    assert stale["id"] in out["expired"] and fresh["id"] not in out["expired"] and meet["id"] not in out["expired"]
    assert status(conn, stale["id"])["status"] == "expired"
    assert LI.result_ko({}, "expired").startswith("기한 지남")


def test_run_due_never_proposes_even_a_pass(conn, planted, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("labintake must never propose")
    monkeypatch.setattr(A, "newlab_propose", boom)
    note = ListNotifier()
    ctx = make_ctx(conn, planted, notifier=note, lab_intake_debate_per_day=1)
    got = debate(conn, 1, "newlab", EDGE)
    out = LI.run_due(ctx, NOW)
    assert out["ran"] == [got["id"]]
    row = status(conn, got["id"])
    assert row["status"] == "tested" and row["detail"]["verdict"] == "passed" and row["detail"]["failed_checks"] == []
    assert R.get_trial(conn, row["trial_id"])["result"]["status"] == "passed"     # waits in the ledger
    assert R.list_proposals(conn) == [] and note.messages == []
    line = LI.result_ko(row["detail"], "tested")
    assert line.startswith("통과: ①~⑥ 모두") and "두 분 확인 필요" in line


# ------------------------------------------------------------------ sources, budgets, priority
def test_owner_requests_exact_approx_none_and_the_owners_click(conn):
    ex = LI.enqueue_owner(conn, 41, 0, {"engine": "newlab", "spec": NOISE, "entry_fidelity": "exact",
                                       "idea": "영상의 볼린저 되돌림"}, NOW)
    ap = LI.enqueue_owner(conn, 41, 1, {"engine": "labtest", "test": skip(), "strategy": S, "entry_fidelity": "approx",
                                       "kept": ["추세 반대 진입 건너뛰기"], "lost": ["RSI 25 → 30"],
                                       "reason_codes": ["param_off_grid", "made_up_code"]}, NOW)
    no = LI.enqueue_owner(conn, 42, 0, {"engine": "none", "entry_fidelity": "none",
                                       "reason_codes": ["pattern", "exit_rule"]}, NOW)
    assert (ex["status"], ap["status"], no["status"]) == ("queued", "needs_owner_ok", "refused")
    e, a, n = status(conn, ex["id"]), status(conn, ap["id"]), status(conn, no["id"])
    assert e["source_ref"] == "owner:41:0" and e["room_id"] == R.LAB_ROOM and e["meta"]["exits_ko"] == LI.OWNER_EXITS_KO
    assert a["room_id"] == ROOM and a["meta"]["kept"] == ["추세 반대 진입 건너뛰기"] and a["meta"]["lost"] == ["RSI 25 → 30"]
    assert a["meta"]["reason_codes"] == ["param_off_grid"] and a["meta"]["fidelity"] == "approx"
    assert LI.OWNER_REASON_KO["pattern"] in n["detail"]["why"] and LI.NOT_TESTED_KO in n["detail"]["why"]
    assert a["status"] == "needs_owner_ok" and LI.STATUS_KO[a["status"]] == "두 분 확인 필요"
    assert LI.decide(conn, ap["id"], "maybe") is False and LI.decide(conn, no["id"], "run") is False
    assert LI.decide(conn, ap["id"], "run", NOW, "owner1") is True and status(conn, ap["id"])["status"] == "queued"
    assert LI.decide(conn, ap["id"], "decline") is False                     # already decided
    other = LI.enqueue_owner(conn, 43, 0, {"engine": "newlab", "spec": OTHER, "entry_fidelity": "approx"}, NOW)
    assert LI.decide(conn, other["id"], "decline", NOW) is True and status(conn, other["id"])["status"] == "declined"
    assert LI.enqueue_owner(conn, 41, 0, {"engine": "newlab", "spec": OTHER, "entry_fidelity": "exact"}, NOW)["created"] is False


def test_owner_first_then_the_meeting_then_the_debate_each_in_its_own_budget(conn, stub, noise):
    d = debate(conn, 1, "labtest", skip(TAGS[0]), S)
    o = LI.enqueue_owner(conn, 9, 0, {"engine": "labtest", "test": skip(TAGS[1]), "strategy": S,
                                      "entry_fidelity": "exact"}, NOW - HOUR)
    m = LI.enqueue(conn, "meeting", "dispute:1", "labtest", skip(TAGS[2]), S2, "", {"by_role": "whatif"}, NOW - HOUR)
    # the owners' source is off: their row waits, the others run in priority order
    ctx = make_ctx(conn, noise, lab_intake_debate_per_day=1, sides=True)
    out = LI.run_due(ctx, NOW, max_per_pass=1)
    assert out["ran"] == [m["id"]] and out["stopped"] == "max_per_pass"
    out = LI.run_due(make_ctx(conn, noise, lab_intake_debate_per_day=1, lab_intake_owner_per_day=1, sides=True), NOW)
    assert out["ran"] == [o["id"], d["id"]]
    assert {status(conn, x["id"])["status"] for x in (o, m, d)} == {"tested"}
    # the meeting's test ran as the attacker's proposal in its own room
    tr = R.trial_history(conn, room_id=f"strat:{S2}")
    assert len(tr) == 1 and R.trial_count(conn, room_id=f"strat:{S2}") == 1
    assert any((m2["data"] or {}).get("lab_intake") == m["id"] and "⚔️ 회의 다툼 #1" in m2["text"]
               for m2 in messages(conn, f"strat:{S2}"))


def test_meeting_disputes_one_counted_test_per_room_per_gap_and_off_without_sides(conn, stub, noise):
    a = LI.enqueue(conn, "meeting", "dispute:1", "labtest", skip(TAGS[0]), S, "", {}, NOW - HOUR)
    b = LI.enqueue(conn, "meeting", "dispute:2", "labtest", skip(TAGS[1]), S, "", {}, NOW - HOUR)
    c = LI.enqueue(conn, "meeting", "dispute:3", "labtest", skip(TAGS[2]), S2, "", {}, NOW - HOUR)
    assert LI.run_due(make_ctx(conn, noise), NOW)["ran"] == []                 # sides off: the source is off
    out = LI.run_due(make_ctx(conn, noise, sides=True, dispute_tests_per_day=3, dispute_room_gap_days=7), NOW)
    assert out["ran"] == [a["id"], c["id"]] and status(conn, b["id"])["status"] == "queued"
    later = NOW + 8 * DAY
    out = LI.run_due(make_ctx(conn, noise, now=later, sides=True), later)
    assert out["ran"] == [b["id"]]


def test_tick_does_nothing_while_every_source_is_off(tmp_path, noise):
    c = R.open_agents(str(tmp_path / "agents3.db"))
    try:
        assert LI.tick(make_ctx(c, noise), str(tmp_path / "debate.db"), NOW) == {"enabled": False}
        assert not LI.exists(c) and LI.view(c) == [] and LI.why_fail(c)["tests"] == 0
        assert R.get_cursor(c, LI.LIMITS_CURSOR) is None
        on = LI.tick(make_ctx(c, noise, lab_intake_owner_per_day=2), None, NOW)
        assert on["enabled"] is True and on["pulled"] == 0 and LI.exists(c)
        assert R.get_cursor(c, LI.LIMITS_CURSOR) == {"debate": 0, "meeting": 0, "owner": 2}
        assert LI.today(c, NOW)["sources"]["owner"]["limit"] == 2
    finally:
        c.close()


def test_result_lines_are_code_text_from_the_numbers():
    d = {"engine": "newlab", "verdict": "failed", "test_number": 57, "threshold": 0.05 / 57,
         "failed_checks": ["①", "⑥"], "passed_checks": ["②", "③", "④", "⑤"],
         "p1": {"mean_roe": -0.0011, "p": 0.64, "coinflip_diff": 0.0002, "coinflip_p": 0.41}}
    line = LI.result_ko(d, "tested")
    assert line == ("불통과: ① 1기간 거래당 -0.11%(p=0.64) · ⑥ 동전과 차이 1기간 +0.02%p(p=0.41) · 통과한 칸 ②③④⑤ "
                    "(새 매매법 시험 #57, 기준 p<0.00088)")
    lt = {"engine": "labtest", "verdict": "failed", "n_trials": 5, "threshold": 0.01, "failed_checks": ["①"],
          "passed_checks": ["③"], "p1": {"diff": 0.0031, "p": 0.21}}
    assert LI.result_ko(lt, "reused", 41) == ("이전 결과 재사용 · 불통과: ① 1기간 개선 +0.31%p(p=0.21) · 통과한 칸 ③ "
                                             "(이 방 시험 5번째, 기준 p<0.01, 장부 #41)")
    assert LI.result_ko({"why": "no_data"}, "not_counted").startswith("시험 수에 안 넣음")
    assert LI.result_ko({}, "declined").startswith("두 분이 그만")
