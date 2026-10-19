"""paperbot/mexc.py against the fake MEXC contract exchange (tests/fakemexc.py): signing, hosts, keys, the translation
into the Binance client's shapes (contracts <-> coins), error classes, the stop protocol, P&L, income and the drill.
No network."""

import hashlib
import hmac
import json
import os
import re
import socket
import urllib.parse
from decimal import Decimal

import pytest

from fakemexc import FakeMexc
from paperbot import mexc as MX
from paperbot.livepnl import trade_costs
from paperbot.mainnet import FLAG, FLAG_VALUE, Refused, check_permissions
from paperbot.testnet import (BAD_TIMESTAMP, NOT_FOUND, RateLimited, TestnetError, TransientError, covers,
                              live_stops, move_stop, place_stop)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = 1_800_000_000_000
BTC = "BTCUSDT"
B = "BTC_USDT"
LIVE = {FLAG: FLAG_VALUE, "MEXC_LIVE_KEY": "mk", "MEXC_LIVE_SECRET": "ms"}


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


def client(fake=None, clock=None, cls=MX.MexcClient, **kw):
    fake = fake or FakeMexc()
    clock = clock or Clock()
    fake.clock = clock
    return cls("mk", "ms", send=fake, clock_ms=clock, sleep=lambda s: None, **kw), fake


def ready(c, lev=20, symbol=BTC):
    c.one_way()
    c.leverage(symbol, lev)
    return c


# ------------------------------------------------------------------ transport: hosts, signing, errors
def test_hosts_are_allowlisted():
    for base in ("https://api.mexc.com.evil.io", "http://api.mexc.com", "https://contract.mexc.com/api",
                 "https://api.mexc.com:8443", "https://futures.mexc.com", "https://api.bybit.com"):
        with pytest.raises(ValueError):
            MX.MexcClient("k", "s", base=base)
    assert MX.MexcClient("k", "s").host == "api.mexc.com"                  # ccxt 4.5.88's contract host
    assert MX.MexcClient("k", "s", base="https://contract.mexc.com").host == "contract.mexc.com"   # MEXC's v1 docs
    with pytest.raises(ValueError):
        MX.MexcClient("", "")
    with pytest.raises(ValueError):
        MX.MexcClient("k", "s", market_type=1)                             # only market types


def test_signature_vector_built_from_the_documented_formula():
    """MEXC contract docs: Signature = hex HMAC-SHA256(secret, accessKey + Request-Time + parameter string); GET: the
    parameters sorted by name, '&'-joined, URL-encoded; POST: the JSON body as sent."""
    key, secret, t = "mx0vglTESTKEY", "TESTSECRET123", "1700000000000"
    params = {"symbol": "BTC_USDT", "page_size": 100, "page_num": 1, "states": "1,2", "side": None}
    target = "mx0vglTESTKEY1700000000000page_num=1&page_size=100&states=1%2C2&symbol=BTC_USDT"
    want = hmac.new(b"TESTSECRET123", target.encode("utf-8"), hashlib.sha256).hexdigest()
    assert MX.query_string(params) == "page_num=1&page_size=100&states=1%2C2&symbol=BTC_USDT"
    assert MX.signature(secret, key, t, MX.query_string(params)) == want
    body = {"symbol": "BTC_USDT", "vol": 1, "side": 1}
    assert MX.body_string(body) == '{"symbol":"BTC_USDT","vol":1,"side":1}'          # not sorted, compact
    want_post = hmac.new(b"TESTSECRET123", (key + t + '{"symbol":"BTC_USDT","vol":1,"side":1}').encode(),
                         hashlib.sha256).hexdigest()
    assert MX.signature(secret, key, t, MX.body_string(body)) == want_post


def test_requests_carry_the_headers_and_are_sent_exactly_as_signed():
    seen = []
    c, fake = client()

    def spy(method, url, headers, body):
        seen.append((method, url, dict(headers), body))
        return fake(method, url, headers, body)
    c.send = spy
    c.sync_time()
    c.position(BTC)
    ready(c)
    c.market(BTC, "BUY", 0.0012, client_id="pbe1")
    m, url, h, body = seen[1]
    q = url.split("?", 1)[1]
    assert q == "symbol=BTC_USDT" and url.startswith("https://api.mexc.com/api/v1/private/position/open_positions")
    want = hmac.new(b"ms", ("mk" + h["Request-Time"] + q).encode(), hashlib.sha256).hexdigest()
    assert h["Signature"] == want and h["ApiKey"] == "mk" and h["Content-Type"] == "application/json"
    assert "Signature" not in seen[0][2] and "ApiKey" not in seen[0][2]   # public endpoints are not signed
    m, url, h, body = next(x for x in seen if x[1].endswith("/order/create"))
    assert json.loads(body) == {"symbol": B, "vol": 12, "side": 1, "type": 5, "openType": 1, "leverage": 20,
                                "externalOid": "pbe1"}
    assert h["Signature"] == hmac.new(b"ms", ("mk" + h["Request-Time"]).encode() + body, hashlib.sha256).hexdigest()
    bad = MX.MexcClient("mk", "wrong", send=fake, clock_ms=Clock())
    with pytest.raises(TestnetError) as e:                                 # 602: a refusal, not retried
        bad.position(BTC)
    assert e.value.code == 602 and not isinstance(e.value, TransientError)


