"""Strategy rooms with sides (design #102 C, policy ``sides`` / AGENTS_SIDES=1): the advocate (the strategy's own
specialist), the attacker (dealt by code) and the attack turn, the dispute code opens after it (talk only, given up,
conceded, held), the validator only on a passing gate, the team lead's one dispute in the six review meetings, the
settings, and today's meetings unchanged while sides are off."""

import json

import pytest

from paperbot.agents import disputes as DS
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from test_disputes import _fake_labintake
from test_rooms import (HOUR, MIN, NOTE, QUIET, ROOM, S, SPEC, TEST, QueueRunner, World, analysis,  # noqa: F401
                        bad_lab, challenge, good_lab, kst, team_answer)

ATT = DS.attacker_of(S)                       # N17_KC_RSI: the exit-timing analyst attacks it
LAB_SETTLE = {"kind": "lab", "test": {"template": "skip_tag", "timeframe": "15m", "value": "추세 반대 진입"}}


def attack(verdict, settle=None, claim="추세 반대 진입이 이 매매법 손실의 원인", **kw):
    return {"headline": "결함 하나", "claim": claim,
            "objections": [{"claim": "새 손실 3건 모두 추세 반대 진입", "evidence": ["losses.n_new"]}],
            "verdict": verdict, "settle": settle, "confidence": 2,
            "responds_to": {"role": SPEC, "stance": "disagree", "point": "손실 특징을 정상 손실로 봄"}, **kw}


def final(proposal, concede=False, reply=True, **kw):
    out = analysis(proposal, changes="공격에 답함", concede=concede, **kw)
    if reply:
        out["responds_to"] = {"role": ATT, "stance": "disagree" if not concede else "agree", "point": "숫자로 답함"}
    return out


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


@pytest.fixture
def intake(monkeypatch):
    calls: list = []
    monkeypatch.setattr(DS, "_labintake", lambda: _fake_labintake(calls))
    return calls


def sides(**kw):
    return RM.RoomsPolicy(sides=True, **kw)


def disputes(world):
    return [dict(r) for r in DS._rows(world.agents, order="id")]


# ------------------------------------------------------------------ settings and today's meetings
def test_sides_are_off_unless_the_server_turns_them_on():
    assert RM.RoomsPolicy().sides is False and RM.policy_from_env({}).sides is False
    p = RM.policy_from_env({"AGENTS_SIDES": "1", "AGENTS_DISPUTE_TESTS_PER_DAY": "2", "AGENTS_DISPUTE_ROOM_GAP_DAYS": "5",
                            "AGENTS_DISPUTE_EXPERT": "1"})
    assert (p.sides, p.dispute_tests_per_day, p.dispute_room_gap_days, p.dispute_expert) == (True, 2, 5, True)
    assert RM.policy_from_env({"AGENTS_SIDES": "0"}).sides is False
    d = RM.policy_from_env({})
    assert (d.dispute_tests_per_day, d.dispute_room_gap_days, d.dispute_expert) == (3, 7, False)
    for bad in ({"AGENTS_SIDES": "2"}, {"AGENTS_SIDES": "yes"}, {"AGENTS_DISPUTE_TESTS_PER_DAY": "4"},
                {"AGENTS_DISPUTE_EXPERT": "3"}):
        with pytest.raises(ValueError):
            RM.policy_from_env(bad)


def test_with_sides_off_the_meeting_and_its_prompts_are_todays(world):
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE)], "devils_advocate": [challenge("agree")]})
    world.tick(runner, QUIET)
    assert runner.roles() == [SPEC, "devils_advocate"]
    assert "sides" not in runner.calls[0]["packet"] and "disputes" not in runner.calls[0]["packet"]
    assert "편드는 직원" not in runner.calls[0]["system"] and disputes(world) == []
    assert R.get_cursor(world.agents, DS.SIDES_CURSOR) is None                # no seats written while off
    for meeting in ("ranking", "morning"):
        assert '"dispute"' not in RM.system_prompt("team_lead", "lead", meeting)
    assert '"concede"' not in RM.system_prompt(SPEC, "revision", "loss_cluster")
    assert RM.system_prompt(SPEC, "specialist", "loss_cluster") == RM.system_prompt(SPEC, "specialist", "loss_cluster",
                                                                                    False)


