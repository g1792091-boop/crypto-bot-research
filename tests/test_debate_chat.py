"""debate-chat (owners 10/06 13:27: "에이전트 팀들끼리 서로 대화하는게 토론 아니야?"): the 24-hour debate room as a real
back-and-forth (paperbot/agents/debate.py, prompts3/debate_room.md). A fake transport, no network, no real key.

- every round all five roles speak once, then replies: 7 turns by default (DEBATE_TURNS 5-9; an older 3 or 4 is read
  as 5, not a stop), the order names the turns and asks for reply_to / stance from the third turn on;
- the parser keeps reply_to only for someone who already spoke (not the speaker) and the stance only as 동의 / 반대 /
  보완 / 질문, accepts the keys in any order (a cut-off answer keeps its complete turns), and reads an answer in the old
  format as plain turns;
- storage is additive: an older debate.db gains two NULL columns, nothing else changes; the round, the summary and the
  dashboard's /api/debate carry the fields;
- the answer's ceiling and the dry run's output estimate follow the turns, and the estimate stays within a quarter of
  the old 4-turn one (the owners' per-round cost limit for this change).
"""
import json
import os
import sqlite3

import pytest

from debate_world import make_world
from paperbot.agents import debate as D
from test_debate import KEY, NOW, make, ok_body, rows

ROLES = list(D.ROLES)


@pytest.fixture
def world(tmp_path):
    return make_world(tmp_path, NOW, days=10, per_day=60)


def chat_answer(order, replies):
    """A 7-turn answer in the order given; replies: [(reply_to, stance)] per turn."""
    turns = [{"speaker": sp, "reply_to": rt, "stance": st, "text": f"{i + 1}번째 {sp}의 말. 표본 작음."}
             for i, (sp, (rt, st)) in enumerate(zip(order, replies))]
    return {"turns": turns, "note": "표본이 작아 결론은 아직 없다.", "hypotheses": [], "ideas": []}


REPLIES = [(None, None), ("낙관론자", "반대"), ("낙관론자", "질문"), ("비관론자", "보완"), ("회의론자", "동의"),
           ("회의론자", "반대"), ("퀀트", "보완")]


# ---------------------------------------------------------------- order and settings
def test_every_role_speaks_then_they_answer_each_other():
    for n in range(10):
        order = D.roles_for(n, D.TURNS_DEFAULT)
        assert len(order) == 7 and set(order[:5]) == set(ROLES) and order[5:] == order[:2]
    assert D.Config().turns == D.TURNS_DEFAULT == 7
    cfg = D.config_from_env({})
    assert (cfg.turns, cfg.max_tokens, cfg.est_out_tokens) == (7, 1150, 1000)
    assert D.config_from_env({"DEBATE_TURNS": "4"}).turns == 5 and D.config_from_env({"DEBATE_TURNS": "3"}).turns == 5
    assert D.config_from_env({"DEBATE_TURNS": "9"}).turns == 9 and D.config_from_env({"DEBATE_TURNS": "5"}).turns == 5
    for bad in ("10", "2", "x"):
        with pytest.raises(ValueError):
            D.config_from_env({"DEBATE_TURNS": bad})
    # the ceiling follows the turns (thinking on top for a thinking model); the env still wins; 9 turns fit the range
    son = {"DEBATE_MODEL": "claude-sonnet-5-5", "DEBATE_EFFORT": "low"}
    assert D.config_from_env(son).max_tokens == 1750
    assert D.config_from_env({**son, "DEBATE_TURNS": "9"}).max_tokens == 1950 <= 2000
    assert D.config_from_env({"DEBATE_TURNS": "5"}).max_tokens == 950
    assert D.config_from_env({"DEBATE_MAX_TOKENS": "900"}).max_tokens == 900
    # the owners' limit for this change: the output estimate within a quarter of the old 4-turn one (800)
    assert D.est_out_default(7) == 1000 <= 1.25 * 800


def test_the_prompt_asks_for_a_conversation():
    s = D.system_text()
    for w in ("## 대화 방식", '"reply_to"', "`동의`", "`반대`", "`보완`", "`질문`", "셋째 발언부터는 `reply_to`와 `stance`를 반드시",
              "한 번에 2~3문장", "전체 900 토큰 안팎"):
        assert w in s, w
    assert "한 번에 최대 4문장" not in s and "700 토큰" not in s
    from paperbot.agents import debate_packet as P
    assert P.estimate_tokens(s) < 4500                       # still the cached prefix of tests/test_agents_v4_sweep2.py


