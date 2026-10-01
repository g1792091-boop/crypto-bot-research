"""The new-strategy lab room (team:lab): rooms.py ``_lab_round`` + actions.py ``newlab_*`` + the 'research'
trigger and budget class, on the real newlab engine with small synthetic 4-hour caches (test_newlab.py's
writer: a planted edge that passes the gate, and noise that fails it). A scripted runner answers for the
researcher (inventor), the devil's advocate (skeptic) and the lead.
"""

import json
import os

import pytest

from paperbot.agents import actions as A
from paperbot.agents import labtests as LT
from paperbot.agents import newlab as NL
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.agents import triggers as TR
from paperbot.notify import WARN, ListNotifier

from test_newlab import _write
from test_rooms import DAY, HOUR, MIN, QUIET, QueueRunner, World, kst

LAB = "team:lab"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = {"timeframe": "4h", "entry": {"family": "volume_spike"}, "direction": "long"}      # passes on `planted`
NOISE = {"timeframe": "4h", "entry": {"family": "bb_revert"}, "direction": "both"}
OTHER = {"timeframe": "4h", "entry": {"family": "ema_cross", "params": {"fast": 9, "slow": 21}}}
BAD = {"timeframe": "4h", "entry": {"family": "psar_flip"}, "exit": "tp2"}                # exits are not choosable


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    return LT.LabData(_write(str(tmp_path_factory.mktemp("lab_planted")), events=True))


@pytest.fixture(scope="module")
def noise(tmp_path_factory):
    return LT.LabData(_write(str(tmp_path_factory.mktemp("lab_noise")), coins=("BTCUSD", "ETHUSD"), pre=False))


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def lab_policy(**kw):
    p = RM.RoomsPolicy(**kw)
    p.triggers.research_every_ms = HOUR
    return p


def inventor(*specs, headline="새 후보"):
    return {"headline": headline, "specs": [{"spec": s, "idea": f"아이디어 {i}", "why_new": "필터와 방향이 다름"}
                                            for i, s in enumerate(specs, 1)]}


def skeptic(*drop, keep_all=True):
    return lambda pk: {"headline": "검토", "reviews": [{"index": c["index"], "keep": c["index"] not in drop,
                                                        "reason": "비슷한 실패작" if c["index"] in drop else "새로움"}
                                                       for c in pk["candidates"]]}


LEAD = {"summary": ["이번 회의 요약"], "next_time": []}


def canon(spec):
    return NL.normalize_spec(spec)


def stored(world):
    return R.trial_history(world.agents, kinds=("newlab",), limit=100)[::-1]


def add_other_room_test(world, spec=OTHER, room="team:elsewhere"):
    """A counted lab test made in another room: the gate's n is global."""
    c = canon(spec)
    return R.add_trial_with_result(world.agents, room, None, "newlab", c, "failed",
                                   {"n_tests_so_far": 0, "test_number": 1, "gate_input": {}, "summary_ko": "예전 시험"},
                                   ts=QUIET - DAY)


