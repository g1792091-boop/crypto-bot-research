"""Toobit (paperbot/toobit.py) on the fake exchange (tests/faketoobit.py): signing (the docs' own examples), the host
allowlist, key gates, contract units (contracts x contractMultiplier; LOT_SIZE in contracts or in base units), orders
(LIMIT + priceType MARKET, the OPEN / CLOSE sides, read back, a resting remainder cancelled), newClientOrderId mapping
and look-ups (no ledger), STOP-order stops (place, confirm from the stop list, move with two at once, cancel, fire; a
lost stop answer found by its client id), lagging records, 429 and the protective budget, missing fields, fills and P&L
(Toobit's own realizedPnl checked against the replay), funding and transfers, the drill, and the executor's whole cycle
with ``"exchange": "toobit"`` (owners 10-25). No network."""

import dataclasses
import hashlib
import hmac
import json
import pathlib
import socket
import urllib.parse

import pytest

from faketoobit import SPECS, FakeToobit
from paperbot import risk as R
from paperbot import toobit as TB
from paperbot.executor import ExecConfig, ExecStore, Executor, Guarded, Intent, Refused
from paperbot.mainnet import FLAG, FLAG_VALUE, check_permissions
from paperbot.notify import ListNotifier
from paperbot.testnet import (BAD_TIMESTAMP, NOT_FOUND, WOULD_TRIGGER, ProtectionError, RateLimited, TestnetError,
                              TransientError, covers, live_stops, move_stop, place_stop)

T0 = 1_800_000_000_000
BTC, ETH, DOGE, LTC = "BTCUSDT", "ETHUSDT", "DOGEUSDT", "LTCUSDT"
LIVE_ENV = {FLAG: FLAG_VALUE, "TOOBIT_LIVE_KEY": "tk", "TOOBIT_LIVE_SECRET": "ts", TB.KEY_CHECKED: TB.KEY_CHECKED_VALUE}
ROOT = pathlib.Path(__file__).resolve().parents[1]
ORDER = "/api/v1/futures/order"
OPEN = "/api/v1/futures/openOrders"


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


def ticking(clock):
    """A sleep that moves the test clock (the fake's lags and the protective budget run on it)."""
    def tick(s):
        clock.t += int(round(s * 1000))
    return tick


def make(fake=None, clock=None, advance=False, **kw):
    clock = clock or Clock()
    fake = fake or FakeToobit()
    fake.clock = clock
    c = TB.ToobitClient("tk", "ts", send=fake, clock_ms=clock, sleep=ticking(clock) if advance else (lambda s: None),
                        **kw)
    return c, fake, clock


def ready(c, symbols=(BTC,)):
    c.sync_time()
    c.one_way()
    for s in symbols:
        c.isolated(s)
    return c


def orders(fake):
    return fake.order_bodies


def stops_sent(fake):
    return fake.stop_bodies


def calls(fake, method, path):
    return [x for x in fake.calls if x[1] == method and x[2] == path]


def edit_route(fake, path, f, method="GET"):
    """Rewrite one route's answer (f: the parsed answer -> the answer sent)."""
    real = fake._route

    def edited(m, p, q):
        st, raw, h = real(m, p, q)
        if p == path and m == method and st == 200:
            raw = json.dumps(f(json.loads(raw))).encode()
        return st, raw, h
    fake._route = edited


def reset_route(fake):
    fake._route = FakeToobit._route.__get__(fake)


# ------------------------------------------------------------------ signing, transport, errors
def test_signature_matches_the_docs_examples():
    """The docs' SIGNED endpoint examples: hex HMAC-SHA256 of the query string (example 1) and of the query string
    followed by the body without an "&" between them (example 3)."""
    secret = "30lfjDT51iOG1kYZnDoLNynOyMdIcmQyO1XYfxzYOmQfx9tjiI98Pzio4uhZ0Uk2"
    q = TB.query_string({"symbol": "BTCUSDT", "side": "SELL", "type": "LIMIT", "timeInForce": "GTC", "quantity": 1,
                         "price": 400, "recvWindow": 100000, "timestamp": 1668481902307})
    assert q == "symbol=BTCUSDT&side=SELL&type=LIMIT&timeInForce=GTC&quantity=1&price=400&recvWindow=100000" \
                "&timestamp=1668481902307"
    assert TB.signature(secret, q) == "8420e499e71cce4a00946db16543198b6bcae01791bdb75a06b5a7098b156468"
    mixed = "symbol=BTCUSDT&side=SELL&type=LIMIT&timeInForce=GTC" + "quantity=1&price=400&recvWindow=10000000" \
            "&timestamp=1668481902307"
    assert TB.signature(secret, mixed) == "59ef0b2085ebb99cca5b6445c202d99add17be2d5d1861c0f4aa17bc785ac4d5"
    assert TB.tb(BTC) == "BTC-SWAP-USDT" and TB.bn("BTC-SWAP-USDT") == BTC and TB.bn("BTC-SWAP") == ""
    assert TB.bn("BTCUSDT") == "" and TB.query_string({"a": None, "b": True}) == "b=true"


def test_signed_requests_timestamp_and_the_host_allowlist():
    c, fake, clock = make()
    assert c.sync_time() == 0 and c.time_source == "/api/v1/time"
    c.account()
    _, method, path, query, body = calls(fake, "GET", "/api/v1/futures/balance")[-1]
    assert body is None
    q = dict(urllib.parse.parse_qsl(query))
    assert set(q) == {"recvWindow", "timestamp", "signature"} and q["recvWindow"] == "5000"
    assert q["signature"] == hmac.new(b"ts", query[:query.index("&signature=")].encode(), hashlib.sha256).hexdigest()
    bad = TB.ToobitClient("tk", "other", send=fake, clock_ms=clock, sleep=lambda s: None)
    with pytest.raises(TestnetError) as e:                     # the fake checks every signature
        bad.account()
    assert e.value.code == "AUTH" and not isinstance(e.value, TransientError)
    wrong = TB.ToobitClient("other", "ts", send=fake, clock_ms=clock, sleep=lambda s: None)
    with pytest.raises(TestnetError) as e:
        wrong.account()
    assert e.value.code == "AUTH" and "IP" in e.value.msg
    c.offset_ms = -6_000                                       # older than recvWindow: refused, never executed
    with pytest.raises(TestnetError) as e:
        c.account()
    assert e.value.code == BAD_TIMESTAMP
    c.offset_ms = 0
    for base in ("https://www.toobit.com", "http://api.toobit.com", "https://api.toobit.com:8443",
                 "https://api.toobit.com/x", "https://api.toobit.com.evil.com"):
        with pytest.raises(ValueError):
            TB.ToobitClient("tk", "ts", base=base)
    for args in (("tk", ""), ("", "ts")):
        with pytest.raises(ValueError):
            TB.ToobitClient(*args)
    assert TB.ToobitClient.HOSTS == ("api.toobit.com",) and TB.hosts_for("mainnet") == ("api.toobit.com",)


def test_a_post_carries_its_parameters_in_a_signed_form_body():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbBody1")
    _, method, path, query, body = next(x for x in fake.calls if x[1] == "POST" and x[2] == ORDER)
    assert query == "" and body.decode().startswith("symbol=BTC-SWAP-USDT&side=BUY_OPEN&type=LIMIT&priceType=MARKET")
    raw = body.decode()
    assert hmac.new(b"ts", raw[:raw.index("&signature=")].encode(), hashlib.sha256).hexdigest() == raw.split("=")[-1]
    cancel = [x for x in fake.calls if x[1] == "DELETE"]
    assert all(x[4] is None for x in cancel)                   # a DELETE carries its parameters in the query string


def test_the_public_client_reads_specs_without_a_key_and_never_signs():
    fake = FakeToobit()
    fake.clock = Clock()
    c = TB.ToobitClient("", "", public_only=True, send=fake, clock_ms=fake.clock, sleep=lambda s: None)
    assert c.spec(BTC)["ct_val"] == "0.001" and c.price(BTC) == 100.0
    text = TB.specs_text(c)
    assert "BTCUSDT: 상태 Trading" in text and "요청 한도(exchangeInfo)" in text and "코인 단위로 읽음" in text
    with pytest.raises(TestnetError) as e:
        c.account()
    assert e.value.code == "NO_KEY"
    assert all(x[2] in ("/api/v1/exchangeInfo", "/api/v1/time") or x[2].startswith("/quote/") for x in fake.calls)


def test_error_mapping_to_the_executor_classes():
    c, fake, clock = make()
    ready(c)
    fake.fail("GET", "/api/v1/futures/balance", "503_before", times=4)
    with pytest.raises(TransientError):
        c.account()
    fake.fails.clear()
    fake.fail("GET", "/api/v1/futures/positions", "403")
    with pytest.raises(RateLimited) as e:
        c.positions()
    assert e.value.status == 418
    fake.fail("GET", "/api/v1/futures/accountLeverage", ("err", 401, -2015, "Invalid API-key, IP, or permissions"))
    with pytest.raises(Refused, match="IP"):
        c.isolated(ETH)
    fake.fail("GET", "/api/v1/futures/balance", ("err", 400, -1102, "Mandatory parameter was not sent"))
    with pytest.raises(TestnetError) as e:
        c.account()
    assert e.value.code == -1102 and not isinstance(e.value, TransientError)
    fake.fail("GET", "/api/v1/futures/balance", ("err", 400, -9001, "Too many requests, slow down"), times=9)
    with pytest.raises(RateLimited):
        c.account()
    fake.fails.clear()
    with pytest.raises(TestnetError) as e:                     # cancel of an unknown order: -2013
        c.cancel(BTC, "123")
    assert e.value.code in NOT_FOUND
    with pytest.raises(TestnetError) as e:                     # a close with nothing to close: refused, nothing ran
        c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbX")
    assert e.value.code == -2010 and not isinstance(e.value, TransientError) and "pbX" not in c.sent
    fake.fail("POST", ORDER, ("err", 400, -3130, "order margin insufficient"))
    with pytest.raises(TestnetError) as e:
        c.market(BTC, "BUY", 1.0, client_id="pbE1")
    assert e.value.code == -3130 and not isinstance(e.value, TransientError) and "pbE1" not in c.sent
    assert TB.definite(e.value)


RAN_THEN = [("err_after", 400, -1006, "An unexpected response was received. Execution status unknown."),
            ("err_after", 400, -1007, "Timeout waiting for response from backend server."),
            ("err_after", 400, -9999, "Order expired: matching engine timeout"),
            ("err_after", 400, -1141, "Duplicate clientOrderId"), ("err_after", 400, None, "Bad Request"),
            ("err_after", 200, -1000, "An unknown error occurred"), "403_after"]


@pytest.mark.parametrize("kind", RAN_THEN)
def test_an_order_that_ran_but_was_answered_otherwise_is_never_read_as_refused(kind):
    """An order or a stop is refused only on a documented refusal code. "Execution status unknown", a duplicate id, an
    undocumented code (whatever its words), a garbled answer, a 403: an unknown outcome looked up by the client id:
    never "refused", never a clock refusal sent again, never a 429."""
    c, fake, clock = make()
    ready(c, (DOGE,))
    fake.prices[DOGE] = 1.0
    fake.fail("POST", ORDER, kind)
    with pytest.raises(TransientError) as e:
        c.market(DOGE, "BUY", 100.0, client_id="pbE1")
    assert e.value.code != BAD_TIMESTAMP and not isinstance(e.value, RateLimited) and c.rate_answers == 0
    assert fake.amt(DOGE) == 100 and "pbE1" in c.sent         # it ran: its record is kept, looked up by its id
    assert c.order(DOGE, client_id="pbE1")["status"] == "FILLED"
    assert c.market(DOGE, "BUY", 100.0, client_id="pbE1")["status"] == "FILLED" and len(orders(fake)) == 1
    g = Guarded(c, lambda s: None, retries=4)                  # the executor's wrapper: found, never sent again
    fake.fail("POST", ORDER, kind)
    assert g.market(DOGE, "BUY", 100.0, client_id="pbE2")["status"] == "FILLED"
    assert fake.amt(DOGE) == 200 and len(orders(fake)) == 2


def test_only_a_documented_refusal_refuses_an_order():
    c, fake, clock = make()
    ready(c)
    fake.fail("POST", ORDER, ("err", 400, -1021, "Timestamp for this request is outside of the recvWindow."))
    with pytest.raises(TestnetError) as e:                     # documented: refused before anything ran
        c.market(BTC, "BUY", 1.0, client_id="pbT")
    assert e.value.code == BAD_TIMESTAMP and "pbT" not in c.sent and fake.amt(BTC) == 0
    fake.fail("POST", ORDER, ("err", 400, -1021, "Timestamp for this request is outside of the recvWindow."))
    assert Guarded(c, lambda s: None).market(BTC, "BUY", 1.0, client_id="pbT")["status"] == "FILLED"
    assert fake.amt(BTC) == 1                                  # re-synced and sent again: filled once
    sent = len(orders(fake))
    for i, kind in enumerate((("err", 400, -9999, "Order expired"), ("err", 400, -1006, "status unknown"), "403",
                              ("err", 400, None, "x"))):
        fake.fail("POST", ORDER, kind)                         # it did not run, but nothing says so: unknown
        with pytest.raises(TransientError) as e:
            c.market(BTC, "BUY", 1.0, client_id=f"pbU{i}")
        assert e.value.code != BAD_TIMESTAMP and not isinstance(e.value, RateLimited)
    clock.t += TB.SETTLE_MS
    for i in range(4):
        with pytest.raises(TestnetError) as e:
            c.order(BTC, client_id=f"pbU{i}")
        assert e.value.code == NOT_FOUND[0]
        with pytest.raises(TransientError):                   # an opening id: never sent again
            c.market(BTC, "BUY", 1.0, client_id=f"pbU{i}")
    assert len(orders(fake)) == sent and fake.amt(BTC) == 1 and c.rate_answers == 0


@pytest.mark.parametrize("kind", [("err_after", 400, -1007, "Timeout waiting for response"), "403_after"])
def test_a_stop_that_ran_but_was_answered_otherwise_is_found_and_never_doubled(kind):
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    fake.fail("POST", ORDER, kind)
    with pytest.raises(TransientError):
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS")
    assert "pbS" in c.stop_intents and c.algo_order(client_id="pbS")["algoStatus"] == "NEW"
    fake.fail("POST", ORDER, kind)
    st = place_stop(Guarded(c, ticking(clock)), BTC, "SELL", 96.0, 5.0, client_id="pbS2")
    assert st["algoStatus"] == "NEW" and len(fake.live_stops(BTC)) == 2 and len(stops_sent(fake)) == 2


def test_a_failure_before_an_opening_order_is_sent_says_nothing_was_sent():
    """The look-up of a new client id or the contract read failing sent nothing. Tried again for a few seconds; still
    failing: NotSent, a refusal (never the unknown outcome of a send, never a RateLimited the executor would resend)."""
    c, fake, clock = make(advance=True)
    ready(c)
    fake.fail("GET", ORDER, "503_before")                      # once: tried again, then sent once
    o = c.market(BTC, "BUY", 1.0, client_id="pbN")
    assert o["status"] == "FILLED" and len(orders(fake)) == 1 and fake.amt(BTC) == 1
    fake.fail("GET", ORDER, "503_before", times=99)            # on every try: refused, nothing sent
    t0 = clock.t
    with pytest.raises(TB.NotSent) as e:
        c.market(BTC, "BUY", 1.0, client_id="pbN1")
    assert not isinstance(e.value, (TransientError, RateLimited)) and e.value.code == TB.NOT_SENT
    assert "pbN1" not in c.sent and len(orders(fake)) == 1 and clock.t - t0 >= 3_000
    fake.fails.clear()
    c.specs.clear()
    c.spec_ms = None
    fake.fail("GET", "/api/v1/exchangeInfo", "503_before", times=99)
    with pytest.raises(TB.NotSent):
        c.market(BTC, "BUY", 1.0, client_id="pbN2")
    fake.fails.clear()
    fake.fail("POST", ORDER, "drop_after")                     # an id this process sent: its look-up failing is unknown
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 1.0, client_id="pbM")
    fake.fail("GET", ORDER, "503_before")
    with pytest.raises(TransientError) as e:
        c.market(BTC, "BUY", 1.0, client_id="pbM")
    assert not isinstance(e.value, TB.NotSent) and len(orders(fake)) == 2


