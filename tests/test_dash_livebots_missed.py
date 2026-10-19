"""실거래 › 못 탄 신호 (GET /api/v4/livebots/missed, dash/more/livemissed.py; screens/livebots-missed.js, livebots-missed.css).

On the world where the combined paper bot really ran (tests/livesim_world.py) and the 1-minute watcher's pass filled
livecheck.db (paperbot/livemissed.py):
- the answer: the two blocks (실제로 탄 거래 from the paper database over the same span, 못 탄 신호(가상) from the watcher's
  rows), the rows newest first with why, result, hold and the trade taken (its result fresh from the paper database), the
  spans 최근 7일 / 기록 전체, the watcher's last pass (stale after 10 minutes);
- honest states: no file / no table = missing (수집 전 "1분 감시가 아직 기록 전"), unreadable = error (못 읽음), the paper
  database unreadable blanks the left block only; the route is behind the login, a bad span is the default;
- the view in node (the tiny DOM, tests/anasyn_dom.mjs): the header and both blocks, the rows (✅ / ❌ / 진행 중 / 1분봉 없음,
  "그때 탄 거래: BTC 롱 +19.8%"), the foot always on (also before the first answer and in every state), 수집 전 / 못 읽음, a failed
  refresh keeps the last answer dimmed with its age, the same answer draws nothing again;
then static checks of the css and the js.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import types

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import livesim_world as W  # noqa: E402
from paperbot import livecheck as LC  # noqa: E402
from paperbot import livemissed as LM  # noqa: E402
from paperbot import livesim as LS  # noqa: E402
from paperbot.dash.app import create_app, hash_password, json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livemissed as DM  # noqa: E402
from test_dash import SECRET, _store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENS = os.path.join(ROOT, "paperbot", "dash", "static", "v4", "screens")
JS = os.path.join(SCREENS, "livebots-missed.js")
CSS = os.path.join(SCREENS, "livebots-missed.css")
MIN = W.MIN
NOW = W.END + 5 * MIN
PW = "correct horse battery"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _clean():
    L._cache.clear()
    yield
    L._cache.clear()


def _pass(w, db, now=NOW):
    conn = LC.open_out(db)
    try:
        LM.missed_pass(LC.Sources(db=db, paper_db=w.paper_db, rule_db=w.rule_db, combo_config="-"), conn, now, log=lambda s: None)
    finally:
        conn.close()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    d = tmp_path_factory.mktemp("lbm")
    w = W.build(str(d / "w"))
    db = str(d / "livecheck.db")
    _pass(w, db)
    yield {"w": w, "p": {"paper": w.paper_db}, "more": {"check_db": db}, "dir": d}
    w.close()


@pytest.fixture(scope="module")
def answer(world):
    return json_finite(DM.build(world["p"], world["more"], NOW + MIN))


# ---------------------------------------------------------------- the answer
def test_the_answer_two_blocks_and_rows(answer):
    d = answer
    assert d["state"] == "ok" and d["span"] == "7d" and d["since_ms"] == LM.window_start(NOW + MIN) and d["paper"] == {"state": "ok"}
    m, t = d["summary"]["missed"], d["summary"]["taken"]
    assert (m["n"], m["closed"], m["wins"], m["losses"], m["open"], m["no_data"], m["moments"], m["small"]) == (3, 2, 1, 1, 1, 0, 3, True)
    assert (t["n"], t["closed"], t["wins"], t["losses"], t["open"], t["small"]) == (3, 3, 2, 1, 0, True)
    assert m["roe_sum"] == pytest.approx(sum(r["roe"] for r in d["rows"] if r["state"] == "closed"))
    assert [r["symbol"] for r in d["rows"]] == ["DOGEUSDT", "SOLUSDT", "ETHUSDT"]                  # newest first
    sol = d["rows"][1]
    assert sol["why"] == "이미 BTC 롱 보유 중" and sol["reason_ko"] == "계단 익절" and sol["win"] is True
    assert sol["taken"]["symbol"] == "BTCUSDT" and sol["taken"]["state"] == "closed" and sol["taken"]["reason_ko"] == "계단 익절"
    assert d["pass"]["stale"] is False and d["pass"]["funding"] == "excluded" and d["funding_included"] is False
    assert d["note_ko"] == LM.NOTE_KO and d["funding_ko"] == LS.FUNDING_NOTE_KO and d["n_rows"] == 3
    assert all("signal" not in r and "detail" not in r for r in d["rows"])


def test_spans_and_a_stale_pass(world):
    late = DM.build(world["p"], world["more"], NOW + 20 * MIN)
    assert late["pass"]["stale"] is True and late["pass"]["last_ms"] == NOW
    later = DM.build(world["p"], world["more"], NOW + 9 * W.DAY)                   # out of the 7 days
    assert later["state"] == "ok" and later["rows"] == [] and later["summary"]["missed"]["n"] == 0
    every = DM.build(world["p"], world["more"], NOW + 9 * W.DAY, span="all")
    assert len(every["rows"]) == 3 and every["since_ms"] == LM.window_start(NOW)
    assert DM.build(world["p"], world["more"], NOW, span="zzz")["span"] == "7d"


def test_missing_no_table_and_unreadable(world, tmp_path):
    d = DM.build(world["p"], {"check_db": str(tmp_path / "nope.db")}, NOW)
    assert d["state"] == "missing" and d["reason_ko"] == DM.MISSING_KO and d["rows"] == [] and d["summary"] is None
    db = str(tmp_path / "livecheck.db")
    LC.open_out(db).close()                                           # the watcher's file, before the first missed pass
    d = DM.build(world["p"], {"check_db": db}, NOW)
    assert d["state"] == "missing" and "1분 감시가 아직 기록 전" in d["reason_ko"]
    folder = tmp_path / "adir.db"
    folder.mkdir()
    d = DM.build(world["p"], {"check_db": str(folder)}, NOW)
    assert d["state"] == "error" and d["reason_ko"] and d["rows"] == []
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not sqlite" * 100)
    d = DM.build(world["p"], {"check_db": str(junk)}, NOW)
    assert d["state"] == "error" and "망가졌" in d["reason_ko"]
    d = DM.build({"paper": str(tmp_path / "no-paper.db")}, world["more"], NOW + MIN)
    assert d["state"] == "ok" and d["summary"]["taken"] is None and d["paper"]["state"] == "missing"
    assert d["summary"]["missed"]["n"] == 3 and len(d["rows"]) == 3                 # the right block and the rows stay


def test_the_trade_taken_is_fresh_from_the_paper_db(tmp_path):
    w = W.build(str(tmp_path / "w"), until=W.B1 + 20 * MIN)             # SOL skipped while BTC is open
    try:
        db = str(tmp_path / "livecheck.db")
        _pass(w, db, W.B1 + 21 * MIN)
        stored = LM.read_rows(LC.open_ro(db), 0)
        assert next(r for r in stored if r["symbol"] == "SOLUSDT")["taken"]["state"] == "open"
        d = DM.build({"paper": w.paper_db}, {"check_db": db}, W.B1 + 21 * MIN)
        tk = next(r for r in d["rows"] if r["symbol"] == "SOLUSDT")["taken"]
        assert tk["state"] == "open" and tk["roe"] is not None
        w.run_to(W.B1 + 40 * MIN)                                       # BTC closed; the watcher has not passed again
        L._cache.clear()
        d = DM.build({"paper": w.paper_db}, {"check_db": db}, W.B1 + 41 * MIN)
        tk = next(r for r in d["rows"] if r["symbol"] == "SOLUSDT")["taken"]
        assert tk["state"] == "closed" and tk["reason"] == "LOCK" and tk["id"] is not None and tk["roe"] > 0.1
        assert d["summary"]["taken"]["closed"] == 1
    finally:
        w.close()


def test_the_route_is_behind_the_login(world, tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERBOT_LIVE_PAPER_DB", world["w"].paper_db)
    monkeypatch.setenv("PAPERBOT_LIVE_CHECK_DB", world["more"]["check_db"])
    monkeypatch.setattr(DM, "time", types.SimpleNamespace(time=lambda: (NOW + MIN) / 1000))
    base = tmp_path / "data"
    base.mkdir()
    dbp = str(base / "paper3.db")
    _store(dbp).close()
    app = create_app(dbp, hash_password(PW), SECRET, candles=lambda s, i, n: [])
    reg = DM.register(app, types.SimpleNamespace())
    assert reg["routes"] == ["/api/v4/livebots/missed"]
    c = TestClient(app)
    assert c.get("/api/v4/livebots/missed", follow_redirects=False).status_code in (401, 302, 307)
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    d = c.get("/api/v4/livebots/missed").json()
    assert d["state"] == "ok" and len(d["rows"]) == 3 and d["summary"]["missed"]["n"] == 3
    assert c.get("/api/v4/livebots/missed?span=all").json()["span"] == "all"
    assert c.get("/api/v4/livebots/missed?span=bad").json()["span"] == "7d"


# ---------------------------------------------------------------- the view in node
def _node(body: str, data) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    dom = "file://" + os.path.join(ROOT, "tests", "anasyn_dom.mjs")
    script = (f"const D = await import('{dom}');\nconst X = await import('file://{JS}');\nconst d = {json.dumps(data)};\n"
              "const tick = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setTimeout(r, 0)); };\n"
              "const shown = (n) => (n == null || n.hidden ? '' : n instanceof Text ? n.t : (n.childNodes || []).map(shown).join(' '));\n"
              "const find = (n, cls, out = []) => { if (String(n.className || '').split(/\\s+/).includes(cls)) out.push(n); "
              "(n.childNodes || []).forEach((c) => find(c, cls, out)); return out; };\n" + body)
    r = subprocess.run([node, "--input-type=module"], input=script, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _bad(text):
    return [w for w in ("null", "undefined", "NaN", "Infinity", "[object") if w in text]


def test_node_check():
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    r = subprocess.run([node, "--check", JS], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_pure_functions(answer):
    out = _node("""const R = (o) => X.resultText(o);