def test_clock_offset_and_the_request_time_window():
    c, fake = client()
    fake.skew = 12_000                                                     # MEXC is 12 s ahead: outside 10 s
    with pytest.raises(TestnetError) as e:
        c.position(BTC)
    assert e.value.code == BAD_TIMESTAMP                                   # 513: the executor re-syncs and resends
    assert c.sync_time() == 12_000 and float(c.position(BTC)["positionAmt"]) == 0
    fake.ping_str = False                                                  # the time as a number works too
    assert c.sync_time() == 12_000


def test_error_classes():
    c, fake = client()
    P = "/api/v1/private/position/open_positions"
    fake.fail("GET", P, "drop_before")
    with pytest.raises(TransientError):
        c.position(BTC)
    fake.fail("GET", P, "503_before")
    with pytest.raises(TransientError) as e:
        c.position(BTC)
    assert e.value.status == 503
    fake.fail("GET", P, "429")
    with pytest.raises(RateLimited) as e:
        c.position(BTC)
    assert e.value.status == 429 and e.value.retry_after == 2.0
    for code in (510, 2037):
        fake.fail("GET", P, ("ret", code, "Excessive frequency of requests"))
        with pytest.raises(RateLimited):
            c.position(BTC)
    fake.fail("GET", P, "403")
    with pytest.raises(RateLimited) as e:
        c.position(BTC)
    assert e.value.status == 418 and e.value.retry_after >= 300           # a block: the loop waits, no retries
    for code in (9999, 500, 501, 504):
        fake.fail("GET", P, ("ret", code, "System busy"))
        with pytest.raises(TransientError):
            c.position(BTC)
    for code in (401, 406, 701, 1001):
        fake.fail("GET", P, ("ret", code, "Unauthorized"))
        with pytest.raises(TestnetError) as e:
            c.position(BTC)
        assert e.value.code == code and not isinstance(e.value, TransientError)
    fake.fail("GET", P, ("ret", 603, "Repeated requests"))
    fake.skew = 3_000
    with pytest.raises(TransientError):                                    # outcome looked up, clock re-synced
        c.position(BTC)
    assert c.offset_ms == 3_000
    c.send = lambda *a: (200, b"<html>maintenance</html>", {})            # a 200 that is not a MEXC answer: unknown
    with pytest.raises(TransientError):
        c.position(BTC)
    c.send = lambda *a: (200, json.dumps({"success": False, "code": 0}).encode(), {})
    with pytest.raises(TransientError):
        c.position(BTC)


def test_a_garbled_or_empty_answer_is_never_flat_or_zero():
    c, fake = client()
    fake.null_positions = True
    with pytest.raises(TransientError):                                    # data null: never "flat"
        c.position(BTC)
    with pytest.raises(TransientError):
        c.positions()
    fake.null_positions = False
    c.send = lambda *a: (200, json.dumps({"success": True, "code": 0, "data": [
        {"symbol": B, "positionType": 1, "holdVol": "", "state": 1}]}).encode(), {})
    with pytest.raises(TransientError):                                    # nor from a missing size
        c.position(BTC)
    c.send = lambda *a: (200, json.dumps({"success": True, "code": 0, "data": [
        {"currency": "BTC", "equity": 0.1, "unrealized": 0}]}).encode(), {})
    with pytest.raises(TransientError):                                    # no USDT row: never $0 (a false halt)
        c.account()
    c.send = lambda *a: (200, json.dumps({"success": True, "code": 0, "data": None}).encode(), {})
    with pytest.raises(TransientError):                                    # a stop list that is not a list
        c.open_algo_orders(BTC)


def test_rate_limit_window_slows_the_next_request():
    clock = Clock()
    c, fake = client(clock=clock)
    c.position(BTC)
    assert c.throttle_s() == 0
    for _ in range(16):
        c.position(BTC)
    assert 0 < c.throttle_s() <= 2.0
    clock.t += 2_001
    assert c.throttle_s() == 0


# ------------------------------------------------------------------ units: contracts <-> coins, rounding
def test_spec_is_read_live_once_and_converts_contracts():
    c, fake = client()
    sp = c.spec(BTC)
    assert (sp["qty_step"], sp["min_qty"], sp["tick"], sp["max_leverage"]) == (0.0001, 0.0001, 0.1, 125.0)
    assert c.spec("DOGEUSDT")["qty_step"] == 100.0 and c.spec("SOLUSDT")["tick"] == 0.001
    details = [x for x in fake.calls if x[1] == "/api/v1/contract/detail"]
    assert len(details) == 1                                               # every contract in one read (1 / 5 s)
    with pytest.raises(TestnetError):
        c.spec("XRPUSDT")
    with pytest.raises(TestnetError):
        c.spec("BTCUSD")                                                   # coin-margined: not a USDT contract
    assert c._contracts(BTC, 0.00129) == Decimal(12)                       # floored to volUnit, never more
    assert c._contracts("DOGEUSDT", 1299.0) == Decimal(12)                 # 100 DOGE per contract
    assert c._contracts(BTC, 0.0003) == Decimal(3)                         # float noise does not lose a contract
    assert MX._price_str(95.1, "0.1") == "95.1" and MX._price_str(0.12345, "0.00001") == "0.12345"
    assert MX.mx("DOGEUSDT") == "DOGE_USDT" and MX.bn("DOGE_USDT") == "DOGEUSDT"


