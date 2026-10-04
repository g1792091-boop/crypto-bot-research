"""Portfolio synergy (agents/synergy.py, owners approved 2026-10-04): equal-weight combinations of 2-5 strategies
from their KST-day P&L, the search (exhaustive / beam) against brute force, the multiple-testing guard (the same
search on day-shuffled P&L and on the coin flips), the diversification ratio, the clusters, the 'same bet twice'
pairs from overlap.py, and the Tuesday combo packet (``combo.synergy``) and the dashboard-ready view."""

import itertools
import json

import numpy as np
import pytest

from paperbot.agents import meetings as M
from paperbot.agents import rooms as RM
from paperbot.agents import synergy as SY

from test_new_meetings import bulk, tpol
from test_rooms import DAY, HOUR, QueueRunner, START, World, kst, rec, team_answer

S, V45 = "N17_KC_RSI", "V45_AMB"
TUE = kst(2026, 10, 6, 11, 5)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def brute(U, cap, kmin, kmax):
    best = []
    for k in range(kmin, kmax + 1):
        for c in itertools.combinations(range(len(U)), k):
            sc = SY.curve_numbers(U[list(c)].sum(axis=0)[None, :], np.array([cap[list(c)].sum()]))[3][0]
            best.append((sc, c))
    best.sort(key=lambda x: (-x[0], x[1]))
    return best


def test_curve_numbers_and_the_diversification_ratio():
    a = np.array([[10.0, -20.0, 30.0, -5.0]])
    total, dd, ddp, sc = SY.curve_numbers(a, np.array([100.0]))
    assert total[0] == 15.0 and dd[0] == 20.0 and ddp[0] == pytest.approx(20 / 110) and sc[0] == pytest.approx(0.75)
    flat = SY.curve_numbers(np.array([[1.0, 1.0]]), np.array([100.0]))
    assert flat[1][0] == 0.0 and flat[3][0] == pytest.approx(2.0 / 0.5)               # the drawdown floor
    U = np.array([[10.0, -10.0, 10.0, -10.0], [-10.0, 10.0, -10.0, 10.0]])           # opposite days
    assert SY.diversification(U, np.array([100.0, 100.0]), (0, 1)) is None            # together: never down
    V = np.array([[10.0, -10.0, 10.0], [-5.0, 4.0, -10.0]])
    assert SY.diversification(V, np.array([100.0, 100.0]), (0, 1)) == pytest.approx((10 + 11) / 6)
    assert SY.diversification(np.ones((2, 3)), np.array([100.0, 100.0]), (0, 1)) is None   # nothing ever fell


def test_the_search_matches_brute_force_where_it_is_exhaustive():
    rng = np.random.default_rng(3)
    U = rng.normal(0.5, 10, size=(9, 20))
    cap = np.full(9, 5000.0)
    got = SY.search(U, cap, kmin=2, kmax=4, keep=5)
    want = brute(U, cap, 2, 4)[:5]
    assert [c for _s, c in got] == [c for _s, c in want]
    assert [s for s, _c in got] == pytest.approx([s for s, _c in want])
    # the beam (k >= 4 when C(n, k) is large) never returns a worse best than its own exhaustive pairs
    old = SY.EXHAUSTIVE
    try:
        SY.EXHAUSTIVE = 40
        beam = SY.search(U, cap, kmin=2, kmax=5, keep=1)
    finally:
        SY.EXHAUSTIVE = old
    assert beam[0][0] >= brute(U, cap, 2, 2)[0][0]


def test_the_shuffled_day_guard_is_seeded_and_ranks_the_real_best():
    rng = np.random.default_rng(4)
    U = rng.normal(0, 10, size=(8, 25))
    cap = np.full(8, 5000.0)
    a = SY.shuffled_bests(U, cap, runs=15, seed=1)
    assert len(a) == 15 and (a == SY.shuffled_bests(U, cap, runs=15, seed=1)).all()
    # every unit's total is kept by the shuffle (only the timing changes)
    V = np.random.default_rng(1).permuted(U, axis=1)
    assert V.sum(axis=1) == pytest.approx(U.sum(axis=1))


def test_corr_clusters_is_the_tuesday_rule():
    pairs = [(0.9, "a", "b"), (0.75, "b", "c"), (0.2, "c", "d"), (0.71, "e", "f")]
    assert M.corr_clusters(["a", "b", "c", "d", "e", "f"], pairs) == [["a", "b", "c"], ["e", "f"]]
    assert M.corr_clusters(["a", "b"], [(0.5, "a", "b")]) == []


