"""졸업 길 (#/path, dash/more/gradpath.py + screens/path.js): five stages from an idea to a live candidate, read-only
from the databases the dashboard already reads. The world (tests/gradpath_world.py) is the ana-syn paper3.db plus an
agents3.db / inbox.db / debate.db written with the agents' and the dashboard's own functions.

Checked: real counts per stage (the strategy-room owner post is not an idea), where each item is stuck (the first
failed gate line, the observation period, the owners' click), the verdict before its day says 판정 전 (no pass / fail
word, the performance conditions not counted), after it the passed accounts with DeepSeek as counts only, a missing
source says so instead of a zero, no money key anywhere, the databases are not written, and the screen's wiring."""
import hashlib
import json
import os
import re
import sys
import time

import pytest

fastapi = pytest.importorskip("fastapi")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gradpath_world import build  # noqa: E402
from paperbot.checkpoint import FAIL, HOLD, OBSERVE, PASS1, PASS2  # noqa: E402
from paperbot.dash.more import gradpath as GP  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
MONEY = re.compile(r"^(pnl|usd|usdt|money|equity|wallet|balance|roe|mean_roe|margin)$", re.I)
NOW = int(time.time() * 1000)


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _client(w):
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app
    app = create_app(w["paper"], None, b"s" * 32, agents_db=w["agents"], inbox_db=w["inbox"])
    return TestClient(app)


def _get(c):
    for _ in range(60):
        r = c.get("/api/v4/gradpath")
        assert r.status_code == 200, r.text
        d = r.json()
        if not d.get("pending"):
            return d
        time.sleep(0.25)
    raise AssertionError("still pending")


def _digest(paths):
    out = {}
    for p in paths:
        if p and os.path.exists(p):
            with open(p, "rb") as f:
                out[p] = hashlib.sha256(f.read()).hexdigest()
    return out


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return build(str(tmp_path_factory.mktemp("gp")), NOW)


@pytest.fixture(scope="module")
def answer(world):
    paths = [world["paper"], world["agents"], world["inbox"], world["debate"]]
    c = _client(world)
    before = _digest(paths)
    d = _get(c)
    assert _digest(paths) == before                       # nothing is written to any database
    return d


def _stage(d, sid):
    return next(s for s in d["stages"] if s["id"] == sid)


# ---------------------------------------------------------------- the five stages on the world
def test_five_stages_in_order_with_real_counts(answer):
    assert [s["id"] for s in answer["stages"]] == ["ideas", "tests", "paper", "verdict", "ready"]
    assert [s["ko"] for s in answer["stages"]] == ["아이디어", "5년 시험", "모의 계좌", "30일 판정", "실전 후보"]
    ideas = _stage(answer, "ideas")
    parts = {p["k"]: p["n"] for p in ideas["parts"]}
    assert parts == {"debate": 2, "hypothesis": 2, "owner": 1}          # the strategy-room post is not an idea
    assert ideas["count"] == 5 and ideas["state"] == "has"
    assert [i["ts"] for i in ideas["items"]] == sorted((i["ts"] for i in ideas["items"]), reverse=True)   # newest first
    tests = _stage(answer, "tests")
    assert tests["count"] == 4 and tests["passed"] == 2
    assert {p["k"]: (p["n"], p["good"], p["bad"]) for p in tests["parts"]} == {"newlab": (2, 1, 1), "test": (2, 1, 1)}
    paper = _stage(answer, "paper")
    assert {p["k"]: p["n"] for p in paper["parts"]} == {"core": 144, "ds200": 24, "reel": 1}
    assert paper["count"] == 169 and paper["flips"] == 15                # the coin flips: the yardstick, not candidates
    assert answer["frontier"] == "paper"


def test_where_each_test_is_stuck(answer):
    tests = _stage(answer, "tests")
    by = {i["sub"].split(" · ")[0]: i for i in tests["items"]}
    # most advanced first: the proposal waiting for the owners, then the stored pass, then the failures
    assert [i["tag"] for i in tests["items"]][:2] == ["통과", "통과"]
    assert tests["items"][0]["wait"] == "두 분 승인 기다림"
    passed_new = by["새 매매법 시험 #5"]
    obs = answer["observe"]
    assert obs["observing"] and passed_new["wait"] == f"관찰 기간 {obs['until_ko']}까지 제안 없음"
    failed = by["새 매매법 시험 #4"]
    assert failed["tag"] == "탈락" and failed["wait"].startswith("② 1기간 거래 120건") and "미달" in failed["wait"]
    assert all(i["go"]["name"] == "rooms" for i in tests["items"])
    # the number test is named the lab's way, with the strategy's Korean name (not its code)
    num = by["기존 매매법 숫자 시험 #3"]
    assert "손절폭" in num["title"] and "S5_DONCHIAN_MFI" not in num["title"]


def test_paper_stage_says_how_many_trades_are_missing(answer):
    paper = _stage(answer, "paper")
    core = next(i for i in paper["items"] if i["tag"] == "기존 36")
    assert re.search(r"거래 30건 넘은 계좌 \d+/144 · 가운데 계좌는 거래 \d+건 더 필요", core["wait"])
    assert core["go"] == {"name": "board", "arg": None, "query": {"group": "core"}}