# ------------------------------------------------------------------ the meeting
def test_lab_meeting_tests_new_specs_handles_bad_and_duplicate_and_counts_globally(world, planted):
    other = add_other_room_test(world)
    runner = QueueRunner({"researcher": [inventor(EDGE, BAD, OTHER)], "devils_advocate": [skeptic()],
                          "team_lead": [LEAD]})
    note = ListNotifier()
    out = world.tick(runner, QUIET, policy=lab_policy(), lab=planted, notifier=note)
    assert [(r["room_id"], r["trigger"], r["status"]) for r in out["rounds"]] == [(LAB, "research", "done")]
    assert runner.roles() == ["researcher", "devils_advocate", "team_lead"]
    assert [c["model"] for c in runner.calls] == ["sonnet"] * 3              # every lab turn is sonnet
    assert [c["turn"] for c in runner.calls] == ["lab_inventor", "lab_skeptic", "lab_lead"]
    # the inventor's packet: grammar, gate, the global count, what was tested, the prior research
    lab = runner.calls[0]["packet"]["lab"]
    assert lab["tests_so_far"] == 1 and lab["next_test_number"] == 2 and lab["next_p_threshold"] == pytest.approx(0.025)
    assert lab["max_passable_n"] == NL.max_passable_n() and lab["can_still_pass"] is True
    assert "ema_cross" in lab["grammar_ko"] and "관문" in lab["gate_ko"]
    assert lab["recent"][0]["trial_id"] == other and lab["summary"]["by_entry"] == {"ema_cross": 1}
    assert "2,000개" in lab["prior_research"]["library_ko"] and lab["prior_research"]["entry_study_tests"]
    assert "volume_spike" in lab["summary"]["entries_never_tested_here"]
    sysp = runner.calls[0]["system"]
    assert "새 매매법 연구실" in sysp and "specs" in sysp and "proposal.action" not in sysp
    # code checked the three: the bad one is refused, the repeat shown with its old result, only one is new
    cands = runner.calls[1]["packet"]["candidates"]
    assert [c["index"] for c in cands] == [1] and cands[0]["spec"] == canon(EDGE)
    msgs = world.messages(LAB)
    assert any(m["kind"] == "system" and "후보 2: 문법에 맞지 않아" in m["text"] and "청산" in m["text"] for m in msgs)
    dup = next(m for m in msgs if m["kind"] == "code_result" and (m["data"] or {}).get("duplicate"))
    assert "후보 3: 이미 시험한 매매법" in dup["text"] and f"장부 #{other}" in dup["text"] and "예전 시험" in dup["text"]
    # the new one ran with n = 1 (the other room's test), is stored append-only and passed
    rows = stored(world)
    assert [t["kind"] for t in rows] == ["newlab", "newlab"] and A.newlab_count(world.agents) == 2
    t = rows[-1]
    assert t["room_id"] == LAB and t["spec"] == canon(EDGE) and t["spec_hash"] == NL.spec_hash(canon(EDGE))
    body = t["result"]["result"]
    assert body["n_tests_so_far"] == 1 and body["test_number"] == 2
    assert body["gate"]["pass"] is True and body["gate"]["alpha_period1"] == pytest.approx(0.05 / 2)
    assert body["ledger"]["pass"] and body["notes"]["idea"] == "아이디어 1"
    # a pass: one proposal row of kind 'newlab' for the owners (written with the ledger's 'proposed' result in one
    # transaction), the owners told once, no account created here
    assert t["result"]["status"] == "proposed" and body["proposal"]["kind"] == "new_paper_account"
    [prop] = R.list_proposals(world.agents)
    assert body["proposal"]["needs_owner_ok"] is True and prop["status"] == "awaiting_owner" and prop["room_id"] == LAB
    assert prop["strategy"] is None and prop["trial_id"] == t["id"] and body["proposal_id"] == prop["id"]
    assert prop["change"]["kind"] == "newlab" and prop["change"]["account"]["spec_hash"] == t["spec_hash"]
    assert [lvl for lvl, _ in note.messages] == [WARN] and "새 매매법" in note.messages[0][1]
    assert "OK" in note.messages[0][1] and "volume_spike" in note.messages[0][1]
    act = next(m for m in msgs if m["kind"] == "action" and (m["data"] or {}).get("action") == "newlab_proposal")
    assert "두 분 OK" in act["text"] and "승인/거절" in act["text"] and f"제안 #{prop['id']}" in act["text"]
    res = next(m for m in msgs if m["kind"] == "code_result" and (m["data"] or {}).get("trial_id") == t["id"]
               and not m["data"].get("duplicate"))
    assert res["data"]["gate"]["pass"] is True and "[새 매매법 시험 #2]" in res["text"]
    # the lead saw the code's results; the decision has the numbers
    lr = runner.calls[2]["packet"]["lab_results"]
    assert lr[0]["trial_id"] == t["id"] and lr[0]["status"] == "passed" and lr[0]["counted"] is True
    dec = world.rounds()[-1]["decision"]
    assert dec["tested"] == [t["id"]] and dec["passed"] == [t["id"]] and dec["proposed"] == [t["id"]]
    assert dec["bad_spec"] == 1 and dec["duplicate"] == 1 and dec["n_tests_now"] == 2
    assert "AI 호출 3회" in dec["summary_ko"] and "누적 2번" in dec["summary_ko"]
    usage = R.usage_today(world.agents, QUIET)
    assert usage["by_class"]["research"]["calls"] == 3 and set(usage["by_class"]) == {"research"}
    counts = R.trial_counts(world.agents)
    assert counts["newlab"] == 2 and counts["newlab_passed"] == 1

    # an hour later the same spec again: shown, not re-run, not counted; no skeptic, no second Telegram
    runner2 = QueueRunner({"researcher": [inventor(EDGE)], "team_lead": [LEAD]})
    out = world.tick(runner2, QUIET + HOUR, policy=lab_policy(), lab=planted, notifier=note)
    assert out["rounds"][0]["status"] == "no_action" and runner2.roles() == ["researcher", "team_lead"]
    assert A.newlab_count(world.agents) == 2 and len(note.messages) == 1
    # not again within the hour
    assert world.tick(QueueRunner({}), QUIET + HOUR + 20 * MIN, policy=lab_policy(), lab=planted)["rounds"] == []