def test_the_sides_prompt_pieces_are_fixed_text_by_role_and_turn():
    adv = RM.system_prompt(SPEC, "specialist", "loss_cluster", True)
    assert "편드는 직원" in adv and "request_test" in adv
    rev = RM.system_prompt(SPEC, "revision", "loss_cluster", True)
    assert '"concede": false' in rev and "this_round.attack" in rev
    lens = RM.system_prompt("exit_timing", "attack", "loss_cluster", True)
    assert "공격하는 직원" in lens and "# 당신의 전문 관점" in lens and "청산 타점" in lens and '"settle"' in lens
    plain = RM.system_prompt("devils_advocate", "attack", "loss_cluster", True)
    assert "# 당신의 전문 관점" not in plain and '"responds_to"' in plain
    assert '"dispute"' in RM.system_prompt("team_lead", "lead", "ranking", True)
    assert '"dispute"' not in RM.system_prompt("team_lead", "lead", "morning", True)
    assert "편드는 직원" not in RM.system_prompt("devils_advocate", "challenge", "morning", True)


# ------------------------------------------------------------------ the sides meeting
def test_hold_opens_a_lab_dispute_in_three_calls_and_hands_its_test_to_the_queue(world, intake):
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE), final(NOTE)], ATT: [attack("disagree", LAB_SETTLE)]})
    out = world.tick(runner, QUIET, policy=sides())
    assert runner.roles() == [SPEC, ATT, SPEC] and out["rounds"][0]["calls"] == 3
    t1, t2, t4 = (c["packet"] for c in runner.calls)
    assert t1["sides"]["advocate"]["role"] == SPEC and t1["sides"]["attacker"]["role"] == ATT
    assert "dispute_tests" in t1["disputes"] and "attack_hint" in t2 and t4["this_round"]["attack"]["verdict"] == "disagree"
    assert runner.calls[1]["turn"] == "attack" and "공격하는 직원" in runner.calls[1]["system"]
    [d] = disputes(world)
    assert (d["status"], d["kind"], d["side_a"], d["side_b"], d["source"], d["room_id"]) == (
        "queued", "lab", ATT, SPEC, "strategy_room", ROOM)
    assert d["spec"]["test"] == {"template": "skip_tag", "strategy": S, "timeframe": "15m", "tag": "추세 반대 진입"}
    assert d["intake_id"] == 1 and intake[0]["source_ref"] == f"dispute:{d['id']}" and intake[0]["meta"]["by_role"] == ATT
    msgs = world.messages()
    att = next(m for m in msgs if m["role"] == ATT)
    assert att["kind"] == "challenge" and "공격: 추세 반대 진입" in att["text"]
    assert "가릴 시험: 5년 시험 · N17_KC_RSI 15m: '추세 반대 진입' 신호 건너뛰기" in att["text"]
    rev = next(m for m in msgs if m["kind"] == "revision")
    assert "공격에 대해: 버팀" in rev["text"]
    act = next(m for m in msgs if m["kind"] == "action" and (m["data"] or {}).get("action") == "dispute")
    assert act["role"] == "code" and act["text"].startswith(f"⚔️ 다툼 #{d['id']} 열림: 공격 청산 타점 분석가 vs 편 켈트너·RSI 전담")
    dec = world.rounds()[-1]["decision"]
    assert dec["dispute"]["status"] == "queued" and dec["sides"] == {"advocate": SPEC, "attacker": ATT}
    assert "⚔️ 다툼" in dec["summary_ko"] and "공격하는 직원(청산 타점 분석가) 판단: 반대" in dec["summary_ko"]
    assert R.get_cursor(world.agents, DS.SIDES_CURSOR)["version"] == 1


def test_the_attacker_giving_up_ends_the_meeting_in_two_calls(world):
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE)], ATT: [attack("agree", LAB_SETTLE)]})
    out = world.tick(runner, QUIET, policy=sides())
    assert runner.roles() == [SPEC, ATT] and out["rounds"][0]["calls"] == 2 and disputes(world) == []
    texts = [m["text"] for m in world.messages()]
    assert any(t.startswith("🏳️ 공격 포기") for t in texts)
    att = next(m for m in world.messages() if m["role"] == ATT)
    assert "판정: 동의 (공격 포기)" in att["text"] and "가릴 시험" not in att["text"]
    dec = world.rounds()[-1]["decision"]
    assert dec["early_stop"] is True and dec["dispute"]["status"] == "gave_up" and "공격 포기" in dec["summary_ko"]
    assert DS.role_record(DS.board(world.agents), ATT)["gave_up"] == 1


