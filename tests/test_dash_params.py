"""숫자(파라미터) 시험 결과 (dash/more/params.py, screens/strategies-params.js): GET /api/v4/params/<strategy>.

Checks: the route sits behind the login and answers for a core strategy (one row per timeframe x parameter, counted
straight from agents/research_prior.json, the whole-study totals counted from the same file: 1,680 variants, no sharp
peak), for the reel (its choice variants from research/reel5m/out/per_variant.csv, the live choice marked once per
dimension), for a DeepSeek definition ("이 매매법은 숫자 변형 시험 없음" + its timeframe x exit rows as counts only), and
404 for an unknown id; no answer carries a money field (DeepSeek carries no per-trade return either); every one of the
36 and the 44 answers; a missing research file is a plain "no data" answer, never a 500; the files are cached and
never written; the panel module exists, is imported by strategies-detail.js with one additive line, calls the route,
labels everything 5년 과거 시험 (참고) and builds its DOM with h() / s() only."""

import csv
import json
import os
import re
import sqlite3

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.config import DS200_FAMILY  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import params as P  # noqa: E402
from paperbot.store3 import SCHEMA  # noqa: E402

PW = "correct horse battery"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
MONEY_KEYS = re.compile(r"pnl|money|usdt|wallet|equity|balance|profit|roe", re.I)


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def _keys(x, path=""):
    """Every dict key in a JSON answer, with its path."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, f"{path}.{k}"
            yield from _keys(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _keys(v, f"{path}[{i}]")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db = str(tmp_path_factory.mktemp("params") / "paper3.db")
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)
    c.close()
    tc = TestClient(create_app(db, hash_password(PW), b"p" * 32))
    assert tc.get("/api/v4/params/N03_ADX_GC").status_code == 401           # behind the same login
    assert tc.post("/api/login", json={"password": PW}).status_code == 200
    assert "params" in tc.app.state.more
    return tc


def _prior():
    with open(P.RESEARCH_PRIOR, encoding="utf-8") as fh:
        return json.load(fh)


def test_core_strategy_one_row_per_timeframe_and_parameter(client):
    r = client.get("/api/v4/params/N03_ADX_GC")
    assert r.status_code == 200
    d = r.json()
    assert d["group"] == "core" and d["available"] and d["has_param_test"] and d["label_ko"] == "5년 과거 시험 (참고)"
    src = _prior()["strategies"]["N03_ADX_GC"]["parameters"]
    c = d["core"]
    assert c["variants"] == src["variants"] == 48 and c["adopted"] == src["adopted"] == 0
    assert len(c["rows"]) == len(src["params"])
    want = {(p["tf"], p["param"]): p for p in src["params"]}
    for row in c["rows"]:
        assert set(row) == {"tf", "param", "param_ko", "shape", "shape_ko", "variants", "positive_all3", "positive_values"}
        p = want[(row["tf"], row["param"])]
        assert row["shape"] in ("flat", "smooth", "sharp", "thin")
        assert row["shape_ko"] == P.SHAPE_KO[row["shape"]] and p["shape_ko"] == row["shape_ko"]
        assert row["variants"] == p["variants"] and row["positive_all3"] == len(p["positive_all3"])
        assert [x["value"] for x in row["positive_values"]] == [str(x["value"]) for x in p["positive_all3"]]
    assert [r["tf"] for r in c["rows"]] == sorted((r["tf"] for r in c["rows"]), key=["15m", "30m", "1h", "4h"].index)
    assert c["positive_all3"] == sum(len(p["positive_all3"]) for p in src["params"]) == 3
    assert {r["param_ko"] for r in c["rows"]} >= {"ADX 길이", "느린 EMA 길이"}           # plain words where obvious
    assert c["untested_ko"] and "30분봉" in c["untested_ko"]
    # the whole study, counted from the same file (never typed in)
    st = c["study"]
    assert st["strategies"] == 36 and st["variants"] == 1680 == _prior()["totals"]["parameters"]
    assert st["shapes"]["sharp"] == 0 and sum(st["shapes"].values()) == st["params"] == 420
    assert st["positive_all3"] == sum(len(p["positive_all3"]) for s in _prior()["strategies"].values()
                                      for p in s["parameters"]["params"])
    assert "1,680" in c["meaning_ko"] and f"{st['positive_all3']}개" in c["meaning_ko"]
    # the plain explanation: the trap, and how new numbers get tested
    assert "운" in d["trap_ko"] and "함정" in d["trap_ko"]
    assert "세 기간 시험" in d["lab_ko"] and "새 모의 계좌" in d["lab_ko"] and "바꾸지 않습니다" in d["lab_ko"]
    assert [x["shape"] for x in d["shapes_ko"]] == ["flat", "smooth", "sharp", "thin"]
    assert "위험 신호" in d["shapes_ko"][2]["note_ko"]


def test_reel_variant_table_comes_from_per_variant_csv(client):
    d = client.get("/api/v4/params/REEL_H1").json()
    assert d["group"] == "reel" and d["available"] and d["core"] is None and d["ds"] is None
    with open(P.REEL_VARIANTS, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    r = d["reel"]
    assert len(r["rows"]) == len(rows) == 6
    by = {x["variant"]: x for x in r["rows"]}
    for src in rows:
        x = by[src[""]]
        assert x["configs"] == int(src["configs"]) and x["dimension"] == src["dimension"]
        assert x["positive"] == {k: int(src[f"{k}_pos"]) for k in ("is", "cf", "pre")}
        assert x["all3_positive"] == int(src["all3_positive"])
    live = [x["variant"] for x in r["rows"] if x["live"]]
    assert sorted(live) == ["CLOSE", "LONG", "SMA200"]                      # H1: one live choice per dimension
    assert r["configs"] == 40 and r["candidates"] == 0 and r["h1_pass"] is False
    assert [x["tf"] for x in r["by_tf"]] == ["5m", "15m", "30m", "1h", "4h"] and sum(x["live"] for x in r["by_tf"]) == 1


def test_deepseek_definition_says_no_number_variants_and_counts_only(client):
    d = client.get("/api/v4/params/F10_OTE").json()
    assert d["group"] == "ds200" and d["has_param_test"] is False and d["core"] is None and d["reel"] is None
    assert d["none_ko"] == "이 매매법은 숫자 변형 시험 없음" == d["ds"]["none_ko"]
    with open(P.DS_PRIOR, encoding="utf-8") as fh:
        tests = json.load(fh)["strategies"]["F10_OTE"]["tests"]
    x = d["ds"]
    assert len(x["rows"]) == len(tests) == x["configs"] == 8
    for row, t in zip(x["rows"], tests):
        assert (row["tf"], row["exit"]) == (t["tf"], t["exit"])
        assert row["trades"] == {k: t[f"{k}_n"] for k in ("is", "cf", "pre")}
        assert row["positive"] == {k: t[f"{k}_mean_pct"] > 0 for k in ("is", "cf", "pre")}
        assert row["positive_periods"] == sum(row["positive"].values())
    # counts only: no per-trade return, no money (owners D10 / D11)
    for k, where in _keys(d):
        assert "pct" not in k and not re.match(r"mean(_|$)", k), where
    assert x["study"]["configs"] == 342 and x["study"]["candidates"] == 0 and x["study"]["definitions"] == 44


def test_unknown_id_is_404_and_no_answer_carries_money(client):
    r = client.get("/api/v4/params/NOT_A_STRATEGY")
    assert r.status_code == 404 and r.json()["detail"] == "그런 매매법이 없습니다"
    assert client.get("/api/v4/params/RANDOM_1@15m").status_code == 404
    for sid in ("N03_ADX_GC", "V39_ALL", "REEL_H1", "F9_FVG"):
        d = client.get(f"/api/v4/params/{sid}").json()
        bad = [where for k, where in _keys(d) if MONEY_KEYS.search(k)]
        assert not bad, (sid, bad)


def test_every_core_strategy_and_every_deepseek_definition_answers():
    for sid in _prior()["strategies"]:
        d = P.answer(sid)
        assert d["group"] == "core" and d["has_param_test"] and d["core"]["rows"], sid
    for sid in DS200_FAMILY:
        d = P.answer(sid)
        assert d["group"] == "ds200" and d["ds"] and d["ds"]["rows"] and not d["has_param_test"], sid
    assert len(DS200_FAMILY) == 44


def test_missing_research_file_is_a_plain_answer_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "RESEARCH_PRIOR", str(tmp_path / "gone.json"))
    monkeypatch.setattr(P, "REEL_VARIANTS", str(tmp_path / "gone.csv"))
    monkeypatch.setattr(P, "DS_PRIOR", str(tmp_path / "gone2.json"))
    d = P.answer("N03_ADX_GC")
    assert d["available"] is False and d["core"] is None and d["none_ko"]
    r = P.answer("REEL_H1")
    assert r["available"] is False and r["reel"] is None
    s = P.answer("F10_OTE")
    assert s["group"] == "ds200" and s["available"] is False and s["none_ko"] == "이 매매법은 숫자 변형 시험 없음"


def test_files_are_cached_and_never_written():
    before = {p: os.stat(p).st_mtime_ns for p in (P.RESEARCH_PRIOR, P.DS_PRIOR, P.REEL_VARIANTS)}
    a, b = P._core_doc(), P._core_doc()
    assert a is b and P._ds_doc() is P._ds_doc() and P._reel_doc() is P._reel_doc()
    P.answer("N03_ADX_GC"), P.answer("REEL_H1"), P.answer("F10_OTE")
    assert {p: os.stat(p).st_mtime_ns for p in before} == before
    src = _read(os.path.join(ROOT, "paperbot", "dash", "more", "params.py"))
    assert "sqlite3" not in src and not re.search(r"open\([^)]*['\"]w", src)


def test_panel_module_is_present_imported_and_honest():
    js = _read(os.path.join(SCREENS, "strategies-params.js"))
    detail = _read(os.path.join(SCREENS, "strategies-detail.js"))
    assert 'import {paramsCard} from "./strategies-params.js";' in detail
    assert re.search(r"^\s*paramsCard\(ctx, name, kind, \{after: profCard, scope: sc\}\);", detail, re.M)
    assert "export function paramsCard" in js and "`/api/v4/params/${encodeURIComponent(name)}`" in js
    assert "숫자(파라미터) 시험 결과" in js and "5년 과거 시험 (참고)" in js and "이 매매법은 숫자 변형 시험 없음" in js
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString"):
        assert bad not in js, bad
    for bad in ("up", "good"):                                  # no pass / fail colours on the counts
        assert f'"{bad}")' not in js and f"'{bad}'" not in js
    css = _read(os.path.join(SCREENS, "strategies-params.css"))
    assert '@import url("strategies-params.css");' in _read(os.path.join(SCREENS, "strategies.css"))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"/\*.*?\*/", "", css, flags=re.S))
    assert "/api/v4/params" in _read(os.path.join(ROOT, "paperbot", "dash", "static", "v4", "INVENTORY.md"))


def test_texts_match_the_sources(monkeypatch, tmp_path):
    """Review fixes: every parameter of the study has a plain name; 뾰족 is about the CURRENT number (the study's
    definition: the default better than both neighbours), not any lone point; the lab line says a pass is only a
    proposal that needs both owners' OK (docs/newlab-prereg.md 6장); a positive variant is labelled as a x-variant, not
    "기본의 n배" (a level variant moves the distance from a neutral line); the reel never claims an H1 result or "no
    combination" without its summary file."""
    names = {r["param"] for s in _prior()["strategies"].values() for r in s["parameters"]["params"]}
    assert not sorted(n for n in names if n not in P.PARAM_KO)
    assert "지금 숫자" in P.SHAPE_NOTE_KO["sharp"] and "지금 숫자" in P.answer("V39_ALL")["core"]["meaning_ko"]
    assert "두 분이 OK" in P.LAB_KO and "제안" in P.LAB_KO
    js = _read(os.path.join(SCREENS, "strategies-params.js"))
    assert "기본의 ${" not in js and " 변형)`" in js
    monkeypatch.setattr(P, "REEL_SUMMARY", str(tmp_path / "gone.json"))
    P._CACHE.pop("reel", None)
    try:
        r = P.answer("REEL_H1")["reel"]
        assert r["h1_pass"] is None and r["configs"] is None and r["meaning_ko"] is None
    finally:
        P._CACHE.pop("reel", None)
