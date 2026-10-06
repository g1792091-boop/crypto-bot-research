"""Review fixes on the idea factory (factory-round): the deep debate is once a KST day also by hand, each deep part keeps
its own seats, the day and hour guards count the round's worst case, the loss-traits question reads only what was
known at entry, a classic debate.db keeps its scoreboard, and one broken question kind never stops the bank."""
import sqlite3

import pytest

from paperbot.agents import debate as D
from paperbot.agents import debate_factory as DF
from paperbot.agents import debate_grade as G
from paperbot.agents import debate_questions as DQ

import test_debate_factory_round as TF
import test_debate_questions as TQ
from test_debate import ok_body


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return TQ.rich_world(tmp_path_factory.mktemp("factory_review"))


def test_once_deep_runs_the_deep_debate_once_a_day_and_says_so(world, tmp_path, capsys):
    cfg = D.config_from_env(TF.env_for(world, tmp_path, DEBATE_DEEP=1))
    svc = TF.service(cfg, *TF.deep_answers(), *TF.deep_answers(1), at=TF.AT_2005 - 5 * TF.HOUR)   # 15:05 KST
    assert svc.deep_round(svc.clock.t) == "deep" and len(svc.fake.calls) == 3      # by hand, before 20:00
    assert svc.deep_round(svc.clock.t + TF.HOUR) == "deep_done" and len(svc.fake.calls) == 3       # no second call
    assert not svc.deep_due(TF.AT_2005)                                              # 20:00 does not run it again
    assert svc.db.conn.execute("SELECT COUNT(*) FROM debate_rounds WHERE kind = 'deep'").fetchone()[0] == 1
    assert svc.deep_due(TF.AT_2005 + TF.DAY)                                         # the next KST day it is due
    # the command line (the real clock): a day already done says why and exits 1, no call
    svc.db.put(f"deep:{D.kst_day(D._now_ms())}", {"day": D.kst_day(D._now_ms()), "done": True})
    svc.db.close()
    fake = TF.Fake()
    assert D.main(["once", "--deep"], environ=TF.env_for(world, tmp_path, DEBATE_DEEP=1), transport=fake,
                  out=lambda s: None) == 1
    assert fake.calls == [] and "하루 한 번만" in capsys.readouterr().err


def test_each_deep_part_keeps_its_own_seats_whatever_names_the_model_writes(world, tmp_path):
    sides = DF.sides_for(0)
    pro = [r for r in DF.ROLES if sides[r] == "찬성"]
    con = [r for r in DF.ROLES if sides[r] == "반대"]
    # part 1 answered by a 반대 seat and the judge, part 2 by one 반대 seat twice
    got = D.parse_deep_part('{"turns": [{"speaker": "%s", "text": "a"}, {"speaker": "심판", "text": "b"}]}' % con[0],
                            0, sides)
    assert [(t["speaker"], t["side"], t["part"]) for t in got["turns"]] == [(pro[0], "찬성", "주장"),
                                                                             (pro[1], "찬성", "주장")]
    got = D.parse_deep_part('{"turns": [{"speaker": "%s", "text": "a"}, {"speaker": "%s", "text": "b"}], '
                            '"con_check": "③"}' % (con[1], con[1]), 1, sides)
    assert [(t["speaker"], t["side"]) for t in got["turns"]] == [(con[1], "반대"), (con[0], "반대")]
    got = D.parse_deep_part('{"turns": [{"speaker": "%s", "text": "a"}], "lab_idea": null, "note": ""}' % pro[0], 2,
                            sides)
    assert [(t["speaker"], t["side"], t["part"]) for t in got["turns"]] == [("심판", "심판", "심판")]
    # a whole deep round with the wrong names: every stored turn's side matches its part
    a1, a2, a3 = TF.deep_answers()
    bad = ok_body({"turns": [{"speaker": con[0], "text": "주장?"}, {"speaker": "심판", "text": "주장??"}]})
    cfg = D.config_from_env(TF.env_for(world, tmp_path, DEBATE_DEEP=1))
    svc = TF.service(cfg, bad, a2, a3, at=TF.AT_2005)
    assert svc.tick() == "deep"
    owner = {"주장": "찬성", "반박": "반대", "심판": "심판"}
    msgs = svc.db.conn.execute("SELECT speaker, side, part FROM debate_messages WHERE part IS NOT NULL").fetchall()
    assert len(msgs) == 5 and all(side == owner[part] and sides[sp] == side for sp, side, part in msgs)


