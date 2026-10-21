"""실거래 › 분석팀 (#/livebots/team; screens/livebots-team.js on /api/v4/livebots/team, dash/more/livebots.py team()).

The tab reads the 실거래 분석 팀's own records (paperbot/liveteam.py). Its pure functions and the view run in node (the tiny
DOM, tests/anasyn_dom.mjs) on real answers:
- the team world (tests/livebots_world.py team_db: liveteam.db made by liveteam.py itself with FakeRunner answers): a 판단
  회의 and a 주간 보고 done with an idea each, a quiet week, a 손실 회의 stopped by a plan limit; timer on, login checked
- production day 1: no liveteam.db, the timer off: what the team is, the four members, when it meets, the one command,
  that it only reads, the AI caps; never a 0 for the AI use it has no record of
- a file that cannot be read (못 읽음), a failed first load, a failed refresh (the last answer stays, dimmed)
Then static checks of the css (tokens only, --t-* sizes, no endless motion, reduced motion, own prefix) and the js.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

pytest.importorskip("fastapi")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livebots_world as W  # noqa: E402
from paperbot import liveteam as T  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-team.js")
CSS = os.path.join(SCREENS, "livebots-team.css")
NOW = W.NOW
ON = lambda unit: ("active", "enabled")             # noqa: E731
OFF = lambda unit: ("inactive", "disabled")         # noqa: E731


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent")
    monkeypatch.delenv(T.BUDGET_ENV, raising=False)
    L._cache.clear()
    yield
    L._cache.clear()


@pytest.fixture
def team(tmp_path, monkeypatch):
    folder = str(tmp_path / "w")
    p = W.build_world(folder)
    for k, v in W.env_more_of(W.live_checks(p, folder, rich=True)).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv(T.DB_ENV, W.team_db(folder, p))           # team_db sets it too: monkeypatch restores it after
    return json_finite(L.team(p, NOW, units=ON))


@pytest.fixture
def missing(tmp_path, monkeypatch):
    folder = str(tmp_path / "m")
    p = W.build_world(folder)
    monkeypatch.setenv(T.DB_ENV, os.path.join(folder, "liveteam.db"))      # not made: production day 1
    return json_finite(L.team(p, NOW, units=OFF))


def _node(body: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\nconst R = await import('file://{JS}');\n"
              f"const d = {json.dumps(data)};\n{body}")
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _bad_words(text):
    return [w for w in ("null", "undefined", "NaN", "Infinity", "[object") if w in text]


def test_node_check():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    r = subprocess.run([node, "--check", JS], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------- the pure functions
def test_pure_functions_on_the_team_world(team):
    ms = {m["id"]: m for m in team["meetings"]}
    assert [m["state"] for m in team["meetings"]] == ["failed", "done", "quiet", "done"]          # newest first
    out = _node("""const ms = d.meetings, by = Object.fromEntries(ms.map((m) => [m.id, m]));
    const risk = by[3].messages.find((x) => x.role === "risk"), lead = by[3].messages.find((x) => x.role === "lead");
    console.log(JSON.stringify({risk: R.parseText(risk.text), lead: R.parseText(lead.text), odd: R.parseText("첫 줄\\n· a\\n둘째 줄\\n\\n걱정: b"),
      none: R.parseText(""), latest: R.latestDone(ms).id, lines: R.lastLines(ms), timer: R.timerWord(d.timer), auth: R.authWord(d.auth),
      use: R.usageOf(d), cp: R.checkpointOf(d.when), cp0: R.checkpointOf({paper_n: 0, checkpoint_every: 40}), cpx: R.checkpointOf({paper_n: null}),
      st: ms.map((m) => R.stateOf(m, d.now_ms).ko), stale: R.stateOf({state: "running", started_ts: d.now_ms - 3600000}, d.now_ms),
      fresh: R.stateOf({state: "running", started_ts: d.now_ms - 60000}, d.now_ms).ko,
      same: R.sameKey(d) === R.sameKey({...d, now_ms: 1}), diff: R.sameKey(d) === R.sameKey({...d, ideas_open: 9}),
      unknown: [R.timerWord({active: null, enabled: null, on: false}).ko, R.timerWord(null).ko, R.authWord({ok: false, why: "로그인 만료"}).ko]}));""", team)
    r = out["risk"]
    assert r["head"] == "바이비트 -8.35달러, MEXC는 3연패로 멈춤" and r["points"] == ["바이비트 19번 중 12번 이김", "MEXC 멈춤은 규칙대로"]
    assert r["worry"] == "MEXC가 멈춘 동안 페이퍼 진입을 못 따라감" and r["luck"] == "아직 거래가 적어 우연이 큼" and r["other"] == []
    assert out["lead"]["head"] == W.TEAM_LEAD["headline"] and out["lead"]["points"] == W.TEAM_LEAD["summary"]
    assert out["odd"] == {"head": "첫 줄", "points": ["a"], "worry": "b", "luck": None, "other": ["둘째 줄"]}          # nothing dropped
    assert out["none"]["head"] is None and out["none"]["points"] == []
    assert out["latest"] == 3 and ms[3]["kind"] == "weekly"                    # the newest meeting with a conclusion
    # each member's last real line: the plan-limit error of meeting 4 is skipped, meeting 3's words are used
    assert set(out["lines"]) == {"risk", "stats", "market", "lead"} and all(v["id"] == 3 for v in out["lines"].values())
    assert out["lines"]["risk"]["head"] == "바이비트 -8.35달러, MEXC는 3연패로 멈춤" and out["lines"]["lead"]["kind_ko"] == "주간 보고"
    assert out["timer"] == {"ko": "켜짐", "tone": "good", "on": True} and out["auth"]["ko"] == "로그인 확인됨"
    u = {x["id"]: x for x in out["use"]}
    assert (u["day"]["n"], u["day"]["cap"], u["day"]["ratio"]) == (9, 12, 0.75) and (u["week"]["n"], u["week"]["cap"]) == (9, 40)
    assert u["tokens"]["cap"] == 900000 and u["tokens"]["n"] == 0
    assert out["cp"] == {"n": 48, "prev": 40, "next": 80, "ratio": 0.2} and out["cp0"]["next"] == 40 and out["cpx"] is None
    assert out["st"] == ["멈춤", "결론 나옴", "조용히 넘어감", "결론 나옴"]
    assert out["stale"]["tone"] == "warn" and "멈췄을 수 있음" in out["stale"]["ko"] and out["fresh"] == "회의 중"
    assert out["same"] is True and out["diff"] is False
    assert out["unknown"] == ["켜짐 여부 확인 못 함", "확인 못 함", "로그인 문제"]


def test_pure_functions_day1_never_zero(missing):
    assert missing["state"] == "missing" and "분석팀 기록 파일이 아직 없어요" in missing["reason_ko"] and "meetings" not in missing
    out = _node("""console.log(JSON.stringify({use: R.usageOf(d), timer: R.timerWord(d.timer), auth: R.authWord(d.auth), cp: R.checkpointOf(d.when),
      latest: R.latestDone(d.meetings), lines: R.lastLines(d.meetings)}));""", missing)
    assert [x["n"] for x in out["use"]] == [None, None, None] and [x["ratio"] for x in out["use"]] == [None, None, None]   # no record: —, never 0
    assert [x["cap"] for x in out["use"]] == [12, 40, 900000]
    assert out["timer"] == {"ko": "꺼짐", "tone": "warn", "on": False} and out["auth"]["ko"] == "로그인 확인 전"
    assert out["cp"]["n"] == 6 and out["cp"]["next"] == 40                     # the standard world's 6 paper trades
    assert out["latest"] is None and out["lines"] == {}


# ---------------------------------------------------------------- the view in the tiny DOM
VIEW = """const ctx = {api: () => (d && d.__fail ? Promise.reject(Object.assign(new Error("x"), {kind: "network", status: 0})) : Promise.resolve(d)),
  every() {}, watch() {}, alive: () => true, href: (n, a) => '#/' + n + (a ? '/' + a : ''), track() {}, toast() {}};
