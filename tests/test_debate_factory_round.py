"""The idea factory's round in the debate service (paperbot/agents/debate.py DEBATE_MODE=factory) and the daily deep
debate. A fake transport everywhere: no network, no real key.

- settings: classic stays the default (the rollback) and its prompt, request and ceiling are unchanged; factory mode
  raises the ceiling by the idea's 250 tokens; DEBATE_MAX_TOKENS goes to 3000; bad values stop the service;
- a factory round: code's question, code's sides on every stored turn (the model's own label ignored), the one lab
  idea checked and stored, the round's question and idea id, the per-key / rotation / coverage records;
- a missing or cut idea leaves the round ok with check_status 'missing' (a complete idea in a cut answer is kept);
- no fresh question: a free 'no_question' skip, no call; the forced round still runs;
- upkeep: the daily pick hands the idea to the lab intake contract, the lab's result comes back and settles the side;
- the deep debate: three calls to Opus 5.5 sharing the cached prefix, each reading the earlier parts; one round of kind
  'deep' with its parts; its money on the month and on its own line; caps, failures and the once-a-day rule;
- the rename: old rows keep the names they were stored with; the grep gate: never rooms.py, agents3 only read-only.
"""
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from paperbot.agents import debate as D
from paperbot.agents import debate_factory as DF
from paperbot.agents import debate_grade as G
from paperbot.agents import debate_questions as DQ
from paperbot.agents import labintake as LI
from paperbot.agents import rooms_db as R
from paperbot.notify import ListNotifier

import test_debate_questions as TQ
from test_debate import KEY, Clock, Fake, err_body, ok_body

NOW = TQ.NOW                                         # 2026-10-15 23:00 KST
HOUR, MIN, DAY = 3_600_000, 60_000, 86_400_000
AT_2005 = NOW - 3 * HOUR + 5 * MIN                   # 20:05 KST: the deep debate is due
NEWLAB_IDEA = {"engine": "newlab", "spec": {"timeframe": "4h", "entry": {"family": "obv_cross"}, "direction": "long"},
               "claim": "주장", "pro": "찬성 근거", "con": "반대 근거", "con_check": "⑥", "backs": None, "weak": []}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return TQ.rich_world(tmp_path_factory.mktemp("factory_round"))


def env_for(world, tmp_path, **over):
    env = {"ANTHROPIC_API_KEY": KEY, "DEBATE_MODEL": "claude-sonnet-5-5", "DEBATE_EFFORT": "low",
           "DEBATE_MODE": "factory", "DEBATE_MONTHLY_USD_CAP": "70", "DEBATE_DAILY_USD_CAP": "3",
           "DEBATE_PAPER_DB": world["paper"], "DEBATE_DAILY_DB": world["daily"], "DEBATE_AGENTS_DB": world["agents"],
           "DEBATE_CHECKPOINT_DB": str(tmp_path / "no_cp.db"), "DEBATE_DIR": str(tmp_path / "debate")}
    env.update({k: str(v) for k, v in over.items()})
    return {k: v for k, v in env.items() if v != "None"}


def service(cfg, *answers, at=NOW):
    db = D.DB(cfg.debate_db)
    fake, logs = Fake(*answers), []
    svc = D.Service(cfg, db, ListNotifier(), transport=fake, clock=Clock(at), sleep=lambda s: None, out=logs.append)
    svc.start()
    svc.fake, svc.logs = fake, logs
    return svc


def factory_answer(n=0, turns=7, idea=NEWLAB_IDEA, labels=None):
    order = DF.factory_order(n, turns)
    out = {"turns": [{"speaker": s, "reply_to": None if i < 2 else order[0], "stance": None if i < 2 else "반대",
                      "text": f"{i + 1}번째 {s}의 말. 표본 작음."} for i, s in enumerate(order)],
           "note": "정리 한 줄", "hypotheses": []}
    if labels:                                          # the model writes its own side labels: ignored
        for t, lab in zip(out["turns"], labels):
            t["side"] = lab
    if idea is not None:
        out = {"turns": out["turns"], "lab_idea": idea, "note": out["note"], "hypotheses": []}
    return out


def rows(svc, sql, *a):
    return svc.db.conn.execute(sql, a).fetchall()


