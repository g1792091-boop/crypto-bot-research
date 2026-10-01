import time

import pytest

from app.data import market
from app.quant import termind


def test_runs_every_terminal_indicator():
    ok, err = termind.available()
    assert ok, err
    c = market.candles("BTCUSDT", "1h", 500)[0]
    res = termind.compute_all(c, {})
    from pathlib import Path
    import re
    src = (Path(__file__).resolve().parents[2] / "frontend" / "js" / "ind.js").read_text(encoding="utf-8")
    keys = set(re.findall(r'^  (\w+): \{ name:', src, re.M)) - {"volume"}
    assert keys <= set(res) and len(keys) >= 140
    assert not [k for k, r in res.items() if r.get("error")]


def test_vote_rules():
    close, atr = 100.0, 2.0
    above = {"pane": "main", "group": "추세", "plots": [{"type": "line", "last": 96.0, "ago": 0}]}
    assert termind.vote("ema", above, close, atr)[0] == 1.0
    sig = {"pane": "main", "group": "신호 · 패턴", "plots": [{"type": "signals", "dir": -1, "ago": 1}]}
    assert termind.vote("ut_bot", sig, close, atr)[0] == -1.0
    rsi = {"pane": "sub", "group": "오실레이터", "levels": [30, 50, 70], "plots": [{"type": "line", "last": 80.0, "ago": 0}]}
    v, t = termind.vote("rsi", rsi, close, atr)
    assert v == 1.0 and t == "ob"
    rsi_low = {**rsi, "plots": [{"type": "line", "last": 25.0, "ago": 0}]}
    assert termind.vote("rsi", rsi_low, close, atr) == (-1.0, "os")
    assert termind.vote("atr", {"pane": "sub", "group": "변동성", "plots": [{"type": "line", "last": 3.0, "ago": 0}]}, close, atr) == (None, None)
    obv = {"pane": "sub", "group": "거래량", "levels": [0], "plots": [{"type": "line", "last": 10.0, "prev5": 5.0, "ago": 0}]}
    assert termind.vote("obv", obv, close, atr)[0] == 1.0


def test_plan_multi_timeframe():
    p = termind.plan("ETHUSDT")
    assert set(p["per_tf"]) == {"15m", "1h", "4h", "1d"} and -100 <= p["trend"] <= 100
    assert all(a["voters"] >= 80 for a in p["per_tf"].values())
    if p["entry"]:
        e = p["entry"]
        assert e["rr"] >= 1.5 and (e["stop"] < e["entry"] < e["take"] if e["action"] == "long" else e["take"] < e["entry"] < e["stop"])
    assert "판정" in termind.text(p)


def test_office_team_scan_and_api(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.office import engine as office
    from app.office import roster, teamjobs
    assert roster.TEAM_BY["termind"]["name"] == "터미널 지표 추세·타점팀" and len(roster.MEMBERS["termind"]) == 11
    monkeypatch.setattr(office, "ai_ok", lambda: False)
    office.load()
    office.LOG.clear()
    teamjobs.TERM.clear()
    p = teamjobs.termind_scan("SOLUSDT")
    assert teamjobs.TERM["SOLUSDT"] is p
    if p["entry"]:
        assert any(e["kind"] == "term" for e in office.LOG)
        from app.quant import copilot
        assert any(s["engine"] == "terminal" and s["symbol"] == "SOLUSDT" for s in copilot.ai_signals)
    assert (office._dir() / "files" / "termind").exists()
    c = TestClient(app)
    d = c.get("/api/office/termind").json()
    assert d["available"] and any(x["symbol"] == "SOLUSDT" for x in d["items"])
    assert c.post("/api/office/termind/scan?symbol=BTCUSDT").json()["symbol"] == "BTCUSDT"
    teamjobs.run_team("termind")
    assert any(e["ch"] == "termind" for e in office.LOG)
