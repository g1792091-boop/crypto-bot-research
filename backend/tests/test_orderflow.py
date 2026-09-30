from fastapi.testclient import TestClient

from app import orderflow
from app.data import exchanges
from app.main import app


def test_group_and_walls():
    book = {"bids": [[100.0 - i * 0.1, 1.0] for i in range(1, 200)],
            "asks": [[100.0 + i * 0.1, 1.0] for i in range(1, 200)]}
    book["asks"][30][1] = 80.0   # 103.1 부근 큰 매도벽
    g = orderflow._group(book["asks"], 1.0, "ask")
    assert g[0]["price"] == 101 and abs(g[0]["qty"] - 10) < 1e-6 and g[1]["cum"] > g[0]["cum"]
    walls = orderflow.find_walls(book, 100.0)
    assert walls and walls[0]["side"] == "ask" and 103 <= walls[0]["price"] <= 103.2


def test_nice_step():
    assert [orderflow.nice_step(x) for x in (0.3, 3, 7, 60)] == [0.5, 5, 10, 100]


def test_exchange_premiums():
    rows = [{"exchange": "바이낸스", "market": "선물", "price": 100.0},
            {"exchange": "바이낸스", "market": "현물", "price": 100.0},
            {"exchange": "바이비트", "market": "선물", "price": 100.5},
            {"exchange": "업비트", "market": "원화", "price_krw": 141_000.0, "volume_krw": 1.0}]
    r = exchanges._finish(rows, {"fx": 1400.0, "usdt_krw": 1414.0}, "t")
    by = {x["exchange"] + x["market"]: x for x in r["rows"]}
    assert abs(by["바이비트선물"]["diff_pct"] - 0.5) < 1e-9
    assert abs(r["kimchi_pct"] - (141_000 / 1400 / 100 - 1) * 100) < 1e-9
    assert abs(r["tether_premium_pct"] - 1.0) < 1e-9


def test_orderflow_endpoints_offline():
    with TestClient(app) as c:
        ob = c.get("/api/orderbook?symbol=ETHUSDT&rows=10").json()
        assert len(ob["bids"]) == 10 and ob["bids"][0]["price"] < ob["asks"][0]["price"]
        w = c.get("/api/whales?symbol=BTCUSDT&interval=15m&limit=200").json()
        assert w["trades"] and all(t["usd"] >= w["min_usd"] for t in w["trades"])
        e = c.get("/api/exchanges?symbol=SOLUSDT").json()
        assert len(e["rows"]) == 8 and e["kimchi_pct"] is not None
        d = c.get("/api/derivatives?symbol=BTCUSDT&interval=1h&limit=50").json()
        assert d["source"] == "synthetic" and len(d["taker"]) == 50
        assert c.get("/api/cg-index/ahr999").status_code == 400