# ------------------------------------------------------------------ settings
def test_classic_is_the_default_and_unchanged_factory_raises_the_ceiling():
    c = D.config_from_env({})
    assert (c.mode, c.turns, c.max_tokens, c.est_out_tokens) == ("classic", 7, 1150, 1000)
    son = {"DEBATE_MODEL": "claude-sonnet-5-5", "DEBATE_EFFORT": "low"}
    assert D.config_from_env(son).max_tokens == 1750
    f = D.config_from_env({**son, "DEBATE_MODE": "factory"})
    assert (f.mode, f.max_tokens, f.est_out_tokens, f.lab_per_day, f.deep) == ("factory", 2000, 1250, 2, False)
    assert D.config_from_env({"DEBATE_MODE": "factory"}).max_tokens == 1400                  # Haiku: no thinking room
    assert D.config_from_env({**son, "DEBATE_MODE": "factory", "DEBATE_TURNS": "9"}).max_tokens == 2200 <= 3000
    assert D.config_from_env({"DEBATE_MAX_TOKENS": "3000"}).max_tokens == 3000
    deep = D.config_from_env({"DEBATE_MODE": "factory", "DEBATE_DEEP": "1", "DEBATE_DEEP_AT": "7:30"})
    assert (deep.deep, deep.deep_model, deep.deep_at, deep.deep_effort, deep.deep_monthly_cap) == (
        True, "claude-opus-5-5", "07:30", "low", 10.0)
    assert deep.deep_config().cache_ttl() == "5m" and deep.deep_config().cache_read_mult() == 0.05
    for bad in ({"DEBATE_MODE": "lab"}, {"DEBATE_MAX_TOKENS": "3001"}, {"DEBATE_LAB_PER_DAY": "3"},
                {"DEBATE_DEEP": "yes"}, {"DEBATE_DEEP_AT": "25:00"}, {"DEBATE_DEEP_EFFORT": "max"},
                {"DEBATE_DEEP": "1", "DEBATE_DEEP_MODEL": "claude-haiku-4-5-20251001", "DEBATE_DEEP_EFFORT": "low"}):
        with pytest.raises(ValueError):
            D.config_from_env(bad)


def test_the_classic_prompt_is_byte_for_byte_the_old_one_and_shares_its_rules_with_the_factory():
    classic = D.system_text()
    assert classic == D.system_text("classic") and "아이디어 공장" not in classic and "lab_idea" not in classic
    with open(D.PROMPT, encoding="utf-8") as fh:
        raw = fh.read()
    assert "낙관론자" in raw and "lab_idea" not in raw                                   # the classic file is untouched
    fac = D.system_text("factory")
    assert "## 아이디어 공장" in fac and "새 매매법 문법(newlab-v1)" in fac and "관문(모두 통과)" in fac
    assert "timeframe_only" not in fac.split("## 36개 고쳐 보기 틀")[1].split("## 관문")[0]       # refused template
    for seat in DF.ROLES:
        assert f"- {seat}:" in fac
    assert "낙관론자" not in fac
    # the shared sections (data rules, the run's facts) are word for word the classic ones
    with open(D.PROMPT_FACTORY, encoding="utf-8") as fh:
        fraw = fh.read()

    def section(text, head):
        return text.split(head, 1)[1].split("\n## ", 1)[0]
    for head in ("## 자료\n", "## 이번 실행의 규칙"):
        assert section(raw, head) == section(fraw, head), head
    assert D.prompt_version("classic") != D.prompt_version("factory")


