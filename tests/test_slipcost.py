"""Realistic stop slippage and the cost at a larger size (paperbot/slipcost.py, daily3 items 4 and 5): synthetic
aggregate trades from a fake REST client, fake order books. Records only; no fill changes."""

import json
import sqlite3

import pytest

import paperbot.daily3 as D
from paperbot import slipcost as SC
from paperbot.config import v3_settings
from paperbot.notify import ListNotifier
from paperbot.store3 import Store3

MIN = 60_000
S = v3_settings()
SLIP = S.slippage_frac
T0 = 30 * MIN                    # the exit minute


def tr(t, p, q=1.0, sell=True):
    """(ms, price, qty, buyer_is_maker): ``sell`` = a taker sell (what a long's stop exit is)."""
    return (T0 + t, float(p), float(q), sell)


# ---------------------------------------------------------------------------- 1. stop_fill / stop_row
def test_gap_through_the_stop_fills_at_the_first_trade_and_walks_the_next_sells():
    trades = [tr(100, 99.50, 2), tr(300, 99.40, 3, sell=False), tr(400, 99.30, 3), tr(9_000, 90.0, 50)]
    f = SC.stop_fill(trades, side=1, stop=100.0, qty=4.0, start_ms=T0)
    assert f["status"] == "ok" and f["first_px"] == 99.50 and f["trigger"]["ms_into_minute"] == 100
    # after the trigger: the buy at 99.40 is not liquidity a sell takes; 3 at 99.30 cover 3 of 4 -> thin
    assert not f["walk"]["covered"] and f["thin"] and f["walk"]["trades"] == 1
    assert f["est_px"] == pytest.approx(99.30)                     # the rest at the worst price seen
    assert f["walk"]["qty_seen"] == 3                               # the trade 8.9 s later is outside the window
    f2 = SC.stop_fill(trades, side=1, stop=100.0, qty=3.0, start_ms=T0)
    assert f2["walk"]["covered"] and not f2["thin"] and f2["est_source"] == "trades"
    assert f2["est_px"] == pytest.approx(99.30)
    t = {"account_id": "X@1h", "strategy_id": "X", "timeframe": "1h", "symbol": "BTCUSDT", "side": 1,
         "stop_price": 100.0, "qty": 3.0, "exit_price": 99.50 * (1 - SLIP), "entry_price": 101.0, "margin": 30.0,
         "exit_reason": "SL", "exit_time": T0, "entry_time": T0 - 10 * MIN}
    r = SC.stop_row(t, f2, SLIP)
    assert r["status"] == "ok" and r["assumed_bps"] == pytest.approx(2.0)
    assert r["paper_bps"] == pytest.approx((100 - 99.50 * (1 - SLIP)) / 100 * 1e4)   # the open-gap fill
    assert r["first_bps"] == pytest.approx(50.0) and r["real_bps"] == pytest.approx(70.0)
    assert r["diff_usd"] == pytest.approx(3.0 * (99.50 * (1 - SLIP) - 99.30))         # real costs more
    assert r["multiples"]["2"]["covered"] is False


def test_a_short_stop_takes_the_buys_and_a_book_read_covers_thin_trades():
    trades = [tr(10, 99.0, 1, sell=False), tr(20_000, 100.2, 1, sell=False), tr(20_050, 100.25, 1, sell=True),
              tr(20_100, 100.4, 0.5, sell=False)]
    f = SC.stop_fill(trades, side=-1, stop=100.0, qty=2.0, start_ms=T0)
    assert f["first_px"] == 100.2 and f["thin"]                       # only 0.5 of 2 bought after the trigger
    assert f["est_px"] == pytest.approx(100.4)
    g = SC.stop_fill(trades, side=-1, stop=100.0, qty=2.0, start_ms=T0, depth_slip=0.001)
    assert not g["thin"] and g["est_source"] == "book" and g["est_px"] == pytest.approx(100.2 * 1.001)
    h = SC.stop_fill(trades, side=-1, stop=100.0, qty=0.5, start_ms=T0, depth_slip=0.0001)
    # both covered: the more adverse (higher for a short's buy) wins
    assert h["est_source"] == "trades" and h["est_px"] == pytest.approx(100.4)


