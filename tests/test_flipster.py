"""Flipster (paperbot/flipster.py) on the fake exchange (tests/fakeflipster.py): signing, the host allowlist, key gates,
contract units, orders (IOC market orders read back from their fills), the client-id ledger (Flipster has no client
order id), the stop protocol (place, confirm, move with two at once, cancel), a stop that fires, fills and P&L, funding,
error mapping, the drill, and the executor's whole cycle with ``"exchange": "flipster"`` (owners 10-23). No network."""

import hashlib
import hmac
import json
import pathlib
import socket
from urllib.parse import urlparse

import pytest

from fakeflipster import FakeFlipster
from paperbot import flipster as FL
from paperbot import risk as R
from paperbot.executor import ExecConfig, ExecStore, Executor, Intent, Refused
from paperbot.mainnet import FLAG, FLAG_VALUE, check_permissions
from paperbot.notify import ListNotifier
from paperbot.testnet import (BAD_TIMESTAMP, NOT_FOUND, WOULD_TRIGGER, RateLimited, TestnetError, TransientError,
                              covers, live_stops, move_stop, place_stop)

T0 = 1_800_000_000_000
BTC, DOGE = "BTCUSDT", "DOGEUSDT"
LIVE_ENV = {FLAG: FLAG_VALUE, "FLIPSTER_LIVE_KEY": "fk", "FLIPSTER_LIVE_SECRET": "fs",
            FL.KEY_CHECKED: FL.KEY_CHECKED_VALUE}
ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a test tried to open a network connection")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def make(fake=None, clock=None, db=None, **kw):
    clock = clock or Clock()
    fake = fake or FakeFlipster()
    fake.clock = clock
    c = FL.FlipsterClient("fk", "fs", send=fake, clock_ms=clock, sleep=lambda s: None, ledger=FL.IdLedger(db), **kw)
    return c, fake, clock


def ready(c, symbols=(BTC,)):
    c.sync_time()
    c.one_way()
    for s in symbols:
        c.isolated(s)
    return c


def posts(fake, otype=None):
    out = [json.loads(b) for _, m, p, _, b in fake.calls if m == "POST" and p == "/api/v1/trade/order"]
    return [b for b in out if otype is None or b["type"] == otype]


# ------------------------------------------------------------------ signing, transport, errors
def generate_api_key_signature(secret, method, url, expires, data=None):
    """Flipster's Quick Tutorial, step 2 (copied as written: the reference the client must agree with)."""
    parsed = urlparse(url)
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    parts = [method.upper().encode("utf-8"), path.encode("utf-8"), str(expires).encode("utf-8")]
    if data:
        parts.append(data)
    message = b"".join(parts)
    return hmac.new(secret.encode("utf-8"), message, digestmod=hashlib.sha256).hexdigest()


def test_signature_vector_matches_the_docs():
    body = b'{"symbol":"BTCUSDT.PERP","side":"BUY","type":"MARKET","quantity":"0.01"}'
    ours = FL.signature("s3cr3t", "POST", "/api/v1/trade/order", 1765975850, body)
    assert ours == generate_api_key_signature("s3cr3t", "POST", "https://trading-api.flipster.io/api/v1/trade/order",
                                              1765975850, body)
    assert ours == hmac.new(b"s3cr3t", b"POST/api/v1/trade/order1765975850" + body, hashlib.sha256).hexdigest()
    q = FL.query_string({"symbol": "BTCUSDT.PERP", "startTime": "1", "endTime": "2"})
    assert q == "endTime=2&startTime=1&symbol=BTCUSDT.PERP"
    assert FL.signature("s3cr3t", "GET", f"/api/v1/trade/order/history?{q}", 7) == generate_api_key_signature(
        "s3cr3t", "GET", f"https://trading-api.flipster.io/api/v1/trade/order/history?{q}", 7)


def test_signed_requests_and_the_host_allowlist():
    c, fake, clock = make()
    assert c.sync_time() == 0 and c.time_source == "/api/v1/public/time"
    m, path, query, body = fake.calls[-1][1:]
    assert (m, path, body) == ("GET", "/api/v1/public/time", None)
    bad = FL.FlipsterClient("fk", "other", send=fake, clock_ms=clock, sleep=lambda s: None)
    with pytest.raises(TestnetError) as e:                 # the fake checks every signature
        bad.account()
    assert e.value.status == 401 and e.value.code == "AUTH"
    for base in ("https://api.flipster.io", "http://trading-api.flipster.io", "https://trading-api.flipster.io:8443",
                 "https://trading-api.flipster.io/x", "https://trading-api.flipster.io.evil.com"):
        with pytest.raises(ValueError):
            FL.FlipsterClient("fk", "fs", base=base)
    with pytest.raises(ValueError):
        FL.FlipsterClient("fk", "")
    assert FL.FlipsterClient.HOSTS == ("trading-api.flipster.io",)


def test_error_mapping_to_the_executor_classes():
    c, fake, clock = make()
    fake.fail("GET", "/api/v1/account", "429", times=9)                 # past the read retries
    with pytest.raises(RateLimited) as e:
        c.account()
    assert e.value.status == 429 and c.rate_answers >= 4
    fake.fails.clear()
    fake.fail("GET", "/api/v1/account", "403")
    with pytest.raises(RateLimited) as e:
        c.account()
    assert e.value.status == 418
    fake.fail("GET", "/api/v1/account", "503_before")
    with pytest.raises(TransientError):
        c.account()
    fake.fail("GET", "/api/v1/account", "drop_before")
    with pytest.raises(TransientError):
        c.account()
    c.offset_ms = -120_000                                 # a clock two minutes slow: api-expires has passed
    with pytest.raises(TestnetError) as e:
        c.account()
    assert e.value.code == BAD_TIMESTAMP
    c.offset_ms = 0
    with pytest.raises(TestnetError) as e:
        c.cancel(BTC, "00000000-0000-0000-0000-00000000abcd")
    assert e.value.code == NOT_FOUND[0]
    with pytest.raises(TestnetError) as e:
        c.order(BTC, order_id="00000000-0000-0000-0000-00000000abcd")
    assert e.value.code == NOT_FOUND[0]


def test_a_read_refused_for_the_rate_is_read_again_and_the_client_paces_itself():
    c, fake, clock = make()
    pauses = []

    def pause(s):
        pauses.append(s)
        clock.t += int(s * 1000)
    c.sleep = pause
    fake.fail("GET", "/api/v1/account", "429", times=2)
    assert c.account()["totalWalletBalance"] == "10000" and len(pauses) == 2
    pauses.clear()
    for _ in range(20):                                    # 20 reads at one instant: the 8-a-second budget waits
        c.price(BTC)
    assert pauses and all(p <= 1.0 for p in pauses)
    assert c.throttle_s() >= 0