# ------------------------------------------------------------------ the factory round
def test_a_factory_round_stores_the_question_the_code_sides_and_the_checked_idea(world, tmp_path):
    cfg = D.config_from_env(env_for(world, tmp_path))
    labels = ["반대", "찬성"] * 4                                  # the model's own side labels: never used
    svc = service(cfg, ok_body(factory_answer(labels=labels)))
    assert svc.tick() == "round"
    body = svc.fake.calls[0][2]
    assert body["max_tokens"] == 2000 and body["output_config"] == {"effort": "low"}
    assert body["system"][0]["text"] == D.system_text("factory")
    user = body["messages"][0]["content"]
    rid, kind, qkind, qkey, qko, iid = rows(svc, "SELECT round_id, kind, question_kind, question_key, question_ko, "
                                                  "lab_idea_id FROM debate_rounds WHERE status = 'ok'")[0]
    assert kind == "factory" and qkind == "event" and qko in user and DF.sides_text(0) in user
    assert "7. 심판(심판)" in user and "lab_idea 하나를 꼭" in user
    sides = DF.sides_for(0)
    msgs = rows(svc, "SELECT speaker, side, stance, reply_to FROM debate_messages WHERE round_id = ? ORDER BY id", rid)
    turns = [m for m in msgs if m[0] != D.NOTE_SPEAKER]
    assert [m[0] for m in turns] == DF.factory_order(0, 7)
    assert all(m[1] == sides[m[0]] for m in turns) and turns[-1][:2] == ("심판", "심판")
    assert {m[2] for m in turns} <= set(D.FACTORY_STANCE.values())
    idea = rows(svc, "SELECT id, round_id, engine, check_status, queue_status, round_kind, question_kind, question_key, "
                     "con_check, description_ko FROM debate_lab_ideas")[0]
    assert idea[:8] == (iid, rid, "newlab", "ok", "candidate", "factory", qkind, qkey) and idea[8] == "⑥"
    assert "obv_cross" in idea[9]
    asked = svc.db.asked()
    assert asked[qkey]["n"] == 1 and svc.db.get("last_question_kind") == qkind
    assert svc.db.get("covered") == {"S5_DONCHIAN_MFI": NOW}                     # an event names one strategy: its turn
    s = D.summary(cfg.debate_db, NOW)
    m = s["rounds"][0]["messages"]
    assert s["rounds"][0]["kind"] == "factory" and m[0]["side"] == sides[m[0]["speaker"]] and "part" not in m[0]
    assert s["factory"]["ideas"][0]["check_status_ko"] == "시험 후보" and s["factory"]["today"]["candidates"] == 1


def test_a_missing_or_cut_idea_leaves_the_round_ok_and_says_so(world, tmp_path):
    cfg = D.config_from_env(env_for(world, tmp_path))
    no_idea = factory_answer(idea=None)
    full = json.dumps(factory_answer(), ensure_ascii=False)
    cut_after_idea = full[:full.index('"note"')]                     # cut at max_tokens right after the idea
    cut_before = json.dumps(factory_answer(), ensure_ascii=False)
    cut_before = cut_before[:cut_before.index('"lab_idea"') + 30]
    svc = service(cfg, ok_body(no_idea))
    assert svc.tick() == "round"
    for text in (cut_after_idea, cut_before):
        svc.fake.answers.append((200, {}, json.dumps({"content": [{"type": "text", "text": text}], "usage": {
            "input_tokens": 1, "output_tokens": 1}, "stop_reason": "max_tokens"}).encode()))
        svc.fake.answers.pop(0)
        assert svc.tick(force=True) == "round"
    got = rows(svc, "SELECT check_status FROM debate_lab_ideas ORDER BY id")
    assert [g[0] for g in got] == ["missing", "ok", "missing"]
    assert [r[0] for r in rows(svc, "SELECT status FROM debate_rounds WHERE kind = 'factory' ORDER BY round_id")] == [
        "ok", "ok", "ok"]
    # the parser alone: the code's sides, the model's label ignored, at most one hypothesis
    order, sides = DF.factory_order(3, 7), DF.sides_for(3)
    ans = D.parse_answer(json.dumps({**factory_answer(3, labels=["심판"] * 7), "hypotheses": [{}, {}]},
                                    ensure_ascii=False), order, factory=True, sides=sides)
    assert [t["side"] for t in ans["turns"]] == [sides[s] for s in order] and len(ans["hypotheses"]) == 1
    assert ans["ideas"] == [] and ans["lab_idea"]["engine"] == "newlab"


