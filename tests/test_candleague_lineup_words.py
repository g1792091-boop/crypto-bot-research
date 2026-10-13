"""candleague dashboard: the words of the owner-exit league (owners 10/12-10/13) are its own, never the old league's.

In lineup mode (the snapshot carries ``lineup``: ~26 kinds of account per pick, the decision protocol with day 14 = look only and day 28 =
the one decision) every screen that still said "38 picks x 5 accounts", "same stop for every account", "no pre-registered checkpoint", the
old checkpoints 11/11 · 12/11 · 1/11, "5계좌 비교" or "190계좌" was wrong. These tests mount the screens under node on the DOM stand-in of
test_candleague_rank_ui and read what reached the page:
  (a) 요약: the head's real counts, the hero (kinds side by side by group, the decision's one line, the way to it), the 일정 road
      (시작 → 14일째 첫 확인 → 28일째 판정, the dates of the snapshot's decision, the bar), the LED card's real picks;
  (b) 순위표 · 계좌 비교 · 점검 진행 · 서버 상태 · 읽는 법 · 흐름 · 매매법: the decision is day 28 on the 판정 screen, the screen's name follows
      the league, the counts come from the snapshot, nothing says "같은 손절", "다섯 계좌", "1/4 계좌" or "기본값 계좌";
  (c) 익절·손절·배수 · 커스텀값 · 계좌 자세히 (with a snapshot whose picks carry their exit, and /api/rules made by the server);
  (d) the menu label and the helpers (labels.compareKo, lk.road, lk.allAccountsKo, lk.leagueCounts);
  (e) the old league (no lineup): its words stay exactly as they were."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from candleague import dash as D  # noqa: E402
from candleague import exits as X  # noqa: E402
import test_candleague_kinds_ui as KU  # noqa: E402  (a snapshot with the real 26 kinds, its one-screen runner)
import test_candleague_owner_exits as OX  # noqa: E402  (a three-pick snapshot with five kinds, its multi-screen runner)
import test_candleague_rank_ui as RANK  # noqa: E402
import test_candleague_rules_ui as RU  # noqa: E402  (its free-form node runner)

DAY = 86_400_000
KST = timezone(timedelta(hours=9))


def _mmdd(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=KST).strftime("%m/%d")


def _decision(start_ms: int, days: int, summary: str | None = None) -> dict:
    return {"phase": "decide" if days >= 28 else "observe", "days": days, "checkpoints": {"observe_day": 14, "decide_day": 28}, "min_pairs": 300,
            "alpha": 0.05, "ci_level": 0.9, "family_size": 4, "observe_ms": start_ms + 14 * DAY, "decide_ms": start_ms + 28 * DAY,
            "counts": {"pass": 0, "fail": 0, "wait": 4, "few": 0}, "ds_in_stats": False, "rows": [],
            "summary_ko": summary or f"아직 판정 시점이 아닙니다 ({days}일째, 28일째에 판정)"}


OLD_WORDS = ("같은 손절", "잔고 1등", "5계좌", "다섯 계좌", "다섯 가지 계좌", "38개 계좌", "190계좌", "1/4 계좌", "기본값 계좌", "미리 정한 점검 날짜가 없습니다",
             "고르는 배수가 같", "손절 후보 그대로", "청산만 바꾼")


def _clean(text: str, *, allow=()) -> None:
    for w in OLD_WORDS:
        if w not in allow:
            assert w not in text, w
    for bad in ("NaN", "undefined", "null", "Infinity"):
        assert bad not in text, bad


# ---------------------------------------------------------------- (a) 요약
def _home_doc(days=18.0, decision=True):
    d = KU._doc(scale=10.0, days=days)
    d["accounts"] = [{**a, "pick": "core-X-1h-1"} for a in d["accounts"]]
    if decision:
        d["decision"] = _decision(d["start_ms"], int(days))
    return d


def test_home_hero_chips_decision_line_and_road(tmp_path):
    d = _home_doc(18.0)
    groups = {"main": 0, "control": 0, "research": 0}
    for e in KU.OWNER:
        groups[KU._group(e["label_ko"])] += 1
    o = KU._run(tmp_path, "home", d, sels={"hero": ".s2a-hero", "goal": ".s2a-goal", "led": ".s2a-led", "head": ".scr-head", "chips": ".s2a-krow .pp",
                                            "prog": ".s2a-goal .dl-progbar", "steps": ".s2a-goal .steps li"})
    page, hero, goal = o["text"], o["sel"]["hero"][0]["t"], o["sel"]["goal"][0]["t"]
    # the head: the snapshot's own counts (one pick row here, 26 accounts), never "38 x 5"
    head = o["sel"]["head"][0]["t"]
    assert "후보 리그 한눈에 보기 · 후보 1개 · 계좌 26개" in head and "38개" not in head and "× 계좌 5개" not in head
    # the hero: how many kinds of account, grouped, short names, the decision's one line and the button
    assert "청산 비교" in hero and f"계좌 종류 {len(KU.OWNER)}가지 나란히" in hero
    for ko, n in (("메인", groups["main"]), ("대조", groups["control"]), ("연구용", groups["research"])):
        assert f"{ko} {n}" in hero, ko
    assert [c["t"] for c in o["sel"]["chips"] if c["t"] in (f"메인 {groups['main']}", f"대조 {groups['control']}", f"연구용 {groups['research']}")] == [
        f"메인 {groups['main']}", f"대조 {groups['control']}", f"연구용 {groups['research']}"]            # one pill per group, in the table's order
    assert "실전 후보" in hero                                               # the live candidate is marked on its chip
    assert "판정 한 줄" in hero and d["decision"]["summary_ko"] in hero
    assert "판정 화면 보기" in hero and "계좌 비교" in hero and "5계좌" not in page
    assert "통과하기 전에는 실전에 쓰지 않습니다" in hero
    # the old league's wall of text and its false claims are gone
    _clean(page)
    assert "같은 신호 · 같은 손절로 돌립니다" not in page and "잔고 1등" not in page
    assert len(hero) < 700                                                  # a hero, not a wall of text
    # the road: 시작 → 14일째 첫 확인 → 28일째 판정, the snapshot's own dates, the bar to day 28
    assert "14일째 첫 확인 · 숫자만 보고 아무것도 바꾸지 않음" in goal and "28일째 판정 · 한 번만" in goal and "시작 (설치)" in goal
    assert _mmdd(d["decision"]["observe_ms"]) in goal and _mmdd(d["decision"]["decide_ms"]) in goal
    assert "18일째 / 28일째에 판정" in goal and len(o["sel"]["prog"]) == 1
    steps = [s["c"] for s in o["sel"]["steps"]]
    assert len(steps) == 3 and "done" in steps[0] and "done" in steps[1] and "now" in steps[2]            # day 14 is behind, the decision is next
    assert "판정 화면 보기" in goal and "24시간씩 센 날" in goal
    # the LED card counts the real picks and says what it adds up (one 지금 청산 account per pick)
    led = o["sel"]["led"][0]["t"]
    assert "‘지금 청산’ 계좌 합계 잔고" in led and "후보 1개의 ‘지금 청산’ 계좌의 지갑 합계" in led and "판정까지" in led and "10일 남음" in led
    assert "판정 없음" not in led and "후보 38개" not in led


def test_home_road_before_day_14_without_a_decision_block_and_after_day_28(tmp_path):
    # no ``decision`` yet (the engine has not written it): the same 14 / 28 days from the start, an honest line, the way to the screen
    d = _home_doc(5.0, decision=False)
    o = KU._run(tmp_path, "home", d, sels={"steps": ".s2a-goal .steps li", "hero": ".s2a-hero"})
    goal = o["text"]
    assert "판정 기록은 아직 없습니다" in o["sel"]["hero"][0]["t"] and "판정 화면 보기" in o["sel"]["hero"][0]["t"]
    assert _mmdd(d["start_ms"] + 14 * DAY) in goal and _mmdd(d["start_ms"] + 28 * DAY) in goal and "5일째 / 28일째에 판정" in goal
    steps = [s["c"] for s in o["sel"]["steps"]]
    assert "done" in steps[0] and "now" in steps[1] and steps[2].strip() == ""                       # the first look is next
    # past day 28: the decision day has passed
    d = _home_doc(30.0)
    d["decision"]["summary_ko"] = "통과한 것 0개: 새 구조에서 우위를 찾지 못했습니다"
    o = KU._run(tmp_path, "home", d, sels={"steps": ".s2a-goal .steps li", "hero": ".s2a-hero"})
    assert "통과한 것 0개: 새 구조에서 우위를 찾지 못했습니다" in o["sel"]["hero"][0]["t"] and "판정일 지남" in o["text"] and "30일째 / 28일째에 판정" in o["text"]
    assert all("done" in s["c"] for s in o["sel"]["steps"])


def test_home_of_the_old_league_keeps_its_words(tmp_path):
    d = KU._doc(scale=10.0, days=18.0, lineup=False, kinds=False, pairs=False)
    d["watch"] = {"checkpoints": [], "pools": {}}
    o = KU._run(tmp_path, "home", d, sels={"head": ".scr-head", "led": ".s2a-led"})
    assert "후보 리그 한눈에 보기 · 커스텀값 후보 38개 × 계좌 5개" in o["sel"]["head"][0]["t"]
    assert "후보 38개 계좌의 지갑 합계" in o["text"] and "점검 진행 →" in o["text"] and "점검도 묶음마다 따로" in o["text"]
    assert "판정 한 줄" not in o["text"] and "14일째 첫 확인" not in o["text"]


# ---------------------------------------------------------------- (b) the other screens of the league
def _owner_doc():
    d = OX._ui_league()
    d["equity0"] = 1000
    d["start_ms"] = d["started_ms"] = d["done_ms"] - 18 * DAY
    d["decision"] = _decision(d["start_ms"], 18)
    return d


@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    d = _owner_doc()
    out = OX._node(tmp_path_factory.mktemp("lw"), d, ["rank", "compare", "check", "status", "howto", "home"])
    return d, out["screens"]


def test_rank_names_the_decision_day_and_the_screens_name(pages):
    d, s = pages
    t = s["rank"]["text"]
    assert "판정은 28일째에 판정 화면의 규칙으로만 합니다" in t and "순위와 ▲▼는 모두 참고이고 판정이 아닙니다" in t
    assert "11/11" not in t and "점검 날(" not in t and "5계좌 비교" not in t and "동전 ▲▼ = 같은 후보의 동전 계좌" not in t
    assert "계좌 비교" in t and "같은 후보의 ‘지금 청산’ 계좌와 비교한 숫자는 모두 참고입니다 (판정은 28일째에 판정 화면에서 한 번만)" in t
    _clean(t)


def test_compare_says_what_the_accounts_share_and_what_they_do_not(pages):
    d, s = pages
    t = s["compare"]["text"]
    assert "같은 후보의 계좌는 같은 신호로 들어갑니다" in t and "필터 계좌는 일부 신호를 건너뛰고" in t and "동전 짝은 같은 시각에 방향만 동전으로 정합니다" in t
    assert "시작 잔고와 배수(레버리지)를 고르는 규칙은 모든 계좌가 같습니다" in t
    assert "손절 거리는 계좌마다 다를 수 있습니다" in t and "‘지금 청산’은 후보의 지금 손절 그대로" in t and "메인은 모두 최대 2 ATR" in t
    assert "손절 거리가 다르면 같은 규칙이 고르는 배수도 달라질 수 있습니다" in t
    assert "청산 방법이 다르고, 손절 거리도 다를 수 있습니다" in t
    assert "계좌 종류 5가지가 뭔가요" in t and "후보마다 계좌 (종류 5가지)" in t
    assert "손절은 모든 계좌가 후보의 것" not in t and "같은 손절이라" not in t
    _clean(t)


def test_check_points_to_the_decision_instead_of_the_old_checks(pages):
    d, s = pages
    t = s["check"]["text"]
    assert "대신 14일째에 숫자만 보고 28일째에 한 번 판정합니다" in t and "계좌 종류 5가지를 같은 신호로 나란히" in t
    assert "14일째 첫 확인" in t and "28일째 판정 · 한 번만" in t and "승자는 판정 화면의 규칙으로만 가립니다" in t
    assert "승자를 가리는 판정은 판정 화면에서 28일째 한 번" in t
    assert "2차 점검에서 묶음이" not in t and "1차 11/11" not in t and "WATCH_PREREG.md" not in t
    assert "동전 최장" not in t                                               # no per-pick 동전 account here
    assert "23개 다 차면" not in t
    _clean(t)


def test_status_shows_the_road_and_the_real_counts(pages):
    d, s = pages
    t = s["status"]["text"]
    ob, de = d["decision"]["observe_ms"], d["decision"]["decide_ms"]
    assert f"14일째 첫 확인 {_mmdd(ob)} · 28일째 판정 {_mmdd(de)}" in t and "판정 일정" in t and "점검 날짜" not in t
    n_acc = len(d["accounts"])
    assert f"{n_acc}개 (후보 3개 × 계좌 종류 5가지 · 후보에 따라 없는 종류가 있음)" in t and "기본값은 칸마다 1개" not in t
    _clean(t)


def test_howto_describes_this_league(pages):
    d, s = pages
    t = s["howto"]["text"]
    n_acc = len(d["accounts"])
    assert "커스텀값 후보 3개(매매법 3개)" in t and "계좌 5가지 종류" in t and f"계좌는 모두 {n_acc}개" in t
    assert "판정은 어떻게 하나요 (미리 정함)" in t and "첫 확인: 숫자만 봅니다" in t and "딱 한 번 판정합니다" in t
    assert _mmdd(d["decision"]["observe_ms"]) in t and _mmdd(d["decision"]["decide_ms"]) in t
    assert "판정에 쓰는 비교는 4개뿐" in t and "쌍 300개 이상" in t and "‘우위 없음’이 결론" in t
    assert "같은 후보의 계좌는 같은 신호로 들어갑니다" in t and "손절 거리는 계좌마다 다를 수 있습니다" in t
    for screen in ("판정", "짝 비교", "청산 이유", "목표 진척도", "구조 기준", "메인 vs 대조", "계좌 비교"):
        assert screen in t, screen
    assert "점검 (미리 고정)" not in t and "11/11" not in t and "후보 38개" not in t and "5년 시험 · 38개 중" not in t
    assert "계단 잠금" in t and "두 분이 정한 계단" in t and "규칙봇과 기본값 계좌가 씁니다" not in t
    assert "1/4 계좌는 그 1/4" not in t and "(1/4 계좌는 약 4배 넓음)" not in t
    assert "통과하기 전에는 어떤 것도 실전에 쓰지 않습니다" in t and "1/4 크기 이하" not in t
    _clean(t)


def test_menu_label_and_titles_follow_the_league(tmp_path):
    d = _owner_doc()
    cfg = {"routes": {"/api/league": d}}
    o = RU._run(tmp_path, cfg, r"""