# ---------------------------------------------------------------- the parser
def test_reply_fields_are_checked_and_old_answers_read_as_plain_turns():
    order = D.roles_for(0, 7)
    reps = [(None, "동의"),                       # the first turn answers nobody: dropped
            ("낙관론자", "반대"), ("회의론자", "동의"),   # 회의론자 has not spoken yet: dropped
            ("리스크 책임자", "보완"),               # itself: dropped
            (" 비관론자 ", "질문 "),                 # spaces are trimmed
            ("퀀트", "몰라"),                       # unknown stance: the target stays, no chip
            ("아무개", "반대")]                      # nobody of that name: dropped
    a = D.parse_answer(json.dumps(chat_answer(order, reps), ensure_ascii=False), order)
    assert [(t["reply_to"], t["reply_stance"]) for t in a["turns"]] == [
        (None, None), ("낙관론자", "반대"), (None, None), (None, None), ("비관론자", "질문"), ("퀀트", None), (None, None)]
    alias = D.parse_answer(json.dumps({"turns": [{"speaker": "퀀트", "text": "a"},
                                                  {"speaker": "낙관론자", "text": "b", "reply_to": "퀀트", "reply_stance": "보완"}]},
                                      ensure_ascii=False), order)
    assert alias["turns"][1]["reply_stance"] == "보완"
    # review: the role's spelling without (or with an extra) space and a stance word with more after it still count;
    # the stored names are the code's own (ROLES), so the dashboard can find the bubble a turn answers
    spell = D.parse_answer(json.dumps({"turns": [
        {"speaker": "리스크책임자", "text": "a"},
        {"speaker": "퀀트", "reply_to": "리스크책임자", "stance": "반대합니다", "text": "b"},
        {"speaker": "낙 관론자", "reply_to": "퀀트", "stance": "보완(조건 하나)", "text": "c"},
        {"speaker": "비관론자", "reply_to": "낙관론자", "stance": "동 의", "text": "d"}]}, ensure_ascii=False), order)
    assert [(t["speaker"], t["reply_to"], t["reply_stance"]) for t in spell["turns"]] == [
        ("리스크 책임자", None, None), ("퀀트", "리스크 책임자", "반대"), ("낙관론자", "퀀트", "보완"),
        ("비관론자", "낙관론자", None)]
    old = D.parse_answer(json.dumps({"turns": [{"speaker": r, "text": "말"} for r in ROLES[:4]], "note": "n"},
                                    ensure_ascii=False), order)
    assert [(t["reply_to"], t["reply_stance"]) for t in old["turns"]] == [(None, None)] * 4 and old["note"] == "n"


def test_a_cut_answer_keeps_its_complete_turns_in_any_key_order():
    order = D.roles_for(0, 7)
    text = json.dumps(chat_answer(order, REPLIES), ensure_ascii=False)
    # keys in another order than the prompt's, then cut inside the fifth turn
    text = text.replace('"speaker": "회의론자", "reply_to": "낙관론자", "stance": "질문", ',
                        '"stance": "질문", "reply_to": "낙관론자", "speaker": "회의론자", ')
    cut = text[:text.index("5번째")]
    got = D.parse_answer(cut, order)
    assert got["truncated"] and [t["speaker"] for t in got["turns"]] == order[:4]
    assert [(t["reply_to"], t["reply_stance"]) for t in got["turns"]] == REPLIES[:4]
    # a complete answer followed by text that holds a brace: the whole answer is used (note kept, not "cut")
    whole = D.parse_answer(text + " 끝} 이상", order)
    assert not whole["truncated"] and len(whole["turns"]) == 7 and whole["note"]
    prefixed = D.parse_answer("설명 {예시} " + text + " 끝} 이상", order)                    # braces before it too
    assert not prefixed["truncated"] and len(prefixed["turns"]) == 7 and prefixed["note"]


