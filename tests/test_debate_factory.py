"""The debate room as an idea factory (paperbot/agents/debate_factory.py): assigned sides and order, the code check of
each round's lab idea (grammar, refusals, the ledger, repeats, near-copies of failed tests), the daily pick across KST
midnight, the read-back block, and the hand-off round trip into the agents' lab intake queue and back."""

import json
import sqlite3

import pytest

from paperbot.agents import actions as A
from paperbot.agents import debate as D
from paperbot.agents import debate_factory as DF
from paperbot.agents import debate_packet as P
from paperbot.agents import labintake as LI
from paperbot.agents import labtests as LT
from paperbot.agents import newlab as NL
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.config import DS200_FAMILY, REEL_NAME

from test_rooms import StubLab

DAY, HOUR, MIN = 86_400_000, 3_600_000, 60_000
KST = 9 * HOUR
D0 = 1_791_158_400_000 + 10 * DAY - KST            # 2026-10-15 00:00 KST
S = "N17_KC_RSI"
NOISE = {"timeframe": "4h", "entry": {"family": "bb_revert"}, "direction": "both"}
EMA = {"family": "ema_cross", "params": {"fast": 9, "slow": 21}}
NEAR_FAILED = {"timeframe": "1h", "entry": EMA, "filters": [{"kind": "trend_ema", "length": 200}], "direction": "long"}


def kst_at(day, hh, mm=0):
    return D0 + day * DAY + hh * HOUR + mm * MIN


@pytest.fixture
def dconn(tmp_path):
    c = sqlite3.connect(str(tmp_path / "debate.db"))
    DF.ensure(c)
    yield c
    c.close()


@pytest.fixture
def agents(tmp_path):
    path = str(tmp_path / "agents3.db")
    c = R.open_agents(path)
    R.ensure_rooms(c, ts=D0 - DAY)
    yield c, path
    c.close()


def idea(engine="newlab", spec=None, test=None, **kw):
    out = {"engine": engine, "claim": "주장", "pro": "찬성 근거", "con": "반대 근거", "con_check": "⑥", **kw}
    if spec is not None:
        out["spec"] = spec
    if test is not None:
        out["test"] = test
    return out


def skip(tag=LT.SKIP_TAGS[0], tf="1h", strategy=S):
    return {"template": "skip_tag", "strategy": strategy, "timeframe": tf, "tag": tag}


# ------------------------------------------------------------------ sides and order
def test_the_specialists_split_two_two_every_round_and_the_judge_speaks_last():
    """Owners 10/06: five specialists (차트 분석가, 리스크 책임자, 퀀트, 시장 분석가) and a 심판 seat of its own; the four
    split 2-2 into 찬성 / 반대, a different split every round, each plays both sides equally often."""
    assert DF.ROLES == D.FACTORY_ROLES == ("차트 분석가", "리스크 책임자", "퀀트", "시장 분석가", "심판")
    assert D.ROLES == ("낙관론자", "비관론자", "회의론자", "리스크 책임자", "퀀트")           # classic: unchanged
    count = {r: {"찬성": 0, "반대": 0} for r in DF.ROLES[:4]}
    prev = None
    splits = set()
    for n in range(12):
        s = DF.sides_for(n)
        assert list(s) == list(DF.ROLES) and s["심판"] == "심판"
        assert sorted(s.values()) == ["반대", "반대", "심판", "찬성", "찬성"]
        pro = frozenset(r for r in s if s[r] == "찬성")
        assert pro != prev                                                             # a new split every round
        prev = pro
        splits.add(pro)
        for r in DF.ROLES[:4]:
            count[r][s[r]] += 1
        for turns in range(3, 12):
            order = DF.factory_order(n, turns)
            assert len(order) == min(max(turns, 5), 9) and set(order) == set(DF.ROLES)     # all five speak
            assert order[-1] == "심판" and order.count("심판") == 1                         # the judge last, once
            assert [s[r] for r in order[:4]] == ["찬성", "반대", "찬성", "반대"]
    assert len(splits) == 6                                                            # every 2-2 split in 6 rounds
    assert all(v == {"찬성": 6, "반대": 6} for v in count.values())
    assert DF.sides_text(0) == ("찬성 차트 분석가, 리스크 책임자 / 반대 퀀트, 시장 분석가 / 심판 — 마지막 발언은 심판. "
                                + DF.SIDE_RULE_KO)
    assert "맡은 편만 변호" in DF.SIDE_RULE_KO and "①~⑥" in DF.SIDE_RULE_KO       # no side may step out of its side


