"""실거래 › 못 탄 신호 (GET /api/v4/livebots/missed, dash/more/livemissed.py; screens/livebots-missed.js, livebots-missed.css).

On the research world where the combined paper bot really ran (tests/livesim_world.py: every not-entered group written by
combo.py's own code) with two executors (bybit followed two trades and was blocked by its light once; MEXC went live late and
halted) and the 1-minute watcher's pass in livecheck.db (paperbot/livemissed.py):
- the answer: the cards (실제로 탄 거래 over the same span, then each group: n, closed, 이김 / 짐, win rate, net ROE sum and mean,
  the other states, the one-line read), the rows of the chosen group and result newest first, the chosen group's totals for
  both sides whatever the result filter (``list``), the chips' counts, the spans, the watcher's last pass;
- honest states: no file / no table = missing (수집 전 "1분 감시가 아직 기록 전"), unreadable = error (못 읽음), the paper
  database unreadable blanks the 실제로 탄 거래 card only; the route is behind the login, bad parameters are the defaults;
- the view in node (the tiny DOM, tests/anasyn_dom.mjs): the cards and their reads, the group chips with counts and the
  result filter (remembered), the totals line with both sides under a "이겼을 신호" filter, the rows (✅ / ❌ / 진행 중 / 1분봉
  없음, the group chip, "돌파를 안 기다리고 바로 탔다면", "그때 탄 거래: BTC 롱 +19.8%"), the foot always on (filter words, 13장,
  funding), 수집 전 / 못 읽음 without a list, a failed refresh keeps the last answer dimmed with its age, the same answer draws
  nothing again;
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
NOW = W.END_R + 5 * MIN
PW = "correct horse battery"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(autouse=True)
def _clean():
    L._cache.clear()
    yield
    L._cache.clear()


def _pass(src, now=NOW):
    conn = LC.open_out(src.db)
    try:
        LM.missed_pass(src, conn, now, log=lambda s: None)
    finally:
        conn.close()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    from pathlib import Path

    from paperbot import events
    d = tmp_path_factory.mktemp("lbm")
    csv = d / "macro.csv"
    csv.write_text(W.MACRO_CSV, encoding="utf-8")
    old = events.PATH
    events.PATH = Path(csv)
    events.reset()
    try:
        w = W.build(str(d / "w"), until=W.END_R, research=True)
    finally:
        events.PATH = old
        events.reset()
    trades = LM.read_paper(LC.open_ro(w.paper_db), 0)["trades"]
    btc, eth, bch1, _bch2 = trades
    key = f"{LM.ACCOUNT}|{eth['symbol']}|{eth['entry_time']}"
    bybit = W.exec_db(str(d / "bybit.db"), "bybit", followed=[("BTCUSDT", 1, btc["entry_time"], 1.2), ("BCHUSDT", 1, bch1["entry_time"], 0.8)],
                      events=[(eth["entry_time"] + 20_000, "light_red", "신호등 빨강", key)])
    mexc = W.exec_db(str(d / "mexc.db"), "mexc", followed=[], halt_at=W.T0 + 2 * W.H, live_since=W.T0 + 30 * MIN)
    infos = [LC.ExecInfo(name=n, config="-", unit="-", db=p, light_n=20, light_min=0.85, exchange=n) for n, p in (("bybit", bybit), ("mexc", mexc))]
    db = str(d / "livecheck.db")
    _pass(LC.Sources(db=db, paper_db=w.paper_db, rule_db=w.rule_db, combo_config="-", executors=infos))
    yield {"w": w, "p": {"paper": w.paper_db}, "more": {"check_db": db}, "dir": d}
    w.close()


@pytest.fixture(scope="module")
def answer(world):
    return json_finite(DM.build(world["p"], world["more"], NOW + MIN))


def _g(d, gid):
    return next(g for g in d["summary"]["groups"] if g["id"] == gid)


# ---------------------------------------------------------------- the answer
def test_the_answer_cards_rows_and_counts(answer):
    d = answer
    assert d["state"] == "ok" and (d["span"], d["group"], d["result"]) == ("7d", "all", "all") and d["paper"] == {"state": "ok"}
    t = d["summary"]["taken"]
    assert (t["n"], t["closed"], t["wins"], t["losses"], t["open"], t["small"]) == (4, 4, 3, 1, 0, True)
    assert [g["id"] for g in d["summary"]["groups"]] == ["one", "research", "nobreak", "pause", "late", "exec"]
    assert [(_g(d, g)["n"], _g(d, g)["wins"], _g(d, g)["losses"]) for g in LM.GROUPS] == \
        [(3, 1, 2), (3, 2, 1), (1, 1, 0), (1, 0, 1), (1, 1, 0), (5, 3, 2)]
    assert _g(d, "research")["read_ko"].startswith("연구 조건이 막은 신호: 가상 2승 1패 · 순ROE 합 +") and \
        _g(d, "research")["read_ko"].endswith("→ 이번엔 막은 게 이익을 놓쳤어요 · 표본 적음 · 대부분 운")
    assert _g(d, "pause")["read_ko"].endswith("→ 이번엔 쉰 게 손해를 줄였어요 · 표본 적음 · 대부분 운")
    assert _g(d, "nobreak")["subj"] == "돌파를 안 기다리고 바로 탔다면" and _g(d, "exec")["read_ko"].startswith("실행기가 안 따라간 페이퍼 거래: 페이퍼 결과 3승 2패")
    assert d["summary"]["all"]["n"] == 9                                           # the simulated groups (the executors' are paper results)
    assert d["counts"] == {"all": 14, "one": 3, "research": 3, "nobreak": 1, "pause": 1, "late": 1, "exec": 5}
    assert d["n_rows"] == 14 and [r["t"] for r in d["rows"]] == sorted((r["t"] for r in d["rows"]), reverse=True)
    sol = next(r for r in d["rows"] if r["grp"] == "one" and r["symbol"] == "SOLUSDT")
    assert sol["why"] == "이미 BTC 롱 보유 중" and sol["taken"]["reason_ko"] == "계단 익절" and sol["result"] == "win"
    nb = next(r for r in d["rows"] if r["grp"] == "nobreak")
    assert nb["how_ko"] == "돌파를 안 기다리고 바로 탔다면 (가상)" and nb["grp_ko"] == "돌파 없음"
    assert d["list"]["n"] == 14 and d["list"]["wins"] + d["list"]["losses"] == 14 and d["list"]["read_ko"] is None
    assert d["note_ko"] == LM.NOTE_KO and d["filter_note_ko"] == LM.FILTER_NOTE_KO and d["funding_ko"] == LS.FUNDING_NOTE_KO
    assert d["pass"]["stale"] is False and set(d["pass"]["executors"]) == {"bybit", "mexc"}
    assert all("signal" not in r and "detail" not in r for r in d["rows"])


def test_group_and_result_filters_keep_both_sides_totals(world):
    d = DM.build(world["p"], world["more"], NOW + MIN, group="research", result="win")
    assert (d["group"], d["result"]) == ("research", "win") and d["n_rows"] == 2 and all(r["win"] and r["grp"] == "research" for r in d["rows"])
    lst = d["list"]
    assert (lst["n"], lst["wins"], lst["losses"], lst["shown"], lst["group_ko"]) == (3, 2, 1, 2, "연구 조건 밖")    # both sides stay
    assert lst["read_ko"].startswith("연구 조건이 막은 신호: 가상 2승 1패")
    assert _g(d, "one")["n"] == 3 and d["counts"]["all"] == 14                  # the cards and the chips never filtered
    lose = DM.build(world["p"], world["more"], NOW + MIN, result="loss")
    assert lose["n_rows"] == 6 and all(r["state"] == "closed" and not r["win"] for r in lose["rows"]) and lose["list"]["wins"] == 8
    bad = DM.build(world["p"], world["more"], NOW + MIN, group="zzz", result="zzz")
    assert (bad["group"], bad["result"], bad["n_rows"]) == ("all", "all", 14)


def test_spans_and_a_stale_pass(world):
    late = DM.build(world["p"], world["more"], NOW + 20 * MIN)
    assert late["pass"]["stale"] is True and late["pass"]["last_ms"] == NOW
    later = DM.build(world["p"], world["more"], NOW + 9 * W.DAY)                   # out of the 7 days
    assert later["state"] == "ok" and later["rows"] == [] and later["counts"]["all"] == 0 and _g(later, "one")["n"] == 0
    every = DM.build(world["p"], world["more"], NOW + 9 * W.DAY, span="all")
    assert every["n_rows"] == 14 and every["since_ms"] == LM.window_start(NOW)
    assert DM.build(world["p"], world["more"], NOW, span="zzz")["span"] == "7d"


def test_missing_no_table_and_unreadable(world, tmp_path):
    d = DM.build(world["p"], {"check_db": str(tmp_path / "nope.db")}, NOW)
    assert d["state"] == "missing" and d["reason_ko"] == DM.MISSING_KO and d["rows"] == [] and d["summary"] is None and d["list"] is None
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
    assert _g(d, "research")["n"] == 3 and d["n_rows"] == 14                       # the groups and the rows stay


def test_the_trade_taken_is_fresh_from_the_paper_db(tmp_path, monkeypatch):
    monkeypatch.setattr(LC, "load_executors", lambda *a, **k: [])
    w = W.build(str(tmp_path / "w"), until=W.B1 + 20 * MIN)             # SOL skipped while BTC is open
    try:
        src = LC.Sources(db=str(tmp_path / "livecheck.db"), paper_db=w.paper_db, rule_db=w.rule_db, combo_config="-")
        _pass(src, W.B1 + 21 * MIN)
        d = DM.build({"paper": w.paper_db}, {"check_db": src.db}, W.B1 + 21 * MIN)
        tk = next(r for r in d["rows"] if r["symbol"] == "SOLUSDT")["taken"]
        assert tk["state"] == "open" and tk["roe"] is not None
        w.run_to(W.B1 + 40 * MIN)                                       # BTC closed; the watcher has not passed again
        L._cache.clear()
        d = DM.build({"paper": w.paper_db}, {"check_db": src.db}, W.B1 + 41 * MIN)
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
    if not any(getattr(r, "path", "") == "/api/v4/livebots/missed" for r in app.routes):
        DM.register(app, types.SimpleNamespace())
    c = TestClient(app)
    assert c.get("/api/v4/livebots/missed", follow_redirects=False).status_code in (401, 302, 307)
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    d = c.get("/api/v4/livebots/missed").json()
    assert d["state"] == "ok" and d["n_rows"] == 14 and _g(d, "exec")["n"] == 5
    d = c.get("/api/v4/livebots/missed?span=all&group=nobreak&result=win").json()
    assert (d["span"], d["group"], d["result"], d["n_rows"]) == ("all", "nobreak", "win", 1)
    assert c.get("/api/v4/livebots/missed?span=bad&group=bad&result=bad").json()["group"] == "all"


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
        R({state: "open", roe: 0.04}), R({state: "no_data"}), R({state: "refused", note: "x"}), R({state: "rebuild_failed", note: "y"}), R({state: "error", error: "x"})],
  tones: ["closed", "open", "no_data", "rebuild_failed", "error"].map((s) => X.resultOf({state: s, win: true, roe: 0.1}).tone),
  why: [X.resultOf({state: "refused", note: "n"}).why, X.resultOf({state: "rebuild_failed", note: "r"}).why, X.resultOf({state: "error", error: "e"}).why],
  tk: [X.takenText(null), X.takenText({symbol: "BTCUSDT", side: 1, state: "closed", roe: 0.12}), X.takenText({symbol: "ETHUSDT", side: -1, state: "open", roe: -0.031}),
       X.takenText({symbol: "SOLUSDT", side: 1, state: "open", roe: null})],
  hold: [X.holdText({hold_ms: 3840000}), X.holdText({hold_ms: null}), X.holdText(null)],
  bw: X.blockWords(d.summary.groups[1], "개"), bt: X.blockWords(d.summary.taken, "번"),
  other: [X.otherLine({open: 2, no_data: 1, refused: 1, rebuild_failed: 1, error: 1}), X.otherLine({})],
  list: [X.listLine({...d.list, group_ko: "연구 조건 밖", n: 3, wins: 2, losses: 1, open: 0, shown: 2}, "win"), X.listLine(d.list, "all"), X.listLine(null, "all")],
  chips: X.groupChips(d.counts).map((c) => c.id + ":" + c.label),
  same: X.sameKey(d) === X.sameKey({...d, now_ms: 1, pass: {...d.pass, last_ms: 5, stale: true}, rows: d.rows.map((r) => ({...r, updated_ts: 9, sims: 7}))}),
  diff: X.sameKey(d) === X.sameKey({...d, rows: d.rows.map((r, i) => (i ? r : {...r, roe: 0.5}))}),
  pass: [X.passLine(null), X.passLine({last_ms: null}), X.passLine({last_ms: 1792381200000, stale: false}, 1792381260000),
         X.passLine({last_ms: 1792381200000, stale: true}, 1792382400000)],
  spans: [X.spanOf("all"), X.spanOf("x")], groups: [X.groupOf("exec"), X.groupOf("all"), X.groupOf("x")], results: [X.resOf("loss"), X.resOf("x")],
  note: X.NOTE, filter: X.FILTER_NOTE, funding: X.FUNDING}));""", answer)
    assert out["res"] == ["✅ +11.2% 계단 익절", "❌ −38.0% 손절", "진행 중 +4.0%", "1분봉 없음", "진입 안 됨", "다시 못 만듦", "못 읽음"]
    assert out["tones"] == ["up", "open", "thin", "thin", "bad"] and out["why"] == ["n", "r", "e"]
    assert out["tk"] == ["그때 탄 거래: 기록 못 찾음", "그때 탄 거래: BTC 롱 +12.0%", "그때 탄 거래: ETH 숏 진행 중 −3.1%", "그때 탄 거래: SOL 롱 진행 중"]
    assert out["hold"] == ["1시간 4분", "—", "—"]
    assert out["bw"]["count"] == "3개" and (out["bw"]["wins"], out["bw"]["losses"]) == ("2", "1") and out["bw"]["rate"] == "67%"
    assert out["bt"]["count"] == "4번" and out["bt"]["rate"] == "75%"
    assert out["other"] == ["진행 중 2 · 1분봉 없음 1 · 진입 안 됨 1 · 다시 못 만듦 1 · 못 읽음 1", ""]
    assert out["list"][0] == "연구 조건 밖: 이김 2 · 짐 1 (전체 3개) · 보이는 것: 이겼을 신호 2개"
    assert out["list"][1] == "전체: 이김 8 · 짐 6 (전체 14개)" and out["list"][2] == ""
    assert out["chips"] == ["all:전체 14", "one:한 번에 하나 3", "research:연구 조건 밖 3", "nobreak:돌파 없음 1", "pause:쉬는 시간 1",
                            "late:늦음·재시작 1", "exec:실행기가 안 따라감 5"]
    assert out["same"] is True and out["diff"] is False
    assert out["pass"][0] == "" and out["pass"][1] == "1분 감시가 아직 계산 전이에요"
    assert out["pass"][2].startswith("마지막 계산 ") and "1분 전" in out["pass"][2] and "10분 넘게" in out["pass"][3]
    assert out["spans"] == ["all", "7d"] and out["groups"] == ["exec", "all", "all"] and out["results"] == ["loss", "all"]
    assert out["note"] == LM.NOTE_KO and out["filter"] == LM.FILTER_NOTE_KO and out["funding"] == LS.FUNDING_NOTE_KO


