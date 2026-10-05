"""The dashboard's '분석' tab, health card, alert history, server clock, debate room, chart extras and the phone
shortcut (paperbot/dash/analysis.py, charts.js, analysis.js, manifest.json)."""

import json
import os
import re
import sqlite3
import sys
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot.dash import analysis as AN  # noqa: E402
from paperbot.dash.app import CANDLE_INTERVALS, PUBLIC_PATHS, create_app, hash_password  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_dash import SECRET, _store  # noqa: E402

PW = "correct horse battery"
STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "paperbot", "dash", "static")
ROUTES = ("/api/time", "/api/analysis/health", "/api/analysis/alerts", "/api/analysis/risk",
          "/api/analysis/readiness", "/api/analysis/shock", "/api/analysis/map", "/api/analysis/entry",
          "/api/analysis/synergy", "/api/analysis/questions", "/api/debate")
MAX_BYTES = 300_000


def _client(db, **kw):
    app = create_app(db, hash_password(PW), SECRET,
                     candles=lambda s, i, n: [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}], **kw)
    c = TestClient(app)
    return c


def _login(c):
    assert c.post("/api/login", json={"password": PW}).status_code == 200


def _daily(path, parity, labels=()):
    d = sqlite3.connect(path)
    d.executescript("CREATE TABLE reports (day TEXT PRIMARY KEY, ts INTEGER NOT NULL, data TEXT NOT NULL);"
                    "CREATE TABLE mismatches (day TEXT NOT NULL, account_id TEXT NOT NULL, data TEXT NOT NULL);")
    d.execute("INSERT INTO reports VALUES (?, ?, ?)", ("2026-10-03", int(time.time() * 1000),
                                                       json.dumps({"day": "2026-10-03", "parity": parity,
                                                                   "data_quality": {"BTCUSDT": {"missing": 2}}})))
    for i, lab in enumerate(labels):
        d.execute("INSERT INTO mismatches VALUES (?, ?, ?)", ("2026-10-03", f"A{i}@15m", json.dumps({"label": lab})))
    d.commit()
    d.close()


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / "paper3.db")
    _store(db).close()
    return {"db": db, "dir": tmp_path, "client": _client(db, failalert_dir=str(tmp_path / "failalert"))}


def test_every_new_route_needs_the_login(env):
    c = env["client"]
    for r in ROUTES:
        assert c.get(r).status_code == 401, r


def test_every_new_route_answers_bounded_json(env):
    c = env["client"]
    _login(c)
    for r in ROUTES:
        got = c.get(r)
        assert got.status_code == 200, r
        assert isinstance(got.json(), dict) and len(got.content) < MAX_BYTES, r
        assert not got.json().get("pending"), r                  # a tiny paper3.db is computed within the wait
    now = c.get("/api/time").json()["now"]
    assert abs(now - time.time() * 1000) < 5_000
    risk = c.get("/api/analysis/risk").json()
    assert risk["trades"] == 1 and risk["all"]["small"] is True and "drawdown" in risk     # sample size is stated
    assert risk["computed_at"] > 0
    rd = c.get("/api/analysis/readiness").json()
    assert rd["summary"]["accounts"] == 1 and rd["accounts"][0]["marks"] and len(rd["conditions"]) == 8
    sh = c.get("/api/analysis/shock").json()
    assert sh["open_positions"] == 0 and sh["rows"]
    mp = c.get("/api/analysis/map").json()
    assert mp["strategy"]["trades"] == 1 and mp["strategy"]["by_coin"]["BTC"]["small"] is True
    sy = c.get("/api/analysis/synergy").json()
    assert sy.get("small") is True                                # 1 day < 14: marked small
    hl = c.get("/api/analysis/health").json()
    assert hl["level"] == "bad" and hl["bot"]["ready"] and hl["agents"] == {"configured": False}
    assert any("생존 신호" in p for p in hl["problems"])
    al = c.get("/api/analysis/alerts").json()
    assert al["bot"] and al["not_stored"] and "paper3.db alerts" in al["sources"]