def test_a_read_refused_for_the_rate_is_read_again_and_the_client_paces_itself():
    c, fake, clock = make()
    pauses = []

    def pause(s):
        pauses.append(s)
        clock.t += int(s * 1000)
    c.sleep = pause
    fake.fail("GET", "/api/v1/futures/balance", ("429", 2))
    assert c.account()["totalWalletBalance"] == "10000" and pauses == [2.0] and c.rate_answers == 1
    fake.fail("GET", "/api/v1/futures/balance", ("429", 600))
    pauses.clear()
    with pytest.raises(RateLimited) as e:                      # past RETRY_AFTER_MAX_S: not waited here
        c.account()
    assert e.value.retry_after == 600 and pauses == []
    pauses.clear()
    c.hits["weight"] = [(clock.t, 5)] * 479                    # 2395 of the 2400 a minute (80 % of 3000)
    c.positions()                                              # weight 5: fits
    assert pauses == []
    c.positions()                                              # the next one waits for the window
    assert pauses and pauses[0] <= 60
    assert c.throttle_s() >= 0


def test_the_pace_comes_before_the_timestamp_and_the_signature():
    """A full minute's budget is waited out BEFORE ``timestamp`` is made (else -1021: recvWindow is 5 s)."""
    c, fake, clock = make()
    pauses = []

    def pause(s):
        pauses.append(s)
        clock.t += int(s * 1000)
    c.sleep = pause
    c.hits["weight"] = [(clock.t, 5)] * 480                    # the minute's budget used up just now
    assert c.account()["totalWalletBalance"] == "10000"       # no -1021
    assert sum(pauses) >= 59


def test_protective_work_never_waits_for_the_self_imposed_budget():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbE")
    c.hits["weight"] = [(clock.t, 5)] * 480
    c.hits["orders"] = [(clock.t, 1)] * 48
    t0 = clock.t
    st = place_stop(c, BTC, "SELL", 95.0, 1.0, client_id="pbS")
    assert st["algoStatus"] == "NEW" and clock.t - t0 < 1_000


def test_rate_limits_from_exchange_info():
    c, fake, clock = make()
    assert c.limits_source == "docs example"
    c.spec(BTC)
    assert c.limits_source == "exchangeInfo" and c.limits["weight"] == ((60_000, 3000),)
    assert c.limits["orders"] == ((60_000, 60),)
    c._read_limits([{"rateLimitType": "REQUEST_WEIGHT", "interval": "SECOND", "intervalUnit": 10, "limit": 500},
                    {"rateLimitType": "ORDERS", "interval": "DAY", "intervalUnit": 1, "limit": 100000},
                    {"rateLimitType": "ORDERS", "interval": "MINUTE", "intervalUnit": "x", "limit": 1}, "junk"])
    assert c.limits["weight"] == ((10_000, 500),) and c.limits["orders"] == ((86_400_000, 100000),)
    assert [b[0] for b in c._buckets("order")] == ["weight", "orders"] and len(c._buckets("query")) == 1


# ------------------------------------------------------------------ specs, prices, account
def test_contract_units_from_exchange_info():
    c, fake, clock = make()
    sp = c.spec(BTC)
    assert (sp["qty_step"], sp["min_qty"], sp["tick"], sp["max_leverage"], sp["status"], sp["lot_unit"]) == (
        0.001, 0.001, 0.1, 125.0, "Trading", "contracts")
    eth = c.spec(ETH)                                          # LOT_SIZE in base units: 0.01 ETH = 1 contract
    assert (eth["lot_unit"], eth["lot_sz"], eth["min_sz"], eth["max_sz"], eth["qty_step"]) == ("base", "1", "1",
                                                                                               "100000", 0.01)
    assert str(c._contracts(ETH, 0.057)) == "5"
    doge = c.spec(DOGE)                                        # 1 contract = 10 DOGE
    assert (doge["qty_step"], doge["min_qty"], doge["min_notional"]) == (10.0, 10.0, 5.0)
    assert str(c._contracts(DOGE, 125.0)) == "12" and c._base(DOGE, "12") == 120
    with pytest.raises(TestnetError) as e:
        c.spec("XRPUSDT")
    assert e.value.code == "NO_SYMBOL"
    assert "BTCUSDT" in c.specs and not any(k.endswith("SWAP") for k in c.specs)   # the inverse contract left out
    from decimal import Decimal
    assert TB.lot_unit(Decimal("5"), Decimal("0.1")) == ("contracts", Decimal("5"))
    with pytest.raises(TestnetError) as e:
        TB.lot_unit(Decimal("0.015"), Decimal("0.01"))
    assert e.value.code == "BAD_SPEC"


def test_live_specs_10_26_step_finer_than_a_contract(monkeypatch):
    """Toobit's live exchangeInfo (the owners' `check`, 10-26): BTC, ETH and SOL give a LOT_SIZE step in coins that is a
    fraction of one contract (BTC 0.0001 with 0.001 BTC a contract, ETH 0.001 / 0.01, SOL 0.01 / 1). They were refused
    as BAD_SPEC; now orders go in whole contracts (each a whole number of steps), the smallest order rounded up to one
    contract and the largest down. DOGE, LTC and BCH read as they did."""
    from decimal import Decimal
    live = {"BTCUSDT": ("0.001", "0.0001", "0.0001", "1000"), "ETHUSDT": ("0.01", "0.001", "0.001", "10000"),
            "SOLUSDT": ("1", "0.01", "0.01", "100000"), "DOGEUSDT": ("1", "1", "63", "30000000"),
            "LTCUSDT": ("0.001", "0.001", "0.068", "10207"), "BCHUSDT": ("0.001", "0.001", "0.01", "3400")}
    for s, (ct, step, mn, mx) in live.items():
        monkeypatch.setitem(SPECS, s, {**SPECS[s], "ct": ct, "step": step, "min": mn, "max": mx, "notional": "0"})
    c, fake, clock = make()
    got = {s: (c.spec(s)["lot_unit"], c.spec(s)["lot_sz"], c.spec(s)["min_sz"], c.spec(s)["max_sz"],
               c.spec(s)["qty_step"], c.spec(s)["min_qty"]) for s in live}
    assert got == {"BTCUSDT": ("base_fine", "1", "1", "1000000", 0.001, 0.001),
                   "ETHUSDT": ("base_fine", "1", "1", "1000000", 0.01, 0.01),
                   "SOLUSDT": ("base_fine", "1", "1", "100000", 1.0, 1.0),
                   "DOGEUSDT": ("contracts", "1", "63", "30000000", 1.0, 63.0),
                   "LTCUSDT": ("base", "1", "68", "10207000", 0.001, 0.068),
                   "BCHUSDT": ("base", "1", "10", "3400000", 0.001, 0.01)}
    # a base quantity becomes whole contracts, floored; never a part of a contract
    assert str(c._contracts("BTCUSDT", 0.0096)) == "9" and str(c._contracts("SOLUSDT", 4.97)) == "4"
    assert str(c._contracts("ETHUSDT", 0.2299)) == "22"
    assert TB.lot_unit(Decimal("0.0001"), Decimal("0.001")) == ("base_fine", Decimal(1))
    with pytest.raises(TestnetError) as e:                     # a step that does not divide a contract stays refused
        TB.lot_unit(Decimal("0.0003"), Decimal("0.001"))
    assert e.value.code == "BAD_SPEC"
    text = TB.specs_text(c)
    assert "BTCUSDT: 상태 Trading, 1계약 0.001" in text and "코인 단위로 읽음, 1계약보다 잘아서 1계약씩 주문]" in text
    assert "상품 정보를 쓸 수 없습니다" not in text
    # the drill still picks a coin whose contract is not 1 coin and costs at most DRILL_UNIT_MAX_USDT
    for s, px in (("BTCUSDT", 83000.0), ("ETHUSDT", 2700.0), ("SOLUSDT", 190.0), ("DOGEUSDT", 0.077),
                  ("LTCUSDT", 56.8), ("BCHUSDT", 280.0)):
        fake.set_price(s, px)
    d = TB.ToobitDrill(c)
    assert d.smallest() == "BCHUSDT"


def test_prices_klines_and_server_time():
    c, fake, clock = make()
    fake.set_price(BTC, 101.0, mark=100.5)
    assert c.price(BTC) == 101.0 and c.mark(BTC) == 100.5
    fake.ticker_name = "plain"                                 # the plain name is the same coin
    assert c.price(BTC) == 101.0
    edit_route(fake, "/quote/v1/contract/ticker/price", lambda d: [{"s": "ETH-SWAP-USDT", "p": "7"}])
    with pytest.raises(TransientError):                        # another coin's row is never this coin's price
        c.price(BTC)
    reset_route(fake)
    t0 = clock.t
    for i in range(1, 2501):                                   # 2500 minutes: three pages of 1000 rows
        clock.t = t0 + i * 60_000
        fake.set_price(BTC, 100.0 + i % 7)
    rows = c.klines(BTC, t0 + 60_000, clock.t)
    assert len(rows) == 2500 and rows[0][0] == t0 + 60_000 and rows[-1][0] == clock.t
    assert [r[0] for r in rows] == sorted({r[0] for r in rows})
    assert len(calls(fake, "GET", "/quote/v1/klines")) == 3
    clock.t += 1234
    assert c.sync_time() == 0
    fake.clock = lambda: clock.t + 700
    assert c.sync_time() == 700


def test_account_equity_and_garbled_answers_are_errors():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    fake.set_price(BTC, 102.0)
    a = c.account()                                            # the isolated position's own unrealizedPnL
    assert a["totalUnrealizedProfit"] == "10" and float(a["totalMarginBalance"]) == pytest.approx(
        float(a["totalWalletBalance"]) + 10)
    assert a["assets"] == [{"asset": "USDT", "walletBalance": a["totalWalletBalance"]}]
    for broken in ([], [{"asset": "USDT", "balance": "", "availableBalance": "1"}],
                   [{"asset": "USDT", "balance": "1"}], None, {"x": 1}):
        edit_route(fake, "/api/v1/futures/balance", lambda d, b=broken: b)
        with pytest.raises(TransientError):                   # never $0 from a gap
            c.account()
        reset_route(fake)
    edit_route(fake, "/api/v1/futures/positions", lambda d: [{**r, "unrealizedPnL": ""} for r in d])
    with pytest.raises(TransientError):
        c.account()
    reset_route(fake)
    edit_route(fake, "/api/v1/futures/balance", lambda d: d + [{"asset": "BNB", "balance": "0.5"}])
    assert {"asset": "BNB", "walletBalance": "0.5"} in c.account()["assets"]
    reset_route(fake)
    assert c.fee_rate(BTC)["open_taker"] == 0.0006 and c.fee_rate(BTC)["close_taker"] == 0.0006


def test_one_way_isolated_leverage_and_the_read_back():
    c, fake, clock = make()
    with pytest.raises(TestnetError) as e:                     # not checked yet: no entry
        c.leverage(BTC, 20)
    assert e.value.code == "NOT_ONE_WAY"
    assert fake.levs[BTC] == {"leverage": 20, "marginType": "CROSS"}
    ready(c, (BTC, DOGE))
    assert fake.levs[BTC] == {"leverage": 40, "marginType": "ISOLATED"} and fake.levs[DOGE]["leverage"] == 30
    assert c.leverage(BTC, 20) == {"symbol": BTC, "leverage": 20, "marginType": "isolated"}
    assert fake.levs[BTC]["leverage"] == 20
    sent = len(calls(fake, "POST", "/api/v1/futures/leverage"))
    c.leverage(BTC, 20)                                        # already so: nothing sent
    assert len(calls(fake, "POST", "/api/v1/futures/leverage")) == sent
    with pytest.raises(TestnetError) as e:
        c.leverage(DOGE, 60)
    assert e.value.code == "LEVERAGE_MAX"
    c.market(BTC, "BUY", 1.0, client_id="pbE")
    with pytest.raises(TestnetError) as e:
        c.leverage(BTC, 10)
    assert e.value.code == "POSITION_OPEN"
    edit_route(fake, "/api/v1/futures/accountLeverage", lambda d: [{**r, "leverage": "3"} for r in d])
    with pytest.raises(TransientError) as e:                   # read again after pauses: never a refusal
        c.leverage(DOGE, 10)
    assert e.value.code == TB.MISMATCH
    reset_route(fake)
    lines = c.account_setup([BTC, ETH])
    assert all(ok for ok, _ in lines) and "한 코인에 한쪽만" in lines[0][1] and "ISOLATED 20배" in lines[1][1]


def test_a_lagging_leverage_read_back_is_read_again():
    c, fake, clock = make(advance=True)
    fake.lev_lag_ms = 1_500
    ready(c, (BTC, DOGE))
    assert c.lev == {BTC: 40, DOGE: 30} and not c.lev_problems and fake.levs[DOGE]["leverage"] == 30
    assert c.leverage(DOGE, 20)["leverage"] == 20
    fake.lev_lag_ms = 60_000
    with pytest.raises(TransientError) as e:                   # still another value: unknown (tried again), not refused
        c.leverage(DOGE, 25)
    assert e.value.code == TB.MISMATCH


@pytest.mark.parametrize("answer", [("err", 400, -1130, "Data sent for paramter 'leverage' is not valid."),
                                    ("err", 400, -9999, "System busy"), "503_before"])
def test_a_coin_whose_leverage_cannot_be_set_never_stops_the_start(answer):
    """isolated() at the start notes a coin it cannot set and returns: the executor starts and protects; leverage()
    sets it before an entry and refuses only that entry when it cannot. The key itself refused: Refused."""
    c, fake, clock = make()
    c.sync_time()
    c.one_way()
    fake.fail("POST", "/api/v1/futures/marginType", answer, times=4)
    assert c.isolated(ETH) is None and ETH in c.lev_problems and ETH not in c.lev
    fake.fails.clear()
    c.isolated(BTC)
    assert BTC not in c.lev_problems and c.lev[BTC] == 40
    line = c.account_setup([ETH])[1]
    assert not line[0] and "진입 직전에 다시 맞추고" in line[1]
    fake.fail("POST", "/api/v1/futures/marginType", answer, times=4)
    with pytest.raises(TestnetError):                         # that entry only
        c.leverage(ETH, 20)
    fake.fails.clear()
    assert c.leverage(ETH, 20)["leverage"] == 20 and ETH not in c.lev_problems
    fake.fail("POST", "/api/v1/futures/marginType", ("err", 400, -1022, "Signature for this request is not valid."))
    with pytest.raises(Refused):
        c.isolated(DOGE)


def test_a_margin_type_that_cannot_change_while_an_order_rests_is_refused_and_noted():
    c, fake, clock = make()
    ready(c)
    fake._record({"symbol": "ETH-SWAP-USDT", "side": "BUY_OPEN", "quantity": "1", "newClientOrderId": "byHand",
                  "priceType": "INPUT"}, "LIMIT")              # a resting order placed in the app (cross)
    assert c.isolated(ETH) is None and "-3128" in c.lev_problems[ETH]


def test_a_coin_not_trading_is_read_again_before_an_entry():
    c, fake, clock = make()
    fake.states.update({DOGE: "HALT", ETH: "BREAK"})
    ready(c, (DOGE, ETH))
    assert c.spec(DOGE)["status"] == "HALT" and not c.spec(DOGE)["tradable"]
    fake.states[DOGE] = "TRADING"
    clock.t += 60_000
    assert c.leverage(DOGE, 30)["leverage"] == 30
    with pytest.raises(TestnetError) as e:
        c.leverage(ETH, 30)
    assert e.value.code == "NOT_TRADING" and "BREAK" in e.value.msg


def test_a_coin_holding_a_long_and_a_short_at_once_is_an_error_never_netted():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 2.0, client_id="pbL")
    other = TB.ToobitClient("tk", "ts", send=fake, clock_ms=clock, sleep=lambda s: None)
    other.one_side = True
    other.market(BTC, "SELL", 1.0, client_id="pbS")            # a short opened next to the long (by hand)
    with pytest.raises(TransientError, match="롱·숏"):
        c.position(BTC)
    with pytest.raises(TransientError):
        c.positions()
    c2, _, _ = make(fake=fake, clock=clock)
    with pytest.raises(Refused, match="롱·숏"):
        c2.one_way()
    assert not c2.one_side and not c2.account_setup([BTC])[0][0]


