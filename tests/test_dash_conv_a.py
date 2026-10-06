"""Dashboard v4, 편의 4가지 (conv-a; owners 10/06 "클릭이 너무 많다"):

- 설정 한 곳 (core/settings.js): every per-device choice in one panel, the SAME storage keys as the controls it mirrors
  (nothing migrated), live through core/prefs.js; the gear / ',' / the speaker menu open it; night hours and each
  event's sound (core/sound.js, own keys); the start screen (routes.js startScreen) and the phone swipe switch.
- 자는 동안 (core/since.js + dash/more/since.py): the server's stops / restarts / nightly checks in the window
  (hand-computed on a synthetic paper3.db and daily3.db), days_left, nothing claimed without live_bars; the card lists
  every section with 없음, DeepSeek and coin flips counted only.
- 차트 크게 보기 (core/fullchart.js): every chart frame has the button, the key f, Esc / ✕ back.
- 여러 차트 (#/charts, screens/charts.js): the route, a clean stored grid, the overlay list (our groups only), one relay
  connection for the screen, the lite chart deck.
Static checks on the v4 files plus pure functions in node (a tiny DOM, tests/anasyn_dom.mjs) and the route on a
synthetic world. Read-only: nothing here writes a bot database.
"""
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash.app import _ro_uri, create_app, hash_password  # noqa: E402
from paperbot.dash.more import since as N  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
T0 = 1_791_000_000_000 - 1_791_000_000_000 % DAY + 2 * HOUR      # the run start (a whole minute)
PW = "conv a horse battery"


