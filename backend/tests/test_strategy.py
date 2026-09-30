import pytest

from app.nl_strategy import rule_parse
from app.strategy import Condition, ConditionGroup, IndicatorSpec, StrategySpec, signals, validate
from app.data import synthetic


def test_validate_catches_unknown_reference():
    spec = StrategySpec(name="x", long_entry=ConditionGroup(conditions=[Condition(left="foo", op=">", right="1")]))
    assert any("foo" in p for p in validate(spec))


def test_multi_output_and_shift_and_multiplier_operands():
    c = synthetic.candles("ETHUSDT", "1h", 200, seed=3)
    spec = StrategySpec(
        name="x",
        indicators=[IndicatorSpec(id="m", type="macd"), IndicatorSpec(id="v", type="volume_sma", length=10)],
        long_entry=ConditionGroup(logic="any", conditions=[
            Condition(left="m.hist", op=">", right="m.hist[1]"),
            Condition(left="volume", op=">", right="v*1.5"),
        ]),
    )
    assert validate(spec) == []
    sig = signals(spec, c)
    assert any(sig["long_entry"])


def test_rule_parser_korean_prompt():
    s = rule_parse("BTC 1시간봉 EMA 20/50 골든크로스 롱, RSI 70 이상이면 제외, 손절 2% 익절 4%, 레버리지 5배")
    assert s.symbol == "BTCUSDT" and s.interval == "1h"
    assert s.risk.leverage == 5 and s.risk.stop_loss_pct == 2 and s.risk.take_profit_pct == 4
    ops = [(c.left, c.op, c.right) for c in s.long_entry.conditions]
    assert ("ma_fast", "crosses_above", "ma_slow") in ops and ("rsi", "<", "70") in ops
    assert validate(s) == []


def test_rule_parser_interval_and_long_only():
    s = rule_parse("이더 15분봉 슈퍼트렌드 전환 롱만 거래량 2배")
    assert s.interval == "15m" and s.symbol == "ETHUSDT"
    assert s.short_entry is None


def test_rule_parser_rejects_empty():
    with pytest.raises(ValueError):
        rule_parse("아무 조건 없음")
