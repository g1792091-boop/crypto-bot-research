"""Guard: the agents' analysis surface never shrinks (owners 2026-10-05, paper v4 restart).

``tests/data/agents_v3_surface.json`` is a snapshot of what the agent staff did on 2026-10-05, BEFORE any v4 change:
the rooms and their members, the meeting kinds, the trigger kinds with their budget class and priority, the
sections of every packet the staff read (the board, the team views, a strategy room's packet), the scheduled
meetings (hours, weekdays, rooms) and the AI budget. The current code must be a SUPERSET of it: a new room, member,
meeting, packet section or role may be added, nothing may be dropped, and the budget stays the same.

Regenerate the snapshot only by an owners' decision to drop something: ``python tests/test_agents_surface.py``
(prints the current surface; the file is never rewritten by a test).
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "data", "agents_v3_surface.json")


def _team_dues():
    from paperbot.agents import triggers as TR
    plans = [("research", "team:lab", {}), ("loss_cluster", "team:lab", {}), ("bust", "team:lab", {}),
             ("weekly", "team:lab", {}), ("morning", "team:market", {}), ("market_move", "team:market", {}),
             ("ranking", "team:review", {}), ("event_review", "team:market", {}), ("bull_bear", "team:market", {}),
             ("evening", "team:review", {}), ("evening", "team:lead", {}),
             ("incident", "team:ops", {"counts": {"liquidation": 1}}), ("incident", "team:ops", {"counts": {"data_gap": 2}}),
             ("checkpoint", "team:lead", {})]
    plans += [(trig, room, {}) for trig, (_wd, room) in TR.ANALYSES.items()]
    plans += [("owner", room, {}) for room in (*TR.TEAM_ROOMS, TR.LAB_ROOM)]
    for trig, room, data in plans:
        tag = f"{trig}@{room}" + (f"#{'+'.join(sorted(data['counts']))}" if "counts" in data else "")
        yield tag, TR.Due(room, trig, 0, data, trig)


def _packets(tmp_path) -> dict:
    """The sections of the packets the staff read, from real meetings on a small synthetic world (scripted answers)."""
    sys.path.insert(0, HERE)
    from test_rooms import NOTE, QueueRunner, World, analysis, challenge, kst, team_answer, QUIET
    from paperbot.agents import packets3

    (tmp_path / "loss").mkdir()
    (tmp_path / "morning").mkdir()
    w = World(tmp_path / "loss")
    w.losses()
    r = QueueRunner({"spec_N17_KC_RSI": [analysis(NOTE)], "devils_advocate": [challenge("agree")]})
    w.tick(r, QUIET)
    t1 = r.calls[0]["packet"]
    w2 = World(tmp_path / "morning")
    lead = {"summary": ["a", "b", "c"], "human_actions": [], "watch_next": []}
    r2 = QueueRunner({"chart_regime": [team_answer("c")], "derivs_flow": [team_answer("d")],
                      "strategist": [team_answer("s")], "devils_advocate": [challenge("agree")], "team_lead": [lead]})
    w2.tick(r2, kst(2026, 10, 7, 8, 3))
    board = packets3.build(w2.paths["paper"], w2.paths["daily"], QUIET)
    return {
        "board": sorted(board),
        "meta": sorted(board["meta"]),
        "today": sorted(board["today"]),
        "league_tf": sorted(next(iter(board["league"].values()))),
        "strategy_room": sorted(t1),
        "strategy_room_specialist": sorted(t1["specialist"]),
        "strategy_room_losses": sorted(t1["losses"]),
        "strategy_room_rules": sorted(t1["rules"]),
        "team_room": sorted(r2.calls[0]["packet"]),
        "team_lead": sorted(r2.calls[-1]["packet"]),
    }


def surface(tmp_path) -> dict:
    from paperbot.agents import rooms as RM
    from paperbot.agents import rooms_db as R
    from paperbot.agents import roster3
    from paperbot.agents import triggers as TR

    server = RM.policy_from_env({})
    return {
        "rooms": {s["room_id"]: {"kind": s["kind"], "strategy": s["strategy"], "title": s["title"],
                                 "members": list(s["members"])} for s in R.room_specs()},
        "trigger_rooms": list(TR.all_rooms()),
        "team_room_members": {k: list(v) for k, v in R.TEAM_ROOM_MEMBERS.items()},
        "triggers": list(TR.TRIGGERS),
        "trigger_class": dict(TR.TRIGGER_CLASS),
        "trigger_priority": dict(TR.PRIORITY),
        "budget_classes": list(TR.CLASSES),
        "incident_kinds": sorted({k for k, _l, _f in TR.INCIDENT_ALERTS} | set(TR.INCIDENT_KO)),
        "meeting_kinds": {"roster": [m[0] for m in roster3.MEETINGS], "trigger_ko": sorted(RM.TRIGGER_KO),
                          "meeting_file": dict(RM.MEETING_FILE),
                          "meeting_packets": {k: v[0] for k, v in RM.MEETING_PACKETS.items()},
                          "lead_hypothesis": list(RM.LEAD_HYPOTHESIS_MEETINGS), "lead_extra": sorted(RM.LEAD_EXTRA),
                          "analysis_ko": dict(TR.ANALYSIS_KO)},
        "turns": {"turn_file": dict(RM.TURN_FILE), "expert_file": dict(RM.EXPERT_FILE), "checks": sorted(RM.CHECKS),
                  "schemas": sorted(RM.SCHEMAS), "strategy_room_roles": list(R.STRATEGY_ROOM_ROLES),
                  "strategy_experts": list(RM.STRATEGY_EXPERTS), "lab_turns": list(RM.LAB_TURNS),
                  "owner_responders": {k: list(v) for k, v in RM.OWNER_RESPONDERS.items()}},
        "team_plans": {tag: [list(x) for x in RM.team_plan(d)] for tag, d in _team_dues()},
        "packet_sections": {"team_view": {k: list(v) for k, v in RM.TEAM_VIEW.items()}, **_packets(tmp_path)},
        "scheduled": {"analyses": {k: list(v) for k, v in TR.ANALYSES.items()},
                      "server_hours": RM.schedule_hours(server),
                      "env_hours": {k: list(v) for k, v in RM.NEW_MEETING_HOURS.items()},
                      "weekly_report": [server.weekly_report_weekday, server.weekly_report_hour_kst],
                      "research_every_ms": server.triggers.research_every_ms},
        "budget": {"classes": {k: list(v) for k, v in RM.DEFAULT_BUDGETS.items()}, "total": list(RM.DEFAULT_TOTAL),
                   "week": list(RM.DEFAULT_WEEK), "bust_reserve_calls": server.bust_reserve_calls,
                   "critical_reserve_calls": server.critical_reserve_calls,
                   "extras_meetings_per_day": server.triggers.extras_meetings_per_day,
                   "max_rounds_per_room_day": server.triggers.max_rounds_per_room_day,
                   "max_rounds_per_tick": server.triggers.max_rounds_per_tick,
                   "max_calls_per_tick": server.max_calls_per_tick},
        "roles": [r[0] for r in roster3.ROLES + roster3.SPECIALISTS],
        "teams": [t for t, _n in roster3.TEAMS],
        "strategies": list(roster3.STRATEGY_KO),
    }


def missing(old, new, path="") -> list[str]:
    """What ``old`` has that ``new`` lacks: dict keys (recursively), list items; scalars must be equal."""
    out: list[str] = []
    if isinstance(old, dict):
        if not isinstance(new, dict):
            return [f"{path}: was a mapping"]
        for k, v in old.items():
            if k not in new:
                out.append(f"{path}/{k}: dropped")
            else:
                out += missing(v, new[k], f"{path}/{k}")
    elif isinstance(old, list):
        if not isinstance(new, list):
            return [f"{path}: was a list"]
        have = {json.dumps(x, sort_keys=True, ensure_ascii=False) for x in new}
        out += [f"{path}: dropped {x}" for x in (json.dumps(y, sort_keys=True, ensure_ascii=False) for y in old)
                if x not in have]
    elif old != new:
        out.append(f"{path}: {old!r} -> {new!r}")
    return out


def test_agents_surface_is_a_superset_of_the_v3_snapshot(tmp_path):
    with open(FIXTURE, encoding="utf-8") as fh:
        old = json.load(fh)
    new = surface(tmp_path)
    assert set(old) <= set(new)
    problems = missing(old, new)
    assert problems == [], "an existing room, meeting, trigger, packet section or schedule was dropped:\n" + \
        "\n".join(problems)
    assert new["budget"] == old["budget"]          # owners 2026-10-05: the AI budget is unchanged


def test_the_guard_catches_a_dropped_item():
    old = {"rooms": {"team:ops": {"members": ["ops_auditor", "team_lead"]}}, "triggers": ["incident", "owner"]}
    assert missing(old, {"rooms": {"team:ops": {"members": ["ops_auditor", "team_lead", "x"]}},
                         "triggers": ["incident", "owner", "new"]}) == []
    assert missing(old, {"rooms": {"team:ops": {"members": ["ops_auditor"]}}, "triggers": ["incident", "owner"]}) == \
        ['/rooms/team:ops/members: dropped "team_lead"']
    assert missing(old, {"rooms": {}, "triggers": ["owner"]}) == ["/rooms/team:ops: dropped",
                                                                   '/triggers: dropped "incident"']
    assert missing({"budget": {"loss": [48, 1]}}, {"budget": {"loss": [40, 1]}}) == ["/budget/loss: dropped 48"]


if __name__ == "__main__":          # print the current surface (the snapshot is written by hand, never by a test)
    import pathlib
    import tempfile
    sys.path.insert(0, os.path.dirname(HERE))
    with tempfile.TemporaryDirectory() as d:
        print(json.dumps(surface(pathlib.Path(d)), ensure_ascii=False, indent=1, sort_keys=True))
