import json
import urllib.parse

import pytest

from paperbot import Bar, Brackets, PaperEngine, Settings, Signal
from paperbot.aggregate import Aggregator
from paperbot.binance import BinanceError, BinanceREST, RegionBlocked, bars_from_klines
from paperbot.feed import LiveFeed
from paperbot.live import LiveRunner
from paperbot.notify import ListNotifier

MIN = 60_000
T0 = 1_700_000_040_000 - (1_700_000_040_000 % 86_400_000)  # a UTC midnight


def kline(ot, o=100.0, h=100.5, l=99.5, c=100.0):
    return [ot, str(o), str(h), str(l), str(c), "1", ot + MIN - 1, "1", 1, "1", "1", "0"]


class FakeBinance:
    """Serves closed and forming 1m bars up to ``now`` for each symbol."""

    def __init__(self, symbols, now, missing=None, funding=None):
        self.symbols = symbols
        self.now = now
        self.missing = missing or {}  # symbol -> set of open_times withheld
        self.funding = funding or {}  # symbol -> list of (time, rate)
        self.calls = []
        self.fail_next = []  # list of (status, headers)

    def fetch(self, url, headers):
        self.calls.append(url)
        if self.fail_next:
            status, h = self.fail_next.pop(0)
            return status, b"{}", h
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path == "/fapi/v1/time":
            return 200, json.dumps({"serverTime": self.now}).encode(), {}
        if u.path in ("/fapi/v1/klines", "/fapi/v1/markPriceKlines"):
            sym = q["symbol"]
            limit = int(q["limit"])
            last_open = self.now - self.now % MIN  # the forming bar
            if "startTime" in q:
                start = int(q["startTime"])
                times = list(range(start, last_open + 1, MIN))[:limit]
            else:
                times = list(range(last_open - (limit - 1) * MIN, last_open + 1, MIN))
            skip = self.missing.get(sym, set())
            off = 1.0 if u.path.endswith("markPriceKlines") else 0.0
            rows = [kline(t, 100 + off, 100.5 + off, 99.5 + off, 100 + off)
                    for t in times if t not in skip]
            return 200, json.dumps(rows).encode(), {}
        if u.path == "/fapi/v1/fundingRate":
            sym = q["symbol"]
            start = int(q.get("startTime", 0))
            rows = [{"symbol": sym, "fundingTime": t, "fundingRate": str(r)}
                    for t, r in self.funding.get(sym, []) if t >= start and t <= self.now]
            return 200, json.dumps(rows).encode(), {}
        return 404, b"not found", {}


def rest_for(fake, **kw):
    return BinanceREST(fetch=fake.fetch, sleep=lambda s: None,
                       clock_ms=lambda: fake.now, **kw)


def test_bars_from_klines_joins_mark_prices():
    rows = [kline(0), kline(MIN)]
    marks = [kline(0, 101, 101, 101, 101)]
    b = bars_from_klines("BTCUSDT", rows, marks)
    assert b[0].mark_close == 101.0 and b[1].mark_close is None
    assert b[1].close_time == 2 * MIN - 1


def test_region_block_raises_immediately():
    fake = FakeBinance(["BTCUSDT"], T0)
    fake.fail_next = [(451, {})]
    with pytest.raises(RegionBlocked):
        rest_for(fake).server_time()


def test_rate_limit_retries_then_succeeds():
    fake = FakeBinance(["BTCUSDT"], T0)
    fake.fail_next = [(429, {"Retry-After": "1"}), (503, {})]
    assert rest_for(fake).server_time() == T0


def test_gives_up_after_retries():
    fake = FakeBinance(["BTCUSDT"], T0)
    fake.fail_next = [(500, {})] * 10
    with pytest.raises(BinanceError):
        rest_for(fake, max_retries=2).server_time()


def test_signed_request_requires_keys_and_signs():
    fake = FakeBinance(["BTCUSDT"], T0)
    with pytest.raises(BinanceError):
        rest_for(fake).leverage_brackets()
    r = rest_for(fake, api_key="k", api_secret="s")
    try:
        r.leverage_brackets()
    except BinanceError:
        pass
    assert "signature=" in fake.calls[-1] and "timestamp=" in fake.calls[-1]


def test_feed_never_passes_forming_bar_and_backfills():
    syms = ["BTCUSDT", "ETHUSDT"]
    fake = FakeBinance(syms, T0 + 10 * MIN + 5_000)  # bar 10 is forming
    events = []
    feed = LiveFeed(rest_for(fake), syms, start_time=T0 + 3 * MIN,
                    clock_ms=lambda: fake.now, on_event=lambda l, t: events.append((l, t)))
    steps = feed.poll()
    assert [t for t, _, _ in steps] == [T0 + i * MIN for i in range(3, 10)]
    assert all(set(b) == set(syms) for _, b, _ in steps)
    assert steps[0][1]["BTCUSDT"].mark_close == 101.0
    fake.now += MIN
    more = feed.poll()
    assert [t for t, _, _ in more] == [T0 + 10 * MIN]