def test_the_skeptic_drops_and_a_failing_test_is_counted_too(world, noise):
    runner = QueueRunner({"researcher": [inventor(NOISE, OTHER)], "devils_advocate": [skeptic(2)],
                          "team_lead": [LEAD]})
    note = ListNotifier()
    world.tick(runner, QUIET, policy=lab_policy(), lab=noise, notifier=note)
    rows = stored(world)
    assert [t["spec"] for t in rows] == [canon(NOISE)]                       # candidate 2 dropped, never run
    assert rows[0]["result"]["status"] == "failed" and note.messages == []
    near = runner.calls[1]["packet"]["candidates"]
    assert {c["index"] for c in near} == {1, 2} and near[0]["library_overlap"] is True
    assert any("반론 검토관이 뺀 후보" in m["text"] for m in world.messages(LAB) if m["kind"] == "system")
    assert world.rounds()[-1]["decision"]["dropped"] == 1
    # the next test of the lab is judged with n = 1
    runner = QueueRunner({"researcher": [inventor(OTHER)], "devils_advocate": [skeptic()], "team_lead": [LEAD]})
    world.tick(runner, QUIET + HOUR, policy=lab_policy(), lab=noise)
    near = runner.calls[1]["packet"]["candidates"][0]["similar_tested"]
    assert near == []                                                        # a different entry is not "similar"
    b = stored(world)[-1]["result"]["result"]
    assert b["n_tests_so_far"] == 1 and b["gate"]["alpha_period1"] == pytest.approx(0.025)


def test_unreadable_skeptic_keeps_the_specs_and_a_crashing_test_never_breaks_the_tick(world, noise, monkeypatch):
    def boom(*a, **k):
        raise MemoryError("cache too big")
    monkeypatch.setattr(NL, "run_new_strategy", boom)
    runner = QueueRunner({"researcher": [inventor(NOISE)], "devils_advocate": ["모르겠습니다", "역시 모름"],
                          "team_lead": [LEAD]})
    out = world.tick(runner, QUIET, policy=lab_policy(), lab=noise)
    assert out["rounds"][0]["status"] == "no_action" and out["rounds"][0]["error"] is None
    texts = [m["text"] for m in world.messages(LAB) if m["kind"] == "system"]
    assert any("반론 검토관의 답이 없어" in t for t in texts)
    assert any("시험 중 오류" in t and "MemoryError" in t and "넣지 않습니다" in t for t in texts)
    assert A.newlab_count(world.agents) == 0


