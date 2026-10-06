"""The owners' '🧪 이 매매법 시험해줘' (#103 idea inbox): the lab room's form posts a request (fixed first line), the lab
owner meeting's translator puts it into the grammar (rooms.py turn 'lab_translate'), code re-makes and queues it
(labintake.enqueue_owner): exact -> tested within the owners' daily budget, approx -> waits for the owners' click
(inbox.db lab_request_decisions, written by the dashboard, applied by the tick read-only), none -> refused. Off by
default: a request post is then an ordinary owner post and nothing is queued."""

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
from paperbot.notify import INFO, ListNotifier

from test_labintake import NOISE, OTHER
from test_newlab import _write
from test_rooms import HOUR, MIN, QUIET, QueueRunner, World

LAB = R.LAB_ROOM
LEAD = {"summary": ["요청을 받았습니다", "코드가 옮긴 결과대로 진행", "결과는 코드가 알림"], "human_actions": [], "watch_next": []}
REQ = {"entry": "볼린저 밴드 아래를 찍고 다시 안으로 들어올 때", "exit": "영상에서는 3% 익절", "timeframe": "4h",
       "coins": "BTC만", "side": "둘 다", "link": "https://youtu.be/abc"}


@pytest.fixture(scope="module")
def noise(tmp_path_factory):
    return LT.LabData(_write(str(tmp_path_factory.mktemp("owner_noise")), coins=("BTCUSD", "ETHUSD"), pre=False))


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def translate(*items, reply="옮겼습니다"):
    return lambda pk: {"headline": "두 분 요청 옮김", "requests": [dict(it, message_id=it.get("message_id") or
                                                                     pk["lab_requests"][0]["id"]) for it in items],
                       "reply_to_owner": reply}


def exact(spec=NOISE, **kw):
    return {"engine": "newlab", "spec": spec, "entry_fidelity": "exact", "kept": ["볼린저 아래에서 안으로 들어올 때 진입"],
            "lost": ["영상의 3% 익절"], "reason_codes": ["exit_rule"], "idea": "볼린저 되돌림", **kw}


def approx(spec=OTHER, **kw):
    return {"engine": "newlab", "spec": spec, "entry_fidelity": "approx", "kept": ["이평 교차"], "lost": ["EMA 8 → 9"],
            "reason_codes": ["param_off_grid"], "idea": "이평 교차", **kw}


def tick(world, runner, now, lab, owner=1, notifier=None, **pol):
    return world.tick(runner, now, policy=RM.RoomsPolicy(lab_intake_owner_per_day=owner, **pol), lab=lab,
                      notifier=notifier)


def lab_lines(world, owner_only=True):
    return [m for m in world.messages(LAB) if not owner_only or (m["data"] or {}).get("owner_request")]


# ------------------------------------------------------------------ the request text (dashboard side)
def test_the_form_text_has_the_fixed_first_line_and_one_labelled_line_per_field():
    text = LI.request_text({**REQ, "entry": "  볼린저 밴드 아래를\n찍고  다시 안으로  "})
    lines = text.split("\n")
    assert lines[0] == LI.LAB_REQUEST_MARK == "🧪 시험 요청" and LI.is_lab_request(text)
    assert lines[1] == "언제 들어가나: 볼린저 밴드 아래를 찍고 다시 안으로"           # one line per field, blanks collapsed
    assert "참고 링크(에이전트는 열 수 없음): https://youtu.be/abc" in lines
    assert len(LI.request_text({k: "가" * m for k, _l, _n, m in LI.REQUEST_FIELDS if k not in ("timeframe", "side")})) <= 1000
    for bad, why in (({}, "언제 들어가나"), ({"entry": "x", "timeframe": "1d"}, "시간봉"), ({"entry": "x", "side": "아무거나"}, "롱·숏"),
                     ({"entry": "가" * 351}, "350자")):
        with pytest.raises(ValueError, match=why):
            LI.request_text(bad)
    assert not LI.is_lab_request("시험 요청 해주세요") and not LI.is_lab_request(None)
    assert LI.is_lab_request("﻿ 🧪 시험 요청 \n언제 들어가나: x")