def test_a_disagreement_without_a_test_is_talk_only(world):
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE), final(NOTE)],
                          ATT: [attack("needs_test", {"kind": "lab", "test": {"template": "timeframe_only"}})]})
    world.tick(runner, QUIET, policy=sides())
    assert runner.roles() == [SPEC, ATT, SPEC] and disputes(world) == []
    att = next(m for m in world.messages() if m["role"] == ATT)
    assert "가릴 시험: 없음 (말로만 반대)" in att["text"] and att["data"]["answer"]["talk_only"] is True
    assert any("말로만 반대" in m["text"] and m["kind"] == "system" for m in world.messages())
    assert world.rounds()[-1]["decision"]["dispute"]["status"] == "talk_only"
    assert DS.role_record(DS.board(world.agents), ATT)["talk_only"] == 1


def test_a_concession_is_final_unscored_and_its_test_still_queued(world, intake):
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE), final(NOTE, concede=True)], ATT: [attack("disagree", LAB_SETTLE)]})
    world.tick(runner, QUIET, policy=sides())
    [d] = disputes(world)
    assert d["status"] == "conceded" and d["intake_id"] == 1 and len(intake) == 1 and intake[0]["meta"]["conceded"]
    assert any("공격에 대해: 인정함" in m["text"] for m in world.messages())
    b = DS.board(world.agents)
    assert DS.role_record(b, SPEC)["conceded"] == 1 and b["base_rates"]["all"]["settled"] == 0


def test_the_advocates_first_turn_cannot_ask_for_a_test(world):
    world.losses()
    runner = QueueRunner({SPEC: [analysis(TEST)], ATT: [attack("agree")]})
    world.tick(runner, QUIET, policy=sides())
    assert world.rounds()[-1]["decision"]["final"]["action"] == "no_action"       # T1's test became no action
    assert any("허용되지 않은 행동" in m["text"] for m in world.messages() if m["kind"] == "system")


def test_a_forward_dispute_opens_with_the_codes_n(world):
    world.parent_trades()                     # 30 closed N17 trades in the last 14 days: about 2 a day
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE), final(NOTE)],
                          ATT: [attack("disagree", {"kind": "forward", "check": "vs_flip", "timeframe": None})]})
    world.tick(runner, QUIET, policy=sides())
    [d] = disputes(world)
    assert (d["status"], d["kind"]) == ("open", "forward") and d["spec"]["check"] == "vs_flip"
    assert 20 <= d["spec"]["n"] <= 60 and d["data"]["base_trade_id"] > 0
    att = next(m for m in world.messages() if m["role"] == ATT)
    assert f"가릴 시험: 앞으로 거래 {d['spec']['n']}건: 같은 기간 동전 계좌보다 나은지" in att["text"]
    assert runner.calls[1]["packet"]["disputes"]["forward"]["all"]["n"] == d["spec"]["n"]


def test_the_validator_speaks_only_when_the_gate_passes_and_the_dispute_follows_the_claim_rule(world, bad_lab):
    world.parent_trades()
    world.losses()
    t = {"template": "skip_tag", "timeframe": "15m", "value": "추세 반대 진입"}
    runner = QueueRunner({SPEC: [analysis(NOTE), final(TEST)], ATT: [attack("disagree", {"kind": "lab", "test": t})]})
    out = world.tick(runner, QUIET, policy=sides(), lab=object())
    assert runner.roles() == [SPEC, ATT, SPEC] and out["rounds"][0]["calls"] == 3       # no validator for a failed gate
    [p] = R.list_proposals(world.agents)
    assert p["status"] == "blocked_gate"
    # the next tick settles the dispute from the meeting's own test: the claim rule, not the copy gate
    world.tick(QueueRunner({}), QUIET + 10 * MIN, policy=sides())
    [d] = disputes(world)
    assert (d["status"], d["winner"]) == ("settled", "a") and d["trial_id"] == p["trial_id"]
    assert "공격하는 직원 맞음" in d["outcome"] and "복제 관문: 불통과" in d["outcome"]
    assert any(m["text"].startswith(f"⚖️ 다툼 #{d['id']} 결론") for m in world.messages())