def test_orders_positions_and_fills_are_in_coins():
    c, fake = client()
    ready(c, symbol="DOGEUSDT")
    o = c.market("DOGEUSDT", "BUY", 1250.0)                                # 12 contracts of 100 DOGE
    assert next(q for m, p, q in fake.calls if p.endswith("/order/create"))["vol"] == 12
    assert o["origQty"] == "1200" and o["executedQty"] == "1200" and fake.pos["DOGE_USDT"] == 12
    assert c.position("DOGEUSDT")["positionAmt"] == "1200"
    fills = c.user_trades("DOGEUSDT", T0 - 1000, T0 + 1000)
    assert [(f["qty"], f["vol"], f["side"]) for f in fills] == [("1200", "12", "BUY")]
    with pytest.raises(TestnetError) as e:
        c.market("DOGEUSDT", "BUY", 99.0)                                  # less than one contract
    assert e.value.code == "QTY_ZERO"


def test_account_in_the_binance_shape_and_other_assets():
    c, fake = client()
    fake.wallet, fake.other = 520.0, {"MX": 3.0}
    a = c.account()
    assert a["totalWalletBalance"] == "520" and a["totalMarginBalance"] == "520"
    assert [x["asset"] for x in a["assets"]] == ["USDT", "MX"]
    ready(c)
    c.market(BTC, "SELL", 50.0)                                            # short 50 BTC at 100 (test sizes)
    fake.last[B] = 90.0
    a = c.account()                                                        # wallet = equity - unrealized
    assert float(a["totalMarginBalance"]) == pytest.approx(float(a["totalWalletBalance"]) + 500.0)
    assert c.position(BTC)["positionAmt"] == "-50" and c.position(BTC)["marginType"] == "isolated"
    assert [p["symbol"] for p in c.positions()] == [BTC]
    fake.bonus = 5.0
    assert {"asset": "BONUS", "walletBalance": "5"} in c.account()["assets"]


# ------------------------------------------------------------------ modes, margin, leverage
def test_one_way_mode_is_set_when_nothing_is_open_and_refused_otherwise():
    c, fake = client()
    fake.mode = 1
    c.one_way()
    assert fake.mode == 2
    c.one_way()                                                            # already one-way: nothing sent
    assert sum(1 for x in fake.calls if x[1].endswith("change_position_mode")) == 1
    fake.mode = 1
    fake.add_resting(B, 1, 1, 50.0)
    with pytest.raises(Refused) as e:                                      # hedge with an order open: no start
        c.one_way()
    assert "양방향" in str(e.value) and fake.mode == 1
    with pytest.raises(TestnetError) as e:                                 # and never an entry
        c.leverage(BTC, 20)
    assert e.value.code == "NOT_ONE_WAY"


def test_isolated_leverage_is_set_for_both_sides_and_read_back():
    c, fake = client()
    c.isolated(BTC)
    c.isolated("ETHUSDT")
    assert fake.levs[(B, 1)] == fake.levs[(B, 2)] == [1, 40]               # owners: BTC 40x
    assert fake.levs[("ETH_USDT", 1)] == fake.levs[("ETH_USDT", 2)] == [1, 30]   # the others 30x
    assert c.leverage(BTC, 20) == {"symbol": BTC, "leverage": 20, "marginType": "isolated"}
    assert fake.levs[(B, 1)] == [1, 20]
    with pytest.raises(TestnetError):
        c.leverage("SOLUSDT", 80)                                          # over the contract's max
    real = fake.route

    def lying(m, path, q):                                                 # answers ok but does not change it
        if path.endswith("change_leverage"):
            return 200, json.dumps({"success": True, "code": 0}).encode(), {}
        return real(m, path, q)
    fake.route = lying
    with pytest.raises(TestnetError) as e:
        c.leverage(BTC, 25)
    assert e.value.code == "LEVERAGE_MISMATCH"

    def with_cross_rows(m, path, q):                       # the answer also lists the cross settings: not used
        st, body, h = real(m, path, q)
        if path.endswith("/position/leverage"):
            d = json.loads(body)
            d["data"] = [{**r, "openType": 2, "leverage": 5} for r in d["data"]] + d["data"]
            body = json.dumps(d).encode()
        return st, body, h
    fake.route = with_cross_rows
    assert c.leverage(BTC, 30)["leverage"] == 30 and fake.levs[(B, 1)] == [1, 30]


def test_isolated_with_a_cross_position_warns_and_a_refusal_with_nothing_open_stops():
    c, fake = client()
    fake.pos[B], fake.entry[B], fake.pos_open[B] = Decimal(10), 100.0, 2
    with pytest.raises(TestnetError) as e:
        c.isolated(BTC)
    assert e.value.code == -4048                                           # the executor warns and keeps protecting
    c2, fake2 = client()
    fake2.fail("POST", "/api/v1/private/position/change_leverage", ("ret", 2006, "Leverage ratio error"), times=2)
    with pytest.raises(Refused):
        c2.isolated(BTC)