# ------------------------------------------------------------------ the meeting
def test_off_by_default_a_request_is_an_ordinary_owner_post_and_nothing_is_queued(world, noise):
    mid = world.say(LAB, LI.request_text(REQ), QUIET - 10 * MIN)
    runner = QueueRunner({"researcher": [{"headline": "읽었습니다", "findings": [], "data_gaps": [],
                                           "reply_to_owner": "지금은 시험 요청이 꺼져 있습니다"}], "team_lead": [LEAD]})
    out = tick(world, runner, QUIET, noise, owner=0)
    assert [(c["role"], c["turn"]) for c in runner.calls] == [("researcher", "team"), ("team_lead", "lead")]
    assert out["rounds"][0]["status"] == "done" and not LI.exists(world.agents)
    off = [m for m in world.messages(LAB) if (m["data"] or {}).get("off")]
    assert len(off) == 1 and "꺼져" in off[0]["text"] and (off[0]["data"] or {}).get("message_ids") == [mid]
    assert "lab_translate" not in runner.calls[0]["system"] and A.newlab_count(world.agents) == 0


def test_an_exact_request_is_queued_tested_in_the_same_pass_and_reported_back(world, noise):
    mid = world.say(LAB, LI.request_text(REQ), QUIET - 10 * MIN)
    world.say(LAB, "이건 그냥 질문입니다", QUIET - 9 * MIN)
    note = ListNotifier()
    runner = QueueRunner({"researcher": [translate(exact())], "team_lead": [LEAD]})
    out = tick(world, runner, QUIET, noise, notifier=note)
    # the same two calls as any owner post: the translator, then the lead (with what code queued)
    assert [(c["role"], c["turn"]) for c in runner.calls] == [("researcher", "lab_translate"), ("team_lead", "lead")]
    tr = runner.calls[0]["packet"]
    assert [r["id"] for r in tr["lab_requests"]] == [mid]                     # only the request, not the plain question
    assert "bb_revert" in tr["lab"]["grammar_ko"] and tr["lab_translate"]["reason_codes"] == LI.OWNER_REASON_KO
    assert "링크(영상·글)는 열 수 없습니다" in runner.calls[0]["system"] and "번역가" in runner.calls[0]["system"]
    assert runner.calls[1]["packet"]["lab_request_results"][0]["status"] == "queued"
    assert out["rounds"][0]["status"] == "done"
    cards = LI.owner_cards(world.agents)
    assert len(cards) == 1 and cards[0]["source_ref"] == f"owner:{mid}:0" and cards[0]["fidelity"] == "exact"
    assert cards[0]["status"] == "tested" and cards[0]["trial_id"] and A.newlab_count(world.agents) == 1   # counted
    assert cards[0]["stage"]["done"] == ["received", "translated", "confirmed", "tested", "result"]
    lines = [m["text"] for m in lab_lines(world)]
    assert any("정확히 옮김" in t and "오늘 두 분 몫(0/1)" in t and LI.OWNER_EXITS_KO in t for t in lines)
    result = [t for t in lines if t.startswith(f"🧪 두 분 시험 요청 #{mid}-1 결과")]
    assert len(result) == 1 and ("불통과" in result[0] or "통과" in result[0])
    assert any(level == INFO and "시험 요청 결과" in text for level, text in note.messages)
    # the decision line of the meeting counts it; the post is never translated again
    dec = [m for m in world.messages(LAB) if m["kind"] == "decision"][-1]
    assert "두 분 시험 요청 1건: 시험 줄 1" in dec["text"]
    tick(world, QueueRunner({}), QUIET + 15 * MIN, noise)
    assert len(LI.owner_cards(world.agents)) == 1 and A.newlab_count(world.agents) == 1


