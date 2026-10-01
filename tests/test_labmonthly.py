"""Monthly re-check on new data (paperbot/agents/labmonthly.py): period 4 outcomes per strategy and
for every test that passed the gate. Synthetic caches; nothing touches the network."""

import json
import os

import pytest

from paperbot.agents import labmonthly as M
from paperbot.agents import rooms_db as R
from test_labtests import NAMES, COINS2, _write_cache


def test_month_helpers():
    from datetime import datetime, timezone
    assert M.last_complete_month(datetime(2026, 11, 5, tzinfo=timezone.utc)) == "2026-10"
    assert M.last_complete_month(datetime(2027, 1, 2, tzinfo=timezone.utc)) == "2026-12"
    assert M.month_end("2026-10") == "2026-11-01" and M.month_end("2026-12") == "2027-01-01"
    with pytest.raises(SystemExit):
        M.build_recent("/nonexistent", "2026-08")


def test_the_builder_range_follows_the_requested_months():
    from paperbot.agents import labdata as LD
    import importlib.util
    spec = importlib.util.spec_from_file_location("b_range", LD.BUILD_PY)
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    assert B.month_day_files("2025-10-01", "2026-11-01") == ([f"2025-{m}" for m in ("10", "11", "12")] +
                                                            [f"2026-{m:02d}" for m in range(1, 11)], [])
    months, days = B.month_day_files("2021-01-01", "2026-09-30")       # the research range, unchanged
    assert months[0] == "2021-01" and months[-1] == "2026-08" and days[0] == "2026-09-01" and days[-1] == "2026-09-29"


@pytest.fixture
def lab(tmp_path):
    root = str(tmp_path / "lab")
    for k, coin in enumerate(COINS2):          # 1h bars 2026-06-01 .. ~2026-11-25: warm-up, then period 4
        _write_cache(os.path.join(root, "recent"), "1h", coin, "2026-06-01", 4200, seed=40 + k, rate=0.08)
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps({"cards": [{"strategy": "AAA", "rows": [{"tf": "1h", "mean_roe": -0.05,
                                                                         "win_rate": 0.45}]}]}))
    agents = str(tmp_path / "agents3.db")
    conn = R.open_agents(agents)
    R.ensure_rooms(conn, ts=1)
    spec = {"template": "stop_atr", "strategy": "AAA", "timeframe": "1h", "k": 1.5}
    tid = R.add_trial(conn, "strat:AAA", "AAA", "test", spec)
    R.add_trial_result(conn, tid, "passed", {"result": {"gate": {"pass": True}}})
    t2 = R.add_trial(conn, "strat:BBB", "BBB", "test", {**spec, "strategy": "BBB"})
    R.add_trial_result(conn, t2, "failed", {"result": {"gate": {"pass": False}}})
    conn.close()
    return root, str(cards), agents, tid


def test_recheck_reports_period_4_per_strategy_and_for_passed_tests(lab):
    root, cards, agents, tid = lab
    rep = M.recheck(root, "2026-10", agents, cards, names=list(NAMES))
    assert rep["period"] == [M.P4_START, "2026-11-01"]
    a = {r["tf"]: r for r in rep["strategies"]["AAA"]}
    assert a["1h"]["available"] and a["1h"]["trades"] > 10 and a["1h"]["five_year_mean_roe"] == -0.05
    assert a["4h"]["available"] is False and a["4h"]["trades"] is None
    [t] = rep["trials"]                                              # only the passed test
    assert t["trial_id"] == tid and t["available"] and t["baseline"]["trades"] > 10
    assert t["variant"]["trades"] > 0 and t["diff"] is not None and t["still_better"] == (t["diff"] > 0)
    # only signals of period 4 count: a later month adds trades
    rep2 = M.recheck(root, "2026-11", agents, cards, names=list(NAMES))
    assert {r["tf"]: r for r in rep2["strategies"]["AAA"]}["1h"]["trades"] > a["1h"]["trades"]
    path = M.write(root, rep)
    assert M.read(root)["through"] == "2026-10" and path.endswith("recent/recheck.json")
    assert M.read(None) is None and M.read("/nonexistent") is None


def test_the_tick_posts_a_new_month_once_and_specialists_see_it(lab):
    from paperbot.agents import labtests as LT
    from paperbot.agents import rooms as RM
    root, cards, agents, tid = lab
    M.write(root, M.recheck(root, "2026-10", agents, cards, names=list(NAMES)))
    conn = R.open_agents(agents)
    data = LT.LabData(root)
    assert RM.post_recheck(conn, data, 5) == "2026-10"
    assert RM.post_recheck(conn, data, 6) is None                     # once per month
    lead = [r[0] for r in conn.execute("SELECT text FROM messages WHERE room_id = ?", (R.team_room_id("lead"),))]
    assert any("매달 재검사" in t for t in lead)
    room = [r[0] for r in conn.execute("SELECT text FROM messages WHERE room_id = 'strat:AAA'")]
    assert any(f"시험 #{tid}" in t and "새 기간 재검사" in t for t in room)
    got = RM.recent_period(data, "AAA")
    assert got["through"] == "2026-10" and got["passed_tests"][0]["trial_id"] == tid
    assert RM.recent_period(None, "AAA") is None
