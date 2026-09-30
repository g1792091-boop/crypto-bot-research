import math

from fastapi.testclient import TestClient

from app import analysis, liquidation
from app.data import market, news
from app.main import app


def _mk(f, n=400):
    return [{"time": i * 3600, "open": f(i - 1), "high": max(f(i), f(i - 1)) * 1.002,
             "low": min(f(i), f(i - 1)) * 0.998, "close": f(i), "volume": 1000} for i in range(1, n)]


def test_regime_classifies_trend_and_range():
    assert analysis.regime(_mk(lambda i: 100 * 1.003 ** i))["state"] == "long"
    assert analysis.regime(_mk(lambda i: 100 * 0.997 ** i))["state"] == "short"
    assert analysis.regime(_mk(lambda i: 100 + 2 * math.sin(i / 6)))["state"] == "range"


def test_scenarios_have_consistent_levels():
    c = _mk(lambda i: 100 + 3 * math.sin(i / 15) + i * 0.01)
    reg = analysis.regime(c)
    out = analysis.scenarios(c, reg)
    assert abs(sum(s["probability"] for s in out["scenarios"]) - 100) <= 2
    for s in out["scenarios"]:
        side = -1 if s["bias"] == "short" else 1
        assert side * (s["entry"] - s["stop"]) > 0            # 손절은 진입 반대편
        assert side * (s["targets"][0] - s["entry"]) > 0      # 목표는 진입 방향
        assert s["rr"] is None or s["rr"] >= 0.99             # 최소 1R


def test_liquidation_estimate_places_longs_below_shorts_above():
    c = _mk(lambda i: 100 + 5 * math.sin(i / 20))
    r = liquidation.estimate(c)
    last = c[-1]["close"]
    assert r["columns"] and r["max_value"] > 0
    assert all(z["price"] > last for z in r["clusters_above"])
    assert all(z["price"] < last for z in r["clusters_below"])


def test_liquidation_levels_are_wiped_when_price_crosses():
    flat = [{"time": i, "open": 100, "high": 100.1, "low": 99.9, "close": 100, "volume": 10} for i in range(5)]
    # 5% 급락 봉: 25배 이상 롱 청산가(약 96~99.5)는 모두 지나감
    crash = flat + [{"time": 5, "open": 100, "high": 100, "low": 95, "close": 95.5, "volume": 0}]
    r = liquidation.estimate(crash, oi=[1000, 1000, 1000, 1000, 1000, 1000])
    lo, step = r["price_min"], r["price_step"]
    last_col = dict(r["columns"][-1][1])
    assert not any(95 <= lo + (i + 0.5) * step <= 100 for i in last_col if i in last_col and last_col[i] > 0)


def test_yearly_aggregation():
    m = [{"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}
         for t, o, h, l, c in [(1672531200, 1, 5, 1, 2), (1675209600, 2, 9, 2, 3), (1704067200, 3, 4, 0.5, 1)]]
    y = market._yearly(m)
    assert [(b["time"], b["open"], b["high"], b["low"], b["close"]) for b in y] == [
        (1672531200, 1, 9, 1, 3), (1704067200, 3, 4, 0.5, 1)]


def test_news_rss_parsing_and_tags():
    xml = """<rss><channel>
      <item><title>BREAKING: SEC approves spot ETH ETF</title><link>https://x/1</link>
        <pubDate>Tue, 29 Sep 2026 10:00:00 GMT</pubDate></item>
      <item><title>비트코인 급락, 청산 1조원</title><link>https://x/2</link></item>
      <item><title>Miners publish monthly report</title><link>https://x/3</link></item>
    </channel></rss>"""
    items = news._parse_rss("t", xml)
    assert items[0]["important"] and "ETF" in items[0]["tags"] and items[0]["time"]
    assert items[1]["lang"] == "ko" and "청산·급변" in items[1]["tags"]
    assert not items[2]["important"]


def test_new_endpoints():
    with TestClient(app) as c:
        st = c.get("/api/status").json()
        assert "1y" in st["intervals"] and "1m" in st["intervals"]
        for iv in ("1m", "1w", "1M", "1y"):
            assert c.get(f"/api/candles?interval={iv}&limit=10").status_code == 200
        assert c.get("/api/candles?interval=7m").status_code == 400
        t = c.get("/api/tickers?symbols=BTCUSDT,ETHUSDT").json()
        assert [x["symbol"] for x in t["items"]] == ["BTCUSDT", "ETHUSDT"]
        a = c.get("/api/analysis?symbol=BTCUSDT&interval=4h").json()
        assert a["regime"]["label"] in ("롱 우위", "숏 우위", "횡보") and a["scenarios"] and len(a["mtf"]) == 4
        h = c.get("/api/liq-heatmap?symbol=ETHUSDT&interval=15m&limit=200").json()
        assert len(h["columns"]) == 200 and h["model"].startswith("estimate")
        assert c.get("/api/news/brief").status_code == 400  # 키 없음