def test_no_fresh_question_is_a_free_skip_and_the_forced_round_still_asks(world, tmp_path):
    cfg = D.config_from_env(env_for(world, tmp_path))
    svc = service(cfg, ok_body(factory_answer()))
    _board, cands = svc._question_bank(NOW)
    for q in cands:                                                      # every question asked 3 times today
        svc.db.put(f"asked:{q.key}", {"day": DQ.kst_day(NOW), "n": DQ.MAX_ASKS_A_DAY, "ts": NOW, "kind": q.kind})
    assert svc.tick() == "skipped" and svc.fake.calls == []
    r = rows(svc, "SELECT status, kind, error, cost_usd FROM debate_rounds ORDER BY round_id DESC LIMIT 1")[0]
    assert r[:2] == ("skipped", "factory") and r[2].startswith("no_question:") and r[3] == 0
    assert svc.db.spent(NOW)["month"] == 0
    # the 6-hour forced round (or `once`) is never a skip: it asks the retro question
    for q in cands:
        if q.kind == "retro":
            svc.db.delete(f"asked:{q.key}")
    assert svc.tick(force=True) == "round"
    assert rows(svc, "SELECT question_kind FROM debate_rounds WHERE status = 'ok'")[0][0] == "retro"


def test_the_daily_pick_hands_the_idea_to_the_lab_and_the_result_comes_back(world, tmp_path):
    """slot_pick (debate side) -> labintake.pull_debate's contract (agents side) -> a counted test's result -> sync_lab
    -> the settled side and the check 반대 named, in the summary and the scoreboard."""
    cfg = D.config_from_env(env_for(world, tmp_path, DEBATE_LAB_PER_DAY=1, DEBATE_AGENTS_DB=tmp_path / "agents3.db"))
    a = R.open_agents(str(tmp_path / "agents3.db"))
    R.ensure_rooms(a, ts=NOW - DAY)
    LI.ensure(a)
    svc = service(cfg, ok_body(factory_answer()), at=NOW - 6 * HOUR)          # 17:00 KST
    assert svc.tick() == "round"
    iid = rows(svc, "SELECT id FROM debate_lab_ideas")[0][0]
    svc.clock.t = NOW - 2 * HOUR + MIN                                        # 21:01 KST: the slot has closed
    svc.factory_upkeep(svc.clock.t)
    assert rows(svc, "SELECT queue_status, slot FROM debate_lab_ideas")[0][0] == "queued"
    ro = sqlite3.connect(f"file:{cfg.debate_db}?mode=ro", uri=True)
    pulled = ro.execute(LI.DEBATE_SQL, (svc.clock.t - 3 * DAY,)).fetchall()       # the agents side's contract
    ro.close()
    assert [p[0] for p in pulled] == [iid] and pulled[0][3] == "newlab"
    got = LI.enqueue(a, "debate", f"debate:{iid}", "newlab", json.loads(pulled[0][5]), None, "주장", {}, svc.clock.t)
    detail = {"engine": "newlab", "verdict": "failed", "failed_checks": ["⑥"], "passed_checks": ["①"],
              "test_number": 3, "threshold": 0.0125}
    LI.event(a, got["id"], "tested", svc.clock.t + MIN, trial_id=7, detail=detail)
    svc.clock.t += 20 * MIN
    svc.factory_upkeep(svc.clock.t)
    st, trial, side, hit, line = rows(svc, "SELECT lab_status, lab_trial_id, settled_side, con_check_hit, lab_result_ko "
                                           "FROM debate_lab_ideas")[0]
    assert (st, trial, side, hit) == ("tested", 7, "반대", 1) and line.startswith("불통과")
    rec = G.scoreboard(svc.db.conn)["factory"]
    assert (rec["tested"], rec["반대_right"], rec["찬성_right"], rec["con_check_hits"]) == (1, 1, 0, 1)
    assert rec["base_rates_known"] and "사람 성적이 아님" in rec["note"]
    assert D.summary(cfg.debate_db, svc.clock.t)["factory"]["ideas"][0]["lab_status_ko"] == "시험함"
    a.close()


def test_classic_mode_keeps_the_classic_round_and_only_lets_queued_results_come_back(world, tmp_path):
    cfg = D.config_from_env(env_for(world, tmp_path, DEBATE_MODE="classic", DEBATE_DEEP=1))
    from test_debate import answer
    svc = service(cfg, ok_body(answer(turns=7)), at=AT_2005)
    assert svc.tick() == "round"                                             # no deep debate in classic mode
    body = svc.fake.calls[0][2]
    assert body["system"][0]["text"] == D.system_text() and "회차 0번. 주제:" in body["messages"][0]["content"]
    assert rows(svc, "SELECT kind, question_kind FROM debate_rounds") == [(None, None)]
    assert rows(svc, "SELECT side, part FROM debate_messages LIMIT 1") == [(None, None)]
    assert svc.factory_upkeep(AT_2005) == {}                                 # nothing queued: nothing read
    assert "factory" not in D.summary(cfg.debate_db, AT_2005)                # a classic room shows no factory block
    assert "mode" not in svc.db.get("run")                                   # the classic run state, as before


