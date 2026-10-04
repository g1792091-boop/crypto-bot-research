"""Statistical power of the 30-day checkpoint (research/power/power.py, agents/power.py; owners approved
2026-10-04): the BH step-up against checkpoint.bh, the account Monte Carlo (bust stops trading), the checkpoint
schedule (1st verdict at the first checkpoint with 30 trades, a fail stays, the 2nd on the next 30 days), a tiny
seeded grid on synthetic bars, the committed result and its reader, and the packets that carry it (the Saturday
learning meeting, the 30-day checkpoint meeting)."""

import json
import os
import sys

import numpy as np
import pytest

from paperbot import checkpoint as CP
from paperbot.agents import power as PW
from paperbot.agents import rooms as RM

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "research", "power"))
sys.path.insert(0, os.path.join(ROOT, "research", "paper_rules"))
import power as P  # noqa: E402

from test_new_meetings import bulk, tpol  # noqa: E402
from test_rooms import HOUR, QueueRunner, World, kst, team_answer  # noqa: E402

SAT = kst(2026, 10, 10, 11, 5)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_bh_rows_is_the_checkpoints_step_up():
    rng = np.random.default_rng(1)
    for m in (1, 5, 30, 144):
        allp = rng.random((40, m)) ** 3
        allp[:, 0] = rng.choice([1 / 2001, 0.0004, 0.01, 0.5], size=40)
        got = P.bh_rows(allp, 0.10)
        for row, g in zip(allp, got):
            assert (CP.bh(row, 0.10)[1] == g).all()


def test_bh_target_alone_needs_to_beat_every_bot():
    rng = np.random.default_rng(2)
    best, second = np.full(2000, 1 / 2001), np.full(2000, 2 / 2001)
    assert P.bh_target(best, 144, 2000, 0.10, rng).mean() > 0.99          # p = 1/2001 <= 0.1/144
    # 2/2001 > 0.1/144: it passes only when other accounts' p-values happen to be small too
    assert P.bh_target(second, 144, 2000, 0.10, rng).mean() < 0.2


def test_accounts_stop_at_bust_and_an_edge_helps():
    rng = np.random.default_rng(3)
    dead = P.simulate_accounts(np.array([-1.0]), np.array([0.9999]), 10.0, 50, 0.0, rng, bust_frac=0.002)
    assert (dead["trades"] == 1).all() and dead["bust"].all() and (dead["equity"] < 0.002).all()
    R = rng.normal(-0.03, 0.3, 5000).clip(-1, None)
    mf = np.full(5000, 0.2)
    a = P.simulate_accounts(R, mf, 4.0, 3000, 0.0, np.random.default_rng(4), 0.002)
    b = P.simulate_accounts(R, mf, 4.0, 3000, 0.05, np.random.default_rng(4), 0.002)
    assert np.median(b["equity"][:, 0]) > 1.0 > np.median(a["equity"][:, 0])
    assert (np.diff(a["trades"], axis=1) >= 0).all() and abs(a["trades"][:, 0].mean() - 120) < 5


def test_checkpoint_schedule_first_verdict_fail_stays_second_check():
    rng = np.random.default_rng(5)
    nulls = {d: np.full(1000, 0.9) for d in P.CHECKPOINTS}          # every bot ends at 0.9: above it = p 1/2001
    acc = {"equity": np.array([[2.0, 4.0, 8.0],      # passes at 30, 2nd at 60
                               [0.5, 4.0, 8.0],      # fails at 30 (below the start): stays failed
                               [2.0, 2.0, 2.0],      # 1st at 30, 2nd window flat (P&L 0): fails at 60
                               [1.5, 3.0, 6.0]]),    # 10 trades by 30: judged first at 60, 2nd at 90
           "trades": np.array([[40, 80, 120], [40, 80, 120], [40, 80, 120], [10, 40, 80]]),
           "bust": np.zeros((4, 3), dtype=bool)}
    out = {i: P.checkpoint_pass({k: v[i:i + 1] for k, v in acc.items()}, nulls, 1, rng, 2000, 0.10, 30)
           for i in range(4)}
    assert out[0]["p_pass1_d30"] == 1 and out[0]["p_pass2_by_d60"] == 1
    assert out[1]["p_pass1_by_d90"] == 0 and out[1]["p_judged_by_d30"] == 1
    assert out[2]["p_pass1_d30"] == 1 and out[2]["p_pass2_by_d60"] == 0 and out[2]["p_pass2_by_d90"] == 0
    assert out[3]["p_pass1_d30"] == 0 and out[3]["p_pass1_by_d60"] == 1 and out[3]["p_pass2_by_d60"] == 0
    assert out[3]["p_pass2_by_d90"] == 1 and out[3]["p_judged_by_d30"] == 0