const LB = await import(`file://${S}/js/labels.js`);
out.owner = LB.compareKo();
LK.setLeague({...doc, lineup: undefined});
out.old = LB.compareKo();
LK.setLeague(doc);
out.again = LB.compareKo();
""")
    assert o["owner"] == "계좌 비교" and o["old"] == "5계좌 비교" and o["again"] == "계좌 비교"
    app = open(os.path.join(ROOT, "candleague", "static", "js", "app.js"), encoding="utf-8").read()
    assert '{id: "compare", ko: "5계좌 비교", group: "study"}' in app                      # the candidate league's label stays as written
    assert 'Object.defineProperty(MENU.find((m) => m.id === "compare"), "ko"' in app and "compareKo()" in app
    assert "function refreshMenuWords()" in app and "onLineup(() => refreshMenuWords())" in app
    # every title that names the old league's counts has an owner-exit version
    own = re.search(r"function ownerTitle\(id\) \{(.*?)\n\}", app, re.S).group(1)
    for key in ("check", "rank", "compare", "weekly", "rules", "howto"):
        assert re.search(rf"\b{key}: ", own), key
    assert "190개" not in own and "38개" not in own and "5개" not in own and "11/11" not in own


def test_lineup_helpers(tmp_path):
    d = _owner_doc()
    cfg = {"routes": {"/api/league": d}}
    o = RU._run(tmp_path, cfg, r"""
