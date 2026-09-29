import pytest

from paperbot import Bar, Brackets, PaperEngine, Settings, Signal
from paperbot.live import LiveRunner, make_books
from paperbot.notify import ListNotifier
from paperbot.policy import RecommendedPolicy, RecommendedSettings, RiskGuards

MIN = 60_000
DAY = 86_400_000
S = Settings()
EX = Brackets.example()
R = RecommendedSettings()


def sig(ts=MIN - 1, side=+1, stop=99.0, tier="base", **kw):
    return Signal(ts, "BTCUSDT", "1m", "s", side, stop, tier=tier, **kw)


def per_unit(entry, stop, side=+1):
    exit_px = stop * (1 - side * S.slippage_frac)
    return abs(entry - exit_px) + entry * S.taker_fee + exit_px * S.taker_fee


def test_risk_one_percent_sets_size_and_leverage_is_the_result():
    pol = RecommendedPolicy(S)
    d = pol.size(1000.0, sig(stop=99.0), 100.0, EX, {})
    assert d.ok
    assert d.loss_at_stop == pytest.approx(10.0)  # 1% of 1000, fees included
    assert d.qty == pytest.approx(10.0 / per_unit(100.0, 99.0))
    assert d.leverage == 1  # ~900 notional fits a 1000 wallet


def test_tight_stop_raises_leverage():
    d = RecommendedPolicy(S).size(1000.0, sig(stop=99.9), 100.0, EX, {})  # 0.1% stop
    assert d.ok and 1 < d.leverage <= 10


def test_fees_alone_keep_one_percent_risk_under_ten_x():
    # Round-trip taker fees are 0.1% of notional, so a 1% risk budget can
    # never buy more than ~10x equity, however tight the stop.
    d = RecommendedPolicy(S).size(1000.0, sig(stop=99.9999), 100.0, EX, {})
    assert d.qty * 100.0 < 10 * 1000.0 and d.leverage <= 10


def test_leverage_cap_binds_at_higher_risk():
    pol = RecommendedPolicy(S, RecommendedSettings(risk_frac=0.05))
    d = pol.size(1000.0, sig(stop=99.99), 100.0, EX, {})  # 0.01% stop
    assert d.ok and d.leverage == 10
    assert d.qty * 100.0 == pytest.approx(10 * 1000.0)
    assert d.loss_at_stop < 50.0  # capped size risks less than the 5% budget
    assert any("capped" in r for r in d.reasons)


def test_best_tier_gets_two_percent_only_when_validated():
    base = RecommendedPolicy(S).size(1000.0, sig(tier="best"), 100.0, EX, {})
    assert base.loss_at_stop == pytest.approx(10.0)
    val = RecommendedPolicy(S, RecommendedSettings(best_tier_validated=True))
    assert val.size(1000.0, sig(tier="best"), 100.0, EX, {}).loss_at_stop == pytest.approx(20.0)


def test_take_profit_uses_strategy_target_else_two_r():
    pol = RecommendedPolicy(S)
    d = pol.size(1000.0, sig(stop=99.0), 100.0, EX, {})
    assert pol.take_profit(sig(stop=99.0), 100.0, d) == pytest.approx(102.0)
    assert pol.take_profit(sig(stop=99.0, tp_price=101.5), 100.0, d) == 101.5


def test_wrong_side_stop_rejected():
    assert not RecommendedPolicy(S).size(1000.0, sig(stop=101.0), 100.0, EX, {}).ok


def bar(i, o, h, l, c):
    return Bar("BTCUSDT", i * MIN, i * MIN + MIN - 1, o, h, l, c)


def rec_engine(rec=R):
    n = ListNotifier()
    return PaperEngine(S, {s: EX for s in S.symbols}, notifier=n,
                       policy=RecommendedPolicy(S, rec), guards=RiskGuards(rec),
                       book="recommended"), n


def _lose_once(e, i):
    e.submit(sig(ts=i * MIN + MIN - 1, stop=99.0))
    e.step({"BTCUSDT": bar(i + 1, 100, 100.1, 99.95, 100)})
    e.step({"BTCUSDT": bar(i + 2, 100, 100, 98.0, 98.5)})
    return e.trades[-1]


def test_consecutive_losses_pause_the_book():
    e, _ = rec_engine(RecommendedSettings(max_consecutive_losses=3, daily_loss_frac=0.5))
    for k in range(3):
        assert _lose_once(e, 10 * k).exit_reason == "SL"
    e.submit(sig(ts=40 * MIN - 1))
    e.step({"BTCUSDT": bar(40, 100, 100.1, 99.9, 100)})
    assert e.outcomes[-1].status == "REJECTED"
    assert "consecutive losses" in e.outcomes[-1].reason


def test_daily_loss_limit_blocks_until_next_utc_day():
    e, _ = rec_engine(RecommendedSettings(daily_loss_frac=0.015, max_consecutive_losses=99))
    _lose_once(e, 0)
    _lose_once(e, 10)  # ~2% down on the day, past the 1.5% limit
    e.submit(sig(ts=20 * MIN - 1))
    e.step({"BTCUSDT": bar(20, 100, 100.1, 99.9, 100)})
    assert "daily loss limit" in e.outcomes[-1].reason
    # Next UTC day (09:00 KST): allowed again.
    i = DAY // MIN
    e.submit(sig(ts=i * MIN - 1))
    e.step({"BTCUSDT": bar(i, 100, 100.1, 99.95, 100)})
    assert e.outcomes[-1].status == "ENTERED"


def test_both_books_get_the_same_signal_and_size_differently():
    engines, _ = make_books(S, {s: EX for s in S.symbols}, {}, ListNotifier(), None, "t")
    runner = LiveRunner(None, engines, [], ListNotifier())
    for e in engines:
        e.submit(sig(stop=99.0))
    runner.process([(MIN, {"BTCUSDT": bar(1, 100, 100.1, 99.95, 100)}, {})])
    owner, rec = engines
    assert owner.book == "owner" and rec.book == "recommended"
    assert owner.position.leverage == 20 and owner.position.margin == pytest.approx(200.0)
    assert rec.position.leverage == 1
    assert owner.position.qty > 4 * rec.position.qty
    assert owner.summary()["policy_version"] == S.version
    assert rec.summary()["policy_version"] == R.version


def test_owner_settings_still_reject_below_20x():
    from paperbot.config import Tier
    with pytest.raises(ValueError):
        Settings(tiers=(Tier("x", 0.2, (10,)),))
