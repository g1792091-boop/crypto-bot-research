"""candleague/dash.py: nothing without a session, a wrong password refused, a cross-site login refused, the
snapshots served read-only, a missing file shown as 준비 중."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

from candleague import dash as D  # noqa: E402


def _client(snap):
    return TestClient(D.create_app(str(snap), D.hash_password("pw-123"), b"x" * 32), base_url="http://league.test")


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
