"""차트 위 얹기 (chart-plus; review additions 4 · 11 · 12, owners 10/06 ~15:55 "전부 지금"): the market liquidations on the
chart (bubbles + price-bucket bars), our stop / liquidation map with "이 가격이면", and the lower panes (CVD, open interest,
funding, long / short).

- dash/more/chartplus.py: /api/v4/chartplus/liq cuts liq.db into the chart's own bars (a SELL forced order closes a LONG),
  says when the recorder started, where its stream was down, whether it went quiet, and is honest when there is no file
  or the file cannot be read; /api/v4/chartplus/series is fetched by the SERVER (a swappable FETCH), one cached answer per
  coin / kind / period, a short timeout, a failure never reads as data (ready false + 못 불러옴), the last good answer is
  kept and marked stale;
- /api/candles carries the taker-buy volume (kline field 9) the CVD pane is computed from;
- screens/chart-plus-calc.js (pure, run in node): bubble size, price rows, whatIf (DeepSeek and coin flips counted, money
  never added), stop levels, CVD (a missing bar is null, never 0), Binance series put on the candles' own times;
- the page: everything off until chosen, per device, in the '선' menu; the strips take their own column (never the names);
  a failed series draws nothing; one hook call in each chart screen; no browser call to Binance; tokens only.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot import liqstream  # noqa: E402
from paperbot.dash import app as APP  # noqa: E402
from paperbot.dash.app import create_app, hash_password  # noqa: E402
from paperbot.dash.more import chartplus as CP  # noqa: E402
from tests.test_dash import SECRET, _store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V4 = os.path.join(ROOT, "paperbot", "dash", "static", "v4")
PW = "correct horse battery"
STEP = 900
T0 = 1_790_000_100 - 1_790_000_100 % STEP          # an aligned first bar (seconds)
NOW = (T0 + 40 * STEP) * 1000


def _src(*p):
    with open(os.path.join(V4, *p), encoding="utf-8") as f:
        return f.read()


def _code(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'`])//.*$", r"\1", src)


def _liq(path, rows, conn=()):
    """rows: (symbol, trade_ts ms, side, price, qty); conn: (ts ms, event)."""
    q = sqlite3.connect(path)
    q.executescript(liqstream.SCHEMA)
    for sym, ts, side, px, qty in rows:
        q.execute("INSERT INTO liq VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (ts, ts, sym, side, "LIMIT", "IOC", qty, px, px, "FILLED", qty, qty, ts + 500))
    for ts, ev in conn:
        q.execute("INSERT INTO conn_log VALUES (?,?,?)", (ts, ev, "{}"))
    q.commit()
    q.close()


def _bar_ms(k, off=0):
    return (T0 + k * STEP) * 1000 + off


# ---------------------------------------------------------------- the liquidation bars (liq.db, read-only)
def test_nice_tick_is_a_round_step():
    assert CP.nice_tick(0.0123) == 0.02 and CP.nice_tick(7) == 10 and CP.nice_tick(1) == 1 and CP.nice_tick(12.4) == 20
    assert CP.nice_tick(0) == 1.0 and CP.nice_tick(float("nan")) == 1.0


def test_liq_bars_cut_the_charts_bars_and_a_sell_closes_a_long(tmp_path):
    path = str(tmp_path / "liq.db")
    _liq(path, [
        ("BTCUSDT", _bar_ms(-2, 0), "SELL", 100.0, 1.0),            # before the first bar: not in the answer
        ("BTCUSDT", _bar_ms(0, 1000), "SELL", 100.0, 2.0),          # bar 0 long   $200 @ 100
        ("BTCUSDT", _bar_ms(0, 5000), "SELL", 110.0, 10.0),         # bar 0 long   $1,100 @ 110 (the biggest)
        ("BTCUSDT", _bar_ms(0, 9000), "BUY", 100.0, 1.0),           # bar 0 short  $100
        ("ETHUSDT", _bar_ms(1, 100), "SELL", 10.0, 1.0),            # another coin: not in the answer
        ("BTCUSDT", _bar_ms(3, 100), "BUY", 120.0, 5.0),            # bar 3 short  $600
    ], conn=[(_bar_ms(-1), "connected")])
    r = CP.liq_bars(path, "BTCUSDT", T0, STEP, _bar_ms(4))
    assert r["ready"] and r["recorder"] and r["symbol"] == "BTCUSDT" and r["step_s"] == STEP and r["t0"] == T0
    by = {(b["t"], b["side"]): b for b in r["bars"]}
    assert set(by) == {(T0, "long"), (T0, "short"), (T0 + 3 * STEP, "short")}
    lg = by[(T0, "long")]
    assert lg["usd"] == 1300.0 and lg["n"] == 2 and lg["big"] == {"usd": 1100.0, "px": 110.0, "ts": _bar_ms(0, 5000)}
    assert lg["px"] == pytest.approx((200 * 100 + 1100 * 110) / 1300)               # the USDT-weighted price
    assert by[(T0, "short")]["usd"] == 100.0 and by[(T0 + 3 * STEP, "short")]["usd"] == 600.0
    assert r["n"] == 4
    # the price buckets: [bar index, bucket, long USDT, short USDT]; one tick is a round step
    assert r["tick"] and r["tick"] == CP.nice_tick(r["tick"])
    assert sum(c[2] for c in r["cells"]) == 1300.0 and sum(c[3] for c in r["cells"]) == 700.0
    assert {c[0] for c in r["cells"]} == {0, 3}
    # honesty: when the recorder started, that nothing is stale, the fixed words
    assert r["since_ts"] == _bar_ms(-1) and r["stale"] is False and r["gaps"] == []
    assert "우리 봇 아님" in r["note_ko"] and "1초에 1건" in r["note_ko"] and "들은 것만" in r["note_ko"]


def test_liq_bars_say_where_the_recorder_was_down_and_when_it_went_quiet(tmp_path):
    path = str(tmp_path / "liq.db")
    gap0, gap1 = _bar_ms(5), _bar_ms(7)
    _liq(path, [("BTCUSDT", _bar_ms(1), "SELL", 100.0, 1.0)],
         conn=[(_bar_ms(0), "connected"), (gap0, "disconnected"), (gap1, "connected"),
               (_bar_ms(20), "disconnected"), (_bar_ms(20) + 5_000, "connected")])      # a 5 s reconnect is not a gap
    r = CP.liq_bars(path, "BTCUSDT", T0, STEP, NOW)
    assert r["gaps"] == [[gap0, gap1]] and r["since_ts"] == _bar_ms(0)
    # a stream that is down NOW is a gap that runs to now; a recorder with no new row for 2 hours is stale
    _liq(str(tmp_path / "liq2.db"), [("BTCUSDT", _bar_ms(1), "SELL", 100.0, 1.0)], conn=[(_bar_ms(0), "connected"), (_bar_ms(30), "disconnected")])
    r2 = CP.liq_bars(str(tmp_path / "liq2.db"), "BTCUSDT", T0, STEP, NOW + 3 * 3_600_000)
    assert r2["stale"] is True and r2["gaps"] and r2["gaps"][-1] == [_bar_ms(30), NOW + 3 * 3_600_000]


def test_liq_bars_never_turn_a_missing_or_broken_file_into_no_liquidations(tmp_path):
    none = CP.liq_bars(str(tmp_path / "nope.db"), "BTCUSDT", T0, STEP, NOW)
    assert none["ready"] is False and none["recorder"] is False and "기록기" in none["why"]
    empty = str(tmp_path / "empty.db")
    _liq(empty, [("ETHUSDT", _bar_ms(1), "SELL", 10.0, 1.0)], conn=[(_bar_ms(0), "connected")])
    r = CP.liq_bars(empty, "BTCUSDT", T0, STEP, NOW)             # a recorder that heard nothing of THIS coin: ready, n 0, said so
    assert r["ready"] is True and r["n"] == 0 and r["bars"] == [] and r["since_ts"] == _bar_ms(0)
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"this is not a database" * 50)
    b = CP.liq_bars(str(bad), "BTCUSDT", T0, STEP, NOW)
    assert b["ready"] is False and b.get("failed") is True and ("읽지 못" in b["why"] or "열지 못" in b["why"])


def test_liq_bars_value_a_forced_order_like_the_market_screens_do(tmp_path):
    """USDT = the average FILL price x the FILLED quantity (a partly filled order is not its order size x its limit price),
    the same sum /api/liq and the terminal's list use."""
    path = str(tmp_path / "liq.db")
    q = sqlite3.connect(path)
    q.executescript(liqstream.SCHEMA)
    ts = _bar_ms(0, 3000)
    q.execute("INSERT INTO liq VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (ts, ts, "BTCUSDT", "SELL", "LIMIT", "IOC", 10.0, 105.0, 100.0, "FILLED", 2.0, 4.0, ts))
    q.execute("INSERT INTO liq VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (ts + 1, ts + 1, "BTCUSDT", "BUY", "LIMIT", "IOC", 3.0, 50.0, 0.0, "NEW", 0.0, 0.0, ts))
    q.commit()
    q.close()
    r = CP.liq_bars(path, "BTCUSDT", T0, STEP, NOW)
    by = {b["side"]: b for b in r["bars"]}
    assert by["long"]["usd"] == 400.0 and by["long"]["px"] == 100.0                  # 4 filled x 100 average (not 10 x 105)
    assert by["short"]["usd"] == 150.0 and by["short"]["px"] == 50.0                 # nothing filled / no average: order size x price
    # ... and the market screens' own totals agree
    market = APP.Data.liquidations(object.__new__(APP.Data), path, "BTCUSDT", 100_000_000, now_ms=NOW)
    assert market["long_usd"] == 400.0 and market["short_usd"] == 150.0


def test_liq_db_in_a_folder_with_odd_characters_is_still_read(tmp_path):
    """The path goes through the dashboard's own quoted read-only URI: a '?', '#' or '%' in a folder name never changes the file opened."""
    odd = tmp_path / "data#1?x%20y"
    odd.mkdir()
    path = str(odd / "liq.db")
    _liq(path, [("BTCUSDT", _bar_ms(1), "SELL", 100.0, 1.0)], conn=[(_bar_ms(0), "connected")])
    r = CP.liq_bars(path, "BTCUSDT", T0, STEP, NOW)
    assert r["ready"] is True and r["n"] == 1 and r["since_ts"] == _bar_ms(0)


def test_a_busy_window_gets_a_coarser_price_step_and_never_loses_its_newest_bars(tmp_path, monkeypatch):
    """The price-bar strip used to stop at 20,000 cells and silently drop the NEWEST bars; now the price step grows instead."""
    path = str(tmp_path / "liq.db")
    rows = [("BTCUSDT", _bar_ms(k, 100 + i), "SELL" if i % 2 else "BUY", 100.0 + 0.2 * (k * 7 + i), 1.0) for k in range(12) for i in range(30)]
    _liq(path, rows, conn=[(_bar_ms(0), "connected")])
    full = CP.liq_bars(path, "BTCUSDT", T0, STEP, NOW)
    assert full["coarse"] is False and len(full["cells"]) > 40
    monkeypatch.setattr(CP, "CELLS_MAX", 40)
    r = CP.liq_bars(path, "BTCUSDT", T0, STEP, NOW)
    assert r["coarse"] is True and len(r["cells"]) <= 40 and r["tick"] > full["tick"] and r["tick"] % full["tick"] == 0
    assert {c[0] for c in r["cells"]} == {c[0] for c in full["cells"]} == set(range(12))             # every bar, the newest too
    assert sum(c[2] + c[3] for c in r["cells"]) == pytest.approx(sum(c[2] + c[3] for c in full["cells"]))
    assert sum(b["usd"] for b in r["bars"]) == pytest.approx(sum(b["usd"] for b in full["bars"])) and r["capped"] is False
    # never an endless loop, even when the bars alone are more than the cap
    monkeypatch.setattr(CP, "CELLS_MAX", 3)
    assert CP.liq_bars(path, "BTCUSDT", T0, STEP, NOW)["ready"] is True


# ---------------------------------------------------------------- Binance series, fetched by the server
KL = [{"symbol": "BTCUSDT", "sumOpenInterest": "1.5", "sumOpenInterestValue": "93000.5", "timestamp": 1_000},
      {"symbol": "BTCUSDT", "sumOpenInterest": "x", "sumOpenInterestValue": "nan", "timestamp": 2_000},      # not a number: left out
      {"symbol": "BTCUSDT", "sumOpenInterest": "1", "sumOpenInterestValue": "90000", "timestamp": 500},       # older: sorted first
      "junk"]


def test_parse_series_keeps_finite_numbers_oldest_first():
    assert CP.parse_series("oi", KL) == [[500, 90000.0], [1000, 93000.5]]
    ls = [{"timestamp": 5, "longShortRatio": "1.8", "longAccount": "0.64"}, {"timestamp": 4, "longShortRatio": "0"}, {"timestamp": 3}]
    assert CP.parse_series("ls", ls) == [[5, 1.8, 0.64]]                                     # a ratio of 0 is not a ratio
    fu = [{"fundingTime": 8, "fundingRate": "0.0001"}, {"fundingTime": 4, "fundingRate": "-0.0002"}, {"fundingTime": 2, "fundingRate": "inf"}]
    assert CP.parse_series("funding", fu) == [[4, -0.0002], [8, 0.0001]]
    assert CP.parse_series("oi", None) == [] and CP.parse_series("oi", {"code": -1121}) == []


def test_series_urls_use_the_matching_binance_endpoint_and_period():
    assert CP.series_url("BTCUSDT", "oi", "15m") == "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=15m&limit=500"
    assert "/futures/data/globalLongShortAccountRatio?symbol=ETHUSDT&period=1h&limit=500" in CP.series_url("ETHUSDT", "ls", "1h")
    assert CP.series_url("SOLUSDT", "funding", "8h") == "https://fapi.binance.com/fapi/v1/fundingRate?symbol=SOLUSDT&limit=1000"
    assert CP.PERIOD_OF["1m"] == "5m" and CP.PERIOD_OF["8h"] == "6h" and CP.PERIOD_OF["1w"] == "1d" and CP.PERIOD_OF["4h"] == "4h"
    assert set(CP.PERIOD_OF) == set(CP.TF_S) and set(CP.PERIOD_OF.values()) <= set(CP.PERIOD_S)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_series_are_cached_failures_are_honest_and_the_last_good_answer_is_kept(monkeypatch):
    clock, calls, mode = Clock(), [], {"fail": None}

    def fetch(url):
        calls.append(url)
        if mode["fail"]:
            raise mode["fail"]
        return [{"timestamp": 1000 + len(calls), "sumOpenInterestValue": "100.0"}]

    monkeypatch.setattr(CP, "FETCH", fetch)
    s = CP.Series(clock=clock)
    a = s.get("BTCUSDT", "oi", "15m")
    assert a["ready"] and a["points"] == [[1001, 100.0]] and a["stale"] is False and a["period"] == "15m" and "30일" in a["note_ko"]
    clock.t += 30
    assert s.get("BTCUSDT", "oi", "15m") is not None and len(calls) == 1                     # inside the TTL: one fetch for everybody
    assert s.get("BTCUSDT", "oi", "1h")["period"] == "1h" and len(calls) == 2                  # another period is its own answer
    clock.t += 61
    mode["fail"] = TimeoutError("timed out")
    b = s.get("BTCUSDT", "oi", "15m")                                                          # expired and Binance is slow: the old points, marked
    assert b["ready"] and b["stale"] is True and b["points"] == [[1001, 100.0]] and "못 불러옴" in b["why_ko"] and "시간 초과" in b["why_ko"]
    n = len(calls)
    clock.t += 5
    assert s.get("BTCUSDT", "oi", "15m")["stale"] is True and len(calls) == n                  # a dead Binance is not asked on every poll
    clock.t += CP.FAIL_RETRY_S + 1
    mode["fail"] = None
    assert s.get("BTCUSDT", "oi", "15m")["stale"] is False and len(calls) == n + 1             # it recovers by itself


def test_a_series_that_never_loaded_is_not_ready_and_says_why(monkeypatch):
    monkeypatch.setattr(CP, "FETCH", lambda url: (_ for _ in ()).throw(OSError("blocked")))
    r = CP.Series(clock=Clock()).get("ETHUSDT", "ls", "5m")
    assert r["ready"] is False and r["failed"] is True and "points" not in r and "못 불러옴" in r["why_ko"]
    monkeypatch.setattr(CP, "FETCH", lambda url: [])
    e = CP.Series(clock=Clock()).get("ETHUSDT", "funding", "1h")
    assert e["ready"] is False and "비어" in e["why_ko"]                                         # an empty answer is not "0"


def test_a_binance_slow_down_stops_every_request_for_a_while(monkeypatch):
    class Slow(Exception):
        code = 429

    clock, calls = Clock(), []

    def fetch(url):
        calls.append(url)
        raise Slow("too many requests")

    monkeypatch.setattr(CP, "FETCH", fetch)
    s = CP.Series(clock=clock)
    a = s.get("BTCUSDT", "oi", "15m")
    assert a["ready"] is False and "막음" in a["why_ko"] and len(calls) == 1
    clock.t += CP.FAIL_RETRY_S + 1                       # another coin and kind too: no request reaches Binance while it is cooling
    assert s.get("ETHUSDT", "ls", "1h")["ready"] is False and s.get("BTCUSDT", "oi", "15m")["ready"] is False and len(calls) == 1
    clock.t += CP.COOL_S
    s.get("BTCUSDT", "oi", "15m")
    assert len(calls) == 2                                # asked again after the cool-down


# ---------------------------------------------------------------- the routes
def _client(tmp_path, rows=(), conn=()):
    db = str(tmp_path / "p.db")
    _store(db).close()
    if rows or conn:
        _liq(str(tmp_path / "liq.db"), rows, conn)
    c = TestClient(create_app(db, hash_password(PW), SECRET))
    return c


def test_routes_are_behind_the_login_and_validate_their_input(tmp_path, monkeypatch):
    monkeypatch.setattr(CP, "FETCH", lambda url: [{"timestamp": 1, "sumOpenInterestValue": "5.0"}])
    c = _client(tmp_path)
    assert c.get("/api/v4/chartplus/series?symbol=BTCUSDT&kind=oi&tf=15m", follow_redirects=False).status_code in (401, 302, 307)
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    ok = c.get("/api/v4/chartplus/series", params={"symbol": "BTCUSDT", "kind": "oi", "tf": "15m"}).json()
    assert ok["ready"] and ok["points"] == [[1, 5.0]]
    for bad in ({"symbol": "NOPE", "kind": "oi", "tf": "15m"}, {"symbol": "BTCUSDT", "kind": "zzz", "tf": "15m"},
                {"symbol": "BTCUSDT", "kind": "oi", "tf": "7m"}):
        assert c.get("/api/v4/chartplus/series", params=bad).status_code == 400
    now = int(time.time())
    assert c.get("/api/v4/chartplus/liq", params={"symbol": "BTCUSDT", "tf": "15m", "t0": 0}).status_code == 400
    assert c.get("/api/v4/chartplus/liq", params={"symbol": "BTCUSDT", "tf": "15m", "t0": now + 99999}).status_code == 400
    assert c.get("/api/v4/chartplus/liq", params={"symbol": "NOPE", "tf": "15m", "t0": now - 900}).status_code == 400
    assert c.get("/api/v4/chartplus/liq", params={"symbol": "BTCUSDT", "tf": "7m", "t0": now - 900}).status_code == 400
    # no liq.db next to the database: ready false (the page says so, it never draws "no liquidations")
    r = c.get("/api/v4/chartplus/liq", params={"symbol": "BTCUSDT", "tf": "15m", "t0": now - 900}).json()
    assert r["ready"] is False and r["recorder"] is False
    assert c.app.state.more["chartplus"]["routes"] == ["/api/v4/chartplus/liq", "/api/v4/chartplus/series"]


def test_the_liq_route_reads_the_recorders_file_and_a_failed_series_is_a_normal_answer(tmp_path, monkeypatch):
    now = int(time.time() * 1000)
    t0 = (now // 1000 - 3 * STEP) // STEP * STEP
    c = _client(tmp_path, rows=[("BTCUSDT", t0 * 1000 + 5000, "SELL", 62000.0, 2.0), ("BTCUSDT", t0 * 1000 + STEP * 1000 + 5000, "BUY", 62100.0, 1.0)],
                conn=[(t0 * 1000 - 1000, "connected")])
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    r = c.get("/api/v4/chartplus/liq", params={"symbol": "BTCUSDT", "tf": "15m", "t0": t0}).json()
    assert r["ready"] and [(b["t"], b["side"]) for b in r["bars"]] == [(t0, "long"), (t0 + STEP, "short")] and r["since_ts"] == t0 * 1000 - 1000
    monkeypatch.setattr(CP, "FETCH", lambda url: (_ for _ in ()).throw(OSError("x")))
    f = c.get("/api/v4/chartplus/series", params={"symbol": "BTCUSDT", "kind": "funding", "tf": "1h"})
    assert f.status_code == 200 and f.json()["ready"] is False and "못 불러옴" in f.json()["why_ko"]


def test_the_liq_route_keeps_one_answer_per_cut_and_a_slow_cut_does_not_hold_up_the_others(tmp_path, monkeypatch):
    import threading
    rows = [("BTCUSDT", _bar_ms(1), "SELL", 100.0, 1.0), ("ETHUSDT", _bar_ms(1), "SELL", 10.0, 1.0)]
    c = _client(tmp_path, rows, [(_bar_ms(0), "connected")])
    assert c.post("/api/login", json={"password": PW}).status_code == 200
    now = int(time.time())
    t0 = now // STEP * STEP - 20 * STEP
    gate, entered, calls = threading.Event(), threading.Event(), []
    real = CP.liq_bars

    def slow(path, symbol, t0_, step, now_ms):
        calls.append(symbol)
        if symbol == "ETHUSDT":
            entered.set()
            assert gate.wait(15)
        return real(path, symbol, t0_, step, now_ms)
    monkeypatch.setattr(CP, "liq_bars", slow)
    slow_one = {}
    th = threading.Thread(target=lambda: slow_one.update(c.get("/api/v4/chartplus/liq", params={"symbol": "ETHUSDT", "tf": "15m", "t0": t0}).json()))
    th.start()
    assert entered.wait(10)
    t = time.time()
    btc = c.get("/api/v4/chartplus/liq", params={"symbol": "BTCUSDT", "tf": "15m", "t0": t0}).json()        # answers while ETH's cut is still running
    assert btc["ready"] is True and time.time() - t < 5 and calls == ["ETHUSDT", "BTCUSDT"]
    c.get("/api/v4/chartplus/liq", params={"symbol": "BTCUSDT", "tf": "15m", "t0": t0})
    assert calls == ["ETHUSDT", "BTCUSDT"]                                                                   # the second ask is the cached answer
    gate.set()
    th.join(10)
    assert slow_one.get("ready") is True
    assert CP.liq_ttl(900) == CP.LIQ_TTL_S < CP.liq_ttl(14400) < CP.liq_ttl(86400)                             # a daily cut (the slow one) is reused longer


def test_the_server_never_blocks_on_binance_for_long():
    assert CP.FETCH_TIMEOUT_S <= 5 and CP.FAIL_RETRY_S >= 10
    src = open(os.path.join(ROOT, "paperbot", "dash", "more", "chartplus.py"), encoding="utf-8").read()
    assert "_get_json(url, timeout=FETCH_TIMEOUT_S)" in src and "Lock()" in src
    assert "chartplus" in open(os.path.join(ROOT, "paperbot", "dash", "more", "__init__.py"), encoding="utf-8").read()


# ---------------------------------------------------------------- /api/candles carries the taker-buy volume
def test_candles_carry_the_taker_buy_volume(monkeypatch):
    rows = [[1_700_000_000_000 + i * 900_000, "10", "11", "9", "10.5", "100", 0, "1050", 5, "60.5", "630", "0"] for i in range(3)]
    rows.append([1_700_002_700_000, "10", "11", "9", "10.5", "100"])                           # a short row: no key, no crash

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(rows).encode()

    monkeypatch.setattr(APP.urllib.request, "urlopen", lambda url, timeout=0: Resp())
    APP._CANDLE_CACHE.clear()
    out = APP.fetch_candles("BTCUSDT", "15m", 4)
    assert [c["taker_buy"] for c in out[:3]] == [60.5, 60.5, 60.5] and out[0]["volume"] == 100.0 and "taker_buy" not in out[3]
    assert out[0]["time"] == 1_700_000_000 and out[0]["close"] == 10.5
    APP._CANDLE_CACHE.clear()


# ---------------------------------------------------------------- the browser-side arithmetic, run in node
def _node(body):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    script = f"const C = await import('file://{os.path.join(V4, 'screens', 'chart-plus-calc.js')}');\n" + body
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_bubble_size_and_which_bars_become_bubbles():
    o = _node("""console.log(JSON.stringify({
      lo: C.liqRadius(50000, 50000), mid: C.liqRadius(5e6, 50000), big: C.liqRadius(1e15, 50000), zero: C.liqRadius(0, 50000), under: C.liqRadius(10, 50000),
      minBtc: C.minLiqUsd("BTCUSDT"), minEth: C.minLiqUsd("ETHUSDT"), tone: C.LIQ_TONE === undefined ? null : C.LIQ_TONE,
      b: C.bubbles([{t: 1, px: 100, usd: 60000}, {t: 2, px: 100, usd: 70000}, {t: 3, px: 100, usd: 100}, {t: 4, px: null, usd: 9e9},
                    {t: 5, px: 100, usd: 50000}], 50000).map((x) => x.t)}));""")
    assert o["lo"] == 4 and 12 < o["mid"] < 13 and o["big"] == 24 and o["zero"] == 0 and o["under"] == 4
    assert o["minBtc"] == 50000 and o["minEth"] == 10000
    assert o["tone"] is None                                             # (wave-b merge) no copy of the colour rule here: core/liqkit.js is the one source
    assert o["b"] == [2, 1, 5]                                           # biggest first, under the minimum and a missing price left out


def test_price_rows_add_the_bars_on_screen_into_pixel_rows():
    o = _node("""const cells = [[0, 10, 5, 0], [1, 10, 0, 7], [2, 11, 1, 1], [9, 10, 100, 100], [1, 50, 9, 9]];
    const yOf = (p) => (p > 20 ? null : 200 - p * 10);
    console.log(JSON.stringify(C.priceRows(cells, 1, 0, 2, yOf, 3, 400)));""")
    # price 10.5 -> y 95 -> row 31; price 11.5 -> y 85 -> row 28; bar 9 is off screen, price 50.5 has no place
    assert [(r["long"], r["short"]) for r in o["rows"]] == [(1, 1), (5, 7)] and o["max"] == 12
    assert [r["y"] for r in o["rows"]] == [85.5, 94.5]
    assert [r["y"] for r in o["rows"]] == sorted(r["y"] for r in o["rows"])


def test_what_if_counts_every_account_and_adds_money_for_none_of_the_count_only_ones():
    o = _node("""
    const A = {side: 1, entry: 100, qty: 1, margin: 10, stop: 98, liq: 91, money: true};
    const B = {side: -1, entry: 100, qty: 2, margin: 20, stop: 103, liq: 109, money: true};
    const Cc = {side: 1, entry: 100, qty: 1, margin: 10, stop: 99, liq: 95, money: false};     // DeepSeek / a coin flip
    const L = {side: 1, entry: 100, qty: 1, margin: 10, stop: 99, liq: 91, money: true, lock: true};
    const D = {side: 1, entry: 100, qty: 3, margin: 30, stop: 90, liq: 95, money: true};       // liquidated before its stop
    const w = (items, m, P) => C.whatIf(items, m, P);
    console.log(JSON.stringify({
      down97: w([A, B, Cc], 100, 97), down90: w([A, B, Cc], 100, 90), up105: w([A, B, Cc], 100, 105), same: w([A, B], 100, 100),
      lock: w([L], 100, 98), liqFirst: w([D], 100, 85), nomark: w([A], null, 90), none: w([], 100, 90),
      lv: C.stopLevels([A, B, Cc, {side: 1, entry: 100, stop: 98.001, liq: null}]),
    }));""")
    d = o["down97"]                              # A stopped (-2), B open (+6), C stopped but counted without money
    assert (d["n"], d["stops"], d["liqs"], d["open"], d["countOnly"], d["nMoney"]) == (3, 2, 0, 1, 1, 2) and d["pnl"] == 4
    d = o["down90"]                              # the stop is nearer to the mark than the liquidation: the stop closes it
    assert (d["stops"], d["liqs"]) == (2, 0) and d["pnl"] == -2 + 20
    d = o["up105"]                               # B's stop (-6); A is worth +5; C's money is not in the sum
    assert (d["stops"], d["open"], d["countOnly"]) == (1, 2, 1) and d["pnl"] == -6 + 5
    assert o["same"]["pnl"] == 0 and o["same"]["stops"] == 0
    assert o["lock"]["stops"] == 1 and o["lock"]["locks"] == 1
    assert (o["liqFirst"]["liqs"], o["liqFirst"]["stops"], o["liqFirst"]["pnl"]) == (1, 0, -30)     # a liquidation loses the whole margin
    assert o["nomark"]["n"] == 0 and o["none"]["n"] == 0
    assert [(x["kind"], x["n"]) for x in o["lv"]] == [("liq", 1), ("liq", 1), ("stop", 2), ("stop", 1), ("stop", 1), ("liq", 1)]
    assert [round(x["price"]) for x in o["lv"]] == [91, 95, 98, 99, 103, 109]    # by price; 98 and 98.001 are one price (x2)


def test_cvd_is_buy_minus_sell_and_a_missing_bar_is_a_gap_never_zero():
    o = _node("""const cs = [{volume: 10, taker_buy: 7}, {volume: 10, taker_buy: 2}, {volume: 10}, {volume: 10, taker_buy: 11}, {volume: 4, taker_buy: 3}];
    const r = C.cvd(cs, 1, 4);
    const all = C.cvd(cs);
    console.log(JSON.stringify({r, all: all.cum, none: C.cvd([{volume: 5}, {volume: 6}]), empty: C.cvd([])}));""")
    r = o["r"]
    assert r["delta"] == [4, -6, None, None, 2]                    # 2*buy - volume; no taker_buy / a buy above the volume: null
    assert r["cum"] == [0, -6, None, None, -4]                     # zero before the first bar on screen, running on both sides
    assert r["missing"] == 2 and r["missingVisible"] == 2
    assert o["all"] == [4, -2, None, None, 0]
    assert o["none"]["missing"] == 2 and o["none"]["cum"] == [None, None] and o["empty"]["delta"] == []


def test_series_are_put_on_the_candles_times_without_inventing_values():
    o = _node("""const H = 3600;
    const times = [0, 900, 1800, 2700, 3600, 5400, 20000];
    const a = C.alignSeries([[0, 1, 0.5], [H * 1000, 2, 0.6]], times, 900, H);
    const early = C.alignSeries([[2000 * 1000, 5]], [0, 900, 1800, 2700], 900, 900);
    const f = C.alignFunding([[0, 0.0001], [14400 * 1000, 0.0002]], [0, 14400, 28800], 14400);
    const day = C.alignFunding([[0, 0.0001], [28800 * 1000, 0.0002], [57600 * 1000, 0.0003]], [0], 86400);
    console.log(JSON.stringify({a, early, f, day}));""")
    a = o["a"]
    assert [x and (x["v"], x["carried"]) for x in a] == [(1, False), (1, True), (1, True), (1, True), (2, False), (2, True), None]
    assert a[0]["x"] == 0.5 and a[4]["ts"] == 3_600_000
    assert o["early"] == [None, None, {"v": 5, "ts": 2_000_000, "carried": False}, {"v": 5, "ts": 2_000_000, "carried": True}]   # nothing before the first point
    assert [x and x["v"] for x in o["f"]] == [0.0001, 0.0002, None]    # a bar without a settlement stays empty (nothing is carried)
    assert o["day"][0]["n"] == 3 and o["day"][0]["v"] == pytest.approx(0.0006)


def test_what_if_says_how_many_accounts_pass_both_their_stop_and_liquidation():
    o = _node("""const A = {side: 1, entry: 100, qty: 1, margin: 10, stop: 98, liq: 91, money: true};
    console.log(JSON.stringify({deep: C.whatIf([A, A, {...A, stop: 50}], 100, 80), shallow: C.whatIf([A], 100, 95), up: C.whatIf([A], 100, 120)}));""")
    assert o["deep"]["both"] == 2 and o["deep"]["stops"] == 2 and o["deep"]["liqs"] == 1       # stop 50 is beyond the liquidation 91: the liquidation is nearer
    assert o["shallow"]["both"] == 0 and o["up"]["both"] == 0
    assert "WORDS.both(r.both)" in _code(_src("screens", "chart-stopmap.js")) and "먼저 닿는 쪽 하나로만" in _src("screens", "chart-plus-kit.js")


def test_what_if_stops_a_reel_position_at_its_take_profit():
    o = _node("""const R = {side: 1, entry: 100, qty: 2, margin: 20, stop: 95, liq: 80, tp: 110, money: true};      // the 5-minute reel has a target
    const S = {side: -1, entry: 100, qty: 1, margin: 10, stop: 105, liq: 120, tp: 90, money: true};
    const N = {side: 1, entry: 100, qty: 5, margin: 50, stop: 95, liq: 80, tp: null, money: true};               // the ladder houses: no target
    console.log(JSON.stringify({above: C.whatIf([R, N], 100, 130), below: C.whatIf([S], 100, 80), under: C.whatIf([R], 100, 105), down: C.whatIf([R], 100, 90)}));""")
    assert (o["above"]["tps"], o["above"]["open"]) == (1, 1) and o["above"]["pnl"] == 2 * 10 + 5 * 30      # the reel books its target (+10), the ladder one runs on to 130
    assert (o["below"]["tps"], o["below"]["pnl"]) == (1, 10)                                          # a short's target lies below the price
    assert o["under"]["tps"] == 0 and o["under"]["pnl"] == 10                                         # not yet at the target: valued at the price
    assert (o["down"]["stops"], o["down"]["tps"]) == (1, 0) and o["down"]["pnl"] == -10               # a target above never closes a fall
    assert "r.tps" in _code(_src("screens", "chart-stopmap.js")) and "tp: p.target" in _code(_src("screens", "chart-stopmap.js"))


def test_a_candle_ends_where_the_next_one_opens_and_a_missing_candle_does_not_shift_the_bars():
    o = _node("""const D = 86400, M = 2592000;
    // 1-month candles: January (31 days), February (28): a point on Feb 1 + 2 h belongs to February, not to January's "30 days"
    const times = [0, 31 * D, 59 * D];
    const pts = [[(30 * D + 100) * 1000, 1], [(31 * D + 7200) * 1000, 2]];
    const a = C.alignSeries(pts, times, M, D);
    const f = C.alignFunding([[(30 * D + 100) * 1000, 0.0001], [(31 * D + 7200) * 1000, 0.0002]], times, M);
    // candles of 15 minutes with one missing (index 2 is absent): the bars of the liquidation cut are by time
    const cs = [{time: 0}, {time: 900}, {time: 2700}, {time: 3600}];
    console.log(JSON.stringify({a: a.map((x) => x && x.v), f: f.map((x) => x && x.v), w: C.barWindow(cs, 2, 3, 0, 900), all: C.barWindow(cs, 0, 99, 0, 900),
      none: C.barWindow([], 0, 5, 0, 900), off: C.barWindow(cs, 1, 3, 900, 900)}));""")
    assert o["a"] == [1, 2, None] and o["f"] == [0.0001, 0.0002, None]          # (March: the last point is 28 days old, nothing is carried that far)
    assert o["w"] == [3, 4] and o["all"] == [0, 4] and o["none"] == [0, -1] and o["off"] == [0, 3]


# ---------------------------------------------------------------- the page
def test_everything_is_off_until_chosen_and_remembered_per_device():
    kit = _code(_src("screens", "chart-plus-kit.js"))
    assert "liq: s.liq === true, stops: s.stops === true" in kit and 'local.get("cfxp-" + key' in kit and 'local.set("cfxp-" + key' in kit
    assert "slice(0, 2)" in kit and "localStorage" not in kit                        # at most two panes, the wrapped dom.js local
    plus = _code(_src("screens", "chart-plus.js"))
    assert "겹쳐 보기 (처음엔 꺼 둠)" in plus and "아래 칸 (동시에 2개까지)" in plus and "deck.menuEl" in plus
    assert "how === \"default\" || how === \"none\"" in plus                        # 기본으로 / 모두 숨기기 turn the add-ons off again
    assert "slice(-2)" in plus                                                      # a third pane replaces the oldest
    fx = _code(_src("core", "chartfx.js"))
    assert "onData(fn) { dataSubs.push(fn); }" in fx and "menuEl: menu," in fx
    assert 'fn(null, on ? "all" : "none")' in fx and 'fn(null, "default")' in fx


def test_each_chart_screen_makes_one_call_and_css_comes_with_it():
    tc, ch = _src("screens", "terminal-chart.js"), _src("screens", "chart.js")
    assert tc.count("chartPlus({") == 1 and 'key: "term"' in tc and "minMain: 230" in tc and 'from "./chart-plus.js"' in tc
    assert ch.count("chartPlus({") == 1 and 'key: "chart"' in ch and "minMain" not in ch
    assert '@import url("chart-plus.css")' in _src("screens", "terminal.css") and '@import url("chart-plus.css")' in _src("screens", "chart.css")
    css = _src("screens", "chart-plus.css")
    assert ".term-cwrap.cfxp-has > .term-cbox { right: var(--cfxp-w, 0px); }" in css          # the strips take their own column
    assert ".chart-wrap.cfxp-has > .chart-box { margin-right: var(--cfxp-w, 0px); }" in css
    assert ".term-cwrap.cfxp-has > .term-ptag { right: var(--cfxp-w, 0px); }" in css          # the price tag stays at the axis
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(\s*\d", re.sub(r"/\*.*?\*/", "", css, flags=re.S))


def test_the_liquidation_colour_rule_is_the_terminal_feeds():
    # (wave-b merge) the bubbles, the price bars and the note's dots read core/liqkit.js through pb.js, like the terminal's feed,
    # the flashes and the 시장 board: one colour rule (롱 청산 = up, 숏 청산 = down) and one money format ($ K / M);
    # tests/test_dash_wave_b.py pins that no other copy of the rule exists
    feed = _code(_src("screens", "terminal-feed.js"))
    assert "liqTone(r.liquidated)" in feed and 'lg ? "up" : "down"' not in feed
    assert "LIQ_TONE" not in _code(_src("screens", "chart-plus-calc.js"))
    liq = _code(_src("screens", "chart-liqmap.js"))
    assert "const {liqTone, liqKo, usdShort} = liqkit;" in liq and "const toneOf = (side) => liqTone(side);" in liq
    assert "toneOf(\"long\")" in liq and "toneOf(\"short\")" in liq and "koUsdt" not in liq
    assert "${liqKo(b.side)} ${usdShort(b.usd)}" in liq and "가장 큰 건 ${usdShort(big.usd)}" in liq
    plus = _code(_src("screens", "chart-plus.js"))
    assert "dataset: {tone: liqTone(side)}" in plus and 'usdShort(minLiqUsd("BTCUSDT"))' in plus and "LIQ_TONE" not in plus


def test_honest_words_and_no_flat_lines():
    kit, plus, liq = _src("screens", "chart-plus-kit.js"), _src("screens", "chart-plus.js"), _src("screens", "chart-liqmap.js")
    assert "바이낸스 시장 전체 (우리 봇 아님)" in kit and "코인마다 1초에 1건만 알려 줘서 실제보다 적음" in kit and "딥시크·동전 봇 ${n}개는 개수만" in kit
    assert "기록기가 들은 것만" in plus and "못 불러옴: 거품과 막대를 그리지 않았습니다" in plus and "기록기 자료가 없습니다" in plus
    assert "기록기가 켜지기 전 (이 앞은 모름)" in liq and "끊김" in liq and "기록 없음" in liq
    low = _src("screens", "chart-lower.js")
    assert "봉 자료로 계산한 근사치" in low and "못 불러옴" in low and "30초마다 다시 받아 봅니다" in low
    assert "S.line.setData(can && line ? line : [])" in low and "S.hist.setData(can && hist ? hist : [])" in low      # a failure empties the pane
    assert "ctx.every(30000" in low                                               # the retry the note promises really happens
    stop = _src("screens", "chart-stopmap.js")
    assert "countOnly(a, \"\")" in stop and "예상 손익" in stop and "WORDS.countOnly" in stop and "WORDS.stopsMath" in stop


def test_no_page_asks_binance_directly_and_nothing_parses_html():
    for name in ("chart-plus.js", "chart-plus-calc.js", "chart-plus-kit.js", "chart-liqmap.js", "chart-stopmap.js", "chart-lower.js"):
        src = _code(_src("screens", name))
        assert "binance" not in src.lower() and "fapi" not in src and "fetch(" not in src and "XMLHttpRequest" not in src, name
        assert "innerHTML" not in src and "insertAdjacentHTML" not in src and "outerHTML" not in src and "eval(" not in src, name
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src) and "toLocaleString" not in src, name
    # the page only asks this server's two routes
    paths = set(re.findall(r"/api/v4/chartplus/\w+", " ".join(_src("screens", n) for n in ("chart-liqmap.js", "chart-lower.js"))))
    assert paths == {"/api/v4/chartplus/liq", "/api/v4/chartplus/series"}


def test_the_terminal_chart_keeps_its_candles_readable():
    plus = _code(_src("screens", "chart-plus.js"))
    assert "const budget = pb.clientHeight - others - o.minMain - notesH();" in plus and "PANE_H = {max: 88, min: 56}" in plus
    assert "TERM_PANE_MAX = 76" in plus and "cfxp-nokey" in plus                      # the key line gives its row up
    assert "이 화면은 높이가 모자라" in plus                                           # a panel too low for panes says so
    css = _src("screens", "chart-plus.css")
    assert ".cfxp-nokey > .term-ckey { display: none; }" in css and ".term-chart .cfxp-n { white-space: nowrap;" in css
    term = _src("screens", "terminal.css")
    assert ".term-chart .term-pb { flex: 1 1 auto; display: grid; grid-template-rows: minmax(0, 1fr) auto auto; padding: 0; }" in term


def test_review_fixes_of_the_page():
    plus = _code(_src("screens", "chart-plus.js"))
    low = _code(_src("screens", "chart-lower.js"))
    liq = _code(_src("screens", "chart-liqmap.js"))
    # the market liquidation choice is offered only while the recorder runs (CONTRACT 1.7), a saved "on" stays visible to be turned off
    assert 'items.get("liq").hidden = features.probed && !features.liq && !st.liq;' in plus and 'bus.on("features"' in plus
    # the notes are rebuilt only when their words change (the panes report every second)
    assert "if (sig !== notesSig)" in plus
    # the legend says which bubbles exist at all (a small order has a price bar, no circle)
    assert "작은 건 가격 막대에만" in plus and "minLiqUsd(" in plus
    # a failed refresh with an old answer on screen says so; the colours are read once per draw, not per bar
    assert "if (d.stale || p.err) chip = " in low and "palette().up" not in low
    # the price bars are cut by the candles' times, not their count
    assert "barWindow(d, a, z, data.t0, data.step_s)" in liq


def test_a_fault_in_an_add_on_never_reaches_the_chart_or_the_candle_feed():
    """The deck calls the add-ons from inside setData / update, the chart library from inside its draw and crosshair loop: every
    one of those callbacks is wrapped (chart-plus-kit.js safe), so a fault is logged and the candles go on."""
    kit = _code(_src("screens", "chart-plus-kit.js"))
    assert "export const safe = (fn) => (...a) => {" in kit and "console.error(" in kit
    plus, liq = _code(_src("screens", "chart-plus.js")), _code(_src("screens", "chart-liqmap.js"))
    low, stop = _code(_src("screens", "chart-lower.js")), _code(_src("screens", "chart-stopmap.js"))
    assert "deck.onData(safe(" in plus and "deck.onToggle(safe(" in plus and "subscribeVisibleLogicalRangeChange(safe(" in plus
    assert "drawBackground: safe(" in liq and "draw: safe(" in liq and "updateAllViews: safe(" in liq
    assert "subscribeCrosshairMove(safe(" in liq and "subscribeClick(safe(" in liq
    assert low.count("subscribeCrosshairMove(safe(") == 2 and "subscribeVisibleLogicalRangeChange(safe(" in low
    assert "updateAllViews: safe(" in stop
