"""실거래 › 순위 › 진입 가능성 (screens/livebots-likely.js on /api/v4/livebots/likely) and the 순위 tab's switch (livebots-rank.js:
진입 가능성 | 성적 순위, remembered per device).

On the real likely() answer of the hand-made world (tests/test_dash_livebots_likely.py's setup: the rule bot's bars with
the BCH wait on N03_ADX_GC, PAPERBOT_LIVE_RULE_DB; the world's paper position open = the blocked banner; S2_ST_ROC not in
the 5-year file), in node (the tiny DOM, tests/anasyn_dom.mjs):
- the ranked rows with the ⏳ chip and its countdown on N03_ADX_GC, the unknown strategy (5년 기준 없음, never 0)
- the window switch re-sorting by that window (waits always first, no share last), the remembered window
- the blocked banner, the next pause, the honest footer (note_ko, not a win rate, the samples)
- the likely file missing / broken (L.LIKELY_FILE)
- the 순위 switch: 진입 가능성 by default, 성적 순위 remembered, only the shown view polls
Then static checks of the css and the js.
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
from paperbot import events  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
SCREENS = os.path.join(V4, "screens")
JS = os.path.join(SCREENS, "livebots-likely.js")
RANK_JS = os.path.join(SCREENS, "livebots-rank.js")
CSS = os.path.join(SCREENS, "livebots-likely.css")
NOW, MIN = W.NOW, W.MIN
T0W = NOW - 10 * MIN


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
    f = tmp_path / "macro.csv"
    f.write_text("ts_utc,kind,source_url\n", encoding="utf-8")
    monkeypatch.setattr(events, "PATH", f)
    events.reset()
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    L._cache.clear()
    L._likely_ref.clear()
    yield
    events.reset()
    L._likely_ref.clear()
    L._cache.clear()


@pytest.fixture
def world(tmp_path, monkeypatch):
    d = tmp_path / "w"
    d.mkdir()
    p = W.build_world(str(d))
    rule = str(d / "paper3.db")
    W.rule_bars(rule, "BCHUSDT", T0W - 20 * MIN, NOW, high=lambda ts: 101.0 if T0W - 15 * MIN <= ts < T0W else 100.5)
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", rule)
    return p


@pytest.fixture
def likely(world):
    return json_finite(L.likely(world, NOW))


def _node(body: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\nconst X = await import('file://{JS}');\nconst R = await import('file://{RANK_JS}');\n"
              f"const d = {json.dumps(data)};\n{body}")
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _bad(text):
    return [w for w in ("null", "undefined", "NaN", "Infinity", "[object") if w in text]


def test_node_check():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    for f in (JS, RANK_JS):
        r = subprocess.run([node, "--check", f], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------- pure functions
def test_pure_functions(likely):
    d = likely
    assert d["state"] == "ok" and [r["strategy"] for r in d["rows"]] == ["N03_ADX_GC", "S2_ST_ROC"]
    n03 = d["rows"][0]
    out = _node("""const n03 = d.rows[0], w = n03.waits[0];
    const P = (s, w4, w24, nx, wait) => ({strategy: s, known: true, p: {w1: {recent: w4 / 4}, w4: {recent: w4}, w24: {recent: w24}, next: {recent: nx}}, waits: wait ? [wait] : []});
    const rows = [P("A", 5, 30, 1), P("B", 8, 20, 2), {strategy: "C", known: false, p: {w4: {recent: null}, w24: {recent: null}, next: {recent: null}}, waits: []},
      P("D", 1, 2, 0, {to_go: 0.02, touched: false}), P("E", 1, 2, 0, {to_go: 0.05, touched: true}), P("F", 1, 2, 0, {to_go: 0.001, touched: false})];
    const ids = (xs) => xs.map((r) => r.strategy + r.rank);
    const fri20 = 1792335600000 + 4 * 86400000 + 20 * 3600000;  // Friday 2026-10-23 20:00 KST (Monday 10/19 00:00 KST + 4 days 20 h)
    console.log(JSON.stringify({w4: ids(X.sortRows(rows, "w4")), w24: ids(X.sortRows(rows, "w24")), w1: ids(X.sortRows(rows, "w1")), bad: ids(X.sortRows(rows, "nope")),
      real: X.sortRows(d.rows, "w24").map((r) => r.strategy), max: [X.barMax(rows, "w4"), X.barMax(rows, "w24"), X.barMax([], "w4")],
      pk: [X.pk(7.4), X.pk(42.3), X.pk(0), X.pk(null), X.pk(0.4)], bot: X.botLine(d, "w4"), bot24: X.botLine(d, "w24"), none: X.botLine({cell: {group: "sat", hour: 3}, bot: {}}, "w4"),
      samples: X.samplesLine(d.cell), live: [X.liveLine(n03.sig), X.liveLine({week: 0}), X.liveLine(n03.sig, false)],
      clock: [X.clockKo(293000), X.clockKo(3725000), X.clockKo(0), X.clockKo(null)],
      wh: [X.waitHead(w), X.waitHead({...w, touched: true}), X.waitHead({...w, to_go: null}), X.waitHead({...w, to_go: -0.001}), X.waitHead(null)],
      cells: X.stripCells(n03.hours).map((c) => [c.now, c.weekend, c.hour]), fmax: Math.max(...X.stripCells(n03.hours).map((c) => c.f)),
      wk: X.stripCells(Array.from({length: 24}, (_, i) => ({t: fri20 + i * 3600000, p: 1}))).map((c) => c.weekend),
      same: X.sameKey(d) === X.sameKey({...d, now_ms: 1, rows: d.rows.map((r) => ({...r, waits: r.waits.map((x) => ({...x, left_ms: 7}))}))}),
      diff: X.sameKey(d) === X.sameKey({...d, blocked_ko: null}), modes: [R.modeOf(null), R.modeOf("rank"), R.modeOf("x")], win: [X.winOf("w24"), X.winOf("x")]}));""", d)
    assert out["w4"] == ["E1", "F2", "D3", "B4", "A5", "C6"]               # waits first (touched, then closest), then 4 hours, none last
    assert out["w24"] == ["E1", "F2", "D3", "A4", "B5", "C6"] and out["w1"][3:] == ["B4", "A5", "C6"] and out["bad"] == out["w4"]
    assert out["real"] == ["N03_ADX_GC", "S2_ST_ROC"]                       # the wait leads in every window
    assert out["max"] == [8, 30, None]
    assert out["pk"] == ["7.4%", "42%", "0%", "—", "0.4%"]
    b = d["bot"]
    assert out["bot"].startswith("지금 같은 시간(월~목 19시)에는 4시간 안에 진입 신호가 나온 적이 ") and f"(5년 {round(b['w4']['all'])}%)" in out["bot"]
    assert out["bot"].endswith(f" · 보통 {b['next_h_median']['recent']:.1f}시간 뒤 다음 신호")
    assert "24시간 안에 진입 신호가 나온 적이" in out["bot24"] and out["none"] == "지금 같은 시간(토 3시) 기록이 없어요"
    sm = d["cell"]["samples"]
    assert out["samples"] == f"월~목 19시 표본: 최근 {sm['recent']:,}시간 · 5년 {sm['all']:,}시간"
    assert out["live"] == ["이번 주 신호 9개 · 진입 3 · 마지막 10/19 18:50 (돌파 기다림)", "이번 주 신호 없음", "신호 기록 못 읽음"]
    assert out["clock"] == ["4분 53초", "1시간 02분", "시간 지남", "—"]
    assert out["wh"] == ["대기 중 · BCH 롱 · 1.00% 남음", "돌파함 · 진입 확인 중 · BCH 롱", "대기 중 · BCH 롱 · 기준가 못 읽음",
                         "대기 중 · BCH 롱 · 기준가 넘음", None]
    assert len(out["cells"]) == 24 and out["cells"][0] == [True, False, 19] and not any(c[0] for c in out["cells"][1:])
    assert all(c[1] is False for c in out["cells"]) and out["fmax"] == 1                 # Monday 19:00 + 24 h: no weekend hour
    assert out["wk"][:4] == [False] * 4 and out["wk"][4:] == [True] * 20                 # Friday 20:00 ..: Saturday from the 5th hour
    assert out["same"] is True and out["diff"] is False
    assert out["modes"] == ["likely", "rank", "likely"] and out["win"] == ["w24", "w4"]
    assert n03["waits"][0]["left_ms"] == 5 * MIN


# ---------------------------------------------------------------- the view
VIEW = """const every = [];
const ctx = {api: (p) => (d.__fail ? Promise.reject(Object.assign(new Error("x"), {kind: "network", status: 0})) : Promise.resolve(d)),
  every(ms, fn) { every.push({ms, fn}); }, watch() {}, alive: () => true, href: (n, a) => '#/' + n + (a ? '/' + a : ''), track() {}};
