"""실거래 › 신호 › ⏳ 진입 대기 (screens/livebots-signals.js waitView on /api/v4/livebots/now `pending`; the waits come from
paperbot/livecheck.py pending_entries, read-only).

On the hand-made world (tests/livebots_world.py: one WAITING row, BCH long, N03_ADX_GC 15m, signalled 10 minutes before
NOW; the rule bot's 1m bars by W.rule_bars, as tests/test_livecheck_wait.py makes them) the section shows, in node (the
tiny DOM, tests/anasyn_dom.mjs):
- a wait: the level line, the price now, how far to go with its bar, a countdown to the deadline (that reaches
  "시간 지남 · 진입 없음"), the signal time
- touched (already beyond after the signal): 돌파함 · 진입 확인 중
- no rule-bot bars: 기준가 못 읽음 (규칙봇 1분봉: <its path>), never a made-up level
- nothing waiting: 지금 기다리는 진입 없음 and each timeframe's next bar close with its settings
- a reason a wait cannot become an entry now (a position open): the banner
- the source not there / not read, and /now failing while the rest of the 신호 tab still works
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
JS = os.path.join(SCREENS, "livebots-signals.js")
CSS = os.path.join(SCREENS, "livebots-signals-wait.css")
NOW, MIN = W.NOW, W.MIN
T0W = NOW - 10 * MIN


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    f = tmp_path / "macro.csv"
    f.write_text("ts_utc,kind,source_url\n", encoding="utf-8")            # no macro release: no pause
    monkeypatch.setattr(events, "PATH", f)
    events.reset()
    monkeypatch.setenv("PAPERBOT_LIVE_COMBO_CONFIG", "/nonexistent/combo.json")
    L._cache.clear()
    yield
    events.reset()
    L._cache.clear()


def _now(tmp_path, monkeypatch, position=False, high=None, bars=True, at=NOW):
    """/api/v4/livebots/now on the world: no position unless asked, the rule bot's bars (level 101.0, last 100.0) unless not."""
    d = tmp_path / "w"
    d.mkdir(parents=True)
    p = W.build_world(str(d))
    if not position:
        W.paper_db(p["paper"] + ".2", with_position=False)
        os.replace(p["paper"] + ".2", p["paper"])
    rule = str(d / "paper3.db")
    if bars:
        hi = high or (lambda ts: 101.0 if T0W - 15 * MIN <= ts < T0W else 100.5)
        W.rule_bars(rule, "BCHUSDT", T0W - 20 * MIN, NOW, high=hi)
    monkeypatch.setenv("PAPERBOT_LIVE_RULE_DB", rule)
    return json_finite(L.whynow(p, at))


def _node(body: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\nconst S = await import('file://{JS}');\n"
              f"const d = {json.dumps(data)};\n{body}")
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# the section alone, rendered after its first answer; later: the 1 s tick with the clock moved on, the 15 s poll again
VIEW = """const every = [];
const ctx = {api: (p) => (d.__fail ? Promise.reject(Object.assign(new Error("x"), {kind: "network", status: 0})) : Promise.resolve(d)),
  every(ms, fn) { every.push({ms, fn}); }, watch() {}, alive: () => true, href: (n) => '#/' + n, track() {}};
const v = S.waitView(ctx);
await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
const first = D.walk(v.el);
const find = (n, c) => { if (!n || !n.childNodes) return null; if (String(n.className || "").split(" ").includes(c)) return n;
  for (const k of n.childNodes) { const f = find(k, c); if (f) return f; } return null; };
const card0 = find(v.el, "lbw-wait");
const poll = every.find((x) => x.ms === 15000), tick = every.find((x) => x.ms === 1000);
if (d.pending && d.pending.waits) d.pending.waits.forEach((w) => { w.left_ms -= 7000; });    // the same waits, 7 s later
d.now_ms += 7000;
poll.fn(); await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
const same = find(v.el, "lbw-wait") === card0;
const real = Date.now; Date.now = () => real() + 6 * 60000; tick.fn(); const later = D.walk(v.el); Date.now = real;
console.log(JSON.stringify({text: first.text.replace(/\\s+/g, " "), classes: first.classes, same, ms: every.map((x) => x.ms).sort((a, b) => a - b),
  later: later.text.replace(/\\s+/g, " "), laterCls: later.classes}));"""


def _bad(text):
    return [w for w in ("null", "undefined", "NaN", "Infinity", "[object") if w in text]