def test_server_time_in_nanoseconds():
    c, fake, clock = make()
    fake.clock = lambda: clock.t + 1_500                  # the server 1.5 s ahead
    assert c.sync_time() == 1_500
    fake.fail("GET", "/api/v1/public/time", ("err", 404, "NotFound", "no route"))
    assert c.sync_time() == 0 and c.time_source == "local"


# ------------------------------------------------------------------ market data, account
def test_contract_units_and_the_tradable_list():
    c, fake, _ = make()
    sp = c.spec(BTC)
    assert (sp["qty_step"], sp["min_qty"], sp["tick"], sp["min_notional"], sp["max_leverage"]) == \
        (0.001, 0.001, 0.1, 5.0, 100.0)
    assert sp["tradable"] and sp["status"] == "Trading"
    assert c._qty(DOGE, 25.9) == 25 and str(c._qty(BTC, 0.0059)) == "0.005"    # floored
    with pytest.raises(TestnetError):
        c.spec("BTCUSD")                                   # not a USDT perpetual
    fake.set_price(BTC, 101.5, mark=101.2)
    assert c.price(BTC) == 101.5 and c.mark(BTC) == 101.2


def test_klines_in_nanoseconds_and_pieces():
    c, fake, clock = make()
    for i in range(3):
        fake.set_price(BTC, 100.0 + i)
        clock.t += 60_000
    rows = c.klines(BTC, T0 - 60_000, clock.t)
    assert [r[0] for r in rows] == [T0, T0 + 60_000, T0 + 120_000] and rows[-1][3] == 102.0
    q = dict(x.split("=") for x in fake.calls[-1][3].split("&"))
    assert q["interval"] == "1" and len(q["startTime"]) == 19 and q["limit"] == "1000"
    c.klines(BTC, T0 - 2999 * 60_000, T0)                  # 3000 minutes: three requests of 1000
    assert sum(1 for x in fake.calls if x[2] == "/api/v1/market/kline") == 4


def test_account_in_the_binance_shape_and_garbled_answers_are_errors():
    c, fake, _ = make()
    a = c.account()
    assert a["totalWalletBalance"] == "10000" and a["totalMarginBalance"] == "10000"
    assert [x["asset"] for x in a["assets"]] == ["USDT", "USDC"]
    real = fake._route

    def drop(m, path, query, body):
        st, raw, h = real(m, path, query, body)
        if path == "/api/v1/account":
            d = json.loads(raw)
            d.pop("totalMarginBalance")
            raw = json.dumps(d).encode()
        return st, raw, h
    fake._route = drop
    with pytest.raises(TransientError):                    # never $0 equity from a gap
        c.account()


# ------------------------------------------------------------------ account set-up
def test_one_way_and_isolated_leverage_read_back():
    c, fake, _ = make()
    ready(c, (BTC, DOGE))
    assert fake.mode == "ONE_WAY" and c.trade_mode == "ONE_WAY"
    assert fake.levs[BTC] == ["ISOLATED", 40] and fake.levs[DOGE] == ["ISOLATED", 30]
    body = json.loads(next(x[4] for x in fake.calls if x[2] == "/api/v1/trade/leverage"))
    assert body == {"symbol": "BTCUSDT.PERP", "leverage": 40, "marginType": "ISOLATED"}
    lines = c.account_setup((BTC, DOGE))
    assert all(ok for ok, _ in lines) and "ISOLATED 40" in lines[1][1]
    n = sum(1 for x in fake.calls if x[2] == "/api/v1/trade/leverage")
    c.isolated(BTC)                                        # already so: nothing is sent
    assert sum(1 for x in fake.calls if x[2] == "/api/v1/trade/leverage") == n


def test_leverage_without_a_settings_row_is_accepted_on_the_answer_and_marked():
    c, fake, _ = make()
    fake.settings_rows = False
    ready(c)
    assert c.leverage(BTC, 20) == {"symbol": BTC, "leverage": 20, "marginType": "isolated", "verified": False}
    assert BTC in c.lev_unverified


def test_a_wrong_read_back_is_refused():
    c, fake, _ = make()
    ready(c)
    real = fake._route

    def cross(m, path, query, body):
        st, raw, h = real(m, path, query, body)
        if path in ("/api/v1/trade/leverage", "/api/v1/account/position"):
            raw = raw.replace(b'"ISOLATED"', b'"CROSS"')
        return st, raw, h
    fake._route = cross
    with pytest.raises(TestnetError) as e:
        c.leverage(BTC, 20)
    assert e.value.code == "LEVERAGE_MISMATCH"


def test_trade_mode_with_a_position_open_needs_this_executors_record(tmp_path):
    db = str(tmp_path / "exec.db")
    c, fake, clock = make(db=db)
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbe1")
    c2, _, _ = make(fake=fake, clock=clock, db=db)          # a restart with the position open: the record says ONE_WAY
    c2.one_way()
    assert c2.trade_mode == "ONE_WAY" and c2.trade_mode_source == "record"
    c3, _, _ = make(fake=fake, clock=clock, db=str(tmp_path / "other.db"))
    with pytest.raises(Refused):                            # no record: the mode cannot be confirmed
        c3.one_way()
    c4, _, _ = make(fake=fake, clock=clock)
    with pytest.raises(TestnetError) as e:                  # no one-way confirmed in this process: no entry
        c4.leverage(BTC, 20)
    assert e.value.code == "NOT_ONE_WAY"


# ------------------------------------------------------------------ orders
def test_market_entry_and_close_shapes():
    c, fake, _ = make()
    ready(c)
    o = c.market(BTC, "BUY", 5.0, client_id="pbAentry1")
    assert o["status"] == "FILLED" and o["executedQty"] == "5" and o["avgPrice"] == "100" and o["fills"] == 1
    assert o["commission"] == "0.3" and o["clientOrderId"] == "pbAentry1"
    assert float(c.position(BTC)["positionAmt"]) == 5.0
    assert c.order(BTC, client_id="pbAentry1")["orderId"] == o["orderId"]          # through the ledger
    x = c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbAclose1")
    assert x["status"] == "FILLED" and x["reduceOnly"] is True and fake.pos[BTC] == 0
    sent = posts(fake, "MARKET")
    assert sent[0] == {"symbol": "BTCUSDT.PERP", "side": "BUY", "type": "MARKET", "quantity": "5"}
    assert sent[1] == {"symbol": "BTCUSDT.PERP", "side": "SELL", "type": "MARKET", "quantity": "5", "reduceOnly": True}
    assert not fake.slippage_sent                          # never maxSlippagePrice, never timeInForce