if (d.__win) localStorage.setItem("pb4-lb-likely-win", JSON.stringify(d.__win));
const v = X.likelyView(ctx);
await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
const w = D.walk(v.el);
const real = Date.now; Date.now = () => real() + 6 * 60000; const tick = every.find((x) => x.ms === 1000); if (tick) tick.fn();
const later = D.walk(v.el); Date.now = real;
console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " "), classes: w.classes, ms: every.map((x) => x.ms).sort((a, b) => a - b),
  later: later.text.replace(/\\s+/g, " "), laterCls: later.classes, hidden: v.el.childNodes.map((c) => !!c.hidden)}));"""


def test_view_ranked_rows_wait_chip_unknown_banner_and_footer(likely):
    out = _node(VIEW, likely)
    t, cls = out["text"], out["classes"]
    assert not _bad(t), _bad(t)
    for words in ("다음 진입은 어느 매매법일까?", "1시간", "4시간", "24시간", "봇 전체 · 4시간 안에 신호", "지금 같은 시간(월~목 19시)에는 4시간 안에",
                  "지금", "N03_ADX_GC", "대기 중 · BCH 롱 · 1.00% 남음", "4시간 안에 신호", "다음 진입일 확률", "이번 주 신호 9개 · 진입 3",
                  "S2_ST_ROC", "5년 기준 없음", "이 매매법은 진입 가능성 기준표에 없어요",
                  "지금은 진입 안 해요: 이미 포지션이 있어 새 진입 안 함(한 번에 하나)", "풀리면 이 순서예요", "다음 쉬는 시간: 주말",
                  "이건 신호가 얼마나 자주 나오는지예요. 이길 확률이 아니에요", "(이길 확률은 성적 순위)", "예측이 아니라 과거 빈도",
                  "월~목 19시 표본: 최근", "주말 칸이 0인 건 봇이 주말에 진입하지 않아서예요"):
        assert words in t, words
    assert re.search(r"[45]분 \d\d초", t), t                                         # the countdown from left_ms
    pods = [c for c in cls if c.split()[0] == "lbl-pod"]
    assert pods == ["lbl-pod r1 waiting", "lbl-pod r2"]                              # the wait leads the podium
    assert "5년 0" not in t and "0.0%" not in t                                      # the unknown strategy shows no made-up share
    assert out["ms"] == [1000, 30000]
    assert "시간 지남" in out["later"] and any("lapsed" in c.split() for c in out["laterCls"])


def test_view_remembered_window_re_sorts_and_relabels(likely):
    out = _node(VIEW, {**likely, "__win": "w24"})
    t = out["text"]
    assert "봇 전체 · 24시간 안에 신호" in t and "24시간 안에 진입 신호가 나온 적이" in t and not re.search(r"(?<!2)4시간 안에 신호", t)
    rows = likely["rows"]
    assert f"{round(rows[0]['p']['w24']['recent'])}%" in t                           # the big number follows the window


def test_view_file_missing_broken_and_failed_load(world, tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LIKELY_FILE", str(tmp_path / "nope.json"))
    t = _node(VIEW, json_finite(L.likely(world, NOW)))["text"]
    assert "수집 전" in t and "진입 가능성 기준표(deploy/combo.live-ac.likely.json)가 없어요" in t and "이길 확률이 아니에요" in t
    assert "대기 중 · BCH" not in t and not _bad(t)
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    monkeypatch.setattr(L, "LIKELY_FILE", str(bad))
    L._likely_ref.clear()
    t = _node(VIEW, json_finite(L.likely(world, NOW)))["text"]
    assert "못 읽음" in t
    out = _node(VIEW, {"__fail": True})
    assert "서버에 닿지 못했습니다" in out["text"] and out["hidden"] == [False, True]


def test_rank_switch_default_remembered_and_only_the_shown_view_polls(world, likely):
    rank = json_finite(L.rank(world, NOW))
    out = _node("""const calls = [], polls = [];
