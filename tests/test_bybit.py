"""paperbot/bybit.py against the fake Bybit v5 exchange (tests/fakebybit.py): signing, hosts, keys, the translation
into the Binance client's shapes, error classes, the stop protocol and the testnet drill. No network."""

import hashlib
import hmac
import json
import os
import re
import socket

import pytest

from fakebybit import FakeBybit
from paperbot import bybit as BY
from paperbot.livepnl import trade_costs
from paperbot.mainnet import FLAG, FLAG_VALUE, Refused, check_permissions
from paperbot.testnet import (NOT_FOUND, WOULD_TRIGGER, RateLimited, TestnetError, TransientError, covers,
                              live_stops, move_stop, place_stop)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T0 = 1_800_000_000_000
BTC = "BTCUSDT"


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


def client(fake=None, clock=None, cls=BY.BybitClient, **kw):
    fake = fake or FakeBybit()
    clock = clock or Clock()
    fake.clock = clock
    return cls("k", "s", send=fake, clock_ms=clock, sleep=lambda s: None, **kw), fake


# ------------------------------------------------------------------ transport: hosts, signing, errors
def test_hosts_are_allowlisted_per_class():
    for base in ("https://api.bybit.com", "https://api-testnet.bybit.com.evil.io", "http://api-testnet.bybit.com",
                 "https://api-demo.bybit.com", "https://api-testnet.bybit.com/v5", "https://api-testnet.bybit.com:8443"):
        with pytest.raises(ValueError):
            BY.BybitClient("k", "s", base=base)
    for base in ("https://api-testnet.bybit.com", "https://fapi.binance.com", "https://api.bybit.com.evil.io"):
        with pytest.raises(ValueError):
            BY.BybitMainnetClient("k", "s", base=base)
    assert BY.BybitMainnetClient("k", "s").host == "api.bybit.com"
    assert BY.BybitMainnetClient("k", "s", base="https://api.bytick.com").host == "api.bytick.com"
    assert BY.BybitClient("k", "s").host == "api-testnet.bybit.com"
    with pytest.raises(ValueError):
        BY.BybitClient("", "")


def test_signature_matches_the_documented_example_and_the_fake_checks_every_request():
    # docs v5/guide.mdx: GET string timestamp + key + recv_window + queryString
    s = "1658384314791" + "XXXXXXXXXX" + "5000" + "category=option&symbol=BTC-29JUL22-25000-C"
    assert len(hmac.new(b"secret", s.encode(), hashlib.sha256).hexdigest()) == 64
    seen = []
    c, fake = client()

    def spy(method, url, headers, body):
        seen.append((method, url, dict(headers), body))
        return fake(method, url, headers, body)
    c.send = spy
    c.sync_time()
    c.position(BTC)
    c.stop_close(BTC, "SELL", 95.0, qty=1.0, client_id="pbs1") if fake.pos[BTC] else None
    m, url, h, body = seen[1]
    q = url.split("?", 1)[1]
    assert q == "category=linear&symbol=BTCUSDT"                       # sorted, sent exactly as signed
    want = hmac.new(b"s", (h["X-BAPI-TIMESTAMP"] + "k" + "5000" + q).encode(), hashlib.sha256).hexdigest()
    assert h["X-BAPI-SIGN"] == want and h["X-BAPI-SIGN-TYPE"] == "2" and h["X-BAPI-RECV-WINDOW"] == "5000"
    assert "X-BAPI-SIGN" not in seen[0][2]                             # public endpoints are not signed
    # a wrong secret: the exchange answers 10004 (a refusal, not retried)
    bad = BY.BybitClient("k", "wrong", send=fake, clock_ms=Clock())
    with pytest.raises(TestnetError) as e:
        bad.position(BTC)
    assert e.value.code == 10004 and not isinstance(e.value, TransientError)


def test_post_bodies_are_signed_as_sent():
    c, fake = client()
    seen = []

    def spy(method, url, headers, body):
        seen.append((headers, body))
        return fake(method, url, headers, body)
    c.send = spy
    c.market(BTC, "BUY", 1.0, client_id="pbe1")
    h, body = next((h, b) for h, b in seen if b is not None)
    assert json.loads(body) == {"category": "linear", "symbol": BTC, "side": "Buy", "orderType": "Market",
                                "qty": "1.000", "positionIdx": 0, "orderLinkId": "pbe1"}
    want = hmac.new(b"s", (h["X-BAPI-TIMESTAMP"] + "k5000").encode() + body, hashlib.sha256).hexdigest()
    assert h["X-BAPI-SIGN"] == want