# ------------------------------------------------------------------ the daily deep debate
def deep_answers(k=0, idea=None, con_check="⑥"):
    sides = DF.sides_for(k)
    pro = [r for r in DF.ROLES if sides[r] == "찬성"]
    con = [r for r in DF.ROLES if sides[r] == "반대"]
    u1 = {"input_tokens": 400, "output_tokens": 800, "cache_creation_input_tokens": 9000, "cache_read_input_tokens": 0}
    u2 = {"input_tokens": 1200, "output_tokens": 900, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 9000}
    idea = idea or {"engine": "labtest", "test": {"template": "skip_tag", "strategy": "N17_KC_RSI", "timeframe": "1h",
                                                  "tag": "추세 반대 진입"}, "claim": "c", "pro": "p", "con": "n"}
    return (ok_body({"turns": [{"speaker": pro[0], "text": "주장 하나"}, {"speaker": pro[1], "text": "주장 둘"}]}, u1),
            ok_body({"turns": [{"speaker": con[0], "text": "반박 하나"}, {"speaker": con[1], "text": "반박 둘"}],
                     "con_check": con_check}, u2),
            ok_body({"turns": [{"speaker": "심판", "text": "심판의 말"}], "lab_idea": idea, "note": "깊은 정리"}, u2))


def test_the_deep_debate_is_three_calls_reading_each_other_once_a_day(world, tmp_path):
    cfg = D.config_from_env(env_for(world, tmp_path, DEBATE_DEEP=1))
    svc = service(cfg, *deep_answers(), at=AT_2005 - 10 * MIN)
    assert not svc.deep_due(svc.clock.t)                                     # 19:55: not yet
    svc.clock.t = AT_2005
    assert svc.deep_due(AT_2005) and svc.tick() == "deep"
    calls = [c[2] for c in svc.fake.calls]
    assert len(calls) == 3 and {c["model"] for c in calls} == {"claude-opus-5-5"}
    assert all(c["max_tokens"] == 4000 and c["output_config"] == {"effort": "low"} and "thinking" not in c
               for c in calls)
    assert len({c["system"][0]["text"] for c in calls}) == 1 and "## 깊은 토론" in calls[0]["system"][0]["text"]
    heads = [c["messages"][0]["content"][0] for c in calls]
    assert all(h == heads[0] for h in heads) and heads[0]["cache_control"] == {"type": "ephemeral"}   # 5-minute cache
    parts = [c["messages"][0]["content"][1]["text"] for c in calls]
    assert "1/3 주장" in parts[0] and "[주장]" not in parts[0]
    assert "2/3 반박" in parts[1] and "[주장] " in parts[1] and "주장 둘" in parts[1]
    assert "3/3 심판" in parts[2] and "반박 하나" in parts[2] and "주장 하나" in parts[2]
    rid, kind, model, status, turns, cost, iid = rows(svc, "SELECT round_id, kind, model, status, turns, cost_usd, "
                                                           "lab_idea_id FROM debate_rounds")[0]
    assert (kind, model, status, turns) == ("deep", "claude-opus-5-5", "ok", 5) and cost > 0
    msgs = rows(svc, "SELECT speaker, side, part FROM debate_messages WHERE round_id = ? ORDER BY id", rid)
    assert [m[2] for m in msgs[:5]] == ["주장", "주장", "반박", "반박", "심판"] and msgs[5][0] == D.NOTE_SPEAKER
    assert all(m[1] == DF.sides_for(0)[m[0]] for m in msgs[:5])
    idea = rows(svc, "SELECT id, check_status, con_check, round_kind FROM debate_lab_ideas")[0]
    assert idea == (iid, "ok", "⑥", "deep")                    # the check 반대 named in part 2, the judge left it out
    assert svc.db.deep_spent(AT_2005) == pytest.approx(cost) and svc.db.spent(AT_2005)["month"] == pytest.approx(cost)
    assert not svc.deep_due(AT_2005 + HOUR) and svc.db.get("deep_seq") == 1  # once a day
    s = D.summary(cfg.debate_db, AT_2005)
    assert s["factory"]["deep"]["last"]["status"] == "ok" and s["avg_round"]["rounds_7d"] == 0   # not in the average
    # the next KST day it is due again (after its hour)
    assert svc.deep_due(AT_2005 + DAY)