def test_an_approximate_request_waits_for_the_owners_click_then_runs(world, noise):
    mid = world.say(LAB, LI.request_text({"entry": "EMA 8이 21을 위로 넘으면", "timeframe": "4h"}), QUIET - 10 * MIN)
    tick(world, QueueRunner({"researcher": [translate(approx())], "team_lead": [LEAD]}), QUIET, noise)
    card = LI.owner_cards(world.agents)[0]
    assert card["status"] == "needs_owner_ok" and card["stage"]["now"] == "confirmed" and A.newlab_count(world.agents) == 0
    assert card["lost"] == ["EMA 8 → 9"] and card["reasons_ko"] == [LI.OWNER_REASON_KO["param_off_grid"]]
    assert any("두 분 확인 필요" in m["text"] and "[시험하기]" in m["text"] for m in lab_lines(world))
    # a click with another row's source_ref (a replaced agents3.db) or from before the row is never applied
    LI.add_decision(world.inbox, card["id"], "owner:999:0", "run", "owner1", QUIET + MIN)
    LI.add_decision(world.inbox, card["id"], card["source_ref"], "decline", "owner1", card["ts"] - 1)
    tick(world, QueueRunner({}), QUIET + 15 * MIN, noise)
    assert LI.latest(world.agents, card["id"])["status"] == "needs_owner_ok"
    LI.add_decision(world.inbox, card["id"], card["source_ref"], "run", "owner2", QUIET + 20 * MIN)
    LI.add_decision(world.inbox, card["id"], card["source_ref"], "decline", "owner1", QUIET + 21 * MIN)   # too late
    assert LI.owner_cards(world.agents, world.paper())[0]["decision"] is None             # wrong file: no click shown
    ib = R.open_ro(world.paths["inbox"])
    assert LI.owner_cards(world.agents, ib)[0]["decision"]["decision"] == "run"            # waiting to be applied
    ib.close()
    tick(world, QueueRunner({}), QUIET + 30 * MIN, noise)
    after = LI.latest(world.agents, card["id"])
    assert after["status"] == "tested" and A.newlab_count(world.agents) == 1              # the first valid click: run
    assert any("'시험하기'를 고르셨습니다" in m["text"] and "owner2" in m["text"] for m in lab_lines(world))


def test_decline_tests_nothing_and_the_daily_budget_holds(world, noise):
    world.say(LAB, LI.request_text({"entry": "a"}), QUIET - 10 * MIN)
    tick(world, QueueRunner({"researcher": [translate(approx(), exact(NOISE))], "team_lead": [LEAD]}), QUIET, noise)
    cards = {c["source_ref"].rsplit(":", 1)[1]: c for c in LI.owner_cards(world.agents)}
    assert cards["0"]["status"] == "needs_owner_ok" and cards["1"]["status"] == "tested"
    LI.add_decision(world.inbox, cards["0"]["id"], cards["0"]["source_ref"], "decline", "", QUIET + MIN)
    tick(world, QueueRunner({}), QUIET + 15 * MIN, noise)
    assert LI.latest(world.agents, cards["0"]["id"])["status"] == "declined" and A.newlab_count(world.agents) == 1
    assert LI.result_ko({}, "declined").startswith("두 분이 그만두셨습니다")


def test_a_second_exact_request_waits_for_tomorrow_when_todays_owner_budget_is_used(world, noise):
    world.say(LAB, LI.request_text({"entry": "a"}), QUIET - 10 * MIN)
    tick(world, QueueRunner({"researcher": [translate(exact(NOISE), exact(OTHER))], "team_lead": [LEAD]}), QUIET, noise)
    st = sorted(c["status"] for c in LI.owner_cards(world.agents))
    assert st == ["queued", "tested"] and A.newlab_count(world.agents) == 1


def test_code_refuses_what_the_translator_could_not_put_into_the_grammar(world, noise):
    a = world.say(LAB, LI.request_text({"entry": "머리어깨 패턴 완성 때"}), QUIET - 12 * MIN)
    b = world.say(LAB, LI.request_text({"entry": "5분봉 볼린저", "timeframe": "모름"}), QUIET - 11 * MIN)
    c = world.say(LAB, LI.request_text({"entry": "말 안 한 요청"}), QUIET - 10 * MIN)
    runner = QueueRunner({"researcher": [lambda pk: {"headline": "옮김", "requests": [
        {"message_id": a, "engine": "none", "entry_fidelity": "none", "reason_codes": ["pattern", "made_up"]},
        {"message_id": b, "engine": "newlab", "entry_fidelity": "exact", "spec": {**NOISE, "timeframe": "5m"}},
        {"message_id": 777, "engine": "newlab", "entry_fidelity": "exact", "spec": NOISE}]}], "team_lead": [LEAD]})
    tick(world, runner, QUIET, noise)
    by = {int(x["source_ref"].split(":")[1]): x for x in LI.owner_cards(world.agents)}
    assert by[a]["status"] == "refused" and LI.OWNER_REASON_KO["pattern"] in by[a]["result_ko"]
    assert by[b]["status"] == "refused" and "5분봉" in by[b]["result_ko"]
    assert by[c]["status"] == "refused" and by[c]["fidelity"] == "none"                  # the post it left out
    assert A.newlab_count(world.agents) == 0
    assert all(LI.NOT_TESTED_KO in m["text"] for m in lab_lines(world) if m["kind"] == "code_result")
    problems = [m for m in world.messages(LAB) if (m["data"] or {}).get("problems")]
    assert problems and any("made_up" in p for p in problems[0]["data"]["problems"])
    assert any("777" in p for p in problems[0]["data"]["problems"])