def test_clock_offset_and_the_recv_window():
    clock = Clock()
    c, fake = client(clock=clock)
    fake.skew = 7_000                                                  # the exchange is 7 s ahead of us
    with pytest.raises(TestnetError) as e:
        c.position(BTC)
    assert e.value.code == -1021                                       # 10002: the executor re-syncs and resends
    assert c.sync_time() == 7_000 and float(c.position(BTC)["positionAmt"]) == 0


def test_error_classes():
    c, fake = client()
    fake.fail("GET", "/v5/position/list", "drop_before")
    with pytest.raises(TransientError):
        c.position(BTC)
    fake.fail("GET", "/v5/position/list", "503_before")
    with pytest.raises(TransientError) as e:
        c.position(BTC)
    assert e.value.status == 503
    fake.fail("GET", "/v5/position/list", "429")
    with pytest.raises(RateLimited) as e:
        c.position(BTC)
    assert e.value.status == 429 and e.value.retry_after == 2.0
    for code in (10006, 10018):
        fake.fail("GET", "/v5/position/list", ("ret", code, "Too many visits!"))
        with pytest.raises(RateLimited):
            c.position(BTC)
    fake.fail("GET", "/v5/position/list", "403")
    with pytest.raises(RateLimited) as e:
        c.position(BTC)
    assert e.value.status == 418 and e.value.retry_after >= 600          # an IP ban: the loop waits, no retries
    for code in (10000, 10016, 429):
        fake.fail("GET", "/v5/position/list", ("ret", code, "Server Timeout"))
        with pytest.raises(TransientError):
            c.position(BTC)
    fake.fail("GET", "/v5/position/list", ("ret", 10005, "Permission denied"))
    with pytest.raises(TestnetError) as e:
        c.position(BTC)
    assert e.value.code == 10005 and not isinstance(e.value, TransientError)
    c.send = lambda *a: (200, b"<html>maintenance</html>", {})        # 200 that is not a Bybit answer: unknown
    with pytest.raises(TransientError):
        c.position(BTC)
    c.send = lambda *a: (200, json.dumps({"retCode": 0, "result": {"list": []}}).encode(), {})
    with pytest.raises(TransientError):                                # never "flat" from an empty answer
        c.position(BTC)
    c.send = lambda *a: (200, json.dumps({"retCode": 0, "result": {"list": [
        {"symbol": BTC, "positionIdx": 0, "side": "Buy", "size": ""}]}}).encode(), {})
    with pytest.raises(TransientError):                                # nor from a missing size
        c.position(BTC)


def test_rate_limit_headers_slow_the_next_request():
    c, fake = client()
    c.position(BTC)
    assert c.throttle_s() == 0
    c.rl["/v5/order/create"] = (1, 10, c.clock_ms() + 400)
    assert 0 < c.throttle_s() <= 0.4


# ------------------------------------------------------------------ market data, account, modes
def test_spec_is_read_live_and_rounds_to_the_exchange_steps():
    c, fake = client()
    sp = c.spec(BTC)
    assert (sp["qty_step"], sp["min_qty"], sp["tick"], sp["min_notional"], sp["max_leverage"]) == \
        (0.001, 0.001, 0.1, 5.0, 100.0)
    assert c.spec("DOGEUSDT")["qty_step"] == 1.0
    assert BY._floor_to(0.0129, "0.001") == "0.012" and BY._floor_to(3.0, "1") == "3"
    assert BY._floor_to(0.3, "0.1") == "0.3" and BY._price_str(95.1, "0.10") == "95.10"
    with pytest.raises(TestnetError):
        c.spec("XRPUSDT")
    tiers = c.risk_limits(BTC)                                         # percent units detected (1% x 100x = 100)
    assert tiers[0]["mmr"] == 0.005 and tiers[0]["max_leverage"] == 100
    br = c.leverage_brackets()
    assert {b["symbol"] for b in br} == {BTC, "DOGEUSDT"}
    from paperbot.margin import Brackets
    Brackets.from_binance(br[0])                                       # the executor's signal mode reads it