def test_tests_are_bounded_per_meeting_and_by_the_wall_time(world, noise):
    pol = lab_policy(lab_max_tests=1)
    runner = QueueRunner({"researcher": [inventor(NOISE, OTHER)], "devils_advocate": [skeptic()], "team_lead": [LEAD]})
    world.tick(runner, QUIET, policy=pol, lab=noise)
    assert A.newlab_count(world.agents) == 1
    assert runner.calls[0]["packet"]["lab"]["max_specs_per_meeting"] == 1          # the inventor is told,
    assert len(runner.calls[1]["packet"]["candidates"]) == 1                     # and code cuts the rest
    assert world.rounds()[-1]["decision"]["candidates"] == 1
    pol = lab_policy(lab_tests_wall_s=0.0)
    runner = QueueRunner({"researcher": [inventor(OTHER)], "devils_advocate": [skeptic()], "team_lead": [LEAD]})
    world.tick(runner, QUIET + HOUR, policy=pol, lab=noise)
    assert A.newlab_count(world.agents) == 1
    assert any("시험 시간" in m["text"] and "시험하지 않습니다" in m["text"] for m in world.messages(LAB))
    # the tick's own wall time: no test that could run past it
    pol = lab_policy(tick_wall_s=1.0, lab_test_est_s=60.0)
    runner = QueueRunner({"researcher": [inventor(OTHER)], "devils_advocate": [skeptic()], "team_lead": [LEAD]})
    world.tick(runner, QUIET + 2 * HOUR, policy=pol, lab=noise)
    assert A.newlab_count(world.agents) == 1
    assert any("실행의 시간 한도" in m["text"] for m in world.messages(LAB))


# ------------------------------------------------------------------ observation period
def test_observation_period_tests_but_does_not_propose_until_it_ends(world, planted):
    note = ListNotifier()
    obs = lab_policy(observe_until=R.kst_day(QUIET + DAY))
    runner = QueueRunner({"researcher": [inventor(EDGE)], "devils_advocate": [skeptic()], "team_lead": [LEAD]})
    world.tick(runner, QUIET, policy=obs, lab=planted, notifier=note)
    t = stored(world)[-1]
    assert t["result"]["status"] == "passed" and t["result"]["result"]["proposal"] is None
    assert note.messages == [] and runner.calls[0]["packet"]["lab"]["observation"]["proposals"] is False
    assert any("관찰 기간" in m["text"] and "제안은 하지 않습니다" in m["text"] for m in world.messages(LAB))
    assert "관찰 기간" in world.rounds()[-1]["decision"]["summary_ko"]
    assert R.trial_counts(world.agents)["newlab_passed"] == 1
    # still observing: nothing proposed by the tick's housekeeping either
    world.tick(QueueRunner({}), QUIET + 10 * MIN, policy=obs, lab=None, notifier=note)
    assert note.messages == [] and stored(world)[-1]["result"]["status"] == "passed"
    # the period is over: code proposes it, judged again with the count now, once
    after = lab_policy(observe_until=R.kst_day(QUIET - DAY))
    world.tick(QueueRunner({}), QUIET + 2 * DAY, policy=after, lab=None, notifier=note)
    t = stored(world)[-1]
    assert t["result"]["status"] == "proposed" and t["result"]["result"]["proposal"]["needs_owner_ok"] is True
    assert len(note.messages) == 1
    world.tick(QueueRunner({}), QUIET + 2 * DAY + 15 * MIN, policy=after, lab=None, notifier=note)
    assert len(note.messages) == 1


