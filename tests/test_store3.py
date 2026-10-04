"""Store3 (paperbot/store3.py): the live_bars record (option 3a of the 2026-10-03 parity diagnosis)."""

import json
import sqlite3

from paperbot import Bar
from paperbot.fillcost import bar_rows
from paperbot.store3 import Store3

MIN = 60_000


def _bar(sym, ts, lo=99.0, vol=5.0):
    return Bar(sym, ts, ts + MIN - 1, 100.0, 101.0, lo, 100.5, 100.1, 101.1, 98.9, 100.6, volume=vol)


def test_fill_costs_sends_bar_rows_to_live_bars_and_keeps_the_first_record_of_a_minute(tmp_path):
    st = Store3(str(tmp_path / "p.db"))
    cost = {"ts": 0, "account_id": "A@5m", "symbol": "BTCUSDT", "event": "entry", "status": "ok",
            "notional": 100.0, "slip_best": 0.0001}
    st.fill_costs([cost] + bar_rows(0, {"BTCUSDT": _bar("BTCUSDT", 0), "ETHUSDT": _bar("ETHUSDT", 0)}, 61_500))
    st.fill_costs(bar_rows(0, {"BTCUSDT": _bar("BTCUSDT", 0, lo=90.0)}, 99_000))     # a second record: ignored
    st.commit()
    assert [json.loads(d)["event"] for (d,) in st.conn.execute("SELECT data FROM fill_costs")] == ["entry"]
    rows = st.conn.execute("SELECT ts, symbol, open, high, low, close, volume, mark_open, mark_high, mark_low, "
                           "mark_close, close_time, processed_at FROM live_bars ORDER BY symbol").fetchall()
    assert rows == [(0, "BTCUSDT", 100.0, 101.0, 99.0, 100.5, 5.0, 100.1, 101.1, 98.9, 100.6, MIN - 1, 61_500),
                    (0, "ETHUSDT", 100.0, 101.0, 99.0, 100.5, 5.0, 100.1, 101.1, 98.9, 100.6, MIN - 1, 61_500)]
    from paperbot.daily3 import fill_cost_report
    assert fill_cost_report(st.conn, 0, MIN)["recorded"] == 1                         # bar rows are not fill costs


def test_an_older_database_gets_the_table_and_a_failed_insert_is_swallowed(tmp_path):
    path = str(tmp_path / "old.db")
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE alerts (ts INTEGER NOT NULL, level TEXT NOT NULL, text TEXT NOT NULL)")
    c.commit()
    c.close()
    st = Store3(path)
    assert st.conn.execute("SELECT COUNT(*) FROM live_bars").fetchone()[0] == 0
    st.live_bars([{"ts": 0, "symbol": "BTCUSDT", "open": None, "high": 1, "low": 1, "close": 1,
                   "processed_at": 5}])                                    # an incomplete row is skipped (OR IGNORE)
    assert st.conn.execute("SELECT COUNT(*) FROM live_bars").fetchone()[0] == 0 and st.live_bar_errors == 0
    st.conn.execute("DROP TABLE live_bars")                                 # the insert itself fails: never raised
    st.live_bars(bar_rows(0, {"BTCUSDT": _bar("BTCUSDT", 0)}, 61_000))
    st.live_bars(bar_rows(MIN, {"BTCUSDT": _bar("BTCUSDT", MIN)}, 121_000))
    assert st.live_bar_errors == 2
    assert st.conn.execute("SELECT level FROM alerts").fetchall() == [("WARN",)]    # one alert, the first time