def test_a_partly_filled_ioc_order_reads_its_fills_not_its_status():
    c, fake, _ = make()
    ready(c)
    fake.partial = 0.4
    o = c.market(BTC, "BUY", 5.0, client_id="pbApart")
    assert o["flipsterStatus"] == "CANCELED" and o["status"] == "CANCELED"
    assert o["executedQty"] == "2" and o["origQty"] == "5" and o["avgPrice"] == "100"
    assert float(c.position(BTC)["positionAmt"]) == 2.0
    again = c.order(BTC, client_id="pbApart")
    assert again["executedQty"] == "2" and again["status"] == "CANCELED"


def test_an_accepted_order_whose_fills_lag_keeps_the_answers_filled_amount():
    c, fake, _ = make()
    ready(c)
    real = fake._route

    def no_execs(m, path, query, body):
        if path == "/api/v1/trade/execution/history":
            return 200, b'{"history": [], "hasPrev": false, "hasNext": false}', {}
        return real(m, path, query, body)
    fake._route = no_execs
    o = c.market(BTC, "BUY", 5.0, client_id="pbAlag")
    assert o["status"] == "FILLED" and o["executedQty"] == "5" and "readBack" in o     # never "not executed"


def test_position_shapes_and_what_flipster_does_not_offer():
    c, fake, _ = make()
    ready(c, (BTC, DOGE))
    assert c.position(BTC)["positionAmt"] == "0" and c.positions() == []          # settings rows only: flat
    c.market(DOGE, "SELL", 30, client_id="pbShort")
    p = c.position(DOGE)
    assert (p["positionAmt"], p["entryPrice"], p["leverage"], p["marginType"], p["positionSide"]) == \
        ("-30", "100.0", "30", "isolated", "SHORT")
    assert [x["symbol"] for x in c.positions()] == [DOGE]
    assert c.open_orders(DOGE) == [] and c.cancel_all(DOGE) == {"code": 200, "msg": "ok"}
    with pytest.raises(TestnetError):
        c.leverage_brackets()                               # signal mode: not offered (follows the paper position)
    with pytest.raises(TestnetError) as e:
        c.leverage(DOGE, 20)                                # a position open: the leverage is not changed
    assert e.value.code == "POSITION_OPEN"


# ------------------------------------------------------------------ the client-id ledger
def test_a_lost_answer_is_found_in_the_order_history_and_bound(tmp_path):
    db = str(tmp_path / "exec.db")
    c, fake, clock = make(db=db)
    ready(c)
    fake.fail("POST", "/api/v1/trade/order", "drop_after")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 5.0, client_id="pbLost1")
    row = c.ledger.get("pbLost1")
    assert row["order_id"] is None and row["state"] == "sent" and row["qty"] == "5"
    got = c.order(BTC, client_id="pbLost1")
    assert got["status"] == "FILLED" and got["executedQty"] == "5"
    assert c.ledger.get("pbLost1")["order_id"] == got["orderId"] and c.ledger.get("pbLost1")["how"] == "search"
    c2, _, _ = make(fake=fake, clock=clock, db=db)           # a restart reads the same cid from the database
    assert c2.order(BTC, client_id="pbLost1")["orderId"] == got["orderId"]
    assert sum(1 for b in posts(fake) if b["type"] == "MARKET") == 1


def test_a_partly_filled_lost_order_still_matches_its_row():
    c, fake, _ = make()
    ready(c)
    fake.partial = 0.6
    fake.fail("POST", "/api/v1/trade/order", "drop_after")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 5.0, client_id="pbLostP")
    got = c.order(BTC, client_id="pbLostP")
    assert got["executedQty"] == "3" and got["status"] == "CANCELED"


def test_several_fitting_orders_are_unknown_never_not_found():
    c, fake, clock = make()
    ready(c)
    fake.fail("POST", "/api/v1/trade/order", "drop_after", times=2)
    for cid in ("pbAmb1", "pbAmb2"):
        with pytest.raises(TransientError):
            c.market(BTC, "BUY", 1.0, client_id=cid)
    with pytest.raises(TestnetError) as e:
        c.order(BTC, client_id="pbAmb1")
    assert e.value.code == FL.AMBIGUOUS and e.value.code not in NOT_FOUND and not isinstance(e.value, TransientError)


def test_an_order_that_never_arrived_is_not_found_only_after_the_settle_window():
    c, fake, clock = make()
    ready(c)
    fake.fail("POST", "/api/v1/trade/order", "drop_before")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 1.0, client_id="pbGone1")
    clock.t += 5_000
    with pytest.raises(TransientError):                     # the history may not be written yet
        c.order(BTC, client_id="pbGone1")
    clock.t += FL.SETTLE_MS
    with pytest.raises(TestnetError) as e:
        c.order(BTC, client_id="pbGone1")
    assert e.value.code == NOT_FOUND[0] and not isinstance(e.value, TransientError)


def test_a_late_history_row_is_waited_for():
    c, fake, clock = make()
    ready(c)
    fake.history_lag_ms = 10_000
    fake.fail("POST", "/api/v1/trade/order", "drop_after")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 1.0, client_id="pbLate1")
    with pytest.raises(TransientError):
        c.order(BTC, client_id="pbLate1")
    clock.t += 12_000
    assert c.order(BTC, client_id="pbLate1")["executedQty"] == "1"


def test_no_ledger_row_is_not_found_and_a_refused_order_is_not_found_at_once():
    c, fake, _ = make()
    ready(c)
    with pytest.raises(TestnetError) as e:
        c.order(BTC, client_id="pbNever")
    assert e.value.code == NOT_FOUND[0]
    with pytest.raises(TestnetError):                       # reduce-only with nothing to reduce: refused
        c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbRef1")
    assert c.ledger.get("pbRef1")["state"] == "refused"
    with pytest.raises(TestnetError) as e:
        c.order(BTC, client_id="pbRef1")
    assert e.value.code == NOT_FOUND[0]


