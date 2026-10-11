"""candleague/candidates.py: candidates from the study's confirm.json, the checks, and the league's accounts."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from candleague import candidates as C  # noqa: E402


def _row(kind, name, tf, rank, passed, exit_="tp2R|1.5", **over):
    combo = {**C.default_combo(kind, name), **over}
    return {"kind": kind, "name": name, "tf": tf, "rank": rank, "row": 7, "exit": exit_, "exit_index": 9,
            "combo": {k: C._plain(v) for k, v in combo.items()}, "pass": passed, "select_n": 400,
            "test": {"n": 210, "mean": None if kind == "ds" else 0.0123}}


def _confirm():
    ds_tf = C.ds_defs().TFS_OF["F17_Z"][0]
    return {"rows": [_row("core", "S2_ST_ROC", "15m", 1, True, st_mult=9.0),
                     _row("core", "S2_ST_ROC", "15m", 2, False),
                     _row("ds", "F17_Z", ds_tf, 1, True, exit_="swing3|2")]}


def test_from_results_takes_the_passed_rows():
    cands = C.from_results(_confirm())
    assert [c["id"] for c in cands] == ["core-S2_ST_ROC-15m-1", f"ds-F17_Z-{cands[1]['tf']}-1"]
    assert cands[0]["combo"]["st_mult"] == 9.0 and cands[0]["exit"] == "tp2R|1.5"
    assert cands[0]["source"]["test_mean"] == 0.0123 and "test_mean" not in cands[1]["source"]     # D11
    assert len(C.from_results(_confirm(), all_picks=True)) == 3
    assert C.check(cands) == []


def test_check_refuses_what_the_league_cannot_run_as_the_study():
    good = C.from_results(_confirm())[0]
    bad = [{**good, "id": "a1x", "exit": "tp9R|2"},
           {**good, "id": "a2x", "tf": "5m"},
           {**good, "id": "a3x", "combo": {k: v for k, v in good["combo"].items() if k != "roc_len"}},
           {**good, "id": "a4x", "combo": {**good["combo"], "st_mult": "9"}},
           {**good, "id": "a5x", "name": "NOPE"},
           {**good, "id": "a 6"}]
    msgs = C.check(bad)
    for cid, word in (("a1x", "exit"), ("a2x", "timeframe"), ("a3x", "parameters"), ("a4x", "type"),
                      ("a5x", "not runnable"), ("a 6", "id")):
        assert any(m.startswith(cid) and word in m for m in msgs), (cid, msgs)


def test_accounts_add_a_flip_per_candidate_and_one_base_per_cell(tmp_path):
    cands = C.from_results(_confirm(), all_picks=True)
    acc = C.accounts(cands)
    roles = [a["role"] for a in acc]
    assert roles.count("cand") == 3 and roles.count("flip") == 3 and roles.count("base") == 2
    base = next(a for a in acc if a["id"] == "base-core-S2_ST_ROC-15m")
    assert base["exit"] == "ladder|2" and base["combo"] == {k: C._plain(v)
                                                             for k, v in C.default_combo("core", "S2_ST_ROC").items()}
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"candidates": cands}))
    assert len(C.load(str(p))) == 3


def test_phase2_bands_ride_along_for_core_only():
    band = {"10": {"p5": -0.02, "median": 0.004}, "30": {"p5": -0.008, "median": 0.004}}
    ds_tf = C.ds_defs().TFS_OF["F17_Z"][0]
    phase2 = {"candidates": [{"id": "core-S2_ST_ROC-15m-1", "band": band}, {"id": f"ds-F17_Z-{ds_tf}-1", "band": band}]}
    cands = C.from_results(_confirm(), phase2=phase2)
    assert cands[0]["source"]["band"] == band and "band" not in cands[1]["source"]                   # D11
    assert "band" not in C.from_results(_confirm())[0]["source"]


def test_watch_list_runs_each_pick_with_quarter_size_and_exit_only_comparisons():
    conf = _confirm()
    ds_tf = C.ds_defs().TFS_OF["F17_Z"][0]
    select = [{"kind": "core", "name": "S2_ST_ROC", "tf": "15m", "rank": 2},
              {"kind": "ds", "name": "F17_Z", "tf": ds_tf, "rank": 1}]
    band = {"30": {"p5": -0.03, "median": 0.01}}
    cands = C.from_watch(conf, select, {"core-S2_ST_ROC-15m-2": band, f"ds-F17_Z-{ds_tf}-1": band})
    assert [c["id"] for c in cands] == ["core-S2_ST_ROC-15m-2", f"ds-F17_Z-{ds_tf}-1"]
    assert all(c["source"]["watch"] for c in cands) and not cands[0]["source"]["passed"]
    assert cands[0]["source"]["band"] == band and "band" not in cands[1]["source"]            # D11
    assert "test_mean" not in cands[1]["source"] and C.check(cands) == []
    acc = {a["id"]: a for a in C.accounts(cands)}
    q, x = acc["core-S2_ST_ROC-15m-2-q"], acc["core-S2_ST_ROC-15m-2-x"]
    assert q["role"] == "quarter" and q["size"] == C.QUARTER and q["combo"] == cands[0]["combo"]
    assert x["role"] == "exitonly" and x["exit"] == cands[0]["exit"] and x.get("size", 1.0) == 1.0
    assert x["combo"] == {k: C._plain(v) for k, v in C.default_combo("core", "S2_ST_ROC").items()}
    assert sorted(a["role"] for a in acc.values()).count("base") == 2
    bad = C.check([{**cands[0], "variants": ["double"]}])
    assert any("variants" in b for b in bad)