# ------------------------------------------------------------------ orders
def test_market_order_is_read_back_until_final():
    c, fake = client()
    ready(c)
    fake.market_lag = 2
    o = c.market(BTC, "BUY", 0.001, client_id="pbe1")
    assert o["status"] == "FILLED" and o["executedQty"] == "0.001" and float(o["avgPrice"]) == 100.0
    assert o["side"] == "BUY" and o["clientOrderId"] == "pbe1" and not o["reduceOnly"]
    assert c.order(BTC, client_id="pbe1")["orderId"] == o["orderId"]      # the look-up after a lost answer
    fake.market_lag = 9
    x = c.market(BTC, "SELL", 0.0005, reduce_only=True, client_id="pbx1")
    assert x["status"] == "NEW" and x["orderId"]                           # still uncompleted after the reads
    assert fake.pos[B] == 5
    body = next(q for m, p, q in reversed(fake.calls) if p.endswith("/order/create"))
    assert body["side"] == 4 and body["openType"] == 1 and body["leverage"] == 20   # close long: never opens
    for style in ("error", "null"):
        fake.not_found = style
        with pytest.raises(TestnetError) as e:
            c.order(BTC, client_id="nothere")
        assert e.value.code in NOT_FOUND
    fake.market_lag, fake.partial = 0, 0.6
    o = c.market(BTC, "BUY", 0.001)
    assert o["status"] == "CANCELED" and float(o["executedQty"]) == 0.0006  # rest cancelled: final, part filled


def test_a_short_closes_with_side_2_and_the_market_type_can_be_6():
    c, fake = client(market_type=6)
    ready(c)
    c.market(BTC, "SELL", 0.002)
    c.market(BTC, "BUY", 0.002, reduce_only=True)
    sides = [(q["side"], q["type"]) for m, p, q in fake.calls if p.endswith("/order/create")]
    assert sides == [(3, 6), (2, 6)] and fake.pos[B] == 0


def test_an_opening_orders_rate_limit_answer_is_an_unknown_outcome():
    c, fake = client()
    ready(c)
    fake.fail("POST", "/api/v1/private/order/create", ("ret", 510, "Excessive frequency of requests"))
    with pytest.raises(TransientError) as e:                               # looked up, never sent again
        c.market(BTC, "BUY", 0.001, client_id="pbe1")
    assert not isinstance(e.value, RateLimited)
    c.market(BTC, "BUY", 0.001)
    fake.fail("POST", "/api/v1/private/order/create", ("ret", 510, "Excessive frequency of requests"))
    with pytest.raises(RateLimited):                                       # a close: may be sent again (cannot open)
        c.market(BTC, "SELL", 0.001, reduce_only=True)


def test_an_order_path_that_does_not_exist_falls_back_once_to_order_submit():
    c, fake = client()
    ready(c)
    fake.fail("POST", "/api/v1/private/order/create", "404")              # not routed: nothing ran
    c.market(BTC, "BUY", 0.001)
    paths = [p for m, p, q in fake.calls if p.endswith(("/order/create", "/order/submit"))]
    assert paths == ["/api/v1/private/order/submit"] and fake.pos[B] > 0  # one order, on the other path
    c.market(BTC, "SELL", 0.001, reduce_only=True)                        # later orders go there directly
    assert [p for m, p, q in fake.calls if p.endswith(("/order/create", "/order/submit"))][-1].endswith("/order/submit")
    assert fake.pos[B] == 0


def test_an_order_answer_other_than_404_is_never_sent_to_the_other_path():
    c, fake = client()
    ready(c)
    fake.fail("POST", "/api/v1/private/order/create", "503_after")        # it may have run: never resent elsewhere
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 0.001, client_id="pbe2")
    assert not [p for m, p, q in fake.calls if p.endswith("/order/submit")]


def test_ext_ids():
    assert MX.ext_id("pb0123456789abs3r0a1b2c3d") == "pb0123456789abs3r0a1b2c3d"
    long = MX.ext_id("x" * 40)
    assert len(long) <= 32 and long == MX.ext_id("x" * 40)
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,32}", MX.ext_id("a.b/c"))
    assert MX.ext_id(None) != MX.ext_id(None) and len(MX.ext_id(None)) <= 32


# ------------------------------------------------------------------ stops (plan orders)
def test_stop_parameters_and_translation():
    c, fake = client()
    ready(c)
    c.market(BTC, "BUY", 0.002)
    s = c.stop_close(BTC, "SELL", 95.0, qty=0.002, client_id="pbs1")
    body = fake.calls[-1][2]
    assert body == {"symbol": B, "side": 4, "openType": 1, "leverage": 20, "vol": 20, "triggerPrice": "95",
                    "triggerType": 2, "executeCycle": 2, "orderType": 5, "trend": 1, "externalOid": "pbs1"}
    got = c.algo_order(algo_id=s["algoId"])
    assert got["orderType"] == "STOP_MARKET" and got["algoStatus"] == "NEW" and got["side"] == "SELL"
    assert got["workingType"] == "CONTRACT_PRICE" and got["quantity"] == "0.002" and got["executeCycle"] == 168
    assert covers(got, 0.002) and not covers(got, 0.003) and not covers(got, -0.002)
    assert got["refreshAt"] == got["createTime"] + 6 * 86_400_000
    assert c.algo_order(client_id="pbs1")["algoId"] == s["algoId"]
    assert [x["algoId"] for x in live_stops(c, BTC)] == [s["algoId"]]
    with pytest.raises(TestnetError) as e:
        c.stop_close(BTC, "SELL", 94.0, qty=0.00005)                       # less than a contract: refused, not 0
    assert e.value.code == "QTY_ZERO"
    tp = c._algo_dict({**fake._plan_view(fake.plans[s["algoId"]]), "triggerType": 1})
    assert tp["orderType"] == "TAKE_PROFIT_MARKET"                         # rises for a long: not a stop
    opening = c._algo_dict({**fake._plan_view(fake.plans[s["algoId"]]), "side": 1})
    assert opening["orderType"] == "CONDITIONAL" and not opening["reduceOnly"]
    c.market(BTC, "SELL", 0.004)                                           # flip: short 0.002 (test only)
    c.cancel_all_algo(BTC)
    s2 = c.stop_close(BTC, "BUY", 105.0, qty=0.002)
    assert fake.calls[-1][2]["side"] == 2 and fake.calls[-1][2]["triggerType"] == 1
    assert covers(c.algo_order(algo_id=s2["algoId"]), -0.002)