def test_position_shapes_and_garbled_rows_are_errors():
    c, fake, clock = make()
    ready(c, (BTC, ETH))
    assert c.position(BTC)["positionAmt"] == "0" and c.positions() == []
    c.market(ETH, "SELL", 0.37, client_id="pbE")               # 37 contracts of 0.01 ETH
    p = c.position(ETH)
    assert (p["positionAmt"], p["marginType"], p["leverage"], p["positionSide"], p["available"]) == (
        "-0.37", "isolated", "30", "SHORT", "0.37")
    assert [x["symbol"] for x in c.positions()] == [ETH]
    edit_route(fake, "/api/v1/futures/positions", lambda d: [{**r, "position": "-37"} for r in d])
    assert c.position(ETH)["positionAmt"] == "-0.37"           # a short written negative: still the short
    reset_route(fake)
    for bad in ({"position": ""}, {"side": "LONG", "position": "-3"}, {"side": "BOTH"}, {"position": "abc"}):
        edit_route(fake, "/api/v1/futures/positions", lambda d, b=bad: [{**r, **b} for r in d])
        with pytest.raises(TransientError):                   # never "flat" from a garbled row
            c.position(ETH)
        reset_route(fake)
    edit_route(fake, "/api/v1/futures/positions", lambda d: None)
    with pytest.raises(TransientError):
        c.positions()
    reset_route(fake)
    with pytest.raises(TestnetError) as e:
        c.leverage_brackets()
    assert e.value.code == "NO_BRACKETS"


# ------------------------------------------------------------------ orders
def test_market_entry_and_close_bodies_and_read_back():
    c, fake, clock = make()
    ready(c, (BTC, ETH, DOGE))
    o = c.market(BTC, "BUY", 5.0004, client_id="pbAbcE")      # floored to whole contracts
    assert orders(fake)[-1] == {"symbol": "BTC-SWAP-USDT", "side": "BUY_OPEN", "type": "LIMIT", "priceType": "MARKET",
                                "quantity": "5000", "newClientOrderId": "pbAbcE"}
    assert (o["status"], o["executedQty"], o["avgPrice"], o["reduceOnly"], o["type"]) == ("FILLED", "5", "100", False,
                                                                                         "MARKET")
    x = c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbAbcX")
    assert (orders(fake)[-1]["side"], orders(fake)[-1]["quantity"]) == ("SELL_CLOSE", "5000")
    assert x["status"] == "FILLED" and x["reduceOnly"] is True and fake.amt(BTC) == 0
    s = c.market(ETH, "SELL", 0.05, client_id="pbEthS")       # a short: SELL_OPEN, 5 contracts of 0.01 ETH
    assert (orders(fake)[-1]["side"], orders(fake)[-1]["quantity"]) == ("SELL_OPEN", "5") and s["executedQty"] == "0.05"
    c.market(ETH, "BUY", 0.05, reduce_only=True, client_id="pbEthX")
    assert orders(fake)[-1]["side"] == "BUY_CLOSE" and fake.amt(ETH) == 0
    for sym, qty, code in ((BTC, 0.0004, "QTY_ZERO"), (ETH, 0.005, "QTY_ZERO"), (DOGE, 5.0, "QTY_ZERO")):
        with pytest.raises(TestnetError) as e:
            c.market(sym, "BUY", qty, client_id="pbTiny")
        assert e.value.code == code
    fake.prices[DOGE] = 0.2                                    # 1 contract = 10 DOGE = $2: below $5
    with pytest.raises(TestnetError) as e:                     # the exchange's own minimum value: refused
        c.market(DOGE, "BUY", 20.0, client_id="pbDoge")
    assert e.value.code == -1140 and not isinstance(e.value, TransientError)
    with pytest.raises(TestnetError):
        c.market(BTC, "HOLD", 1.0)


def test_a_market_remainder_that_rests_is_cancelled():
    """A market order is matched only within 5 % of the last price: a remainder still resting after the read-back is
    cancelled, so nothing of an entry waits on the book."""
    c, fake, clock = make()
    ready(c)
    fake.partial, fake.rest = 0.4, True
    o = c.market(BTC, "BUY", 5.0, client_id="pbP")
    assert (o["status"], o["executedQty"], o.get("restCancelled")) == ("CANCELED", "2", True) and fake.amt(BTC) == 2
    assert c.open_orders(BTC) == [] and len(calls(fake, "DELETE", ORDER)) == 1
    assert c.order(BTC, client_id="pbP")["executedQty"] == "2"
    st = place_stop(c, BTC, "SELL", 95.0, 2.0, client_id="pbS")
    assert covers(st, 2.0)


def test_a_partly_filled_market_order_reads_its_filled_part():
    c, fake, clock = make()
    ready(c)
    fake.partial = 0.4
    o = c.market(BTC, "BUY", 5.0, client_id="pbP")
    assert (o["status"], o["executedQty"], o["tbStatus"]) == ("CANCELED", "2", "CANCELED") and fake.amt(BTC) == 2
    assert not o.get("restCancelled") and not calls(fake, "DELETE", ORDER)


def test_an_accepted_order_whose_record_lags_is_never_reported_as_not_executed():
    c, fake, clock = make()
    ready(c)
    fake.order_lag_ms = 60_000
    o = c.market(BTC, "BUY", 5.0, client_id="pbLag")
    assert o["orderId"] and o["status"] == "NEW" and "readBack" in o and fake.amt(BTC) == 5
    assert not calls(fake, "DELETE", ORDER)                    # an unread record is never "resting": nothing cancelled
    with pytest.raises(TransientError):                       # sent by this process: unknown, never "not found" yet
        c.order(BTC, client_id="pbLag")
    clock.t += 60_000
    assert c.order(BTC, order_id=o["orderId"])["status"] == "FILLED"


def test_open_orders_cancel_all_and_reconcile():
    c, fake, clock = make()
    ready(c)
    o = fake._record({"symbol": "BTC-SWAP-USDT", "side": "BUY_OPEN", "quantity": "3", "newClientOrderId": "byHand",
                      "priceType": "INPUT"}, "LIMIT")          # a resting order placed in the app
    got = c.open_orders(BTC)
    assert [(x["orderId"], x["status"], x["origQty"], x["clientOrderId"]) for x in got] == [(o["orderId"], "NEW",
                                                                                            "0.003", "byHand")]
    c.cancel_all(BTC)
    assert fake.orders[o["orderId"]]["status"] == "CANCELED" and c.open_orders(BTC) == []
    with pytest.raises(TestnetError) as e:                     # already ended: answered with its record
        c.cancel(BTC, o["orderId"])
    assert e.value.code in NOT_FOUND
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    rep = TB.reconcile(c, BTC)
    assert rep["problem"] == "position without a protective stop" and not rep["repaired"]
    rep = TB.reconcile(c, BTC, stop_price=95.0)
    assert rep["repaired"] and len(live_stops(c, BTC)) == 1 and TB.reconcile(c, BTC)["problem"] is None


def test_client_ids_map_to_a_deterministic_newclientorderid():
    for cid in ("pbe1a2b3c4d5e6fe", "pbAbc", "x" * 32):
        assert TB.ext_id(cid) == cid
    long_id = "pb0123456789abs3r9f8e7d6c5b4a3f2e1d0"           # longer than 32 characters
    m = TB.ext_id(long_id)
    assert m == TB.ext_id(long_id) and len(m) == 32 and m.isalnum() and m.startswith("pbh") and m != TB.ext_id(
        long_id + "x")
    assert TB.ext_id("pb.x-y_z") != "pb.x-y_z" and TB.ext_id("pb.x-y_z").isalnum()
    fresh = TB.ext_id(None)
    assert len(fresh) == 32 and fresh.isalnum() and fresh != TB.ext_id(None)


UNKNOWN_IDS = pytest.mark.parametrize("unknown_ids", ["error", "empty"])   # an id nobody has: -2013 or {}


@UNKNOWN_IDS
def test_a_lost_answer_is_found_by_its_client_id_also_after_a_restart(unknown_ids):
    c, fake, clock = make()
    fake.unknown_ids = unknown_ids
    ready(c)
    long_id = "pbxr5f4d3c2b1a0fe9d8c7b6a5f4e3d2c1"
    fake.fail("POST", ORDER, "drop_after")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 5.0, client_id=long_id)
    assert fake.amt(BTC) == 5
    got = c.order(BTC, client_id=long_id)                      # GET order by its origClientOrderId
    assert got["status"] == "FILLED" and got["clientOrderId"] == TB.ext_id(long_id)
    c2, _, _ = make(fake=fake, clock=clock)                    # a new process: no record at all
    ready(c2)
    assert c2.order(BTC, client_id=long_id)["orderId"] == got["orderId"]
    o = c2.market(BTC, "BUY", 5.0, client_id=long_id)          # the same opening id: looked up, never sent again
    assert o["orderId"] == got["orderId"] and len(orders(fake)) == 1 and fake.amt(BTC) == 5
    c2.forget_order(TB.ext_id(long_id))
    fake.query_cid = False                                     # GET order by client id finds nothing: the lists do
    assert c2.order(BTC, client_id=long_id)["orderId"] == got["orderId"]


@UNKNOWN_IDS
def test_an_order_that_never_arrived_is_not_found_only_after_the_settle_window(unknown_ids):
    c, fake, clock = make()
    fake.unknown_ids = unknown_ids
    ready(c)
    fake.fail("POST", ORDER, "drop_before")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 5.0, client_id="pbNever")
    with pytest.raises(TransientError):
        c.order(BTC, client_id="pbNever")
    with pytest.raises(TransientError):                       # an opening id: never sent twice, not even now
        c.market(BTC, "BUY", 5.0, client_id="pbNever")
    clock.t += TB.SETTLE_MS
    with pytest.raises(TestnetError) as e:
        c.order(BTC, client_id="pbNever")
    assert e.value.code == NOT_FOUND[0] and not isinstance(e.value, TransientError)
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 5.0, client_id="pbNever")
    assert len(orders(fake)) == 0 and fake.amt(BTC) == 0


def test_a_close_is_sent_again_only_once_its_absence_is_settled_and_sized_from_the_position():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    fake.fail("POST", ORDER, "drop_before")
    with pytest.raises(TransientError):
        c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    with pytest.raises(TransientError):                       # inside the window: looked up, never re-sent
        c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    fake.set_price(BTC, 99.0)
    c.market(BTC, "SELL", 2.0, reduce_only=True, client_id="pbCut")         # meanwhile part was closed
    clock.t += TB.SETTLE_MS
    x = c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    assert x["executedQty"] == "3" and orders(fake)[-1]["quantity"] == "3000" and fake.amt(BTC) == 0


def test_close_words_read_the_other_way_are_refused_never_a_flip():
    """The docs and ccxt agree (SELL_CLOSE closes a long); were the exchange to read them the other way, a CLOSE side
    never opens a position, so a wrong reading is a refusal with the position unchanged (the drill's half close shows it)."""
    c, fake, clock = make()
    fake.close_words = "swapped"
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    with pytest.raises(TestnetError) as e:
        c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    assert e.value.code == -2010 and fake.amt(BTC) == 5 and not [k for k in fake.pos if k[1] == "SHORT"]


# ------------------------------------------------------------------ stops: STOP orders
@pytest.mark.parametrize("cancel_answer", ["before", "after"])
def test_stop_body_place_confirm_move_cancel(cancel_answer):
    c, fake, clock = make()
    fake.cancel_answer = cancel_answer
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS1")
    assert stops_sent(fake)[-1] == {"symbol": "BTC-SWAP-USDT", "side": "SELL_CLOSE", "type": "STOP",
                                    "priceType": "MARKET", "stopPrice": "95", "quantity": "5000",
                                    "newClientOrderId": "pbS1"}
    assert (st["algoStatus"], st["triggerPrice"], st["quantity"], st["tbStatus"]) == ("NEW", "95", "5", "ORDER_NEW")
    stops = live_stops(c, BTC)
    assert len(stops) == 1 and covers(stops[0], 5.0) and stops[0]["reduceOnly"] is True
    assert c.list_delay_ms[st["algoId"]] == 0 and c.level_field[st["algoId"]] == "stopPrice"
    mv = move_stop(c, BTC, "SELL", 97.0, 5.0, [st["algoId"]], client_id="pbS2")
    assert mv["result"] == "moved" and mv["cancelled"] == [st["algoId"]]
    assert [x["triggerPrice"] for x in live_stops(c, BTC)] == ["97"]
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == "CANCELED"
    assert c.algo_order(client_id="pbS2")["algoId"] == mv["stop"]["algoId"]
    assert not fake.unprotected()
    if cancel_answer == "before":
        c.cancel_algo(algo_id=mv["stop"]["algoId"])
    else:                                                      # an answer with the ended status: NOT_FOUND, still gone
        with pytest.raises(TestnetError) as e:
            c.cancel_algo(algo_id=mv["stop"]["algoId"])
        assert e.value.code in NOT_FOUND
    with pytest.raises(TestnetError) as e:                     # cancelled: a second cancel is "not found"
        c.cancel_algo(algo_id=mv["stop"]["algoId"])
    assert e.value.code in NOT_FOUND
    assert c.open_algo_orders(BTC) == [] and fake.amt(BTC) == 5
    short = make()[0]
    ready(short, (ETH,))
    short.market(ETH, "SELL", 0.5, client_id="pbSh")
    place_stop(short, ETH, "BUY", 105.0, 0.5, client_id="pbShS")
    b = short.send.stop_bodies[-1]
    assert (b["side"], b["quantity"]) == ("BUY_CLOSE", "50")


def test_a_stop_past_the_price_is_refused_before_it_is_sent_or_reads_as_would_trigger():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    with pytest.raises(TestnetError) as e:
        c.stop_close(BTC, "SELL", 101.0, 5.0, client_id="pbS")
    assert e.value.code == WOULD_TRIGGER and not stops_sent(fake)
    real = fake._stop

    def moved(q, s, closing):                                  # the price moves between the check and the send
        fake.prices[BTC] = 94.0
        return real(q, s, closing)
    fake._stop, fake.past_stop = moved, "refuse"
    with pytest.raises(TestnetError) as e:
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS2")
    assert e.value.code == WOULD_TRIGGER
    fake._stop = real
    fake.prices[BTC] = 100.0
    mv = move_stop(c, BTC, "SELL", 101.0, 5.0, [], client_id="pbS3", close_id="pbX")
    assert mv["result"] == "closed" and fake.amt(BTC) == 0


@pytest.mark.parametrize("own_fills, family, level", [(True, "plan", "stopPrice"), (False, "plan", "triggerPrice"),
                                                      (True, "regular", "triggerPrice"),
                                                      (False, "regular", "stopPrice")])
def test_a_fired_stop_reads_as_triggered_with_the_order_it_placed(own_fills, family, level):
    c, fake, clock = make()
    fake.own_fills, fake.stop_family, fake.level_field = own_fills, family, level
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    assert st["triggerPrice"] == "95" and c.level_field[st["algoId"]] == level
    clock.t += 5_000
    fake.set_price(BTC, 94.0)
    assert fake.amt(BTC) == 0
    got = c.algo_order(algo_id=st["algoId"])
    assert got["algoStatus"] == "TRIGGERED" and got["actualOrderId"]
    assert (got["actualOrderId"] == st["algoId"]) == own_fills
    fills = [r for r in c._trades(BTC, T0, clock.t) if str(r["orderId"]) == got["actualOrderId"]]
    assert len(fills) == 1 and fills[0]["side"] == "SELL_CLOSE"


def test_a_fired_stops_order_is_told_from_our_own_close():
    """Our own close made just before the stop fired (the same side) is never taken for the stop's order: the orders
    this process placed are left out by orderId, the executor's by their "pb" client id."""
    c, fake, clock = make()
    fake.lists_hide_cid = True
    ready(c)
    c.market(BTC, "BUY", 10.0, client_id="pbE")
    close = c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")      # ours: SELL_CLOSE, like the stop
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    fake.set_price(BTC, 94.0)
    child = next(o["orderId"] for o in fake.orders.values() if o["type"] == "LIMIT" and not o["clientOrderId"])
    assert close["orderId"] in c.own_oids and child not in c.own_oids
    real = fake._route

    def broken(m, p, q):                                       # the fills cannot be read: the history still names it
        if (m, p) == ("GET", "/api/v1/futures/userTrades"):
            return 503, b"busy", {}
        return real(m, p, q)
    fake._route = broken
    got = c.algo_order(algo_id=st["algoId"])
    assert (got["algoStatus"], got["actualOrderId"]) == ("TRIGGERED", child)


