"""fillcost.FillProbe keeps the walked side of the order book with each row (``book``), so the nightly check walks
2x / 5x / 10x the paper size exactly (slipcost.size_cost_rows); records only, the fill is unchanged."""

import json

import pytest

from paperbot import fillcost as FC
from paperbot.runinfo import EXTRA_FILES, EXTRA_GATE_FILES, SHARED_SIGNAL_FILES, TRADING_FILES
from paperbot.slipcost import size_cost_rows
from test_fillcost import Depth, _rows, _run
from test_live3 import S, steps


def test_fillcost_is_not_a_trading_or_gate_file():
    lists = TRADING_FILES + EXTRA_FILES + EXTRA_GATE_FILES + SHARED_SIGNAL_FILES
    assert "paperbot/fillcost.py" not in lists and "paperbot/slipcost.py" not in lists


def test_book_levels_stop_once_ten_times_the_size_is_covered_and_at_the_cap():
    lv = [("100", "1"), ("101", "2"), ("102", "50"), ("103", "50")]
    # 10 x 30 = 300 of notional: 100 + 202 covers it after two levels
    assert FC.book_levels(lv, 30.0) == [[100.0, 1.0], [101.0, 2.0]]
    assert FC.book_levels(lv, 1e9) == [[100.0, 1.0], [101.0, 2.0], [102.0, 50.0], [103.0, 50.0]]
    assert len(FC.book_levels([(1, 1)] * 500, 1e9)) == FC.BOOK_KEEP_MAX == FC.LIMIT
    assert FC.book_levels([], 10.0) == []


def test_each_priced_row_carries_the_levels_it_walked(tmp_path):
    depth = Depth()
    store, book, run, probe = _run(tmp_path, depth)
    run.process(steps(0, 11))
    p = book.engines["S@5m"].position
    assert p is not None and p.entry_price == 100.2 * (1 + S.slippage_frac)      # the fill is unchanged
    [e] = _rows(store)
    assert e["status"] == "ok" and e["book"] == [[100.2, 1.0], [100.3, 1000.0]]   # the asks, best first
    assert all(isinstance(x, float) for lv in e["book"] for x in lv)
    # the nightly check now walks the larger sizes on the recorded levels instead of 'levels not recorded'
    # (the fake book holds about $100k: 2x the order is covered, 5x and 10x are honestly too thin)
    assert 100.2 < e["notional"] < 100_400 / 2
    [row] = size_cost_rows([{**e, "timeframe": "5m"}])
    m = row["multiples"]
    assert {k: v["status"] for k, v in m.items()} == {"2": "ok", "5": "book too thin", "10": "book too thin"}
    assert m["2"]["slip_best"] > e["slip_best"] > 0 and m["10"]["covered_notional"] == pytest.approx(100_400.2)


def test_a_row_without_a_book_has_no_levels(tmp_path):
    store, book, run, probe = _run(tmp_path, Depth(fail=True))
    run.process(steps(0, 11))
    [e] = _rows(store)
    assert e["status"] == "no_book" and "book" not in e


def test_the_stored_row_stays_small(tmp_path):
    store, book, run, probe = _run(tmp_path, Depth())
    run.process(steps(0, 11))
    [(data,)] = store.conn.execute("SELECT data FROM fill_costs").fetchall()
    assert len(data) < 1_000 and json.loads(data)["book"]