def test_with_a_passing_gate_the_validator_and_approver_still_speak(world, good_lab):
    world.parent_trades()
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE), final(TEST)], ATT: [attack("disagree", LAB_SETTLE)],
                          "validator": [{"pass_gate": True, "explanation": "두 기간 개선"}],
                          "approver": [{"approve": False, "reason": "관찰"}]})
    world.tick(runner, QUIET, policy=sides(), lab=object())
    assert runner.roles() == [SPEC, ATT, SPEC, "validator", "approver"]


def test_an_owner_named_expert_or_dispute_expert_adds_the_expert_turn(world):
    world.losses()
    runner = QueueRunner({SPEC: [analysis(NOTE), final(NOTE)], ATT: [attack("needs_test", LAB_SETTLE)],
                          "entry_timing": [{"headline": "진입", "findings": [], "verdict": "agree"}]})
    world.tick(runner, QUIET, policy=sides(dispute_expert=True))
    assert runner.roles() == [SPEC, ATT, "entry_timing", SPEC]           # entry_timing: the losses' top tag


# ------------------------------------------------------------------ the team lead's dispute
def _ranking(world, lead, stance="disagree", sides_on=True):
    t = kst(2026, 10, 7, 14, 5)
    pol = RM.RoomsPolicy(sides=sides_on)
    pol.triggers.ranking_hour_kst = 14
    pol.triggers.fresh_run_min_trades = 0
    second = {**team_answer("p"), "responds_to": {"role": "performance", "stance": stance, "point": "하위 3개는 비용 탓"}}
    runner = QueueRunner({"performance": [team_answer("f")], "pnl_reviewer": [second],
                          "risk_officer": [team_answer("r")], "team_lead": [lead]})
    world.tick(runner, t, policy=pol)
    return runner


LEAD = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [],
        "dispute": {"strategy": S, "side_a": "pnl_reviewer", "side_b": "performance",
                    "claim": "켈트너·RSI의 손실은 추세 반대 진입 탓", "settle": LAB_SETTLE}}


def test_a_lead_dispute_opens_only_with_a_recorded_disagree_reply(world, intake):
    runner = _ranking(world, LEAD)
    assert '"dispute"' in runner.calls[-1]["system"]
    [d] = disputes(world)
    assert (d["source"], d["room_id"], d["side_a"], d["side_b"], d["status"]) == (
        "team_lead", "team:review", "pnl_reviewer", "performance", "queued")
    assert intake[0]["strategy"] == S                                   # the test runs in strat:<S>'s own ledger
    assert any(m["text"].startswith(f"⚔️ 다툼 #{d['id']} 열림") for m in world.messages("team:review"))
    assert "⚔️ 다툼" in world.rounds()[-1]["decision"]["summary_ko"]


def test_a_lead_dispute_without_a_disagree_reply_is_refused(world):
    _ranking(world, LEAD, stance="agree")
    assert disputes(world) == []
    assert any("팀장이 적은 다툼은 열지 않았습니다" in m["text"] for m in world.messages("team:review"))


def test_at_most_one_dispute_a_meeting_and_none_while_sides_are_off(world):
    _ranking(world, {**LEAD, "dispute": [LEAD["dispute"], LEAD["dispute"]]})        # a list is not one dispute
    assert disputes(world) == []


def test_no_lead_dispute_while_sides_are_off(world):
    runner = _ranking(world, LEAD, sides_on=False)
    assert '"dispute"' not in runner.calls[-1]["system"] and disputes(world) == []
    assert not any("다툼" in m["text"] for m in world.messages("team:review") if m["role"] == "code")