def test_a_waiting_pass_lapses_when_the_count_grew_past_its_p(world, planted):
    obs = lab_policy(observe_until=R.kst_day(QUIET + DAY))
    runner = QueueRunner({"researcher": [inventor(EDGE)], "devils_advocate": [skeptic()], "team_lead": [LEAD]})
    world.tick(runner, QUIET, policy=obs, lab=planted)
    tid = stored(world)[-1]["id"]
    _fill(world, NL.max_passable_n() + 5)                     # thousands of tests later (other rooms)
    note = ListNotifier()
    world.tick(QueueRunner({}), QUIET + 2 * DAY, policy=lab_policy(), lab=None, notifier=note)
    t = R.get_trial(world.agents, tid)
    assert t["result"]["status"] == "lapsed" and note.messages == []
    assert any("다시 판정하면 통과하지 못해" in m["text"] for m in world.messages(LAB))
    assert R.trial_counts(world.agents)["newlab_passed"] == 1                 # it did pass when it ran


# ------------------------------------------------------------------ the gate's count
def _fill(world, n, room="team:elsewhere"):
    """n counted lab tests in another room (distinct specs by a fake hash)."""
    world.agents.executemany(
        "INSERT INTO trials (ts, room_id, strategy, kind, spec, spec_hash, round_id) VALUES (?,?,?,?,?,?,?)",
        [(QUIET - DAY, room, None, "newlab", json.dumps({"fake": k}), f"fake{k}", None) for k in range(n)])
    world.agents.commit()


def test_the_gate_count_tightens_and_the_lab_stops_when_nothing_can_pass(world, planted):
    _fill(world, 48)
    runner = QueueRunner({"researcher": [inventor(EDGE)], "devils_advocate": [skeptic()], "team_lead": [LEAD]})
    world.tick(runner, QUIET, policy=lab_policy(), lab=planted)
    t = stored(world)[-1]
    g = t["result"]["result"]["gate"]
    assert g["n_tests_so_far"] == 48 and g["alpha_period1"] == pytest.approx(0.05 / 49)
    # judged again later with more tests, the stored pass would need a smaller p
    gate_now, n_now = A.newlab_gate_now(world.agents, t)
    assert n_now == 48 and gate_now["pass"] is True
    _fill(world, NL.max_passable_n() - 49, room="team:more")
    assert A.newlab_count(world.agents) == NL.max_passable_n()             # 4,999 tests: test #5,000 can still pass
    assert not A.newlab_exhausted(world.agents)
    _fill(world, 1, room="team:last")
    assert A.newlab_exhausted(world.agents)                                # 5,000 tests: the next one cannot
    gate_now, n_now = A.newlab_gate_now(world.agents, t)
    assert n_now == NL.max_passable_n() and gate_now["pass"] is True         # judged with 4,999 others: still ok
    _fill(world, 1, room="team:after")
    gate_now, n_now = A.newlab_gate_now(world.agents, t)
    assert n_now == NL.max_passable_n() + 1 and gate_now["pass"] is False and not gate_now["can_pass_at_this_n"]
    # no test can pass any more: no lab meeting, and the room is told once
    ctx = RM.RoundContext(world.agents, None, None, None, QueueRunner({}), planted, QUIET + HOUR,
                          policy=lab_policy(), clock_ms=lambda: QUIET + HOUR)
    assert RM.lab_blocked(ctx) == "exhausted" and "research" in RM.deferred_triggers(ctx)
    for k in range(2):
        out = world.tick(QueueRunner({}), QUIET + (2 + k) * HOUR, policy=lab_policy(), lab=planted)
        assert out["rounds"] == []
    notes = [m for m in world.messages(LAB) if (m["data"] or {}).get("reason") == "exhausted"]
    assert len(notes) == 1 and "어떤 새 시험도 관문을 넘을 수 없습니다" in notes[0]["text"]