VIEW = """const every = [];
let fail = !!d.__fail;
const calls = [];
const ctx = {api: (p) => { calls.push(p); return fail ? Promise.reject(Object.assign(new Error("x"), {kind: "network", status: 0})) : Promise.resolve(d); },
  every(ms, fn) { every.push({ms, fn}); }, watch() {}, alive: () => true, href: (n, a) => '#/' + n, track() {}};
for (const [k, v] of Object.entries(d.__local || {})) localStorage.setItem("pb4-" + k, JSON.stringify(v));
const v = X.missedView(ctx);
const before = D.walk(v.el).text.replace(/\\s+/g, " ");
await tick();
const w = D.walk(v.el);
const shownFirst = shown(v.el).replace(/\\s+/g, " ");
const rows = find(v.el, "lbm-row");
if (rows[0]) rows[0].__mark = 1;
// the same answer again (the clock and the pass time moved): nothing is drawn again
d.now_ms = (d.now_ms || 0) + 60000; if (d.pass) d.pass = {...d.pass, last_ms: (d.pass.last_ms || 0) + 60000};
for (const e of every) e.fn(); await tick();
const kept = (find(v.el, "lbm-row")[0] || {}).__mark === 1;
// a refresh that fails: the last answer stays, dimmed, with its age
fail = true; for (const e of every) e.fn(); await tick();
const after = D.walk(v.el);
console.log(JSON.stringify({before, text: w.text.replace(/\\s+/g, " "), shown: shownFirst, classes: w.classes, kept, calls,
  ms: every.map((x) => x.ms), stale: after.text.replace(/\\s+/g, " "), staleCls: after.classes, hidden: v.el.childNodes.map((c) => !!c.hidden)}));"""