# ------------------------------------------------------------------ the idea check
def test_every_bad_spec_path_and_the_refusals(dconn, agents):
    a, _ = agents
    cases = [(None, "missing"), ("문자열", "missing"),
             ({"engine": "none", "reason": "청산 규칙이라 못 옮김"}, "cannot_express"),
             (idea("magic", spec=NOISE), "bad_spec"),
             (idea(spec={"timeframe": "1h", "entry": "nope"}), "bad_spec"),
             (idea(spec={**NOISE, "exit": "tp"}), "bad_spec"),
             (idea("labtest", test="skip"), "bad_spec"),
             (idea("labtest", test={**skip(), "tag": "아무 태그"}), "bad_spec"),
             (idea("labtest", test={"template": "stop_atr", "strategy": S, "timeframe": "1h", "k": 2.0}), "bad_spec"),
             (idea(spec={**NOISE, "timeframe": "5m"}), "refused"),
             (idea("labtest", test=skip(tf="5m")), "refused"),
             (idea("labtest", test={"template": "timeframe_only", "strategy": S}), "refused"),
             (idea("labtest", test=skip(strategy="RANDOM_1")), "refused"),
             (idea("labtest", test=skip(strategy=next(iter(DS200_FAMILY)))), "refused"),
             (idea("labtest", test=skip(strategy=REEL_NAME)), "refused")]
    for raw, want in cases:
        got = DF.check_idea(raw, a, dconn, D0)
        assert got["check_status"] == want, (raw, got)
        assert got["check_ko"]
    ok = DF.check_idea(idea(spec=NOISE, con_check="f", backs=3, weak=[{"id": 2, "why": "표본"}, {"id": True}]), a, dconn, D0)
    assert ok["check_status"] == "ok" and ok["spec"] == NL.normalize_spec(NOISE) and ok["con_check"] == "⑥"
    assert ok["description_ko"] == NL.describe_ko(NL.normalize_spec(NOISE)) and ok["backs"] == 3
    assert ok["weak"] == [{"id": 2, "why": "표본"}] and ok["library_overlap"] is True
    lt = DF.check_idea(idea("labtest", test={k: v for k, v in skip().items() if k != "strategy"}, strategy=S), a, dconn, D0)
    assert lt["check_status"] == "ok" and lt["strategy"] == S and lt["spec_hash"] == R.spec_hash(LT.normalize_spec(skip(), S))
    long = DF.check_idea(idea(spec=NOISE, claim="가" * 900, con_check="⑦"), a, dconn, D0)
    assert len(long["claim_ko"]) == 200 and long["con_check"] is None


