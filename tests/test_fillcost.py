"""Order-book cost records of paper entries and exits (paperbot/fillcost.py): records only."""

import json

import pytest

from paperbot import Bar, Brackets
from paperbot.accounts import AccountBook
from paperbot.config import V3_SYMBOLS
from paperbot.fillcost import FillProbe, book_cost, summary
from paperbot.live3 import Runner3
from paperbot.store3 import Store3
from test_live3 import MIN, S, FakeService, steps


def test_book_cost_walks_the_levels():
    r = book_cost([(100, 5), (101, 10)], 1000.0, +1, best=100, mid=99.95)
    qty = 5 + 500 / 101
    assert r["vwap"] == pytest.approx(1000 / qty) and r["levels"] == 2 and r["enough"]
    assert r["slip_best"] == pytest.approx((1000 / qty - 100) / 100)
    assert r["slip_mid"] == pytest.approx((1000 / qty - 99.95) / 99.95)
    s = book_cost([(99, 1), (98, 1)], 500.0, -1, best=99, mid=99.05)        # a sell walks the bids down
    assert s["slip_best"] > 0 and not s["enough"] and s["filled_notional"] == pytest.approx(197)
    assert book_cost([], 10, 1, 1, 1)["vwap"] is None


class Depth:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, symbol):
        self.calls.append(symbol)
        if self.fail:
            raise ConnectionError("down")
        return {"T": 1, "bids": [["100.10", "1"], ["100.00", "1000"]], "asks": [["100.20", "1"], ["100.30", "1000"]]}


def _run(tmp_path, depth, now=lambda: 10 * MIN + 5_000):
    store = Store3(str(tmp_path / "p.db"))
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store)
    book.open_accounts([{"strategy": "S", "timeframe": "5m", "kind": "strategy"}], 0)
    probe = FillProbe(depth, S.slippage_frac)
    run = Runner3(book, FakeService(10 * MIN), store, None, V3_SYMBOLS, now,
                  lambda: {"BTCUSDT": (100.1, 100.2)}, fills=probe)
    return store, book, run, probe


def _rows(store):
    return [json.loads(r[0]) for r in store.conn.execute("SELECT data FROM fill_costs ORDER BY id")]


def test_an_entry_and_its_stop_exit_are_priced_on_the_book_without_changing_the_fill(tmp_path):
    depth = Depth()
    clock = {"now": 10 * MIN + 5_000}
    store, book, run, probe = _run(tmp_path, depth, lambda: clock["now"])
    run.process(steps(0, 11))
    p = book.engines["S@5m"].position
    assert p is not None and p.entry_price == 100.2 * (1 + S.slippage_frac)      # the engine's fill as before
    [e] = _rows(store)
    assert (e["event"], e["symbol"], e["order_side"], e["status"]) == ("entry", "BTCUSDT", 1, "ok")
    assert e["notional"] == pytest.approx(p.qty * p.entry_price) and e["notional"] > 100.2  # walks past level 1
    assert e["best"] == 100.2 and e["slip_best"] > 0 and e["enough"] and e["assumed_slip"] == S.slippage_frac
    assert depth.calls == ["BTCUSDT"]
    # a bar through the stop: the exit is a sell, priced on the bids
    clock["now"] = 11 * MIN + 5_000
    crash = {s: Bar(s, 11 * MIN, 12 * MIN - 1, 100.0, 100.0, 90.0, 91.0, volume=1.0) for s in V3_SYMBOLS}
    run.process([(11 * MIN, crash, {})])
    assert book.engines["S@5m"].position is None
    x = _rows(store)[-1]
    assert (x["event"], x["order_side"], x["status"], x["best"]) == ("exit", -1, "ok", 100.1)
    assert summary(_rows(store))["rows"][0]["orders"] == 1