def test_missing_paper_db_never_errors_and_creates_nothing(tmp_path):
    db = str(tmp_path / "nope" / "paper3.db")
    os.makedirs(os.path.dirname(db))
    c = _client(db)
    _login(c)
    for r in ROUTES:
        got = c.get(r)
        assert got.status_code == 200, r
        assert len(got.content) < MAX_BYTES
    assert c.get("/api/analysis/risk").json()["error"]
    assert c.get("/api/analysis/shock").json()["error"]
    assert c.get("/api/analysis/health").json()["bot"] == {"ready": False}
    assert sorted(os.listdir(os.path.dirname(db))) == []          # read-only: no database file was created


def test_empty_paper_db_never_errors(tmp_path):
    db = str(tmp_path / "paper3.db")
    sqlite3.connect(db).close()
    c = _client(db)
    _login(c)
    for r in ROUTES:
        got = c.get(r)
        assert got.status_code == 200 and len(got.content) < MAX_BYTES, r


def test_health_and_alerts_read_the_nightly_check_with_the_early_kline_label(env, tmp_path):
    _daily(str(tmp_path / "daily3.db"), {"accounts": 156, "mismatched_accounts": 0, "early_kline": 2},
           labels=("early_kline (거래소 1분봉 확정 전 읽음)", "early_kline (거래소 1분봉 확정 전 읽음)"))
    os.makedirs(tmp_path / "failalert")
    (tmp_path / "failalert" / "paperbot-daily3.service").write_text("2026-10-04")
    c = env["client"]
    _login(c)
    h = c.get("/api/analysis/health").json()
    assert h["nightly"]["parity"]["early_kline"] == 2 and h["nightly"]["missing_bars"] == 2
    assert h["nightly"]["mismatch_labels"] == {"early_kline (거래소 1분봉 확정 전 읽음)": 2}
    assert any("early_kline" in w for w in h["warnings"])
    assert not any("불일치" in p for p in h["problems"])
    assert h["job_failures"][0]["unit"] == "paperbot-daily3.service" and h["job_failures"][0]["day"] == "2026-10-04"
    a = c.get("/api/analysis/alerts").json()
    assert a["nightly"][0]["parity"]["early_kline"] == 2 and len(a["mismatches"]) == 2
    assert a["mismatches"][0]["label"].startswith("early_kline")


def test_a_real_mismatch_is_a_problem(tmp_path):
    db = str(tmp_path / "paper3.db")
    _store(db).close()
    _daily(str(tmp_path / "daily3.db"), {"accounts": 156, "mismatched_accounts": 3})
    out = AN.health(type("D", (), {"db": db, "summary": lambda self, now=None: {}})(),
                    type("R", (), {"agents_db": None})(), str(tmp_path / "daily3.db"), None, None,
                    failalert_dir=str(tmp_path / "none"))
    assert out["level"] == "bad" and any("불일치 3" in p for p in out["problems"])


def test_heavy_waits_then_answers_pending_and_keeps_the_result():
    import threading
    gate = threading.Event()
    h = AN.Heavy(wait_s=0.05)
    calls = []

    def slow():
        calls.append(1)
        gate.wait(5)
        return {"x": 1}
    assert h.get("k", 60, slow)["pending"] is True
    assert h.get("k", 60, slow)["pending"] is True               # the same computation, not a second one
    gate.set()
    for _ in range(100):
        if h.peek("k"):
            break
        time.sleep(0.02)
    got = h.get("k", 60, slow)
    assert got["x"] == 1 and got["computed_at"] > 0 and calls == [1]
    # an error is kept only briefly and never shown as a result
    e = AN.Heavy(wait_s=2).get("e", 600, lambda: 1 / 0)
    assert e["error"].startswith("계산하지 못함")