def test_a_retried_meeting_never_queues_or_announces_a_request_twice(tmp_path):
    c = R.open_agents(str(tmp_path / "a.db"))
    R.ensure_rooms(c)

    class Rnd:                                   # the parts of rooms._Round that queue_owner_requests uses
        def __init__(self):
            self.ctx = RM.RoundContext(agents_conn=c, paper_ro=None, daily_ro=None, inbox_ro=None, runner=None, lab=None,
                                       now_ms=QUIET, policy=RM.RoomsPolicy(lab_intake_owner_per_day=1), clock_ms=lambda: QUIET)
            self.posts = []

        def post(self, role, kind, text, data=None):
            self.posts.append(text)

        def system(self, text, data=None):
            self.posts.append(text)
    t1 = {"requests": [{"message_id": 7, **exact()}]}
    first, again = Rnd(), Rnd()
    a = RM.queue_owner_requests(first, t1, [{"id": 7}])
    b = RM.queue_owner_requests(again, {"requests": [{"message_id": 7, **approx()}]}, [{"id": 7}])
    assert a[0]["intake_id"] == b[0]["intake_id"] and b[0]["again"] is True and b[0]["status"] == "queued"
    assert len(first.posts) == 1 and again.posts == []                          # the first translation stands
    assert len(LI.owner_cards(c)) == 1
    c.close()


def test_no_translation_records_nothing_and_asks_to_post_again(world, noise):
    world.say(LAB, LI.request_text({"entry": "a"}), QUIET - 10 * MIN)
    runner = QueueRunner({"researcher": ["읽을 수 없는 답", "또 읽을 수 없는 답"], "team_lead": [LEAD]})
    out = tick(world, runner, QUIET, noise)
    assert out["rounds"][0]["status"] == "done" and LI.owner_cards(world.agents) == []
    assert any("다시 올려 주세요" in m["text"] for m in world.messages(LAB))


# ------------------------------------------------------------------ the checker and the settings
def test_check_lab_translate_keeps_only_this_meetings_posts_and_the_fixed_vocabulary():
    given = {"lab_requests": [{"id": 5}, {"id": 6}]}
    out, problems = RM.check_lab_translate({"requests": [
        {"message_id": 5, "engine": "newlab", "entry_fidelity": "exact", "spec": NOISE, "reason_codes": ["universe", "x"]},
        {"message_id": 5, "engine": "labtest", "entry_fidelity": "maybe", "test": {"template": "skip_tag"}, "strategy": "N17_KC_RSI"},
        {"message_id": 5, "engine": "newlab", "entry_fidelity": "exact", "spec": NOISE},
        {"message_id": True, "engine": "newlab"}, {"message_id": 9, "engine": "newlab"},
        {"message_id": 6, "engine": "telepathy", "entry_fidelity": "exact"},
        {"message_id": 6, "engine": "newlab", "entry_fidelity": "exact", "spec": {"x": "y" * 3000}}], "reply_to_owner": 3},
        given)
    assert [(r["message_id"], r["engine"], r["entry_fidelity"]) for r in out["requests"]] == [
        (5, "newlab", "exact"), (5, "labtest", "approx"), (6, "none", "none"), (6, "none", "none")]
    assert out["requests"][0]["reason_codes"] == ["universe"] and out["reply_to_owner"] == ""
    assert len(problems) == 7
    assert RM.check_lab_translate([], given)[0] is None