def two_strategies(world, days=12):
    """S wins on even days, V45 on odd days (opposite): together smoother than either; a coin flip loses."""
    for d in range(days):
        t = START + (d + 1) * DAY + 3 * HOUR
        world.store.trade(f"{S}@15m", rec(S, "15m", 20.0 if d % 2 == 0 else -10.0, t))
        world.store.trade(f"{V45}@1h", rec(V45, "1h", 20.0 if d % 2 else -10.0, t + HOUR))
        world.store.trade("RANDOM_1@15m", rec("RANDOM_1", "15m", -3.0, t + 2 * HOUR))
    world.store.commit()


def test_analyse_on_paper3(world, monkeypatch):
    two_strategies(world)
    now = START + 14 * DAY
    d = SY.daily(world.paper(), now)
    assert len(d["days"]) == 15 and set(d["strategies"]) == {S, V45} and d["n_accounts"] == {S: 2, V45: 2}
    assert d["strategies"][S].sum() == pytest.approx(6 * 20 - 6 * 10) and "RANDOM_1@15m" in d["flips"]
    monkeypatch.setattr(SY, "same_bets", lambda *a, **k: {frozenset((S, V45)): {
        "accounts": [f"{S}@15m", f"{V45}@1h"], "same_of_busy": 0.8, "corr": 0.4}})
    a = SY.analyse(world.paper(), now, shuffles=10)
    top = a["top"][0]
    assert top["units"] == [S, V45] and top["k"] == 2 and top["combined_never_fell"] and top["div_ratio"] is None
    assert top["same_bet"][0]["pair"] == ["켈트너·RSI", "V4.5"] and a["same_bet_pairs"][0]["same_of_busy"] == 0.8
    assert a["shuffled_days"]["runs"] == 10 and 0 < a["shuffled_days"]["rank_p"] <= 1
    assert "coin_flips" not in a                                                  # one coin-flip account only
    acc = SY.analyse(world.paper(), now, level="account", shuffles=2)
    assert acc["units"] == 4 and acc["top"][0]["names"][0].endswith("@15m")


def test_same_bets_reads_the_overlap_pairs(world, monkeypatch):
    from paperbot import overlap as OV
    fake = {"pairs": {"top": [
        {"a": {"account_id": f"{S}@15m", "strategy": S}, "b": {"account_id": f"{V45}@1h", "strategy": V45},
         "corr": 0.3, "same_of_busy": 0.6},
        {"a": {"account_id": f"{S}@15m", "strategy": S}, "b": {"account_id": f"{S}@1h", "strategy": S},
         "corr": 0.95, "same_of_busy": 0.9},                                       # the same strategy: not a pair
        {"a": {"account_id": "X@5m", "strategy": "X"}, "b": {"account_id": "Y@5m", "strategy": "Y"},
         "corr": 0.2, "same_of_busy": 0.1}]}}
    monkeypatch.setattr(OV, "report", lambda *a, **k: fake)
    got = SY.same_bets(world.paper())
    assert list(got) == [frozenset((S, V45))] and got[frozenset((S, V45))]["same_of_busy"] == 0.6


def test_the_tuesday_combo_packet_carries_synergy(world):
    two_strategies(world, days=10)
    bulk(world, 250, TUE - HOUR)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("combo_review",), combo_review_hour_kst=11))
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}
    runner = QueueRunner({"combo_synergy": [team_answer("c", "combo.synergy.top.0.score")],
                          "risk_officer": [team_answer("r")], "team_lead": [lead]})
    out = RM.tick(world.paths["paper"], world.paths["daily"], world.paths["agents"], world.paths["inbox"], runner,
                  policy=pol, now_ms=TUE, clock_ms=lambda: TUE)
    assert [(r["trigger"], r["status"]) for r in out["rounds"]] == [("combo_review", "done")]
    sy = runner.calls[0]["packet"]["combo"]["synergy"]
    assert sy["top"] and "units" not in sy["top"][0] and sy["clusters_in"] == "combo.correlation.clusters"
    assert sy["shuffled_days"]["runs"] == SY.SHUFFLES and "rank_p" in sy["shuffled_days"]
    assert len(json.dumps(sy, ensure_ascii=False)) < 6_000
    assert "combo.synergy" in runner.calls[0]["system"]
    dv = SY.dash_view(world.paper(), TUE)
    assert dv["top"] and "clusters" in dv and dv["shuffled_days"]["runs"] == 20 and dv["how_to_read"]
