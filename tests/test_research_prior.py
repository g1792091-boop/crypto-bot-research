"""The entry study's per-strategy summary for the agent rooms (paperbot/agents/research_prior.json)."""

import json

from paperbot.agents import packets3 as P
from paperbot.strategy_view_defs import NAMES


def test_every_strategy_has_its_summary_and_the_totals_match_the_study():
    doc = P.research_doc()
    assert set(doc["strategies"]) == set(NAMES)
    assert doc["totals"] == {"support_resistance": 290, "entry_strength": 410, "parameters": 1680}
    assert P.research_counts() == {**doc["totals"], "total": 2380}
    assert sum(P.research_counts(s)["total"] for s in NAMES) == 2380
    assert P.research_counts("NOPE")["total"] == 0 and P.research_prior("NOPE") is None


def test_the_summary_says_what_passed_and_what_to_watch():
    s = {k: P.research_prior(k) for k in NAMES}
    passed = {k for k, v in s.items() if v["support_resistance"]["passed_all3"]}
    assert passed == {"N04_ST_KLINGER", "N17_KC_RSI"}          # both market-wide (random entries show it too)
    assert all("시장 전체" in c["note"] for k in passed for c in s[k]["support_resistance"]["passed_all3"])
    assert all(v["entry_strength"]["passed_all3"] == 0 and v["parameters"]["adopted"] == 0 for v in s.values())
    assert {(k, w["tf"]) for k, v in s.items() for w in v["watch"]} == {("V39_ALL", "4h"), ("N10_HA_PSAR", "4h")}
    shapes = {p["shape"] for v in s.values() for p in v["parameters"]["params"]}
    assert "spiky" not in shapes and shapes <= {"flat", "smooth", "insufficient"}
    assert "없었다" in s["DOGE"]["conclusion_ko"]
    assert len(json.dumps(s["V39_ALL"], ensure_ascii=False)) < 12_000          # packet size stays small


def test_the_specialist_packet_carries_it():
    got = P.specialist_packet({"pass_check": {}, "by_strategy": {}}, "V39_ALL")
    assert got["research"]["strategy"] == "V39_ALL" and "note" in got["research"]
