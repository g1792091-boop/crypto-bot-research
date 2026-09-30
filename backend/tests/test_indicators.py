import math

from app import indicators as ind
from app.data import synthetic


def test_sma_ema_rma_basic():
    x = [1.0, 2, 3, 4, 5]
    assert ind.sma(x, 3) == [None, None, 2.0, 3.0, 4.0]
    e = ind.ema(x, 3)
    assert e[:2] == [None, None] and e[2] == 2.0          # SMA 시드
    assert math.isclose(e[3], 0.5 * 4 + 0.5 * 2.0)
    r = ind.rma(x, 3)
    assert math.isclose(r[3], (1 / 3) * 4 + (2 / 3) * 2.0)


def test_rsi_extremes():
    up = [float(i) for i in range(1, 40)]
    assert ind.rsi(up, 14)[-1] == 100.0
    down = list(reversed(up))
    assert ind.rsi(down, 14)[-1] == 0.0


def test_bbands_constant_series_has_zero_width():
    bb = ind.bbands([10.0] * 30, 20, 2)
    assert bb["upper"][-1] == bb["lower"][-1] == 10.0


def test_all_registry_indicators_compute_full_length():
    c = synthetic.candles("BTCUSDT", "1h", 300, seed=1)
    for name in ind.REGISTRY:
        res = ind.compute(c, name, {})
        for series in res.values():
            assert len(series) == len(c)
            assert series[-1] is not None, name


def test_supertrend_trend_follows_strong_trend():
    c = [{"time": i * 3600, "open": 100 + i, "high": 101 + i, "low": 99.5 + i, "close": 100.8 + i, "volume": 1}
         for i in range(60)]
    assert ind.supertrend(c, 10, 3)["trend"][-1] == 1


def test_synthetic_bars_are_stable_across_request_sizes():
    short = synthetic.candles("BTCUSDT", "1h", 300)
    long_ = synthetic.candles("BTCUSDT", "1h", 2000)
    assert short == long_[-300:]
    assert all(a["close"] == b["open"] for a, b in zip(long_, long_[1:]))
