"""전략·자동 개선·페이퍼 봇이 BTC 1시간봉에 묶이지 않고 모든 코인·봉에서 도는지."""
import pytest
from fastapi.testclient import TestClient

from app import nl_strategy
from app.main import app, paper
from app.strategy import validate

c = TestClient(app)
SPEC = nl_strategy.rule_parse("EMA 20/50 골든크로스 롱 데드크로스 숏, 손절 2% 익절 4%").model_dump()


@pytest.mark.parametrize("text,iv", [("3분봉", "3m"), ("2시간봉", "2h"), ("12시간", "12h"), ("6시간봉", "6h"),
                                     ("3일봉", "3d"), ("주봉", "1w"), ("월봉", "1M"), ("15분", "15m"), ("일봉", "1d")])
def test_rule_parser_knows_every_interval(text, iv):
    assert nl_strategy.rule_parse(f"솔라나 {text} RSI 30 아래 롱").interval == iv
    assert nl_strategy.rule_parse(f"솔라나 {text} RSI 30 아래 롱").symbol == "SOLUSDT"


def test_chat_edit_changes_coin_and_interval():
    spec = nl_strategy.rule_parse("RSI 30 아래 롱", "BTCUSDT", "1h")
    new, changes = nl_strategy.rule_edit(spec, "도지 4시간봉으로 바꿔")
    assert (new.symbol, new.interval) == ("DOGEUSDT", "4h") and len(changes) == 2


def test_unsupported_interval_rejected():
    spec = nl_strategy.rule_parse("RSI 30 아래 롱").model_copy(update={"interval": "7m"})
    assert any("봉 간격" in p for p in validate(spec))


def test_scan_many_coins_and_intervals():
    r = c.post("/api/strategy/scan", json={"spec": SPEC, "symbols": ["btc", "이더", "페페"], "intervals": ["15m", "4h", "1w", "1y"], "bars": 600})
    rows = r.json()["rows"]
    assert r.status_code == 200 and len(rows) == 9          # 1y 는 전략용이 아니라 빠진다
    assert {x["symbol"] for x in rows} == {"BTCUSDT", "ETHUSDT", "1000PEPEUSDT"}
    rets = [x["metrics"]["total_return_pct"] for x in rows if "metrics" in x]
    assert rets == sorted(rets, reverse=True)
    assert c.post("/api/strategy/scan", json={"spec": SPEC, "symbols": [], "intervals": ["1h"]}).status_code == 400


def test_improve_and_bot_on_other_coin_and_interval():
    spec = {**SPEC, "symbol": "솔라나", "interval": "15m"}
    rep = c.post("/api/strategy/improve", json={"spec": spec, "bars": 800}).json()
    assert rep["spec"]["symbol"] == "SOLUSDT" and rep["spec"]["interval"] == "15m"
    bt = c.post("/api/backtest", json={"spec": {**SPEC, "symbol": "xrp", "interval": "1d"}, "bars": 500}).json()
    assert bt["metrics"]["trades"] >= 0 and len(bt["candles"]) == 500
    b = c.post("/api/paper/bots", json={"spec": {**SPEC, "symbol": "이더", "interval": "4h"}}).json()
    try:
        assert (b["symbol"], b["interval"]) == ("ETHUSDT", "4h")
    finally:
        paper.bots.pop(b["id"], None)