def test_an_opening_order_is_never_sent_twice():
    c, fake, clock = make()
    ready(c)
    fake.fail("POST", "/api/v1/trade/order", "drop_before")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 1.0, client_id="pbOnce")
    clock.t += FL.SETTLE_MS + 1_000
    with pytest.raises(TransientError):                     # the same cid again: looked up, never sent
        c.market(BTC, "BUY", 1.0, client_id="pbOnce")
    assert len(posts(fake)) == 1
    first = c.market(BTC, "BUY", 1.0, client_id="pbTwice")
    again = c.market(BTC, "BUY", 1.0, client_id="pbTwice")  # a cid that placed an order: that order answers
    assert again["orderId"] == first["orderId"] and fake.pos[BTC] == 1
    fake.fail("POST", "/api/v1/trade/order", "429")
    with pytest.raises(TransientError):                     # an opening order's 429: unknown, never resent here
        c.market(BTC, "BUY", 1.0, client_id="pbRate")
    assert len(posts(fake)) == 3


def test_a_reduce_only_order_is_sent_again_only_once_its_absence_is_settled():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 2.0, client_id="pbE")
    fake.fail("POST", "/api/v1/trade/order", "drop_before")
    with pytest.raises(TransientError):
        c.market(BTC, "SELL", 2.0, reduce_only=True, client_id="pbX1")
    with pytest.raises(TransientError):                     # inside the window: unknown, not sent
        c.market(BTC, "SELL", 2.0, reduce_only=True, client_id="pbX1")
    assert len(posts(fake)) == 2
    clock.t += FL.SETTLE_MS + 1_000
    x = c.market(BTC, "SELL", 2.0, reduce_only=True, client_id="pbX1")
    assert x["status"] == "FILLED" and fake.pos[BTC] == 0 and len(posts(fake)) == 3


def test_an_entry_is_refused_when_the_ledger_cannot_be_written_but_a_stop_still_goes_out(tmp_path):
    db = str(tmp_path / "exec.db")
    store = ExecStore(db)                                   # WAL, like the executor's own database
    c, fake, clock = make(db=db)
    ready(c)
    c.ledger.timeout_s = 0.1
    store.conn.execute("BEGIN IMMEDIATE")                   # another writer holds the database: reads still work
    try:
        with pytest.raises(TestnetError) as e:
            c.market(BTC, "BUY", 1.0, client_id="pbNoLedger")
        assert e.value.code == "LEDGER" and not posts(fake) and "locked" in c.ledger.failed
        fake.pos[BTC] = 1                                    # a position to protect (opened elsewhere)
        fake.entry[BTC] = 100.0
        st = c.stop_close(BTC, "SELL", 95.0, 1.0, client_id="pbStopNoLedger")
        assert st["algoStatus"] == "NEW" and c.ledger.get("pbStopNoLedger")["order_id"] == st["algoId"]
        assert c.algo_order(client_id="pbStopNoLedger")["algoStatus"] == "NEW"     # the row kept in memory
        store.conn.rollback()
        assert c.ledger.bind("pbStopNoLedger", st["algoId"])        # a later write stores the whole row
        assert store.conn.execute("SELECT order_id, type, reduce_only FROM flipster_ids WHERE cid = ?",
                                  ("pbStopNoLedger",)).fetchone() == (st["algoId"], "STOP_MARKET", 1)
    finally:
        store.conn.rollback()
        store.close()


def test_the_ledger_lives_in_the_executor_database_and_is_trimmed(tmp_path):
    db = str(tmp_path / "exec.db")
    store = ExecStore(db)
    c, fake, clock = make(db=db)
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbOld")
    store.event(clock.t, "INFO", "x", "an executor write in between")
    store.commit()
    clock.t += FL.LEDGER_KEEP_MS + 60_000
    c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbNew")
    cids = [r[0] for r in store.conn.execute("SELECT cid FROM flipster_ids ORDER BY sent_ms")]
    assert cids == ["pbNew"]
    store.close()                                           # the executor's clean close still leaves WAL mode
    import sqlite3
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    conn.close()


# ------------------------------------------------------------------ stops
def test_stop_place_confirm_move_cancel():
    c, fake, _ = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs1r1")
    stops = live_stops(c, BTC)
    assert len(stops) == 1 and stops[0]["algoId"] == st["algoId"] and stops[0]["triggerPrice"] == "95"
    assert covers(stops[0], 5.0) and stops[0]["side"] == "SELL" and stops[0]["reduceOnly"] is True
    assert stops[0]["clientAlgoId"] == "pbAs1r1"
    assert posts(fake, "STOP_MARKET")[0] == {"symbol": "BTCUSDT.PERP", "side": "SELL", "type": "STOP_MARKET",
                                             "quantity": "5", "price": "95", "reduceOnly": True}
    seen = {}
    orig = c.cancel_algo

    def watch(algo_id=None, client_id=None):
        seen.setdefault("during", len(live_stops(c, BTC)))
        return orig(algo_id=algo_id, client_id=client_id)
    c.cancel_algo = watch
    fake.set_price(BTC, 105.0)
    mv = move_stop(c, BTC, "SELL", 101.1, 5.0, [st["algoId"]], client_id="pbAs2r2")
    c.cancel_algo = orig
    assert mv["result"] == "moved" and seen["during"] == 2
    assert [(x["triggerPrice"], x["quantity"]) for x in live_stops(c, BTC)] == [("101.1", "5")]
    assert not fake.unprotected()
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == "CANCELED"
    assert c.algo_order(client_id="pbAs2r2")["algoStatus"] == "NEW"
    c.cancel_all_algo(BTC)
    assert not live_stops(c, BTC)


def test_a_stop_past_the_price_is_refused_before_it_is_sent():
    c, fake, _ = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    fake.set_price(BTC, 100.5)
    with pytest.raises(TestnetError) as e:
        c.stop_close(BTC, "SELL", 101.1, 5.0, client_id="pbAs3r3")
    assert e.value.code == WOULD_TRIGGER and not posts(fake, "STOP_MARKET")
    mv = move_stop(c, BTC, "SELL", 101.1, 5.0, [], client_id="pbAs3r4", close_id="pbAx3")
    assert mv["result"] == "closed" and mv["flat"] and fake.pos[BTC] == 0


def test_a_refused_stop_while_the_price_is_past_it_reads_as_would_trigger():
    c, fake, _ = make()
    fake.past_stop = "refuse"
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    real = fake._route
    moved = {}

    def move_then_place(m, path, query, body):         # the price moves between our check and the exchange's
        if m == "POST" and body and b"STOP_MARKET" in body and not moved:
            moved["x"] = True
            fake.prices[BTC] = 94.0
        return real(m, path, query, body)
    fake._route = move_then_place
    with pytest.raises(TestnetError) as e:
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbAs9")
    assert e.value.code == WOULD_TRIGGER and c.ledger.get("pbAs9")["state"] == "refused"