def test_exact_with_an_entry_change_is_approximate_but_exits_alone_are_not(tmp_path):
    """Code's rule: an 'exact' whose entry needed a change is approximate (the exits alone never decide it)."""
    c = R.open_agents(str(tmp_path / "a.db"))
    LI.ensure(c)
    u = LI.enqueue_owner(c, 1, 0, {"engine": "newlab", "spec": NOISE, "entry_fidelity": "exact", "reason_codes": ["universe"]})
    e = LI.enqueue_owner(c, 2, 0, {"engine": "newlab", "spec": OTHER, "entry_fidelity": "exact",
                                   "reason_codes": ["exit_rule", "position_mgmt"]})
    assert (u["status"], e["status"]) == ("needs_owner_ok", "queued")
    c.close()


def test_the_policy_caps_the_owners_budget_and_reads_the_goal_line_switch():
    assert RM.policy_from_env({"AGENTS_LAB_INTAKE_OWNER_PER_DAY": "3"}).lab_intake_owner_per_day == 3
    with pytest.raises(ValueError, match="하루 3개까지"):
        RM.policy_from_env({"AGENTS_LAB_INTAKE_OWNER_PER_DAY": "4"})
    assert RM.policy_from_env({}).goal_line is False and RM.policy_from_env({"AGENTS_GOAL_LINE": "1"}).goal_line is True
    with pytest.raises(ValueError):
        RM.policy_from_env({"AGENTS_GOAL_LINE": "2"})
    env = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "agents.env.example"),
               encoding="utf-8").read()
    assert "\n#AGENTS_GOAL_LINE=1" in env and "\nAGENTS_GOAL_LINE=" not in env


def test_the_translator_prompt_and_plan():
    sp = RM.system_prompt("researcher", "lab_translate", "owner")
    assert "번역가" in sp and '"entry_fidelity"' in sp and "exact | approx | none" in sp and "자료" in sp
    assert RM.role_model("researcher", "lab_translate") == RM.role_model("researcher", "lab_inventor")
    due = RM.TR.Due(LAB, "owner", 1, {"message_ids": [1]}, "owner")
    assert RM.team_plan(due, lab_request=True) == [("researcher", "lab_translate"), ("team_lead", "lead")]
    assert RM.team_plan(due) == [("researcher", "team"), ("team_lead", "lead")]
    other = RM.TR.Due("team:risk", "owner", 1, {"message_ids": [1]}, "owner")
    assert RM.team_plan(other, lab_request=True) == RM.team_plan(other)              # only the lab room translates
    ans = RM.DryRunRunner().call("sonnet", "", "", {"role": "researcher", "turn": "lab_translate",
                                                    "lab_requests": [{"id": 4}]})
    clean, problems = RM.check_lab_translate(json.loads(ans.text), {"lab_requests": [{"id": 4}]})
    assert not problems and clean["requests"][0]["entry_fidelity"] == "approx"


def test_a_free_repeat_answers_the_owners_without_a_new_test(world, noise, tmp_path):
    world.say(LAB, LI.request_text({"entry": "a"}), QUIET - 10 * MIN)
    tick(world, QueueRunner({"researcher": [translate(exact())], "team_lead": [LEAD]}), QUIET, noise)
    world.say(LAB, LI.request_text({"entry": "같은 것 다시"}), QUIET + 5 * MIN)
    tick(world, QueueRunner({"researcher": [translate(exact())], "team_lead": [LEAD]}), QUIET + 2 * HOUR, noise)
    cards = LI.owner_cards(world.agents)
    assert sorted(c["status"] for c in cards) == ["duplicate", "tested"] and A.newlab_count(world.agents) == 1
    dup = next(c for c in cards if c["status"] == "duplicate")
    assert dup["counted"] is False and dup["result_ko"].startswith("이미 시험함")
    assert any(m["text"].startswith(f"🧪 두 분 시험 요청 {dup['label_ko'][3:]} 결과") for m in lab_lines(world))