def test_replayed_steps_and_a_failed_book_are_recorded_but_never_stop_the_bot(tmp_path):
    store, book, run, probe = _run(tmp_path, Depth(), lambda: 10 * MIN + 3_600_000)    # an hour behind
    run.process(steps(0, 11))
    assert [r["status"] for r in _rows(store)] == ["stale"]
    (other := tmp_path / "b").mkdir()
    store2, book2, run2, probe2 = _run(other, Depth(fail=True))
    run2.process(steps(0, 11))
    assert book2.engines["S@5m"].position is not None
    [r] = _rows(store2)
    assert r["status"] == "no_book" and "down" in r["error"] and probe2.errors == 1


def test_the_nightly_report_summarises_the_day(tmp_path):
    from paperbot.daily3 import fill_cost_report
    store, book, run, probe = _run(tmp_path, Depth())
    run.process(steps(0, 11))
    store.commit()
    rep = fill_cost_report(store.conn, 0, 3_600_000)
    assert rep["recorded"] == 1 and rep["without_book"] == 0
    [row] = rep["rows"]
    assert (row["symbol"], row["event"], row["orders"], row["assumed"]) == ("BTCUSDT", "entry", 1, S.slippage_frac)
    import sqlite3
    assert fill_cost_report(sqlite3.connect(":memory:"), 0, 1) is None        # a database from before the table


def test_an_extra_accounts_fill_never_fetches_an_order_book(tmp_path):
    """An extra account's entry or exit reuses a book fetched for the 195 in the same step, else it is recorded
    as 'skipped': a fetch runs before the boundary's 195 compute and would move their ref_time / delay_ms."""
    from paperbot import Signal
    depth = Depth()
    store = Store3(str(tmp_path / "x.db"))
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store)
    book.open_accounts([{"strategy": "S", "timeframe": "5m", "kind": "strategy"},
                        {"strategy": "S", "timeframe": "5m", "kind": "copy", "account_id": "S@5m~c1",
                         "parent": "S@5m"},
                        {"strategy": "NL1", "timeframe": "5m", "kind": "newlab", "account_id": "NL1@5m"}], 0)
    run = Runner3(book, FakeService(10 * MIN), store, None, V3_SYMBOLS, lambda: 10 * MIN + 5_000,
                  lambda: {"BTCUSDT": (100.1, 100.2)}, fills=FillProbe(depth, S.slippage_frac))
    run.process(steps(0, 10))                     # the 195's S@5m gets its BTC signal at the 10m boundary

    def sig(sym, aid):
        return Signal(ts=10 * MIN - 1, symbol=sym, timeframe="5m", strategy_id=aid.split("@")[0], side=1,
                      stop_price=0.0, tier="best", atr=0.2, meta={"stop_dist": 0.4, "ref_price": 100.2,
                                                                  "ref_time": 10 * MIN, "account": aid})
    book.submit("S@5m~c1", sig("BTCUSDT", "S@5m~c1"))
    book.submit("NL1@5m", sig("ETHUSDT", "NL1@5m"))
    run.process(steps(10, 11))                    # all three enter at minute 10
    rows = {r["account_id"]: r for r in _rows(store)}
    assert depth.calls == ["BTCUSDT"]             # only the original account's event fetched a book
    assert rows["S@5m"]["status"] == "ok"
    assert rows["S@5m~c1"]["status"] == "ok" and rows["S@5m~c1"]["best"] == 100.2   # the 195's book, reused
    assert rows["NL1@5m"]["status"] == "skipped" and rows["NL1@5m"]["event"] == "entry"
    assert all(book.engines[a].position is not None for a in ("S@5m", "S@5m~c1", "NL1@5m"))


# ---------------------------------------------------------------------------- live bars (option 3a: records only)
def _live_bars(store):
    return store.conn.execute("SELECT ts, symbol, open, high, low, close, volume, processed_at FROM live_bars "
                              "ORDER BY ts, symbol").fetchall()