def test_feed_waits_for_lagging_symbol_then_reports_gap():
    syms = ["BTCUSDT", "ETHUSDT"]
    fake = FakeBinance(syms, T0 + 5 * MIN + 1_000,
                       missing={"ETHUSDT": {T0 + 4 * MIN}})
    events = []
    feed = LiveFeed(rest_for(fake), syms, start_time=T0 + 3 * MIN, grace_ms=20_000,
                    clock_ms=lambda: fake.now, on_event=lambda l, t: events.append((l, t)))
    steps = feed.poll()
    # bar 4 has no ETH yet and is not overdue -> held back, so nothing after it
    assert [t for t, _, _ in steps] == [T0 + 3 * MIN]
    fake.now = T0 + 5 * MIN + 30_000  # past grace for bar 4
    steps = feed.poll()
    assert [t for t, _, _ in steps] == [T0 + 4 * MIN]
    assert set(steps[0][1]) == {"BTCUSDT"}
    assert any("data gap" in t for _, t in events)


def test_feed_attaches_funding_to_settlement_minute():
    syms = ["BTCUSDT"]
    ft = T0 + 8 * MIN + 3  # Binance stamps funding a few ms after the hour
    fake = FakeBinance(syms, T0 + 10 * MIN + 1, funding={"BTCUSDT": [(ft, 0.0001)]})
    feed = LiveFeed(rest_for(fake), syms, start_time=T0 + 5 * MIN, clock_ms=lambda: fake.now)
    steps = feed.poll()
    funded = {t: f for t, _, f in steps if f}
    assert funded == {T0 + 8 * MIN: {"BTCUSDT": 0.0001}}


def _b(i, o=100, h=101, l=99, c=100, sym="BTCUSDT"):
    return Bar(sym, T0 + i * MIN, T0 + (i + 1) * MIN - 1, o, h, l, c)


def test_aggregator_builds_5m_bar_on_last_minute():
    agg = Aggregator(["1m", "5m"])
    out = []
    for i, (o, h, l, c) in enumerate([(1, 2, 0.5, 1.5), (1.5, 3, 1, 2), (2, 2, 1, 1),
                                      (1, 1.2, 0.2, 0.3), (0.3, 0.9, 0.3, 0.8)]):
        out += agg.add(_b(i, o, h, l, c))
    five = [b for tf, b in out if tf == "5m"]
    assert len(five) == 1
    b = five[0]
    assert (b.open, b.high, b.low, b.close) == (1, 3, 0.2, 0.8)
    assert b.open_time == T0 and b.close_time == T0 + 5 * MIN - 1 and not b.partial


def test_aggregator_flags_partial_bucket():
    agg = Aggregator(["5m"])
    out = []
    for i in (0, 1, 2, 3):  # minute 4 missing
        out += agg.add(_b(i))
    out += agg.add(_b(5))
    assert len(out) == 1 and out[0][1].partial


class OnceLong:
    strategy_id = "once"
    timeframe = "5m"
    warmup_bars = 1

    def __init__(self):
        self.fired = False

    def on_bar(self, symbol, history):
        if self.fired:
            return []
        self.fired = True
        b = history[-1]
        return [Signal(b.close_time, symbol, "5m", self.strategy_id, +1, b.close * 0.99)]


def test_live_runner_fills_signal_at_next_1m_open():
    s = Settings()
    n = ListNotifier()
    eng = PaperEngine(s, {x: Brackets.example() for x in s.symbols}, notifier=n)
    runner = LiveRunner(feed=None, engine=eng, strategies=[OnceLong()], notifier=n)
    steps = [(T0 + i * MIN, {"BTCUSDT": _b(i, o=100 + 0.1 * i, h=100.6 + 0.1 * i,
                                          l=99.6 + 0.1 * i, c=100.1 + 0.1 * i)}, {})
             for i in range(7)]
    runner.process(steps[:5])  # 5m bar closes with minute 4
    assert eng.position is None and len(eng.pending) == 1
    runner.process(steps[5:6])
    assert eng.outcomes[-1].status == "ENTERED"
    # Net 10% ROE at 20x = 0.64% above entry; bar 5's high (101.1) stays below it.
    fill = 100.5 * (1 + s.slippage_frac)
    assert eng.position.tp_price == pytest.approx(fill * 1.0064)
    runner.process(steps[6:7])  # bar 6's high (101.2) trades through the target
    t = eng.trades[-1]
    assert t.entry_time == T0 + 5 * MIN
    assert t.entry_price == pytest.approx(100.5 * (1 + s.slippage_frac))
    assert t.stop_price == pytest.approx(100.5 * 0.99)  # 5m close x 0.99
    assert t.exit_reason == "TP" and t.leverage == 20