def test_exact_repeat_and_near_duplicates_against_the_ledger(dconn, agents):
    a, _ = agents
    old = R.add_trial_with_result(a, R.LAB_ROOM, None, "newlab", NL.normalize_spec(NOISE), "failed", {"x": 1}, ts=D0 - DAY)
    near = R.add_trial_with_result(a, R.LAB_ROOM, None, "newlab", NL.normalize_spec(NEAR_FAILED), "failed", {}, ts=D0 - DAY)
    tid = R.add_trial(a, f"strat:{S}", S, "test", LT.normalize_spec(skip(), S), ts=D0 - DAY)
    R.add_trial_result(a, tid, "failed", {}, ts=D0 - DAY)
    dup = DF.check_idea(idea(spec=NOISE), a, dconn, D0)
    assert dup["check_status"] == "duplicate" and dup["old_trial_id"] == old and "failed" in dup["check_ko"]
    tdup = DF.check_idea(idea("labtest", test=skip()), a, dconn, D0)
    assert tdup["check_status"] == "duplicate" and tdup["old_trial_id"] == tid
    # the same as a failed test but for the direction (score 3+1+2+0+1+1 = 8 >= 7): a near-copy, not tested
    nd = DF.check_idea(idea(spec={**NEAR_FAILED, "direction": "short"}), a, dconn, D0)
    assert nd["check_status"] == "near_duplicate" and nd["old_trial_id"] == near
    far = DF.check_idea(idea(spec={**NEAR_FAILED, "direction": "short", "filters": []}), a, dconn, D0)
    assert far["check_status"] == "ok" and far["similar"][0] == {"trial_id": near, "similarity": 6, "status": "failed"}
    # this room's own idea of the last 30 days: a repeat backs it
    first = DF.add_idea(dconn, 1, D0, {"kind": "big_losses", "key": "k", "question_ko": "질문"}, far)
    again = DF.check_idea(idea(spec={**NEAR_FAILED, "direction": "short", "filters": []}), a, dconn,
                          D0 + HOUR)
    assert again["check_status"] == "repeat" and again["repeat_of"] == first and again["backs"] == first
    later = DF.check_idea(idea(spec={**NEAR_FAILED, "direction": "short", "filters": []}), a, dconn,
                          D0 + 31 * DAY)
    assert later["check_status"] == "ok"
    # no lab modules on this side: stored 'unchecked' for the agents side to check
    assert DF.check_idea(idea(spec=NOISE), None, None, D0)["check_status"] == "ok"


def test_unimportable_lab_modules_leave_the_idea_unchecked(dconn, monkeypatch):
    def broken(engine, raw):
        raise ImportError("no numpy here")
    monkeypatch.setattr(DF, "_canon", broken)
    got = DF.check_idea(idea(spec=NOISE), None, dconn, D0)
    assert got["check_status"] == "unchecked" and got["spec"] == NOISE


def test_an_unchecked_idea_is_still_a_candidate_for_the_agents_side_to_check(dconn, agents, monkeypatch):
    """The design: if the lab modules cannot load on the debate side, the idea is stored 'unchecked' and the agents
    side still checks it (labintake re-makes every spec). It must reach the daily pick, not be skipped for good."""
    a, _ = agents

    def broken(engine, raw):
        raise ImportError("no numpy here")
    monkeypatch.setattr(DF, "_canon", broken)
    n = DF.check_idea(idea(spec=SPECS[0]), a, dconn, kst_at(0, 20))
    t = DF.check_idea(idea("labtest", test={k: v for k, v in skip().items() if k != "strategy"}, strategy=S), a, dconn,
                      kst_at(0, 20))
    monkeypatch.undo()
    assert n["check_status"] == t["check_status"] == "unchecked" and t["strategy"] == S
    nid = DF.add_idea(dconn, 1, kst_at(0, 20), None, n)
    tid = DF.add_idea(dconn, 2, kst_at(0, 20, 5), None, t)
    assert _q(dconn, nid)[0] == _q(dconn, tid)[0] == "candidate"
    assert DF.slot_pick(dconn, a, kst_at(0, 21, 5), 1)["queued"] in (nid, tid)


def test_malformed_backs_and_weak_from_the_model_never_break_the_round(dconn, agents):
    a, _ = agents
    for weak in (5, 1.5, True, "약함", {"id": 1}, [{"id": 2 ** 70}], [{"id": "3"}], [{"id": -4}], None):
        for backs in (2 ** 70, -1, 0, True, "7", 1.5, [1], None):
            got = DF.check_idea(idea(spec=SPECS[0], backs=backs, weak=weak), a, dconn, kst_at(0, 20))
            assert got["weak"] == [] and got["backs"] is None, (weak, backs)
            DF.add_idea(dconn, 1, kst_at(0, 20), None, got, commit=False)        # storable (no overflow)
            dconn.rollback()
    ok = DF.check_idea(idea(spec=SPECS[0], backs=7, weak=[{"id": 9, "why": "표본"}]), a, dconn, kst_at(0, 20))
    assert ok["backs"] == 7 and ok["weak"] == [{"id": 9, "why": "표본"}]