@pytest.mark.parametrize("hidden, takes_cid", [(True, False), (False, True), (True, True)])
def test_a_fired_stops_order_found_by_its_fills_live_drill_10_26(hidden, takes_cid):
    """The owners' first live drill (10-26, BCH long and BTC short): the stop fired and closed the position, its fills
    were in userTrades under a new orderId, but the order-history look-up found no order: the order a fired stop places
    is now found by its fills (side, time, not one of ours), and also when it carries the stop's own client id."""
    c, fake, clock = make()
    fake.child_hidden, fake.child_takes_stop_cid = hidden, takes_cid
    ready(c)
    c.market(BTC, "BUY", 10.0, client_id="pbE")
    close = c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")      # ours, the same side, just before
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    clock.t += 3_000
    fake.set_price(BTC, 94.0)
    assert fake.amt(BTC) == 0
    child = next(str(f["orderId"]) for f in fake.fills if str(f["orderId"]) not in (str(close["orderId"]),) and
                 f["side"] == "SELL_CLOSE" and str(f["orderId"]) != str(st["algoId"]) and int(f["time"]) >= clock.t)
    got = c.algo_order(algo_id=st["algoId"])
    assert (got["algoStatus"], got["actualOrderId"]) == ("TRIGGERED", child)
    if takes_cid and not hidden:                       # the history row alone (fills unreadable) still names it
        real = fake._route

        def broken(m, p, q):
            if (m, p) == ("GET", "/api/v1/futures/userTrades"):
                return 503, b"busy", {}
            return real(m, p, q)
        fake._route = broken
        assert c.algo_order(algo_id=st["algoId"])["actualOrderId"] == child


def test_a_stop_looked_up_after_a_restart():
    """A stop id this process has not seen: its own record names its coin; without a record every coin's stop list is
    read, and one coin that cannot be read makes the answer unknown, never "not found"."""
    c, fake, clock = make()
    ready(c, (DOGE,))
    fake.prices[DOGE] = 1.0
    c.market(DOGE, "BUY", 100.0, client_id="pbE")
    st = place_stop(c, DOGE, "SELL", 0.9, 100.0, client_id="pbS")
    after = make(fake=fake, clock=clock)[0]                    # a restart: the stop's coin is not known
    assert after.algo_order(algo_id=st["algoId"])["algoStatus"] == "NEW"
    assert after.algo_order(client_id="pbS")["algoId"] == st["algoId"]      # by its client id too
    real = fake._route

    def no_record(m, p, q):                                    # GET order of a stop answers nothing; ETH unread
        if (m, p) == ("GET", ORDER) and q.get("type") == "STOP":
            return 400, b'{"code":-2013,"msg":"Order does not exist."}', {}
        if (m, p) == ("GET", OPEN) and q.get("symbol") == "ETH-SWAP-USDT":
            return 503, b"busy", {}
        return real(m, p, q)
    fake._route = no_record
    assert make(fake=fake, clock=clock)[0].algo_order(algo_id=st["algoId"])["algoStatus"] == "NEW"
    with pytest.raises(TransientError):                       # not on the coins read, ETH unread: unknown
        make(fake=fake, clock=clock)[0].algo_order(algo_id="999")
    fake._route = real
    with pytest.raises(TestnetError) as e:                     # every coin answered: not found
        make(fake=fake, clock=clock)[0].algo_order(algo_id="999")
    assert e.value.code == NOT_FOUND[0] and not isinstance(e.value, TransientError)


def test_a_stop_fires_on_the_price_the_fake_chooses():
    c, fake, clock = make()
    fake.stop_price = "mark"
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    fake.set_price(BTC, 94.0, mark=96.0)                       # the last price crossed, the mark did not
    assert fake.amt(BTC) == 5
    fake.set_price(BTC, 96.0, mark=94.5)
    assert fake.amt(BTC) == 0
    assert TB.trigger_source(1, 95.0, {"last": [96.0], "mark": [94.5]})["verdict"] == "마크 가격"


def test_a_second_stop_firing_without_a_position_reads_as_rejected_never_fired():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    a = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS1")
    b = place_stop(c, BTC, "SELL", 94.0, 5.0, client_id="pbS2")
    fake.set_price(BTC, 93.0)
    got = {x: c.algo_order(algo_id=s["algoId"])["algoStatus"] for x, s in (("a", a), ("b", b))}
    assert got == {"a": "TRIGGERED", "b": "REJECTED"} and fake.amt(BTC) == 0


def test_a_stop_is_cancelled_only_on_an_explicit_record():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    fake.stop_lag_ms = 10 ** 9                                 # neither the list nor GET order shows it: ours
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == TB.UNCONFIRMED
    other, _, _ = make(fake=fake, clock=clock)
    with pytest.raises(TestnetError) as e:                     # someone else's id: not found, never "cancelled"
        other.algo_order(algo_id=st["algoId"])
    assert e.value.code == NOT_FOUND[0]
    fake.stop_lag_ms = 0
    edit_route(fake, OPEN, lambda d: [])                       # its record says resting, the list does not show it
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == TB.UNCONFIRMED
    reset_route(fake)
    for status in ("PENDING_CANCEL", "", "ORDER_SOMETHING"):
        edit_route(fake, ORDER, lambda d, x=status: {**d, "status": x})
        with pytest.raises(TransientError):                   # a status it does not know: never "cancelled"
            c.algo_order(algo_id=st["algoId"])
        reset_route(fake)
    resting = {k: v for k, v in fake.orders[st["algoId"]].items() if not k.startswith("_")}
    c.cancel_algo(algo_id=st["algoId"])
    edit_route(fake, OPEN, lambda d: d + [resting])            # a stale list still shows it resting
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == "CANCELED"   # its own record decides
    reset_route(fake)


@pytest.mark.parametrize("history_lag", [0, 5_000])
def test_a_new_stop_the_list_shows_late_is_waited_for(history_lag):
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    fake.stop_lag_ms, fake.history_lag_ms = 2_000, history_lag
    t0 = clock.t
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbLag")
    assert st["algoStatus"] == "NEW" and 2_000 <= clock.t - t0 <= TB.PROTECT_WAIT_S * 1000
    assert c.list_delay_ms[st["algoId"]] >= 2_000


def test_a_stop_the_list_does_not_show_is_never_confirmed():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    fake.stop_lag_ms = 30_000
    t0 = clock.t
    with pytest.raises(ProtectionError, match="UNCONFIRMED"):
        place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbLag")
    assert clock.t - t0 <= TB.PROTECT_WAIT_S * 1000 and len(fake.live_stops(BTC)) == 1


def test_a_new_stop_cancelled_by_the_exchange_never_lets_a_move_cancel_the_old_stop():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    old = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS1")
    fake.kill_new_stops = True
    with pytest.raises(ProtectionError):
        move_stop(c, BTC, "SELL", 97.0, 5.0, [old["algoId"]], client_id="pbS2")
    assert [t["orderId"] for t in fake.live_stops(BTC)] == [old["algoId"]] and not fake.unprotected()
    assert c.algo_order(client_id="pbS2")["algoStatus"] == "CANCELED"


@pytest.mark.parametrize("query_cid", [True, False])
def test_a_stop_whose_answer_was_lost_is_found_by_its_client_id(query_cid):
    c, fake, clock = make()
    fake.query_cid = query_cid                                 # False: GET order finds nothing, the stop list does
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    other = TB.ToobitClient("tk", "ts", send=fake, clock_ms=clock, sleep=lambda s: None)
    old = other.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbByHand")      # an identical stop resting before
    fake.fail("POST", ORDER, "drop_after")
    with pytest.raises(TransientError):
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbLostStop")
    got = c.algo_order(client_id="pbLostStop")
    assert got["algoId"] != old["algoId"] and got["algoStatus"] == "NEW" and len(fake.live_stops(BTC)) == 2
    again = c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbLostStop")       # never a second copy
    assert again["algoId"] == got["algoId"] and len(stops_sent(fake)) == 2
    c.forget_stop("pbLostStop")
    assert c.algo_order(client_id="pbLostStop")["algoId"] == got["algoId"]
    with pytest.raises(TestnetError) as e:                     # an id this process never sent
        c.algo_order(client_id="pbNeverSent")
    assert e.value.code == NOT_FOUND[0]


@UNKNOWN_IDS
def test_a_lost_stop_not_found_is_unknown_until_the_settle_window_then_sent_again(unknown_ids):
    c, fake, clock = make()
    fake.unknown_ids = unknown_ids
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    fake.fail("POST", ORDER, "drop_before")
    with pytest.raises(TransientError):
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS")
    with pytest.raises(TransientError):
        c.algo_order(client_id="pbS")
    with pytest.raises(TransientError):                       # inside the window: never a second copy
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS")
    clock.t += TB.SETTLE_MS
    with pytest.raises(TestnetError) as e:
        c.algo_order(client_id="pbS")
    assert e.value.code == NOT_FOUND[0]
    st = c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS")
    assert st["algoStatus"] == "NEW" and len(stops_sent(fake)) == 1 and len(fake.live_stops(BTC)) == 1


def test_two_stops_refused_stops_the_move_with_the_old_stop_in_place():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    old = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS1")
    fake.two_stops = False
    with pytest.raises(TestnetError):
        move_stop(c, BTC, "SELL", 97.0, 5.0, [old["algoId"]], client_id="pbS2")
    assert [t["orderId"] for t in fake.live_stops(BTC)] == [old["algoId"]]


def test_a_resting_stop_that_locks_the_close_is_a_refusal_with_the_stop_in_place():
    c, fake, clock = make()
    fake.locks_close = True
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    assert c.position(BTC)["available"] == "0"                 # the drill shows this number
    with pytest.raises(TestnetError) as e:
        c.market(BTC, "SELL", 2.0, reduce_only=True, client_id="pbX")
    assert e.value.code == -2010 and fake.amt(BTC) == 5 and [t["orderId"] for t in fake.live_stops(BTC)] == [
        st["algoId"]]


def test_opening_stops_and_position_tpsl_rows_are_never_counted_as_stops_nor_cancelled():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    base = {k: v for k, v in fake.orders[st["algoId"]].items() if not k.startswith("_")}
    tpsl = {**base, "orderId": "999", "type": "STOP_LONG_LOSS", "clientOrderId": ""}
    opening = {**base, "orderId": "998", "side": "BUY_OPEN", "stopPrice": "120", "clientOrderId": "byHand"}
    edit_route(fake, OPEN, lambda d: d + [tpsl, opening] if d else d)
    algos = {a["algoId"]: a["orderType"] for a in c.open_algo_orders(BTC)}
    assert algos == {st["algoId"]: "STOP_MARKET", "999": "CONDITIONAL", "998": "CONDITIONAL"}
    assert [a["algoId"] for a in live_stops(c, BTC)] == [st["algoId"]]
    reset_route(fake)
    edit_route(fake, OPEN, lambda d: d + [tpsl] if d else d)
    c.cancel_all_algo(BTC)
    cancelled = [dict(urllib.parse.parse_qsl(x[3]))["orderId"] for x in calls(fake, "DELETE", ORDER)]
    assert st["algoId"] in cancelled and "999" not in cancelled


def test_a_stop_row_whose_side_or_level_cannot_be_read_is_an_error_never_no_stop():
    c, fake, clock = make()
    ready(c, (BTC, ETH))
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    for bad in ({"side": ""}, {"side": None}, {"side": "CLOSE"}, {"type": "STOP_WHAT"}, {"stopPrice": ""},
                {"origQty": "x"}):
        edit_route(fake, OPEN, lambda d, b=bad: [{**r, **b} for r in d])
        with pytest.raises(TransientError):
            live_stops(c, BTC)
        reset_route(fake)
    edit_route(fake, OPEN, lambda d: [{**r, "type": "STOP_LIMIT"} for r in d])   # the order stream's word: a stop
    assert [a["algoId"] for a in live_stops(c, BTC)] == [st["algoId"]]
    reset_route(fake)
    garbled = {"orderId": "903", "symbol": "ETH-SWAP-USDT", "type": "STOP", "side": "", "status": "ORDER_NEW",
               "origQty": "1", "stopPrice": "x"}
    edit_route(fake, OPEN, lambda d: d + [garbled] if "ETH" in json.dumps(d) or not d else d)
    eth = c.open_algo_orders(ETH)                              # flat: the garbled row is listed, never a stop
    assert [(a["algoId"], a["orderType"], bool(a.get("tbUnreadable"))) for a in eth] == [("903", "CONDITIONAL", True)]
    assert live_stops(c, ETH) == []
    reset_route(fake)
    c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    edit_route(fake, OPEN, lambda d: [{**r, "side": ""} for r in d])
    with pytest.raises(TransientError):                       # flat, but a stop this process placed
        live_stops(c, BTC)
    reset_route(fake)


@pytest.mark.parametrize("cancel_final", ["record", "error"])
def test_a_cancel_of_a_stop_that_already_fired_is_not_found_and_reads_fired(cancel_final):
    c, fake, clock = make()
    fake.cancel_final = cancel_final
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    fake.set_price(BTC, 94.0)
    with pytest.raises(TestnetError) as e:
        c.cancel_algo(algo_id=st["algoId"])
    assert e.value.code == NOT_FOUND[1] and ("TRIGGERED" in e.value.msg or "ORDER_FILLED" in e.value.msg)
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == "TRIGGERED"


# ------------------------------------------------------------------ 429 and the protective budget
def test_an_opening_order_answered_429_is_never_sent_twice():
    c, fake, clock = make()
    ready(c)
    fake.fail("POST", ORDER, "429")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 1.0, client_id="pbE2")
    g = Guarded(c, lambda s: None, retries=4)
    fake.fail("POST", ORDER, "429_after")                      # it ran: the look-up finds it
    o = g.market(BTC, "BUY", 1.0, client_id="pbE3")
    assert o["status"] == "FILLED" and fake.amt(BTC) == 1 and len(orders(fake)) == 1


def test_a_close_answered_429_that_ran_is_found_and_reads_filled():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 2.0, client_id="pbE")
    fake.order_lag_ms = 3_000
    fake.fail("POST", ORDER, "429_after")
    o = c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbX1")
    assert (o["status"], o["executedQty"]) == ("FILLED", "1") and fake.amt(BTC) == 1 and len(orders(fake)) == 2


def test_a_close_answered_429_not_found_in_time_stays_unknown_and_never_goes_past_the_position():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbE")
    fake.order_lag_ms = 40_000                                 # shown only after the settle window
    fake.fail("POST", ORDER, "429_after")
    t0 = clock.t
    with pytest.raises(TB.RateLimitedUnknown):
        c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbX")
    assert clock.t - t0 <= TB.PROTECT_WAIT_S * 1000 and fake.amt(BTC) == 0
    with pytest.raises(TransientError):
        c.order(BTC, client_id="pbX")
    fake.order_lag_ms = 10 ** 9
    clock.t += TB.SETTLE_MS
    with pytest.raises(TestnetError) as e:                     # sent again only up to the position now: none left
        c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbX")
    assert e.value.code == -2022 and len(orders(fake)) == 2


def test_a_stop_answered_429_that_rests_is_found_and_never_sent_twice():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbE")
    fake.fail("POST", ORDER, "429_after")
    st = place_stop(c, BTC, "SELL", 95.0, 1.0, client_id="pbS1")
    assert st["algoStatus"] == "NEW" and len(fake.live_stops(BTC)) == 1 and len(stops_sent(fake)) == 1