def test_no_trade_through_the_stop_and_no_trades():
    trades = [tr(10, 100.5), tr(20, 100.1)]
    assert SC.stop_fill(trades, 1, 100.0, 1.0, T0)["status"] == "no_trade_through_stop"
    assert SC.stop_fill([], 1, 100.0, 1.0, T0)["status"] == "no_trades"
    # a trade through the stop before the exit minute does not count
    assert SC.stop_fill([(T0 - 5, 99.0, 1.0, True)], 1, 100.0, 1.0, T0)["status"] == "no_trade_through_stop"
    r = SC.stop_row({"symbol": "BTCUSDT", "side": 1, "stop_price": 100.0, "qty": 1.0, "exit_price": 99.98,
                     "entry_price": 101.0, "exit_reason": "SL", "exit_time": T0 + MIN - 1, "entry_time": 0},
                    {"status": "api_error", "error": "down"}, SLIP)
    assert r["status"] == "api_error" and r["error"] == "down" and "real_bps" not in r


def test_a_liquidation_compares_the_lost_margin_with_a_stop_capped_at_the_margin():
    trades = [tr(100, 99.0, 10)]
    f = SC.stop_fill(trades + [tr(200, 98.9, 10)], 1, 100.0, 5.0, T0)
    t = {"symbol": "BTCUSDT", "side": 1, "stop_price": 100.0, "qty": 5.0, "exit_price": 95.0, "entry_price": 101.0,
         "margin": 20.0, "exit_reason": "LIQ", "exit_time": T0 + MIN - 1, "entry_time": 0}
    r = SC.stop_row(t, f, SLIP)
    # paper lost the margin (20); a real stop at 98.9 loses 5 x 2.1 = 10.5: real costs 9.5 less
    assert r["diff_usd"] == pytest.approx(-20.0 + 10.5)


def test_summary_per_strategy_timeframe_coin():
    rows = [{"status": "ok", "strategy": "A", "timeframe": "1h", "symbol": "BTCUSDT", "exit_reason": "SL",
             "paper_bps": 2.0, "real_bps": x, "diff_usd": d, "account_id": f"A{k}", "exit_time": k, "notional": 1e4,
             "est_source": "trades"} for k, (x, d) in enumerate([(3.0, 1.0), (5.0, 3.0), (40.0, 30.0)])]
    rows.append({"status": "api_error", "strategy": "B", "timeframe": "4h", "symbol": "ETHUSDT",
                 "exit_reason": "LOCK"})
    s = SC.summarize_stops(rows, SLIP)
    assert s["exits"] == 4 and s["status"] == {"ok": 3, "api_error": 1} and s["assumed_bps"] == 2.0
    o = s["overall"]
    assert (o["measured"], o["real_bps_median"], o["real_bps_p90"], o["real_bps_worst"]) == (3, 5.0, 40.0, 40.0)
    assert o["diff_usd_total"] == 34.0 and o["extra_bps_median"] == 3.0
    assert s["by_strategy"]["B"]["measured"] == 0 and s["by_timeframe"]["1h"]["exits"] == 3
    assert s["by_symbol"]["BTCUSDT"]["diff_usd_worst"] == 30.0 and s["worst"][0]["account_id"] == "A2"


# ---------------------------------------------------------------------------- 2. cost at a larger size
ASKS = [[100.0, 1.0], [100.1, 2.0], [100.5, 5.0]]          # $802.7 in all


def test_size_walk_on_a_fake_book_enough_and_too_thin():
    w = SC.walk_multiples(ASKS, 100.0, +1, 100.0, 99.95)
    vwap = 200.0 / (1.0 + 100.0 / 100.1)                           # 1 at 100.0, then $100 at 100.1
    assert w["2"]["status"] == "ok" and w["2"]["slip_best"] == pytest.approx((vwap - 100) / 100, rel=1e-9)
    assert w["5"]["status"] == "ok" and w["5"]["levels"] == 3
    total = 100.0 + 200.2 + 502.5
    assert w["10"]["status"] == SC.THIN and w["10"]["covered_notional"] == pytest.approx(total)