def test_a_stop_is_found_by_its_fingerprint_when_mexc_does_not_echo_the_id():
    c, fake = client()
    ready(c)
    c.market(BTC, "BUY", 0.002)
    fake.fail("POST", "/api/v1/private/planorder/place", "drop_after")     # placed, answer lost
    with pytest.raises(TransientError):
        c.stop_close(BTC, "SELL", 95.0, qty=0.002, client_id="pbs7")
    assert not fake.plan_ext
    found = c.algo_order(client_id="pbs7")                                 # side, trigger, contracts, created after
    assert found["algoId"] in fake.plans and found["clientAlgoId"] == "pbs7"
    other = MX.MexcClient("mk", "ms", send=fake, clock_ms=fake.clock)      # a restarted process: nothing to match
    with pytest.raises(TestnetError) as e:
        other.algo_order(client_id="pbs8")
    assert e.value.code in NOT_FOUND
    fake.plan_ext = True                                                   # echoed: found by the id itself
    assert other.algo_order(client_id="pbs7")["algoId"] == found["algoId"]


@pytest.mark.parametrize("past", ["refuse", "trigger"])
def test_a_stop_past_the_price(past):
    c, fake = client()
    fake.plan_past = past
    ready(c)
    c.market(BTC, "BUY", 0.002)
    s1 = place_stop(c, BTC, "SELL", 95.0, 0.002)
    fake.set_price(B, 98.0)
    res = move_stop(c, BTC, "SELL", 99.0, 0.002, [s1["algoId"]])
    if past == "refuse":                                                   # 3004 while past: the -2021 path
        assert res["result"] == "closed" and res["flat"] and "3004" in res["error"]
    else:                                                                  # MEXC executes it at once
        assert res["result"] == "triggered" and res["stop"]["algoStatus"] == "TRIGGERED"
    assert fake.pos[B] == 0
    c2, fake2 = client()
    ready(c2)
    c2.market(BTC, "BUY", 0.002)
    fake2.fail("POST", "/api/v1/private/planorder/place", ("ret", 600, "Param error!"))
    with pytest.raises(TestnetError) as e:                                 # another refusal, price not past
        c2.stop_close(BTC, "SELL", 95.0, qty=0.002)
    assert e.value.code == 600


def test_move_stop_new_first_then_cancel_and_cancel_codes():
    c, fake = client()
    ready(c)
    c.market(BTC, "BUY", 0.001)
    s1 = place_stop(c, BTC, "SELL", 95.0, 0.001)
    fake.fail("POST", "/api/v1/private/planorder/place", ("ret", 2036, "The orders more than the limit"))
    with pytest.raises(TestnetError):
        move_stop(c, BTC, "SELL", 97.0, 0.001, [s1["algoId"]])
    assert [p["id"] for p in fake.live_plans()] == [s1["algoId"]] and fake.covered(B)
    res = move_stop(c, BTC, "SELL", 97.0, 0.001, [s1["algoId"]])
    assert res["result"] == "moved" and [p["triggerPrice"] for p in fake.live_plans()] == [97.0]
    first = next(i for i, (m, p, q) in enumerate(fake.calls) if p.endswith("planorder/place"))
    assert not [t for t in fake.unprotected_moments(B) if t[0] > first]
    other = MX.MexcClient("mk", "ms", send=fake, clock_ms=fake.clock)      # a restarted process: no id -> symbol
    with pytest.raises(TestnetError) as e:
        other.cancel_algo(algo_id=s1["algoId"])                            # 2041: already cancelled
    assert e.value.code in NOT_FOUND
    with pytest.raises(TestnetError) as e:
        other.cancel_algo(algo_id="123")
    assert e.value.code in NOT_FOUND
    body = [q for m, p, q in fake.calls if p.endswith("planorder/cancel")][0]
    assert body == [{"symbol": B, "orderId": s1["algoId"]}]                # a JSON list, the id as a string


def test_a_triggered_stop_reads_as_fired_with_the_order_it_placed():
    c, fake = client()
    ready(c)
    c.market(BTC, "BUY", 0.001)
    s = c.stop_close(BTC, "SELL", 95.0, qty=0.001)
    fake.set_price(B, 94.0)
    o = c.algo_order(algo_id=s["algoId"])
    assert o["algoStatus"] == "TRIGGERED" and o["actualOrderId"] and fake.pos[B] == 0
    fills = c.user_trades(BTC, T0 - 1000, T0 + 1000)
    assert [f["orderId"] for f in fills if f["side"] == "SELL"] == [o["actualOrderId"]]


