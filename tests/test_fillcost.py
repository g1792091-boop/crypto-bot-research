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
