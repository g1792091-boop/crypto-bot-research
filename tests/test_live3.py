from paperbot import Bar, Brackets, Signal
from paperbot.accounts import AccountBook
from paperbot.config import V3_SYMBOLS, v3_settings
from paperbot.live3 import Runner3, account_defs
from paperbot.store3 import Store3

MIN = 60_000
FIVE = 300_000
S = v3_settings()


class FakeService:
    """Emits one long signal for account S@5m at a chosen 5m boundary."""

    def __init__(self, fire_at):
        self.fire_at = fire_at
        self.last = {}
        self.computed = []

    def add_5m(self, b):
        self.last[b.symbol] = b.open_time + FIVE

    def complete(self, boundary):
        return all(self.last.get(s) == boundary for s in V3_SYMBOLS)

    def due(self, boundary):
        return ["5m"]

    def compute(self, boundary, tf, now_ms, book):
        self.computed.append(boundary)
        if boundary != self.fire_at:
            return [], [], []
        ref = book()["BTCUSDT"][1]
        sig = Signal(ts=boundary - 1, symbol="BTCUSDT", timeframe="5m", strategy_id="S", side=1,
                     stop_price=0.0, tier="best", atr=0.2,
                     meta={"stop_dist": 0.4, "ref_price": ref, "ref_time": now_ms()})
        row = {"bar_close": boundary, "timeframe": tf, "strategy": "S", "symbol": "BTCUSDT", "side": 1,
               "atr": 0.2, "ref_price": ref, "ref_time": now_ms(), "delay_ms": 1000, "status": "SUBMITTED"}
        return [row], [("S@5m", sig)], []


def steps(lo, hi):
    out = []
    for i in range(lo, hi):
        bars = {s: Bar(s, i * MIN, i * MIN + MIN - 1, 100.0, 100.05, 99.95, 100.0, volume=1.0)
                for s in V3_SYMBOLS}
        out.append((i * MIN, bars, {}))
    return out


def make(tmp_path, name, fire_at, skip_before=None):
    store = Store3(str(tmp_path / name))
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store)
    if not book.load():
        book.open_accounts([{"strategy": "S", "timeframe": "5m", "kind": "strategy"}], 0)
    svc = FakeService(fire_at)
    run = Runner3(book, svc, store, None, V3_SYMBOLS, lambda: 12345,
                  lambda: {"BTCUSDT": (100.1, 100.2)}, skip_before=skip_before)
    return store, book, svc, run


def test_signal_fills_next_minute_at_reference_ask(tmp_path):
    store, book, svc, run = make(tmp_path, "a.db", fire_at=10 * MIN)
    run.process(steps(0, 12))
    p = book.engines["S@5m"].position
    assert p is not None and p.entry_time == 10 * MIN
    assert p.entry_price == 100.2 * (1 + S.slippage_frac)
    assert svc.computed == [5 * MIN, 10 * MIN]
    assert store.conn.execute("SELECT status FROM signal_log").fetchall() == [("SUBMITTED",)]


def test_restart_replays_missed_minutes_without_trading_them(tmp_path):
    store, book, svc, run = make(tmp_path, "b.db", fire_at=None)
    run.process(steps(0, 7))          # processed through minute 6, then the process dies
    store.close()
    store, book, svc, run = make(tmp_path, "b.db", fire_at=10 * MIN, skip_before=7 * MIN)
    assert book.last_ts == 6 * MIN
    run.process(steps(5, 12))         # the feed restarts at the 5m boundary before the gap
    p = book.engines["S@5m"].position
    assert p is not None and p.entry_time == 10 * MIN


def test_account_defs_count():
    defs = account_defs([f"s{k}" for k in range(36)], ("5m", "15m", "30m", "1h", "4h"))
    assert len(defs) == 195 and sum(d["kind"] == "random" for d in defs) == 15
