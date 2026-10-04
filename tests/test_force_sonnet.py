"""AGENTS_FORCE_SONNET: every role whose roster tier is opus runs on sonnet (default off; a bad value refuses)."""

import pytest

from paperbot.agents import pipeline as P
from paperbot.agents import rooms as RM
from paperbot.agents import runner as RU
from paperbot.agents.roles import EVENING_ROLES
from paperbot.agents.runner import CallResult
from paperbot.agents.roster3 import ROLES
from test_new_meetings import TUE, bulk, tpol
from test_rooms import HOUR, QueueRunner, World, team_answer

OPUS = sorted(r[0] for r in ROLES if r[3] == "opus")
SONNET = sorted(r[0] for r in ROLES if r[3] == "sonnet")
LEAD = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}


def test_the_switch_is_off_by_default_and_parsed_strictly():
    assert RM.RoomsPolicy().force_sonnet is False and RM.policy_from_env({}).force_sonnet is False
    for on in ("1", "yes", "TRUE", " on "):
        assert RM.policy_from_env({"AGENTS_FORCE_SONNET": on}).force_sonnet is True
    for off in ("0", "no", "false", "off", ""):
        assert RM.policy_from_env({"AGENTS_FORCE_SONNET": off}).force_sonnet is False
    with pytest.raises(ValueError, match="AGENTS_FORCE_SONNET"):
        RM.policy_from_env({"AGENTS_FORCE_SONNET": "maybe"})
    assert RU.FORCE_SONNET_ENV not in RU.ENV_ALLOW              # read by the parent only, never the CLI child


def test_role_model_moves_only_the_opus_roles():
    assert OPUS and SONNET
    for r in OPUS:
        assert RM.role_model(r) == "opus" and RM.role_model(r, "team", True) == "sonnet"
    for r in SONNET:
        assert RM.role_model(r) == RM.role_model(r, "team", True) == "sonnet"
    assert RM.role_model("researcher", "lab_inventor", True) == RM.LAB_MODEL == "sonnet"
    assert RU.tier_model("opus", False) == "opus" and RU.tier_model("haiku", True) == "haiku"


@pytest.mark.parametrize("forced", [False, True])
def test_a_meeting_calls_the_opus_role_on_sonnet_only_when_switched(tmp_path, forced):
    world = World(tmp_path)
    bulk(world, 250, TUE - HOUR)
    pol = RM.RoomsPolicy(triggers=tpol(enabled=("combo_review",), combo_review_hour_kst=11), force_sonnet=forced)
    runner = QueueRunner({"combo_synergy": [team_answer("c")], "risk_officer": [team_answer("r")],
                          "team_lead": [LEAD]})
    world.tick(runner, TUE, policy=pol)
    models = {c["role"]: c["model"] for c in runner.calls}
    assert models == {"combo_synergy": "sonnet", "risk_officer": "sonnet" if forced else "opus",
                      "team_lead": "sonnet"}


def test_the_evening_pipeline_follows_the_switch(monkeypatch):
    role = next(r for r in EVENING_ROLES if r.model == "opus")
    seen = []

    class Rn:
        def call(self, model, system_prompt, instruction, packet):
            seen.append(model)
            return CallResult("{}", {}, {})
    for env, want in (("", "opus"), ("1", "sonnet"), ("bogus", "opus")):
        monkeypatch.setenv("AGENTS_FORCE_SONNET", env)
        seen.clear()
        try:
            P._call_role(role, {}, Rn(), retries=0)
        except Exception:  # noqa: BLE001  (the empty answer is unusable; only the model asked matters here)
            pass
        assert seen == [want]


def test_launchcheck_says_when_the_switch_is_on(tmp_path):
    from paperbot import launchcheck as L
    from test_launchcheck import Server, agents_env, st
    srv = Server(tmp_path)
    assert "AGENTS_FORCE_SONNET" not in str(L.check_agents_policy(srv.ctx(), srv.envs()["agents"], True, None))
    srv.write_env("agents", agents_env(extra="AGENTS_FORCE_SONNET=1\n"))
    lines = L.check_agents_policy(srv.ctx(), srv.envs()["agents"], True, None)
    assert L.FIX not in st(lines) and any(x[0] == L.NOTE and "AGENTS_FORCE_SONNET 켜짐" in x[1] for x in lines)
    srv.write_env("agents", agents_env(extra="AGENTS_FORCE_SONNET=sometimes\n"))
    lines = L.check_agents_policy(srv.ctx(), srv.envs()["agents"], True, None)
    assert st(lines) == [L.FIX] and "AGENTS_FORCE_SONNET" in lines[0][1]
