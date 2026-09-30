from app.backtest import run
from app.data import synthetic
from app.engine import Simulator
from app.strategy import Condition, ConditionGroup, IndicatorSpec, RiskSpec, StrategySpec


def bar(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}


def zero_cost(**kw):
    return RiskSpec(fee_pct=0, slippage_pct=0, funding_rate_8h_pct=0, **kw)


def test_stop_loss_hits_before_take_profit_in_same_bar():
    sim = Simulator(risk=zero_cost(leverage=1, position_pct=100, stop_loss_pct=2, take_profit_pct=2))
    sim.open_position(1, 100.0, 0)
    t = sim.check_stops(bar(1, 100, 103, 97, 100))
    assert t.exit_reason == "stop_loss"
    assert round(t.exit_price, 6) == 98.0
    assert round(sim.cash, 6) == 10_000 - 200


def test_take_profit_short():
    sim = Simulator(risk=zero_cost(leverage=2, position_pct=50, take_profit_pct=5))
    sim.open_position(-1, 100.0, 0)
    t = sim.check_stops(bar(1, 99, 99.5, 94, 95))
    assert t.exit_reason == "take_profit" and t.exit_price == 95.0
    # 증거금 5000 x2 = 10000 명목, 5% 수익 = 500
    assert round(t.pnl, 6) == 500.0


def test_liquidation_loses_isolated_margin():
    sim = Simulator(risk=zero_cost(leverage=50, position_pct=10))
    sim.open_position(1, 100.0, 0)
    t = sim.check_stops(bar(1, 100, 100, 97, 97.5))
    assert t.exit_reason == "liquidation"
    assert round(sim.cash, 6) == 9_000.0


def test_trailing_stop_locks_profit():
    sim = Simulator(risk=zero_cost(leverage=1, position_pct=100, trailing_stop_pct=5))
    sim.open_position(1, 100.0, 0)
    assert sim.check_stops(bar(1, 100, 120, 100, 119)) is None
    t = sim.check_stops(bar(2, 119, 119, 110, 111))
    assert t.exit_reason == "trailing_stop" and round(t.exit_price, 6) == 114.0


def test_signal_executes_on_next_bar_open():
    spec = StrategySpec(name="t", indicators=[],
                        long_entry=ConditionGroup(conditions=[Condition(left="close", op=">", right="open")]),
                        risk=zero_cost(leverage=1, position_pct=100))
    candles = [bar(0, 100, 100, 100, 100), bar(3600, 100, 106, 100, 105), bar(7200, 107, 110, 106, 108)]
    res = run(spec, candles)
    t = res["trades"][0]
    assert t["entry_time"] == 7200 and t["entry_price"] == 107  # 신호 봉(3600) 다음 봉 시가


def test_backtest_on_synthetic_data_produces_metrics():
    spec = StrategySpec(
        name="ema cross", interval="1h",
        indicators=[IndicatorSpec(id="f", type="ema", length=20), IndicatorSpec(id="s", type="ema", length=50)],
        long_entry=ConditionGroup(conditions=[Condition(left="f", op="crosses_above", right="s")]),
        short_entry=ConditionGroup(conditions=[Condition(left="f", op="crosses_below", right="s")]),
        risk=RiskSpec(leverage=3, stop_loss_pct=3),
    )
    res = run(spec, synthetic.candles("BTCUSDT", "1h", 1500, seed=7))
    m = res["metrics"]
    assert m["trades"] > 5
    assert len(res["equity_curve"]) == 1500
    assert m["final_equity"] == round(res["equity_curve"][-1]["value"], 2)
    assert m["long_trades"] + m["short_trades"] == m["trades"]