def test_account_and_positions_in_the_binance_shape():
    c, fake = client()
    fake.wallet, fake.other_coins = 520.0, {"BTC": 0.001}
    a = c.account()
    assert a["totalWalletBalance"] == "520.0" and a["totalMarginBalance"] == "520.0"
    assert [x["asset"] for x in a["assets"]] == ["USDT", "BTC"]
    fake.pos[BTC], fake.entry[BTC] = BY.Decimal("-0.5"), 100.0
    fake.last[BTC] = 90.0
    p = c.position(BTC)
    assert p["positionAmt"] == "-0.5" and p["entryPrice"] == "100.0" and p["markPrice"] == "90.0"
    assert float(c.account()["totalMarginBalance"]) == 525.0
    assert [x["symbol"] for x in c.positions()] == [BTC]


def test_one_way_and_isolated_margin_and_leverage():
    c, fake = client()
    fake.hedge[BTC] = True
    c.one_way()
    assert fake.hedge[BTC] is False
    c.one_way()                                                        # 110025 "not modified": fine
    fake.margin_refusal = "Equity needs to be equal to or greater than 1000 USDC"
    with pytest.raises(TestnetError) as e:                             # never an entry in cross margin
        c.leverage(BTC, 40)
    assert e.value.code == "NOT_ISOLATED" and fake.lev[BTC] == "10"
    fake.margin_refusal = None
    c.isolated(BTC)
    assert fake.info["marginMode"] == "ISOLATED_MARGIN"
    c.isolated("ETHUSDT")                                              # account level: nothing more to do
    assert c.leverage(BTC, 40)["leverage"] == 40 and fake.lev[BTC] == "40"
    assert c.leverage(BTC, 40)["leverage"] == 40                       # 110043 "not modified": fine
    with pytest.raises(TestnetError):
        c.leverage("SOLUSDT", 80)                                      # over the instrument's max


def test_isolated_refuses_or_warns_when_it_cannot_switch():
    c, fake = client()
    fake.margin_refusal = "Equity needs to be equal to or greater than 1000 USDC"
    with pytest.raises(Refused) as e:                                  # nothing open: do not start
        c.isolated(BTC)
    assert "ISOLATED_MARGIN" in str(e.value) and "1000 USDC" in str(e.value)
    c2, fake2 = client()
    fake2.pos[BTC], fake2.entry[BTC] = BY.Decimal("1"), 100.0           # a position open in cross margin
    with pytest.raises(TestnetError) as e:
        c2.isolated(BTC)
    assert e.value.code == -4048                                       # the executor warns and keeps protecting


def test_classic_account_switches_per_symbol():
    c, fake = client(FakeBybit(uta=1))
    c.isolated(BTC)
    assert fake.trade_mode[BTC] == 1 and fake.lev[BTC] == "40"           # BTC 40x, the rest 30x
    c.isolated("ETHUSDT")
    assert fake.lev["ETHUSDT"] == "30"
    c.isolated(BTC)                                                    # 110026 "not modified"
    assert c.leverage(BTC, 20)["leverage"] == 20
    assert c.account()["totalWalletBalance"] == "10000.0"              # accountType CONTRACT


