"""add-accounts (owners 10/06 "전부 지금"): the review items on 계좌, 결재함 and the meeting links.

- 흐름 레이스: outside events nearer than 40 px share one mark, names stacked (FOMC over PCE, never "FOMCE");
- 회의 '근거': packet paths in plain Korean (loss_cards[0].tags -> 손실 카드 1번 › 태그), JSON never shown raw;
- 한눈 지도: the default colour is the account's own return (a big loss is never gold), 동전 봇 대비 second;
- 계좌 '왜 이 수익률인가' card: fees / funding waterfall, exit reasons, win rate vs the break-even rate, the biggest
  losses with their replays; DeepSeek: exit-reason counts only (no money, owners' D10 / D11);
- 승인한 복제 계좌: 원본 vs 복제 over the same period (/api/v4/copycmp/<id>);
- 손실 거래 <-> 회의 (/api/v4/losslinks): trade ids the loss meetings stored, checked against the trades' exit times;
- 결재함 (/api/v4/approvals + #/inbox): the 5-year table, for / against lines, what approving does; approving goes
  through the existing POST /api/proposals/<id>/decide only.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")


def _read(name, folder=SCREENS):
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        return f.read()


def _node(imports: str, body: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    base = "file://" + SCREENS
    script = imports.replace("{base}", base) + "\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- 흐름: event labels
def test_close_events_share_one_mark():
    out = _node("const K = await import('{base}/flow-kit.js');", """
      const ev = (x, kind) => ({x, ev: {kind}});
      const c = K.clusterEvents([ev(300, "PCE"), ev(280, "FOMC"), ev(100, "CPI"), ev(500, "NFP"), ev(530, "CPI")]);
      console.log(JSON.stringify({n: c.length, groups: c.map((g) => g.items.map((e) => e.ev.kind)), xs: c.map((g) => g.x),
        gap: K.EV_GAP, none: K.clusterEvents([]).length, bad: K.clusterEvents([{x: NaN, ev: {}}]).length}));""")
    assert out["gap"] == 40
    assert out["groups"] == [["CPI"], ["FOMC", "PCE"], ["NFP", "CPI"]]   # 20 px apart: one mark, both names
    assert out["xs"] == [100, 290, 515]                                    # the mark sits between them
    assert out["none"] == 0 and out["bad"] == 0
    src = _read("flow-kit.js")
    assert "clusterEvents(evs)" in src and "names.map((n, i) => s(\"text\"" in src


# ---------------------------------------------------------------- 회의 '근거' in plain words
def test_evidence_paths_read_in_korean_and_never_as_json():
    out = _node("const E = await import('{base}/rooms-evidence.js');", """
      const p = (x) => E.pathKo(x);
      const g = E.evidenceGroups({evidence: ["board.today.trades", {path: "losses.tag_stats.0.losses", value: 3}, {a: {b: 1}}]}, {});
      const gc = E.evidenceGroups({evidence: ["x"]}, {findings: [{claim: "손절 2건이 추세 반대", evidence: ["loss_cards[0].tags"]}],
        objections: [{claim: "표본 적음", evidence: ["code_result.result.periods.2.diff"]}]});
      console.log(JSON.stringify({a: p("loss_cards[0].tags"), b: p("losses.tag_stats.0.losses"), c: p("board.today.trades"),
        d: p("specialist.by_strategy.15m.mean_roe"), e: p("meta.weird_new_key_xyz"), f: p("by_coin.BTCUSDT.pnl"), g: p(""),
        flat: g, claims: gc, n: E.evidenceCount(gc), v: [E.valueKo(0.123456), E.valueKo(1234.5), E.valueKo({x: 1}), E.valueKo(["a", "b"])]}));""")
    assert out["a"] == "손실 카드 1번 › 태그"
    assert out["b"] == "손실 › 태그 통계 1번 › 손실"
    assert out["c"] == "순위 자료 › 오늘 › 거래 수"
    assert out["d"] == "전담 자료 › 봉별 › 15분봉 › 거래당 평균 ROE"
    assert out["e"] == "기본 정보 › 세부 항목"                          # an unknown key: never the raw English
    assert out["f"] == "코인별 › BTC › 손익" and out["g"] == "세부 항목"
    flat = out["flat"][0]
    assert flat["claim"] is None and [i["name"] for i in flat["items"]] == ["순위 자료 › 오늘 › 거래 수", "손실 › 태그 통계 1번 › 손실",
                                                                         "세부 자료"]
    assert flat["items"][1]["value"] == "3"
    assert not any("{" in i["name"] for i in flat["items"])              # an object is never printed as JSON
    assert [c["claim"] for c in out["claims"]] == ["손절 2건이 추세 반대", "표본 적음"] and out["n"] == 2
    assert out["claims"][1]["items"][0]["name"] == "코드 계산 결과 › 결과 › 2기간 › 차이"     # a period id, not a list index
    assert out["v"][0] == "0.1235" and out["v"][1] == "1,235" and out["v"][2] is None and out["v"][3] == "a, b"
    src = _read("rooms-chat.js")
    assert "JSON.stringify(x)" not in src and "evidenceList(evg)" in src