def test_a_stop_whose_429_was_a_refusal_is_sent_once_more():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbE")
    g = Guarded(c, ticking(clock), retries=4)
    fake.fail("POST", ORDER, "429")                            # refused: nothing placed
    t0 = clock.t
    st = place_stop(g, BTC, "SELL", 95.0, 1.0, client_id="pbS1")
    assert st["algoStatus"] == "NEW" and [t["orderId"] for t in fake.live_stops(BTC)] == [st["algoId"]]
    assert len(stops_sent(fake)) == 1 and clock.t - t0 <= TB.PROTECT_WAIT_S * 1000
    assert c.stop_intents["pbS1"]["sends"] == 2
    fake.fail("POST", ORDER, "429", times=2)                   # a close is still never sent again by the client
    with pytest.raises(TB.RateLimitedUnknown):
        c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbX")
    assert len(orders(fake)) == 1 and fake.amt(BTC) == 1


def test_a_stop_answered_429_that_ran_behind_a_lagging_record_rests_once():
    """The stop ran, its 429 answer came back and neither its record nor the list shows it yet: it is sent once more
    under the same client id, which Toobit refuses while the first rests (-1141); the look-ups then find the first."""
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbE")
    fake.stop_lag_ms = 3_000
    fake.fail("POST", ORDER, "429_after")
    st = place_stop(c, BTC, "SELL", 95.0, 1.0, client_id="pbS1")
    assert st["algoStatus"] == "NEW" and len(fake.live_stops(BTC)) == 1
    assert len([x for x in calls(fake, "POST", ORDER) if b"type=STOP" in x[4]]) == 2


def test_protective_calls_end_within_their_budget():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    real = fake._stop

    def throttled(q, s, closing):                              # from the stop's 429 on, its look-ups are throttled too
        fake.fail("GET", ORDER, ("429", 3), times=100)
        fake.fail("GET", OPEN, ("429", 3), times=100)
        return 429, b'{"code":-1003,"msg":"Too many requests."}', {"Retry-After": "3"}
    fake._stop = throttled
    t0 = clock.t
    with pytest.raises(TB.RateLimitedUnknown):
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS")
    assert 3_000 <= clock.t - t0 <= TB.PROTECT_WAIT_S * 1000
    fake.fails.clear()
    fake._stop = real
    fake.fail("POST", ORDER, ("429", 60))
    t0 = clock.t
    with pytest.raises(RateLimited):
        c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    assert clock.t - t0 <= 1_000 and fake.amt(BTC) == 5


# ------------------------------------------------------------------ missing fields
def strip_lot(fake, symbol, field):
    def f(d):
        for r in d["contracts"]:
            if r["symbol"] == TB.tb(symbol):
                for flt in r["filters"]:
                    flt.pop(field, None)
                r.pop(field, None)
        return d
    edit_route(fake, "/api/v1/exchangeInfo", f)


def test_a_missing_entry_only_field_refuses_that_coins_entries_only():
    c, fake, clock = make()
    ready(c, (BTC, DOGE))
    fake.prices[DOGE] = 1.0
    c.market(DOGE, "BUY", 100.0, client_id="pbD")             # opened before the value went missing
    strip_lot(fake, DOGE, "minQty")
    c.specs.clear()
    c.spec_ms = None
    sp = c.spec(DOGE)
    assert sp["min_sz"] is None and "minQty" in sp["problem"] and c.spec(BTC)["problem"] is None
    assert "없음 → 새 진입 안 함" in TB.specs_text(c) and "BTCUSDT: 상태 Trading" in TB.specs_text(c)
    for call in (lambda: c.leverage(DOGE, 10), lambda: c.market(DOGE, "BUY", 100.0, client_id="pbD2")):
        with pytest.raises(TestnetError) as e:
            call()
        assert e.value.code == "BAD_SPEC" and "새 진입" in e.value.msg
    assert place_stop(c, DOGE, "SELL", 0.95, 100.0, client_id="pbDs")["algoStatus"] == "NEW"
    assert c.market(DOGE, "SELL", 100.0, reduce_only=True, client_id="pbDx")["status"] == "FILLED"
    assert not c.account_setup([DOGE])[1][0]
    d = TB.ToobitDrill(c, wait=lambda s: None, elapsed=lambda: clock.t / 1000)
    with pytest.raises(AssertionError):
        d.check()
    step = next(r for r in d.log if r["step"].startswith("상품 정보"))
    assert not step["ok"] and "minQty" in step["detail"][DOGE]["error"]
    for field in ("maxQty", "minNotional"):                   # a filter without its value: no new entry
        reset_route(fake)
        strip_lot(fake, BTC, field)
        c.spec_ms = None
        c._load_instruments()
        assert field in c.spec(BTC)["problem"]
    reset_route(fake)
    edit_route(fake, "/api/v1/exchangeInfo", lambda d: {**d, "contracts": [
        {**r, "filters": [f for f in r["filters"] if f["filterType"] != "MIN_NOTIONAL"]} for r in d["contracts"]]})
    c.spec_ms = None
    c._load_instruments()                                      # no MIN_NOTIONAL filter at all: no minimum value
    assert c.spec(BTC)["problem"] is None and c.spec(BTC)["min_notional"] == 0.0


def test_a_missing_unit_is_bad_spec_for_that_coin_only():
    c, fake, clock = make()
    strip_lot(fake, ETH, "contractMultiplier")
    with pytest.raises(TestnetError) as e:
        c.spec(ETH)
    assert e.value.code == "BAD_SPEC" and "contractMultiplier" in e.value.msg
    assert c.spec(BTC)["ct_val"] == "0.001"
    assert "ETHUSDT: 상품 정보를 쓸 수 없습니다" in TB.specs_text(c)


def test_the_stop_list_and_records_are_never_empty_from_a_garbled_answer():
    c, fake, clock = make()
    ready(c)
    for stop in (True, False):
        edit_route(fake, OPEN, lambda d: None)
        with pytest.raises(TransientError):
            c.open_algo_orders(BTC) if stop else c.open_orders(BTC)
        reset_route(fake)
    edit_route(fake, OPEN, lambda d: [{**r, "orderId": ""} for r in d] + [{"symbol": "BTC-SWAP-USDT"}])
    with pytest.raises(TransientError):
        c.open_orders(BTC)
    reset_route(fake)


# ------------------------------------------------------------------ fills, P&L, funding
def test_fills_carry_toobits_own_pnl_checked_against_the_fill_prices():
    c, fake, clock = make()
    ready(c, (ETH,))
    t0 = clock.t
    c.market(ETH, "SELL", 1.0, client_id="pbE")                # 100 contracts short at 100
    clock.t += 60_000
    fake.set_price(ETH, 95.0)
    c.market(ETH, "BUY", 0.4, reduce_only=True, client_id="pbX1")
    clock.t += 60_000
    fake.set_price(ETH, 90.0)
    c.market(ETH, "BUY", 0.6, reduce_only=True, client_id="pbX2")
    fills = c.user_trades(ETH, t0, clock.t)
    got = [(f["side"], f["qty"], f["realizedPnl"], f["realizedSource"], f.get("realizedCheck")) for f in fills]
    assert got == [("SELL", "1", "0", "open", None), ("BUY", "0.4", "2", "pnl", "ok"), ("BUY", "0.6", "6", "pnl", "ok")]
    assert sum(float(f["commission"]) for f in fills) == pytest.approx(0.06 + 0.0228 + 0.0324)
    assert fake.wallet == pytest.approx(10_000 + 8 - 0.1152)
    late = c.user_trades(ETH, t0 + 90_000, clock.t)            # a window holding only the last close: its own pnl
    assert [(f["realizedPnl"], f["realizedSource"], f["realizedCheck"]) for f in late] == [("6", "pnl", "pnl")]


def test_a_pnl_net_of_fees_or_a_missing_one_is_never_a_final_number():
    c, fake, clock = make()
    fake.pnl_net_of_fees = True
    ready(c)
    t0 = clock.t
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    clock.t += 60_000
    fake.set_price(BTC, 110.0)
    c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    fills = c.user_trades(BTC, t0, clock.t)
    assert fills[-1]["realizedCheck"] == "mismatch"             # 50 by the fill prices, 49.67 by the realizedPnl
    edit_route(fake, "/api/v1/futures/userTrades", lambda d: [{**r, "realizedPnl": ""} for r in d])
    fills = c.user_trades(BTC, t0, clock.t)
    assert (fills[-1]["realizedPnl"], fills[-1]["realizedSource"], fills[-1]["realizedCheck"]) == ("50", "replay",
                                                                                                    "unchecked")
    late = c.user_trades(BTC, clock.t, clock.t)                 # the close alone, no realizedPnl: unknown, never a 0
    assert (late[0]["realizedSource"], late[0]["realizedCheck"]) == ("unknown", "mismatch")


def test_a_full_fills_page_is_read_again_in_halves_and_a_too_long_window_is_split():
    c, fake, clock = make()
    ready(c, (DOGE,))
    fake.prices[DOGE] = 1.0
    t0 = clock.t
    for i in range(600):
        c.market(DOGE, "BUY", 10.0, client_id=f"pbB{i}")
        clock.t += 1
        c.market(DOGE, "SELL", 10.0, reduce_only=True, client_id=f"pbC{i}")
        clock.t += 1
    fills = c.user_trades(DOGE, t0, clock.t - 1)
    assert len(fills) == 1200 and len({f["id"] for f in fills}) == 1200
    last = max(f["time"] for f in fills)
    assert [f["time"] for f in c.user_trades(DOGE, last, last)] == [last]
    real, seen = fake._route, []

    def too_long(m, p, q):                                     # a window longer than an hour is refused (-1127)
        if p == "/api/v1/futures/userTrades" and int(q["endTime"]) - int(q["startTime"]) > 3_600_000:
            seen.append(1)
            return 400, b'{"code":-1127,"msg":"More than 1 hours between startTime and endTime."}', {}
        return real(m, p, q)
    fake._route = too_long
    assert len(c.user_trades(DOGE, t0 - 3 * 3_600_000, clock.t)) == 1200 and seen
    fake._route = real
    edit_route(fake, "/api/v1/futures/userTrades", lambda d: d + d[:1] * 1000)
    with pytest.raises(TransientError):                        # a server that ignores the window: an error
        c.user_trades(DOGE, t0, clock.t)


def test_funding_and_transfers_from_the_balance_flow():
    c, fake, clock = make()
    ready(c)
    t0 = clock.t
    for i in range(30):
        clock.t += 1_000
        fake.add_funding(BTC if i % 3 else ETH, -0.5 if i % 2 else 0.25)
    clock.t += 1_000
    fake.add_transfer(100.0)
    clock.t += 1_000
    fake.add_transfer(-40.0)
    rows = c.income(BTC, None, t0, clock.t)
    funding = [r for r in rows if r["incomeType"] == "FUNDING_FEE"]
    assert len(funding) == 20 and all(r["symbol"] == BTC for r in funding) and funding[0]["income"] == "-0.5"
    assert [r["income"] for r in rows if r["incomeType"] == "TRANSFER"] == ["100", "-40"]
    assert len({r["tranId"] for r in rows}) == len(rows)
    assert len(c.income(None, "FUNDING_FEE", t0, clock.t)) == 30 and c.income(None, "OTHER", t0, clock.t) == []
    kinds = c.flow_types(t0, clock.t)
    assert kinds == {"32 펀딩비": 30, "51 이체": 2}
    edit_route(fake, "/api/v1/futures/balanceFlow", lambda d: [{**r, "flowTypeValue": 10} for r in d])
    assert c.income(BTC, None, t0, clock.t) == []              # the filter ignored: rows of other types left out


# ------------------------------------------------------------------ keys and gates
def test_keys_gates_and_reuse_refusals():
    assert TB.trading_keys("mainnet", LIVE_ENV) == ("tk", "ts")
    with pytest.raises(Refused, match="테스트넷"):
        TB.trading_keys("testnet", LIVE_ENV)
    with pytest.raises(Refused, match=FLAG):
        TB.trading_keys("mainnet", {**LIVE_ENV, FLAG: ""})
    with pytest.raises(Refused):
        TB.trading_keys("mainnet", {**LIVE_ENV, "TOOBIT_LIVE_SECRET": ""})
    with pytest.raises(Refused, match="같습니다"):
        TB.trading_keys("mainnet", {**LIVE_ENV, "TOOBIT_LIVE_SECRET": "tk"})
    for name in ("BINANCE_API_KEY", "LIVE_API_KEY", "TESTNET_API_SECRET", "BYBIT_LIVE_API_KEY", "MEXC_LIVE_SECRET",
                 "WOOXPRO_LIVE_KEY", "WOOXPRO_LIVE_MEMO", "FLIPSTER_LIVE_KEY", "DEEPCOIN_LIVE_KEY",
                 "DEEPCOIN_LIVE_PASSPHRASE"):
        with pytest.raises(Refused):
            TB.trading_keys("mainnet", {**LIVE_ENV, name: "tk"})
    with pytest.raises(Refused, match="paper"):
        TB.trading_keys("mainnet", LIVE_ENV, {"BINANCE_API_KEY": "ts"})
    c, kc = TB.clients("mainnet", LIVE_ENV)
    assert type(c) is TB.ToobitClient and isinstance(kc, TB.ToobitKeyCheckClient) and kc.attested
    assert (c.key, c.secret) == ("tk", "ts")


def test_the_owners_statement_is_required():
    c, kc = TB.clients("mainnet", LIVE_ENV)
    TB.check_executor_keys("mainnet", c, kc, LIVE_ENV, {})
    env = {k: v for k, v in LIVE_ENV.items() if k != TB.KEY_CHECKED}
    c2, kc2 = TB.clients("mainnet", env)
    with pytest.raises(Refused, match=TB.KEY_CHECKED):
        TB.check_executor_keys("mainnet", c2, kc2, env, {})
    with pytest.raises(Refused):
        TB.check_executor_keys("mainnet", c, c, LIVE_ENV, {})                # the order client is no key check
    other = TB.ToobitClient("tk", "other")
    with pytest.raises(Refused):
        TB.check_executor_keys("mainnet", other, kc, LIVE_ENV, {})
    fake = FakeToobit()
    fake.clock = Clock()
    kc3 = TB.ToobitKeyCheckClient("tk", "ts", send=fake, clock_ms=fake.clock, sleep=lambda s: None, attested=True)
    perm = kc3.api_restrictions()
    assert check_permissions(perm) == [] and perm["warnings"] and TB.KEY_CHECKED in perm["warnings"][0]
    kc3.attested = False
    assert any(TB.KEY_CHECKED in p for p in check_permissions(kc3.api_restrictions()))


def test_refuse_unless_allowed():
    c, kc = TB.clients("mainnet", LIVE_ENV)
    TB.refuse_unless_allowed("mainnet", c)
    with pytest.raises(Refused):
        TB.refuse_unless_allowed("testnet", c)
    with pytest.raises(Refused):
        TB.refuse_unless_allowed("mainnet", kc)                  # the key-check class never trades
    with pytest.raises(Refused):
        TB.refuse_unless_allowed("mainnet", TB.public_client())

    class Other(TB.ToobitClient):
        HOSTS = ("api.toobit.com", "evil.example")
    with pytest.raises(Refused):
        TB.refuse_unless_allowed("mainnet", Other("tk", "ts"))


def test_agents_never_import_the_module():
    root = ROOT / "paperbot"
    for p in list(root.glob("agents*.py")) + list(root.glob("rooms*.py")) + list((root / "agents").glob("**/*.py")):
        assert "toobit" not in p.read_text(encoding="utf-8"), p


