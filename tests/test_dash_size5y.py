"""분석 › 손실 크기 규칙 (size5y): the committed 5-year JSON's shape and honesty, the server module (the file as
committed, without the per-cell curves; one cell with them), the routes, and the page's static rules (the 36 only,
the caveat words, the money caption, the coin-flip 참고 note, tokens only)."""
import json
import os
import re
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paperbot.dash import more as MORE  # noqa: E402
from paperbot.dash.more import size5y as SZ  # noqa: E402
from paperbot.dash.tools import size5y as G  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")


def _read(name):
    with open(os.path.join(SCREENS, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def doc():
    assert os.path.getsize(SZ.DATA) < 2_000_000
    with open(SZ.DATA, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- the committed 5-year file
def test_file_shape(doc):
    assert doc["version"] == 1 and doc["label"] == "설명용, 판정 아님" and doc["prereg"] == "docs/size5y.md"
    assert [r["key"] for r in doc["rules"]] == list(G.RULES)
    assert doc["m_keys"] == list(G.M_KEYS) and doc["w_keys"] == list(G.W_KEYS)
    assert [p["key"] for p in doc["periods"]] == ["full", "p1", "p2", "p3"]
    cells = doc["cells"]
    assert len(cells) == 144 and len({(c["s"], c["tf"]) for c in cells}) == 144
    assert {c["tf"] for c in cells} == set(G.TFS)
    nm = len(doc["months"])
    assert doc["months"][0] == "2021-03" and doc["months"][-1] == "2026-09"
    for c in cells:
        for rule in G.RULES:
            r = c["r"][rule]
            assert len(r["full"]) == len(G.M_KEYS) and len(r["curve"]) == nm
            assert r["full"][G.M_KEYS.index("mult")] >= 0
            assert 0 <= r["full"][G.M_KEYS.index("mdd")] <= 1
            if r["full"][G.M_KEYS.index("bust")]:
                assert r["full"][G.M_KEYS.index("bust_at")] is not None
    s = json.dumps(doc)
    assert "NaN" not in s and "Infinity" not in s


def test_pooled_counts_match_the_cells(doc):
    K = doc["m_keys"]
    for rule in G.RULES:
        p = doc["pooled"]["all"][rule]["full"]
        assert p["n"] == 144
        assert p["busts"] == sum(c["r"][rule]["full"][K.index("bust")] for c in doc["cells"])
        full = [c["r"][rule]["full"] for c in doc["cells"]]      # multiples are rounded to 4 significant digits
        lo = sum(1 for m in full if m[K.index("mult")] > 1.0005)
        hi = sum(1 for m in full if m[K.index("mult")] >= 1.0 and m[K.index("taken")] > 0)
        assert lo <= p["up"] <= hi
        assert len(p["curve"]) == len(doc["months"])
        for tf in G.TFS:
            assert doc["pooled"][tf][rule]["full"]["n"] == 36
        assert doc["flips"]["all"][rule]["full"]["n"] == len(G.TFS) * len(G.FLIP_SEEDS)


def test_risk_rules_lose_their_share_and_parity_held(doc):
    for rule, r in G.RISK.items():
        med = doc["pooled"]["all"][rule]["loss_med"]
        assert abs(med - r) < 0.15 * r                    # the median losing trade costs about r of equity
    assert doc["pooled"]["all"]["v4"]["loss_med"] > 0.03  # today's rule: several % per losing trade
    par = doc["parity"]
    assert par["windows"] > 10_000 and par["max_diff"] <= G.PARITY_TOL and par["skipped"] == 0


def test_preregistration_names_the_rules():
    with open(os.path.join(ROOT, "docs", "size5y.md"), encoding="utf-8") as f:
        pre = f.read()
    for words in ("0.5% / 1% / 2%", "배수 절반", "설명용 연구이고 판정이 아닙니다", "2023-01-01, 2025-01-01",
                  "$10 미만", "결과를 본 뒤 바꾼 것"):
        assert words in pre


# ---------------------------------------------------------------- the server module
def test_view_drops_cell_curves_and_cell_has_them(doc):
    v = SZ.view(SZ.load_doc())
    assert "curve" not in v["cells"][0]["r"]["v4"] and "curve" in v["pooled"]["all"]["v4"]["full"]
    c0 = doc["cells"][0]
    one = SZ.cell(SZ.load_doc(), c0["s"], c0["tf"])
    assert one["r"]["r1"]["curve"] == c0["r"]["r1"]["curve"] and one["months"] == doc["months"]
    assert SZ.cell(SZ.load_doc(), "NOPE", "15m") is None


def test_missing_or_bad_file(tmp_path):
    assert SZ.load_doc(str(tmp_path / "none.json"))["unavailable"]
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert SZ.load_doc(str(bad))["unavailable"]
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"version": 0}), encoding="utf-8")
    assert SZ.load_doc(str(old))["unavailable"]


def test_routes_answer():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    assert "size5y" in MORE.MODULES
    app = fastapi.FastAPI()
    done = SZ.register(app, SimpleNamespace())
    assert done["routes"] == ["/api/v4/size5y", "/api/v4/size5y/cell"]
    c = TestClient(app)
    d = c.get("/api/v4/size5y").json()
    assert len(d["cells"]) == 144 and d["label"] == "설명용, 판정 아님"
    s0, tf0 = d["cells"][0]["s"], d["cells"][0]["tf"]
    one = c.get("/api/v4/size5y/cell", params={"s": s0, "tf": tf0}).json()
    assert one["s"] == s0 and len(one["r"]["v4"]["curve"]) == len(d["months"])
    assert c.get("/api/v4/size5y/cell", params={"s": "NOPE", "tf": "15m"}).status_code == 404
    assert c.get("/api/v4/size5y/cell", params={"s": "x" * 200, "tf": "15m"}).status_code == 404


# ---------------------------------------------------------------- the page (static rules)
def test_tab_is_registered_core_only():
    js = _read("analysis.js")
    assert re.search(r'\{id: "size", label: "손실 크기 규칙", path: "/api/v4/size5y", render: SZ\.size, groups: "core"', js)
    assert 'import * as SZ from "./analysis-size.js";' in js
    assert '@import url("analysis-size.css");' in _read("analysis.css")


def test_page_honesty_words_and_safety():
    js = _read("analysis-size.js")
    for words in ("설명용, 판정 아님", "첫 판정 전에 이 결과로 바뀌지 않습니다", "같은 5년 자료로 골라진",
                  "ui.assume(\"closed\"", "ui.refNote(env.verdictTs", "청산을 고정"):
        assert words in js
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat"):
        assert bad not in js
    assert "toFixed" not in js.replace(".toFixed(1)", "")          # only SVG coordinates


def test_css_tokens_only():
    css = _read("analysis-size.css")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    for m in re.finditer(r"font-size\s*:\s*([^;]+);", css):
        assert m.group(1).strip().startswith("var(--t-"), m.group(0)
    for m in re.finditer(r"font\s*:\s*([^;]+);", css):
        if m.group(1).strip() != "inherit":
            assert "var(--t-" in m.group(1), m.group(0)