# ------------------------------------------------------------------ trigger and budget
def test_research_trigger_is_off_by_default_on_for_the_server_and_needs_the_lab(world, noise):
    assert RM.RoomsPolicy().triggers.research_every_ms == 0
    assert RM.policy_from_env({}).triggers.research_every_ms == RM.RESEARCH_EVERY_MIN_DEFAULT * 60_000
    assert RM.policy_from_env({"AGENTS_RESEARCH_EVERY_MIN": "0"}).triggers.research_every_ms == 0
    with pytest.raises(ValueError):
        RM.policy_from_env({"AGENTS_RESEARCH_EVERY_MIN": "-5"})
    assert world.tick(QueueRunner({}), QUIET, lab=noise)["rounds"] == []                  # default: off
    assert world.tick(QueueRunner({}), QUIET, policy=lab_policy(), lab=None)["rounds"] == []   # no cache
    due = TR.find_due(None, None, world.agents, None, QUIET, lab_policy().triggers)
    assert [(d.room_id, d.trigger, d.priority, d.data["class"]) for d in due] == [(LAB, "research", 5, "research")]
    assert due[0].data["key"] == f"research:{R.kst_day(QUIET)}:15"
    assert TR.TriggerPolicy().cap_exempt == ("incident", "research")      # the budget bounds it, not the room cap


def test_research_budget_class_is_enforced_paced_and_not_reserved(world, noise):
    assert "research" not in RM.RESERVED_CLASSES and "research" in TR.CLASSES
    assert RM.DEFAULT_BUDGETS["research"] == (24, 700_000)
    caps = RM.budget_caps(lab_policy())
    assert caps["research"] == {"calls": 24, "tokens": 700_000}
    assert RM.scaled_policy(lab_policy(), 0.5).budgets["research"] == (12, 350_000)   # the adaptive scale applies
    assert RM.budget_warnings(lab_policy()) == []
    assert any("research=2" in w for w in RM.budget_warnings(lab_policy(budgets={**RM.DEFAULT_BUDGETS, "research": (2, 10 ** 6)})))
    due = TR.Due(LAB, "research", 5, {"class": "research"}, "research")

    def ctx(t, pol=None):
        return RM.RoundContext(world.agents, None, None, None, QueueRunner({}), noise, t, policy=pol or lab_policy(),
                               clock_ms=lambda: t)
    b = RM.round_budget(due, ctx(QUIET))
    assert b.pipeline == "research" and b.paced and b.max_calls == 24 and b.reserve()[0] == 30
    # the owner class keeps nothing for research (research is not a reserve)
    owner = RM.round_budget(TR.Due("team:risk", "owner", 1, {"class": "owner"}, "owner"), ctx(QUIET))
    assert owner.reserve() == (30, 850_000)

    def use(cls, n, t):
        world.agents.executemany("INSERT INTO agent_calls VALUES (?,?,?,?,?,?,?)",
                                 [(t, R.kst_day(t), cls, "x", "sonnet", 1, 8_000)] * n)
        world.agents.commit()
    # paced over the KST day: at 00:30 KST ceil(24 x 3.5 / 24) = 4 calls
    night = kst(2026, 10, 8, 0, 30)
    assert RM.round_budget(due, ctx(night)).headroom() == 4 and RM.can_start(due, ctx(night))
    use("research", 2, night)
    assert RM.round_budget(due, ctx(night)).headroom() == 2 and not RM.can_start(due, ctx(night))   # 3 calls a meeting
    # its own cap: a call past it stops the meeting and pauses only research
    use("research", 24, QUIET)
    with pytest.raises(RM.BudgetExceeded) as ei:
        RM.round_budget(due, ctx(QUIET)).check()
    assert RM.stop_blocks(RM.stop_kind(ei.value), "research") == ["research"]
    assert not RM.can_start(due, ctx(QUIET)) and "research" in RM.deferred_triggers(ctx(QUIET))
    # it never touches the incident / 08:00 / 22:00 reserve, and it leaves the reviews' unused calls
    day2 = kst(2026, 10, 9, 23, 0)
    use("owner", 20, day2)
    use("weekly", 4, day2)
    b = RM.round_budget(due, ctx(day2))
    kc, _kt = b.paced_keep()
    assert kc == 8 + 10                                       # the bust reserve + 10 of the reviews' 32 unused calls
    assert b.headroom() == 80 - 24 - 30 - kc == 8
    use("loss", 4, day2)                                       # reviews use their calls: still 28 unused, keep 10
    assert RM.round_budget(due, ctx(day2)).headroom() == 4
    use("research", 4, day2)
    rb = RM.round_budget(due, ctx(day2))
    assert rb.headroom() == 0
    with pytest.raises(RM.PacedKeepExceeded) as ei:
        rb.check()
    assert RM.stop_blocks(RM.stop_kind(ei.value), "research") == []          # stops itself only
    loss = TR.Due("strat:N17_KC_RSI", "loss_cluster", 2, {"class": "loss"}, "loss_cluster")
    assert RM.can_start(loss, ctx(day2))                                     # a review still can
    inc = RM.round_budget(TR.Due("team:ops", "incident", 0, {"class": "incident", "counts": {"liquidation": 1}},
                                 "incident"), ctx(day2))
    assert inc.headroom() == 15                                              # the liquidation reserve is intact
    # another class's reserve stop does not need to block research (its headroom decides); its own does
    assert "research" not in RM.stop_blocks("budget_reserve", "loss")
    assert "research" in RM.stop_blocks("budget_reserve", "research")
    assert set(RM.stop_blocks("budget_total", "owner")) == set(TR.CLASSES)