# ------------------------------------------------------------------ orders
def test_market_order_is_read_back_until_final():
    c, fake = client()
    fake.market_lag = 2                                                # creation is asynchronous
    o = c.market(BTC, "BUY", 1.0, client_id="pbe1")
    o_first = o["orderId"]
    assert o["status"] == "FILLED" and o["executedQty"] == "1.000" and float(o["avgPrice"]) == 100.0
    assert o["side"] == "BUY" and o["clientOrderId"] == "pbe1"
    assert c.order(BTC, client_id="pbe1")["orderId"] == o["orderId"]   # the look-up after a lost answer
    fake.market_lag = 9
    o = c.market(BTC, "SELL", 0.5, reduce_only=True, client_id="pbx1")
    assert o["status"] == "NEW" and o["executedQty"] == "0"            # still New after the reads: not final
    assert fake.pos[BTC] == BY.Decimal("0.5")
    with pytest.raises(TestnetError) as e:
        c.order(BTC, client_id="nothere")
    assert e.value.code in NOT_FOUND
    fake.market_lag, fake.partial = 0, 0.6
    o = c.market(BTC, "BUY", 1.0)
    assert o["status"] == "CANCELED" and float(o["executedQty"]) == 0.6   # IOC remainder cancelled: final, part filled
    with pytest.raises(TestnetError) as e:
        c.market(BTC, "BUY", 0.0004)
    assert e.value.code == "QTY_ZERO"
    n, pos = len(fake.orders), fake.pos[BTC]
    again = c.market(BTC, "BUY", 1.0, client_id="pbe1")                # 110072: never a second order, looked up
    assert again["duplicate"] and again["orderId"] == o_first and len(fake.orders) == n and fake.pos[BTC] == pos


def test_link_ids():
    assert BY.link_id("pb0123456789abs3") == "pb0123456789abs3"
    long = BY.link_id("x" * 40)
    assert len(long) <= 36 and long == BY.link_id("x" * 40)
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,36}", BY.link_id("a.b/c"))
    assert BY.link_id(None) != BY.link_id(None)


def test_stop_parameters_and_translation():
    c, fake = client()
    c.market(BTC, "BUY", 2.0)
    s = c.stop_close(BTC, "SELL", 95.0, qty=2.0, client_id="pbs1")
    body = fake.calls[-1][2]
    assert body == {"category": "linear", "symbol": BTC, "side": "Sell", "orderType": "Market", "qty": "2.000",
                    "triggerPrice": "95.00", "triggerDirection": 2, "triggerBy": "LastPrice", "reduceOnly": True,
                    "closeOnTrigger": True, "positionIdx": 0, "orderLinkId": "pbs1"}
    got = c.algo_order(algo_id=s["algoId"])
    assert got["orderType"] == "STOP_MARKET" and got["algoStatus"] == "NEW" and got["side"] == "SELL"
    assert got["workingType"] == "CONTRACT_PRICE" and covers(got, 2.0) and not covers(got, 3.0)
    assert not covers(got, -2.0)
    assert c.algo_order(client_id="pbs1")["algoId"] == s["algoId"]      # found by orderLinkId (no symbol needed)
    lst = live_stops(c, BTC)
    assert [x["algoId"] for x in lst] == [s["algoId"]]
    c.stop_close(BTC, "SELL", 94.0)                                     # qty "0": close the whole position
    assert fake.calls[-1][2]["qty"] == "0" and any(x["closePosition"] for x in live_stops(c, BTC))
    with pytest.raises(TestnetError) as e:                              # a size that rounds to 0 is never "close all"
        c.stop_close(BTC, "SELL", 94.0, qty=0.0001)
    assert e.value.code == "QTY_ZERO"
    # a take-profit (rises, for a long) is not a stop
    tp = c._algo_dict({**fake.orders[s["algoId"]], "triggerDirection": 1})
    assert tp["orderType"] == "TAKE_PROFIT_MARKET"


def test_would_trigger_maps_to_the_binance_code():
    c, fake = client()
    c.market(BTC, "BUY", 1.0)
    with pytest.raises(TestnetError) as e:
        c.stop_close(BTC, "SELL", 101.0, qty=1.0)                       # 110093: price already below
    assert e.value.code == WOULD_TRIGGER
    c.market(BTC, "SELL", 2.0)                                          # now short 1
    with pytest.raises(TestnetError) as e:
        c.stop_close(BTC, "BUY", 99.0, qty=1.0)                         # 110092
    assert e.value.code == WOULD_TRIGGER
    fake.fail("POST", "/v5/order/create", ("ret", 10001, "params error"))   # another code, price past the stop
    with pytest.raises(TestnetError) as e:
        c.stop_close(BTC, "BUY", 99.0, qty=1.0)
    assert e.value.code == WOULD_TRIGGER and "params error" in e.value.msg
    fake.fail("POST", "/v5/order/create", ("ret", 10001, "params error"))   # price not past: stays a refusal
    with pytest.raises(TestnetError) as e:
        c.stop_close(BTC, "BUY", 105.0, qty=1.0)
    assert e.value.code == 10001