def test_view_cards_chips_rows_and_the_foot(answer):
    out = _node(VIEW, answer)
    t, cls = out["text"], out["classes"]
    assert not _bad(t), _bad(t)
    for words in ("못 탄 신호는 어땠을까?", "최근 7일", "기록 전체", "봇이 안 들어간 신호를, 왜 못 탔는지 그룹마다",
                  "실제로 탄 거래", "4번", "페이퍼 봇이 같은 기간에 실제로 들어간 거래", "한 번에 하나", "연구 조건 밖", "돌파 없음",
                  "쉬는 시간", "늦음·재시작", "실행기가 안 따라감", "이김", "짐", "승률", "순ROE 합", "한 번 평균", "표본 적음",
                  "연구 조건이 막은 신호: 가상 2승 1패", "→ 이번엔 쉰 게 손해를 줄였어요", "돌파를 안 기다리고 바로 탔다면: 가상 1승 0패",
                  "실행기가 안 따라간 페이퍼 거래: 페이퍼 결과 3승 2패", "이긴 것만 보지 말고 진 것과 같이 보세요", "마지막 계산",
                  "신호 하나씩", "전체 14", "한 번에 하나 3", "실행기가 안 따라감 5", "이겼을 신호", "졌을 신호",
                  "전체: 이김 8 · 짐 6 (전체 14개)", "같은 분에 BCH 롱 신호가 먼저 들어감", "끈 구간: 시각 14시", "연구 조건 밖 (필요: 주말만)",
                  "돌파를 안 기다리고 바로 탔다면 (가상)", "바이비트: 실행기 기록에 이유가 없어요", "MEXC: 그때 실행기가 멈춰 있었어요",
                  "페이퍼 거래의 결과 (실행기는 안 탐 · 가상 아님)", "✅", "계단 익절", "❌", "그때 탄 거래: BCH 롱 +16.6%", "1–10 / 14",
                  LM.NOTE_KO, LM.FILTER_NOTE_KO, LS.FUNDING_NOTE_KO):
        assert words in t, words
    assert "lbm-blk taken" in cls and "lbm-blk g-research" in cls and "lbm-w" in cls and "lbm-l" in cls
    assert any(c.startswith("lbm-row closed up") for c in cls) and any(c.startswith("lbm-row closed down") for c in cls)
    assert "lbm-g g-nobreak" in cls and "lbm-g g-exec" in cls
    for words in (LM.NOTE_KO, LM.FILTER_NOTE_KO, LS.FUNDING_NOTE_KO):
        assert words in out["before"]                                                         # the foot before any answer
    assert out["kept"] is True and out["ms"] == [30000]                                       # same answer: nothing redrawn
    assert out["calls"][0] == "/api/v4/livebots/missed?span=7d&group=all&result=all"
    assert "서버에 닿지 못했습니다" in out["stale"] and "자료를 보여 드립니다" in out["stale"] and "끈 구간: 시각 14시" in out["stale"]
    assert any("is-stale" in c.split() for c in out["staleCls"]) and LM.FILTER_NOTE_KO in out["stale"]