def test_before_the_verdict_no_pass_or_fail_and_no_performance_condition(answer):
    v = _stage(answer, "verdict")
    assert v["state"] == "wait" and v["count"] is None and v["head"].startswith("판정 전 · ")
    assert v["when_ko"] and "첫 판정" in v["when_ko"]
    text = json.dumps(v, ensure_ascii=False)
    for word in (PASS1, PASS2, FAIL, "합격", "통과"):
        assert word not in text, word
    core = next(i for i in v["items"] if i["title"] == "기존 36")
    assert re.fullmatch(r"판정 받을 거래 30건 채운 계좌 \d+/108", core["wait"])          # 4h: observation only
    r = _stage(answer, "ready")
    assert r["count"] == 0 and r["state"] == "none" and "판정 전" in r["none_ko"]
    waits = {i["title"]: i["wait"] for i in r["items"]}
    assert len(waits) == 8
    for label in ("우연 기준(FDR) 통과", "국면 2개 이상 플러스", "옆 봉도 같은 방향"):
        assert waits[label].endswith("판정 뒤에 셈"), label
    assert "충족" not in json.dumps(r["items"], ensure_ascii=False)


def test_no_money_anywhere(answer):
    bad = [k for k in _keys(answer) if MONEY.match(str(k))]
    assert not bad, bad


def test_dplus_and_the_top_bar_count_the_same_day(world):
    from paperbot.dash.app import Data
    s = Data(world["paper"]).summary(NOW)
    rs = s.get("restart") or {}
    want = rs.get("day") if rs.get("ready") else s["day"] - 1
    from paperbot.dash.app import Rooms
    rooms = Rooms(world["agents"], world["inbox"], paper_db=world["paper"])
    d = GP.path_view(Data(world["paper"]), rooms, world["paper"], world["debate"], None, NOW)
    assert d["dplus"] == want and d["dplus"] is not None


# ---------------------------------------------------------------- missing and empty sources
def test_missing_sources_say_so_instead_of_a_zero(tmp_path):
    w = build(str(tmp_path), NOW, agents=False, inbox=False, debate=False)
    d = _get(_client(w))
    ideas, tests = _stage(d, "ideas"), _stage(d, "tests")
    assert ideas["state"] == "off" and ideas["none_ko"].startswith("아직 없음") and not ideas["items"]
    assert tests["state"] == "off" and tests["none_ko"].startswith("아직 없음")
    assert _stage(d, "paper")["count"] == 169


def test_empty_ledgers_are_none_not_off(tmp_path):
    w = build(str(tmp_path), NOW, ideas=False)
    d = _get(_client(w))
    ideas, tests = _stage(d, "ideas"), _stage(d, "tests")
    assert ideas["state"] == "none" and ideas["count"] == 0 and {p["k"]: p["n"] for p in ideas["parts"]} == {
        "debate": 0, "hypothesis": 0, "owner": 0}
    assert tests["state"] == "none" and tests["count"] == 0
    assert "관찰 기간" in tests["none_ko"]                      # why nothing is proposed yet


# ---------------------------------------------------------------- the verdict, after its day (synthetic checkpoint view)
def _board(rows):
    return {"accounts": [{"account_id": a, "group": g, "timeframe": tf, "trades": n, "kind": k}
                         for a, g, tf, n, k in rows]}


def test_after_the_verdict_passed_accounts_and_deepseek_counts_only():
    rows = [{"account_id": "S5_DONCHIAN_MFI@1h", "status": PASS1, "group": "core", "trades": 44},
            {"account_id": "S2_ST_ROC@30m", "status": PASS2, "group": "core", "trades": 80},
            {"account_id": "DS_X@1h", "status": PASS1, "group": "ds200", "trades": 50},
            {"account_id": "DS_Y@1h", "status": FAIL, "group": "ds200", "trades": 50},
            {"account_id": "S9@15m", "status": HOLD, "group": "core", "trades": 12},
            {"account_id": "S9@4h", "status": OBSERVE, "group": "core", "trades": 40}]
    cp = {"ready": True, "date": "2026-11-04", "counts": {PASS1: 2, PASS2: 1, FAIL: 1, HOLD: 1, OBSERVE: 1}, "rows": rows}
    v = GP.verdict_stage(cp, {}, None, NOW, 30)
    assert v["count"] == 3 and v["state"] == "has"
    accts = [i["acct"] for i in v["items"] if i["acct"]]
    assert "S5_DONCHIAN_MFI@1h" in accts and "S2_ST_ROC@30m" in accts
    assert not any(str(a).startswith("DS_") for a in accts)                        # never one DeepSeek account
    ds = next(i for i in v["items"] if i["tag"] == "딥시크")
    assert ds["wait"] == f"{PASS1} 1 · {FAIL} 1" and not ds["acct"]
    assert next(i for i in v["items"] if i["acct"] == "S2_ST_ROC@30m")["wait"].startswith("2차 통과")
    hold = next(i for i in v["items"] if i["tag"] == HOLD)
    assert hold["wait"] == "보류: 거래 18건 더 필요"
    assert "DS_" not in json.dumps(v, ensure_ascii=False)