def _read(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as fh:
        return fh.read()


def _nocomment(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


# ---------------------------------------------------------------- a synthetic world
def _world(tmp_path, bars=True):
    """paper3.db: two accounts from T0, 1m live_bars from T0 to T0+170 min with a 10-minute stop at +100 and a
    2-minute gap at +120 (under the 3-minute rule), runs at T0 (the first start), +30 min and +110.5 min;
    daily3.db: two nightly checks (one before the window, one in it with 2 accounts that differ)."""
    db, ddb = str(tmp_path / "p.db"), str(tmp_path / "d.db")
    st = Store3(db)
    st.add_account("A@15m", "A", "15m", "strategy", T0, "paper-v4", None, {})
    st.add_account("F3_X@15m", "F3_X", "15m", "ds200", T0, "paper-v4", None, {"family": "F3"})
    st.put_state("run", T0, {"initial_equity": 5000.0})
    if bars:
        mins = [T0 + k * MIN for k in range(0, 171) if not (100 <= k < 110) and not (120 <= k < 122)]
        st.conn.executemany("INSERT INTO live_bars (ts, symbol, open, high, low, close, processed_at) VALUES (?,?,?,?,?,?,?)",
                            [(t, "BTCUSDT", 1, 1, 1, 1, t + 62_000) for t in mins])
    for t in (T0, T0 + 30 * MIN, T0 + 110 * MIN + 30_000):
        st.add_run(t, {"commit": "test"})
    st.commit()
    st.conn.close()
    d = sqlite3.connect(ddb)
    d.execute("CREATE TABLE reports (day TEXT PRIMARY KEY, ts INTEGER, data TEXT)")
    d.execute("INSERT INTO reports VALUES (?,?,?)", ("2026-10-01", T0 + 10 * MIN, json.dumps({"parity": {"accounts": 10, "mismatched_accounts": 0}})))
    d.execute("INSERT INTO reports VALUES (?,?,?)", ("2026-10-02", T0 + 90 * MIN, json.dumps({"parity": {"accounts": 10, "mismatched_accounts": 2}})))
    d.commit()
    d.close()
    return db, ddb


NOW = T0 + 180 * MIN + 30_000          # t_end (now minus the 3-minute lag) = T0 + 177 min
AFTER = T0 + 60 * MIN


def test_server_issues_count_the_stops_restarts_and_nightly_checks_in_the_window(tmp_path):
    db, ddb = _world(tmp_path)
    c = sqlite3.connect(_ro_uri(db), uri=True)
    s = N.server_issues(c, ddb, AFTER, NOW, T0)
    assert s["known"] is True and s["stop_min_rule"] == 3
    # the 10-minute stop, the 2-minute gap is not one, and the minutes from +171 to t_end (+177) are a stop still going
    assert s["stops"] == [{"from": T0 + 100 * MIN, "to": T0 + 110 * MIN, "min": 10, "ongoing": False},
                          {"from": T0 + 171 * MIN, "to": T0 + 177 * MIN, "min": 6, "ongoing": True}]
    assert (s["stops_n"], s["stop_min"]) == (2, 16) and s["longest"]["min"] == 10
    assert s["restarts"] == [T0 + 110 * MIN + 30_000]            # not the first start, not the one before the window
    assert [x["day"] for x in s["nightly"]] == ["2026-10-02"] and s["nightly"][0]["mismatched"] == 2
    # a window that starts after the stop: none of it
    s2 = N.server_issues(c, ddb, T0 + 140 * MIN, T0 + 170 * MIN + 3 * MIN + 1000, T0)
    assert s2["stops"] == [] and s2["restarts"] == [] and s2["nightly"] == []
    # a window shorter than the lag expects nothing yet
    s3 = N.server_issues(c, ddb, NOW - MIN, NOW, T0)
    assert s3["known"] is True and s3["stops_n"] == 0


def test_without_live_bars_nothing_is_claimed_and_the_answer_stays_empty(tmp_path):
    db, _ = _world(tmp_path, bars=False)
    c = sqlite3.connect(_ro_uri(db), uri=True)
    s = N.server_issues(c, None, AFTER, NOW, T0)
    assert s["known"] is False and s["stops"] == [] and s["stops_n"] == 0
    full = N.since(c, None, NOW - 20 * MIN, NOW)
    assert full["server"]["known"] is False and full["empty"] is True and full["server"]["restarts"] == []
    assert N.server_issues(c, None, AFTER, NOW, None)["known"] is False      # before the run: nothing


def test_since_carries_server_and_days_left_and_a_stop_alone_is_news(tmp_path):
    from paperbot.checkpoint import checkpoint_ts
    db, ddb = _world(tmp_path)
    c = sqlite3.connect(_ro_uri(db), uri=True)
    d = N.since(c, None, AFTER, NOW, False, ddb)
    assert d["server"]["stops_n"] == 2 and d["server"]["restarts"] == [T0 + 110 * MIN + 30_000]
    assert d["empty"] is False and d["trades"]["total"] == 0              # no trade, but the bot stopped: worth saying
    assert d["days_left"] == math.ceil((checkpoint_ts(T0, 1) - NOW) / DAY) and d["verdict_ts"] == checkpoint_ts(T0, 1)
    assert d["meetings"]["finished"] == 0 and "error" in d["meetings"]    # no agents3.db: said so, not zero meetings


def test_the_route_answers_with_the_server_section_behind_the_login(tmp_path):
    db, ddb = _world(tmp_path)
    app = create_app(db, hash_password(PW), b"s" * 32, candles=lambda s, i, n: [], daily_db=ddb, inbox_db=str(tmp_path / "inbox.db"))
    c = TestClient(app)
    assert c.get(f"/api/v4/since?after={AFTER}").status_code == 401
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get(f"/api/v4/since?after={AFTER}")
    assert r.status_code == 200
    j = r.json()
    assert set(j["server"]) >= {"known", "stops", "stops_n", "stop_min", "restarts", "nightly"} and "days_left" in j
    assert len(r.content) < 20_000


# ---------------------------------------------------------------- node: pure parts of the page
def _node(body: str, dom: bool = False) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    pre = f"await import('file://{os.path.join(ROOT, 'tests', 'anasyn_dom.mjs')}');\n" if dom else ""
    core = "file://" + os.path.join(V4, "core")
    scr = "file://" + os.path.join(V4, "screens")
    script = pre + f"const CORE = '{core}', SCR = '{scr}';\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_night_hours_and_event_sounds_keep_their_own_keys():
    out = _node("""
    const mem = {}; globalThis.localStorage = {getItem: (k) => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); }, removeItem: (k) => { delete mem[k]; }};
    globalThis.window = globalThis;
    globalThis.AudioContext = class { constructor() { this.state = "running"; this.currentTime = 0; this.destination = {}; }
      createGain() { return {gain: {value: 0, setTargetAtTime() {}}, connect() {}}; } resume() { return Promise.resolve(); } };
    const S = await import(CORE + '/sound.js');
    const played = []; S._test.setSink((k, a) => played.push(a.name || a.src || k));
    const at = (h) => Date.UTC(2026, 9, 5, (h - 9 + 24) % 24, 30);       // hh:30 Korea time
    const d0 = [0, 6, 7, 23].map((h) => S.nightKst(at(h)));
    S.setHours({from: 23, to: 6});
    const d1 = [22, 23, 2, 5, 6].map((h) => S.nightKst(at(h)));
    S.setHours({from: "x", to: 99});                                       // bad input keeps the hours as they were
    const kept = {...S.hours};
    S.setHours({from: 5, to: 5});
    const none = [0, 5, 12].map((h) => S.nightKst(at(h)));
    S.setEv("c_tp", false); S.setEv("layer", false); S.setEv("nonsense", false);
    S.cfg.on = true; S.cfg.night = false; S._test.unlock(true);
    const tp = S.playMotifs(["c_tp"]), sl = S.playMotifs(["c_sl"]);
    S._test.setKinds({"F3_X@15m": "ds200"});
    S.onTrades([{id: 1, account_id: "F3_X@15m", pnl: 5, exit_reason: "LOCK"}]);
    const layerAfter = S._test.layer.size;
    S.cfg.on = false; played.length = 0;
    const pv = [S.preview("c_tp"), S.preview("layer"), S.preview("x")];
    console.log(JSON.stringify({d0, d1, kept, none, tp, sl, layerAfter, played, pv, ev: S.evOn("c_tp"), evSl: S.evOn("c_sl"),
      mem: {hours: mem["pb4-snd-hours"], ev: mem["pb4-snd-ev"], sound: mem["pb4-sound"] ?? null}, cfg: S.cfg}));
    """)
    assert out["d0"] == [True, True, False, False]                       # default 00-07
    assert out["d1"] == [False, True, True, True, False]                 # 23 -> 06 wraps midnight
    assert out["kept"] == {"from": 23, "to": 6}
    assert out["none"] == [False, False, False]                          # from == to: no window
    assert out["tp"] == [] and out["sl"] == ["c_sl"] and out["ev"] is False and out["evSl"] is True
    assert out["layerAfter"] == 0                                        # 바탕음 off: DeepSeek fills make no beep
    assert out["pv"] == [True, True, False] and out["played"][:2] == ["c_tp", "preview"]   # 들어보기: once, sound off too
    assert json.loads(out["mem"]["hours"]) == {"from": 5, "to": 5}
    assert json.loads(out["mem"]["ev"]) == {"c_tp": False, "layer": False}
    assert out["mem"]["sound"] is None or set(json.loads(out["mem"]["sound"])) <= {"on", "vol", "density", "night"}
    assert set(out["cfg"]) == {"on", "vol", "density", "night"}           # the old key keeps its four fields


def test_start_screen_prefs_and_deck_state():
    out = _node("""
    const mem = {}; globalThis.localStorage = {getItem: (k) => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); }, removeItem: (k) => { delete mem[k]; }};
    let wide = true; globalThis.matchMedia = (q) => ({matches: /min-width: (7[0-9]{2}|900|1200)px/.test(q) ? wide : false, addEventListener() {}});
    const R = await import(CORE + '/routes.js'), P = await import(CORE + '/prefs.js');
    const res = {};
    res.auto = R.landing();
    P.setPref(P.START_KEY, "charts"); res.charts = R.landing();
    P.setPref(P.START_KEY, "account"); res.hidden = R.landing();
    P.setPref(P.START_KEY, "_kit"); res.kit = R.landing();
    P.setPref(P.START_KEY, "toString"); res.proto = R.landing();
    P.setPref(P.START_KEY, "terminal"); res.termWide = R.landing(); wide = false; res.termPhone = R.landing();
    P.setPref(P.START_KEY, ""); res.autoPhone = R.landing();
    const got = []; const off = P.onPref("x", (v) => got.push(v)); P.setPref("x", 1); off(); P.setPref("x", 2);
    res.got = got; res.stored = mem["pb4-x"];
    res.swipe0 = P.swipeOn(); P.setPref(P.SWIPE_KEY, false); res.swipe1 = P.swipeOn();
    res.charts_meta = R.SCREENS.charts; res.trade = R.GROUPS.find((g) => g.id === "trade").screens;
    console.log(JSON.stringify(res));
    """)
    assert out["auto"] == "terminal" and out["charts"] == "charts"
    assert out["hidden"] == "terminal" and out["kit"] == "terminal" and out["proto"] == "terminal"   # not listed: automatic
    # a PC-only screen chosen on a phone, and no choice at all, both fall back on the main rule (routes.js: the 터미널 from
    # 900 px, else the 차트 screen), the same screen the 설정 panel names as 자동
    assert out["termWide"] == "terminal" and out["termPhone"] == "chart" and out["autoPhone"] == "chart"
    assert out["got"] == [1] and out["stored"] == "2"
    assert out["swipe0"] is True and out["swipe1"] is False
    assert out["charts_meta"] == {"ko": "여러 차트", "group": "trade", "title": "여러 차트"}
    assert out["trade"] == ["terminal", "positions", "chart", "charts", "market"]


def test_away_card_lists_every_section_and_counts_deepseek_only():
    away = {"after": T0, "now": T0 + 7 * HOUR, "clamped": False, "start": T0,
            "trades": {"total": 9, "liquidations": 0, "groups": {"core": {"trades": 4, "wins": 3, "liq": 0, "pnl": 120.5},
                                                                  "ds200": {"trades": 5, "wins": 2, "liq": 0}}},
            "best": {"account_id": "A@15m", "symbol": "BTCUSDT", "pnl": 80.0, "exit_reason": "LOCK"}, "worst": None,
            "busts": {"n": 0, "by_group": {}, "named": []}, "meetings": {"finished": 0, "decided": 0, "lines": []},
            "alerts": {"n": 0, "by_level": {}, "latest": []}, "milestones": [],
            "server": {"known": True, "stops": [], "stops_n": 0, "stop_min": 0, "restarts": [], "nightly": []},
            "dn": 1, "of": 30, "verdict_ts": T0 + 29 * DAY, "days_left": 29, "empty": False}
    out = _node(f"""
    globalThis.location = {{hash: ""}}; globalThis.addEventListener = () => {{}};
    const D = await import('file://{os.path.join(ROOT, "tests", "anasyn_dom.mjs")}');
    const S = await import(CORE + '/since.js');
    const d = {json.dumps(away)};
    const J = {{available: true, jobs: {{}}}};
    const p = S.awayParts(d, {{id: "8h", words: "최근 8시간", jobs: J}}); p.sub = p.sub.join("");
    const srv = S.serverRows({{server: {{known: true, stops_n: 1, stop_min: 40, longest: {{from: {T0}, to: {T0 + 40 * MIN}, min: 40, ongoing: true}}, restarts: [{T0 + HOUR}],
      nightly: [{{day: "2026-10-02", accounts: 10, mismatched: 2}}, {{day: "2026-10-03", accounts: 10, mismatched: 0}}]}}}},
      {{available: true, jobs: {{"paperbot-backup": {{ok: false, last_ms: {T0 + 2 * HOUR}}}, "paperbot-daily3": {{ok: true, last_ms: {T0 + 2 * HOUR}}},
        "paperbot-offsite": {{ok: false, last_ms: {T0 - HOUR}}}}}}}, {{level: "warn", problems: [], warnings: ["신호가 늦습니다"]}}, {T0});
    // the health card's real shapes: "bad" carries problems; "ok" nothing to say
    const bad = S.serverRows({{server: {{known: true, stops_n: 0, restarts: [], nightly: []}}}}, null, {{level: "bad", problems: ["봇이 멈췄습니다"], warnings: ["밤 점검 늦음"]}}, {T0});
    const fine = S.serverRows({{server: {{known: true, stops_n: 0, restarts: [], nightly: []}}}}, null, {{level: "ok", problems: [], warnings: []}}, {T0});
    // systemd did not answer (or the jobs request failed) and agents3.db is missing: 확인 못 함, never 없음
    const noJobs = S.awayParts({{...d, meetings: {{finished: 0, decided: 0, lines: [], error: "agents3.db 없음"}}}}, {{id: "8h", words: "최근 8시간", jobs: {{available: false, jobs: {{}}}}}});
    const after30 = S.awayParts({{...d, dn: 35, of: 30}}, {{id: "8h", words: "최근 8시간", jobs: J}});
    const r = S.rangeAfter("away", {T0 + 10 * HOUR}, {{from: {T0 + HOUR}, to: {T0 + 9 * HOUR}}});
    const r2 = S.rangeAfter("away", {T0 + 10 * HOUR}, null);
    const unk = S.awayParts({{...d, server: {{known: false, stops: [], stops_n: 0, restarts: [], nightly: []}}}}, {{id: "8h", words: "최근 8시간", jobs: J}});
    const lastDay = S.verdictLeft({{verdict_ts: {T0 + 5 * HOUR}, now: {T0}, days_left: 1}});
    console.log(JSON.stringify({{tiles: D.walk(p.tiles), rows: D.walk(p.rows), title: p.title, sub: p.sub, srv: D.walk(srv).text, nsrv: srv.length,
      r, r2: r2[0], unk: D.walk(unk.rows).text, lastDay, bad: D.walk(bad).text, nfine: fine.length, noJobs: D.walk(noJobs.rows).text,
      after30: D.walk(after30.rows).text}}));
    """, dom=True)
    t = out["tiles"]["text"]
    assert "기존 36" in t and "120.50 USDT" in t and "딥시크 44" in t and "건수만" in t and "5분봉" in t and "동전 봇" in t
    assert t.count("USDT") == 1                                          # only the money group has money
    rows = out["rows"]["text"]
    for sec in ("거래 · 파산", "회의 · 알림", "서버", "판정"):
        assert sec in rows
    assert rows.count("없음") >= 5                                        # worst, busts, meetings, alerts, server: 없음
    assert "가장 크게 번 거래" in rows and "+80.00" in rows and "판정까지 29일" in rows
    assert out["title"] == "최근 8시간 동안" and "7시간 동안" in out["sub"] and "판정까지 29일" in out["sub"]
    s = out["srv"]
    assert out["nsrv"] == 5 and "봇 멈춤 1번" in s and "지금까지 이어짐" in s and "봇 다시 시작 1번" in s
    assert "다시 계산이 다른 계좌 2개" in s and "2026-10-03" not in s       # a clean nightly check is not a problem
    assert "예약 작업 실패 1개" in s and "DB 백업" in s and "바깥 백업" not in s   # failed before the window: not counted
    assert "지금 확인할 것 있음" in s and "신호가 늦습니다" in s
    assert out["r"][0] == T0 + HOUR and out["r2"] == T0 + 2 * HOUR       # no absence yet: the last 8 hours
    # no 1-minute records: the card says it could not tell, never "no stop"
    assert "봇 멈춤" in out["unk"] and "확인 못 함" in out["unk"] and "봇 가동 기록(1분봉)이 아직 없습니다" in out["unk"]
    assert out["lastDay"] == "5시간"                                     # the verdict's last day counts hours
    # the health card: a problem at "bad", nothing at "ok" (a warning alone was dropped before: the "warn" case read
    # problems, which the server leaves empty at that level)
    assert "지금 문제 있음" in out["bad"] and "봇이 멈췄습니다" in out["bad"] and "밤 점검 늦음" not in out["bad"]
    assert out["nfine"] == 0
    nj = out["noJobs"]
    assert "예약 작업" in nj and "예약 작업 기록을 읽지 못했습니다" in nj and "회의 기록을 읽지 못했습니다" in nj
    assert nj.count("확인 못 함") == 2 and "서버 문제" not in nj                # never "no server problem" without the timers
    assert "D+35 · 다음 판정" in out["after30"] and "/ 30" not in out["after30"]


def test_away_card_says_the_verdict_in_the_clock_words_and_waits_on_the_verdict_day():
    """wave-a merge: the 자는 동안 card's 판정 section in the verdict-day clock's words (more/verdictday.py line_ko,
    fix-verdict change 13), and a verdict day that passed is named until its result is stored (fix 1): 결과 기다림,
    never '판정까지 0초' and never the next verdict; the milestone of that day says 계산 중 / 결과가 나왔습니다."""
    base = {"after": T0, "now": T0 + 7 * HOUR, "clamped": False, "start": T0,
            "trades": {"total": 0, "liquidations": 0, "groups": {}}, "best": None, "worst": None,
            "busts": {"n": 0, "by_group": {}, "named": []}, "meetings": {"finished": 0, "decided": 0, "lines": []},
            "alerts": {"n": 0, "by_level": {}, "latest": []}, "milestones": [],
            "server": {"known": True, "stops": [], "stops_n": 0, "stop_min": 0, "restarts": [], "nightly": []},
            "dn": 1, "of": 30, "verdict_ts": T0 + 29 * DAY, "days_left": 29, "verdict_k": 1, "verdict_due": False,
            "line_ko": "30일 중 1일 지남 · 판정까지 29일 (11/04 09:00)", "empty": False}
    due = {**base, "now": T0 + 29 * DAY + 2 * HOUR, "dn": 30, "verdict_due": True, "days_left": 0,
           "line_ko": "30일 판정 날 · 동전 봇 비교 계산 중",
           "milestones": [{"kind": "day", "from": 29, "to": 30},
                          {"kind": "verdict", "k": 1, "ts": T0 + 29 * DAY, "judged": False, "stored_ts": None}]}
    done = {**due, "milestones": [{"kind": "verdict", "k": 1, "ts": T0 + 29 * DAY, "judged": True, "stored_ts": T0 + 29 * DAY + HOUR}]}
    out = _node(f"""
    globalThis.location = {{hash: ""}}; globalThis.addEventListener = () => {{}};
    const D = await import('file://{os.path.join(ROOT, "tests", "anasyn_dom.mjs")}');
    const S = await import(CORE + '/since.js');
    const J = {{available: true, jobs: {{}}}};
    const one = (d) => {{ const p = S.awayParts(d, {{id: "8h", words: "최근 8시간", jobs: J}}); return {{rows: D.walk(p.rows).text, sub: p.sub.join("")}}; }};
    console.log(JSON.stringify({{base: one({json.dumps(base)}), due: one({json.dumps(due)}), done: one({json.dumps(done)})}}));
    """, dom=True)
    b, d, k = out["base"], out["due"], out["done"]
    assert "판정까지 29일" in b["rows"] and "30일 중 1일 지남 · 판정까지 29일 (11/04 09:00)" in b["rows"] and "판정까지 29일" in b["sub"]
    assert "D+1 / 30" not in b["rows"]                                    # one wording: the clock's sentence
    assert "30일 판정 · 결과 기다림" in d["rows"] and "동전 봇 비교 계산 중" in d["rows"] and "판정 결과 기다림" in d["sub"]
    assert "판정까지 0" not in d["rows"] + d["sub"] and "2번째" not in d["rows"]
    assert "실험 29일 → 30일 지남" in d["rows"] and "30일 판정 날 · 결과 계산 중" in d["rows"]
    assert "30일 판정 결과가 나왔습니다" in k["rows"] and "결과 계산 중" not in k["rows"]


def test_grid_cells_are_cleaned_and_only_our_groups_can_be_laid_over():
    out = _node("""
    const C = await import(SCR + '/charts.js');
    const g0 = C.cleanGrid(null), g1 = C.cleanGrid({layout: "5x5", cells: [{sym: "ABCUSDT", tf: "2m", acct: 5}, {sym: "ETHUSDT", tf: "4h", acct: "all"}]});
    const board = {accounts: [
      {account_id: "A@15m", kind: "strategy", timeframe: "15m", position: {symbol: "BTCUSDT", side: 1, entry: 1, qty: 1}},
      {account_id: "F3_X@15m", kind: "ds200", timeframe: "15m", position: {symbol: "BTCUSDT", side: 1, entry: 1, qty: 1}},
      {account_id: "RANDOM_1@15m", kind: "random", timeframe: "15m", position: {symbol: "BTCUSDT", side: -1, entry: 1, qty: 1}},
      {account_id: "REEL_H1@5m", kind: "reel", timeframe: "5m", position: {symbol: "BTCUSDT", side: 1, entry: 1, qty: 1}},
      {account_id: "B@1h", kind: "strategy", timeframe: "1h", position: {symbol: "ETHUSDT", side: 1, entry: 1, qty: 1}},
      {account_id: "C@1h", kind: "strategy", timeframe: "1h", position: null}]};
    console.log(JSON.stringify({g0, g1, btc: C.overlayAccounts(board, "BTCUSDT").map((a) => a.account_id), none: C.overlayAccounts(null, "BTCUSDT"),
      layouts: C.LAYOUTS, tfs: C.TFS}));
    """)
    assert out["g0"]["layout"] == "2x2" and len(out["g0"]["cells"]) == 9 and out["g0"]["cells"][0] == {"sym": "BTCUSDT", "tf": "15m", "acct": ""}
    assert out["g1"]["layout"] == "2x2" and out["g1"]["cells"][0] == {"sym": "BTCUSDT", "tf": "15m", "acct": ""}
    assert out["g1"]["cells"][1] == {"sym": "ETHUSDT", "tf": "4h", "acct": "all"}
    assert out["btc"] == ["A@15m", "REEL_H1@5m"]                         # DeepSeek and coin flips are never offered
    assert out["none"] == [] and out["layouts"] == {"2x2": 4, "3x3": 9}


# ---------------------------------------------------------------- static: wiring, keys, look
def test_settings_panel_is_wired_everywhere_and_uses_the_same_keys():
    st = _read("core", "settings.js")
    for key in ('local.set("skin", id)', 'local.set("text", id)', "setPref(FLASH_KEY, id)", 'setPref("cfx-" + key', 'setPref("chart-show", next)',
                "sound.setCfg(", "sound.setKind(id)", "sound.setWake(on)", "sound.setHours(", "sound.setEv(id, on)",
                "setPref(START_KEY, sel.value)", "setPref(SWIPE_KEY, on)", "setPref(GRID_KEY,"):
        assert key in st, key
    for bad in ("localStorage", "innerHTML", "insertAdjacentHTML", "outerHTML", "eval(", "toLocaleString"):
        assert bad not in st, bad
    assert '"aria-modal": "true"' in st and 'e.key === "Escape"' in st and 'e.key !== "Tab"' in st
    fx = _read("core", "chartfx.js")
    assert 'FLASH_KEY = "chart-flash"' in fx and "export {FLASH_KEY};" in fx and "onPref(key, (v) =>" in fx and "onPref(FLASH_KEY, (v) =>" in fx
    assert 'const key = "cfx-" + (o.key || "chart");' in fx                 # the decks' storage keys are unchanged
    assert "export function deckState(key, groups, defaults)" in fx
    # a deck saves through prefs (the 여러 차트 cells share one key: a line hidden in one cell is not dropped by another's
    # save) and skips its own echo; only the groups that changed are drawn again
    assert "local.set(key, v);" in fx and "tellPref(key, v)" in fx and "if (saving) return;" in fx
    assert "for (const g of moved) applyGroup(g, true);" in fx
    main = _read("core", "main.js")
    assert main.index("startSettings();") < main.index("startSince();")
    nk = _read("core", "navkeys.js")
    assert 'e.code === "Comma"' in nk and 'e.code === "KeyF"' in nk and "toggleFull()" in nk and "!swipeOn()" in nk
    assert nk.index("if (settingsOpen()) return;") < nk.index('if (e.key === "/")')
    assert "settingsTab()" in _read("core", "shell.js") and "settingsRail()" in _read("core", "rail.js")
    snd = _read("core", "sound.js")
    assert 'bus.emit("settings:open", "sound")' in snd and "evOn(n)" in snd and '!evOn("layer")' in snd
    html = _read("index.html")
    assert '<link rel="stylesheet" href="/static/v4/core/settings.css">' in html and '<link rel="stylesheet" href="/static/v4/core/fullchart.css">' in html
    chart = _read("screens", "chart.js")
    assert 'onPref("chart-show", (v) =>' in chart


def test_every_chart_has_the_fullscreen_button_and_charts_screen_uses_one_relay():
    for rel, mark in (("screens/terminal-chart.js", "fs.bind(el)"), ("screens/chart.js", "fs.bind(chartCard)"),
                      ("screens/strategies-detail.js", ".bind(chartCard)"), ("screens/account.js", "fs.bind(candleCard)"),
                      ("screens/charts.js", "fs.bind(root)"), ("screens/account.js", "eqFs.bind(eqCard)"),
                      ("screens/replay.js", "fs.bind(chartCard)")):
        src = _read(*rel.split("/"))
        assert "fullChart(" in src and mark in src, rel
    # an extra account (no same-strategy strip) no longer shows the word "null" (native replaceChildren with a null)
    acc = _read("screens", "account.js")
    assert "el.replaceChildren(...[backLink(), headSlot, same ? same.el : null, candleCard," in acc and 'ui.assumeLine(["closed", "open"])].filter(Boolean));' in acc
    # the 자본 곡선 cannot be scrolled or zoomed: at a new size it fills the width again
    assert "subscribeSizeChange(() => c.chart.timeScale().fitContent())" in _read("screens", "account.js")
    fc = _read("core", "fullchart.js")
    assert 'e.key !== "Escape"' in fc and '"fullscreenchange"' in fc and '"hashchange"' in fc and "requestFullscreen" in fc
    assert "가로로 돌리면" in fc and "setTimeout" not in fc and "setInterval" not in fc     # nothing on a timer
    # a card drawn again while big (the 계좌 page after a fill) hands over to its new frame or frees the page; the late
    # fullscreenchange of the old frame does not put the new one back (only a frame that really was full screen)
    assert "new MutationObserver(" in fc and "x.o.label === old.o.label" in fc and "enter(next, true)" in fc
    assert "if (mo) { mo.disconnect(); mo = null; }" in fc and "cur.real && document.fullscreenElement !== cur.frame" in fc
    ch = _read("screens", "charts.js")
    assert ch.count("tickStream(ctx)") == 1 and "new EventSource" not in ch           # ONE relay connection for the screen
    assert "lite: true" in ch and "key: GRID_DECK.key" in ch and "ui.assume(\"open\"" in ch
    assert "local.get(GRID_KEY" in ch and "localStorage" not in ch and "innerHTML" not in ch
    assert "for (let x of rows || [])" in ch                                      # the forming bar from the poll
    inv = _read("INVENTORY.md")
    assert "## 편의 4가지 (conv-a" in inv and "#/charts" in inv


def test_since_job_names_match_the_server_screen():
    since = _read("core", "since.js")
    units = re.findall(r'unit: "(paperbot-[a-z0-9]+)", ko: "([^"]+)"', _read("screens", "server-kit.js"))
    for u, ko in units:
        assert f'"{u}": "{ko}"' in since, u
    assert "AWAY_MS = 3 * 3600000" in since and "prev != null && serverNow() - prev >= GAP_MS" in since
    assert '"/api/v4/jobs"' in since and "localStorage" not in since and "innerHTML" not in since


def test_touch_targets_on_a_phone_are_32px():
    st = _nocomment(_read("core", "settings.css"))
    assert re.search(r"\.set-sw \{[^}]*height: 32px", st) and re.search(r"\.set-try \{[^}]*min-height: 32px", st)
    fc = _nocomment(_read("core", "fullchart.css"))
    assert "@media (max-width: 759px) { .fc-btn { height: 32px; } }" in fc
    cg = _nocomment(_read("screens", "charts.css"))
    assert ".cg-sel { height: 32px; }" in cg and ".cg-ov { order: 1; width: auto; flex: 1 1 100%; }" in cg


def test_new_css_uses_tokens_and_the_font_floor():
    for rel in ("core/settings.css", "core/fullchart.css", "screens/charts.css", "core/since.css"):
        css = _nocomment(_read(*rel.split("/")))
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css) and not re.search(r"\brgba?\(\s*\d", css), rel
        for m in re.finditer(r"font(?:-size)?\s*:\s*([^;}]+)", css):
            v = m.group(1)
            assert "var(--t-" in v or "calc(" in v or v.strip() == "inherit", (rel, v)
