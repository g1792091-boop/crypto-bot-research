import pytest

from paperbot import Bar, Brackets, PaperEngine, Settings, Signal
from paperbot.notify import CRITICAL, WARN, ListNotifier

MIN = 60_000
S = Settings()
SLIP = S.slippage_frac


def bar(i, o, h, l, c, sym="BTCUSDT", **mark):
    return Bar(sym, i * MIN, i * MIN + MIN - 1, o, h, l, c, **mark)


def sig(i, side=+1, stop=99.0, sym="BTCUSDT", tier="base", score=0.0, strat="s1", **kw):
    return Signal(ts=i * MIN + MIN - 1, symbol=sym, timeframe="1m",
                  strategy_id=strat, side=side, stop_price=stop, tier=tier,
                  score=score, **kw)


def engine(**kw):
    n = ListNotifier()
    br = {s: Brackets.example() for s in S.symbols}
    return PaperEngine(Settings(**kw) if kw else S, br, notifier=n), n


def test_entry_at_next_bar_open_with_slippage_and_fee():
    e, _ = engine()
    e.step({"BTCUSDT": bar(0, 100, 100, 100, 100)})
    e.submit(sig(0))
    e.step({"BTCUSDT": bar(1, 100, 100.2, 99.9, 100.1)})
    p = e.position
    assert p is not None
    assert p.entry_price == pytest.approx(100 * (1 + SLIP))
    assert p.entry_time == 1 * MIN
    assert e.wallet == pytest.approx(1000 - p.qty * p.entry_price * S.taker_fee)
    assert e.outcomes[-1].status == "ENTERED"


def test_signal_cannot_fill_on_its_own_bar():
    e, _ = engine()
    e.submit(sig(1))  # stamped with bar 1 close
    e.step({"BTCUSDT": bar(1, 100, 101, 99, 100)})
    assert e.position is None
    assert e.outcomes[-1].reason == "signal from the future"


def _open_long(e, stop=99.0):
    e.submit(sig(0, stop=stop))
    e.step({"BTCUSDT": bar(1, 100, 100.1, 99.95, 100)})
    return e.position


def test_tp_needs_trade_through_not_touch():
    e, _ = engine()
    p = _open_long(e)
    e.step({"BTCUSDT": bar(2, 100, p.tp_price, 99.9, 100)})
    assert e.position is not None
    e.step({"BTCUSDT": bar(3, 100, p.tp_price + 0.01, 99.9, 100)})
    t = e.trades[-1]
    assert t.exit_reason == "TP" and t.exit_price == pytest.approx(p.tp_price)
    assert t.fees == pytest.approx(p.entry_fee + p.qty * p.tp_price * S.maker_fee)


def test_ambiguous_bar_assumes_stop_first():
    e, _ = engine()
    p = _open_long(e)
    e.step({"BTCUSDT": bar(2, 100, p.tp_price + 1, 98.0, 100)})
    t = e.trades[-1]
    assert t.exit_reason == "SL"
    assert t.exit_price == pytest.approx(99.0 * (1 - SLIP))


def test_gap_through_stop_fills_at_open():
    e, _ = engine()
    _open_long(e)
    e.step({"BTCUSDT": bar(2, 98.5, 98.6, 98.0, 98.2)})
    t = e.trades[-1]
    assert t.exit_reason == "SL"
    assert t.exit_price == pytest.approx(98.5 * (1 - SLIP))


def test_mark_price_liquidation_loses_whole_isolated_margin():
    e, n = engine()
    p = _open_long(e, stop=97.0)  # 3% stop, liq near 95.5
    margin = p.margin
    e.step({"BTCUSDT": bar(2, 100, 100, 97.5, 98, mark_open=100, mark_high=100,
                           mark_low=95.0, mark_close=96)})
    t = e.trades[-1]
    assert t.exit_reason == "LIQ"
    assert t.pnl == pytest.approx(-margin - p.entry_fee)
    assert any(lvl == CRITICAL and "LIQUIDATED" in m for lvl, m in n.messages)


def test_single_position_records_skipped_signals():
    e, _ = engine()
    _open_long(e)
    e.submit(sig(1, sym="ETHUSDT"))
    e.step({"BTCUSDT": bar(2, 100, 100.1, 99.9, 100),
            "ETHUSDT": bar(2, 100, 100.1, 99.9, 100, sym="ETHUSDT")})
    o = e.outcomes[-1]
    assert o.status == "SKIPPED" and o.reason == "in position"
    assert o.detail["held_symbol"] == "BTCUSDT"


