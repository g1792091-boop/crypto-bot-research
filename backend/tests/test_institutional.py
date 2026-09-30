"""풋프린트 · 호가 진입 도구 · 종합 판단 · 세션 특징 · 기관식 포트폴리오."""
import math

from fastapi.testclient import TestClient

from app import orderflow
from app.main import app
from app.quant import footprint, forecast, portfolio

c = TestClient(app)


def test_footprint_conserves_volume_and_finds_imbalance(monkeypatch):
    base = 1_700_000_000 - 1_700_000_000 % 3600
    parents = [{"time": base + h * 3600, "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 60.0, "taker_buy": 40.0} for h in range(6)]
    subs = []
    for h in range(6):
        for m in range(60):
            lo = 99 + (m % 10) * 0.2
            subs.append({"time": base + h * 3600 + m * 60, "open": lo, "high": lo + 0.2, "low": lo, "close": lo + 0.1,
                         "volume": 1.0, "taker_buy": 0.95 if m % 10 >= 7 else 0.5})
    monkeypatch.setattr(footprint.market, "candles", lambda s, iv, n: ((parents if iv == "1h" else subs), "synthetic"))
    f = footprint.footprint("TESTUSDT", "1h", 6)
    b = f["bars"][0]
    assert abs(b["volume"] - 60) < 1e-6 and abs(b["delta"] - (sum(0.95 if m % 10 >= 7 else 0.5 for m in range(60)) * 2 - 60)) < 1e-6
    assert b["imb_buy"] and b["complete"]                     # 윗부분 매수 몰림 → 매수 불균형


def test_footprint_endpoint():
    assert c.get("/api/footprint", params={"symbol": "btc", "interval": "1m"}).status_code == 400
    r = c.get("/api/footprint", params={"symbol": "btc", "interval": "15m", "bars": 20}).json()
    assert len(r["bars"]) == 20 and r["approx"] and "notes" in r["summary"]


def test_orderbook_entry_tools():
    book = {"bids": [[99.9, 10], [99.5, 500], [99.0, 20]], "asks": [[100.1, 10], [100.6, 400], [101.0, 20]], "time": 0}
    sl = orderflow.slippage(book, 100.0, (500, 5000, 10_000_000))
    assert sl[0]["buy"]["avg"] == 100.1 and sl[1]["buy"]["avg"] > 100.1 and sl[2]["buy"] is None   # 호가 부족
    d = orderflow.depth_stats(book, 100.0)
    assert d[0]["pct"] == 0.25 and d[-1]["imbalance"] > 0
    walls = orderflow.find_walls(book, 100.0, span=0.02)
    plan = orderflow.entry_plan(100.0, walls, d, 0.1)
    assert plan["plans"]["long"]["entry"] > 99.5 and plan["plans"]["long"]["stop"] < 99.5 and plan["plans"]["long"]["take"] < 100.6
    ob = c.get("/api/orderbook", params={"symbol": "BTCUSDT"}).json()
    assert {"depth", "slippage", "plan", "pulled", "imbalance_history"} <= set(ob)


def test_wall_tracker_detects_pulled_wall():
    t = orderflow.WallTracker()
    w = [{"price": 95.0, "usd": 1e6, "side": "bid"}]
    t.update("X", w, 100.0, 0.1)
    t.seen["X"][("bid", 95.0)]["first"] -= 30                  # 30초 전부터 있던 벽
    t.update("X", [], 100.0, 0.0)                               # 가격이 닿지 않았는데 사라짐
    assert t.pulled["X"][-1]["price"] == 95.0
    t.update("Y", [{"price": 99.9, "usd": 1e6, "side": "bid"}], 100.0, 0)
    t.seen["Y"][("bid", 99.9)]["first"] -= 30
    t.update("Y", [], 99.9, 0)                                  # 가격이 닿아서 체결된 벽은 허수가 아님
    assert not t.pulled.get("Y")


def test_session_features_and_entry():
    cs = [{"time": 1_700_006_400 + i * 3600, "open": 100 + math.sin(i / 6), "high": 101 + math.sin(i / 6), "low": 99 + math.sin(i / 6),
           "close": 100.2 + math.sin(i / 6), "volume": 10.0, "taker_buy": 6.0} for i in range(120)]
    prof = forecast.session_profiles(cs, [1.0] * len(cs))
    assert prof[0][1] is None and prof[-1][1] is not None and prof[-1][1]["val"] <= prof[-1][1]["poc"] <= prof[-1][1]["vah"]
    assert len(forecast.FEATURES) == 16
    r = c.get("/api/entry", params={"symbol": "eth", "interval": "1h"}).json()
    assert -100 <= r["score"] <= 100 and r["verdict"] in ("long", "short", "wait") and len(r["parts"]) >= 4
    assert abs(sum(p["contrib"] for p in r["parts"]) - r["score"]) <= len(r["parts"])
    nb = c.get("/api/forecast", params={"symbol": "btc", "interval": "1h"}).json()["next_bar"]
    assert nb["evidence"] and "poc" in nb["session"]


def test_optimizer_constraints_and_oos():
    r = c.post("/api/portfolio/optimize", json={"symbols": ["btc", "eth", "sol", "xrp", "bnb"], "max_weight": 0.3}).json()
    assert {x["method"] for x in r["results"]} == set(portfolio.METHODS)
    for x in r["results"]:
        w = x["weights"].values()
        assert abs(sum(w) - 1) < 1e-3 and max(w) <= 0.3 + 1e-6 and min(w) >= -1e-9
        assert "sharpe" in x["test"] and abs(sum(x["risk_contrib"].values()) - 1) < 1e-3
    rp = next(x for x in r["results"] if x["method"] == "risk_parity")["risk_contrib"].values()
    assert max(rp) - min(rp) < 0.12                                           # 위험 기여가 대체로 고름
    assert len(r["cloud"]) == 1200


def test_stress_exposure_tearsheet():
    s = c.post("/api/portfolio/stress", json={"weights": {"btc": 0.5, "eth": -0.5}, "equity": 10000}).json()
    names = [x["name"] for x in s["scenarios"]]
    assert any("FTX" in n for n in names) and any("루나" in n for n in names) and len(names) == 9
    corr1 = next(x for x in s["scenarios"] if x["key"] == "corr1")
    assert corr1["pnl"] == 0                                                  # 롱·숏 같은 금액 → 전부 −15% 면 0
    c.post("/api/paper/order", json={"symbol": "ETHUSDT", "side": "long", "margin": 1000, "leverage": 5})
    ex = c.get("/api/portfolio/exposure").json()
    assert ex["rows"][0]["symbol"] == "ETHUSDT" and ex["gross"] > 0
    c.post("/api/paper/close/ETHUSDT")
    ts = c.post("/api/portfolio/tearsheet", json={"source": "paper"}).json()
    assert ts["stats"]["trades"] >= 1 and ts["stats"]["cagr_pct"] is None      # 30일 미만은 연율화 안 함
    trades = [{"entry_time": 1_700_000_000 + i * 86400, "exit_time": 1_700_000_000 + i * 86400 + 3600, "pnl": (50 if i % 3 else -40),
               "side": "long", "symbol": "BTCUSDT"} for i in range(60)]
    ts = portfolio.tearsheet(trades, 10_000)
    assert ts["stats"]["trades"] == 60 and ts["stats"]["win_rate_pct"] == 66.7 and ts["stats"]["cagr_pct"] is not None
    assert sum(len(m) for m in ts["monthly"].values()) >= 2 and ts["by_side"][0]["trades"] == 60
