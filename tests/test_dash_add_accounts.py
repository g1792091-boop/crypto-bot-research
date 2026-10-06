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