@pytest.mark.parametrize("own_fills", [True, False])
def test_a_fired_stop_reads_as_triggered(own_fills):
    c, fake, _ = make()
    fake.own_fills = own_fills
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs4r4")
    fake.set_price(BTC, 94.0)
    assert fake.pos[BTC] == 0
    got = c.algo_order(algo_id=st["algoId"])
    assert got["algoStatus"] == "TRIGGERED"
    assert got["actualOrderId"] == (st["algoId"] if own_fills else "")
    fills = c.user_trades(BTC, T0 - 5_000, T0 + 5_000)
    assert [f["side"] for f in fills] == ["BUY", "SELL"] and fills[1]["realizedPnl"] == "-30"


@pytest.mark.parametrize("which", ["last", "mark"])
def test_the_stop_fires_on_the_fakes_chosen_price(which):
    c, fake, _ = make()
    fake.stop_price = which
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs")
    fake.set_price(BTC, 94.0 if which == "mark" else 96.0, mark=96.0 if which == "mark" else 94.0)
    assert fake.pos[BTC] == 5                              # the other price crossed: not fired
    fake.set_price(BTC, 94.0, mark=94.0)
    assert fake.pos[BTC] == 0


def test_a_stop_whose_answer_was_lost_is_found_by_its_client_id():
    c, fake, _ = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    fake.fail("POST", "/api/v1/trade/order", "drop_after")
    with pytest.raises(TransientError):
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbAs1r9")
    got = c.algo_order(client_id="pbAs1r9")                # in the pending list, by side / qty / trigger
    assert got["algoStatus"] == "NEW" and got["triggerPrice"] == "95" and got["clientAlgoId"] == "pbAs1r9"
    again = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs1r9")    # the same cid: never a second copy
    assert again["algoId"] == got["algoId"] and len(fake.live_stops(BTC)) == 1


def test_a_cancelled_stop_reads_as_cancelled_and_a_second_cancel_is_not_found():
    c, fake, _ = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs5r5")
    c.cancel_algo(client_id="pbAs5r5")
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == "CANCELED"
    with pytest.raises(TestnetError) as e:
        c.cancel_algo(algo_id=st["algoId"])
    assert e.value.code in NOT_FOUND


def test_two_stops_refused_stops_the_move_with_the_old_stop_in_place():
    c, fake, _ = make()
    fake.two_stops = False
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs")
    with pytest.raises(TestnetError):
        move_stop(c, BTC, "SELL", 96.0, 5.0, [st["algoId"]], client_id="pbAs2")
    assert [x["algoId"] for x in live_stops(c, BTC)] == [st["algoId"]]


# ------------------------------------------------------------------ missing and garbled fields
def test_missing_or_garbled_fields_are_errors_never_flat_or_empty():
    c, fake, _ = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbAs")
    real = fake._route
    edits = {}

    def edit(m, path, query, body):
        st, raw, h = real(m, path, query, body)
        f = edits.get(path)
        if f and m == "GET":
            raw = json.dumps(f(json.loads(raw))).encode()
        return st, raw, h
    fake._route = edit
    cases = [
        ("/api/v1/account/position", lambda d: [{**r, "positionAmount": None} for r in d]),     # side, no size
        ("/api/v1/account/position", lambda d: [{**r, "positionSide": "BOTH"} for r in d]),
        ("/api/v1/account/position", lambda d: [{**r, "positionAmount": "-5"} for r in d]),     # LONG with -5
        ("/api/v1/account/position", lambda d: {"positions": d}),                               # not a list
        ("/api/v1/account/position", lambda d: d + d),                                          # two on one coin
        ("/api/v1/trade/order", lambda d: {}),                                                  # no orders list
        ("/api/v1/trade/order", lambda d: {"orders": [{**o, "triggerPrice": None, "price": None}
                                                      for o in d["orders"]]}),                  # a stop, no level
        ("/api/v1/trade/order", lambda d: {"orders": [{**o, "status": "UNTRIGGERED"} for o in d["orders"]]}),
    ]
    for path, f in cases:
        edits.clear()
        edits[path] = f
        with pytest.raises(TransientError):
            float(c.position(BTC)["positionAmt"]) if "position" in path else live_stops(c, BTC)
    edits.clear()
    edits["/api/v1/trade/execution/history"] = lambda d: {**d, "history": [{k: v for k, v in r.items()
                                                                            if k != "execFee"} for r in d["history"]]}
    with pytest.raises(TransientError):
        c.user_trades(BTC, T0 - 5_000, T0 + 5_000)
    edits["/api/v1/trade/execution/history"] = lambda d: {"history": d["history"]}            # no hasNext
    with pytest.raises(TransientError):
        c.user_trades(BTC, T0 - 5_000, T0 + 5_000)
    edits.clear()
    edits["/api/v1/account/position"] = lambda d: [{**r, "positionSide": None, "positionAmount": None} for r in d]
    assert c.position(BTC)["positionAmt"] == "0"            # a settings row (both empty) is a flat coin


# ------------------------------------------------------------------ fills, P&L, funding
def test_fills_replay_the_realized_pnl_and_mark_our_closes():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbAe")
    clock.t += 60_000
    fake.set_price(BTC, 110.0)
    c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbAx")
    fills = c.user_trades(BTC, T0 - 5_000, clock.t + 5_000)
    assert [f["side"] for f in fills] == ["BUY", "SELL"]
    out = fills[1]
    assert out["realizedPnl"] == "50" and out["realizedSource"] == "replay" and out["reduceOnly"] is True
    assert float(out["commission"]) == pytest.approx(0.0006 * 5 * 110.0) and out["commissionAsset"] == "USDT"
    assert float(c.account()["totalWalletBalance"]) == pytest.approx(10_000 + 50 - 0.0006 * 5 * 210)
    # a window that starts after the entry: our close is still a close (P&L unknown), never a new short
    late = c.user_trades(BTC, T0 + 30_000, clock.t + 5_000)
    assert len(late) == 1 and late[0]["realizedSource"] == "unknown" and late[0]["realizedPnl"] == "0"


def test_a_full_history_page_is_read_again_in_halves():
    c, fake, clock = make()
    ready(c, (DOGE,))
    for i in range(50):
        c.market(DOGE, "BUY", 10.0, client_id=f"pbB{i}")
        c.market(DOGE, "SELL", 10.0, reduce_only=True, client_id=f"pbC{i}")
        clock.t += 1_000
    fills = c.user_trades(DOGE, T0 - 1_000, clock.t + 1_000)
    assert len(fills) == 100 and len({f["id"] for f in fills}) == 100