const v = R.teamView(ctx);
await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
const w = D.walk(v.el);
const tr = d && d.meetings ? d.meetings.map((m) => D.walk(R.transcript(m)).text.replace(/\\s+/g, " ")) : [];
console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), classes: w.classes, tr, hidden: v.el.childNodes.map((c) => !!c.hidden)}));"""


def test_view_team_world(team):
    out = _node(VIEW, team)
    t, cls = out["text"], out["classes"]
    assert not _bad_words(t), _bad_words(t)
    for words in ("실거래 분석팀", "방패", "리스크 담당", "저울", "통계 담당", "나침반", "시장 담당", "등대", "팀장", "분석팀 켜짐", "로그인 확인됨",
                  "시험해 볼 아이디어 2개", "끄는 법", "오늘", "7일", "다음 회의", "주간 보고", "48 / 80번", "두 번 연속 손실 때",
                  "최근 결론", "지켜보기", W.TEAM_LEAD["headline"], "등대 · 팀장의 결론", "잘된 점", "N08_ICHI_WR 15번 모두 이김", "걱정", "다음에 볼 것",
                  "F4_FAN을 강하락 장세에서 빼면 나아지는가", "근거", "시험 방법", "제안", "개선 후보 장부 순서대로",
                  "회의 기록", "조용히 넘어감", "지난주 닫힌 거래가 없어 AI 회의 없이 넘어갑니다", "멈춤", "AI 사용 한도에 걸려",
                  "읽는 법", "AI의 의견이라 참고만", "고정 규칙", "코드가 모은 사실만", "20번 미만이면 결론을 안 내요",
                  "모의 · 실제 시세", "실거래 · 거래소 실제 체결"):
        assert words in t, words
    assert sum(c.split()[0] == "lbt-bub" for c in cls) == 4                    # each member's last stored line
    assert sum(c.split()[0] == "lbt-mrow" for c in cls) == 4 and "분석팀은 아직 꺼져 있어요" not in t
    tr = {m["id"]: x for m, x in zip(team["meetings"], out["tr"])}
    for words in ("방패 리스크 담당", "저울 통계 담당", "나침반 시장 담당", "등대 팀장", "걱정 MEXC가 멈춘 동안", "우연일 정도 p=0.07",
                  "시험해 볼 아이디어 1개", "AI 호출 4번"):
        assert words in tr[3], words
    assert "(답 없음: AI 사용 한도: 5-hour limit reached)" in tr[4] and "회의가 멈췄어요" in tr[4] and "AI 호출 1번" in tr[4]
    for x in out["tr"]:
        assert not _bad_words(x), _bad_words(x)


def test_view_marks_dry_runs_and_running_meetings(team):
    ms = [dict(m) for m in team["meetings"]]
    ms[1] = {**ms[1], "dry": True}
    run = {**ms[3], "id": 99, "state": "running", "started_ts": NOW - 60_000, "headline": None, "verdict": None, "result": {}, "messages": ms[3]["messages"][:1], "ideas": []}
    out = _node(VIEW, {**team, "meetings": [run] + ms})
    t = out["text"]
    assert "회의 중" in t and "회의가 진행 중이에요" in t and "연습" in t
    assert any("연습 (기록 안 함)" in x for x in out["tr"])


def test_view_day1_explains_the_team_and_the_switch(missing):
    out = _node(VIEW, missing)
    t, cls = out["text"], out["classes"]
    assert not _bad_words(t), _bad_words(t)
    for words in ("분석팀은 아직 꺼져 있어요", "무엇을 하나요?", "누가?", "방패(리스크 담당) · 저울(통계 담당) · 나침반(시장 담당) · 등대(팀장)",
                  "언제?", "손실 회의", "판단 회의", "주간 보고", "매매는?", "주문 권한도", "비용은?", "Claude 요금제", "하루 12번 · 7일 40번",
                  "20번쯤", "sudo systemctl enable --now paperbot-liveteam.timer", "sudo systemctl disable --now paperbot-liveteam.timer", "복사",
                  "분석팀 꺼짐", "로그인 확인 전", "지금은 꺼져 있어 열리지 않아요", "분석팀 기록 파일이 아직 없어요", "회의 기록은 분석팀을 켜고"):
        assert words in t, words
    assert "— / 12" in t and "0 / 12" not in t                                 # no record: a dash, never 0
    assert not any(c.split()[0] in ("lbt-bub", "lbt-hero", "lbt-mrow") for c in cls)


def test_view_states_unreadable_and_failed_load(missing):
    bad = {**missing, "state": "error", "reason": "database disk image is malformed", "reason_ko": "분석팀 기록 파일을 읽지 못했어요"}
    t = _node(VIEW, bad)["text"]
    assert "못 읽음" in t and "분석팀 기록 파일을 읽지 못했어요" in t and not _bad_words(t)
    out = _node(VIEW, {"__fail": True})
    assert "서버에 닿지 못했습니다" in out["text"] and out["hidden"] == [False, True]


def test_view_failed_refresh_keeps_the_last_answer_dimmed(team):
    out = _node("""let fail = false, tick = null;
