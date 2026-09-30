import pytest

from paperbot.ladder import LadderSpec, net_roe, roe_price, tighten
from paperbot.sizing import tp_from_roe

RT = 0.0014


def test_lock_steps():
    s = LadderSpec()
    assert s.lock_for(0.0) is None
    assert s.lock_for(0.1199) is None
    assert s.lock_for(0.12) == pytest.approx(0.10)
    assert s.lock_for(0.1699) == pytest.approx(0.10)
    assert s.lock_for(0.17) == pytest.approx(0.15)
    assert s.lock_for(0.22) == pytest.approx(0.20)
    assert s.lock_for(0.3199) == pytest.approx(0.25)
    assert s.lock_for(1.02) == pytest.approx(1.00)


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("lev", [20, 30, 40, 50])
def test_roe_price_inverts_net_roe(side, lev):
    p = roe_price(side, 100.0, lev, 0.10, RT, 0.0003)
    assert net_roe(side, 100.0, p, lev, RT, 0.0003) == pytest.approx(0.10)
    # same definition as the owners' fixed take-profit
    assert roe_price(side, 100.0, lev, 0.10, RT) == pytest.approx(tp_from_roe(side, 100.0, lev, 0.10, RT))


def test_price_distances_match_owner_table():
    # 10% net at 20x = +0.64%, at 50x = +0.34%; the 12% trigger at 50x = +0.38%
    assert roe_price(1, 100.0, 20, 0.10, RT) == pytest.approx(100.64)
    assert roe_price(1, 100.0, 50, 0.10, RT) == pytest.approx(100.34)
    assert roe_price(1, 100.0, 50, 0.12, RT) == pytest.approx(100.38)
    assert roe_price(-1, 100.0, 20, 0.10, RT) == pytest.approx(99.36)


def test_tighten_only_moves_toward_price():
    assert tighten(1, 99.0, 100.3) == 100.3
    assert tighten(1, 100.5, 100.3) == 100.5
    assert tighten(-1, 101.0, 99.7) == 99.7
    assert tighten(-1, 99.5, 99.7) == 99.5
    assert tighten(1, 99.0, None) == 99.0