console.log(JSON.stringify({
  res: [R({state: "closed", win: true, roe: 0.112, reason: "LOCK", reason_ko: "계단 익절"}), R({state: "closed", win: false, roe: -0.38, reason: "SL"}),
        R({state: "open", roe: 0.04}), R({state: "no_data"}), R({state: "refused", note: "손절 자리가 강제청산 안쪽에 안 맞아요"}), R({state: "error", error: "x"})],
  tones: ["closed", "open", "no_data", "error"].map((s) => X.resultOf({state: s, win: true, roe: 0.1}).tone),
  why: [X.resultOf({state: "refused", note: "n"}).why, X.resultOf({state: "error", error: "e"}).why],
  tk: [X.takenText(null), X.takenText({symbol: "BTCUSDT", side: 1, state: "closed", roe: 0.12}), X.takenText({symbol: "ETHUSDT", side: -1, state: "open", roe: -0.031}),
       X.takenText({symbol: "SOLUSDT", side: 1, state: "open", roe: null})],
  hold: [X.holdText({hold_ms: 3840000}), X.holdText({hold_ms: null}), X.holdText(null)],
  bw: X.blockWords(d.summary.missed, "개"), bt: X.blockWords(d.summary.taken, "번"),
  other: [X.otherLine(d.summary.missed), X.otherLine({open: 2, no_data: 1, refused: 1, error: 1}), X.otherLine({})],
  same: X.sameKey(d) === X.sameKey({...d, now_ms: 1, pass: {...d.pass, last_ms: 5, stale: true}, rows: d.rows.map((r) => ({...r, updated_ts: 9, sims: 7}))}),
  diff: X.sameKey(d) === X.sameKey({...d, rows: d.rows.map((r, i) => (i ? r : {...r, roe: 0.5}))}),
  pass: [X.passLine(null), X.passLine({last_ms: null}), X.passLine({last_ms: 1792381200000, stale: false}, 1792381260000),
         X.passLine({last_ms: 1792381200000, stale: true}, 1792382400000)],
  spans: [X.spanOf("all"), X.spanOf("x"), X.spanOf(null)], note: X.NOTE, funding: X.FUNDING}));""", answer)
    assert out["res"] == ["✅ +11.2% 계단 익절", "❌ −38.0% 손절", "진행 중 +4.0%", "1분봉 없음", "진입 안 됨", "못 읽음"]
    assert out["tones"] == ["up", "open", "thin", "bad"] and out["why"] == ["n", "e"]
    assert out["tk"] == ["그때 탄 거래: 기록 못 찾음", "그때 탄 거래: BTC 롱 +12.0%", "그때 탄 거래: ETH 숏 진행 중 −3.1%", "그때 탄 거래: SOL 롱 진행 중"]
    assert out["hold"] == ["1시간 4분", "—", "—"]
    assert out["bw"]["count"] == "3개" and out["bw"]["wins"] == "1" and out["bw"]["losses"] == "1" and out["bw"]["rate"] == "50%"
    assert out["bt"]["count"] == "3번" and out["bt"]["rate"] == "67%" and out["bt"]["sum"].startswith("+14.")
    assert out["other"] == ["진행 중 1", "진행 중 2 · 1분봉 없음 1 · 진입 안 됨 1 · 못 읽음 1", ""]
    assert out["same"] is True and out["diff"] is False
    assert out["pass"][0] == "" and out["pass"][1] == "1분 감시가 아직 계산 전이에요"
    assert out["pass"][2].startswith("마지막 계산 ") and "1분 전" in out["pass"][2] and "매분" in out["pass"][2]
    assert "10분 넘게 계산하지 않았어요" in out["pass"][3]
    assert out["spans"] == ["all", "7d", "7d"]
    assert out["note"] == LM.NOTE_KO and out["funding"] == LS.FUNDING_NOTE_KO


VIEW = """const every = [];
let fail = !!d.__fail;
const calls = [];
const ctx = {api: (p) => { calls.push(p); return fail ? Promise.reject(Object.assign(new Error("x"), {kind: "network", status: 0})) : Promise.resolve(d); },
  every(ms, fn) { every.push({ms, fn}); }, watch() {}, alive: () => true, href: (n, a) => '#/' + n, track() {}};