const ctx = {api: (p) => { calls.push(p); return Promise.resolve(p.endsWith("/likely") ? d.likely : d.rank); },
  every(ms, fn) { polls.push(fn); }, watch() {}, alive: () => true, href: (n, a) => '#/' + n, track() {}};
const tick = async () => { await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0)); };
const v = R.rankView(ctx); await tick();
const first = D.walk(v.el).text.replace(/\\s+/g, " "), firstCalls = [...calls];
calls.length = 0; polls.forEach((f) => f()); await tick();
const likelyOnly = [...calls];
v.show("rank"); await tick();
const second = D.walk(v.el).text.replace(/\\s+/g, " "), stored = localStorage.getItem("pb4-lb-rank-mode");
calls.length = 0; polls.forEach((f) => f()); await tick();
const rankOnly = [...calls];
const v2 = R.rankView(ctx); await tick();
const third = D.walk(v2.el).text.replace(/\\s+/g, " ");
console.log(JSON.stringify({first, firstCalls, likelyOnly, second, stored, rankOnly, third}));""", {"likely": likely, "rank": rank})
    assert "진입 가능성" in out["first"] and "성적 순위" in out["first"] and "다음 진입은 어느 매매법일까?" in out["first"]
    assert "신호가 얼마나 자주 나오는지 (이길 확률 아님)" in out["first"]
    assert out["firstCalls"] == ["/api/v4/livebots/likely"]                            # the default view only
    assert out["likelyOnly"] == ["/api/v4/livebots/likely"]                            # its poll (the 1 s tick asks nothing)
    assert "매매법 순위" in out["second"] and "선수단" in out["second"] and out["stored"] == '"rank"'
    assert set(out["rankOnly"]) == {"/api/v4/livebots/rank"}                           # the hidden 진입 가능성 view does not poll
    assert "선수단" in out["third"] and "다음 진입은 어느 매매법일까?" not in out["third"]       # remembered on this device


# ---------------------------------------------------------------- static checks
def test_css_and_js_static():
    src = re.sub(r"/\*.*?\*/", "", _read(CSS), flags=re.S)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src) and not re.search(r"\b(rgba?|hsla?)\(\s*\d", src), "colour literal: use a token"
    for v in re.findall(r"font-size\s*:\s*([^;}]+)", src):
        assert "var(--t-" in v, v
    for v in re.findall(r"(?<![-\w])font\s*:\s*([^;}]+)", src):
        assert "var(--t-" in v, v
    assert "infinite" not in src and "@media (prefers-reduced-motion: reduce)" in src
    body = re.sub(r"@media[^{]*\{", "", src)
    for sel in re.findall(r"([^{}@;]+)\{", body):
        for part in sel.strip().split(","):
            assert ".lbl" in part, part
    assert '@import url("livebots-likely.css")' in _read(os.path.join(SCREENS, "livebots.css"))
    js = _read(JS)
    assert '"/api/v4/livebots/likely"' in js and "export function likelyView" in js
    rk = _read(RANK_JS)
    assert 'import {likelyView} from "./livebots-likely.js"' in rk and 'RANK_MODES = [{id: "likely", label: "진입 가능성"}, {id: "rank", label: "성적 순위"}]' in rk
    for f, code in ((JS, js), (RANK_JS, rk)):
        code = re.sub(r"//[^\n]*", "", code)
        for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "setInterval("):
            assert bad not in code, (f, bad)
