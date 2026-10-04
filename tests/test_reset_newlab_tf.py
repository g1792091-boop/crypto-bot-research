"""The restart of 2026-10-04 removed 5m from the run (config.V3_TRADE_TFS); the new-strategy lab's grammar still
allows 5m, so the live runner refuses to start a new-strategy account on a timeframe the run does not trade
(paperbot/extras.py ``run_timeframe_refusal``, check C3 of the activation)."""

import sqlite3

from paperbot import extras as X
from paperbot.config import V3_TRADE_TFS
from tests.extras_world import MIN, T0, World

NO_5M = "5분봉은 2026-10-04부터 실험에서 뺐음"


def test_run_timeframe_refusal():
    for tf in V3_TRADE_TFS:
        assert X.run_timeframe_refusal(tf) == ""
    assert "5m" not in V3_TRADE_TFS
    why = X.run_timeframe_refusal("5m")
    assert why.startswith(NO_5M) and "15m·30m·1h·4h" in why
    assert "이번 실행의 봉" in X.run_timeframe_refusal("2h")
    # a frozen test set with 5m (tests/extras_harness.py, tests/extras_world.py) allows it
    assert X.run_timeframe_refusal("5m", ("5m", "15m", "30m", "1h", "4h")) == ""
    assert X.run_timeframe_refusal("5m", None).startswith(NO_5M)          # no set given: the run's (V3_TRADE_TFS)
    assert "spec_invalid" in X.PERMANENT                                  # the agents tick closes such a proposal


def test_a_5m_new_strategy_is_refused_and_a_1h_one_starts(tmp_path):
    w = World(tmp_path, hist=True)
    try:
        w.service.trade_tfs = V3_TRADE_TFS              # the live runner's SignalService (no 5m)
        w.process(T0)
        p5, _ = w.newlab_proposal(0)                    # 5m ema_cross: valid in the lab grammar
        p1h, _ = w.newlab_proposal(1)                   # 1h rsi_reversal
        w.run(T0 + MIN, T0 + 10 * MIN)
        rows = {a["account_id"]: a for a in w.extras_rows()}
        assert [a for a in rows if a.endswith("@5m")] == []
        assert [a for a in rows if a.endswith("@1h")] == ["NL1@1h"]
        rf = w.refused(p5)
        assert rf is not None and rf["code"] == "spec_invalid" and rf["permanent"] is True
        assert rf["detail"].startswith(NO_5M)
        assert w.refused(p1h) is None
        alerts = [r[0] for r in sqlite3.connect(w.db).execute("SELECT text FROM alerts WHERE text LIKE '[extra]%'")]
        assert any(f"제안 #{p5}" in t and NO_5M in t for t in alerts), alerts
    finally:
        w.close()


def test_the_test_worlds_keep_their_5m_set(tmp_path):
    """The golden-parity harness and the runtime world pin the old set (with 5m): their 5m accounts still start."""
    w = World(tmp_path, hist=True)
    try:
        assert "5m" in w.service.trade_tfs
        w.process(T0)
        w.newlab_proposal(0)
        w.run(T0 + MIN, T0 + 10 * MIN)
        assert [a["account_id"] for a in w.extras_rows()] == ["NL1@5m"]
    finally:
        w.close()
