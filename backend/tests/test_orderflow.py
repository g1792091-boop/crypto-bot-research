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


def test_sr_levels_find_repeated_zone_and_trendline():
    import math
    from app import analysis
    # 100 근처에서 여러 번 막히는 박스 + 마지막 구간 하락 고점
    c = []
    for i in range(300):
        p = 95 + 5 * math.sin(i / 8)
        c.append({"time": i * 3600, "open": p, "high": min(100.2, p + 0.6), "low": p - 0.6, "close": p, "volume": 1})
    r = analysis.sr_levels(c)
    res = [z for z in r["zones"] if z["side"] == "resistance"]
    assert res and abs(res[0]["price"] - 100.2) < 1.0 and res[0]["touches"] >= 3


def test_modify_position_validates_and_updates():
    with TestClient(app) as c:
        c.post("/api/paper/reset", json={})
        acct = c.post("/api/paper/order", json={"symbol": "BTCUSDT", "side": "long", "margin": 1000, "leverage": 5}).json()
        entry = acct["positions"][0]["entry_price"]
        ok = c.post("/api/paper/position/BTCUSDT", json={"stop": entry * 0.98, "take": entry * 1.05}).json()
        p = ok["positions"][0]
        assert abs(p["stop"] - entry * 0.98) < 1e-6 and abs(p["take"] - entry * 1.05) < 1e-6
        bad = c.post("/api/paper/position/BTCUSDT", json={"stop": entry * 1.02, "take": None})
        assert bad.status_code == 400 and "손절가" in bad.json()["detail"]
        too_far = c.post("/api/paper/position/BTCUSDT", json={"stop": entry * 0.5, "take": None})
        assert too_far.status_code == 400 and "강제청산" in too_far.json()["detail"]
        cleared = c.post("/api/paper/position/BTCUSDT", json={"stop": None, "take": None}).json()
        assert cleared["positions"][0]["stop"] is None
        m = c.get("/api/paper/markers?symbol=BTCUSDT").json()
        assert m["manual"]["position"]["leverage"] == 5
        lv = c.get("/api/levels?symbol=BTCUSDT&interval=1h").json()
        assert "zones" in lv and "trendlines" in lv
        c.post("/api/paper/close/BTCUSDT")