# ---------------------------------------------------------------- storage, summary, dashboard
def test_a_round_stores_who_answers_whom_and_every_reader_passes_it_on(tmp_path, world):
    order = D.roles_for(0, 7)
    svc = make(tmp_path, world, ok_body(chat_answer(order, REPLIES)), turns=7)
    assert svc.tick(force=True) == "round"
    got = rows(svc, "SELECT speaker, reply_to, reply_stance FROM debate_messages ORDER BY id")
    assert got[:7] == [(sp, rt, st) for sp, (rt, st) in zip(order, REPLIES)] and got[7] == ("정리", None, None)
    assert rows(svc, "SELECT turns FROM debate_rounds")[0][0] == 7
    assert "발언 7개(누구에게 답했는지 적힌 것 6개)" in svc.logs[-1]
    body = svc.fake.calls[0][2]
    assert "7. 비관론자" in body["messages"][0]["content"] and "## 대화 방식" in body["system"][0]["text"]
    svc.db.close()
    s = D.summary(svc.cfg.debate_db, NOW + 30_000)
    m = s["rounds"][0]["messages"]
    assert (m[1]["reply_to"], m[1]["reply_stance"]) == ("낙관론자", "반대") and m[0]["reply_to"] is None
    from paperbot.dash import analysis as AN
    d = AN.debate(svc.cfg.debate_db, now_ms=NOW + 30_000)
    assert [(x["reply_to"], x["reply_stance"]) for x in d["chat"][0]["messages"][:7]] == REPLIES


def test_an_older_debate_db_only_gains_two_empty_columns(tmp_path):
    path = str(tmp_path / "debate.db")
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE debate_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, "
                    "round_id INTEGER, speaker TEXT NOT NULL, stance TEXT, topic TEXT, text TEXT NOT NULL);"
                    "CREATE TABLE debate_rounds (round_id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, topic TEXT, "
                    "in_tokens INTEGER NOT NULL DEFAULT 0, out_tokens INTEGER NOT NULL DEFAULT 0, cache_read INTEGER NOT NULL "
                    "DEFAULT 0, cache_write INTEGER NOT NULL DEFAULT 0, cost_usd REAL NOT NULL DEFAULT 0, status TEXT NOT NULL, "
                    "error TEXT, model TEXT, turns INTEGER NOT NULL DEFAULT 0);"
                    "CREATE TABLE debate_hypotheses (id INTEGER PRIMARY KEY AUTOINCREMENT, round_id INTEGER, ts INTEGER "
                    "NOT NULL, speaker TEXT, kind TEXT, params_json TEXT, horizon TEXT, status TEXT NOT NULL, outcome TEXT, "
                    "graded_ts INTEGER);"
                    "CREATE TABLE debate_ideas (id INTEGER PRIMARY KEY AUTOINCREMENT, round_id INTEGER, ts INTEGER NOT NULL, "
                    "text TEXT NOT NULL, tag TEXT, status TEXT NOT NULL DEFAULT 'new');"
                    "CREATE TABLE debate_state (k TEXT PRIMARY KEY, v TEXT);")
    c.execute("INSERT INTO debate_rounds (ts, topic, status, turns) VALUES (?, '주제', 'ok', 2)", (NOW,))
    for sp in ("낙관론자", "비관론자"):
        c.execute("INSERT INTO debate_messages (ts, round_id, speaker, stance, topic, text) VALUES (?, 1, ?, '', '주제', '말')",
                  (NOW, sp))
    c.execute("INSERT INTO debate_state (k, v) VALUES ('heartbeat', ?)", (json.dumps(NOW),))
    c.commit()
    c.close()
    # read before the service opened it (the dashboard updated first): plain turns, no error
    s = D.summary(path, NOW)
    assert s["ready"] and s["rounds"][0]["messages"][1]["reply_to"] is None
    db = D.DB(path)                                                     # the service opens it: two columns added
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info(debate_messages)")]
    assert cols == ["id", "ts", "round_id", "speaker", "stance", "topic", "text", "reply_to", "reply_stance"]
    assert db.conn.execute("SELECT speaker, text, reply_to, reply_stance FROM debate_messages ORDER BY id").fetchall() == [
        ("낙관론자", "말", None, None), ("비관론자", "말", None, None)]
    db.close()
    D.DB(path).close()                                                  # opening again changes nothing
    assert D.summary(path, NOW)["rounds"][0]["messages"][0] == {"speaker": "낙관론자", "stance": "", "text": "말",
                                                                 "reply_to": None, "reply_stance": None}
    _ = os