def test_the_live_config_template_is_the_owners_plan():
    """deploy/executor.live-toobit.json (owners 10-25 night: "증거금 40% BTC 40배 나머지 30배", then "손절 2.5 ATR로 가고
    15%되면 13%에 익절 20%되면 17%익절 25%되면 22%", and later "너가 정한 기준으로 갈게": the ladder from 20 -> 17): the
    exchange, mainnet, $50, its own key file and database, the rule bot's V3.9 1-hour paper account, 40 % of the balance as
    margin at BTC 40x / the others 30x, the paper's stop distance x 1.25 (2.5 ATR) from its own fill, no entry whose stop
    sits beyond the liquidation, its own ladder 20 -> 17, 25 -> 22, 30 -> 27 ... on net ROE, no fixed take-profit. A
    valid config as it is."""
    raw = json.loads((ROOT / "deploy" / "executor.live-toobit.json").read_text(encoding="utf-8"))
    cfg = ExecConfig.from_dict(raw)
    assert (cfg.exchange, cfg.mode, cfg.db, cfg.budget_usd, cfg.size_from, cfg.margin_frac, cfg.own_keys) == (
        "toobit", "mainnet", "/var/lib/paperbot/exec/executor-toobit-live.db", 50, "equity", 0.4, True)
    assert (cfg.account, cfg.paper_db) == ("V39_ALL@1h", "/var/lib/paperbot/paper3.db")
    assert cfg.problems() == []
    assert (cfg.stop_from, cfg.ladder_from, cfg.entry_source, cfg.signal_light_n) == ("ratio", "own", "paper", 0)
    assert cfg.leverage_by_symbol == {"BTCUSDT": 40, "*": 30} and cfg.risk.max_leverage == 40
    assert [cfg.entry_leverage(s, 20) for s in cfg.risk.allowed_symbols] == [40, 30, 30, 30, 30, 30]
    assert (cfg.stop_scale, cfg.liq_guard, cfg.liq_guard_mmr) == (1.25, True, 0.005)
    assert cfg.ladder == {"first_lock": 0.17, "trigger_gap": 0.03, "step": 0.05, "next_trigger": 0.25, "next_gap": 0.03}
    spec = cfg.ladder_spec()
    locks = [spec.lock_for(r) for r in (0.15, 0.199, 0.20, 0.249, 0.25, 0.30, 0.35)]
    assert locks[:2] == [None, None] and locks[2:] == pytest.approx([0.17, 0.17, 0.22, 0.27, 0.32])
    assert cfg.ladder_basis == "net" and cfg.take_profit_roe is None and "take_profit_roe" not in raw
    assert "stop_roe" not in raw
    assert cfg.net_cost() == {"taker_fee": 0.0006, "slippage": 0.0002}
    assert tuple(cfg.risk.allowed_symbols) == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")


def test_the_unit_and_the_key_file_template():
    unit = (ROOT / "deploy" / "paperbot-executor-toobit.service").read_text(encoding="utf-8")
    lines = [ln for ln in unit.splitlines() if ln and not ln.startswith("#")]
    start = ("ExecStart=/opt/paperbot/venv/bin/python -m paperbot.executor run --config "
             "/etc/paperbot/executor-toobit.json")
    assert start in lines and "EnvironmentFile=/etc/paperbot/executor-toobit.env" in lines
    assert "EnvironmentFile=/etc/paperbot/executor.env" not in lines        # its own key file INSTEAD of the shared one
    assert "User=paperbot-exec" in lines and "OOMScoreAdjust=-900" in lines and "RestartPreventExitStatus=2" in lines
    hidden = next(ln for ln in lines if ln.startswith("InaccessiblePaths=")).split("=", 1)[1].split()
    assert {"-/etc/paperbot/executor.env", "-/etc/paperbot/agents.env", "-/etc/paperbot/dash.env"} <= set(hidden)
    assert "NEVER enables or starts it" in unit
    env = (ROOT / "deploy" / "executor-toobit.env.example").read_text(encoding="utf-8")
    for name in ("TOOBIT_LIVE_KEY", "TOOBIT_LIVE_SECRET", "TOOBIT_LIVE_KEY_CHECKED", "PAPERBOT_LIVE_MAINNET"):
        assert f"\n{name}=\n" in env
    assert "158.247.200.152" in env and "sudoedit /etc/paperbot/executor-toobit.env" in env
    values = [ln.split("=", 1)[1] for ln in env.splitlines() if "=" in ln and not ln.startswith("#")]
    assert values and all(v == "" for v in values)             # nothing secret in the template


def test_install_and_the_wrapper_know_the_toobit_executor_once_applied():
    """The install.sh / paperbot-exec.sh lines are applied by the reviewer (this change does not edit them): checked
    once they are there."""
    import re
    import subprocess
    sh = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    wrap = (ROOT / "deploy" / "paperbot-exec.sh").read_text(encoding="utf-8")
    if "paperbot-executor-toobit" not in sh or "toobit" not in wrap:
        pytest.skip("the install.sh / paperbot-exec.sh lines for Toobit are applied separately")
    assert ('install -m 644 "$APP/deploy/paperbot-executor-toobit.service" '
            "/etc/systemd/system/paperbot-executor-toobit.service") in sh
    assert not re.search(r"systemctl (enable|start)\b[^\n]*paperbot-executor-toobit", sh)
    assert ('install -o root -g root -m 600 "$APP/deploy/executor-toobit.env.example" '
            "/etc/paperbot/executor-toobit.env") in sh
    assert not re.search(r"(install|cp)\s[^\n]*executor\.live-toobit\.json", sh)
    assert "toobit) keys=EnvironmentFile=/etc/paperbot/executor-toobit.env" in wrap
    assert subprocess.run(["bash", "-n", str(ROOT / "deploy" / "install.sh")]).returncode == 0
    assert subprocess.run(["sh", "-n", str(ROOT / "deploy" / "paperbot-exec.sh")]).returncode == 0


# ------------------------------------------------------------------ the drill
def drill_world(**kw):
    c, fake, clock = make(**kw)
    fake.prices[DOGE] = fake.marks[DOGE] = 0.2
    return c, fake, clock


def trigger_wait(fake, clock, side, symbol=DOGE, px=0.2):
    ours = round(px * (1 + side * 0.004), 6)                   # 0.4 % our way

    def wait(s):
        clock.t += int(s * 1000)
        levels = [float(t["stopPrice"]) for t in fake.live_stops(symbol)]
        if fake.amt(symbol) and len(levels) == 1 and side * (px - levels[0]) > 0:
            fake.set_price(symbol, ours)                       # the test stop goes past the entry (the profit side)
        elif fake.amt(symbol) and len(levels) == 1 and side * (levels[0] - px) > 0:
            fake.set_price(symbol, px, mark=ours)              # ... the last price comes back to it (not the mark)
    return wait


@pytest.mark.parametrize("own_fills, side, family, unknown_ids", [(False, 1, "plan", "error"),
                                                                  (True, 1, "regular", "empty"),
                                                                  (False, -1, "regular", "empty"),
                                                                  (True, -1, "plan", "error")])
def test_drill_check_and_order_cycle_with_the_trigger_test(own_fills, side, family, unknown_ids):
    c, fake, clock = drill_world()
    fake.own_fills, fake.stop_family, fake.unknown_ids = own_fills, family, unknown_ids
    kc = TB.ToobitKeyCheckClient("tk", "ts", send=fake, clock_ms=clock, sleep=lambda s: None, attested=True)
    lines = []
    d = TB.ToobitDrill(c, symbol=DOGE, side=side, keycheck=kc, wait=trigger_wait(fake, clock, side),
                       trigger_wait_s=600, elapsed=lambda: clock.t / 1000, say=lines.append)
    ok = TB.run_drill(c, d, "drill", True, pause=lambda s: None)
    fails = [r for r in d.log if not r["ok"]]
    assert ok and not fails, fails
    this, other = ("롱", "숏(--side short)") if side > 0 else ("숏", "롱(--side long)")
    assert lines[-1] == f"끝: drill 모두 [OK] (이번은 {this} 쪽입니다. {other}도 모두 [OK]여야 drill이 끝납니다)"
    steps = {r["step"]: r for r in d.log}
    entry = next(r for k, r in steps.items() if k.startswith("시장가 진입"))
    assert entry["detail"]["clientOrderId_len"] == 32 and entry["detail"]["contracts"] == "6"
    half = next(r for k, r in steps.items() if k.startswith("손절이 걸린 채로 줄이기 전용 시장가"))
    assert half["ok"] and half["detail"]["qty"] == "30" and abs(float(half["detail"]["positionAmt"])) == 30
    closes = [b for b in orders(fake) if b["side"].endswith("_CLOSE")]
    assert len(closes) == 1 and closes[0]["side"] == ("SELL_CLOSE" if side > 0 else "BUY_CLOSE")
    assert [b["quantity"] for b in stops_sent(fake)][-2:] == ["3", "3"]       # the moved stop and the test stop
    assert steps["답을 잃은 주문 찾기(보낸 기록 없이 우리 번호로 다시 조회 - 실행기가 쓰는 길)"]["ok"]
    assert steps["손절을 우리 번호로 찾음(GET order type=STOP)"]["ok"]
    assert steps["답을 잃은 손절 찾기(보낸 기록 없이 우리 번호로 - 실행기가 쓰는 길)"]["ok"]
    assert steps["취소한 손절이 기록에 '취소'로 남음(CANCELED)"]["ok"]
    assert steps["수량 단위: 포지션 가치(positionValue) = 계약 수 × 계약 크기 × 가격"]["ok"]
    assert steps["잔고(balance)는 진입해도 증거금만큼 줄지 않고, 평가액 = 잔고 + 미실현 손익"]["ok"]
    fired = next(r for k, r in steps.items() if k.startswith("손절 발동 시험:"))
    assert fired["detail"]["status"] == "TRIGGERED"
    assert steps["손절을 발동시킨 가격(마지막 가격 / 마크 가격)"]["detail"]["verdict"] == "마지막 가격"
    assert steps["발동한 손절의 체결을 찾음(손절 자신의 orderId, 또는 손절이 낸 주문)"]["ok"]
    assert steps["이익 쪽 손절(계단 잠금 자리, 진입가보다 유리한 곳)이 걸림"]["ok"]
    pnl = next(r for k, r in steps.items() if k.startswith("체결로 계산한 손익"))
    assert pnl["detail"]["fee_rate_pct"] == pytest.approx(0.06, abs=1e-3) and pnl["detail"]["check"] == ["ok"]
    assert steps["실제 수수료율 = 수수료율 API(진입·청산 테이커; 다르면 실제 값을 쓰세요)"]["ok"]
    still = steps["잔고에 미실현 손익이 섞이지 않음(손절을 기다리는 동안 가격이 움직여도 잔고는 그대로)"]
    assert still["ok"] and isinstance(still["detail"], dict) and still["detail"]["unrealized_swing"] >= TB.WALLET_SWING
    assert d.fire_seen and fake.amt(DOGE) == 0 and not fake.stops(DOGE)


def test_the_drill_catches_a_balance_that_holds_the_unrealized_pnl():
    """Review 10-25: a ``balance`` that already holds the unrealized P&L passed the open step (equity = wallet + uPnL
    by construction); the trigger wait sees the wallet move with the price."""
    c, fake, clock = drill_world()
    fake.balance_has_upnl = True
    d = TB.ToobitDrill(c, symbol=DOGE, wait=trigger_wait(fake, clock, 1), trigger_wait_s=600,
                       elapsed=lambda: clock.t / 1000)
    assert not TB.run_drill(c, d, "drill", True, pause=lambda s: None)
    bad = [r for r in d.log if not r["ok"]]
    assert any(r["step"].startswith("잔고에 미실현 손익이 섞이지 않음") for r in bad), bad
    assert fake.amt(DOGE) == 0 and not fake.stops(DOGE)


def test_drill_prints_each_step_and_ends_flat_without_the_trigger_test():
    c, fake, clock = drill_world()
    lines = []
    d = TB.ToobitDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000,
                       say=lines.append)
    assert TB.run_drill(c, d, "drill", True, pause=lambda s: None), [r for r in d.log if not r["ok"]]
    assert len([x for x in lines if x.startswith("[OK]")]) == len(d.log)
    # no stop seen firing (review 10-25): the steps passed, the drill is not done
    assert lines[-1] == ("끝: drill 실행한 단계는 모두 [OK]이지만 손절 발동은 아직 못 봤습니다: 실행기를 켜기 전에 발동이 보일 때까지 "
                         "drill을 한 번 더 하세요(--no-trigger-test 없이) (이번은 롱 쪽입니다. 숏(--side short)도 모두 [OK]여야 "
                         "drill이 끝납니다)")
    assert not d.fire_seen and fake.amt(DOGE) == 0 and not fake.stops(DOGE)


def test_the_drill_picks_a_coin_whose_contract_tells_the_units_apart():
    c, fake, clock = drill_world()
    d = TB.ToobitDrill(c, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000)
    assert d.smallest() != LTC and TB.Decimal(c.spec(d.smallest())["ct_val"]) != 1
    assert TB.ToobitDrill.drill_qty(c.spec(DOGE), 0.2) == 60   # $10.5 or more (2.1 x $5), halves of 3 contracts
    c2, fake2, clock2 = make()
    lines = []                                                 # LTC: 1 contract = 1 LTC: the step says so
    d2 = TB.ToobitDrill(c2, symbol=LTC, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock2.t / 1000,
                        say=lines.append)
    assert TB.run_drill(c2, d2, "drill", True, pause=lambda s: None), [r for r in d2.log if not r["ok"]]
    step = next(r for r in d2.log if r["step"].startswith("수량 단위"))
    assert step["ok"] and "가리지 못합니다" in step["detail"]["note"]


def test_the_drill_catches_a_balance_that_drops_by_the_margin():
    c, fake, clock = drill_world()
    fake.balance_is_free = True
    d = TB.ToobitDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000)
    assert not TB.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert any(r["step"].startswith("잔고(balance)") and not r["ok"] for r in d.log)
    assert fake.amt(DOGE) == 0 and not fake.stops(DOGE)


def test_the_drill_waits_for_lagging_records_and_ends_flat():
    c, fake, clock = drill_world(advance=True)
    fake.order_lag_ms, fake.stop_lag_ms = 3_000, 1_000
    d = TB.ToobitDrill(c, symbol=DOGE, wait=ticking(clock), trigger_test=False, elapsed=lambda: clock.t / 1000)
    assert TB.run_drill(c, d, "drill", True, pause=lambda s: None), [r for r in d.log if not r["ok"]]
    steps = {r["step"]: r for r in d.log}
    assert steps["진입 주문을 우리 번호(newClientOrderId)로 찾음(GET order)"]["detail"]["seconds"] >= 3
    stop = next(r for k, r in steps.items() if k.startswith("손절이 투비트에 걸림"))
    assert stop["detail"]["listed_after_ms"] >= 1_000 and stop["detail"]["level_field"] == "stopPrice"
    assert fake.amt(DOGE) == 0 and not fake.stops(DOGE)


def test_the_drill_notes_lists_without_the_client_id_and_still_passes():
    """DeepCoin's first live drill (10-25): a list read the client id empty. The look-up the executor uses (GET order)
    is the step; the lists are a note with what they show."""
    c, fake, clock = drill_world()
    fake.lists_hide_cid = True
    lines = []
    d = TB.ToobitDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000,
                       say=lines.append)
    assert TB.run_drill(c, d, "drill", True, pause=lambda s: None), [r for r in d.log if not r["ok"]]
    notes = [x for x in lines if "안 보였습니다" in x]
    assert len(notes) == 2 and "'found_by_orderId': True" in notes[0] and "'clientOrderId_there': ''" in notes[0]
    assert fake.amt(DOGE) == 0


def test_the_drill_notes_lists_with_the_client_id():
    c, fake, clock = drill_world()
    lines = []
    d = TB.ToobitDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000,
                       say=lines.append)
    assert TB.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert any("대기 목록·주문 기록에도 같은 clientOrderId로 보입니다" in x for x in lines)
    assert any("손절 목록·손절 기록에도 같은 clientOrderId로 보입니다" in x for x in lines)


def test_the_drill_fails_when_get_order_cannot_find_by_client_id_and_ends_flat():
    """Every look-up the executor relies on is a drill step: GET order by origClientOrderId not working is a [FAIL]
    (the lists alone are never enough), and the drill still ends flat."""
    c, fake, clock = drill_world()
    fake.query_cid = False
    d = TB.ToobitDrill(c, symbol=DOGE, wait=ticking(clock), trigger_test=False, elapsed=lambda: clock.t / 1000)
    assert not TB.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert any(r["step"].startswith("진입 주문을 우리 번호") and not r["ok"] for r in d.log)
    assert fake.amt(DOGE) == 0 and not fake.stops(DOGE)


def test_the_drill_without_the_confirmation_sends_no_order():
    c, fake, clock = drill_world()
    d = TB.ToobitDrill(c, symbol=DOGE, wait=lambda s: None, elapsed=lambda: clock.t / 1000)
    assert TB.run_drill(c, d, "drill", False, pause=lambda s: None)
    assert not orders(fake) and not stops_sent(fake) and d.log[-1]["step"] == "주문 단계"