def test_a_history_that_ignores_its_time_filter_is_an_error_not_an_endless_split():
    c, fake, clock = make()
    real = fake._route

    def always_more(m, path, query, body):
        st, raw, h = real(m, path, query, body)
        if path == "/api/v1/trade/execution/history":
            raw = json.dumps({**json.loads(raw), "hasNext": True}).encode()
        return st, raw, h
    fake._route = always_more
    with pytest.raises(TransientError):
        c.user_trades(BTC, T0 - 86_400_000, T0)
    assert sum(1 for x in fake.calls if x[2] == "/api/v1/trade/execution/history") <= FL.HISTORY_REQUESTS


def test_funding_rows_and_no_transfers():
    c, fake, clock = make()
    fake.add_funding(BTC, -1.25, time=T0 + 1_000)
    fake.add_funding(DOGE, 0.5, time=T0 + 2_000)
    rows = c.income(None, None, T0, T0 + 10_000)
    assert [(r["symbol"], r["incomeType"], r["income"]) for r in rows] == [(BTC, "FUNDING_FEE", "-1.25"),
                                                                          (DOGE, "FUNDING_FEE", "0.5")]
    assert [r["symbol"] for r in c.income(BTC, None, T0, T0 + 10_000)] == [BTC]
    assert c.income(None, "TRANSFER", T0, T0 + 10_000) == []


def test_fee_rate_levels():
    c, fake, _ = make()
    fee = c.fee_rate()
    assert fee["taker"] == 0.0006 and fee["level"] == 0 and fee["rows"] == 2


# ------------------------------------------------------------------ keys and allowlist
def test_keys_gates_and_reuse_refusals():
    assert FL.trading_keys("mainnet", LIVE_ENV) == ("fk", "fs")
    for drop, needle in ((FLAG, "실거래 스위치"), ("FLIPSTER_LIVE_SECRET", "비어")):
        env = {k: v for k, v in LIVE_ENV.items() if k != drop}
        with pytest.raises(Refused, match=needle):
            FL.trading_keys("mainnet", env)
    for name, needle in (("BINANCE_API_KEY", "paper"), ("LIVE_API_KEY", "바이낸스"), ("TESTNET_API_SECRET", "바이낸스"),
                         ("BYBIT_LIVE_API_KEY", "바이비트"), ("MEXC_LIVE_KEY", "MEXC"),
                         ("WOOXPRO_LIVE_SECRET", "WOO X Pro")):
        with pytest.raises(Refused, match=needle):
            FL.trading_keys("mainnet", {**LIVE_ENV, name: "fk"})
    with pytest.raises(Refused, match="paper"):
        FL.trading_keys("mainnet", LIVE_ENV, {"BINANCE_API_SECRET": "fs"})
    with pytest.raises(Refused, match="테스트넷"):
        FL.trading_keys("testnet", LIVE_ENV)
    with pytest.raises(Refused, match="같습니다"):
        FL.trading_keys("mainnet", {**LIVE_ENV, "FLIPSTER_LIVE_SECRET": "fk"})


def test_the_owners_statement_is_required(tmp_path):
    env = {k: v for k, v in LIVE_ENV.items() if k != FL.KEY_CHECKED}
    c, kc = FL.clients("mainnet", env)
    assert not kc.attested and c.ledger.path is None
    with pytest.raises(Refused, match=FL.KEY_CHECKED):
        FL.check_executor_keys("mainnet", c, kc, env, {})
    c, kc = FL.clients("mainnet", LIVE_ENV, db=str(tmp_path / "x.db"))
    FL.check_executor_keys("mainnet", c, kc, LIVE_ENV, {})
    fake = FakeFlipster()
    fake.clock = Clock()
    for attested, problems in ((True, False), (False, True)):
        k = FL.FlipsterKeyCheckClient("fk", "fs", send=fake, clock_ms=fake.clock, sleep=lambda s: None,
                                      attested=attested)
        assert bool(check_permissions(k.api_restrictions())) is problems


def test_refuse_unless_allowed(tmp_path):
    db = str(tmp_path / "exec.db")
    c, kc = FL.clients("mainnet", LIVE_ENV, db=db)
    FL.refuse_unless_allowed("mainnet", c, db)
    with pytest.raises(Refused):
        FL.refuse_unless_allowed("testnet", c, db)
    with pytest.raises(Refused):
        FL.refuse_unless_allowed("mainnet", kc, db)                     # the key-check class never trades
    with pytest.raises(Refused, match="장부"):
        FL.refuse_unless_allowed("mainnet", c, str(tmp_path / "other.db"))
    with pytest.raises(Refused, match="장부"):
        FL.refuse_unless_allowed("mainnet", FL.clients("mainnet", LIVE_ENV)[0], db)    # a ledger in memory


def test_agents_never_import_the_module():
    root = ROOT / "paperbot"
    for p in list(root.glob("agents*.py")) + list(root.glob("rooms*.py")) + list((root / "agents").glob("**/*.py")):
        assert "flipster" not in p.read_text(encoding="utf-8"), p


def test_the_live_config_and_the_wrapper():
    cfg = ExecConfig.from_file(str(ROOT / "deploy" / "executor.live-flipster.json"))
    assert not cfg.problems()
    assert (cfg.exchange, cfg.mode, cfg.db, cfg.paper_db, cfg.account) == (
        "flipster", "mainnet", "/var/lib/paperbot/exec/executor-flipster-live.db", "/var/lib/paperbot/combo/vwap.db",
        "COMBO@mix")
    base = json.loads((ROOT / "deploy" / "executor.live-wooxpro-vwap.json").read_text(encoding="utf-8"))
    mine = json.loads((ROOT / "deploy" / "executor.live-flipster.json").read_text(encoding="utf-8"))
    assert mine["net_costs"].pop("flipster") == {"taker_fee": 0.0006, "slippage": 0.0002}
    assert {k: v for k, v in mine.items() if k not in ("exchange", "db")} == \
        {k: v for k, v in base.items() if k not in ("exchange", "db")}
    assert "bybit|mexc|wooxpro|flipster) shift" in (ROOT / "deploy" / "paperbot-exec.sh").read_text(encoding="utf-8")
    env = (ROOT / "deploy" / "executor.env.example").read_text(encoding="utf-8")
    for name in ("FLIPSTER_LIVE_KEY", "FLIPSTER_LIVE_SECRET", "FLIPSTER_LIVE_KEY_CHECKED"):
        assert f"\n{name}=\n" in env


# ------------------------------------------------------------------ the drill
def drill_world(**kw):
    c, fake, clock = make(**kw)
    fake.prices[DOGE] = fake.marks[DOGE] = 0.2
    return c, fake, clock