def test_the_deep_debate_stops_at_its_own_line_and_retries_a_failed_call_once(world, tmp_path):
    cfg = D.config_from_env(env_for(world, tmp_path, DEBATE_DEEP=1, DEBATE_DEEP_MONTHLY_USD_CAP=0.2))
    svc = service(cfg, *deep_answers(), at=AT_2005)
    assert svc.tick() == "deep_cap" and svc.fake.calls == []                    # its worst case passes its line
    r = rows(svc, "SELECT status, kind, error, cost_usd FROM debate_rounds")[0]
    assert r[:2] == ("skipped", "deep") and r[2].startswith("deep_cap") and r[3] == 0
    assert not svc.deep_due(AT_2005 + HOUR)                                     # done for the day
    # a failure in part 2: the round ends with what it has (part 1's money counted), tried once more 30 minutes later
    cfg2 = D.config_from_env(env_for(world, tmp_path / "b", DEBATE_DEEP=1))
    a1, a2, a3 = deep_answers()
    svc2 = service(cfg2, a1, err_body(500, "api_error", "boom"), err_body(500, "api_error", "boom"),
                   err_body(500, "api_error", "boom"), a1, a2, a3, at=AT_2005)
    svc2.cfg.retries = 2
    assert svc2.tick() == "error"
    r = rows(svc2, "SELECT status, error, cost_usd, turns FROM debate_rounds")[0]
    assert r[0] == "error" and r[1].startswith("반박: server") and r[2] > 0 and r[3] == 2
    assert svc2.db.deep_spent(AT_2005) == pytest.approx(r[2])
    assert not svc2.deep_due(AT_2005 + 10 * MIN)                                # backoff / 30 minutes
    later = AT_2005 + 31 * MIN
    svc2.db.delete("backoff:until")
    svc2.clock.t = later
    assert svc2.deep_due(later) and svc2.tick() == "deep"
    assert not svc2.deep_due(later + 31 * MIN)                                  # done (2 attempts at most anyway)


# ------------------------------------------------------------------ the rename, the read-back, the gates
def test_old_rows_keep_their_stored_names_next_to_the_specialists(world, tmp_path):
    from test_debate import answer
    classic = D.config_from_env(env_for(world, tmp_path, DEBATE_MODE="classic"))
    svc = service(classic, ok_body(answer(turns=7)))
    assert svc.tick() == "round"
    svc.db.close()
    fac = D.config_from_env(env_for(world, tmp_path))
    svc2 = service(fac, ok_body(factory_answer(1)), at=NOW + HOUR)
    svc2.db.put("round_seq", 1)
    assert svc2.tick(force=True) == "round"
    s = D.summary(fac.debate_db, NOW + HOUR)
    new, old = s["rounds"][0], s["rounds"][1]
    assert {m["speaker"] for m in old["messages"]} - {D.NOTE_SPEAKER} <= set(D.ROLES)
    assert all("side" not in m for m in old["messages"]) and "kind" not in old
    assert {m["speaker"] for m in new["messages"]} - {D.NOTE_SPEAKER} == set(D.FACTORY_ROLES)
    assert new["kind"] == "factory"


def test_the_read_back_reaches_the_next_packet(world, tmp_path):
    cfg = D.config_from_env(env_for(world, tmp_path))
    svc = service(cfg, ok_body(factory_answer()), ok_body(factory_answer(1)))
    assert svc.tick() == "round"
    svc.clock.t += 21 * MIN
    assert svc.tick(force=True) == "round"
    user = svc.fake.calls[1][2]["messages"][0]["content"]
    pk = json.loads(user.split("자료(JSON)입니다.\n", 1)[1])
    assert pk["idea_factory"]["goal"] == DF.GOAL_KO and pk["idea_factory"]["slot_candidates"][0]["id"] == 1
    assert pk["question"]["question_ko"] and "market" in pk and "note" in pk["market"]
    assert svc.db.get("last_question_kind") != rows(svc, "SELECT question_kind FROM debate_rounds WHERE round_id = 1")[0][0]


