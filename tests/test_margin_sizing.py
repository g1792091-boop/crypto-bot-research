import pytest

from paperbot import Brackets, BracketTier, Settings, liquidation_price, size_position, tp_from_roe

B = BracketTier(50_000, 50, 0.005, 0.0)


def iso_liq(side, entry, lev):
    qty = 1.0
    return liquidation_price(side, qty, entry, entry / lev, B)


@pytest.mark.parametrize("lev,long_dist", [(20, 0.0452), (30, 0.0285), (50, 0.0151)])
def test_isolated_liquidation_distance_matches_handover(lev, long_dist):
    # Handover: liquidation adverse move ~ 1/L - 0.5%: 20x 4.5%, 30x 2.8%, 50x 1.5%
    liq = iso_liq(+1, 100.0, lev)
    assert 1 - liq / 100.0 == pytest.approx(long_dist, abs=5e-4)


def test_long_and_short_liquidation_closed_form():
    assert iso_liq(+1, 100.0, 20) == pytest.approx(100 * 0.95 / 0.995)
    assert iso_liq(-1, 100.0, 20) == pytest.approx(100 * 1.05 / 1.005)


def test_brackets_from_binance_payload():
    payload = {"symbol": "BTCUSDT", "brackets": [
        {"bracket": 1, "initialLeverage": 125, "notionalCap": 50000,
         "notionalFloor": 0, "maintMarginRatio": 0.004, "cum": 0.0},
        {"bracket": 2, "initialLeverage": 100, "notionalCap": 600000,
         "notionalFloor": 50000, "maintMarginRatio": 0.005, "cum": 50.0},
    ]}
    b = Brackets.from_binance(payload)
    assert b.for_notional(10_000).max_leverage == 125
    assert b.for_notional(100_000).mmr == 0.005
    assert b.for_notional(10**9).max_leverage == 100


def test_tp_from_roe():
    assert tp_from_roe(+1, 100.0, 20, 0.10) == pytest.approx(100.5)
    assert tp_from_roe(-1, 100.0, 50, 0.10) == pytest.approx(99.8)


S = Settings()
EX = Brackets.example()


def test_base_tier_sizes_20pct_20x():
    d = size_position(S, 1000.0, +1, 100.0, 99.0, "base", EX)
    assert d.ok and d.tier == "base" and d.leverage == 20
    assert d.margin == pytest.approx(200.0)
    assert d.qty == pytest.approx(40.0)
    assert d.loss_at_stop <= 150.0


def test_best_tier_downgrades_when_loss_cap_exceeded():
    # 1% stop: 40%x50x and 40%x40x lose more than 15%; 30%x30x fits.
    d = size_position(S, 1000.0, +1, 100.0, 99.0, "best", EX)
    assert d.ok and d.tier == "good" and d.leverage == 30
    assert any("50x" in r for r in d.reasons) and any("40x" in r for r in d.reasons)


def test_rejects_when_even_base_tier_breaks_loss_cap():
    d = size_position(S, 1000.0, +1, 100.0, 96.0, "base", EX)  # 4% stop -> 16% loss
    assert not d.ok
    assert "15%" in d.reasons[-1]


def test_rejects_when_stop_too_close_to_liquidation():
    # 4% stop at 20x sits 0.52 inside liq; ATR 0.5 demands 1.5 of room.
    d = size_position(S, 1000.0, +1, 100.0, 96.0, "base", EX, atr=0.5)
    assert not d.ok and "liq" in d.reasons[-1]


def test_rejects_stop_on_wrong_side():
    assert not size_position(S, 1000.0, +1, 100.0, 101.0, "base", EX).ok
    assert not size_position(S, 1000.0, -1, 100.0, 99.0, "base", EX).ok


def test_bracket_leverage_cap_skips_high_tiers():
    capped = Brackets([BracketTier(10**9, 25, 0.005, 0.0)])
    d = size_position(S, 1000.0, +1, 100.0, 99.5, "best", capped)
    assert d.ok and d.leverage == 20


def test_qty_step_rounds_down():
    d = size_position(S, 1000.0, +1, 30000.0, 29900.0, "base", EX, qty_step=0.001)
    assert d.ok
    assert d.qty == pytest.approx(0.133)
    assert d.margin == pytest.approx(0.133 * 30000 / 20)


def test_settings_reject_tiers_outside_owner_rules():
    from paperbot.config import Tier
    with pytest.raises(ValueError):
        Settings(tiers=(Tier("x", 0.5, (20,)),))
    with pytest.raises(ValueError):
        Settings(tiers=(Tier("x", 0.2, (10,)),))
