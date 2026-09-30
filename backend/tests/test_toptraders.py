"""고수 포지션(Hyperliquid 상위 트레이더) · 바이낸스 상위 트레이더 롱/숏 비율."""
from fastapi.testclient import TestClient

from app import config
from app.data import hyperliquid
from app.main import app
from app.quant import toptraders

c = TestClient(app)


def test_to_symbol():
    assert hyperliquid.to_symbol("BTC") == "BTCUSDT"
    assert hyperliquid.to_symbol("kPEPE") == "1000PEPEUSDT"
    assert hyperliquid.to_symbol("sol") == "SOLUSDT"


def test_parse_perf_and_positions():
    row = {"windowPerformances": [["day", {"pnl": "10", "roi": "0.01", "vlm": "5"}], ["month", {"pnl": "1000", "roi": "0.5", "vlm": "9"}]]}
    pf = toptraders._perf(row)
    assert pf["month"]["pnl"] == 1000 and pf["day"]["roi"] == 0.01
    st = {"assetPositions": [
        {"type": "oneWay", "position": {"coin": "ETH", "szi": "-2.5", "entryPx": "3000", "positionValue": "7400",
                                        "leverage": {"type": "cross", "value": 20}, "liquidationPx": "3100", "unrealizedPnl": "100",
                                        "returnOnEquity": "0.27"}},
        {"position": {"coin": "BTC", "szi": "0", "entryPx": "1"}},                       # 빈 포지션은 제외
        {"position": {"coin": "kPEPE", "szi": "1000", "entryPx": "0.01", "positionValue": "11",
                      "leverage": {"type": "isolated", "value": 5}, "liquidationPx": None, "unrealizedPnl": "1"}}]}
    ps = toptraders._positions(st)
    assert len(ps) == 2
    eth, pepe = ps
    assert eth["side"] == "short" and eth["size"] == 2.5 and eth["leverage"] == 20 and eth["margin_type"] == "cross"
    assert eth["liq"] == 3100 and round(eth["roe_pct"]) == 27
    assert pepe["symbol"] == "1000PEPEUSDT" and pepe["side"] == "long" and pepe["liq"] is None


def test_synthetic_endpoint_aggregates_by_coin():
    r = c.get("/api/toptraders", params={"window": "week", "n": 10}).json()
    assert r["source"] == "synthetic" and r["window_name"] == "7일" and len(r["traders"]) == 10
    for t in r["traders"]:
        assert t["positions"] and t["gross_leverage"] > 0
        for p in t["positions"]:
            assert p["side"] in ("long", "short") and p["leverage"] >= 1
    tot = sum(len(t["positions"]) for t in r["traders"])
    assert sum(x["long"]["traders"] + x["short"]["traders"] for x in r["by_coin"]) == tot
    for x in r["by_coin"]:
        assert x["bias"] in ("long", "short", "mixed") and 0 <= x["long_share"] <= 100


def test_live_path_with_mocked_hyperliquid(monkeypatch):
    rows = [
        {"ethAddress": "0xa", "accountValue": "500000", "displayName": "whale",
         "windowPerformances": [["month", {"pnl": "90000", "roi": "0.2", "vlm": "1"}]]},
        {"ethAddress": "0xb", "accountValue": "300000", "displayName": None,
         "windowPerformances": [["month", {"pnl": "-5000", "roi": "-0.1", "vlm": "1"}]]},   # 손실 → 제외
        {"ethAddress": "0xc", "accountValue": "5000", "displayName": None,
         "windowPerformances": [["month", {"pnl": "4000", "roi": "4", "vlm": "1"}]]},       # 계좌 작음 → 제외
    ]
    acc = {"assetPositions": [{"position": {"coin": "BTC", "szi": "1", "entryPx": "60000", "positionValue": "61000",
                                            "leverage": {"type": "cross", "value": 10}, "liquidationPx": "55000",
                                            "unrealizedPnl": "1000", "returnOnEquity": "0.16"}}]}
    monkeypatch.setattr(config, "DATA_SOURCE", "auto")
    monkeypatch.setattr(toptraders, "_lb", None)
    monkeypatch.setattr(toptraders, "_acc", {})
    monkeypatch.setattr(hyperliquid, "leaderboard", lambda: rows)
    monkeypatch.setattr(hyperliquid, "account", lambda a: acc)
    r = toptraders.top_traders("month", 30, "pnl", 100_000)
    assert r["source"] == "hyperliquid" and r["error"] is None
    assert [t["address"] for t in r["traders"]] == ["0xa"]
    btc = r["by_coin"][0]
    assert btc["symbol"] == "BTCUSDT" and btc["long"]["traders"] == 1 and btc["long"]["avg_leverage"] == 10 and btc["bias"] == "long"


def test_live_failure_returns_error_in_auto(monkeypatch):
    def boom():
        raise RuntimeError("blocked")
    monkeypatch.setattr(config, "DATA_SOURCE", "auto")
    monkeypatch.setattr(toptraders, "_lb", None)
    monkeypatch.setattr(hyperliquid, "leaderboard", boom)
    r = toptraders.top_traders()
    assert r["traders"] == [] and "Hyperliquid" in r["error"]


def test_binance_ratio_endpoint():
    r = c.get("/api/toptraders/binance", params={"symbol": "ETHUSDT", "interval": "1h"}).json()
    assert r["symbol"] == "ETHUSDT" and len(r["position"]) == 100 and len(r["account"]) == 100
    x = r["position"][-1]
    assert abs(x["long"] + x["short"] - 1) < 1e-3 and x["ratio"] > 0