def test_node_check():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    r = subprocess.run([node, "--check", JS], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_pure_functions(tmp_path, monkeypatch):
    d = _now(tmp_path, monkeypatch)
    w = d["pending"]["waits"][0]
    assert (w["level"], w["last"], w["left_ms"], w["touched"]) == (101.0, 100.0, 5 * MIN, False)
    out = _node("""const w = d.pending.waits[0], rp = d.pending.rule_path;
    console.log(JSON.stringify({near: [S.closeness(0.01), S.closeness(0), S.closeness(-0.002), S.closeness(0.05), S.closeness(null)],
      cd: [S.countdownKo(299000), S.countdownKo(3725000), S.countdownKo(0), S.countdownKo(-5), S.countdownKo(null), S.countdownKo(61000)],
      w: S.waitWords(w, rp), short: S.waitWords({...w, side: -1, level: 99.5, to_go: 0.005}, rp), none: S.waitWords({...w, level: null, to_go: null}, rp),
      touched: S.waitWords({...w, touched: true}, rp), beyond: S.waitWords({...w, to_go: -0.001}, rp), nolast: S.waitWords({...w, last: null, to_go: null}, rp),
      closes: d.pending.closes.map(S.closeWords), frac: [S.timeLeftFrac(w, 5 * 60000), S.timeLeftFrac(w, 0), S.timeLeftFrac(w, null)],
      key: S.waitKey(d) === S.waitKey({...d, now_ms: 1, pending: {...d.pending, waits: d.pending.waits.map((x) => ({...x, left_ms: 1}))}}),
      key2: S.waitKey(d) === S.waitKey({...d, pending_blocked_ko: "주말"}), key0: S.waitKey(null)}));""", d)
    n = out["near"]
    assert n[0] == pytest.approx(2 / 3) and n[1:] == [1, 1, 0, None]
    assert out["cd"] == ["4분 59초 남음", "1시간 02분 남음", "시간 지남 · 진입 없음", "시간 지남 · 진입 없음", "—", "1분 01초 남음"]
    x = out["w"]
    assert (x["coin"], x["long"], x["tf"], x["line"], x["now"], x["left"]) == ("BCH", True, "15분", "101.00 위로 올라가면 진입", "100.00", "1.00% 남음")
    assert x["near"] == pytest.approx(2 / 3) and x["touched"] is False and x["noLevel"] is False
    assert out["short"]["line"] == "99.50 아래로 내려가면 진입" and out["short"]["left"] == "0.50% 남음" and out["short"]["long"] is False
    assert out["none"]["line"] == f"기준가 못 읽음 (규칙봇 1분봉: {d['pending']['rule_path']})" and out["none"]["noLevel"] and out["none"]["near"] is None
    assert out["touched"]["left"] == "한 번 넘었어요" and out["touched"]["near"] == 1 and out["touched"]["touched"] is True
    assert out["beyond"]["left"] == "기준가를 넘었어요" and out["nolast"]["left"] == "지금 가격 못 읽음" and out["nolast"]["now"] == "—"
    # NOW is 19:00 KST: the next 15m / 30m / 1h closes; the world's settings: one break setting on 15m, one at once on 30m and 1h
    assert out["closes"] == ["15분봉 마감 19:15 KST · 바로 진입 0개 · 돌파 대기 1개 설정", "30분봉 마감 19:30 KST · 바로 진입 1개 · 돌파 대기 0개 설정",
                             "1시간봉 마감 20:00 KST · 바로 진입 1개 · 돌파 대기 0개 설정"]
    assert out["frac"][0] == pytest.approx(1 / 3) and out["frac"][1:] == [0, None]
    assert out["key"] is True and out["key2"] is False and out["key0"] == ""


def test_a_wait_with_its_level_left_and_countdown(tmp_path, monkeypatch):
    out = _node(VIEW, _now(tmp_path, monkeypatch))
    t = out["text"]
    assert not _bad(t), _bad(t)
    for words in ("⏳ 진입 대기", "BCH", "롱", "N03_ADX_GC · 15분", "101.00 위로 올라가면 진입", "지금 100.00", "1.00% 남음",
                  "신호 10/19 18:50 · 19:05까지", "15분봉 마감 19:15 KST · 바로 진입 0개 · 돌파 대기 1개 설정",
                  "진입 대기 = 신호는 나왔고 돌파를 기다리는 중. 진입 확정이 아니에요. 시간 안에 못 넘으면 진입 없음.",
                  "PAPERBOT_LIVE_WAIT_MSGS=0"):
        assert words in t, words
    assert re.search(r"[45]분 \d\d초 남음", t), t                                   # the countdown from left_ms (5 minutes)
    assert "돌파함" not in t and "지금은 넘어도 진입 안 해요" not in t
    assert sum(c.split()[0] == "lbw-wait" for c in out["classes"]) == 1 and any("long" in c.split() for c in out["classes"] if c.startswith("lbw-wait"))
    assert out["ms"] == [1000, 15000]                                               # a 1 s countdown, the 15 s poll
    assert out["same"] is True                                                      # the same waits again: the card is kept
    assert "시간 지남 · 진입 없음" in out["later"] and any("lbw-lapsed" in c for c in out["laterCls"])     # past the deadline


def test_touched_level_missing_empty_and_blocked(tmp_path, monkeypatch):
    t = _node(VIEW, _now(tmp_path / "a", monkeypatch, high=lambda ts: 101.0 if ts < T0W else 101.2))["text"]
    assert "돌파함 · 진입 확인 중" in t and "한 번 넘었어요" in t
    d = _now(tmp_path / "b", monkeypatch, bars=False)
    assert d["pending"]["rule_state"] == "missing" and d["pending"]["waits"][0]["level"] is None
    t = _node(VIEW, d)["text"]
    assert f"기준가 못 읽음 (규칙봇 1분봉: {d['pending']['rule_path']})" in t and "규칙봇 1분봉 파일을 아직 못 찾아" in t
    assert "위로 올라가면" not in t and "남음" in t and not _bad(t)                   # no level invented; the countdown stays
    d = _now(tmp_path / "c", monkeypatch, at=NOW + 20 * MIN)                        # the wait lapsed at 19:05
    assert d["pending"]["waits"] == []
    t = _node(VIEW, d)["text"]
    assert "지금 기다리는 진입 없음" in t and "15분봉 마감 19:30 KST · 바로 진입 0개 · 돌파 대기 1개 설정" in t and "1시간봉 마감 20:00 KST" in t
    d = _now(tmp_path / "e", monkeypatch, position=True)
    assert d["pending_blocked_ko"] == "이미 포지션이 있어 새 진입 안 함(한 번에 하나)"
    t = _node(VIEW, d)["text"]
    assert "지금은 넘어도 진입 안 해요: 이미 포지션이 있어 새 진입 안 함(한 번에 하나)" in t and "101.00 위로 올라가면 진입" in t


def test_source_states_and_the_tab_still_works(tmp_path, monkeypatch):
    d = _now(tmp_path, monkeypatch)
    gone = {**d, "pending": {"state": "missing", "reason_ko": "아직 기록이 없어요", "waits": [], "closes": []}}
    t = _node(VIEW, gone)["text"]
    assert "수집 전" in t and "페이퍼 DB (진입 대기)" in t and "지금 기다리는 진입 없음" not in t
    bad = {**d, "pending": {"state": "error", "reason_ko": "읽지 못했어요", "reason": "disk I/O error", "waits": [], "closes": []}}
    t = _node(VIEW, bad)["text"]
    assert "못 읽음" in t and "읽지 못했어요" in t
    t = _node(VIEW, {k: v for k, v in d.items() if k != "pending"})["text"]
    assert "서버가 진입 대기를 보내지 않았어요" in t
    # /now fails, /signals answers: the funnel and the list still draw, the wait card says it could not load
    sig = json_finite(L.read_signals(W.build_world(str(tmp_path / "s"))["paper"], L.ACCOUNT, NOW))
    out = _node("""const ctx = {api: (p) => (p.endsWith("/now") ? Promise.reject(Object.assign(new Error("x"), {kind: "network", status: 0})) : Promise.resolve(d)),
  every() {}, watch() {}, alive: () => true, href: (n) => '#/' + n, track() {}};
const v = S.signalsView(ctx);
await new Promise((r) => setTimeout(r, 0)); await new Promise((r) => setTimeout(r, 0));
const w = D.walk(v.el);
console.log(JSON.stringify({text: w.text.replace(/\\s+/g, " ")}));""", sig)
    t = out["text"]
    assert "⏳ 진입 대기" in t and "서버에 닿지 못했습니다" in t
    assert "신호가 어디까지 갔나" in t and "돌파 기다림" in t and "왜 안 들어갔지?" in t and "끈 구간" in t


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
            assert ".lbw-" in part, part
    assert '@import url("livebots-signals-wait.css")' in _read(os.path.join(SCREENS, "livebots.css"))
    js = _read(JS)
    assert '"/api/v4/livebots/now"' in js and '"/api/v4/livebots/signals"' in js
    code = re.sub(r"//[^\n]*", "", js)
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "setInterval("):
        assert bad not in code, bad
