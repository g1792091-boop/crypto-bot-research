"""시장 강제청산 › 전체 시장 (owners 10/06 13:23: the terminal's box stood almost empty with only BTC): symbol=ALL
reads every coin the recorder keeps, newest first, with the coin on each row; totals of the window; bounded scan."""
import os
import sqlite3
import time

from fastapi.testclient import TestClient

from paperbot import liqstream
from paperbot.dash.app import Data, create_app, hash_password
from tests.test_dash import SECRET, _store

PW = "correct horse battery"
V4 = os.path.join(os.path.dirname(__file__), "..", "paperbot", "dash", "static", "v4")


def _liq(path, rows):
    q = sqlite3.connect(path)
    q.executescript(liqstream.SCHEMA)
    for sym, ts, side, px, qty in rows:
        q.execute("INSERT INTO liq VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (ts, ts, sym, side, "LIMIT", "IOC", qty, px, px, "FILLED", qty, qty, ts))
    q.commit()
    q.close()


def test_all_coins_newest_first_with_totals(tmp_path):
    db = str(tmp_path / "p.db")
    _store(db).close()
    now = int(time.time() * 1000)
    _liq(str(tmp_path / "liq.db"), [("BTCUSDT", now - 60_000, "SELL", 100.0, 2.0),        # long  $200
                                    ("1000PEPEUSDT", now - 30_000, "BUY", 0.01, 5000.0),  # short $50 (not one of ours)
                                    ("ETHUSDT", now - 10_000, "SELL", 10.0, 3.0),         # long  $30
                                    ("BTCUSDT", now - 7_200_000, "BUY", 90.0, 1.0)])      # outside the hour
    c = TestClient(create_app(db, hash_password(PW), SECRET))
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get("/api/liq", params={"symbol": "ALL", "minutes": 60}).json()
    assert r["recorder"] and r["symbol"] == "ALL" and r["n"] == 3 and not r["capped"]
    assert r["long_usd"] == 230.0 and r["short_usd"] == 50.0
    assert [x["symbol"] for x in r["rows"]] == ["ETHUSDT", "1000PEPEUSDT", "BTCUSDT", "BTCUSDT"]   # newest first, every coin
    assert r["rows"][0]["liquidated"] == "long" and r["rows"][1]["liquidated"] == "short"
    one = c.get("/api/liq", params={"symbol": "BTCUSDT", "minutes": 60}).json()          # the one-coin view is unchanged
    assert one["n"] == 1 and all("symbol" not in x for x in one["rows"])
    assert c.get("/api/liq", params={"symbol": "NOPE"}).status_code == 400


def test_the_scan_is_bounded_and_says_so(tmp_path, monkeypatch):
    now = int(time.time() * 1000)
    path = str(tmp_path / "liq.db")
    _liq(path, [("BTCUSDT", now - 50_000 + i, "SELL", 1.0, 1.0) for i in range(30)])
    monkeypatch.setattr(Data, "MARKET_SCAN", 10)
    d = Data.__new__(Data).liquidations_market(path, 60, now_ms=now)
    assert d["n"] == 10 and d["capped"] is True                  # only the newest 10 rows read, and it says so
    assert Data.__new__(Data).liquidations_market(str(tmp_path / "none.db"), 60)["recorder"] is False


def test_the_panel_has_both_views_and_flashes_only_the_chosen_coin():
    js = open(os.path.join(V4, "screens", "terminal-feed.js"), encoding="utf-8").read()
    assert "symbol=${encodeURIComponent(wantKey)}" in js and '"ALL"' in js
    assert '["all", "전체", "전체 시장 (모든 코인)"]' in js and 'local.get("term-liq-mode", "all")' in js
    assert "if (isNew && mine) arrived.push(r);" in js                                    # chart flash: chosen coin only
    css = open(os.path.join(V4, "screens", "terminal.css"), encoding="utf-8").read()
    assert ".term-fr.liq.anyc" in css and ".term-fr.liq.mine" in css