def test_a_slot_is_picked_once_even_when_an_idea_arrives_after_the_pick(dconn, agents):
    a, _ = agents
    x = _add(dconn, a, SPECS[0], kst_at(0, 20))
    assert DF.slot_pick(dconn, a, kst_at(0, 21, 5), 1)["queued"] == x
    # a round that began at 20:55 stores its idea (with its round time) after the 21:05 pick
    late = _add(dconn, a, SPECS[1], kst_at(0, 20, 55), kind="big_losses")
    got = DF.slot_pick(dconn, a, kst_at(0, 21, 20), 1)
    assert got["queued"] is None and got["not_picked"] == [late] and f"이번엔 #{x}" in _q(dconn, late)[3]
    assert dconn.execute("SELECT COUNT(*) FROM debate_lab_ideas WHERE queue_status = 'queued'").fetchone()[0] == 1
    # the next slot picks as usual
    y = _add(dconn, a, SPECS[2], kst_at(1, 10))
    assert DF.slot_pick(dconn, a, kst_at(1, 21, 1), 1)["queued"] == y


def test_the_similar_copy_scores_like_rooms():
    specs = [NEAR_FAILED, {**NEAR_FAILED, "direction": "short"}, {**NEAR_FAILED, "timeframe": "4h"},
             {"timeframe": "1h", "entry": {"family": "ema_cross", "params": {"fast": 20, "slow": 50}}, "direction": "both"},
             {"timeframe": "1h", "entry": {"family": "rsi_cross50"}, "filters": [{"kind": "adx", "mode": "above", "level": 25}]},
             {"timeframe": "1h", "entry": EMA, "filters": [{"kind": "trend_ema", "length": 50},
                                                          {"kind": "session", "window": "us"}], "direction": "long"}]
    index = [{"id": i + 1, "spec": NL.normalize_spec(s), "status": "failed" if i % 2 else "passed"}
             for i, s in enumerate(specs)]
    for s in specs + [{"timeframe": "30m", "entry": EMA}]:
        c = NL.normalize_spec(s)
        mine = [(x["trial_id"], x["similarity"], x["status"]) for x in DF.similar(c, index)]
        theirs = [(x["trial_id"], x["similarity"], x["status"]) for x in RM._similar(c, index, NL)]
        assert mine == theirs and DF.library_overlap(c) == RM._library_overlap(c)


# ------------------------------------------------------------------ the daily pick
def _add(dconn, a, spec, ts, kind="loss_tag", **kw):
    got = DF.check_idea(idea(spec=spec, **kw), a, dconn, ts)
    assert got["check_status"] in ("ok", "repeat"), got
    return DF.add_idea(dconn, 1, ts, {"kind": kind, "key": kind}, got)


def _q(dconn, iid):
    return dconn.execute("SELECT queue_status, slot, score, queue_ko FROM debate_lab_ideas WHERE id = ?", (iid,)).fetchone()


SPECS = [{"timeframe": "1h", "entry": {"family": f}, "direction": "long",
          "filters": [{"kind": "adx", "mode": "above", "level": 25}]}
         for f in ("keltner_break", "psar_flip", "dmi_cross", "ichimoku_tk", "aroon_cross", "cmo_zero")]


def test_slot_pick_one_a_day_across_kst_midnight(dconn, agents):
    a, _ = agents
    x = _add(dconn, a, SPECS[0], kst_at(0, 20))
    y = _add(dconn, a, SPECS[1], kst_at(0, 20, 10), kind="big_losses")       # +0.5: the owners' example question
    z = _add(dconn, a, SPECS[2], kst_at(0, 22))                              # after 21:00: tomorrow's slot
    assert DF.slot_pick(dconn, a, kst_at(0, 20, 30), 1)["queued"] is None    # yesterday's slot: nothing in it
    got = DF.slot_pick(dconn, a, kst_at(0, 21, 5), 1)
    assert got == {"slot": f"slot:{P.kst_day(kst_at(0, 12))}:pm", "queued": y, "not_picked": [x]}
    assert _q(dconn, y)[0] == "queued" and _q(dconn, x)[0] == "not_picked" and f"이번엔 #{y}" in _q(dconn, x)[3]
    assert _q(dconn, y)[2] == pytest.approx(1 + 1 + 1 + 0.5)                 # new family, new filters, big_losses
    assert _q(dconn, z)[0] == "candidate"
    assert DF.slot_pick(dconn, a, kst_at(1, 0, 30), 1)["queued"] is None     # after midnight: same slot, done
    assert DF.slot_pick(dconn, a, kst_at(1, 21, 1), 1)["queued"] == z
    assert DF.slot_pick(dconn, a, kst_at(1, 21, 30), 1) == {"slot": f"slot:{P.kst_day(kst_at(1, 12))}:pm",
                                                            "queued": None, "not_picked": []}
    # the agents' contract: exactly the picked rows are 'queued'
    assert [r[0] for r in dconn.execute("SELECT id FROM debate_lab_ideas WHERE queue_status = 'queued' ORDER BY id")] == [y, z]