def test_view_with_a_win_filter_still_shows_both_sides(world):
    d = json_finite(DM.build(world["p"], world["more"], NOW + MIN, group="research", result="win"))
    out = _node(VIEW, {**d, "__local": {"lb-missed-group": "research", "lb-missed-result": "win"}})
    t = out["shown"]
    assert out["calls"][0] == "/api/v4/livebots/missed?span=7d&group=research&result=win"
    assert "연구 조건 밖: 이김 2 · 짐 1 (전체 3개) · 보이는 것: 이겼을 신호 2개" in t                # the losses stay in sight
    assert "연구 조건이 막은 신호: 가상 2승 1패" in t
    assert "❌" not in t.split("신호 하나씩")[1].split(LM.NOTE_KO)[0] and "✅" in t              # the list: wins only
    for words in ("한 번에 하나 규칙이 막은 신호", "실행기가 안 따라간 페이퍼 거래", "실제로 탄 거래"):
        assert words in t                                                                     # the cards stay whole


def test_view_remembers_the_span_and_says_missing_error_and_a_first_failure(world, tmp_path):
    out = _node(VIEW, {**json_finite(DM.build(world["p"], world["more"], NOW, span="all")), "__local": {"lb-missed-span": "all"}})
    assert out["calls"][0] == "/api/v4/livebots/missed?span=all&group=all&result=all" and "끈 구간: 시각 14시" in out["text"]
    miss = json_finite(DM.build(world["p"], {"check_db": str(tmp_path / "nope.db")}, NOW))
    t = _node(VIEW, miss)["shown"]
    assert "수집 전" in t and "1분 감시가 아직 기록 전" in t and LM.NOTE_KO in t and "실제로 탄 거래" not in t and not _bad(t)
    assert "못 탄 신호가 없어요" not in t and "신호 하나씩" not in t                 # never an empty list that reads as "nothing missed"
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"x" * 4096)
    t = _node(VIEW, json_finite(DM.build(world["p"], {"check_db": str(junk)}, NOW)))["shown"]
    assert "못 읽음" in t and LM.FILTER_NOTE_KO in t and not _bad(t) and "못 탄 신호가 없어요" not in t and "신호 하나씩" not in t
    out = _node(VIEW, {"__fail": True})
    assert "서버에 닿지 못했습니다" in out["text"] and out["hidden"] == [False, True, False] and LM.NOTE_KO in out["text"]
    nopaper = json_finite(DM.build({"paper": str(tmp_path / "no-paper.db")}, world["more"], NOW))
    t = _node(VIEW, nopaper)["text"]
    assert "실제로 탄 거래" in t and "수집 전" in t and "연구 조건 밖" in t and "끈 구간: 시각 14시" in t


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
    assert '@import url("livebots-missed.css")' in _read(os.path.join(SCREENS, "livebots.css"))
    js = _read(JS)
    assert '"/api/v4/livebots/missed"' in js and "export function missedView" in js
    assert 'import {missedView} from "./livebots-missed.js"' in _read(os.path.join(SCREENS, "livebots.js"))
    imports = re.findall(r'^import .* from "([^"]+)";', js, flags=re.M)
    assert imports == ["../core/pb.js", "./livebots-kit.js"]
    code = re.sub(r"//[^\n]*", "", js)
    for bad in ("innerHTML", "insertAdjacentHTML", "outerHTML", "DOMParser", "eval(", "toLocaleString", "Intl.NumberFormat", "setInterval(",
                "toFixed("):
        assert bad not in code, bad