def test_a_research_meeting_stopped_by_its_cap_pauses_only_research(world, noise):
    pol = lab_policy(budgets={**RM.DEFAULT_BUDGETS, "research": (3, 10 ** 9)})
    runner = QueueRunner({"researcher": ["엉망", inventor(NOISE)], "devils_advocate": [skeptic()],
                          "team_lead": [LEAD]})
    out = world.tick(runner, QUIET, policy=pol, lab=noise)
    r = out["rounds"][0]
    # the retry of the unreadable first answer used a call: the lead's call would pass the cap
    assert r["status"] == "stopped_budget" and r["stopped"] == "budget_class"
    assert world.rounds()[-1]["decision"]["blocks"] == ["research"]
    assert A.newlab_count(world.agents) == 1                                  # the test it ran stays in the ledger
    assert R.usage_today(world.agents, QUIET)["by_class"]["research"]["calls"] == 3
    world.say("team:risk", "오늘 어때요?", QUIET + 5 * MIN)
    runner = QueueRunner({"risk_officer": [{"headline": "괜찮음", "findings": []}],
                          "team_lead": [{"summary": ["요약"]}]})
    out = world.tick(runner, QUIET + 15 * MIN, policy=pol, lab=noise)
    assert [(x["room_id"], x["trigger"]) for x in out["rounds"]] == [("team:risk", "owner")]


# ------------------------------------------------------------------ the room, the roster, the dashboard
def test_the_lab_room_exists_with_its_speakers_and_on_the_dashboard(world):
    room = R.get_room(world.agents, LAB)
    assert room["kind"] == "team" and room["title"] == "새 매매법 연구실"
    assert room["members"] == ["researcher", "devils_advocate", "team_lead"]
    speakers = {r for r, _ in RM.team_plan(TR.Due(LAB, "research", 5, {}, "research"))}
    speakers |= {r for r, _ in RM.team_plan(TR.Due(LAB, "owner", 1, {}, "owner"))}
    assert set(room["members"]) == speakers and set(room["members"]) <= set(R.ROLE_NAMES)
    assert LAB in TR.all_rooms() and LAB not in R.TEAM_ROOMS
    assert len(R.room_specs()) == 42
    for turn in RM.LAB_TURNS:
        assert RM.role_model("researcher", turn) == "sonnet"
        assert RM.LAB_DUTY[turn] in RM.system_prompt("researcher", turn)
    pytest.importorskip("fastapi")
    from paperbot.dash.app import Rooms
    rm = Rooms(world.paths["agents"], world.paths["inbox"])
    ov = {r["room_id"]: r for r in rm.overview(now_ms=QUIET)["rooms"]}
    assert ov[LAB]["title"] == "새 매매법 연구실" and ov[LAB]["kind"] == "team"
    info = rm.room_info(LAB)
    assert [m["name"] for m in info["members_info"]] == ["전략 연구원", "반론 검토관", "팀장"]
    tr = rm.trials(None, LAB)
    assert tr["counts"]["newlab"] == 0 and tr["counts"]["newlab_passed"] == 0