def test_entry_view_says_preparing_when_the_module_is_missing(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "paperbot.agents.entrymoment", None)
    out = AN.entry_view(env["db"], None, int(time.time() * 1000))
    assert out["unavailable"] is True and "준비 중" in out["note"]


def test_questions_checklist(tmp_path):
    assert AN.questions(str(tmp_path / "none.json"))["ready"] is False
    shipped = AN.questions()                                      # the file in the repository loads
    assert isinstance(shipped["questions"], list) and ("note" in shipped or shipped["ready"])
    p = tmp_path / "q.json"
    p.write_text(json.dumps({"source": "docs/x.md", "questions": [
        {"n": 1, "q": "봇이 살아 있나?", "status": "done", "where": "분석 > 건강 점검"},
        {"n": 2, "q": "x" * 1000, "status": "weird"}, "junk"]}), encoding="utf-8")
    q = AN.questions(str(p))
    assert q["ready"] and q["total"] == 2 and q["counts"]["done"] == 1 and q["counts"]["todo"] == 1
    assert len(q["questions"][1]["q"]) == 300


def test_debate_room_reads_a_future_table_read_only(tmp_path, env):
    path = str(tmp_path / "debate.db")
    assert AN.debate(path)["ready"] is False
    c = env["client"]
    _login(c)
    off = c.get("/api/debate").json()                              # no debate.db: the service was never started
    assert off["ready"] is False and off["state"] == "off" and off["state_ko"] == "꺼짐" and "꺼짐" in off["note"]
    assert off["rounds"] == [] and off["hypotheses"] == [] and off["ideas"] == []
    d = sqlite3.connect(path)
    d.execute("CREATE TABLE debate_messages (id INTEGER PRIMARY KEY, ts INTEGER, speaker TEXT, stance TEXT, "
              "topic TEXT, text TEXT)")
    d.executemany("INSERT INTO debate_messages VALUES (?,?,?,?,?,?)",
                  [(1, 1000, "낙관", "롱", "BTC", "오른다"), (2, 2000, "비관", "숏", "BTC", "내린다")])
    d.commit()
    d.close()
    before = os.path.getmtime(path)
    out = AN.debate(path)
    assert out["ready"] and [m["id"] for m in out["messages"]] == [1, 2]
    assert os.path.getmtime(path) == before and not os.path.exists(path + "-wal")


def test_bot_chart_takes_every_binance_interval(env):
    c = env["client"]
    _login(c)
    assert CANDLE_INTERVALS == ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d",
                                "1w", "1M")
    for iv in CANDLE_INTERVALS:
        assert c.get(f"/api/candles?symbol=BTCUSDT&interval={iv}").status_code == 200, iv
    for bad in ("2d", "1y", "1mo", ""):
        assert c.get(f"/api/candles?symbol=BTCUSDT&interval={bad}").status_code == 400
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    seg = re.search(r'<div class="seg" id="tf-seg">(.*?)</div>', html, re.S).group(1)
    assert tuple(re.findall(r'data-tf="([^"]+)"', seg)) == CANDLE_INTERVALS


def test_tradingview_and_coinglass_load_in_the_browser_only(env):
    c = env["client"]
    # the CSP stays as it was: frames of this site refused; it has no script/frame source list that would have to
    # name TradingView (adding one would also have to list Binance's streams)
    for r in (c.get("/login"), c.get("/static/manifest.json")):
        assert r.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
    here = os.path.dirname(STATIC)
    for f in ("app.py", "analysis.py"):
        src = open(os.path.join(here, f), encoding="utf-8").read()
        assert "tradingview.com" not in src and "coinglass.com" not in src, f      # the server never fetches them
    js = open(os.path.join(STATIC, "charts.js"), encoding="utf-8").read()
    hosts = set(re.findall(r"https://([a-z0-9.-]+)", js))
    assert hosts == {"s3.tradingview.com", "www.coinglass.com"}
    assert 'BINANCE:${coin(state.sym)}USDT.P' in js and 'locale: "kr"' in js
    assert 'rel="noopener noreferrer"' in js and 'target="_blank"' in js
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    assert "tradingview" not in html.lower()                      # loaded only when that chart is opened
    assert 'data-m="tv"' in html and "거래소 차트" in html and "봇 차트" in html and 'id="cd-strip"' in html