def test_the_attack_answer_is_checked_by_code():
    given = {"room": {"room_id": ROOM, "strategy": S}, "role": ATT, "turn": "attack", "this_round": {},
             "disputes": {"forward": {"all": {"ok": True, "n": 25}, "1h": {"ok": False, "why": "드묾"}}},
             "losses": {"n_new": 3}}
    ok, probs = RM.check_attack(attack("disagree", {"kind": "forward", "check": "tag_gap", "tag": "횡보장 진입",
                                                     "timeframe": None}, confidence=7), given)
    assert ok["settle"] == {"kind": "forward", "check": "tag_gap", "timeframe": None, "tag": "횡보장 진입", "n": 25}
    assert ok["confidence"] is None and probs == [] and "앞으로 거래 25건" in RM.render("attack", ok)
    ok, probs = RM.check_attack(attack("disagree", {"kind": "forward", "check": "vs_flip", "timeframe": "1h"}), given)
    assert ok["settle"] is None and ok["talk_only"] is True and "드묾" in probs[0]
    ok, _ = RM.check_attack(attack("agree", LAB_SETTLE), given)
    assert ok["settle"] is None and "talk_only" not in ok
    ok, _ = RM.check_attack({**attack("maybe", LAB_SETTLE)}, given)       # an unreadable verdict opens nothing
    assert ok["verdict_coerced"] is True and ok["settle"] is None and "talk_only" not in ok
    assert json.dumps(ok, ensure_ascii=False)


# ------------------------------------------------------------------ review fixes (disputes-c adversarial review)
def test_an_open_disputes_claim_is_the_attackers_words_never_a_code_fact():
    given = {"room": {"room_id": ROOM, "strategy": S}, "turn": "specialist", "role": SPEC, "this_round": {},
             "disputes": {"open": [{"id": 1, "claim_ko": "이 매매법은 동전보다 못함", "kind": "forward", "settle_ko": "앞으로 거래 20건"}],
                          "settled_recent": [{"id": 2, "line": "편드는 직원 맞음(코드 결론)"}]},
             "sides": {"advocate": {"record": {"won": 1}}}}
    probs: list = []
    got = RM._findings([{"claim": "동전보다 못함", "kind": "fact", "evidence": [p]} for p in
                        ("disputes.open.0.claim_ko", "disputes.open.0", "disputes.open", "disputes")], given, "findings",
                       probs)
    assert [f["kind"] for f in got] == ["hypothesis"] * 4 and len(probs) == 4
    ok = RM._findings([{"claim": "코드 결론", "kind": "fact", "evidence": [p]} for p in
                       ("disputes.settled_recent.0.line", "disputes.open.0.settle_ko", "sides.advocate.record")],
                      given, "findings", [])
    assert [f["kind"] for f in ok] == ["fact"] * 3


def test_the_owners_named_devils_advocate_answers_in_a_room_it_does_not_attack(world):
    assert ATT != "devils_advocate"
    world.say(ROOM, "@반론 검토관 이 방 손실은 어떻게 봐?", QUIET - MIN)
    runner = QueueRunner({SPEC: [analysis(NOTE), final(NOTE)], ATT: [attack("agree")],
                          "devils_advocate": [challenge("disagree")]})
    out = world.tick(runner, QUIET, policy=sides())
    assert [(r["room_id"], r["trigger"]) for r in out["rounds"]] == [(ROOM, "owner")]
    assert runner.roles() == [SPEC, ATT, "devils_advocate", SPEC]          # no early stop: the owners asked it
    assert runner.calls[2]["turn"] == "challenge" and out["rounds"][0]["calls"] == 4


def test_without_an_attack_to_settle_the_final_answer_neither_concedes_nor_holds(world):
    """The attacker gave up but the meeting went on (T1 was a hypothesis): the advocate's final answer has nothing to
    concede or hold, so the room is not told '버팀 (코드가 시험으로 가림)' and no dispute opens."""
    world.losses()
    hyp = {"action": "hypothesis", "text": "추세 반대 진입 손실이 많음", "how_to_confirm": "다음 20건"}
    runner = QueueRunner({SPEC: [analysis(hyp), final(NOTE, concede=True)], ATT: [attack("agree")]})
    world.tick(runner, QUIET, policy=sides())
    assert runner.roles() == [SPEC, ATT, SPEC] and disputes(world) == []
    rev = next(m for m in world.messages() if m["kind"] == "revision")
    assert "공격에 대해" not in rev["text"] and "concede" not in rev["data"]["answer"]
    assert world.rounds()[-1]["decision"]["dispute"]["status"] == "gave_up"