def test_slot_pick_two_a_day_zero_a_day_backs_weak_and_the_floor(dconn, agents):
    a, _ = agents
    m = _add(dconn, a, SPECS[0], kst_at(0, 8))
    n = _add(dconn, a, SPECS[1], kst_at(0, 10))
    assert DF.slot_pick(dconn, a, kst_at(0, 9, 5), 0) == {"slot": None, "queued": None, "not_picked": []}
    assert DF.slot_pick(dconn, a, kst_at(0, 9, 5), 2)["queued"] == m
    assert DF.slot_pick(dconn, a, kst_at(0, 21, 5), 2)["queued"] == n
    # backs and weak move the score; the library overlap costs 2; under 1 nothing is queued
    p = _add(dconn, a, SPECS[2], kst_at(1, 1))
    q = _add(dconn, a, SPECS[3], kst_at(1, 2), weak=[{"id": 0, "why": "x"}])
    backer = DF.check_idea(idea(spec=SPECS[4], backs=p), a, dconn, kst_at(1, 3))
    DF.add_idea(dconn, 2, kst_at(1, 3), None, backer)
    critic = DF.check_idea(idea(spec=SPECS[5], weak=[{"id": q, "why": "표본 작음"}]), a, dconn, kst_at(1, 4))
    DF.add_idea(dconn, 3, kst_at(1, 4), None, critic)
    got = DF.slot_pick(dconn, a, kst_at(1, 9, 1), 2)
    assert got["queued"] == p and _q(dconn, p)[2] == pytest.approx(1 + 1 + 1 + 1)      # one back
    assert _q(dconn, q)[2] == pytest.approx(1 - 1 + 1 + 1)                             # one weak
    over = _add(dconn, a, {"timeframe": "1h", "entry": {"family": "hma_turn", "params": {"length": 21}},
                           "direction": "both"}, kst_at(2, 1))
    assert DF.slot_pick(dconn, a, kst_at(2, 9, 1), 2)["queued"] == over                 # 1+1+1-2 = 1: just enough
    # an idea whose family and filters are tested and that overlaps the library scores < 1: nothing is forced
    R.add_trial_with_result(a, R.LAB_ROOM, None, "newlab", NL.normalize_spec({"timeframe": "4h",
                            "entry": {"family": "hma_turn", "params": {"length": 55}}}), "failed", {}, ts=D0)
    low = _add(dconn, a, {"timeframe": "15m", "entry": {"family": "hma_turn", "params": {"length": 55}},
                          "direction": "both"}, kst_at(2, 10))
    got = DF.slot_pick(dconn, a, kst_at(2, 21, 1), 2)
    assert got["queued"] is None and got["not_picked"] == [low] and "1 미만" in _q(dconn, low)[3]


# ------------------------------------------------------------------ read-back and the round trip
class FakeLab:
    def available(self, *a):
        return True

    def bars(self, *a):
        return None