@pytest.mark.parametrize("stop", ["error", "ctrl_c"])
def test_a_drill_stopped_part_way_leaves_the_coin_flat(stop):
    c, fake, clock = drill_world()
    lines = []

    def wait(s):            # the stop is resting and the trigger test waits: then the drill is stopped
        clock.t += int(s * 1000)
        if fake.amt(DOGE) and fake.live_stops(DOGE) and clock.t > T0 + 120_000:
            if stop == "ctrl_c":
                raise KeyboardInterrupt("SIGHUP")
            raise ValueError("an unexpected reply")
    d = TB.ToobitDrill(c, symbol=DOGE, wait=wait, trigger_wait_s=600, elapsed=lambda: clock.t / 1000,
                       say=lines.append)
    assert not TB.run_drill(c, d, "drill", True, pause=lambda s: None)
    steps = {r["step"]: r for r in d.log}
    assert not steps["멈춤"]["ok"]
    assert steps["정리 후 상태"]["ok"], steps["정리 후 상태"]
    assert fake.amt(DOGE) == 0 and not fake.stops(DOGE)
    assert lines[-1].startswith("끝: drill [FAIL]")


def test_the_drill_without_the_trigger_test_closes_with_two_reduce_only_orders_on_the_short_side():
    c, fake, clock = drill_world()
    lines = []
    d = TB.ToobitDrill(c, symbol=DOGE, side=-1, wait=lambda s: None, trigger_test=False,
                       elapsed=lambda: clock.t / 1000, say=lines.append)
    assert TB.run_drill(c, d, "drill", True, pause=lambda s: None), [r for r in d.log if not r["ok"]]
    closes = [(b["side"], b["quantity"]) for b in orders(fake) if b["side"].endswith("_CLOSE")]
    assert closes == [("BUY_CLOSE", "3"), ("BUY_CLOSE", "3")] and orders(fake)[0] == {
        "symbol": "DOGE-SWAP-USDT", "side": "SELL_OPEN", "type": "LIMIT", "priceType": "MARKET", "quantity": "6",
        "newClientOrderId": orders(fake)[0]["newClientOrderId"]}
    assert lines[-1].endswith("(이번은 숏 쪽입니다. 롱(--side long)도 모두 [OK]여야 drill이 끝납니다)")
    assert fake.amt(DOGE) == 0 and not fake.stops(DOGE)


@pytest.mark.parametrize("held", ["position", "stop"])
def test_the_drill_never_closes_or_cancels_what_it_did_not_open(held):
    c, fake, clock = drill_world()
    owner = ready(make(fake=fake, clock=clock)[0], (DOGE,))
    if held == "position":                                     # e.g. the executor's trade with its stop
        owner.market(DOGE, "BUY", 500.0, client_id="pbexecentry1")
        place_stop(owner, DOGE, "SELL", 0.19, 500.0, client_id="pbexecstop1")
    else:                                                      # a stop resting without a position
        fake._record({"symbol": "DOGE-SWAP-USDT", "side": "SELL_CLOSE", "quantity": "10", "priceType": "MARKET",
                      "stopPrice": "0.19", "newClientOrderId": "pbexecstop1"}, "STOP")
    before = (fake.amt(DOGE), sorted(o["orderId"] for o in fake.stops(DOGE)))
    lines = []
    d = TB.ToobitDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000,
                       say=lines.append)
    assert not TB.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert (fake.amt(DOGE), sorted(o["orderId"] for o in fake.stops(DOGE))) == before
    assert not any(r["step"].startswith("정리") for r in d.log) and not d.entry_sent
    assert any("계정에는 손대지 않았습니다" in x for x in lines)


def test_a_drill_stopped_after_its_entry_cleans_up_only_what_it_made():
    c, fake, clock = drill_world()
    owner = make(fake=fake, clock=clock)[0]
    theirs = {}

    def wait(s):            # the drill's stop rests: someone else puts a stop on the coin, then the drill is stopped
        clock.t += int(s * 1000)
        if fake.amt(DOGE) and fake.live_stops(DOGE) and clock.t > T0 + 120_000 and not theirs:
            theirs.update(owner.stop_close(DOGE, "SELL", 0.15, 10.0, client_id="pbOther"))
            raise ValueError("an unexpected reply")
    d = TB.ToobitDrill(c, symbol=DOGE, wait=wait, trigger_wait_s=600, elapsed=lambda: clock.t / 1000)
    assert not TB.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert fake.amt(DOGE) == 0 and [o["orderId"] for o in fake.stops(DOGE)] == [theirs["algoId"]]
    steps = {r["step"]: r for r in d.log}
    assert not steps["정리 후 상태"]["ok"] and steps["정리 후 상태"]["detail"]["stops"] == 1


def test_leave_flat_keeps_the_stop_while_the_position_is_open():
    c, fake, clock = make()
    ready(c, (DOGE,))
    fake.prices[DOGE] = 1.0
    c.market(DOGE, "BUY", 100.0, client_id="pbE")
    st = place_stop(c, DOGE, "SELL", 0.9, 100.0, client_id="pbS")
    fake.fail("POST", ORDER, "drop_before")
    log = []
    TB.leave_flat(c, DOGE, lambda step, ok, detail: log.append((step, ok)), 1, 100.0)
    assert fake.amt(DOGE) == 100 and [t["orderId"] for t in fake.live_stops(DOGE)] == [st["algoId"]]
    assert ("정리 후 상태", False) in log and any(s.startswith("정리: 포지션이 남아") for s, _ in log)
    log.clear()
    TB.leave_flat(c, DOGE, lambda step, ok, detail: log.append((step, ok)), 1, 100.0)     # once more: closed
    assert fake.amt(DOGE) == 0 and not fake.stops(DOGE) and log == [("정리 후 상태", True)]


def test_a_drill_whose_close_a_resting_stop_locks_fails_and_still_ends_flat():
    """If a resting STOP locks the position's closable quantity, the half close is refused (the drill's [FAIL] says so);
    the clean-up cancels the drill's own stops, closes at once, and leaves nothing."""
    c, fake, clock = drill_world()
    fake.locks_close = True
    lines = []
    d = TB.ToobitDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000,
                       say=lines.append)
    assert not TB.run_drill(c, d, "drill", True, pause=lambda s: None)
    steps = {r["step"]: r for r in d.log}
    assert "-2010" in steps["멈춤"]["detail"] and any(k.startswith("정리: 청산이 거절됨") for k in steps)
    assert steps["정리 후 상태"]["ok"] and fake.amt(DOGE) == 0 and not fake.stops(DOGE)


def test_leave_flat_puts_the_stops_back_when_the_close_is_refused_again():
    c, fake, clock = make()
    fake.locks_close = True
    ready(c, (DOGE,))
    fake.prices[DOGE] = 1.0
    c.market(DOGE, "BUY", 100.0, client_id="pbE")
    place_stop(c, DOGE, "SELL", 0.9, 100.0, client_id="pbS")
    fake.fail("POST", ORDER, ("err", 400, -2010, "NEW_ORDER_REJECTED"), times=2)
    log = []
    TB.leave_flat(c, DOGE, lambda step, ok, detail: log.append((step, ok)), 1, 100.0)
    assert fake.amt(DOGE) == 100 and len(fake.live_stops(DOGE)) == 1     # never left without its stop
    assert any(s.startswith("정리: 포지션 닫기 실패") for s, _ in log) and ("정리 후 상태", False) in log


def test_drill_stops_when_two_stops_cannot_rest_at_once_and_leaves_flat():
    c, fake, clock = drill_world()
    fake.two_stops = False
    d = TB.ToobitDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000)
    assert not TB.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert fake.amt(DOGE) == 0 and not fake.stops(DOGE)


def test_a_drill_with_the_close_words_read_the_other_way_fails_and_keeps_its_stop():
    """The side words the other way round: the half close is refused (never a flip) and so is the clean-up's close;
    the position keeps its stop and the owners are told to look in the app."""
    c, fake, clock = drill_world()
    fake.close_words = "swapped"
    d = TB.ToobitDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000)
    assert not TB.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert fake.amt(DOGE) == 60 and not [k for k in fake.pos if k[1] == "SHORT"]
    assert len(fake.stops(DOGE)) >= 1 and not [r for r in d.log if r["step"] == "정리 후 상태" and r["ok"]]


def test_the_cli_specs_needs_no_key(monkeypatch, capsys):
    fake = FakeToobit()
    fake.clock = Clock()
    real = TB.ToobitClient

    def public(*a, **k):
        return real("", "", public_only=True, send=fake, clock_ms=fake.clock, sleep=lambda s: None)
    monkeypatch.setattr(TB, "public_client", public)
    monkeypatch.delenv("TOOBIT_LIVE_KEY", raising=False)
    assert TB.main(["specs"]) == 0
    out = capsys.readouterr().out
    assert "BTCUSDT: 상태 Trading" in out and "DOGEUSDT" in out and "요청 한도" in out
    assert TB.main(["check"]) == 2                             # no key in the environment: refused, nothing sent


# ------------------------------------------------------------------ the executor, whole cycle
class Source:
    def __init__(self, clock):
        self.clock, self.intent, self.ts = clock, None, None

    def read(self):
        return self.intent, (self.ts if self.ts is not None else self.clock() - 30_000)


class World:
    def __init__(self, tmp_path, fake=None, advance=False, env=None, **cfg_kw):
        self.clock = Clock()
        self.fake = fake or FakeToobit(wallet=10_000.0)
        self.fake.clock = self.clock
        self.src = Source(self.clock)
        self.note = ListNotifier()
        risk = R.RiskConfig(daily_max_loss_usd=500.0, max_drawdown_pct=0.2, max_consecutive_losses=3, max_leverage=40,
                            max_notional_usd=1_000.0, allowed_symbols=(BTC, ETH),
                            kill_file=str(tmp_path / "STOP"))
        self.cfg = ExecConfig(account="V39_ALL@1h", paper_db=str(tmp_path / "paper3.db"),
                              db=str(tmp_path / "executor-toobit-live.db"), qty_scale=1.0, risk=risk, retries=4,
                              sweep_every=1, exchange="toobit", mode="mainnet", budget_usd=10_000.0,
                              paper_env_file=str(tmp_path / "live.env"), **cfg_kw)
        self.store = ExecStore(self.cfg.db)
        kw = dict(send=self.fake, clock_ms=self.clock, sleep=lambda s: None)
        self.client = TB.ToobitClient("tk", "ts", **{**kw, "sleep": ticking(self.clock) if advance else kw["sleep"]})
        self.keycheck = TB.ToobitKeyCheckClient("tk", "ts", attested=True, **kw)
        self.ex = Executor(self.cfg, self.client, self.src, self.store, self.note, now_ms=self.clock,
                           sleep=lambda s: None, keycheck=self.keycheck, env=dict(env or LIVE_ENV))
        self.ex.start()

    def loop(self, n=1):
        for _ in range(n):
            self.clock.t += 3_000
            self.ex.loop_once()

    def paper(self, stop, side=1, qty=5.0, lev=20, entry=100.0, symbol=BTC):
        et = self.src.intent.entry_time if self.src.intent else self.clock.t - 60_000
        self.src.intent = Intent(key=f"V39_ALL@1h|{symbol}|{et}", symbol=symbol, side=side, qty=qty, leverage=lev,
                                 stop=stop, entry_price=entry, entry_time=et)

    def stops(self, symbol=BTC):
        ct = float(SPECS[symbol]["ct"])
        return [(float(t["stopPrice"]), float(t["origQty"]) * ct) for t in self.fake.live_stops(symbol)]

    def kinds(self):
        return [k for (k,) in self.store.conn.execute("SELECT kind FROM events")]


def test_executor_config_problems():
    risk = R.RiskConfig(max_leverage=40, allowed_symbols=(BTC,), kill_file="/var/lib/paperbot/STOP")
    cfg = ExecConfig(account="A@b", paper_db="p", db="/var/lib/paperbot/exec/x.db", qty_scale=1.0, exchange="toobit",
                     mode="testnet", budget_usd=100.0, risk=risk)
    assert any("투비트에는 테스트넷이 없습니다" in p for p in cfg.problems())
    cfg = ExecConfig(account="A@b", paper_db="p", db="/var/lib/paperbot/exec/x.db", qty_scale=1.0, exchange="toobit",
                     mode="mainnet", budget_usd=100.0, risk=risk,
                     net_costs={"toobit": {"taker_fee": 0.0006, "slippage": 0.0002}})
    assert not [p for p in cfg.problems() if "net_costs" in p or "exchange" in p or "투비트" in p]
    cfg = ExecConfig(account="A@b", paper_db="p", db="/var/lib/paperbot/exec/x.db", qty_scale=1.0, exchange="kraken",
                     mode="mainnet", budget_usd=100.0, risk=risk)
    assert any('"toobit"' in p for p in cfg.problems())
    from paperbot import executor as E
    assert "toobit" in E.EXCHANGES and E.EX_KO["toobit"] == "투비트"
    assert E.NET_COSTS["toobit"] == {"taker_fee": 0.0006, "slippage": 0.0002}
    assert E._prefixes("toobit") == {"mainnet": "[투비트 실거래 실행기]"}
    assert E.KEY_NAMES["toobit"] == ("TOOBIT_LIVE_KEY", "TOOBIT_LIVE_SECRET")
    assert E.foreign_keys("wooxpro", {"TOOBIT_LIVE_KEY": "x"}) == ["TOOBIT_LIVE_KEY"]
    assert E.foreign_keys("toobit", dict(LIVE_ENV)) == []
    c, kc = E._clients(ExecConfig(account="A@b", paper_db="p", db="x.db", qty_scale=1.0, exchange="toobit",
                                  mode="mainnet", budget_usd=100.0, risk=risk), env=dict(LIVE_ENV))
    assert type(c) is TB.ToobitClient and isinstance(kc, TB.ToobitKeyCheckClient)


def test_the_executor_refuses_testnet_and_a_wrong_client(tmp_path):
    w = World(tmp_path)
    store2 = ExecStore(str(tmp_path / "t.db"))
    cfg = ExecConfig(**{**w.cfg.__dict__, "mode": "testnet", "db": str(tmp_path / "t.db")})
    with pytest.raises(Refused):
        Executor(cfg, w.client, w.src, store2, w.note, now_ms=w.clock, sleep=lambda s: None, keycheck=w.keycheck,
                 env=dict(LIVE_ENV))
    store3 = ExecStore(str(tmp_path / "u.db"))
    cfg = ExecConfig(**{**w.cfg.__dict__, "db": str(tmp_path / "u.db")})
    with pytest.raises(Refused):
        Executor(cfg, w.keycheck, w.src, store3, w.note, now_ms=w.clock, sleep=lambda s: None, keycheck=w.keycheck,
                 env=dict(LIVE_ENV))
    with pytest.raises(Refused, match=TB.KEY_CHECKED):
        Executor(cfg, w.client, w.src, store3, w.note, now_ms=w.clock, sleep=lambda s: None, keycheck=w.keycheck,
                 env={k: v for k, v in LIVE_ENV.items() if k != TB.KEY_CHECKED})


def test_an_own_keys_executor_refuses_another_exchanges_key_in_its_file(tmp_path):
    w = World(tmp_path, own_keys=True)                         # its own key file: only TOOBIT_* there
    assert w.store.get_state("key_tie")["exchange"] == "toobit"
    store2 = ExecStore(str(tmp_path / "v.db"))
    cfg = ExecConfig(**{**w.cfg.__dict__, "db": str(tmp_path / "v.db")})
    from paperbot.executor import KeyMixup
    with pytest.raises(KeyMixup, match="DEEPCOIN_LIVE_KEY"):
        Executor(cfg, w.client, w.src, store2, w.note, now_ms=w.clock, sleep=lambda s: None, keycheck=w.keycheck,
                 env={**LIVE_ENV, "DEEPCOIN_LIVE_KEY": "dk"})