def test_the_debate_service_never_loads_rooms_and_reads_agents3_read_only(world, tmp_path):
    """The grep gate: a factory round, the upkeep and the deep debate (in a fresh process) never import rooms.py, the
    agents' runner, actions or triggers; the only databases debate.py opens itself are debate.db and an in-memory one."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (
        "import sys, json\n"
        f"sys.path.insert(0, {os.path.join(root, 'tests')!r})\n"
        "from test_debate import Fake, Clock, ok_body, KEY\n"
        "from test_debate_factory_round import factory_answer, deep_answers, env_for, AT_2005\n"
        "from paperbot.agents import debate as D\n"
        "import pathlib\n"
        f"w = json.loads({json.dumps(json.dumps({k: str(v) for k, v in world.items()}))})\n"
        f"cfg = D.config_from_env(env_for(w, pathlib.Path({str(tmp_path)!r}), DEBATE_DEEP=1))\n"
        "db = D.DB(cfg.debate_db)\n"
        "svc = D.Service(cfg, db, None, transport=Fake(ok_body(factory_answer()), *deep_answers()), "
        "clock=Clock(AT_2005 - 3600000), sleep=lambda s: None, out=lambda s: None)\n"
        "svc.start(); r1 = svc.tick(); svc.factory_upkeep(AT_2005); svc.clock.t = AT_2005; r2 = svc.tick()\n"
        "bad = [m for m in ('paperbot.agents.rooms', 'paperbot.agents.runner', 'paperbot.agents.actions', "
        "'paperbot.agents.triggers') if m in sys.modules]\n"
        "print(r1, r2, ','.join(bad))\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root, timeout=120)
    assert r.returncode == 0 and r.stdout.split() == ["round", "deep"], (r.stdout, r.stderr[-2000:])
    src = open(D.__file__, encoding="utf-8").read()
    import re
    assert not re.search(r"from \.rooms import|import rooms\b(?!_db)", src) and "open_agents" not in src
    assert re.findall(r"sqlite3\.connect\(([^,)]+)", src) == ["path", '":memory:"']      # debate.db, scratch
    assert len(re.findall(r"P\.open_ro\([\w.]*agents_db\)", src)) >= 3                    # agents3: read-only opens
    for f in ("debate_factory.py", "debate_questions.py", "debate_packet.py"):
        other = open(os.path.join(os.path.dirname(D.__file__), f), encoding="utf-8").read()
        assert "sqlite3.connect(" not in other.replace("sqlite3.connect(base + flags", ""), f


def test_the_dry_run_prints_the_factory_sizes_and_the_month_with_the_deep_debate(world, tmp_path):
    cfg = D.config_from_env(env_for(world, tmp_path, DEBATE_DEEP=1, DEBATE_EVERY_MIN=20, ANTHROPIC_API_KEY=None))
    lines = []
    assert D.dry_run(cfg, now_ms=NOW, out=lines.append) == 0
    text = "\n".join(lines)
    assert "고정 앞부분(규칙·자리·연구실 문법·관문·메뉴, 캐시 대상)" in text and "질문 종류별 요청 크기" in text
    for kind in DQ.KINDS:
        assert DQ.KIND_KO[kind] in text, kind
    assert "깊은 토론(하루 한 번 20:00, claude-opus-5-5, 3번 호출" in text and "합계 한 달 약 $" in text
    est = D.estimate_factory(cfg, 6400, 2700, 6600, 2200)
    assert 0.015 < est["per_round"] < 0.03 and est["rounds_month"] == 2160
    assert 40 < est["month_thinking"] < 60 and est["deep"]["month"] <= cfg.deep_monthly_cap
    assert est["total_month"] < cfg.monthly_cap                                        # the owners' $70 cap
    assert not os.path.exists(cfg.debate_db)                                            # nothing written