def test_round_trip_pick_intake_run_sync_and_readback(dconn, agents, tmp_path, monkeypatch):
    a, apath = agents
    monkeypatch.setattr(A, "_lab", StubLab(good=False))
    ids = []
    for k, tag in enumerate(LT.SKIP_TAGS[:3]):
        got = DF.check_idea(idea("labtest", test=skip(tag), con_check="①" if k else "⑥"), a, dconn, kst_at(0, 10 + k))
        ids.append(DF.add_idea(dconn, 10 + k, kst_at(0, 10 + k), {"kind": "big_losses", "key": "b",
                                                                  "question_ko": "오늘 큰 손실"}, got))
    assert DF.slot_pick(dconn, a, kst_at(0, 21, 5), 1)["queued"] == ids[0]
    dconn.commit()
    # the agents side: pull the contract read-only, run within the budget (counted in the room), never propose
    ctx = RM.RoundContext(agents_conn=a, paper_ro=None, daily_ro=None, inbox_ro=None, runner=None, lab=FakeLab(),
                          now_ms=kst_at(0, 21, 20), policy=RM.RoomsPolicy(lab_intake_debate_per_day=1),
                          clock_ms=lambda: kst_at(0, 21, 20))
    out = LI.tick(ctx, str(tmp_path / "debate.db"), kst_at(0, 21, 20))
    assert out["pulled"] == 1 and len(out["ran"]) == 1 and R.trial_count(a, room_id=f"strat:{S}") == 1
    card = LI.view(a, "debate")[0]
    assert card["source_ref"] == f"debate:{ids[0]}" and card["meta"]["question_ko"] == "오늘 큰 손실"
    # back on the debate side: the result, the side that was right, the check 반대 named
    ro = P.open_ro(apath)
    assert DF.sync_lab(dconn, ro, kst_at(0, 21, 30)) == 1 and DF.sync_lab(dconn, ro, kst_at(0, 21, 40)) == 0
    row = dconn.execute("SELECT lab_status, lab_trial_id, lab_result_ko, settled_side, con_check_hit FROM "
                        "debate_lab_ideas WHERE id = ?", (ids[0],)).fetchone()
    assert row[0] == "tested" and row[1] == card["trial_id"] and row[2].startswith("불통과")
    assert row[3] == "반대" and row[4] == 0                       # the stub fails only ④, not ⑥ (the check 반대 named)
    rb = DF.readback(dconn, ro, kst_at(0, 21, 40), 1)
    assert rb["goal"] == DF.GOAL_KO and rb["today"] == {"queued": "1/1", "candidates": 0}
    rec = dict(rb["record"])
    assert rec.pop("base_note").startswith("_expected")
    # next to each side's count, what the lab's own rates give (the stub never passes and fails only ④, not ⑥)
    assert rec == {"tested": 1, "passed": 0, "찬성_right": 0, "반대_right": 1, "con_check_hits": 0,
                   "con_check_graded": 1, "찬성_expected": 0.0, "반대_expected": 1.0, "con_check_expected": 0.0}
    assert rb["recent_results"][0]["verdict"] == "failed" and rb["lab"]["tests_so_far"] == 0
    assert P.estimate_tokens(P.compact_json(rb)) <= 700
    ro.close()


def test_readback_shows_each_side_next_to_the_lab_base_rates(dconn, agents):
    """Lab passes are near 0, so 반대 is 'right' almost always by the base rate alone: the record shows what the lab's
    own rates give each side (the pass rate; the usual fail share of the check 반대 named) next to the counts."""
    a, _ = agents
    full = dict.fromkeys("abcdef", True)
    for spec, st, ch in ((SPECS[0], "passed", full), (SPECS[1], "failed", {**full, "f": False}),
                         (SPECS[2], "failed", {**full, "a": False, "f": False}), (SPECS[3], "failed", {**full, "a": False})):
        R.add_trial_with_result(a, R.LAB_ROOM, None, "newlab", NL.normalize_spec(spec), st, {"ledger": {"checks": ch}},
                                ts=D0 - DAY)
    base = LI.base_rates(a)
    assert base["newlab"]["tests"] == 4 and base["newlab"]["pass_rate"] == 0.25
    assert base["newlab"]["fail_share"]["①"] == base["newlab"]["fail_share"]["⑥"] == 0.5
    assert base["labtest"]["tests"] == 0 and LI.base_rates(None)["newlab"]["pass_rate"] is None
    LI.ensure(a)
    for k, (spec, cc) in enumerate(((SPECS[4], "⑥"), (SPECS[5], "①"))):
        iid = DF.add_idea(dconn, k, kst_at(0, 10 + k), None,
                          DF.check_idea(idea(spec=spec, con_check=cc), a, dconn, kst_at(0, 10 + k)))
        got = LI.enqueue(a, "debate", f"debate:{iid}", "newlab", spec, None, "", {}, kst_at(0, 22))
        LI.event(a, got["id"], "tested", kst_at(0, 22, 10 + k), trial_id=None,
                 detail={"engine": "newlab", "verdict": "failed", "failed_checks": ["⑥"]})
    rec = DF.readback(dconn, a, kst_at(0, 23), 1)["record"]
    assert (rec["tested"], rec["반대_right"], rec["찬성_right"]) == (2, 2, 0)
    assert rec["찬성_expected"] == 0.5 and rec["반대_expected"] == 1.5           # 2 tests x the 25 % pass rate
    assert (rec["con_check_hits"], rec["con_check_graded"], rec["con_check_expected"]) == (1, 2, 1.0)