if (d.__span) localStorage.setItem("pb4-lb-missed-span", JSON.stringify(d.__span));
const v = X.missedView(ctx);
const before = D.walk(v.el).text.replace(/\\s+/g, " ");
await tick();
const w = D.walk(v.el);
const rows = find(v.el, "lbm-row");
if (rows[0]) rows[0].__mark = 1;
// the same answer again (the clock and the pass time moved): nothing is drawn again
d.now_ms = (d.now_ms || 0) + 60000; if (d.pass) d.pass = {...d.pass, last_ms: (d.pass.last_ms || 0) + 60000};
for (const e of every) e.fn(); await tick();
const kept = (find(v.el, "lbm-row")[0] || {}).__mark === 1;
// a refresh that fails: the last answer stays, dimmed, with its age
fail = true; for (const e of every) e.fn(); await tick();
const after = D.walk(v.el);
const shownText = shown(v.el).replace(/\\s+/g, " ");
console.log(JSON.stringify({before, text: w.text.replace(/\\s+/g, " "), shown: shownText, classes: w.classes, kept, calls,
  ms: every.map((x) => x.ms), stale: after.text.replace(/\\s+/g, " "), staleCls: after.classes, hidden: v.el.childNodes.map((c) => !!c.hidden)}));"""


def test_view_blocks_rows_and_the_foot(answer):
    out = _node(VIEW, answer)
    t, cls = out["text"], out["classes"]
    assert not _bad(t), _bad(t)
    for words in ("못 탄 신호는 어땠을까?", "최근 7일", "기록 전체", "한 번에 하나 규칙 때문에 못 탄 신호를",
                  "실제로 탄 거래", "3번", "못 탄 신호(가상)", "3개", "이김", "짐", "승률", "순ROE 합", "한 번 평균", "표본 적음",
                  "진행 중 1 · 서로 다른 순간 3번", "닫힌 것 20번 미만은 대부분 운이에요", "마지막 계산",
                  "신호 하나씩", "DOGE", "SOL", "ETH", "이미 BTC 롱 보유 중", "같은 분에 BTC 롱 신호가 먼저 들어감",
                  "✅", "계단 익절", "❌ −22.2% 손절", "진행 중 −", "그때 탄 거래: BTC 롱 +19.8%", "그때 탄 거래: BCH 롱 +16.6%",
                  LM.NOTE_KO, LS.FUNDING_NOTE_KO):
        assert words in t, words
    assert "lbm-blk taken" in cls and "lbm-blk missed" in cls and "lbm-w" in cls and "lbm-l" in cls
    assert any(c.startswith("lbm-row closed up") for c in cls) and any(c.startswith("lbm-row closed down") for c in cls)
    assert any(c.startswith("lbm-row open open") for c in cls)
    assert LM.NOTE_KO in out["before"] and LS.FUNDING_NOTE_KO in out["before"]                 # the foot before any answer
    assert out["kept"] is True and out["ms"] == [30000]                                          # same answer: nothing redrawn
    assert out["calls"][0] == "/api/v4/livebots/missed?span=7d"
    assert "불러오지 못했습니다" in out["stale"] or "서버에 닿지 못했습니다" in out["stale"]
    assert "자료를 보여 드립니다" in out["stale"] and "이미 BTC 롱 보유 중" in out["stale"]       # the last answer stays
    assert any("is-stale" in c.split() for c in out["staleCls"]) and LM.NOTE_KO in out["stale"]


def test_view_remembers_the_span_and_says_missing_error_and_a_first_failure(world, tmp_path):
    out = _node(VIEW, {**json_finite(DM.build(world["p"], world["more"], NOW, span="all")), "__span": "all"})
    assert out["calls"][0] == "/api/v4/livebots/missed?span=all" and "이미 BTC 롱 보유 중" in out["text"]
    miss = json_finite(DM.build(world["p"], {"check_db": str(tmp_path / "nope.db")}, NOW))
    t = _node(VIEW, miss)["shown"]
    assert "수집 전" in t and "1분 감시가 아직 기록 전" in t and LM.NOTE_KO in t and "실제로 탄 거래" not in t and not _bad(t)
    assert "못 탄 신호가 없어요" not in t and "신호 하나씩" not in t                 # never an empty list that reads as "nothing missed"
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"x" * 4096)
    t = _node(VIEW, json_finite(DM.build(world["p"], {"check_db": str(junk)}, NOW)))["shown"]
    assert "못 읽음" in t and LM.NOTE_KO in t and not _bad(t) and "못 탄 신호가 없어요" not in t and "신호 하나씩" not in t
    out = _node(VIEW, {"__fail": True})
    assert "서버에 닿지 못했습니다" in out["text"] and out["hidden"] == [False, True, False] and LM.NOTE_KO in out["text"]
    nopaper = json_finite(DM.build({"paper": str(tmp_path / "no-paper.db")}, world["more"], NOW))
    t = _node(VIEW, nopaper)["text"]
    assert "실제로 탄 거래" in t and "수집 전" in t and "못 탄 신호(가상)" in t and "이미 BTC 롱 보유 중" in t


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
            assert ".lbm" in part, part
    assert "@media (max-width: 759px)" in src                          # the phone layout (390 px: no sideways scroll)
    js = _read(JS)
    assert '"/api/v4/livebots/missed"' in js and "export function missedView" in js
    imports = re.findall(r'^import .* from "([^"]+)";', js, flags=re.M)
    assert imports == ["../core/pb.js", "./livebots-kit.js"]
    code = re.sub(r"//[^\n]*", "", js)
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "setInterval(",
                "toFixed("):
        assert bad not in code, bad
