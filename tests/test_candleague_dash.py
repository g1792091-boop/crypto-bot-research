"""candleague/dash.py: nothing without a session, a wrong password refused, a cross-site login refused, the
snapshots served read-only, a missing file shown as 준비 중; the 터미널's live routes (fake mode) whitelisted and behind
the login, the fills feed newest first over every account."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from candleague import dash as D  # noqa: E402
from candleague.live import Live  # noqa: E402

FORM = {"content-type": "application/x-www-form-urlencoded", "origin": "http://league.test"}


def _client(snap):
    return TestClient(D.create_app(str(snap), D.hash_password("pw-123"), b"x" * 32, live=Live(mode="fake")),
                      base_url="http://league.test")


def test_login_and_read_only_views(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    c = _client(snap)
    assert c.get("/api/league").status_code == 401
    assert c.get("/", follow_redirects=False).status_code == 303
    assert c.get("/static/js/app.js").status_code == 404                   # the app script needs a session too
    r = c.post("/login", content="password=nope", follow_redirects=False,
               headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.headers["location"] == "/login?bad=1"
    r = c.post("/login", content="password=pw-123", follow_redirects=False,
               headers={"content-type": "application/x-www-form-urlencoded", "origin": "http://evil.test"})
    assert r.status_code == 403
    r = c.post("/login", content="password=pw-123", follow_redirects=False,
               headers={"content-type": "application/x-www-form-urlencoded", "origin": "http://league.test"})
    assert r.status_code == 303 and D.COOKIE in r.cookies
    assert c.get("/api/league").json() == {"status": "준비 중"}
    (snap / "league.json").write_text(json.dumps({"accounts": [], "x": float("nan")}).replace("NaN", "NaN"))
    (snap / "trades.json").write_text(json.dumps({"a1": {"equity": [[1, 5000.0]], "trades": []}}))
    assert c.get("/api/league").json() == {"accounts": [], "x": None}
    assert c.get("/api/trades/a1").json()["equity"] == [[1, 5000.0]]
    assert c.get("/api/trades/nope").json() == {"equity": None, "trades": []}
    assert c.get("/static/js/app.js").status_code == 200
    assert "frame-ancestors 'none'" in c.get("/").headers["content-security-policy"]
    assert sorted(os.listdir(snap)) == ["league.json", "trades.json"]      # nothing written


def test_session_token():
    s = b"k" * 32
    t = D.make_token(s, now=1000.0)
    assert D.token_ok(s, t, now=1001.0) and not D.token_ok(s, t, now=1000.0 + D.SESSION_S + 1)
    assert not D.token_ok(b"other" * 8, t, now=1001.0) and not D.token_ok(s, "1.abc")


def test_terminal_routes(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    c = _client(snap)
    vendor = "/static/vendor/lightweight-charts.standalone.production.js"
    for url in ("/api/live", "/api/klines?coin=BTCUSD&tf=15m&limit=300", "/api/fills", "/api/positions", "/api/sparks",
                "/api/pnl"):
        assert c.get(url).status_code == 401, url
    assert c.get(vendor).status_code == 404                                 # the chart file needs a session too
    assert c.get("/static/tokens.css").status_code == 200                   # the login page's look does not
    assert c.post("/login", content="password=pw-123", follow_redirects=False, headers=FORM).status_code == 303
    assert c.get(vendor).status_code == 200
    assert c.get("/static/../dash.py").status_code == 404 and c.get("/static/index.html").status_code == 404
    live = c.get("/api/live").json()
    assert [r["coin"] for r in live["coins"]] == ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD"]
    k = c.get("/api/klines?coin=ETHUSD&tf=1h&limit=120").json()
    assert k["coin"] == "ETHUSD" and len(k["bars"]["t"]) == 120 and set(k["bars"]) == {"t", "o", "h", "l", "c", "v"}
    for bad in ("coin=XRPUSD&tf=15m", "coin=BTCUSD&tf=3m", "coin=BTCUSD&tf=15m&limit=10",
                "coin=BTCUSD&tf=15m&limit=2000", "coin=BTCUSD&tf=15m&limit=x", "tf=15m"):
        assert c.get(f"/api/klines?{bad}").status_code == 400, bad
    assert c.get("/api/fills").json() == {"fills": []}
    def t(ms):
        return {"symbol": "BTCUSDT", "side": 1, "exit_time": ms, "pnl": 1.0}
    (snap / "trades.json").write_text(json.dumps({"a1": {"equity": None, "trades": [t(3), t(1)]},
                                                  "a2": {"equity": None, "trades": [t(2)]}}))
    rows = c.get("/api/fills").json()["fills"]
    assert [(r["account"], r["exit_time"]) for r in rows] == [("a1", 3), ("a2", 2), ("a1", 1)]
    h = c.get("/").headers
    assert "script-src 'self';" in h["content-security-policy"] and h["referrer-policy"] == "same-origin"


def test_static_kit_and_meta(tmp_path):
    """Every screen module and stylesheet is served after login only (the login page's own four files before), nothing
    outside static/ or of another type; /api/meta gives the Korean names and parameter meanings behind the login."""
    snap = tmp_path / "snap"
    snap.mkdir()
    c = _client(snap)
    for f in ("tokens.css", "base.css", "login.css", "login.js", "icon.svg"):
        assert c.get(f"/static/{f}").status_code == 200, f
    assert c.get("/static/cl.css").status_code == 404 and c.get("/api/meta").status_code == 401
    assert c.post("/login", content="password=pw-123", follow_redirects=False, headers=FORM).status_code == 303
    for f in ("cl.css", "nav.css", "kit.css", "js/app.js", "js/lk.js", "js/live.js", "js/poskit.js", "js/find.js",
              "js/settings.js", "js/screens/home.js", "js/screens/check.js", "js/screens/terminal.js"):
        r = c.get(f"/static/{f}")
        assert r.status_code == 200 and r.headers["content-type"].split(";")[0] in ("text/css", "text/javascript"), f
    for bad in ("/static/js/../../dash.py", "/static/login.html", "/static/index.html", "/static/js/nope.js"):
        assert c.get(bad).status_code == 404, bad
    m = c.get("/api/meta").json()
    assert len(m["strategies"]) == 16 and len(m["picks"]) == 38
    assert m["strategies"]["DOGE"]["ko"] == "도지 봇" and m["strategies"]["F5_BOX"]["kind"] == "ds"
    assert c.get("/favicon.ico").status_code == 200


def test_page_never_parses_html_and_every_screen_exists():
    """Text reaches the page as text nodes only (dom.js h()); every menu route has its screen module; the index page loads
    only files the server serves."""
    import re
    root = os.path.join(ROOT, "candleague", "static")
    js = []
    for d, _dirs, files in os.walk(os.path.join(root, "js")):
        js += [os.path.join(d, f) for f in files if f.endswith(".js")]
    for f in js:
        src = open(f).read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval("):
            assert bad not in src, (f, bad)
        assert "binance.com" not in src, f                      # the browser never talks to Binance
    app = open(os.path.join(root, "js", "app.js")).read()
    screens = re.search(r"const SCREENS = \{([^}]*)\}", app).group(1)
    for name in re.findall(r':\s*"([a-z]+)"', screens):
        assert os.path.exists(os.path.join(root, "js", "screens", f"{name}.js")), name
    index = open(os.path.join(root, "index.html")).read()
    for ref in re.findall(r'(?:href|src)="/static/([^"]+)"', index):
        assert ref in D.STATIC_FILES, ref


def test_no_password_only_on_tailscale_or_loopback(tmp_path, monkeypatch):
    """CANDLEAGUE_DASH_OPEN=1 (setup_env.sh --no-password, owners 2026-10-11) serves without the login, but only on a
    Tailscale (100.64.0.0/10) or loopback address; anything else keeps the login."""
    assert D.open_ok("100.125.1.57") and D.open_ok("100.64.0.1") and D.open_ok("127.0.0.1")
    for bad in ("100.63.0.1", "100.128.0.1", "158.247.200.152", "0.0.0.0", "", "localhost", "::"):
        assert not D.open_ok(bad), bad
    snap = tmp_path / "snap"
    snap.mkdir()
    c = TestClient(D.create_app(str(snap), "", b"x" * 32, live=Live(mode="fake"), open_=True), base_url="http://league.test")
    assert c.get("/api/league").json() == {"status": "준비 중"} and c.get("/static/js/app.js").status_code == 200
    assert c.get("/login", follow_redirects=False).headers["location"] == "/"
    assert c.get("/").headers.get("cache-control") == "no-cache"     # after an update the browser asks again
    seen = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: seen.update(kw, app=app))
    for host, opened in (("100.125.1.57", True), ("158.247.200.152", False)):
        monkeypatch.setenv("CANDLEAGUE_DASH_HOST", host)
        monkeypatch.setenv("CANDLEAGUE_DASH_OPEN", "1")
        monkeypatch.setenv("CANDLEAGUE_DASH_SECRET", "s" * 40)
        monkeypatch.setenv("CANDLEAGUE_DASH_PASSWORD_HASH", D.hash_password("pw-123", rounds=1000))
        monkeypatch.setenv("CANDLEAGUE_SNAP", str(snap))
        monkeypatch.setenv("CANDLEAGUE_DASH_LIVE", "off")
        assert D.main([]) == 0
        code = TestClient(seen["app"], base_url=f"http://{host}:8091").get("/api/league").status_code
        assert (code == 200) is opened, host
    # without the password only requests addressed to the dashboard itself are answered (no DNS rebinding)
    monkeypatch.setenv("CANDLEAGUE_DASH_HOST", "100.125.1.57")
    assert D.main([]) == 0
    for base, ok in (("http://100.125.1.57:8091", True), ("http://localhost:8091", True), ("http://evil.example:8091", False),
                     ("http://100.125.1.57.evil.example:8091", False)):
        r = TestClient(seen["app"], base_url=base).get("/api/league")
        assert (r.status_code == 200) is ok, base
    assert D.host_ok("[::1]:8091", {"::1"}) and not D.host_ok("", {"100.125.1.57"})


def test_every_module_parses_as_an_es_module():
    """A syntax error in one screen breaks only that screen in the browser, so catch it here (node, when installed)."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        return
    root = os.path.join(ROOT, "candleague", "static", "js")
    for d, _dirs, files in os.walk(root):
        for f in files:
            if f.endswith(".js") and f != "skin-boot.js":
                with open(os.path.join(d, f)) as fh:
                    r = subprocess.run([node, "--input-type=module", "--check"], stdin=fh, capture_output=True, text=True)
                assert r.returncode == 0, (f, r.stderr[:400])


def test_confirmed_checkpoints_after_their_date(tmp_path, monkeypatch):
    """/api/checkpoints: nothing before the first date; after it, the same numbers as watch_check / checkpoint.check."""
    snap = tmp_path / "snap"
    snap.mkdir()
    c = _client(snap)
    assert c.post("/login", content="password=pw-123", follow_redirects=False, headers=FORM).status_code == 303
    accts = [{"id": "c1", "role": "cand", "kind": "core", "name": "S2_ST_ROC", "tf": "15m"},
             {"id": "base-core-S2_ST_ROC-15m", "role": "base", "kind": "core", "name": "S2_ST_ROC", "tf": "15m"},
             {"id": "c1-flip", "role": "flip", "kind": "core", "name": "S2_ST_ROC", "tf": "15m"}]
    t0 = 1_790_812_800_000
    eq = {"c1": [[t0, 5000.0], [t0 + 86_400_000, 5100.0]], "base-core-S2_ST_ROC-15m": [[t0, 5000.0], [t0 + 86_400_000, 4990.0]],
          "c1-flip": [[t0, 5000.0], [t0 + 86_400_000, 4900.0]]}
    (snap / "league.json").write_text(json.dumps({"accounts": accts, "done_ms": 1_800_000_000_000}))
    (snap / "trades.json").write_text(json.dumps({k: {"equity": v, "trades": []} for k, v in eq.items()}))
    monkeypatch.setattr(D.time, "gmtime", lambda *a: __import__("time").struct_time((2026, 11, 1, 0, 0, 0, 6, 305, 0)))
    assert c.get("/api/checkpoints").json() == {"due": [], "results": {}}
    monkeypatch.setattr(D.time, "gmtime", lambda *a: __import__("time").struct_time((2026, 11, 12, 0, 0, 0, 3, 316, 0)))
    r = c.get("/api/checkpoints").json()
    assert r["due"] == ["2026-11-11"] and r["results"]["2026-11-11"]["final"] is True
    pool = r["results"]["2026-11-11"]["pools"]["core"]
    assert pool["c1_stop"] is False and pool["roles"]["cand"]["n"] == 1 and abs(pool["roles"]["cand"]["mean"] - 0.02) < 1e-9


def test_trades_file_is_read_again_when_it_changes(tmp_path):
    """trades.json is parsed once per change and shared by /api/trades, /api/fills and /api/checkpoints."""
    snap = tmp_path / "snap"
    snap.mkdir()
    c = TestClient(D.create_app(str(snap), "", b"x" * 32, live=Live(mode="fake"), open_=True), base_url="http://league.test")
    assert c.get("/api/trades/a").json() == {"equity": None, "trades": []}
    t1 = {"exit_time": 1, "pnl": 1.0}
    (snap / "trades.json").write_text(json.dumps({"a": {"equity": [[0, 5000]], "trades": [t1]}}))
    assert c.get("/api/trades/a").json()["trades"] == [t1]
    t2 = {"exit_time": 2, "pnl": -2.5}
    (snap / "trades.json").write_text(json.dumps({"a": {"equity": [[0, 5000]], "trades": [t2, t1]}, "b": {"trades": []}}))
    os.utime(snap / "trades.json", ns=(10**18, 10**18))
    assert c.get("/api/trades/a").json()["trades"] == [t2, t1]
    assert [f["exit_time"] for f in c.get("/api/fills").json()["fills"]] == [2, 1]


def test_klines_before_a_past_entry():
    """The 진입 차트 asks for the bars before a past entry: ``end`` is whitelisted, rounded up to 24 bars (one cached
    answer serves nearby entries), refused before the league's first day, and dropped when it is in the future; the
    Binance request carries endTime and fake mode cuts its bars there."""
    now = 1_791_636_000_000
    q = D.klines_query({"coin": "BTCUSD", "tf": "15m", "limit": "150", "end": "1791436000000"}, now_ms=now)
    assert q["end"] == 1_791_439_200_000 and q["end"] % (900_000 * 24) == 0 and q["end"] >= 1_791_436_000_000
    assert D.klines_query({"coin": "BTCUSD", "tf": "15m", "limit": "150", "end": str(now - 1000)}, now_ms=now)["end"] is None
    for bad in ("1000", "x", "1.5e12", str(D.KLINE_END_MIN - 1)):          # before 2026-10-01: refused
        assert D.klines_query({"coin": "BTCUSD", "tf": "15m", "limit": "150", "end": bad}, now_ms=now) is None, bad
    seen = []

    def fetch(path, params):
        seen.append(params)
        return [[1_791_436_000_000 - 900_000 * i, "1", "2", "0.5", "1.5", "10"] for i in range(3, 0, -1)]
    lv = Live(mode="on", fetch=fetch)
    k = lv.klines("BTCUSD", "15m", 150, 1_791_439_200_000)
    assert seen[-1]["endTime"] == 1_791_439_199_999 and k["end"] == 1_791_439_200_000 and len(k["bars"]["t"]) == 3
    lv.klines("BTCUSD", "15m", 150)
    assert "endTime" not in seen[-1]
    fk = Live(mode="fake", clock=lambda: now / 1000).klines("ETHUSD", "1h", 120, 1_791_504_000_000)
    assert len(fk["bars"]["t"]) == 120 and max(fk["bars"]["t"]) < 1_791_504_000_000


def test_shell_menu_header_and_screen_hooks():
    """The rule bot's shell: the menu in groups 거래 | 홈 | 분석 | 매매법 | 안내 (two levels on top: the group tabs, then only the current group's screens) with every screen a text button (터미널 first), the
    phone's bottom bar, 찾기 (/), 설정 (,), the day pill and 모의 in the top bar; a screen module may bring its own css and
    ask for the full width; the three live screens are routed."""
    import re
    root = os.path.join(ROOT, "candleague", "static")
    app = open(os.path.join(root, "js", "app.js")).read()
    groups = re.findall(r'\{id: "(\w+)", ko: "([^"]+)"\}', re.search(r"const GROUPS = \[(.*?)\];", app, re.S).group(1))
    assert groups == [("trade", "실시간"), ("home", "요약 · 판정"), ("study", "계좌 · 분석"), ("method", "매매법"), ("info", "안내")]
    menu = re.findall(r'\{id: "(\w+)", ko: "([^"]+)", group: "(\w+)"', re.search(r"const MENU = \[(.*?)\];", app, re.S).group(1))
    assert [m[0] for m in menu] == ["terminal", "positions", "charts", "entries", "fills", "events", "home", "decision", "versus", "goal", "monthsim", "check", "rank", "coins", "compare", "pairs", "reasons",
                                    "conditions", "risk", "weekly", "strategies", "judge", "custom", "rules", "dataq", "timeline", "status", "howto"]
    assert [m[2] for m in menu] == sorted([m[2] for m in menu], key=[g[0] for g in groups].index)   # groups stay together
    assert "mod.css" in app and "mod.wide" in app and "onPositions" in app and "onLive" in app
    assert 'innerWidth >= WIDE_PX ? "terminal" : "home"' in app                    # the landing (D-2)
    index = open(os.path.join(root, "index.html")).read()
    for needle in ('id="findbtn"', 'id="botbar"', 'class="dchip cl-day"', ">모의</span>", "/static/nav.css", "/static/kit.css"):
        assert needle in index, needle
    for f in ("nav.css", "kit.css"):
        css = open(os.path.join(root, f)).read()
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsl\(", css), f          # colours only from the tokens
        for m in re.finditer(r"font(?:-size)?:\s*([^;]+);", css):
            assert "var(--t-" in m.group(1) or m.group(1).strip() == "inherit", (f, m.group(0))


def test_position_kit_math():
    """js/poskit.js (node): P&L and ROE at the mark, the distances to the lines, the crowding rule, the totals that leave
    hidden positions out; nothing without a size or a price."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        return
    kit = os.path.join(ROOT, "candleague", "static", "js", "poskit.js")
    code = f"""
import * as K from "file://{kit}";
const p = {{side: 1, qty: 2, entry: 100, margin: 10, liq: 96, stop: 98, stop_is_lock: false, tp: 104, coin: "BTCUSD", hidden: false}};
const s = {{side: -1, qty: 1, entry: 50, margin: 5, liq: 55, stop: 49, stop_is_lock: true, tp: null, coin: "ETHUSD", hidden: false}};
const hid = {{side: 1, qty: null, entry: null, margin: null, coin: "SOLUSD", hidden: true}};
const out = {{
  a: K.livePnl(p, 101), b: K.livePnl(s, 51), h: K.livePnl(hid, 1), n: K.livePnl(p, null),
  g: [K.gap(1, 100, 95), K.gap(-1, 100, 105), K.gap(1, 100, 101)],
  r: K.roeOf(-1, 30, 100, 99),
  c: [K.crowd({{long: 4, short: 1}}), K.crowd({{long: 1, short: 3}}), K.crowd({{long: 0, short: 0}})],
  t: (({{coins, ...x}}) => x)(K.sums([p, s, hid], (c) => ({{BTCUSD: 101, ETHUSD: 51}})[c] ?? null)),
  ok: [K.liveAllowed({{catching_up: false, old: false}}), K.liveAllowed({{catching_up: true}}), K.liveAllowed({{old: true}}), K.liveAllowed(null)],
  grp: K.POS_GROUPS.map((x) => x.id).join(","), ing: [K.inGroup({{role: "flip", kind: "ds"}}, "ds"), K.inGroup({{role: "flip", kind: "ds"}}, "cand")],
}};
console.log(JSON.stringify(out));
"""
    r = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[:600]
    o = json.loads(r.stdout)
    assert o["a"]["pnl"] == 2 and o["a"]["roe"] == 0.2 and abs(o["a"]["liqGap"] - 5 / 101) < 1e-12
    assert abs(o["a"]["stopGap"] - 3 / 101) < 1e-12 and o["a"]["lockGap"] is None and abs(o["a"]["tpGap"] - 3 / 101) < 1e-12
    assert o["b"]["pnl"] == -1 and o["b"]["roe"] == -0.2 and o["b"]["stopGap"] is None and abs(o["b"]["lockGap"] + 2 / 51) < 1e-12
    assert o["h"] is None and o["n"] is None
    assert o["g"] == [0.05, 0.05, -0.01] and abs(o["r"] - 0.3) < 1e-12
    assert [c["on"] for c in o["c"]] == [True, False, False] and o["c"][0]["side"] == 1
    t = o["t"]
    assert (t["n"], t["long"], t["short"], t["hidden"], t["priced"], t["winning"], t["losing"]) == (3, 2, 1, 1, 2, 1, 1)
    assert t["pnl"] == 1 and t["margin"] == 15 and abs(t["roe"] - 1 / 15) < 1e-12
    assert o["ok"] == [True, False, False, False]
    assert o["grp"] == "all,cand,quarter,exitonly,base,flip,core,ds" and o["ing"] == [True, False]