def test_settle_and_the_result_line():
    tested = {"status": "tested", "detail": {"verdict": "passed", "failed_checks": []}}
    assert DF.settle(tested, "⑥") == ("찬성", 0)
    failed = {"status": "tested", "detail": {"verdict": "failed", "failed_checks": ["①", "⑥"]}}
    assert DF.settle(failed, "⑥") == ("반대", 1) and DF.settle(failed, None) == ("반대", None)
    for st in ("duplicate", "reused", "not_counted", "error", "queued"):
        assert DF.settle({"status": st, "detail": failed["detail"]}, "⑥") == (None, None)
    d = {"engine": "newlab", "verdict": "failed", "test_number": 57, "threshold": 0.05 / 57, "failed_checks": ["⑥"],
         "passed_checks": ["①", "②", "③", "④", "⑤"], "p1": {"coinflip_diff": 0.0002, "coinflip_p": 0.41}}
    assert DF.result_line_ko(d) == ("불통과: ⑥ 동전과 차이 1기간 +0.02%p(p=0.41) · 통과한 칸 ①②③④⑤ "
                                    "(새 매매법 시험 #57, 기준 p<0.00088)")


def test_readback_stays_small_with_many_ideas(dconn, agents):
    a, _ = agents
    for k in range(40):
        spec = {"timeframe": "1h", "entry": {"family": list(NL.FAMILIES)[k % 30]}, "direction": "long"} \
            if not NL.FAMILIES[list(NL.FAMILIES)[k % 30]][0] else NOISE
        got = DF.check_idea(idea(spec=spec, claim="긴 주장 " * 40), a, dconn, kst_at(0, 1) + k * MIN)
        DF.add_idea(dconn, k, kst_at(0, 1) + k * MIN, {"kind": "retro", "key": "r", "question_ko": "질문 " * 50}, got)
    rb = DF.readback(dconn, a, kst_at(0, 12), 2)
    assert len(rb["slot_candidates"]) <= 6 and P.estimate_tokens(P.compact_json(rb)) <= 700


def test_the_debate_side_modules_load_no_room_runner_and_no_lab_data_code():
    """Importing the factory, the question bank and the intake's read helpers (what the debate service loads) pulls in
    neither rooms.py, the agents' runner, actions nor triggers, and newlab / labtests only when an idea is checked."""
    import os
    import re
    import subprocess
    import sys
    code = ("import sys, paperbot.agents.debate_factory, paperbot.agents.debate_questions\n"
            "bad = [m for m in ('paperbot.agents.rooms', 'paperbot.agents.runner', 'paperbot.agents.actions', "
            "'paperbot.agents.triggers', 'paperbot.agents.newlab', 'paperbot.agents.labtests') if m in sys.modules]\n"
            "print(','.join(bad))")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "", (r.stdout, r.stderr)
    for name in ("debate_factory.py", "debate_questions.py"):
        src = open(os.path.join(root, "paperbot", "agents", name), encoding="utf-8").read()
        assert "open_agents" not in src and not re.search(r"from \.rooms import|import rooms\b(?!_db)", src), name