def test_code_checks_an_exact_translation_against_the_owners_timeframe_and_side(tmp_path):
    """The translator says 'exact' but changed the 시간봉 or 롱·숏 the owners picked on the form: code makes it approximate
    (the owners confirm first, nothing is counted before) and writes the difference itself; '모름' checks nothing."""
    text = LI.request_text({"entry": "볼린저 아래에서 다시 안으로", "timeframe": "1h", "side": "롱만"})
    assert LI.request_fields(text) == {"timeframe": "1h", "side": "롱만"}
    assert LI.request_fields(LI.request_text({"entry": "x", "timeframe": "모름"})) == {"timeframe": "모름"}
    assert LI.request_fields("그냥 글\n시간봉: 1h") == {} and LI.request_fields(None) == {}
    assert LI.request_fields(LI.LAB_REQUEST_MARK + "\n시간봉: 1d\n롱·숏: 아무거나") == {}
    c = R.open_agents(str(tmp_path / "a.db"))
    LI.ensure(c)
    asked = LI.request_fields(text)
    tf = LI.enqueue_owner(c, 1, 0, {"engine": "newlab", "spec": dict(NOISE, direction="long"), "entry_fidelity": "exact"},
                          asked=asked)                                     # 4h tested, 1h asked
    side = LI.enqueue_owner(c, 2, 0, {"engine": "newlab", "spec": dict(NOISE, timeframe="1h"), "entry_fidelity": "exact"},
                            asked=asked)                                   # both sides tested, 롱만 asked
    same = LI.enqueue_owner(c, 3, 0, {"engine": "newlab", "spec": dict(NOISE, timeframe="1H", direction="long"),
                                      "entry_fidelity": "exact"}, asked=asked)
    unknown = LI.enqueue_owner(c, 4, 0, {"engine": "newlab", "spec": NOISE, "entry_fidelity": "exact"},
                               asked={"timeframe": "모름", "side": "모름"})
    assert (tf["status"], side["status"], same["status"], unknown["status"]) == (
        "needs_owner_ok", "needs_owner_ok", "queued", "queued")
    cards = {int(x["source_ref"].split(":")[1]): x for x in LI.owner_cards(c)}
    assert cards[1]["fidelity"] == "approx" and any("시간봉 1h" in x and "4h" in x for x in cards[1]["reasons_ko"])
    assert any("롱만" in x and "(코드 확인)" in x for x in cards[2]["reasons_ko"])
    assert cards[3]["reasons_ko"] == [] and cards[4]["fidelity"] == "exact"
    # a 36 what-if test cannot pick a side: an owner's 롱만 / 숏만 is never 'exact' there
    lt = LI._asked_mismatch("labtest", {"template": "stop_atr", "timeframe": "1h", "k": 2.5}, asked)
    assert len(lt) == 1 and "롱·숏을 고를 수 없어" in lt[0]
    assert LI._asked_mismatch("newlab", {"timeframe": "9h"}, asked) == []            # unreadable: canon refuses it
    c.close()


def test_the_meeting_passes_the_forms_choices_to_code(world, noise):
    """End to end: an 'exact' translation that changed the owners' 시간봉 waits for their click and tests nothing."""
    world.say(LAB, LI.request_text({"entry": "볼린저 아래에서 다시 안으로", "timeframe": "1h", "side": "둘 다"}),
              QUIET - 10 * MIN)
    tick(world, QueueRunner({"researcher": [translate(exact())], "team_lead": [LEAD]}), QUIET, noise)
    card = LI.owner_cards(world.agents)[0]
    assert card["status"] == "needs_owner_ok" and card["fidelity"] == "approx" and A.newlab_count(world.agents) == 0
    assert any("시간봉 1h" in m["text"] and "두 분 확인 필요" in m["text"] for m in lab_lines(world))


def test_switching_every_source_off_brings_the_saved_budgets_to_zero(world, noise):
    """The dashboard's form reads the budgets the agents saved: turning the owners' budget (and every other source) off
    must not leave the form looking switched on."""
    tick(world, QueueRunner({}), QUIET, noise, owner=2)
    assert R.get_cursor(world.agents, LI.LIMITS_CURSOR) == {"debate": 0, "meeting": 0, "owner": 2}
    tick(world, QueueRunner({}), QUIET + 15 * MIN, noise, owner=0)
    assert R.get_cursor(world.agents, LI.LIMITS_CURSOR) == {"debate": 0, "meeting": 0, "owner": 0}
    assert LI.owner_block(world.agents, None, QUIET + 16 * MIN)["enabled"] is False
