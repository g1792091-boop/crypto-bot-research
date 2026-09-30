import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, nl_strategy
from app.data import market, symbols
from app.main import app


@pytest.mark.parametrize("text,want", [
    ("에이다 4시간봉 RSI 30 아래면 롱", "ADAUSDT"),
    ("비트코인캐시 1시간", "BCHUSDT"),
    ("비트코인 15분", "BTCUSDT"),
    ("pepe 돌파 매매", "1000PEPEUSDT"),
    ("ORDIUSDT 에서 테스트", "ORDIUSDT"),
    ("이더리움클래식", "ETCUSDT"),
    ("솔직히 잘 모르겠는데 추세 따라가", None),   # '솔' 로 시작해도 솔라나가 아니다
    ("operation 이라는 단어", None),              # 영문 별칭은 단어 경계로만
])
def test_find_in_text(text, want):
    assert symbols.find_in_text(text) == want


def test_resolve_search_box():
    assert symbols.resolve("페페") == "1000PEPEUSDT"
    assert symbols.resolve("도지") == "DOGEUSDT"
    assert symbols.resolve("abc") == "ABCUSDT"
    assert symbols.resolve("1000bonkusdt") == "1000BONKUSDT"
    assert TestClient(app).get("/api/resolve", params={"q": "리플"}).json() == {"symbol": "XRPUSDT"}


def test_rule_parse_uses_coin_from_text():
    spec = nl_strategy.rule_parse("에이다 4시간봉 RSI 30 아래에서 롱", "BTCUSDT")
    assert spec.symbol == "ADAUSDT" and spec.interval == "4h"
    assert nl_strategy.rule_parse("RSI 30 아래에서 롱", "SOLUSDT").symbol == "SOLUSDT"


def test_unknown_binance_symbol_is_an_error_not_fake_chart(monkeypatch):
    monkeypatch.setattr(config, "DATA_SOURCE", "auto")
    req = httpx.Request("GET", "https://fapi.binance.com/fapi/v1/klines")

    def bad(*a, **k):
        raise httpx.HTTPStatusError("400", request=req, response=httpx.Response(400, request=req))
    monkeypatch.setattr(market, "_binance_candles", bad)
    market._cache.clear()
    with pytest.raises(ValueError):
        market.candles("NOPEUSDT", "1h", 100)
    r = TestClient(app).get("/api/candles", params={"symbol": "NOPEUSDT", "interval": "1h"})
    assert r.status_code == 400 and "없는 종목" in r.json()["detail"]