def test_move_stop_new_first_then_cancel_and_the_minus_2021_path():
    c, fake = client()
    c.market(BTC, "BUY", 1.0)
    s1 = place_stop(c, BTC, "SELL", 95.0, 1.0)
    fake.fail("POST", "/v5/order/create", ("ret", 110009, "The number of stop orders exceeds the maximum"))
    with pytest.raises(TestnetError):
        move_stop(c, BTC, "SELL", 97.0, 1.0, [s1["algoId"]])
    assert [o["orderId"] for o in fake.live_stops()] == [s1["algoId"]] and fake.covered(BTC)
    res = move_stop(c, BTC, "SELL", 97.0, 1.0, [s1["algoId"]])
    assert res["result"] == "moved" and [o["triggerPrice"] for o in fake.live_stops()] == ["97.00"]
    first = next(i for i, (m, p, q) in enumerate(fake.calls) if p == "/v5/order/create" and "triggerPrice" in q)
    assert not [t for t in fake.unprotected_moments(BTC) if t[0] > first]   # only the entry, before the first stop
    fake.set_price(BTC, 98.0)
    res = move_stop(c, BTC, "SELL", 99.0, 1.0, [res["stop"]["algoId"]])  # above the price: closed at market
    assert res["result"] == "closed" and res["flat"] and fake.pos[BTC] == 0
    assert res["cancelled"] == [] and len(fake.live_stops()) == 1        # the old stop: the caller's to cancel
    c.cancel_all_algo(BTC)
    assert not fake.live_stops()


def test_cancel_needs_no_symbol_and_gone_orders_count_as_cancelled():
    c, fake = client()
    c.market(BTC, "BUY", 1.0)
    s = c.stop_close(BTC, "SELL", 95.0, qty=1.0)
    other = BY.BybitClient("k", "s", send=fake, clock_ms=fake.clock)   # a restarted process: no id -> symbol map
    other.cancel_algo(algo_id=s["algoId"])
    assert fake.orders[s["algoId"]]["orderStatus"] == "Deactivated"
    with pytest.raises(TestnetError) as e:
        c.cancel_algo(algo_id=s["algoId"])                              # 110010: already cancelled
    assert e.value.code in NOT_FOUND
    with pytest.raises(TestnetError) as e:
        other.cancel_algo(algo_id="nope")
    assert e.value.code in NOT_FOUND


def test_a_triggered_stop_reads_as_fired_with_its_own_order_id():
    c, fake = client()
    c.market(BTC, "BUY", 1.0)
    s = c.stop_close(BTC, "SELL", 95.0, qty=1.0)
    fake.set_price(BTC, 94.0)
    o = c.algo_order(algo_id=s["algoId"])
    assert o["algoStatus"] == "FINISHED" and o["actualOrderId"] == s["algoId"] and fake.pos[BTC] == 0
    fills = c.user_trades(BTC, T0 - 1000, T0 + 1000)
    assert [f["orderId"] for f in fills if f["side"] == "SELL"] == [s["algoId"]]


# ------------------------------------------------------------------ fills, P&L, funding, transfers
def test_fills_realized_pnl_from_closed_pnl_and_replay():
    clock = Clock()
    c, fake = client(clock=clock)
    c.market(BTC, "BUY", 2.0)
    clock.t += 1000
    fake.set_price(BTC, 110.0)
    c.market(BTC, "SELL", 0.5, reduce_only=True)
    clock.t += 1000
    c.market(BTC, "SELL", 2.5)                                           # closes 1.5, opens a 1.0 short
    clock.t += 1000
    fake.set_price(BTC, 105.0)
    c.market(BTC, "BUY", 1.0, reduce_only=True)
    fills = c.user_trades(BTC, T0 - 5000, clock.t + 5000)
    assert [f["realizedSource"] for f in fills] == ["open", "closed-pnl", "closed-pnl", "closed-pnl"]
    assert [round(float(f["realizedPnl"]), 6) for f in fills] == [0.0, 5.0, 15.0, 5.0]
    fake.closed_hidden = True                                             # closed-pnl lags: replayed from the fills
    again = c.user_trades(BTC, T0 - 5000, clock.t + 5000)
    assert [f["realizedSource"] for f in again] == ["open", "replay", "replay", "replay"]
    assert [f["realizedPnl"] for f in again] == [f["realizedPnl"] for f in fills]
    assert all(isinstance(f["id"], int) and f["id"] < 2 ** 63 for f in fills)
    assert sum(float(f["commission"]) for f in fills) == pytest.approx(
        0.00055 * (2 * 100 + 0.5 * 110 + 2.5 * 110 + 1 * 105))
    # livepnl reads the same numbers as from Binance: realized - commission + funding = the wallet change
    c2 = trade_costs(1, fills[:3], [], 100.0, 110.0, taker_fee=0.00055, qty_step=0.001)
    assert c2["realized"] == pytest.approx(20.0)