def test_competing_signals_highest_score_wins():
    e, _ = engine()
    e.submit(sig(0, sym="BTCUSDT", score=1.0, strat="a"))
    e.submit(sig(0, sym="ETHUSDT", score=2.0, strat="b"))
    e.step({"BTCUSDT": bar(1, 100, 100.1, 99.9, 100),
            "ETHUSDT": bar(1, 100, 100.1, 99.9, 100, sym="ETHUSDT")})
    assert e.position.symbol == "ETHUSDT"
    skipped = [o for o in e.outcomes if o.status == "SKIPPED"]
    assert skipped[0].signal.strategy_id == "a"
    assert skipped[0].reason == "lower score than entered signal"


def test_sizing_rejection_lets_next_signal_enter():
    e, _ = engine()
    e.submit(sig(0, sym="BTCUSDT", score=5.0, stop=90.0))  # 10% stop: too wide
    e.submit(sig(0, sym="ETHUSDT", score=1.0))
    e.step({"BTCUSDT": bar(1, 100, 100.1, 99.9, 100),
            "ETHUSDT": bar(1, 100, 100.1, 99.9, 100, sym="ETHUSDT")})
    assert e.position.symbol == "ETHUSDT"
    assert e.outcomes[0].status == "REJECTED" and e.outcomes[0].reason == "sizing"


def test_funding_long_pays_positive_rate_and_moves_liquidation():
    e, _ = engine()
    p = _open_long(e)
    wallet, liq = e.wallet, p.liq_price
    e.step({"BTCUSDT": bar(2, 100, 100.1, 99.9, 100)}, funding={"BTCUSDT": 0.0001})
    paid = p.qty * 100 * 0.0001
    assert e.wallet == pytest.approx(wallet - paid)
    assert p.funding_paid == pytest.approx(paid)
    assert p.liq_price > liq


def test_drawdown_warnings_and_halt_at_fifty_percent():
    e, n = engine()
    # A 0.5% stop lets the best tier (40% x 50x) through. Mark-price
    # liquidations while last price stays above the stop lose the full 40%:
    # equity 1000 -> ~590 -> ~350, which crosses the 50% halt.
    tiers = []
    for k in range(3):
        base = 10 * k
        e.submit(sig(base, stop=99.5, tier="best"))
        e.step({"BTCUSDT": bar(base + 1, 100, 100, 99.9, 100)})
        if e.position is None:
            break
        tiers.append((e.position.tier, e.position.leverage))
        e.step({"BTCUSDT": bar(base + 2, 100, 100, 99.6, 99.8, mark_open=100,
                               mark_high=100, mark_low=80.0, mark_close=90)})
        if e.halted:
            break
    assert tiers[0] == ("best", 50)
    assert [t.exit_reason for t in e.trades] == ["LIQ", "LIQ"]
    assert e.halted
    warns = [m for lvl, m in n.messages if lvl == WARN]
    assert any("level 20%" in m for m in warns)
    assert any("ENGINE HALTED" in m for lvl, m in n.messages if lvl == CRITICAL)
    e.submit(sig(50))
    e.step({"BTCUSDT": bar(51, 100, 100, 100, 100)})
    assert e.outcomes[-1].status == "REJECTED"
    assert e.outcomes[-1].reason.startswith("halted")


def test_equity_accounting_matches_trade_pnl():
    e, _ = engine()
    _open_long(e)
    e.step({"BTCUSDT": bar(2, 100, 101, 99.9, 100.5)})
    e.submit(sig(2, side=-1, stop=101.5))
    e.step({"BTCUSDT": bar(3, 100.5, 100.6, 100.4, 100.5)})
    e.step({"BTCUSDT": bar(4, 100.5, 102, 100.4, 101.8)})
    assert e.position is None
    assert e.wallet == pytest.approx(1000 + sum(t.pnl for t in e.trades))


def test_kill_switch_closes_and_halts():
    e, _ = engine()
    _open_long(e)
    b = {"BTCUSDT": bar(2, 100, 100.2, 99.8, 100.1)}
    e.kill(b["BTCUSDT"].close_time, b)
    assert e.position is None and e.halted
    assert e.trades[-1].exit_reason == "MANUAL"