def test_the_bars_live_stepped_on_are_recorded_once_per_coin_per_step_from_the_195s_call_only(tmp_path):
    """One live_bars row per coin per stepped minute, written by the 195's FillProbe call (fetch=True); the extras'
    call (fetch=False) adds none, fill_costs keeps only the entry / exit rows."""
    depth = Depth()
    store = Store3(str(tmp_path / "lb.db"))
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store)
    book.open_accounts([{"strategy": "S", "timeframe": "5m", "kind": "strategy"},
                        {"strategy": "S", "timeframe": "5m", "kind": "copy", "account_id": "S@5m~c1",
                         "parent": "S@5m"}], 0)
    probe = FillProbe(depth, S.slippage_frac)
    run = Runner3(book, FakeService(10 * MIN), store, None, V3_SYMBOLS, lambda: 11 * MIN + 1_234,
                  lambda: {"BTCUSDT": (100.1, 100.2)}, fills=probe)
    st = steps(0, 11)
    run.process(st)
    rows = _live_bars(store)
    assert len(rows) == 11 * len(V3_SYMBOLS) == len({(r[0], r[1]) for r in rows})
    by = {(r[0], r[1]): r for r in rows}
    for ts, bars, _ in st:
        for sym, b in bars.items():
            assert by[(ts, sym)][2:7] == (b.open, b.high, b.low, b.close, b.volume)
            assert by[(ts, sym)][7] == 11 * MIN + 1_234                 # the runner's clock when it handled the step
    [e] = _rows(store)                                                  # fill_costs: the entry only, as before
    assert e["event"] == "entry" and depth.calls == ["BTCUSDT"]
    # the extras' call never returns bar rows; the 195's call returns them even without an entry or exit
    ts, bars, _ = steps(11, 12)[0]
    assert probe.after(ts, {}, {}, bars, 0, fetch=False) == []
    assert [r["event"] for r in probe.after(ts, {}, {}, bars, 0)] == ["bar"] * len(V3_SYMBOLS)


def test_a_failing_live_bar_record_never_raises_and_never_changes_trading(tmp_path):
    from paperbot.engine import engine_state

    def world(name, fills=True):
        (d := tmp_path / name).mkdir()
        store = Store3(str(d / "p.db"))
        book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store)
        book.open_accounts([{"strategy": "S", "timeframe": "5m", "kind": "strategy"}], 0)
        probe = FillProbe(Depth(), S.slippage_frac) if fills else None
        return store, book, Runner3(book, FakeService(10 * MIN), store, None, V3_SYMBOLS, lambda: 11 * MIN,
                                    lambda: {"BTCUSDT": (100.1, 100.2)}, fills=probe), probe

    crash = [(11 * MIN, {s: Bar(s, 11 * MIN, 12 * MIN - 1, 100.0, 100.0, 90.0, 91.0, volume=1.0)
                         for s in V3_SYMBOLS}, {})]
    control_store, control, crun, _ = world("control", fills=False)
    crun.process(steps(0, 11))
    crun.process(crash)
    want = {a: engine_state(e) for a, e in control.engines.items()}
    assert control_store.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1

    # 1) the live_bars insert fails (table gone): fill costs still recorded, one WARN, trading identical
    store, book, run, probe = world("table_gone")
    store.conn.execute("DROP TABLE live_bars")
    run.process(steps(0, 11))
    run.process(crash)
    assert {a: engine_state(e) for a, e in book.engines.items()} == want
    assert [r["event"] for r in _rows(store)] == ["entry", "exit"]
    assert store.live_bar_errors == 12 and probe.errors == 0
    assert [t for (t,) in store.conn.execute("SELECT text FROM alerts WHERE text LIKE 'live bar record failed%'")] \
        and store.conn.execute("SELECT COUNT(*) FROM alerts WHERE text LIKE 'live bar%'").fetchone()[0] == 1

    # 2) the whole record call raises: the runner goes on (one WARN per failed step), trading identical
    store, book, run, probe = world("store_down")

    def boom(rows):
        raise RuntimeError("disk full")
    store.fill_costs = boom
    run.process(steps(0, 11))
    run.process(crash)
    assert {a: engine_state(e) for a, e in book.engines.items()} == want

    # 3) a bar that cannot be read: no bar rows, the entry / exit rows unchanged
    class Broken:
        @property
        def close_time(self):
            raise ValueError("bad bar")
    p = FillProbe(Depth(), S.slippage_frac)
    assert p.after(0, {}, {}, {"BTCUSDT": Broken()}, 0) == [] and p.bar_errors == 1