def test_size_costs_from_recorded_rows():
    base = {"ts": T0, "symbol": "SOLUSDT", "order_side": -1, "book_ts": 7, "status": "ok", "event": "exit"}
    rows = [
        {**base, "account_id": "A@1h", "notional": 1_000.0, "slip_best": 0.0001, "enough": True,
         "filled_notional": 1_000.0},
        {**base, "account_id": "B@15m", "notional": 4_000.0, "slip_best": 0.0005, "enough": True,
         "filled_notional": 4_000.0},
        {**base, "account_id": "C@1h", "notional": 30_000.0, "slip_best": 0.004, "enough": False,
         "filled_notional": 20_000.0},       # the whole recorded depth of this read: 20k
        {**base, "ts": T0 + MIN, "account_id": "D@1h", "notional": 500.0, "slip_best": 0.0, "enough": True,
         "filled_notional": 500.0},
        {**base, "ts": T0 + 2 * MIN, "account_id": "E@1h", "symbol": "BTCUSDT", "order_side": 1, "notional": 100.0,
         "slip_best": 0.0, "enough": True, "filled_notional": 100.0, "book": ASKS, "best": 100.0, "spread": 0.001},
        {**base, "account_id": "F@1h", "status": "no_book", "notional": 9.0, "slip_best": None},
    ]
    by = {r["account_id"]: r["multiples"] for r in SC.size_cost_rows(rows)}
    assert "F@1h" not in by
    assert by["A@1h"]["2"] == {"status": SC.BOUNDED, "slip_low": 0.0001, "slip_high": 0.0005}   # B's 4k bounds 2k
    assert by["A@1h"]["5"]["status"] == SC.NOT_RECORDED and by["A@1h"]["5"]["slip_low"] == 0.0005
    assert by["B@15m"]["5"]["status"] == SC.NOT_RECORDED                     # 20k: exactly the recorded depth
    assert by["B@15m"]["10"]["status"] == SC.THIN and by["B@15m"]["10"]["recorded_depth"] == 20_000.0  # 40k > 20k
    assert all(m["status"] == SC.THIN for m in by["C@1h"].values())          # not even 1x was covered
    assert by["D@1h"]["2"]["status"] == SC.NOT_RECORDED                      # alone in its read
    assert by["E@1h"]["5"]["status"] == "ok" and by["E@1h"]["10"]["status"] == SC.THIN    # walked exactly
    s = SC.summarize_size_costs(rows, {"A@1h": "1h"})
    cells = {(c["symbol"], c["timeframe"]): c for c in s["rows"]}
    sol = cells[("SOLUSDT", "1h")]
    assert sol["orders"] == 3 and sol["x10"]["too_thin"] == 1 and sol["x2"]["bounded"] == 1
    assert cells[("BTCUSDT", "1h")]["x5"]["exact"] == 1 and cells[("SOLUSDT", "15m")]["x10"]["too_thin"] == 1


# ---------------------------------------------------------------------------- daily3: fetch, caps, failures
class Rest:
    """The public aggTrades endpoint (``trades``: symbol -> [(ms, price, qty, buyer_is_maker)])."""

    def __init__(self, trades=None, fail=False):
        self.trades = {s: [{"a": k + 1, "p": str(p), "q": str(q), "m": m, "T": t}
                           for k, (t, p, q, m) in enumerate(sorted(rows))] for s, rows in (trades or {}).items()}
        self.calls, self.fail = [], fail

    def _get(self, path, params):
        assert path == "/fapi/v1/aggTrades"
        self.calls.append(dict(params))
        if self.fail:
            raise ConnectionError("down")
        rows = self.trades.get(params["symbol"], [])
        if "fromId" in params:
            rows = [r for r in rows if r["a"] >= params["fromId"]]
        else:
            rows = [r for r in rows if params["startTime"] <= r["T"] <= params["endTime"]]
        return rows[:params["limit"]]