def test_a_tiny_seeded_grid_on_synthetic_bars_is_monotone_and_repeatable():
    bars = P.synth_bars(n=4000, tf="1h", seed=7)
    pool = P.build_pool(bars, "1h", 0.013, seeds=(1, 2), max_windows=3)
    assert pool["trades"] >= P.MIN_POOL and pool["rate_per_day"] > 0 and (pool["mf"] > 0).all()
    nb = {**P.v3_numbers(), "n_bots": 500}
    run = lambda: P.power_grid({"1h": pool}, edges=(0.0, 0.1, 0.5), families=(20,), reps=300,  # noqa: E731
                               n_null=1500, seed=11, numbers=nb)
    a, b = run(), run()
    assert a == b
    d30 = [r["family_20"]["p_pass1_by_d90"] for r in a["1h"]["rows"]]
    assert d30[0] <= 0.05 and d30[0] <= d30[1] <= d30[2] and d30[2] > 0.5
    assert a["1h"]["pool"]["trades_per_30d"] == pytest.approx(pool["rate_per_day"] * 30, abs=0.1)
    lines = P.summary_ko(a, family=20, numbers=nb)
    assert lines[0].startswith("진짜 엣지가 거래당 +10%") and "1시간" in lines[0]


def test_the_committed_result_and_its_reader():
    doc = P.json.load(open(P.OUT, encoding="utf-8"))
    assert doc["version"] == 1 and doc["edges_roe"][0] == 0.0 and doc["families"] == [144, 180]
    assert doc["rules"]["n_bots"] == CP.N_BOTS and doc["rules"]["alpha"] == CP.ALPHA
    for tf in ("5m", "15m", "30m", "1h"):
        rows = doc["results"][tf]["rows"]
        assert [r["edge_roe"] for r in rows] == doc["edges_roe"]
        assert rows[0]["family_144"]["p_pass1_by_d90"] <= 0.01                     # no edge: (almost) never
        assert rows[-1]["family_144"]["p_pass1_by_d90"] >= rows[0]["family_144"]["p_pass1_by_d90"]
    assert doc["results"]["4h"]["observation_only"] is True
    assert doc["runtime_s"]["total"] < 300 and any(x.startswith("진짜 엣지가 거래당 +") for x in doc["summary_ko"])
    b = PW.brief()
    assert b["lines_ko"] == doc["summary_ko"] and set(b["table"]) == {"5m", "15m", "30m", "1h"}
    assert b["table"]["15m"][0][0] == 0.0 and len(b["table"]["15m"][0]) == 4 and b["timeframes"]["4h"]["observation_only"]
    assert len(json.dumps(b, ensure_ascii=False)) < 5000
    assert PW.brief(path="/nonexistent.json") == {"error": "검정력 결과 파일 없음 (research/power/out/power.json)"}


def test_the_saturday_learning_packet_carries_the_power(world):
    bulk(world, 250, SAT - HOUR)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("learning_review",), learning_review_hour_kst=11))
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": [], "lessons": {}}
    runner = QueueRunner({"performance": [team_answer("p", "learning.power.lines_ko.0")], "learning": [team_answer("l")],
                          "team_lead": [lead]})
    RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
            policy=pol, now_ms=SAT, clock_ms=lambda: SAT)
    pw = runner.calls[0]["packet"]["learning"]["power"]
    assert pw["lines_ko"] and pw["family"] == 144 and "learning.power" in runner.calls[0]["system"]
    from paperbot.agents import rooms_db as R
    said = {m["role"]: m["text"] for m in R.room_messages(world.agents, "team:lead", limit=50)}
    assert "[사실]" in said["performance"]                                            # learning.* is code's
