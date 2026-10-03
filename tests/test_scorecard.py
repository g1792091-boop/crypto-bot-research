"""Graded hypotheses (paperbot/agents/scorecard.py): a prediction is checked by code on the trades
entered after it was written, once enough of them are in."""

import json
import sqlite3

import pytest

from paperbot.agents import actions as A
from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R
from paperbot.agents import scorecard as SC
from paperbot.store3 import Store3
from test_cards import trade

S, ROOM, T0 = "N17_KC_RSI", "strat:N17_KC_RSI", 1_800_000_000_000
PRED = {"metric": "win_rate", "timeframe": "15m", "direction": "above", "value": 0.4, "after_trades": 30}


def test_clean_prediction_keeps_only_the_fixed_form():
    assert SC.clean_prediction(PRED) == (PRED | {"value": 0.4}, None)
    assert SC.clean_prediction(None) == (None, None)
    for bad in ({**PRED, "metric": "sharpe"}, {**PRED, "after_trades": 10}, {**PRED, "after_trades": 30.0},
                {**PRED, "value": 1.5}, {**PRED, "value": float("nan")}, {**PRED, "direction": "up"},
                {**PRED, "timeframe": "1d"}, {**PRED, "metric": "loss_tag_share"}, "win_rate > 0.4"):
        got, why = SC.clean_prediction(bad)
        assert got is None and why
    tag = SC._tags()[0]
    assert SC.clean_prediction({**PRED, "metric": "loss_tag_share", "tag": tag})[0]["tag"] == tag


def test_a_hypothesis_keeps_its_prediction_or_says_why_it_was_dropped():
    a, issues = A.validate({"action": "hypothesis", "text": "x", "prediction": PRED}, strategy=S)
    assert a["prediction"]["after_trades"] == 30 and issues == []
    a, issues = A.validate({"action": "hypothesis", "text": "x", "prediction": {**PRED, "value": "높음"}}, strategy=S)
    assert "prediction" not in a and a["action"] == "hypothesis" and "채점할 수 없어" in issues[0]


@pytest.fixture
def dbs(tmp_path):
    conn = R.open_agents(str(tmp_path / "agents3.db"))
    R.ensure_rooms(conn, ts=T0)
    store = Store3(str(tmp_path / "paper3.db"))
    return conn, store


def _add_trades(store, n, win_every, start):
    for k in range(n):
        win = k % win_every == 0
        t = trade(entry_time=start + k * 60_000, exit_time=start + k * 60_000 + 30_000,
                  pnl=10.0 if win else -10.0, roe=0.1 if win else -0.1, exit_reason="LOCK" if win else "SL")
        store.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, "
                           "roe, equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (f"{S}@15m", "BTCUSDT", t["entry_time"], t["exit_time"], t["exit_reason"], 40, t["pnl"],
                            t["roe"], 5000.0, json.dumps(t)))
    store.commit()


def _hyp(conn, pred, by="specialist", now=T0):
    env = A.ActionEnv(conn=conn, room_id=ROOM, strategy=S, round_id=None, meeting="t", now_ms=now, proposer=by)
    a, _ = A.validate({"action": "hypothesis", "text": "승률이 오른다", "prediction": pred}, strategy=S)
    return A.hypothesis(env, a)["trial_id"]


def test_grading_uses_only_trades_entered_after_the_hypothesis(dbs):
    conn, store = dbs
    _add_trades(store, 40, 1, T0 - 3_600_000)               # all wins, but BEFORE the hypothesis: never counted
    tid = _hyp(conn, PRED)
    paper = sqlite3.connect(store.conn.execute("PRAGMA database_list").fetchone()[2])
    assert SC.grade_due(conn, paper, T0 + 1000, 0.0014) == []           # 0 new trades: waits
    _add_trades(store, 29, 4, T0 + 60_000)
    assert SC.grade_due(conn, paper, T0 + 2000, 0.0014) == []           # 29 < 30: waits
    _add_trades(store, 31, 4, T0 + 60 * 60_000)
    [g] = SC.grade_due(conn, paper, T0 + 3000, 0.0014)
    assert g["trial_id"] == tid and g["status"] == "graded" and g["n"] == 30
    assert g["value"] == pytest.approx(9 / 30) and g["correct"] is False           # 8 of the first 29 + the 30th won
    assert SC.grade_due(conn, paper, T0 + 4000, 0.0014) == []           # graded once
    sc = SC.scorecard(conn, S)
    assert sc["total"] == {"graded": 1, "correct": 0, "waiting": 0, "expired": 0, "not_gradable": 0, "hit_rate": 0.0}
    assert sc["roles"][0]["role"] == "specialist"


def test_unfilled_predictions_expire_and_hypotheses_without_one_are_not_graded(dbs):
    conn, store = dbs
    _hyp(conn, {**PRED, "after_trades": 300})
    env = A.ActionEnv(conn=conn, room_id=ROOM, strategy=S, round_id=None, meeting="t", now_ms=T0)
    A.hypothesis(env, {"action": "hypothesis", "text": "예측 없음", "how_to_confirm": ""})
    paper = sqlite3.connect(store.conn.execute("PRAGMA database_list").fetchone()[2])
    assert SC.grade_due(conn, paper, T0 + 10 * SC.DAY_MS, 0.0014) == []
    [g] = SC.grade_due(conn, paper, T0 + (SC.EXPIRE_DAYS + 1) * SC.DAY_MS, 0.0014)
    assert g["status"] == "expired"
    t = SC.scorecard(conn)["total"]
    assert (t["expired"], t["not_gradable"], t["graded"], t["hit_rate"]) == (1, 1, 0, None)


def test_the_tick_grades_and_tells_the_room(dbs):
    conn, store = dbs
    _hyp(conn, {**PRED, "direction": "below", "value": 0.5})
    _add_trades(store, 30, 4, T0 + 60_000)
    paper = sqlite3.connect(store.conn.execute("PRAGMA database_list").fetchone()[2])
    [g] = RM.grade_hypotheses(conn, paper, T0 + 5000)
    assert g["correct"] is True
    msgs = [r[0] for r in conn.execute("SELECT text FROM messages WHERE room_id = ?", (ROOM,))]
    assert any("채점" in t and "맞음" in t for t in msgs)


def test_more_than_2000_hypotheses_the_oldest_prediction_is_still_graded_and_counted(dbs):
    conn, store = dbs
    oldest = _hyp(conn, PRED)                                   # the first prediction, then 2,100 newer hypotheses
    conn.executemany("INSERT INTO trials (ts, room_id, strategy, kind, spec, spec_hash, round_id) VALUES (?,?,?,?,?,?,?)",
                     [(T0 + 1, ROOM, S, "hypothesis", json.dumps({"text": f"h{k}"}), f"x{k}", None) for k in range(2100)])
    conn.commit()
    t = SC.scorecard(conn)["total"]
    assert (t["waiting"], t["not_gradable"]) == (1, 2100)       # every row counts, not the newest 2,000
    _add_trades(store, 30, 1, T0 + 60_000)
    paper = sqlite3.connect(store.conn.execute("PRAGMA database_list").fetchone()[2])
    [g] = SC.grade_due(conn, paper, T0 + 5000, 0.0014)
    assert g["trial_id"] == oldest and g["correct"] is True
    t = SC.scorecard(conn)["total"]
    assert (t["graded"], t["correct"], t["waiting"]) == (1, 1, 0)