def test_a_stop_expires_after_its_cycle():
    clock = Clock()
    c, fake = client(clock=clock)
    ready(c)
    c.market(BTC, "BUY", 0.001)
    s = c.stop_close(BTC, "SELL", 95.0, qty=0.001)
    clock.t += 168 * 3_600_000
    assert c.algo_order(algo_id=s["algoId"])["algoStatus"] == "EXPIRED" and not live_stops(c, BTC)


def test_resting_orders_and_stops_are_listed_and_cancelled_separately():
    c, fake = client()
    ready(c)
    c.market(BTC, "BUY", 0.001)
    c.stop_close(BTC, "SELL", 95.0, qty=0.001)
    oid = fake.add_resting(B, 1, 5, 90.0)
    assert [o["orderId"] for o in c.open_orders(BTC)] == [oid]
    assert [o["orderType"] for o in c.open_algo_orders(BTC)] == ["STOP_MARKET"]
    c.cancel_all(BTC)
    assert not c.open_orders(BTC) and len(fake.live_plans(B)) == 1
    with pytest.raises(TestnetError) as e:
        c.cancel(BTC, oid)                                                 # already cancelled: 2041
    assert e.value.code == NOT_FOUND[1]


# ------------------------------------------------------------------ fills, P&L, funding, transfers
def scenario(fake, clock, c):
    ready(c)
    c.market(BTC, "BUY", 0.02)                                             # 200 contracts at 100
    clock.t += 1000
    fake.set_price(B, 110.0)
    c.market(BTC, "SELL", 0.005, reduce_only=True)                         # +0.05
    clock.t += 1000
    fake.set_price(B, 105.0)
    c.market(BTC, "SELL", 0.015, reduce_only=True)                         # +0.075
    return c.user_trades(BTC, T0 - 5000, clock.t + 5000)


@pytest.mark.parametrize("net", [False, True])
def test_realized_pnl_is_replayed_from_the_fills_and_checked_against_profit(net):
    clock = Clock()
    c, fake = client(clock=clock)
    fake.profit_net = net                                                  # the docs do not say: both pass
    fills = scenario(fake, clock, c)
    assert [f["realizedSource"] for f in fills] == ["open", "replay", "replay"]
    assert [round(float(f["realizedPnl"]), 9) for f in fills] == [0.0, 0.05, 0.075]
    assert [f["realizedCheck"] for f in fills] == [None, "ok", "ok"]
    assert all(isinstance(f["id"], int) and f["id"] < 2 ** 63 for f in fills)
    costs = trade_costs(1, fills, [], 100.0, 105.0, taker_fee=0.0005, qty_step=0.0001)
    assert costs["pnl"] == pytest.approx(fake.wallet - 10_000.0)          # realized - fees = the wallet change


def test_a_profit_with_the_other_sign_is_flagged():
    clock = Clock()
    c, fake = client(clock=clock)
    fake.profit_tamper = lambda d: {**d, "profit": -d["profit"]}
    fills = scenario(fake, clock, c)
    assert [f["realizedCheck"] for f in fills] == [None, "mismatch", "mismatch"]
    assert [round(float(f["realizedPnl"]), 9) for f in fills] == [0.0, 0.05, 0.075]   # the fills' own prices


def test_a_close_without_its_opening_fill_takes_mexcs_profit():
    deals = [{"id": 9, "symbol": B, "side": 4, "vol": 10, "price": 110.0, "fee": 0.0005, "profit": 0.01,
              "orderId": 77, "timestamp": T0}]
    f = MX.fills_from_deals(deals, "0.0001", BTC)[0]
    assert (f["realizedSource"], f["realizedPnl"], f["side"], f["closedSize"]) == ("profit", "0.01", "SELL", "0.001")
    f = MX.fills_from_deals([{**deals[0], "profit": None}], "0.0001", BTC)[0]
    assert f["realizedSource"] == "unknown" and f["realizedPnl"] == "0"
    with pytest.raises(TransientError):
        MX.fills_from_deals([{**deals[0], "side": 7}], "0.0001", BTC)


def test_fills_page_through():
    clock = Clock()
    c, fake = client(clock=clock)
    fake.page = 2
    ready(c)
    for _ in range(3):
        c.market(BTC, "BUY", 0.001)
        clock.t += 10
    for _ in range(3):
        c.market(BTC, "SELL", 0.001, reduce_only=True)
        clock.t += 10
    fills = c.user_trades(BTC, T0 - 1000, clock.t + 1000)
    assert len(fills) == 6 and len({f["id"] for f in fills}) == 6


def test_funding_transfers_and_bonus_as_income():
    clock = Clock()
    c, fake = client(clock=clock)
    fake.page = 2
    ready(c)
    c.market(BTC, "BUY", 0.001)
    for amount in (-0.4, 0.1, -0.2):
        clock.t += 1000
        fake.add_funding(B, amount)
    fake.add_transfer(250.0)
    fake.add_transfer(-100.0)
    fake.add_transfer(80.0, state="WAIT")                                  # not done yet: not counted
    c.account()
    fake.bonus = 5.0                                                       # a bonus: money that is not P&L
    c.account()
    rows = c.income(None, None, T0 - 10_000, clock.t + 10_000)
    assert [r["income"] for r in rows if r["incomeType"] == "FUNDING_FEE"] == ["-0.4", "0.1", "-0.2"]
    assert [(r["info"], r["income"]) for r in rows if r["incomeType"] == "TRANSFER"] == [
        ("IN", "250"), ("OUT", "-100"), ("BONUS", "5")]
    assert len({r["tranId"] for r in rows}) == len(rows)
    assert all(r["symbol"] == BTC for r in c.income(BTC, None, T0 - 10_000, clock.t + 10_000))
    assert c.income(None, "FUNDING_FEE", T0 + 1500, clock.t + 10_000)[0]["income"] == "0.1"