out.counts = LK.leagueCounts(doc);
out.road = LK.road(doc);
out.roadNoDecision = LK.road({...doc, decision: undefined});
out.roadNone = LK.road({accounts: []});
out.dates = LK.roadDates(doc).map((x) => [x.ko, x.ms]);
out.all = LK.allAccountsKo(doc);
LK.setLeague({...doc, lineup: undefined});
out.allOld = LK.allAccountsKo(doc);
""")
    n = len(d["accounts"])
    assert o["counts"] == {"picks": 3, "strategies": 3, "accounts": n, "kinds": 5}
    dec = d["decision"]
    assert o["road"] == {"start_ms": d["start_ms"], "observe": 14, "decide": 28, "observe_ms": dec["observe_ms"], "decide_ms": dec["decide_ms"], "days": 18,
                         "phase": "observe"}
    assert o["roadNoDecision"]["observe_ms"] == d["start_ms"] + 14 * DAY and o["roadNoDecision"]["decide_ms"] == d["start_ms"] + 28 * DAY
    assert o["roadNoDecision"]["days"] == 18 and o["roadNone"] is None
    assert o["dates"] == [["14일째 확인", dec["observe_ms"]], ["28일째 판정", dec["decide_ms"]]]
    assert o["all"] == f"{n}계좌" and o["allOld"] == "190계좌"


# ---------------------------------------------------------------- (c) the rule screens, with /api/rules made by the server
def _rule_world():
    d = _owner_doc()
    for a in d["accounts"]:
        a["exit_ko"] = X.exit_ko(a["exit"])
    rules = D.rules_doc(d, {}, RU.EX, RU.ATR)
    rules.update(atr=RU.ATR, atr_ms=d["done_ms"] - 60_000, atr_source="fake", atr_loading=False, server_ms=d["done_ms"])
    meta = json.load(open(os.path.join(ROOT, "candleague", "data", "strategies_ko.json"), encoding="utf-8"))
    for k, v in RANK.META["strategies"].items():                              # the synthetic league's names the real file lacks
        meta["strategies"].setdefault(k, {**v, "kind": "ds" if k.startswith("F") else "core", "family": "", "params": [], "long": "", "short": ""})
    return d, {"/api/league": d, "/api/rules": rules, "/api/meta": meta, "/api/insight": {"accounts": {}}, "/api/fills": {"fills": []},
               "/api/checkpoints": {"due": [], "results": {}}, "/api/race": {"t": [], "pools": {}, "generated_ms": d["generated_ms"]}}


def test_rules_and_custom_and_account_screens_in_the_lineup(tmp_path):
    d, routes = _rule_world()
    assert routes["/api/rules"]["picks"], "the snapshot's picks (with their exit) reach the rules doc"
    o = RU._run(tmp_path, {"routes": routes}, r"""