def test_executor_entry_stop_lock_steps_and_exit_from_fills(tmp_path):
    w = World(tmp_path)
    assert w.fake.levs[BTC] == {"leverage": 40, "marginType": "ISOLATED"} and w.fake.levs[ETH]["leverage"] == 30
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)]
    assert w.fake.levs[BTC]["leverage"] == 20                       # the paper's leverage
    assert w.ex.prefix == "[투비트 실거래 실행기]" and w.store.get_state("meta")["exchange"] == "toobit"
    entry = w.fake.order_bodies[0]
    assert entry["newClientOrderId"] == f"pb{w.ex.trade['base']}e" and entry["side"] == "BUY_OPEN"
    for price, lock in [(105.0, 101.1), (109.0, 104.9), (113.0, 109.3)]:
        w.fake.set_price(BTC, price)
        w.paper(stop=lock)
        w.loop()
        assert w.stops() == [(lock, 5.0)], (price, lock)
    assert not w.fake.unprotected()
    assert all(len(b["newClientOrderId"]) <= 32 for b in w.fake.order_bodies + w.fake.stop_bodies)
    assert len(w.fake.stop_bodies) == 4
    w.fake.add_funding(BTC, -1.25)
    w.src.intent = None                                               # paper exit
    w.loop(2)
    assert w.fake.amt(BTC) == 0 and not w.fake.live_stops(BTC) and w.ex.trade is None
    pnl, source = w.store.conn.execute("SELECT pnl, pnl_source FROM trades").fetchone()
    assert source == "fills" and pnl == pytest.approx(w.fake.wallet - 10_000.0, abs=1e-6)


@pytest.mark.parametrize("own_fills", [False, True])
def test_executor_books_a_stop_that_fired_on_the_exchange(tmp_path, own_fills):
    w = World(tmp_path)
    w.fake.own_fills = own_fills
    w.paper(stop=95.0)
    w.loop()
    w.clock.t += 10_000
    w.fake.set_price(BTC, 94.0)                                       # the exchange stop fires
    w.loop(3)
    assert w.fake.amt(BTC) == 0 and w.ex.trade is None
    reason, source, pnl = w.store.conn.execute("SELECT exit_reason, pnl_source, pnl FROM trades").fetchone()
    assert "손절" in reason and source == "fills" and pnl == pytest.approx(w.fake.wallet - 10_000.0, abs=1e-6)


def test_executor_sizes_its_entry_from_the_live_balance(tmp_path):
    """The template's ``size_from: "equity"``: 40 % of the Toobit equity as margin at the paper's leverage."""
    w = World(tmp_path, fake=FakeToobit(wallet=50.0), size_from="equity", margin_frac=0.4)
    w.paper(stop=95.0, qty=5.0, lev=20)                               # $50 x 40 % x 20 / $100 = 4 BTC
    w.loop()
    assert w.fake.amt(BTC) == pytest.approx(4.0) and w.stops() == [(95.0, 4.0)]


def test_executor_finds_an_entry_whose_answer_was_lost_by_its_client_id(tmp_path):
    w = World(tmp_path)
    w.fake.fail("POST", ORDER, "drop_after")
    w.paper(stop=95.0)
    w.loop()                                       # the answer is lost: Guarded looks it up by its client id
    assert w.ex.trade["status"] == "open" and w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)]
    assert len(orders(w.fake)) == 1


@UNKNOWN_IDS
def test_executor_adopts_an_entry_whose_record_lags_and_never_sends_it_twice(tmp_path, unknown_ids):
    w = World(tmp_path)
    w.fake.order_lag_ms, w.fake.unknown_ids = 10_000, unknown_ids
    w.fake.fail("POST", ORDER, "drop_after")
    w.paper(stop=95.0)
    w.loop()                                       # not visible yet: unknown, never resent
    assert w.ex.trade["status"] == "entering" and w.fake.amt(BTC) == 5
    w.loop()                                       # the reconcile adopts and protects it
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)]
    assert len(orders(w.fake)) == 1 and not w.fake.unprotected()


def test_executor_keeps_a_position_whose_new_stop_the_list_shows_late(tmp_path):
    w = World(tmp_path, advance=True)
    w.fake.stop_lag_ms = 2_000
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.amt(BTC) == 5 and w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)]
    w.loop(3)
    assert "protect_failed" not in w.kinds() and "no_stop" not in w.kinds()
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)] and not w.fake.unprotected()


def test_executor_keeps_the_old_stop_when_the_new_one_is_cancelled_by_the_exchange(tmp_path):
    w = World(tmp_path, advance=True)
    w.paper(stop=95.0)
    w.loop()
    assert w.stops() == [(95.0, 5.0)]
    w.fake.kill_new_stops = True
    w.fake.set_price(BTC, 105.0)
    w.paper(stop=101.1)
    w.loop()
    assert "move_failed" in w.kinds() and "protect_failed" not in w.kinds()
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)] and not w.fake.unprotected()


def test_executor_keeps_one_stop_after_a_429_that_ran(tmp_path):
    w = World(tmp_path, advance=True)
    w.fake.stop_lag_ms = 3_000
    real, seen = w.fake._stop, []

    def place(q, s, closing):                        # the first stop: it ran, the answer says 429
        out = real(q, s, closing)
        if not seen:
            seen.append(1)
            return 429, b'{"code":-1003,"msg":"Too many requests."}', {"Retry-After": "1"}
        return out
    w.fake._stop = place
    w.paper(stop=95.0)
    w.loop(2)
    assert "protect_failed" not in w.kinds() and "no_stop" not in w.kinds()
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)] and not w.fake.unprotected()


def test_executor_closes_a_position_whose_stop_stays_throttled(tmp_path):
    w = World(tmp_path, advance=True)
    real, seen = w.fake._stop, []

    def place(q, s, closing):
        if not seen:
            seen.append(1)
            return 429, b'{"code":-1003,"msg":"Too many requests."}', {"Retry-After": "60"}
        return real(q, s, closing)
    w.fake._stop = place
    w.paper(stop=95.0)
    t0 = w.clock.t
    w.loop()
    assert "protect_failed" in w.kinds() and w.fake.amt(BTC) == 0 and not w.fake.live_stops(BTC)
    assert w.clock.t - t0 <= 3_000 + 2 * TB.PROTECT_WAIT_S * 1000


def test_executor_closes_an_unknown_position_and_cancels_stray_stops(tmp_path):
    w = World(tmp_path)
    other = TB.ToobitClient("tk", "ts", send=w.fake, clock_ms=w.clock, sleep=lambda s: None)
    other.one_side = True
    other.market(ETH, "SELL", 1.0, client_id="pbHand")        # a position opened by hand
    w.loop()
    assert w.fake.amt(ETH) == 0 and "unknown_position" in w.kinds()
    w.paper(stop=95.0)
    w.loop()
    st = other.stop_close(BTC, "SELL", 90.0, 5.0, client_id="pbHandStop")
    w.src.intent = None
    w.loop(2)
    assert w.fake.amt(BTC) == 0 and not w.fake.live_stops(BTC) and st["algoId"]


@pytest.mark.parametrize("kind", [("err_after", 400, -1006, "Execution status unknown."), "403_after",
                                  ("err_after", 400, -9999, "Order expired: matching engine timeout")])
def test_executor_keeps_and_protects_an_entry_that_ran_but_was_answered_otherwise(tmp_path, kind):
    w = World(tmp_path)
    w.fake.order_lag_ms = 10_000
    w.fake.fail("POST", ORDER, kind)
    w.paper(stop=95.0)
    w.loop()                                                   # unknown: never resent, never refused
    assert w.fake.amt(BTC) == 5 and len(orders(w.fake)) == 1 and "entry_refused" not in w.kinds()
    w.loop()                                                   # the reconcile adopts and protects it
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)] and not w.fake.unprotected()
    assert len(orders(w.fake)) == 1 and w.fake.amt(BTC) == 5


def test_executor_drops_an_entry_whose_checks_before_the_send_keep_failing(tmp_path):
    w = World(tmp_path)
    w.fake.fail("GET", ORDER, "503_before", times=10 ** 6)
    w.paper(stop=95.0)
    w.loop()
    assert w.ex.trade is None and "entry_refused" in w.kinds() and "entry_unknown" not in w.kinds()
    assert not orders(w.fake) and w.fake.amt(BTC) == 0


def test_executor_never_adds_stops_or_closes_when_the_stop_list_cannot_be_read(tmp_path):
    w = World(tmp_path)
    w.paper(stop=95.0)
    w.loop()
    real = w.fake._listed
    w.fake._listed = lambda o: {**real(o), "side": ""} if o["type"] == "STOP" else real(o)
    for _ in range(3):
        with pytest.raises(TransientError):                   # the loop's read fails (Executor.run logs, goes on)
            w.loop()
    assert w.fake.amt(BTC) == 5 and len(w.fake.live_stops(BTC)) == 1 and len(stops_sent(w.fake)) == 1
    assert "no_stop" not in w.kinds() and "protect_failed" not in w.kinds()
    w.fake._listed = real
    w.loop()
    assert w.stops() == [(95.0, 5.0)] and w.ex.trade["status"] == "open"


def test_executor_starts_and_trades_when_one_coins_leverage_cannot_be_set(tmp_path):
    fake = FakeToobit(wallet=10_000.0)
    real = fake._route

    def refuse_eth(m, p, q):
        if p == "/api/v1/futures/leverage" and q.get("symbol") == "ETH-SWAP-USDT":
            return 400, b'{"code":-1130,"msg":"Data sent for paramter \'leverage\' is not valid."}', {}
        return real(m, p, q)
    fake._route = refuse_eth
    w = World(tmp_path, fake=fake)                             # no Refused: it starts
    assert ETH in w.client.lev_problems and "margin_refused" not in w.kinds()
    et = w.clock.t - 60_000
    w.src.intent = Intent(key=f"V39_ALL@1h|{ETH}|{et}", symbol=ETH, side=1, qty=0.5, leverage=25, stop=95.0,
                          entry_price=100.0, entry_time=et)       # 25x must be set (the coin stands at 20x)
    w.loop()
    assert w.fake.amt(ETH) == 0 and "leverage_refused" in w.kinds() and not orders(w.fake)
    w.src.intent = None
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)]


def test_executor_resizes_a_stop_bigger_than_the_position_so_that_it_can_fire(tmp_path):
    """The fake refuses a firing STOP bigger than the position as a whole (``oversize`` "refuse")."""
    w = World(tmp_path)
    w.paper(stop=95.0)
    w.loop()
    other = TB.ToobitClient("tk", "ts", send=w.fake, clock_ms=w.clock, sleep=lambda s: None)
    other.market(BTC, "SELL", 2.0, reduce_only=True, client_id="pbHandCut")      # part closed by hand
    w.loop(2)
    assert w.fake.amt(BTC) == 3 and w.stops() == [(95.0, 3.0)]
    w.clock.t += 10_000
    w.fake.set_price(BTC, 94.0)
    assert w.fake.amt(BTC) == 0


def test_executor_follows_the_exit_next_to_odd_stop_rows(tmp_path):
    """A garbled STOP row on a coin without a position and an opening STOP on the traded coin never stop the loop's
    sweep (the lock steps and the paper exit go on)."""
    w = World(tmp_path)
    w.paper(stop=95.0)
    w.loop()
    odd = [{"orderId": "902", "symbol": "ETH-SWAP-USDT", "type": "STOP", "side": "", "status": "ORDER_NEW",
            "origQty": "1", "stopPrice": "x", "clientOrderId": ""},
           {"orderId": "901", "symbol": "BTC-SWAP-USDT", "type": "STOP", "side": "BUY_OPEN", "status": "ORDER_NEW",
            "origQty": "5", "stopPrice": "120", "clientOrderId": "byHand", "time": str(T0)}]
    real = w.fake._route

    def with_odd(m, p, q):
        st, raw, h = real(m, p, q)
        if (m, p) == ("GET", OPEN) and q.get("type") == "STOP" and st == 200:
            raw = json.dumps(json.loads(raw) + [r for r in odd if r["symbol"] == q["symbol"]]).encode()
        return st, raw, h
    w.fake._route = with_odd
    w.fake.set_price(BTC, 105.0)
    w.paper(stop=101.1)
    w.loop()
    assert w.stops() == [(101.1, 5.0)] and "reconcile_failed" not in w.kinds()
    w.src.intent = None
    w.loop(2)
    assert w.fake.amt(BTC) == 0 and w.ex.trade is None and not w.fake.live_stops(BTC)


def test_executor_preflight_lines(tmp_path):
    from paperbot import executor as E
    w = World(tmp_path)
    out = []
    E.preflight(w.cfg, w.client, w.keycheck, out=out.append, env=dict(LIVE_ENV))
    text = "\n".join(out)
    assert "주소 api.toobit.com (mainnet)" in text and "한 코인에 한쪽만" in text and "BTCUSDT: 상태 Trading" in text
    assert "투비트는 키 권한을 API로 알려 주지 않습니다" in text


def test_dataclass_fields_unchanged_for_other_exchanges():
    """The executor's config keeps its fields; the template uses known ones only (its opt-in ones of 10-25 night,
    leverage_by_symbol, stop_scale, liq_guard, liq_guard_mmr, are ExecConfig fields too)."""
    names = {f.name for f in dataclasses.fields(ExecConfig)}
    raw = json.loads((ROOT / "deploy" / "executor.live-toobit.json").read_text(encoding="utf-8"))
    assert set(raw) <= names


# ================================================================ review 10-25: a position row's name never reads as flat
def _rename_positions(fake, rename):
    real = fake._route

    def route(m, p, q):
        st, raw, h = real(m, p, q)
        if (m, p) == ("GET", "/api/v1/futures/positions") and st == 200:
            rows = json.loads(raw)
            for r in rows:
                r["symbol"] = rename(r["symbol"])
            raw = json.dumps(rows).encode()
        return st, raw, h
    fake._route = route


def test_a_position_row_named_plainly_reads_and_an_unknown_name_is_an_error():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    _rename_positions(fake, lambda s: s.replace("-SWAP-USDT", "USDT"))       # "BTCUSDT", as other answers name it
    assert float(c.position(BTC)["positionAmt"]) == 5 and [p["symbol"] for p in c.positions()] == [BTC]
    c2, fake2, _ = make()
    ready(c2)
    c2.market(BTC, "BUY", 5.0, client_id="pbE")
    _rename_positions(fake2, lambda s: "BTC/USDT:PERP")                     # a name the client cannot place
    with pytest.raises(TB.TransientError, match="코인 이름을 읽지 못했습니다"):
        c2.position(BTC)
    c3, fake3, _ = make()
    ready(c3)
    c3.market(BTC, "BUY", 5.0, client_id="pbE")
    _rename_positions(fake3, lambda s: "BTC-SWAP")                          # the coin-margined product: not ours
    assert float(c3.position(BTC)["positionAmt"]) == 0


def test_a_filled_entry_without_a_readable_position_is_never_dropped(tmp_path):
    """The entry's own record says FILLED but the position reads flat (a misread): the trade stays 'entering' (no new
    entry, never 'not filled'), with a CRITICAL alert, instead of leaving a real position without its stop."""
    w = World(tmp_path)
    real = w.fake._route

    def route(m, p, q):
        st, raw, h = real(m, p, q)
        if (m, p) == ("GET", "/api/v1/futures/positions") and st == 200:
            raw = b"[]"
        return st, raw, h
    w.fake._route = route
    w.paper(stop=95.0)
    for _ in range(40):
        w.loop()
    assert w.fake.amt(BTC) == 5 and w.ex.trade is not None and w.ex.trade["status"] == "entering"
    kinds = w.kinds()
    assert "entry_filled_flat" in kinds and "recover" not in kinds and "entry_unfilled" not in kinds
    assert any("포지션이 안 보입니다" in t for _, t in w.note.messages)


def test_a_stop_row_with_a_status_we_do_not_know_never_covers_a_position():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    TB.place_stop(c, BTC, "SELL", 95.0, 5.0)
    assert len(c.open_algo_orders(BTC)) == 1
    real = fake._route

    def route(m, p, q):
        st, raw, h = real(m, p, q)
        if m == "GET" and p == "/api/v1/futures/openOrders" and st == 200:
            rows = json.loads(raw)
            for r in rows:
                r["status"] = "ORDER_SOMETHING_NEW"
            raw = json.dumps(rows).encode()
        return st, raw, h
    fake._route = route
    with pytest.raises(TB.TransientError, match="상태"):
        c.open_algo_orders(BTC)