def test_fills_skip_funding_and_page_through_cursors():
    clock = Clock()
    c, fake = client(clock=clock)
    fake.page = 2
    for _ in range(3):
        c.market(BTC, "BUY", 1.0)
        clock.t += 10
    fake.add_funding(BTC, -0.4)
    for _ in range(3):
        c.market(BTC, "SELL", 1.0)
        clock.t += 10
    fills = c.user_trades(BTC, T0 - 1000, clock.t + 1000)
    assert len(fills) == 6 and all(f["execType"] == "Trade" for f in fills)
    inc = c.income(BTC, None, T0 - 1000, clock.t + 1000)
    fund = [r for r in inc if r["incomeType"] == "FUNDING_FEE"]
    assert [r["income"] for r in fund] == ["-0.4"] and fund[0]["symbol"] == BTC
    assert len({r["tranId"] for r in inc}) == len(inc) == 7


def test_income_transfers_and_the_seven_day_windows():
    clock = Clock()
    c, fake = client(clock=clock)
    fake.add_transfer(250.0)
    clock.t += 1000
    fake.add_transfer(-100.0)
    rows = c.income(None, None, T0 - 20 * 86_400_000, clock.t)          # chunked into <= 7-day requests
    assert [(r["incomeType"], r["income"]) for r in rows] == [("TRANSFER", "250"), ("TRANSFER", "-100")]
    assert all(r["asset"] == "USDT" for r in rows)
    spans = [int(q["endTime"]) - int(q["startTime"]) for m, p, q in fake.calls if p == "/v5/account/transaction-log"]
    assert len(spans) == 3 and max(spans) <= 7 * 86_400_000
    assert c.income(None, "FUNDING_FEE", T0 - 1000, clock.t) == []


# ------------------------------------------------------------------ keys and the mainnet permission gate
def test_trading_keys_per_mode_and_exchange():
    env = {"BYBIT_TESTNET_API_KEY": "bt", "BYBIT_TESTNET_API_SECRET": "bts"}
    assert BY.trading_keys("testnet", env) == ("bt", "bts")
    with pytest.raises(Refused):
        BY.trading_keys("mainnet", {**env, "BYBIT_LIVE_API_KEY": "bl", "BYBIT_LIVE_API_SECRET": "bls"})   # no flag
    live = {FLAG: FLAG_VALUE, "BYBIT_LIVE_API_KEY": "bl", "BYBIT_LIVE_API_SECRET": "bls"}
    assert BY.trading_keys("mainnet", live) == ("bl", "bls")
    for bad in ({**env, "BINANCE_API_KEY": "bt"}, {**env, "LIVE_API_KEY": "bts"}, {**env, "TESTNET_API_KEY": "bt"},
                {**env, "BYBIT_LIVE_API_KEY": "bt"}, {"BYBIT_TESTNET_API_KEY": "x", "BYBIT_TESTNET_API_SECRET": "x"},
                {"BYBIT_TESTNET_API_KEY": "x"}):
        with pytest.raises(Refused):
            BY.trading_keys("testnet", bad)
    with pytest.raises(Refused):
        BY.trading_keys("testnet", env, {"BINANCE_API_SECRET": "bts"})   # the paper runner's env file