const r = await mount("rules");
out.answers = txt(r.querySelector(".rl-qa"));
out.page = txt(r);
out.card = txt(r.querySelector(".rl-pickcard"));
const c = await mount("custom");
out.custom = txt(c);
const a = await mount("account", {}, "core-OBV_S-1h-3-e");
out.account = txt(a);
const w = await mount("weekly");
out.weekly = txt(w);
const s = await mount("strategies");
out.strat = txt(s);
""")
    a, page, card = o["answers"], o["page"], o["card"]
    assert "후보마다 ‘지금 청산’ 계좌는 5년 탐색(84가지 청산 중)에서 각자 고른 익절·손절을 씁니다" in a and "다른 종류의 계좌는 청산 방법이 다릅니다" in a
    assert "기본값 계좌만" not in a and "(1/4 계좌는" not in a and "후보 크기" not in a and "‘지금 청산’ 계좌는 아직 닫힌 거래가 없습니다" in a
    assert "계좌 종류 5가지는 무엇이 다른가" in page and "모든 계좌가 같은 규칙 · 규칙봇과 같은 엔진" in page
    assert "다섯 계좌" not in page and "계좌 5개는" not in page and "1/4" not in page and "기본값 계좌" not in page and "후보 크기" not in page
    assert "손절 거리는 계좌마다 다를 수 있습니다" in page and "모든 계좌가 같은 신호 · 같은 크기 · 같은 배수 규칙" not in page
    assert "진입 때 청산까지" in page and "(후보 · 1/4 크기)" not in page
    assert "같은 손절" not in page and "손절 거리도 후보의 것 그대로라" not in page
    assert "손절 2 ATR이면" in card and "1/4" not in card and "기본값" not in card and "다섯 계좌" not in card
    assert "이 후보의 계좌" in card and "개의 익절·손절과 실제로 쓴 배수" in card
    # the 커스텀값 screen: the pick's accounts counted from what it has (the OBV pick has no -tp50), no 기본값 account claimed
    assert "후보의 ‘지금 청산’ 계좌가 그 익절·손절을 씁니다" in o["custom"] and "기본값 계좌는 지금 규칙봇 청산" not in o["custom"]
    assert "지금 계좌 4개" in o["custom"] and "지금 계좌 5개" in o["custom"] and "바뀐 값" in o["custom"]
    # 계좌 자세히 of the OBV pick: four accounts, a shared leverage rule, no "계좌 5개"
    ac = o["account"]
    assert "같은 후보의 계좌 4개" in ac and "계좌 4개" in ac and "모든 계좌 공통 배수 규칙" in ac and "계좌 5개" not in ac and "‘지금 청산’ 계좌" in ac
    # 흐름 and 매매법: no 기본값 · 동전 band, no 2차 점검
    wk = o["weekly"]
    assert "계좌 종류마다 시간에 따른 잔고 중앙값 · 주마다 거래 수 · 승률" in wk and "판정은 이 주 단위가 아니라 하루 단위로 섞어 계산합니다" in wk
    assert "2차 점검" not in wk and "주마다 후보 · 기본값 · 동전" not in wk and "회색 띠" not in wk
    assert "후보 리그의 매매법 16개" not in o["strat"] and "기본값 · 동전" not in o["strat"] or "조절하는 숫자 (기본값)" in o["strat"]
    for key in ("answers", "page", "custom", "account", "weekly"):
        _clean(o[key])


def test_rules_doc_without_a_pick_exit_still_renders_the_rest(tmp_path):
    d, routes = _rule_world()
    cand = next(a for a in d["accounts"] if a["role"] == "cand")
    bare = {k: v for k, v in cand.items() if k not in ("exit", "exit_ko")}
    d2 = {**d, "accounts": [bare if a is cand else a for a in d["accounts"]]}
    doc = D.rules_doc(d2, {}, RU.EX, RU.ATR)                                   # the KeyError of the pick without an exit
    assert cand["id"] not in doc["picks"] and len(doc["picks"]) == 2
    routes = {**routes, "/api/league": d2, "/api/rules": doc}
    o = RU._run(tmp_path, {"routes": routes}, r"""