def test_drill_check_and_order_cycle_with_the_trigger_test():
    c, fake, clock = drill_world()
    kc = FL.FlipsterKeyCheckClient("fk", "fs", send=fake, clock_ms=clock, sleep=lambda s: None, attested=True)

    def wait(s):
        clock.t += int(s * 1000)
        stops = [float(o["triggerPrice"]) for o in fake.live_stops(DOGE)]
        if fake.pos[DOGE] and len(stops) == 1 and stops[0] < 0.2:
            fake.set_price(DOGE, 0.2008)                  # 0.4 % our way: the test stop goes above the entry
        elif fake.pos[DOGE] and len(stops) == 1 and stops[0] > 0.2:
            fake.set_price(DOGE, 0.2, mark=0.2008)        # ... the last price comes back to it (not the mark): fires
    d = FL.FlipsterDrill(c, symbol=DOGE, keycheck=kc, wait=wait, trigger_wait_s=600, elapsed=lambda: clock.t / 1000)
    d.check()
    d.order_cycle()
    fails = [r for r in d.log if not r["ok"]]
    assert not fails, fails
    steps = {r["step"]: r for r in d.log}
    assert steps["답을 잃은 주문 찾기(장부의 주문 번호를 지우고 주문 기록 검색으로 같은 주문)"]["ok"]
    fired = next(r for k, r in steps.items() if k.startswith("손절 발동 시험:"))
    assert fired["detail"]["status"] == "TRIGGERED"
    assert steps["손절을 발동시킨 가격(마지막 가격 / 마크 가격)"]["detail"]["verdict"] == "마지막 가격"
    assert steps["발동한 손절의 체결이 손절 자신의 orderId로 기록됨"]["ok"]
    assert steps["이익 쪽 손절(계단 잠금 자리, 진입가보다 유리한 곳)이 걸림"]["ok"]
    pnl = next(r for k, r in steps.items() if k.startswith("체결로 계산한 손익"))
    assert pnl["detail"]["fee_rate_pct"] == pytest.approx(0.06, abs=1e-3)
    assert fake.pos[DOGE] == 0 and not fake.pending and not fake.slippage_sent


def test_drill_prints_each_step_and_ends_flat_without_the_trigger_test():
    c, fake, clock = drill_world()
    lines = []
    d = FL.FlipsterDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000,
                         say=lines.append)
    assert FL.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert len([x for x in lines if x.startswith("[OK]")]) == len(d.log)
    assert lines[-1] == "끝: drill 모두 [OK]"
    assert fake.pos[DOGE] == 0 and not fake.pending


def test_the_drill_without_the_confirmation_sends_no_order():
    c, fake, clock = drill_world()
    d = FL.FlipsterDrill(c, symbol=DOGE, wait=lambda s: None, elapsed=lambda: clock.t / 1000)
    assert FL.run_drill(c, d, "drill", False, pause=lambda s: None)
    assert not posts(fake) and d.log[-1]["step"] == "주문 단계"


@pytest.mark.parametrize("stop", ["error", "ctrl_c"])
def test_a_drill_stopped_part_way_leaves_the_coin_flat(stop):
    c, fake, clock = drill_world()
    lines = []

    def wait(s):            # the stop is resting and the trigger test waits: then the drill is stopped
        clock.t += int(s * 1000)
        if fake.pos[DOGE] and fake.pending and clock.t > T0 + 90_000:
            if stop == "ctrl_c":
                raise KeyboardInterrupt("SIGHUP")
            raise ValueError("an unexpected reply")
    d = FL.FlipsterDrill(c, symbol=DOGE, wait=wait, trigger_wait_s=600, elapsed=lambda: clock.t / 1000,
                         say=lines.append)
    assert not FL.run_drill(c, d, "drill", True, pause=lambda s: None)
    steps = {r["step"]: r for r in d.log}
    assert not steps["멈춤"]["ok"]
    assert steps["정리 후 상태"]["ok"], steps["정리 후 상태"]
    assert fake.pos[DOGE] == 0 and not fake.pending
    assert lines[-1].startswith("끝: drill [FAIL]")


def test_drill_stops_when_two_stops_cannot_rest_at_once():
    c, fake, clock = drill_world()
    fake.two_stops = False
    d = FL.FlipsterDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000)
    assert not FL.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert fake.pos[DOGE] == 0 and not fake.pending


# ------------------------------------------------------------------ the executor, whole cycle
class Source:
    def __init__(self, clock):
        self.clock, self.intent, self.ts = clock, None, None

    def read(self):
        return self.intent, (self.ts if self.ts is not None else self.clock() - 30_000)


class World:
    def __init__(self, tmp_path, fake=None, **cfg_kw):
        self.clock = Clock()
        self.fake = fake or FakeFlipster(wallet=10_000.0)
        self.fake.clock = self.clock
        self.src = Source(self.clock)
        self.note = ListNotifier()
        risk = R.RiskConfig(daily_max_loss_usd=500.0, max_drawdown_pct=0.2, max_consecutive_losses=3, max_leverage=40,
                            max_notional_usd=1_000.0, allowed_symbols=(BTC, "ETHUSDT"),
                            kill_file=str(tmp_path / "STOP"))
        self.cfg = ExecConfig(account="COMBO@mix", paper_db=str(tmp_path / "vwap.db"),
                              db=str(tmp_path / "executor-flipster-live.db"), qty_scale=1.0, risk=risk, retries=4,
                              sweep_every=1, exchange="flipster", mode="mainnet", budget_usd=10_000.0,
                              paper_env_file=str(tmp_path / "live.env"), **cfg_kw)
        self.store = ExecStore(self.cfg.db)
        kw = dict(send=self.fake, clock_ms=self.clock, sleep=lambda s: None)
        self.client = FL.FlipsterClient("fk", "fs", ledger=FL.IdLedger(self.cfg.db), **kw)
        self.keycheck = FL.FlipsterKeyCheckClient("fk", "fs", attested=True, **kw)
        self.ex = Executor(self.cfg, self.client, self.src, self.store, self.note, now_ms=self.clock,
                           sleep=lambda s: None, keycheck=self.keycheck, env=dict(LIVE_ENV))
        self.ex.start()

    def loop(self, n=1):
        for _ in range(n):
            self.clock.t += 3_000
            self.ex.loop_once()

    def paper(self, stop, side=1, qty=5.0, lev=20, entry=100.0):
        et = self.src.intent.entry_time if self.src.intent else self.clock.t - 60_000
        self.src.intent = Intent(key=f"COMBO@mix|{BTC}|{et}", symbol=BTC, side=side, qty=qty, leverage=lev,
                                 stop=stop, entry_price=entry, entry_time=et)

    def stops(self):
        return [(float(o["triggerPrice"]), float(o["quantity"])) for o in self.fake.live_stops(BTC)]