const ctx = {api: () => (fail ? Promise.reject(Object.assign(new Error("x"), {kind: "timeout", status: 0})) : Promise.resolve(d)),
  every(ms, fn) { tick = {ms, fn}; }, watch() {}, alive: () => true, href: (n, a) => '#/' + n, track() {}};
const v = R.teamView(ctx);
await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
fail = true; tick.fn(); await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
const after = D.walk(v.el);
fail = false; tick.fn(); await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
const back = D.walk(v.el);
console.log(JSON.stringify({ms: tick.ms, after: after.text.replace(/\\s+/g, " "), dim: after.classes.filter((c) => /lbt-body.*is-stale/.test(c)).length,
  rows: after.classes.filter((c) => c.split(" ")[0] === "lbt-mrow").length, back: back.classes.filter((c) => /is-stale/.test(c)).length}));""", team)
    assert out["ms"] == 60000
    assert "서버가 제때 답하지 않았습니다" in out["after"] and "자료를 보여 드립니다" in out["after"]
    assert out["dim"] == 1 and out["rows"] == 4 and out["back"] == 0


# ---------------------------------------------------------------- 추세판단 봇 (10-21): the tab follows the running bot
def test_team_on_the_trend_bot(tmp_path, monkeypatch):
    """The 추세판단 봇 runs (tests/test_liveteam.py trend_world): the members' focus on it, its own trades towards the next
    거래 점검 (the bot before it's not counted, no 88 % rule), the intro and the ideas in its words; then a 40번째 거래 점검
    held by liveteam.py itself (FakeRunner) as the tab shows it."""
    import test_liveteam as TL
    from paperbot.agents import runner as R
    _w, since, paths, now = TL.trend_world(tmp_path, monkeypatch)
    day1 = json_finite(L.team(paths, now, units=OFF))             # no liveteam.db yet
    assert day1["state"] == "missing" and day1["bot"]["trend"] is True and day1["bot"]["since"] == since
    assert (day1["when"]["paper_n"], day1["when"]["checkpoint_next"], day1["when"]["checkpoint_ko"]) == (1, 40, "거래 점검")
    assert [r["focus"] for r in day1["roster"]] == [T.ROLES_TREND[k]["focus"] for k in ("risk", "stats", "market", "lead")]
    t1 = _node(VIEW, day1)["text"]
    for words in ("추세판단 봇의 기록(새 봇 시작 뒤 페이퍼·동전 쌍둥이·두 실행기", "새 봇 시작 뒤 페이퍼 거래 40번마다 거래 점검",
                  "1 / 40번", "새 봇 시작 뒤 페이퍼 닫힌 거래 40번마다 · 88% 같은 기준 없음", "새 봇 시작 뒤 거래만",
                  "아이디어는 가설일 뿐이에요. 그림자 봇으로 나란히 보거나 2주 검토에서 두 분이 정해요."):
        assert words in t1, words
    for old in ("판단 회의", "점검 기록, 5년 기준", "개선 후보 장부"):
        assert old not in t1, old
    assert not _bad_words(t1)
    conn = T.connect(os.environ[T.DB_ENV])
    T.tick(conn, TL.trend_41(T.sources(now, paths), since, now), R.FakeRunner(answers={"lead": TL.LEAD}), T.BUDGET_DEFAULT,
           clock=lambda: now)
    conn.close()
    team = json_finite(L.team(paths, now, units=ON))
    (m,) = team["meetings"]
    assert m["kind_ko"] == "거래 점검" and m["title"].startswith("40번째 거래 점검 · ") and m["ideas"]
    assert all(i["how_ko"] == T.TREND_IDEA_HOW_KO for i in m["ideas"])
    t = _node(VIEW, team)["text"]
    for words in ("거래 점검", "최근 결론", TL.LEAD["headline"], "아이디어는 시험해 볼 가설이에요. 그림자 봇으로 나란히 보거나 2주 검토에서 두 분이 정해요."):
        assert words in t, words
    assert "판단 회의" not in t and "개선 후보 장부" not in t and not _bad_words(t)


# ---------------------------------------------------------------- static checks
def test_css_tokens_sizes_prefix_and_motion():
    src = re.sub(r"/\*.*?\*/", "", _read(CSS), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src), "colour literal: use a token"
    assert not re.search(r"\brgba?\(\s*\d", src) and not re.search(r"\bhsla?\(\s*\d", src), "colour literal: use a token"
    for v in re.findall(r"font-size\s*:\s*([^;}]+)", src):
        assert "var(--t-" in v, v
    for v in re.findall(r"(?<![-\w])font\s*:\s*([^;}]+)", src):
        assert "var(--t-" in v or v.strip() == "inherit", v
    assert "infinite" not in src
    assert "@media (prefers-reduced-motion: reduce)" in src and ".lbt-mem.lbt-enter { animation: none; }" in src
    body = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", src)
    body = re.sub(r"@media[^{]*\{", "", body)
    for sel in re.findall(r"([^{}@;]+)\{", body):
        sel = sel.strip()
        if not sel:
            continue
        for part in sel.split(","):
            assert ".lbt" in part, part
    assert '@import url("livebots-team.css")' in _read(os.path.join(SCREENS, "livebots.css"))


def test_js_endpoint_text_safety_and_wiring():
    src = _read(JS)
    assert '"/api/v4/livebots/team"' in src
    code = re.sub(r"//[^\n]*", "", src)
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "localStorage",
                "setInterval("):
        assert bad not in code, bad
    for ref in re.findall(r'from\s+"([^"]+)"', src):
        assert ref == "../core/pb.js" or re.match(r"^\./[\w-]+\.js$", ref), ref
    # the members and the verdicts are the module's own (liveteam.ROLES / VERDICTS): every one has a look and a tone
    for role in T.ROLES:
        assert re.search(rf"\b{role}: \{{hue: \d+", src), role
    for v in T.VERDICTS:
        assert f'"{v}":' in src, v
    lb = _read(os.path.join(SCREENS, "livebots.js"))
    assert 'import {teamView} from "./livebots-team.js"' in lb and 'id: "team"' in lb
