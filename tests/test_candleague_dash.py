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
    for url in ("/api/live", "/api/klines?coin=BTCUSD&tf=15m&limit=300", "/api/fills"):
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
    for bad in ("coin=XRPUSD&tf=15m", "coin=BTCUSD&tf=5m", "coin=BTCUSD&tf=15m&limit=10",
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
    for f in ("cl.css", "js/app.js", "js/lk.js", "js/screens/home.js", "js/screens/check.js", "js/screens/terminal.js"):
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
