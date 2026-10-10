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
    assert c.get("/static/app.js").status_code == 404                      # the app script needs a session too
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
    assert c.get("/static/app.js").status_code == 200
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
    assert c.get("/static/league.css").status_code == 200                   # the login page's look does not
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