def test_executor_config_problems():
    risk = R.RiskConfig(max_leverage=40, allowed_symbols=(BTC,), kill_file="/var/lib/paperbot/STOP")
    cfg = ExecConfig(account="A@b", paper_db="p", db="/var/lib/paperbot/exec/x.db", qty_scale=1.0, exchange="flipster",
                     mode="testnet", budget_usd=100.0, risk=risk)
    assert any("플립스터에는 테스트넷이 없습니다" in p for p in cfg.problems())
    cfg = ExecConfig(account="A@b", paper_db="p", db="/var/lib/paperbot/exec/x.db", qty_scale=1.0, exchange="flipster",
                     mode="mainnet", budget_usd=100.0, risk=risk,
                     net_costs={"flipster": {"taker_fee": 0.0006, "slippage": 0.0002}})
    assert not [p for p in cfg.problems() if "net_costs" in p or "exchange" in p or "플립스터" in p]
    assert cfg.net_cost() == {"taker_fee": 0.0006, "slippage": 0.0002}
    cfg = ExecConfig(account="A@b", paper_db="p", db="/var/lib/paperbot/exec/x.db", qty_scale=1.0, exchange="kraken",
                     mode="mainnet", budget_usd=100.0, risk=risk)
    assert any('"flipster"' in p for p in cfg.problems())


def test_the_executor_refuses_testnet_and_a_ledger_outside_its_database(tmp_path):
    w = World(tmp_path)
    store2 = ExecStore(str(tmp_path / "t.db"))
    cfg = ExecConfig(**{**w.cfg.__dict__, "mode": "testnet", "db": str(tmp_path / "t.db")})
    with pytest.raises(Refused):
        Executor(cfg, w.client, w.src, store2, w.note, now_ms=w.clock, sleep=lambda s: None, keycheck=w.keycheck,
                 env=dict(LIVE_ENV))
    store3 = ExecStore(str(tmp_path / "u.db"))
    cfg = ExecConfig(**{**w.cfg.__dict__, "db": str(tmp_path / "u.db")})
    with pytest.raises(Refused, match="장부"):
        Executor(cfg, w.client, w.src, store3, w.note, now_ms=w.clock, sleep=lambda s: None, keycheck=w.keycheck,
                 env=dict(LIVE_ENV))


def test_executor_entry_stop_lock_steps_and_exit_from_fills(tmp_path):
    w = World(tmp_path)
    assert w.fake.mode == "ONE_WAY" and w.fake.levs[BTC] == ["ISOLATED", 40]
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.pos[BTC] == 5 and w.stops() == [(95.0, 5.0)]
    assert w.fake.levs[BTC] == ["ISOLATED", 20]                       # the paper's leverage
    assert w.ex.prefix == "[플립스터 실거래 실행기]" and w.store.get_state("meta")["exchange"] == "flipster"
    entry_cid = f"pb{w.ex.trade['base']}e"
    assert w.client.ledger.get(entry_cid)["order_id"] == w.ex.trade["orders"][0]
    for price, lock in [(105.0, 101.1), (109.0, 104.9), (113.0, 109.3)]:
        w.fake.set_price(BTC, price)
        w.paper(stop=lock)
        w.loop()
        assert w.stops() == [(lock, 5.0)], (price, lock)
    assert not w.fake.unprotected()
    w.fake.add_funding(BTC, -1.25)
    w.src.intent = None                                               # paper exit
    w.loop(2)
    assert w.fake.pos[BTC] == 0 and not w.fake.pending and w.ex.trade is None
    pnl, source = w.store.conn.execute("SELECT pnl, pnl_source FROM trades").fetchone()
    assert source == "fills" and pnl == pytest.approx(w.fake.wallet - 10_000.0, abs=1e-6)
    assert not w.fake.slippage_sent


def test_executor_books_a_stop_that_fired_on_the_exchange(tmp_path):
    w = World(tmp_path)
    w.paper(stop=95.0)
    w.loop()
    w.fake.set_price(BTC, 94.0)                                       # the exchange stop fires
    w.loop(3)
    assert w.fake.pos[BTC] == 0 and w.ex.trade is None
    reason, source = w.store.conn.execute("SELECT exit_reason, pnl_source FROM trades").fetchone()
    assert "손절" in reason and source == "fills"


def test_executor_finds_an_entry_whose_answer_was_lost_through_the_ledger(tmp_path):
    w = World(tmp_path)
    w.fake.fail("POST", "/api/v1/trade/order", "drop_after")
    w.paper(stop=95.0)
    w.loop()                                       # the answer is lost: Guarded looks it up by its cid (the ledger)
    assert w.ex.trade["status"] == "open" and w.fake.pos[BTC] == 5 and w.stops() == [(95.0, 5.0)]
    assert len(posts(w.fake, "MARKET")) == 1
    assert w.client.ledger.get(f"pb{w.ex.trade['base']}e")["how"] == "search"


def test_executor_adopts_an_entry_whose_history_row_lags(tmp_path):
    w = World(tmp_path)
    w.fake.history_lag_ms = 10_000
    w.fake.fail("POST", "/api/v1/trade/order", "drop_after")
    w.paper(stop=95.0)
    w.loop()                                       # not in the history yet: unknown, never resent
    assert w.ex.trade["status"] == "entering" and w.fake.pos[BTC] == 5
    w.loop()                                       # the reconcile adopts and protects it
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)]
    assert len(posts(w.fake, "MARKET")) == 1 and not w.fake.unprotected()


def test_executor_drops_an_entry_that_never_arrived_after_the_window(tmp_path):
    w = World(tmp_path)
    w.fake.fail("POST", "/api/v1/trade/order", "drop_before")
    w.paper(stop=95.0)
    w.loop()
    key = w.ex.trade["key"]
    assert w.ex.trade["status"] == "entering" and w.fake.pos[BTC] == 0
    errors = 0
    for _ in range(40):                            # 2 minutes: past the settle window and entry_unknown_s
        try:
            w.loop()
        except TransientError:
            errors += 1                            # "not in the history yet" inside the settle window
        if w.ex.trade is None:
            break
    assert w.ex.trade is None and key in w.ex.done and errors
    assert len(posts(w.fake, "MARKET")) == 1 and w.fake.pos[BTC] == 0     # the lost entry was never sent again