def test_the_day_and_hour_guards_count_the_rounds_worst_case(world, tmp_path):
    cfg = D.config_from_env(TF.env_for(world, tmp_path))
    svc = TF.service(cfg)
    worst = svc.worst_case_usd(5000)
    day = D.kst_day(svc.clock.t)
    svc.db.put(f"spend:day:{day}", cfg.daily_cap - worst / 2)          # under the cap, but this round would cross it
    assert svc.check_cap(svc.clock.t, in_tokens=5000) == "day"
    svc.db.put(f"spend:day:{day}", cfg.daily_cap - 2 * worst)
    assert svc.check_cap(svc.clock.t, in_tokens=5000) is None
    svc.cfg.hourly_cap = svc.db.hour_spend(svc.clock.t) + worst / 2
    assert svc.check_cap(svc.clock.t, in_tokens=5000) == "hour"


def test_loss_traits_never_read_the_exit_side_of_the_macro_tag():
    from paperbot.cards import MACRO_TAG
    base = {"tags": ["추세 반대 진입", MACRO_TAG, "강제청산"], "side_ko": "롱", "symbol": "BTCUSDT", "timeframe": "1h",
            "entry_time": TQ.NOW - TF.DAY, "leverage": 30, "ctx": {"regime": "trend_down"}}
    exit_only = dict(base, macro=[{"kind": "CPI", "entry": False, "exit": True}])
    at_entry = dict(base, macro=[{"kind": "CPI", "entry": True, "exit": False}])
    tv = DQ._trait_values(exit_only)
    assert ("태그", MACRO_TAG) not in tv and not [k for k, _v in tv if k == "경제지표"]
    assert ("태그", "강제청산") not in tv and ("태그", "추세 반대 진입") in tv
    assert ("경제지표", DQ.MACRO_ENTRY_KO) in DQ._trait_values(at_entry)


def test_a_classic_debate_db_keeps_its_scoreboard_until_the_factory_has_an_idea(tmp_path):
    db = D.DB(str(tmp_path / "debate.db"))                  # the service creates the idea table in classic mode too
    assert "factory" not in G.scoreboard(db.conn)
    db.conn.execute("INSERT INTO debate_lab_ideas (round_id, ts, engine, check_status, queue_status) "
                    "VALUES (1, 1, 'newlab', 'ok', 'candidate')")
    db.conn.commit()
    sb = G.scoreboard(db.conn)
    assert sb["factory"]["ideas"] == 1 and sb["factory"]["tested"] == 0
    db.close()


def test_one_broken_question_kind_never_stops_the_bank(world, monkeypatch):
    def boom(*a, **k):
        raise AttributeError("a bug in one kind")
    monkeypatch.setattr(DQ, "q_big_losses", boom)
    monkeypatch.setattr(DQ, "q_worst_vs_flip", boom)
    cands = DQ.candidates(world["paper"], world["daily"], world["agents"], TQ.NOW, covered_since=TQ.NOW)
    kinds = {q.kind for q in cands}
    assert "big_losses" not in kinds and "worst_vs_flip" not in kinds and {"retro", "coverage"} <= kinds
    monkeypatch.setattr(DQ, "q_retro", boom)
    assert DQ.candidates(world["paper"], world["daily"], world["agents"], TQ.NOW, covered_since=TQ.NOW)