def test_permission_record_feeds_the_binance_gate():
    fake = FakeBybit()
    ok = BY.permission_record(fake.key_info)
    assert check_permissions(ok) == []
    for change, needle in (({"ips": []}, "IP"), ({"ips": ["*"]}, "IP"), ({"readOnly": 1}, "선물"),
                           ({"permissions": {"ContractTrade": ["Order"]}}, "선물"),
                           ({"permissions": {"ContractTrade": ["Order", "Position"], "Wallet": ["Withdraw"]}}, "출금"),
                           ({"permissions": {"ContractTrade": ["Order", "Position"], "Wallet": ["AccountTransfer"]}},
                            "이체"),
                           ({"permissions": {"ContractTrade": ["Order", "Position"], "Spot": ["SpotTrade"]}}, "현물"),
                           ({"permissions": {"ContractTrade": ["Order", "Position"], "Options": ["OptionsTrade"]}},
                            "옵션"),
                           ({"permissions": {"ContractTrade": ["Order", "Position"], "Earn": ["Earn"]}}, "Earn")):
        probs = check_permissions(BY.permission_record({**fake.key_info, **change}))
        assert any(needle in p for p in probs), (change, probs)
    assert BY.permission_record({"retCode": 0}) is None and BY.permission_record(None) is None
    uta = BY.permission_record({**fake.key_info, "permissions": {"Derivatives": ["DerivativesTrade"]}})
    assert uta["enableFutures"] is True


# ------------------------------------------------------------------ drill
@pytest.mark.parametrize("side", [1, -1])
def test_drill_runs_clean_cycle(side):
    c, fake = client()
    fake.cancel_lag = 1                                                  # cancels show up a read late
    fake.market_lag = 1
    log = BY.BybitDrill(c, BTC, side=side, notional=200.0, leverage=40, wait=lambda s: None).run()
    assert all(r["ok"] for r in log) and len(log) == 11, log
    assert fake.pos[BTC] == 0 and not fake.live_stops() and fake.info["marginMode"] == "ISOLATED_MARGIN"
    assert fake.lev[BTC] == "40"
    stops = [q for m, p, q in fake.calls if p == "/v5/order/create" and "triggerPrice" in q]
    assert len(stops) == 4                                               # first, moved, restored, refused
    assert all(q["triggerBy"] == "LastPrice" and q["reduceOnly"] and q["closeOnTrigger"] for q in stops)
    moved = next(r for r in log if r["step"] == "stop moved without a gap")
    assert moved["detail"]["during"] == 2
    pnl = log[-1]["detail"]
    assert pnl["fills"] == 2 and pnl["net"] == pytest.approx(float(pnl["bybit_closedPnl"]), abs=1e-9)


def test_drill_refuses_a_dirty_account():
    c, fake = client()
    fake.pos[BTC] = BY.Decimal("0.002")
    with pytest.raises(AssertionError):
        BY.BybitDrill(c, BTC, wait=lambda s: None).run()


def test_drill_cli_needs_testnet_keys(monkeypatch, capsys):
    for k in list(os.environ):
        if "API_" in k:
            monkeypatch.delenv(k, raising=False)
    assert BY.main(["drill"]) == 2
    monkeypatch.setenv("BYBIT_TESTNET_API_KEY", "same")
    monkeypatch.setenv("BYBIT_TESTNET_API_SECRET", "x")
    monkeypatch.setenv("TESTNET_API_KEY", "same")                       # a Binance key: refused before any request
    assert BY.main(["drill"]) == 2
    assert "바이낸스" in capsys.readouterr().err


def test_agents_and_the_dashboard_never_import_the_bybit_client():
    pat = re.compile(r"^\s*(from\s+\S*\bbybit\b\s+import|import\s+\S*\bbybit\b|from\s+\.+\s+import\s+.*\bbybit\b)",
                     re.M)
    roots = [os.path.join(REPO, "paperbot", "agents"), os.path.join(REPO, "paperbot", "dash")]
    files = [os.path.join(r, f) for root in roots for r, _, fs in os.walk(root) for f in fs if f.endswith(".py")]
    files += [os.path.join(REPO, "paperbot", f) for f in ("live3.py", "live.py", "daily3.py", "store3.py")]
    hits = [os.path.relpath(p, REPO) for p in files if pat.search(open(p, encoding="utf-8").read())]
    assert hits == []