# ------------------------------------------------------------------ keys and the key gate
def test_trading_keys_mainnet_only_and_never_another_exchanges_key():
    assert MX.trading_keys("mainnet", LIVE) == ("mk", "ms")
    with pytest.raises(Refused) as e:
        MX.trading_keys("testnet", LIVE)
    assert "테스트넷" in str(e.value)
    with pytest.raises(Refused):
        MX.trading_keys("mainnet", {**LIVE, FLAG: ""})                     # the mainnet switch
    for bad in ({**LIVE, "BINANCE_API_KEY": "mk"}, {**LIVE, "LIVE_API_SECRET": "ms"}, {**LIVE, "TESTNET_API_KEY": "mk"},
                {**LIVE, "BYBIT_LIVE_API_KEY": "mk"}, {**LIVE, "BYBIT_TESTNET_API_SECRET": "ms"},
                {**LIVE, "MEXC_LIVE_SECRET": "mk"}, {FLAG: FLAG_VALUE, "MEXC_LIVE_KEY": "mk"}):
        with pytest.raises(Refused):
            MX.trading_keys("mainnet", bad)
    with pytest.raises(Refused):
        MX.trading_keys("mainnet", LIVE, {"BINANCE_API_SECRET": "ms"})      # the paper runner's env file
    c, kc = MX.clients("mainnet", {**LIVE, MX.KEY_CHECKED: MX.KEY_CHECKED_VALUE}, host="contract.mexc.com")
    assert type(c) is MX.MexcClient and kc.attested and c.host == "contract.mexc.com"
    assert not MX.clients("mainnet", {**LIVE, MX.KEY_CHECKED: "yes"})[1].attested


def test_key_gate_proves_reads_and_needs_the_owners_statement():
    c, fake = client(cls=MX.MexcKeyCheckClient, attested=True)
    rec = c.api_restrictions()
    assert check_permissions(rec) == [] and rec["warnings"] and "출금" in rec["warnings"][0]
    paths = [p for m, p, q in fake.calls]
    assert paths == ["/api/v1/private/account/assets", "/api/v1/private/position/position_mode"]
    c2, _ = client(cls=MX.MexcKeyCheckClient)
    probs = check_permissions(c2.api_restrictions())
    assert any("출금" in p for p in probs) and any("IP" in p for p in probs)
    assert any(MX.KEY_CHECKED in p for p in probs)
    fake.fail("GET", "/api/v1/private/account/assets", ("ret", 701, "Account read permission is required"))
    with pytest.raises(TestnetError):
        c.api_restrictions()


# ------------------------------------------------------------------ the drill
def drill(fake=None, **kw):
    clock = Clock()
    c, fake = client(fake, clock=clock)
    kc = MX.MexcKeyCheckClient("mk", "ms", send=fake, clock_ms=clock, attested=True)
    return MX.MexcDrill(c, keycheck=kc, wait=lambda s: None, **kw), fake


def test_drill_read_only_checks_set_one_way_and_leverage_without_an_order():
    d, fake = drill()
    fake.mode = 1
    log = d.check()
    assert all(r["ok"] for r in log) and len(log) == 7, log
    assert fake.mode == 2 and fake.levs[(B, 1)] == [1, 40] and fake.levs[("DOGE_USDT", 2)] == [1, 30]
    assert not fake.orders and not fake.plans                              # no order of any kind
    contracts = log[1]["detail"]
    assert contracts["DOGEUSDT"]["contractSize"] == "100" and contracts[BTC]["priceUnit"] == "0.1"


@pytest.mark.parametrize("side,net", [(1, False), (-1, True)])
def test_drill_order_cycle_is_one_smallest_order(side, net):
    d, fake = drill(side=side)
    fake.profit_net, fake.slip = net, 0.001
    d.check()
    log = d.order_cycle()
    assert all(r["ok"] for r in log), log
    assert d.symbol == BTC                                                 # the cheapest smallest order
    creates = [q for m, p, q in fake.calls if p.endswith("/order/create")]
    # MEXC refuses orders under 5 USDT (code 7008, the owners' first live drill): the fewest contracts worth >= $6
    spec, px = d.client.spec(BTC), d.client.price(BTC)
    vol = creates[0]["vol"]
    assert vol * spec["qty_step"] * px >= MX.DRILL_ORDER_USDT > (vol - 1) * spec["qty_step"] * px
    assert [q["vol"] for q in creates] == [vol, vol] and [q["side"] for q in creates] == (
        [1, 4] if side > 0 else [3, 2])
    plans = [q for m, p, q in fake.calls if p.endswith("planorder/place")]
    assert len(plans) == 2                                                 # the stop, then the moved stop
    assert fake.pos[B] == 0 and not fake.live_plans() and not [o for o in fake.orders.values() if o["state"] in (1, 2)]
    moved = next(r for r in log if r["step"].startswith("손절 옮기기"))
    assert moved["detail"]["during"] == 2
    pnl = log[-1]["detail"]
    assert pnl["fills"] == 2 and pnl["realized"] < 0 and pnl["check"] == ["ok"]
    assert pnl["fee_rate_pct"] == pytest.approx(100 * fake.fee, rel=1e-3)   # the rate MEXC really charged


