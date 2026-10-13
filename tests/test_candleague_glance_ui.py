"""candleague 한눈 지도 (js/screens/glance.js): one card per analysis screen with the snapshot's own sentence, the order to look in."""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_candleague_risk_ui as R  # noqa: E402  (the node DOM stand-in harness)

ROOT = os.path.dirname(HERE)
RUNNER = R.RUNNER.replace("screens/risk.js", "screens/glance.js").replace('"risk"', '"glance"').replace("rulesDefault: M.RULES_DEFAULT", "rulesDefault: null")   # a copy: the risk tests keep their own runner


def run(tmp_path, d, sels=None):
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(R.RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    (tmp_path / "cfg.json").write_text(json.dumps({"static": R.STATIC, "routes": {}, "local": {}, "doc": d, "sels": sels or {}}, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])
SELS = {"cards": "section.card", "links": "a.btn-line", "order": "ol.kd-rules li a", "muted": "p.muted"}


def test_cards_show_each_screens_own_sentence_and_a_link(tmp_path):
    d = R.doc()
    d.update(decision={"summary_ko": "아직 판정 시점이 아닙니다 (3일째)"}, risk={"headline_ko": "열린 포지션 12개"}, dataq={"status_ko": "정상", "headline_ko": "엔진이 5분마다 이어 갑니다"})
    o = run(tmp_path, d, SELS)
    R.no_junk(o["text"])
    assert "아직 판정 시점이 아닙니다 (3일째)" in o["text"] and "열린 포지션 12개" in o["text"] and "정상 · 엔진이 5분마다 이어 갑니다" in o["text"]
    hrefs = [x["a"].get("href") for x in o["sel"]["links"]]
    assert "#/decision" in hrefs and "#/risk" in hrefs and "#/dataq" in hrefs and "#/timeline" in hrefs
    assert [x["a"].get("href") for x in o["sel"]["order"]] == ["#/home", "#/decision", "#/risk", "#/monthsim", "#/versus"]


def test_missing_blocks_read_as_not_yet_and_nothing_breaks(tmp_path):
    for d in (R.doc(), None, {"decision": "x", "risk": {"headline_ko": 5}}):
        o = run(tmp_path, d, SELS)
        R.no_junk(o["text"])
        assert "아직 기록이 없습니다" in o["text"] and "한눈 지도" in o["text"]
    assert "실제 비용" not in run(tmp_path, R.doc(), SELS)["text"]            # the cost card only when its block exists


def test_static_rules_tokens_only_and_no_dollar_amount():
    src = open(os.path.join(ROOT, "candleague", "static", "js", "screens", "glance.js"), encoding="utf-8").read()
    assert "5,000" not in src and "innerHTML" not in src and "#" not in src.replace("`#/", "").replace("// #/glance", "")