const r = await mount("rules");
out.page = txt(r);
out.rows = r.querySelectorAll(".rl-row").length;
""")
    assert o["rows"] == 3 and "배수(레버리지) 규칙" in o["page"]               # the screen lists the snapshot's picks; the one without an exit has no rule numbers, no crash


def test_positions_and_terminal_open_on_main_plus_control_in_the_owner_league():
    """The first view of 터미널 / 포지션 is 메인만 (not the 연구 / 필터 kinds, not just the 지금 청산 account); the group helper reads the label's first word."""
    root = os.path.join(ROOT, "candleague", "static", "js")
    for f in ("screens/terminal.js", "screens/positions.js"):
        src = open(os.path.join(root, f), encoding="utf-8").read()
        assert 'lineupOn() ? "k2" : "cand"' in src, f
    pk = open(os.path.join(root, "poskit.js"), encoding="utf-8").read()
    assert '{id: "k2", ko: "핵심 2개"}' in pk and '{id: "mn", ko: "메인만"}' in pk and '{id: "mc", ko: "메인 + 대조"}' in pk and 'kindGroup(p.role)' in pk
    lb = open(os.path.join(root, "labels.js"), encoding="utf-8").read()
    assert 'w === "메인" ? "main" : w === "대조" ? "control"' in lb
    rules = open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json"), encoding="utf-8").read()
    assert "원래 메인" not in rules and "(원래 방식)" in rules