def paper(tmp_path, exits, depth=None):
    st = Store3(str(tmp_path / "paper3.db"))
    for k, (aid, sym, side, stop, qty, px, reason, t) in enumerate(exits):
        strat, tf = aid.split("@")
        st.add_account(aid, strat, tf, "strategy", 0, "v3")
        data = {"strategy_id": strat, "timeframe": tf, "symbol": sym, "side": side, "stop_price": stop, "qty": qty,
                "exit_price": px, "entry_price": stop * (1 + side * 0.01), "margin": 1e6, "exit_reason": reason,
                "exit_time": t, "entry_time": t - 10 * MIN - k, "pnl": -1.0}
        st.conn.execute("INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, "
                        "roe, equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (aid, sym, data["entry_time"], t, reason, 10, -1.0, -0.1, 1.0, json.dumps(data)))
    if depth:
        st.fill_costs(depth)
    st.commit()
    return st.conn


def exits3():
    # BTC: two accounts exit in minute 30 (gap through 100), ETH one in minute 40 (in the minute), and a TP (ignored)
    return [("A@1h", "BTCUSDT", 1, 100.0, 2.0, 99.5 * (1 - SLIP), "SL", T0),
            ("B@15m", "BTCUSDT", 1, 99.8, 1.0, 99.5 * (1 - SLIP), "LOCK", T0),
            ("C@1h", "ETHUSDT", -1, 50.0, 4.0, 50.0 * (1 + SLIP), "SL", 40 * MIN + MIN - 1),
            ("D@1h", "ETHUSDT", 1, 40.0, 1.0, 45.0, "TP", 40 * MIN + MIN - 1)]


def world_trades():
    return {"BTCUSDT": [(T0 + 50, 99.5, 1.0, True), (T0 + 80, 99.6, 5.0, False), (T0 + 120, 99.4, 2.0, True),
                        (T0 + 6_000, 99.0, 1.0, True)],
            "ETHUSDT": [(40 * MIN + 10, 49.9, 1.0, False), (40 * MIN + 31_000, 50.01, 1.0, False),
                        (40 * MIN + 31_500, 50.05, 10.0, False)]}


def test_daily3_reads_each_coin_minute_once_and_records_every_stop_exit(tmp_path):
    depth = [{"ts": 40 * MIN, "account_id": "C@1h", "symbol": "ETHUSDT", "event": "exit", "status": "ok",
              "notional": 200.0, "slip_best": 0.002, "order_side": 1, "enough": True}]
    conn = paper(tmp_path, exits3(), depth)
    rest, naps = Rest(world_trades()), []
    rows, s = D.stop_slippage(conn, rest, S, "1970-01-01", 0, D.DAY_MS, sleep=naps.append)
    assert sorted(c["symbol"] for c in rest.calls) == ["BTCUSDT", "ETHUSDT"]       # one read per coin-minute
    assert rest.calls[0]["symbol"] == "BTCUSDT"                  # the larger exit notional first (298.5 vs 200)
    by = {r["account_id"]: r for r in rows}
    assert set(by) == {"A@1h", "B@15m", "C@1h"} and all(r["status"] == "ok" for r in rows)
    a = by["A@1h"]
    assert a["first_px"] == 99.5 and a["est_px"] == pytest.approx(99.4) and a["est_source"] == "trades"
    assert a["key"] == f"A@1h|BTCUSDT|{T0 - 10 * MIN}|{T0}" and a["strategy"] == "A" and a["timeframe"] == "1h"
    assert by["B@15m"]["first_px"] == 99.5                        # the same trades, its own stop
    c = by["C@1h"]                                                # short: buys, the book read is more adverse
    assert c["first_px"] == 50.01 and c["est_source"] == "book" and c["est_px"] == pytest.approx(50.01 * 1.002)
    assert c["depth_slip"] == 0.002 and c["real_bps"] == pytest.approx((50.01 * 1.002 - 50) / 50 * 1e4)
    assert s["overall"]["measured"] == 3 and s["api"]["pages"] == 2 and s["api"]["read"] == 2
    assert naps == [D.STOP_PAGE_PAUSE_S]                          # paced between the coin-minutes


def test_daily3_api_failure_and_caps_are_recorded_never_fatal(tmp_path, monkeypatch):
    conn = paper(tmp_path, exits3())
    rows, s = D.stop_slippage(conn, Rest(fail=True), S, "1970-01-01", 0, D.DAY_MS, sleep=lambda x: None)
    assert [r["status"] for r in rows] == ["api_error"] * 3 and "down" in rows[0]["error"]
    assert s["overall"]["measured"] == 0 and s["status"] == {"api_error": 3}
    monkeypatch.setattr(D, "STOP_MAX_MINUTES", 1)
    rows, s = D.stop_slippage(conn, Rest(world_trades()), S, "1970-01-01", 0, D.DAY_MS, sleep=lambda x: None)
    assert s["status"] == {"ok": 2, "cap": 1}                                 # BTC's minute read, ETH's not
    monkeypatch.setattr(D, "STOP_MAX_MINUTES", 150)
    monkeypatch.setattr(D, "STOP_MAX_FAILS", 1)
    rest = Rest(fail=True)
    rows, s = D.stop_slippage(conn, rest, S, "1970-01-01", 0, D.DAY_MS, sleep=lambda x: None)
    assert len(rest.calls) == 1 and s["status"] == {"api_error": 3}            # stopped asking after one failure


def test_daily3_pages_by_id_and_stops_once_the_window_is_read(tmp_path, monkeypatch):
    conn = paper(tmp_path, exits3()[:1])
    monkeypatch.setattr(D, "AGG_LIMIT", 2)
    many = world_trades()["BTCUSDT"] + [(T0 + 7_000 + k, 99.0, 1.0, True) for k in range(20)]
    rest = Rest({"BTCUSDT": many})
    rows, s = D.stop_slippage(conn, rest, S, "1970-01-01", 0, D.DAY_MS, sleep=lambda x: None)
    # page 1: trigger at +50 (and +80); page 2: +120, +6000 > trigger + 5 s -> enough, no third page
    assert [("fromId" in c) for c in rest.calls] == [False, True] and rows[0]["status"] == "ok"
    monkeypatch.setattr(D, "STOP_MAX_PAGES", 1)
    monkeypatch.setattr(D, "AGG_LIMIT", 1)
    rows, s = D.stop_slippage(conn, Rest({"BTCUSDT": many}), S, "1970-01-01", 0, D.DAY_MS, sleep=lambda x: None)
    assert rows[0]["status"] == "api_error" and "more than 1 pages" in rows[0]["error"]


def test_run_day_writes_stop_slips_and_the_report_line(tmp_path, monkeypatch):
    from test_daily3_early_kline import BR, live_world
    store, steps, stop = live_world(tmp_path, real=False)
    monkeypatch.setattr(D, "fetch_steps", lambda r, syms, a, b: [x for x in steps if a <= x[0] < b])
    trades = {r[1]: json.loads(r[2]) for r in store.conn.execute("SELECT id, account_id, data FROM trades")}
    a, b = trades["A@15m"], trades["B@15m"]

    class R(Rest):
        def server_time(self):
            return D.DAY_MS + 2 * MIN
    ma, mb = D._minute(a["exit_time"]), D._minute(b["exit_time"])
    rest = R({"BTCUSDT": [(ma + 5, a["stop_price"] - 0.03, 100.0, True)],
              "ETHUSDT": [(mb + 30_000, b["stop_price"] - 0.01, 100.0, True)]})
    out = sqlite3.connect(str(tmp_path / "daily3.db"))
    out.executescript(D.SCHEMA)
    out.execute("INSERT INTO stop_slips VALUES ('old', '1970-01-01', 'Z', NULL, NULL, 'BTCUSDT', 'SL', 0, 'ok', "
                "NULL, NULL, NULL, '{}')")                      # a re-run replaces the day's rows
    rep = D.run_day(store.conn, out, rest, S, BR, {}, "1970-01-01", stop_slip=True, sleep=lambda x: None)
    got = {r[0]: r[1:] for r in out.execute("SELECT account_id, status, exit_reason, real_bps FROM stop_slips")}
    assert set(got) == {"A@15m", "B@15m"} and all(v[0] == "ok" for v in got.values())
    sl = rep["stop_slippage"]
    assert sl["overall"]["measured"] == 2 and set(sl["by_symbol"]) == {"BTCUSDT", "ETHUSDT"}
    assert "size_costs" in rep and json.loads(out.execute("SELECT data FROM reports").fetchone()[0])[
        "stop_slippage"]["overall"]["measured"] == 2
    info = D.notify_report(rep, ListNotifier())[-1][1]
    assert "손절 체결 추정 2건: 중간 " in info and "(paper " in info and "paper보다 $" in info
    # without the flag (the tests of the other parts): no aggTrades for it, no rows written
    (tmp_path / "b").mkdir()
    out2 = sqlite3.connect(str(tmp_path / "b" / "daily3.db"))
    out2.executescript(D.SCHEMA)
    rest2 = R({})
    rep2 = D.run_day(store.conn, out2, rest2, S, BR, {}, "1970-01-01")
    assert "stop_slippage" not in rep2 and rest2.calls == []
    assert out2.execute("SELECT COUNT(*) FROM stop_slips").fetchone()[0] == 0


def test_week_packet_reads_both_databases_read_only(tmp_path):
    conn = paper(tmp_path, exits3(), [{"ts": T0, "account_id": "A@1h", "symbol": "BTCUSDT", "event": "exit",
                                       "status": "ok", "notional": 199.0, "slip_best": 0.0001, "order_side": -1,
                                       "enough": True, "filled_notional": 199.0}])
    rows, _ = D.stop_slippage(conn, Rest(world_trades()), S, "1970-01-01", 0, D.DAY_MS, sleep=lambda x: None)
    out = sqlite3.connect(str(tmp_path / "daily3.db"))
    out.executescript(D.SCHEMA)
    D.write_stop_slips(out, "1970-01-01", rows)
    out.commit()
    p = SC.week_packet(out, conn, 0, D.DAY_MS)
    assert p["stop_slippage"]["overall"]["measured"] == 3 and p["size_costs"]["rows"][0]["symbol"] == "BTCUSDT"
    assert "how_to_read" in p
    empty = sqlite3.connect(":memory:")
    q = SC.week_packet(empty, empty, 0, 1)
    assert "note" in q["stop_slippage"] and "note" in q["size_costs"]
    assert SC.week_packet(None, None, 0, 1)["stop_slippage"]["note"]