def test_drill_stops_when_equity_leaves_out_the_position_margin():
    """The daily-loss and drawdown limits read the equity: if MEXC's equity fell by the margin on every entry, the
    executor would halt itself. The drill finds it before any live trading, then leaves the account flat."""
    d, fake = drill(symbol=BTC)
    fake.equity_without_margin = True
    with pytest.raises(AssertionError) as e:
        d.order_cycle()
    assert "평가액" in str(e.value)


def test_drill_refuses_a_dirty_account_and_flips_are_caught(monkeypatch):
    d, fake = drill(symbol=BTC)
    fake.pos[B], fake.entry[B] = Decimal(3), 100.0
    with pytest.raises(AssertionError):
        d.order_cycle()
    d, fake = drill(symbol=BTC)
    fake.slip = 0.001
    real = MX.fills_from_deals

    def flipped(deals, cs, symbol):
        out = real(deals, cs, symbol)
        for f in out:
            f["realizedPnl"] = MX._num(-Decimal(f["realizedPnl"]))
            f["realizedCheck"] = "ok" if f["realizedCheck"] else None       # even if the cross-check were fooled
        return out
    monkeypatch.setattr(MX, "fills_from_deals", flipped)
    with pytest.raises(AssertionError) as e:
        d.order_cycle()
    assert "체결로 계산한 손익" in str(e.value)


def test_drill_cli_needs_keys_and_the_confirmation(monkeypatch, capsys):
    for k in list(os.environ):
        if "API_" in k or k.startswith("MEXC_") or k == FLAG:
            monkeypatch.delenv(k, raising=False)
    assert MX.main(["drill"]) == 2
    monkeypatch.setenv(FLAG, FLAG_VALUE)
    monkeypatch.setenv("MEXC_LIVE_KEY", "same")
    monkeypatch.setenv("MEXC_LIVE_SECRET", "x")
    monkeypatch.setenv("BYBIT_LIVE_API_KEY", "same")                       # a Bybit key: refused before any request
    assert MX.main(["drill"]) == 2
    assert "바이비트" in capsys.readouterr().err
    monkeypatch.delenv("BYBIT_LIVE_API_KEY")
    fake = FakeMexc(api_key="same", api_secret="x")
    clock = Clock()
    fake.clock = clock
    real = MX.MexcClient.__init__

    def init(self, *a, **k):
        real(self, *a, **{**k, "send": fake, "clock_ms": clock, "sleep": lambda s: None})
    monkeypatch.setattr(MX.MexcClient, "__init__", init)
    monkeypatch.setattr(MX, "PAPER_ENV_FILE", "/nonexistent/live.env")
    monkeypatch.setenv(MX.KEY_CHECKED, MX.KEY_CHECKED_VALUE)
    assert MX.main(["drill"]) == 0                                         # checks only: no order without the flag
    out = capsys.readouterr().out
    assert "--confirm-order REAL_ORDER" in out and not fake.orders
    assert MX.main(["drill", "--confirm-order", "yes"]) == 0 and not fake.orders
    assert MX.main(["drill", "--symbol", "DOGEUSDT", "--confirm-order", "REAL_ORDER"]) == 0
    assert [q["symbol"] for m, p, q in fake.calls if p.endswith("/order/create")] == ["DOGE_USDT"] * 2
    assert fake.pos["DOGE_USDT"] == 0


def test_agents_and_the_dashboard_never_import_the_mexc_client():
    pat = re.compile(r"^\s*(from\s+\S*\bmexc\b\s+import|import\s+\S*\bmexc\b|from\s+\.+\s+import\s+.*\bmexc\b)", re.M)
    roots = [os.path.join(REPO, "paperbot", "agents"), os.path.join(REPO, "paperbot", "dash")]
    files = [os.path.join(r, f) for root in roots for r, _, fs in os.walk(root) for f in fs if f.endswith(".py")]
    files += [os.path.join(REPO, "paperbot", f) for f in ("live3.py", "live.py", "daily3.py", "store3.py")]
    hits = [os.path.relpath(p, REPO) for p in files if pat.search(open(p, encoding="utf-8").read())]
    assert hits == []


def test_the_query_is_encoded_like_mexcs_java_example():
    """URLEncoder.encode(value).replaceAll("\\+", "%20"): spaces as %20, commas encoded."""
    assert MX.query_string({"a": "x y", "b": "1,2", "c": True}) == "a=x%20y&b=1%2C2&c=true"
    assert urllib.parse.unquote(MX.query_string({"s": "BTC_USDT"})) == "s=BTC_USDT"


def test_drill_paces_its_requests():
    """The owners' live drill 10-19 got MEXC code 510 (too frequent) reading six coins at once: the drill's requests
    are spaced (at least DRILL_MIN_GAP_S apart)."""
    d, fake = drill()
    t = [0.0]
    waits = []

    def sleep(s):
        waits.append(s)
        t[0] += s
    MX.pace(d.client, sleep=sleep, clock=lambda: t[0])
    d.check()
    n = sum(1 for m, p, q in fake.calls)
    assert n > 5 and len(waits) >= n // 2 and all(w >= MX.DRILL_MIN_GAP_S - 1e-9 for w in waits)   # (the key check uses its own client)