def test_ready_stage_counts_conditions_after_the_verdict():
    rd = {"summary": {"met_all": 1, "accounts": 144, "days_running": 31.2,
                      "by_condition": {"regimes2": {"✅": 5, "❌": 9, "아직 판단 불가": 130}, "trades200": {"✅": 3}}},
          "conditions": [{"id": "day30", "label": "시작 후 30일"}, {"id": "trades200", "label": "거래 200건"},
                         {"id": "regimes2", "label": "국면 2개 이상 플러스"}]}
    r = GP.ready_stage(rd, True, None, 250)
    w = {i["title"]: i["wait"] for i in r["items"]}
    assert r["count"] == 1 and r["state"] == "has"
    assert w == {"시작 후 30일": "시작 후 30일 지남", "거래 200건": "거래 200건 넘은 계좌 3개",
                 "국면 2개 이상 플러스": "충족 5 · 아님 9 · 판단 전 130"}
    before = GP.ready_stage({**rd, "summary": {**rd["summary"], "met_all": 0, "days_running": 2.4,
                                                   "by_condition": {}}}, False, {"ts": NOW + 20 * 86_400_000}, 6)
    w = {i["title"]: i["wait"] for i in before["items"]}
    assert w["시작 후 30일"] == "30일까지 28일 더" and w["거래 200건"] == "가장 많은 계좌도 거래 194건 더 필요"
    assert w["국면 2개 이상 플러스"].endswith("판정 뒤에 셈")
    assert GP.ready_stage({"pending": True}, False, None, 0)["state"] == "pending"
    assert GP.ready_stage({"error": "paper3.db 없음"}, False, None, 0)["state"] == "off"


def test_trial_wait_words():
    obs = {"observing": True, "until_ko": "10/27"}
    assert GP.trial_wait("newlab", "passed", {}, None, obs) == ("관찰 기간 10/27까지 제안 없음", "accent")
    assert GP.trial_wait("newlab", "passed", {}, None, {"observing": False})[0] == "새 매매법 제안 차례 기다림"
    run = {"effective_status": "approved", "account_running": {"account_id": "X"}}
    assert GP.trial_wait("test", "passed", {}, run, obs) == ("모의 계좌에서 도는 중", "good")
    assert GP.trial_wait("test", "passed", {}, {"effective_status": "rejected"}, obs)[0] == "두 분이 거절"
    assert GP.trial_wait("test", "failed", {"gate": {"reasons": ["① a: 통과", "② b: 미달"]}}, None, obs)[0] == "② b: 미달"
    assert GP.trial_wait("test", "described", {}, None, obs)[0] == "설명용 시험이라 합격·불합격 없음"
    assert GP.trial_wait("newlab", "lapsed", {}, None, obs)[0].startswith("시험 수가 늘어")


def test_paper_stage_lists_extra_accounts_with_trades_missing():
    b = _board([("S5@1h", "core", "1h", 40, "strategy"), ("S5@15m", "core", "15m", 10, "strategy"),
                ("R@1h", "flip", "1h", 50, "random")])
    b["accounts"].append({"account_id": "COPY_1", "group": "extra", "timeframe": "1h", "trades": 7, "kind": "copy",
                          "label_ko": "복사 계좌 1", "created_ts": NOW})
    p = GP.paper_stage(b, 30, "11/4 판정 기다림")
    assert p["count"] == 3 and p["flips"] == 1
    extra = next(i for i in p["items"] if i["tag"] == "추가")
    assert extra["title"] == "복사 계좌 1" and extra["wait"] == "거래 23건 더 필요"
    core = next(i for i in p["items"] if i["tag"] == "기존 36")
    assert core["wait"] == "거래 30건 넘은 계좌 1/2 · 가운데 계좌는 거래 0건 더 필요"
    assert GP.paper_stage({}, 30, "")["state"] == "none"


# ---------------------------------------------------------------- the screen
def test_route_menu_icon_and_files():
    routes = _read("core", "routes.js")
    assert '{id: "strat", ko: "매매법", screens: ["strategies", "grid", "analysis", "path"]}' in routes
    assert 'path: {ko: "졸업 길", group: "strat", title: "졸업 길"}' in routes
    assert re.search(r"\n  path: \(\) => \[", routes)
    js, css = _read("screens", "path.js"), _read("screens", "path.css")
    assert re.findall(r"[\"'`](/api/[^\"'`]*)", js) == ["/api/v4/gradpath"]          # one route, read only
    assert "USDT" not in js and "fmt.money" not in js and "fmt.usdt" not in js      # no money on this page
    assert "d.pending" in js and "ctx.timeout(load" in js                            # the background answer: retried
    assert "설명용, 판정 아님" in js
    assert "gradpath" in _read("INVENTORY.md") and "#/path" in _read("INVENTORY.md")
    assert not re.search(r"font(-size)?:[^;}]*\dpx", css)                          # sizes only as --t-* tokens
    from paperbot.dash import more
    assert "gradpath" in more.MODULES