def test_phone_shortcut_files_are_public_and_no_service_worker(env):
    c = env["client"]
    m = c.get("/static/manifest.json")
    assert m.status_code == 200
    man = m.json()
    assert man["start_url"] == "/" and man["display"] == "standalone"
    for icon in man["icons"]:
        assert icon["src"] in PUBLIC_PATHS and c.get(icon["src"]).status_code == 200
    assert c.get("/static/apple-touch-icon.png").status_code == 200
    assert c.get("/static/app.js", follow_redirects=False).status_code in (302, 307)   # the rest still needs the login
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    assert 'rel="manifest" href="/static/manifest.json"' in html and 'rel="apple-touch-icon"' in html
    for f in os.listdir(STATIC):
        if f.endswith(".js"):
            assert "serviceWorker" not in open(os.path.join(STATIC, f), encoding="utf-8").read(), f


def test_analysis_tab_is_on_the_page(env):
    html = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read()
    assert 'data-v="analysis"' in html and 'id="v-analysis"' in html and "/static/analysis.js" in html
    for t in ("health", "risk", "ready", "shock", "map", "entry", "synergy", "questions", "alerts"):
        assert f'data-t="{t}"' in html, t
    assert 'id="debate-body"' in html and "24시간 토론방" in html
    js = open(os.path.join(STATIC, "analysis.js"), encoding="utf-8").read()
    assert "/api/analysis/" in js and "/api/debate" in js and "표본이 적습니다" in js


def test_heavy_answers_an_expired_result_at_once_and_recomputes_in_the_background(monkeypatch):
    """M-6 (review 2026-10-04): risk / shadows / synergy take seconds on a month of data; after the first time no
    viewer waits: an expired result is answered at once (stale) while one background computation refreshes it."""
    import threading
    clock = [1000.0]
    monkeypatch.setattr(AN.time, "time", lambda: clock[0])
    h = AN.Heavy(wait_s=5)
    gate, calls = threading.Event(), []

    def slow():
        calls.append(1)
        if len(calls) > 1:
            gate.wait(5)
        return {"n": len(calls)}
    assert h.get("risk", 60, slow)["n"] == 1                        # the first time: computed in the request
    clock[0] += 61
    t = time.perf_counter()
    got = h.get("risk", 60, slow)
    assert time.perf_counter() - t < 1 and got["n"] == 1 and got["stale"] is True
    assert h.get("risk", 60, slow)["stale"] is True and len(calls) == 2    # one refresh, not two
    gate.set()
    for _ in range(200):
        if (h.peek("risk") or {}).get("n") == 2:
            break
        time.sleep(0.01)
    fresh = h.get("risk", 60, slow)
    assert fresh["n"] == 2 and "stale" not in fresh


def test_shadows_view_is_cached_per_nightly_report(tmp_path):
    d = str(tmp_path / "daily3.db")
    assert AN.report_key(d) == "" and AN.report_key(None) == ""
    c = sqlite3.connect(d)
    c.execute("CREATE TABLE reports (day TEXT PRIMARY KEY, ts INTEGER, data TEXT)")
    c.execute("INSERT INTO reports VALUES ('2026-10-05', 100, '{}')")
    c.commit()
    k1 = AN.report_key(d)
    c.execute("INSERT INTO reports VALUES ('2026-10-06', 200, '{}')")
    c.commit()
    assert k1 == "2026-10-05@100" and AN.report_key(d) == "2026-10-06@200"
    c.execute("INSERT OR REPLACE INTO reports VALUES ('2026-10-05', 300, '{}')")     # a missed night re-run
    c.commit()
    assert AN.report_key(d) == "2026-10-05@300"