def test_an_owner_post_in_the_lab_is_answered_with_the_lab_ledger(world, noise):
    runner = QueueRunner({"researcher": [inventor(NOISE)], "devils_advocate": [skeptic()], "team_lead": [LEAD]})
    world.tick(runner, QUIET, policy=lab_policy(), lab=noise)
    world.say(LAB, "지금까지 몇 개 시험했나요?", QUIET + 5 * MIN)
    runner = QueueRunner({"researcher": [{"headline": "1개", "findings": [
        {"claim": "새 매매법 시험 1개", "kind": "fact", "evidence": ["lab.tests_so_far"]}], "reply_to_owner": "1개입니다"}],
        "team_lead": [{"summary": ["1개 시험"]}]})
    out = world.tick(runner, QUIET + 15 * MIN, policy=lab_policy(), lab=noise)
    assert [(r["room_id"], r["trigger"]) for r in out["rounds"]] == [(LAB, "owner")]
    assert runner.calls[0]["turn"] == "team" and runner.calls[0]["model"] == RM.role_model("researcher")
    assert runner.calls[0]["packet"]["lab"]["tests_so_far"] == 1
    ans = next(m for m in world.messages(LAB) if m["round_id"] == world.rounds()[-1]["round_id"]
               and m["role"] == "researcher")
    assert ans["data"]["answer"]["findings"][0]["kind"] == "fact"           # lab.* is code-computed


def test_dashboard_script_shows_lab_counts_passes_and_the_research_label():
    with open(os.path.join(REPO, "paperbot", "dash", "static", "rooms.js"), encoding="utf-8") as fh:
        src = fh.read()
    assert f"const NEWLAB_MAX_TESTS = {NL.max_passable_n() + 1};" in src
    for s in ('research: "새 매매법 연구"', "새 매매법 시험", "관문을 통과한 새 매매법", '"team:lab": "연구"', 'kind === "newlab"'):
        assert s in src, s


def test_ledger_helpers_and_hash_agree_with_the_engine(world):
    c = canon({"timeframe": "1h", "entry": {"family": "supertrend_flip", "params": {"length": 10, "mult": 3}},
               "filters": [{"kind": "session", "window": "us"}, {"kind": "adx", "mode": "above", "level": 25}]})
    assert R.spec_hash(c) == NL.spec_hash(c)
    tid = R.add_trial_with_result(world.agents, LAB, None, "newlab", c, "failed", {"x": 1}, ts=QUIET)
    assert A.newlab_hashes(world.agents) == {NL.spec_hash(c): tid}
    assert R.trial_index(world.agents, "newlab") == [{"id": tid, "spec": c, "spec_hash": NL.spec_hash(c),
                                                      "status": "failed"}]
    with pytest.raises(ValueError):
        R.add_trial_with_result(world.agents, LAB, None, "nope", c, "failed", {})
    # the inventor's answer check: at most 3, a spec object each
    out, probs = RM.check_lab_inventor({"specs": [{"spec": EDGE}] * 4 + ["x"]}, {"lab": {"max_specs_per_meeting": 3}})
    assert len(out["specs"]) == 3 and any("3개까지" in p for p in probs) and any("spec" in p for p in probs)
    out, probs = RM.check_lab_skeptic({"reviews": [{"index": 9, "keep": False}, {"index": 1, "keep": "no"}]},
                                      {"candidates": [{"index": 1}]})
    assert out["reviews"] == [{"index": 1, "keep": True, "reason": ""}] and len(probs) == 2
