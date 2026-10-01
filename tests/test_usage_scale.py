"""Adaptive use of the owners' Claude plan: the caps shrink after the plan refuses a call and grow back
day by day (paperbot/agents/rooms.py usage_scale / lower_usage_scale / scaled_policy)."""

from paperbot.agents import rooms as RM
from paperbot.agents import rooms_db as R

DAY = 86_400_000
T0 = 1_800_000_000_000


def test_the_scale_drops_once_a_day_and_climbs_back(tmp_path):
    conn = R.open_agents(str(tmp_path / "a.db"))
    assert RM.usage_scale(conn, T0) == 1.0
    assert RM.lower_usage_scale(conn, T0) == 0.7
    assert RM.lower_usage_scale(conn, T0 + 3_600_000) == 0.7           # once per KST day
    assert RM.usage_scale(conn, T0 + 3_600_000) == 0.7
    assert abs(RM.usage_scale(conn, T0 + DAY) - 0.8) < 1e-9               # +0.1 a day without a refusal
    assert abs(RM.lower_usage_scale(conn, T0 + DAY) - 0.56) < 1e-9        # refused again: 0.8 x 0.7
    for d in range(2, 6):
        RM.usage_scale(conn, T0 + d * DAY)
    assert RM.usage_scale(conn, T0 + 9 * DAY) == 1.0                      # back to the full caps
    for d in range(10, 20):
        RM.lower_usage_scale(conn, T0 + d * DAY)
    assert RM.usage_scale(conn, T0 + 19 * DAY) == RM.USAGE_SCALE_MIN      # never below the floor


def test_scaled_policy_keeps_the_reserved_meetings_and_bounds_the_totals():
    p = RM.policy_from_env({"AGENTS_BUDGET": "incident=30:800000,owner=40:1000000,loss=48:1400000,"
                                             "scheduled=30:900000,weekly=40:1100000,total=160:4000000,week=900:20000000"})
    assert RM.scaled_policy(p, 1.0) is p
    q = RM.scaled_policy(p, 0.5)
    assert q.budgets["incident"] == (30, 800000) and q.budgets["scheduled"] == (30, 900000)
    assert q.budgets["owner"] == (20, 500000) and q.budgets["loss"] == (24, 700000)
    assert q.total_budget == (80, 2000000) and q.week_budget == (450, 7 * 1_700_000 + 1)   # tokens: the reserved floor
    low = RM.scaled_policy(p, 0.3)
    assert low.total_budget[0] == 61 and low.week_budget[0] == 7 * 60 + 1       # never below the reserved caps
    assert p.budgets["owner"] == (40, 1000000)                                   # the original is untouched


def test_a_plan_refusal_in_a_tick_lowers_the_scale(tmp_path, monkeypatch):
    conn = R.open_agents(str(tmp_path / "a.db"))
    seen = {}
    real = RM.scaled_policy

    def spy(policy, scale):
        seen["scale"] = scale
        return real(policy, scale)
    monkeypatch.setattr(RM, "scaled_policy", spy)
    RM.lower_usage_scale(conn, T0)
    conn.close()
    RM.tick(None, None, str(tmp_path / "a.db"), None, runner=None, now_ms=T0 + 60_000)
    assert seen["scale"] == 0.7
