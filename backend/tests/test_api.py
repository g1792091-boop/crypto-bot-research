from fastapi.testclient import TestClient

from app.main import app


def test_end_to_end_flow():
    with TestClient(app) as c:
        st = c.get("/api/status").json()
        assert st["llm"] is False and "rsi" in st["indicators"]

        r = c.post("/api/strategy/auto", json={"text": "비트 4시간봉 MACD 골든크로스, 손절 3% 익절 6% 3배",
                                               "bars": 800, "start_paper": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["engine"] == "rules" and body["data_source"] == "synthetic"
        assert "total_return_pct" in body["metrics"]
        bot_id = body["paper_bot"]["id"]
        assert any(b["id"] == bot_id for b in c.get("/api/paper/bots").json())
        assert c.post(f"/api/paper/bots/{bot_id}/pause").json()["ok"]

        acct = c.post("/api/paper/order", json={"symbol": "BTCUSDT", "side": "long", "margin": 1000,
                                                 "leverage": 5, "stop_loss_pct": 2}).json()
        assert len(acct["positions"]) == 1
        acct = c.post("/api/paper/close/BTCUSDT").json()
        assert acct["positions"] == [] and len(acct["trades"]) == 1

        team = c.post("/api/agents/run", json={"symbol": "BTCUSDT"}).json()
        assert team["engine"] == "rules"
        assert set(team["reports"]) == {"technical", "derivatives", "news"}
        assert team["decision"]["action"] in ("long", "short", "stay_flat")

        assert c.get("/").status_code == 200


def test_backtest_with_missing_derivatives_warns_instead_of_failing():
    spec = {
        "name": "readme", "symbol": "BTCUSDT", "interval": "1h",
        "indicators": [{"id": "fast", "type": "ema", "length": 20}, {"id": "slow", "type": "ema", "length": 50},
                       {"id": "m", "type": "macd"}],
        "long_entry": {"logic": "all", "conditions": [
            {"left": "fast", "op": "crosses_above", "right": "slow"},
            {"left": "m.hist", "op": "rising", "right": "2"},
            {"left": "funding", "op": "<", "right": "0.01"}]},
        "short_entry": {"logic": "all", "conditions": [{"left": "fast", "op": "crosses_below", "right": "slow"}]},
    }
    with TestClient(app) as c:
        r = c.post("/api/backtest", json={"spec": spec, "bars": 600})
        assert r.status_code == 200, r.text
        body = r.json()
        assert any("funding" in w for w in body["warnings"])
        assert body["metrics"]["long_trades"] == 0  # 펀딩 데이터가 없으니 롱 조건은 거짓
