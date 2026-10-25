"""DeepCoin (paperbot/deepcoin.py) on the fake exchange (tests/fakedeepcoin.py): signing (ISO-ms timestamp, passphrase),
the host allowlist, key gates, contract units (contracts x ctVal, lotSz 0.1 for ETH / SOL), orders (posSide +
mrgPosition merge, read back), clOrdId mapping and look-ups (no ledger), trigger-order stops (place, confirm from the
list, move with two at once, cancel, fire; a lost stop answer found by what was sent), lagging lists, 429 and the
protective budget, missing fields, fills and P&L (DeepCoin's own pnl checked against the replay), funding bills, the
drill, and the executor's whole cycle with ``"exchange": "deepcoin"`` (owners 10-24). No network."""

import base64
import hashlib
import hmac
import json
import pathlib
import socket

import pytest

from fakedeepcoin import FakeDeepCoin, SPECS
from paperbot import deepcoin as DC
from paperbot import risk as R
from paperbot.executor import ExecConfig, ExecStore, Executor, Guarded, Intent, Refused
from paperbot.mainnet import FLAG, FLAG_VALUE, check_permissions
from paperbot.notify import ListNotifier
from paperbot.testnet import (BAD_TIMESTAMP, NOT_FOUND, WOULD_TRIGGER, ProtectionError, RateLimited, TestnetError,
                              TransientError, covers, live_stops, move_stop, place_stop)

T0 = 1_800_000_000_000
BTC, ETH, DOGE = "BTCUSDT", "ETHUSDT", "DOGEUSDT"
LIVE_ENV = {FLAG: FLAG_VALUE, "DEEPCOIN_LIVE_KEY": "dk", "DEEPCOIN_LIVE_SECRET": "ds", "DEEPCOIN_LIVE_PASSPHRASE": "dp",
            DC.KEY_CHECKED: DC.KEY_CHECKED_VALUE}
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


def ticking(clock):
    """A sleep that moves the test clock (the fake's lags and the protective budget run on it)."""
    def tick(s):
        clock.t += int(round(s * 1000))
    return tick


def make(fake=None, clock=None, advance=False, **kw):
    clock = clock or Clock()
    fake = fake or FakeDeepCoin()
    fake.clock = clock
    c = DC.DeepCoinClient("dk", "ds", "dp", send=fake, clock_ms=clock,
                          sleep=ticking(clock) if advance else (lambda s: None), **kw)
    return c, fake, clock


def ready(c, symbols=(BTC,)):
    c.sync_time()
    c.one_way()
    for s in symbols:
        c.isolated(s)
    return c


def posts(fake, path="/deepcoin/trade/order"):
    return [json.loads(b) for _, m, p, _, b in fake.calls if m == "POST" and p == path]


TRIG = "/deepcoin/trade/trigger-order"


def edit_route(fake, path, f, method="GET"):
    """Rewrite one route's answer (f: the parsed ``data`` -> the ``data`` sent)."""
    real = fake._route

    def edited(m, p, query, body):
        st, raw, h = real(m, p, query, body)
        if p == path and m == method and st == 200:
            d = json.loads(raw)
            raw = json.dumps({**d, "data": f(d["data"])}).encode()
        return st, raw, h
    fake._route = edited


# ------------------------------------------------------------------ signing, transport, errors
def test_signature_matches_the_access_guide():
    """Base64(HMAC-SHA256(secret, timestamp + METHOD + requestPath + body)); the GET query is part of requestPath."""
    ts = "2020-12-08T09:08:57.715Z"
    body = '{"instId":"BTC-USDT","lever":"5","mgnMode":"isolated"}'
    want = base64.b64encode(hmac.new(b"22582BD0CFF14C41EDBF1AB98506286D",
                                     f"{ts}POST/deepcoin/account/set-leverage{body}".encode(),
                                     hashlib.sha256).digest()).decode()
    assert DC.signature("22582BD0CFF14C41EDBF1AB98506286D", ts, "post", "/deepcoin/account/set-leverage", body) == want
    q = DC.query_string({"instType": "SWAP", "instId": "BTC-USDT-SWAP", "limit": 100})
    assert q == "instId=BTC-USDT-SWAP&instType=SWAP&limit=100"
    assert DC.signature("s", ts, "GET", f"/deepcoin/account/positions?{q}") == base64.b64encode(hmac.new(
        b"s", f"{ts}GET/deepcoin/account/positions?{q}".encode(), hashlib.sha256).digest()).decode()
    assert DC.iso_ms(1607418537715) == ts and DC.iso_ms(T0) == "2027-01-15T08:00:00.000Z"


def test_signed_requests_passphrase_timestamp_and_the_host_allowlist():
    c, fake, clock = make()
    assert c.sync_time() == 0 and c.time_source == "/deepcoin/market/time"
    c.account()
    assert fake.calls[-1][2] == "/deepcoin/account/balances"
    for kw, code in ((dict(api_secret="other"), "AUTH"), (dict(passphrase="wrong"), "AUTH")):
        bad = DC.DeepCoinClient(kw.get("api_key", "dk"), kw.get("api_secret", "ds"), kw.get("passphrase", "dp"),
                                send=fake, clock_ms=clock, sleep=lambda s: None)
        with pytest.raises(TestnetError) as e:                 # the fake checks every signature and the passphrase
            bad.account()
        assert e.value.status == 401 and e.value.code == code
    c.offset_ms = -120_000                                     # a stale timestamp: refused, never executed
    with pytest.raises(TestnetError) as e:
        c.account()
    assert e.value.code == BAD_TIMESTAMP
    c.offset_ms = 0
    for base in ("https://www.deepcoin.com", "http://api.deepcoin.com", "https://api.deepcoin.com:8443",
                 "https://api.deepcoin.com/x", "https://api.deepcoin.com.evil.com"):
        with pytest.raises(ValueError):
            DC.DeepCoinClient("dk", "ds", "dp", base=base)
    for args in (("dk", "", "dp"), ("dk", "ds", "")):
        with pytest.raises(ValueError):
            DC.DeepCoinClient(*args)
    assert DC.DeepCoinClient.HOSTS == ("api.deepcoin.com",) and DC.hosts_for("mainnet") == ("api.deepcoin.com",)


def test_the_public_client_reads_specs_without_a_key_and_never_signs():
    fake = FakeDeepCoin()
    fake.clock = Clock()
    c = DC.DeepCoinClient("", "", "", public_only=True, send=fake, clock_ms=fake.clock, sleep=lambda s: None)
    assert c.spec(BTC)["ct_val"] == "0.001" and c.price(BTC) == 100.0
    assert "BTCUSDT: 상태 Trading" in DC.specs_text(c)
    with pytest.raises(TestnetError) as e:
        c.account()
    assert e.value.code == "NO_KEY"
    assert not [x for x in fake.calls if not x[2].startswith("/deepcoin/market/")]


def test_error_mapping_to_the_executor_classes():
    c, fake, clock = make()
    ready(c)
    fake.fail("GET", "/deepcoin/account/balances", "503_before")
    fake.fail("GET", "/deepcoin/account/balances", "503_before", times=3)
    with pytest.raises(TransientError):
        c.account()
    fake.fails.clear()
    fake.fail("GET", "/deepcoin/account/positions", "403")
    with pytest.raises(RateLimited) as e:
        c.positions()
    assert e.value.status == 418
    fake.fail("POST", "/deepcoin/account/set-leverage", ("err", 401, "50110", "Invalid IP"))
    with pytest.raises(Refused, match="IP"):
        c.isolated(ETH)
    fake.fail("GET", "/deepcoin/account/balances", ("err", 200, "51", "The instType field is required"))
    with pytest.raises(TestnetError) as e:
        c.account()
    assert e.value.code == "51" and not isinstance(e.value, TransientError)
    fake.fail("GET", "/deepcoin/account/balances", ("err", 200, "50011", "Too Many Requests, slow down"), times=9)
    with pytest.raises(RateLimited):
        c.account()
    fake.fails.clear()
    with pytest.raises(TestnetError) as e:                     # cancel of an unknown order: sCode 24
        c.cancel(BTC, "123")
    assert e.value.code == NOT_FOUND[0]
    with pytest.raises(TestnetError) as e:                     # a close with nothing to close: sCode 31
        c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbX")
    assert e.value.code == -2022
    fake.fail("POST", "/deepcoin/trade/order", ("scode", "36", "InsufficientMoney:-0.000004"))
    with pytest.raises(TestnetError) as e:
        c.market(BTC, "BUY", 1.0, client_id="pbE1")
    assert e.value.code == "36" and not isinstance(e.value, TransientError)


ORDER = "/deepcoin/trade/order"
RAN_THEN = [("err_after", 200, "50013", "System is busy, please try again later"),
            ("err_after", 200, "51999", "Order expired: matching engine timeout"),
            ("err_after", 401, "51998", "Request timestamp expired at the gateway"),
            ("err_after", 200, "51008", "Position limit exceeded"), ("err_after", 400, None, "Bad Request"),
            "403_after"]


@pytest.mark.parametrize("kind", RAN_THEN)
def test_an_order_that_ran_but_was_answered_otherwise_is_never_read_as_refused(kind):
    """Review 10-24 (1): an order or a stop is refused only on a documented code or its own sCode. Any other answer
    after the send (an undocumented code, whatever its words: "busy", "expired ... timestamp", "limit exceeded"; a
    garbled 400; a 403) is an unknown outcome looked up by the clOrdId: never "refused", never a clock refusal sent
    again, never a 429."""
    c, fake, clock = make()
    ready(c, (DOGE,))
    fake.fail("POST", ORDER, kind)
    with pytest.raises(TransientError) as e:
        c.market(DOGE, "BUY", 100.0, client_id="pbE1")
    assert e.value.code != BAD_TIMESTAMP and not isinstance(e.value, RateLimited) and c.rate_answers == 0
    assert fake.amt(DOGE) == 100 and "pbE1" in c.sent         # it ran: its record is kept, looked up by its id
    assert c.order(DOGE, client_id="pbE1")["status"] == "FILLED"
    assert c.market(DOGE, "BUY", 100.0, client_id="pbE1")["status"] == "FILLED" and len(posts(fake)) == 1
    g = Guarded(c, lambda s: None, retries=4)                  # the executor's wrapper: found, never sent again
    fake.fail("POST", ORDER, kind)
    assert g.market(DOGE, "BUY", 100.0, client_id="pbE2")["status"] == "FILLED"
    assert fake.amt(DOGE) == 200 and len(posts(fake)) == 2


def test_an_entry_answered_expired_behind_a_lagging_record_is_sent_once():
    """probe3: an undocumented "expired ... time" answer was read as a clock refusal and the entry sent twice."""
    c, fake, clock = make(advance=True)
    ready(c, (DOGE,))
    g = Guarded(c, ticking(clock))
    fake.order_lag_ms = 2_000
    fake.fail("POST", ORDER, ("err_after", 200, "51999", "Order expired: matching engine timeout"))
    o = g.market(DOGE, "BUY", 100.0, client_id="pbtestentryA")
    assert (o["status"], o["executedQty"]) == ("FILLED", "100") and len(posts(fake)) == 1 and fake.amt(DOGE) == 100
    assert c._error("51999", "Order expired: matching engine timeout", 200).code != BAD_TIMESTAMP


def test_only_a_documented_code_or_the_orders_own_scode_refuses_an_order():
    c, fake, clock = make()
    ready(c, (DOGE,))
    fake.fail("POST", ORDER, ("err", 401, "50102", "Request timestamp has expired"))
    with pytest.raises(TestnetError) as e:                     # documented: refused before anything ran
        c.market(DOGE, "BUY", 100.0, client_id="pbT")
    assert e.value.code == BAD_TIMESTAMP and "pbT" not in c.sent and fake.amt(DOGE) == 0
    fake.fail("POST", ORDER, ("err", 401, "50102", "Request timestamp has expired"))
    assert Guarded(c, lambda s: None).market(DOGE, "BUY", 100.0, client_id="pbT")["status"] == "FILLED"
    assert fake.amt(DOGE) == 100                               # re-synced and sent again: filled once
    fake.fail("POST", ORDER, ("scode", "36", "InsufficientMoney:-0.000004"))
    with pytest.raises(TestnetError) as e:
        c.market(DOGE, "BUY", 100.0, client_id="pbS")
    assert e.value.code == "36" and not isinstance(e.value, TransientError) and "pbS" not in c.sent
    sent = len(posts(fake))
    for i, kind in enumerate((("err", 200, "51999", "Order expired: matching engine timeout"),
                              ("err", 200, "51008", "Position limit exceeded"), "403", ("err", 400, None, "x"))):
        fake.fail("POST", ORDER, kind)                         # it did not run, but nothing says so: unknown
        with pytest.raises(TransientError) as e:
            c.market(DOGE, "BUY", 100.0, client_id=f"pbU{i}")
        assert e.value.code != BAD_TIMESTAMP and not isinstance(e.value, RateLimited)
    clock.t += DC.SETTLE_MS
    for i in range(4):
        with pytest.raises(TestnetError) as e:
            c.order(DOGE, client_id=f"pbU{i}")
        assert e.value.code == NOT_FOUND[0]
        with pytest.raises(TransientError):                   # an opening id: never sent again
            c.market(DOGE, "BUY", 100.0, client_id=f"pbU{i}")
    assert len(posts(fake)) == sent + 4 and fake.amt(DOGE) == 100 and c.rate_answers == 0


@pytest.mark.parametrize("kind", [("err_after", 200, "50013", "System is busy, please try again later"), "403_after"])
def test_a_stop_that_ran_but_was_answered_otherwise_is_found_and_never_doubled(kind):
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    fake.fail("POST", TRIG, kind)
    with pytest.raises(TransientError):
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS")
    assert "pbS" in c.stop_intents and c.algo_order(client_id="pbS")["algoStatus"] == "NEW"
    fake.fail("POST", TRIG, kind)
    st = place_stop(Guarded(c, ticking(clock)), BTC, "SELL", 96.0, 5.0, client_id="pbS2")
    assert st["algoStatus"] == "NEW" and len(fake.live_stops(BTC)) == 2 and len(posts(fake, TRIG)) == 2


def test_a_failure_before_an_opening_order_is_sent_says_nothing_was_sent():
    """Review 10-24 (9): the look-up of a new clOrdId or the instrument read failing sent nothing. They are tried again
    for a few seconds; still failing: NotSent, a refusal (never the unknown outcome of a send, never a RateLimited that
    the executor would send again)."""
    c, fake, clock = make(advance=True)
    ready(c, (DOGE,))
    fake.fail("GET", ORDER, "503_before")                      # once: tried again, then sent once
    o = c.market(DOGE, "BUY", 100.0, client_id="pbN")
    assert o["status"] == "FILLED" and len(posts(fake)) == 1 and fake.amt(DOGE) == 100
    fake.fail("GET", ORDER, "503_before", times=99)            # on every try: refused, nothing sent
    t0 = clock.t
    with pytest.raises(DC.NotSent) as e:
        c.market(DOGE, "BUY", 100.0, client_id="pbN1")
    assert not isinstance(e.value, (TransientError, RateLimited)) and e.value.code == DC.NOT_SENT
    assert "pbN1" not in c.sent and len(posts(fake)) == 1 and clock.t - t0 >= 3_000
    fake.fails.clear()
    c.specs.clear()
    c.spec_ms = None
    fake.fail("GET", "/deepcoin/market/instruments", "503_before", times=99)
    with pytest.raises(DC.NotSent):
        c.market(DOGE, "BUY", 100.0, client_id="pbN2")
    fake.fails.clear()
    fake.fail("POST", ORDER, "drop_after")                     # an id this process sent: its look-up failing is unknown
    with pytest.raises(TransientError):
        c.market(DOGE, "BUY", 100.0, client_id="pbM")
    fake.fail("GET", ORDER, "503_before")
    with pytest.raises(TransientError) as e:
        c.market(DOGE, "BUY", 100.0, client_id="pbM")
    assert not isinstance(e.value, DC.NotSent) and len(posts(fake)) == 2


def test_a_read_refused_for_the_rate_is_read_again_and_the_client_paces_itself():
    c, fake, clock = make()
    pauses = []

    def pause(s):
        pauses.append(s)
        clock.t += int(s * 1000)
    c.sleep = pause
    fake.fail("GET", "/deepcoin/account/balances", ("429", 2))
    assert c.account()["totalWalletBalance"] == "10000" and pauses == [2.0] and c.rate_answers == 1
    fake.fail("GET", "/deepcoin/account/balances", ("429", 600))
    pauses.clear()
    with pytest.raises(RateLimited) as e:                      # past RETRY_AFTER_MAX_S: not waited here
        c.account()
    assert e.value.retry_after == 600 and pauses == []
    pauses.clear()
    for _ in range(9):                                        # bills: 5/s (80 %: 4) -> the fifth waits
        c._bills(0, clock.t)
    assert pauses and all(p <= 1.0 for p in pauses)
    assert c.throttle_s() >= 0


def test_the_pace_comes_before_the_timestamp_and_the_signature():
    """2 (Flipster lesson): a full minute's budget is waited out BEFORE DC-ACCESS-TIMESTAMP is made."""
    c, fake, clock = make()
    pauses = []

    def pause(s):
        pauses.append(s)
        clock.t += int(s * 1000)
    c.sleep = pause
    c.hits["balances"] = [clock.t] * 240                       # 300/min (80 %: 240) used up just now
    assert c.account()["totalWalletBalance"] == "10000"       # no 50102 "timestamp expired"
    assert sum(pauses) >= 59


# ------------------------------------------------------------------ specs, prices, account
def test_contract_units_from_the_instruments_list():
    c, fake, clock = make()
    sp = c.spec(BTC)
    assert (sp["qty_step"], sp["min_qty"], sp["tick"], sp["max_leverage"], sp["status"]) == (0.001, 0.001, 0.1, 125.0,
                                                                                            "Trading")
    eth = c.spec(ETH)                                          # lotSz 0.1: a tenth of a contract
    assert (eth["qty_step"], eth["min_qty"], eth["lot_sz"]) == (0.01, 0.01, "0.1")
    assert c._contracts(ETH, 0.057) == pytest.approx(0.5) and str(c._contracts(ETH, 0.057)) == "0.5"
    doge = c.spec(DOGE)
    assert (doge["min_qty"], doge["min_sz"], doge["min_notional"]) == (20.0, "20", 0.0)
    with pytest.raises(TestnetError) as e:
        c.spec("XRPUSDT")
    assert e.value.code == "NO_SYMBOL"
    assert DC.fx(BTC) == "BTC-USDT-SWAP" and DC.bn("BTC-USDT-SWAP") == BTC and DC.bn("BTC-USD-SWAP") == ""
    assert DC.uly(DOGE) == "DOGE-USDT"


def test_prices_klines_and_server_time():
    c, fake, clock = make()
    fake.set_price(BTC, 101.0, mark=100.5)
    assert c.price(BTC) == 101.0 and c.mark(BTC) == 100.5
    t0 = clock.t
    for i in range(1, 2501):                                   # 2500 minutes: three pages of 1000 rows back
        clock.t = t0 + i * 60_000
        fake.set_price(BTC, 100.0 + i % 7)
    rows = c.klines(BTC, t0 + 60_000, clock.t)
    assert len(rows) == 2500 and rows[0][0] == t0 + 60_000 and rows[-1][0] == clock.t
    assert [r[0] for r in rows] == sorted({r[0] for r in rows})
    assert len([x for x in fake.calls if x[2] == "/deepcoin/market/candles"]) == 3
    clock.t += 1234
    assert c.sync_time() == 0
    fake.clock = lambda: clock.t + 700
    assert c.sync_time() == 700


def test_account_in_the_binance_shape_and_garbled_answers_are_errors():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    fake.set_price(BTC, 102.0)
    a = c.account()
    assert a["totalUnrealizedProfit"] == "10" and float(a["totalMarginBalance"]) == pytest.approx(
        float(a["totalWalletBalance"]) + 10)
    assert a["assets"] == [{"asset": "USDT", "walletBalance": a["totalWalletBalance"]}]
    for broken in ([], [{"ccy": "USDT", "bal": "", "unrealizedProfit": "0", "equity": "1", "availBal": "1"}],
                   [{"ccy": "USDT", "bal": "1", "unrealizedProfit": "0", "availBal": "1"}], None, {"x": 1}):
        edit_route(fake, "/deepcoin/account/balances", lambda d, b=broken: b)
        with pytest.raises(TransientError):                   # never $0 from a gap
            c.account()
        fake._route = FakeDeepCoin._route.__get__(fake)
    edit_route(fake, "/deepcoin/account/balances",
               lambda d: d + [{"ccy": "BTC", "bal": "0.5", "unrealizedProfit": "0", "equity": "0.5", "availBal": "0"}])
    assert {"asset": "BTC", "walletBalance": "0.5"} in c.account()["assets"]
    assert c.fee_rate(BTC) == {"taker": 0.0005, "maker": 0.0002, "level": "Lv1"}


def test_one_way_isolated_leverage_and_the_read_back():
    c, fake, clock = make()
    with pytest.raises(TestnetError) as e:                     # not checked yet: no entry
        c.leverage(BTC, 20)
    assert e.value.code == "NOT_ONE_WAY"
    ready(c, (BTC, DOGE))
    assert fake.levs[BTC]["isolated"] == 40 and fake.levs[DOGE]["isolated"] == 30 and c.one_side
    assert c.leverage(BTC, 20) == {"symbol": BTC, "leverage": 20, "marginType": "isolated"}
    assert fake.levs[BTC]["isolated"] == 20
    sent = len(posts(fake, "/deepcoin/account/set-leverage"))
    c.leverage(BTC, 20)                                        # already so: nothing sent
    assert len(posts(fake, "/deepcoin/account/set-leverage")) == sent
    with pytest.raises(TestnetError) as e:
        c.leverage(DOGE, 100)
    assert e.value.code == "LEVERAGE_MAX"
    c.market(BTC, "BUY", 1.0, client_id="pbE")
    with pytest.raises(TestnetError) as e:
        c.leverage(BTC, 10)
    assert e.value.code == "POSITION_OPEN"
    real = fake._route

    def lie(m, p, q, b):                                       # the read-back shows another leverage
        st, raw, h = real(m, p, q, b)
        if p == "/deepcoin/account/leverage-info":
            d = json.loads(raw)
            d["data"]["lever"] = 3
            raw = json.dumps(d).encode()
        return st, raw, h
    fake._route = lie
    with pytest.raises(TransientError) as e:                  # read again after pauses: never a refusal
        c.leverage(DOGE, 10)
    assert e.value.code == "LEVERAGE_MISMATCH"
    fake._route = real
    lines = c.account_setup([BTC, ETH])
    assert all(ok for ok, _ in lines) and "합침(merge)" in lines[0][1] and "격리 레버리지 20" in lines[1][1]


def test_a_lagging_leverage_read_back_is_read_again():
    """Review 10-24 (5): the read-back after set-leverage can lag: read again after pauses, never a refusal."""
    c, fake, clock = make(advance=True)
    fake.lev_lag_ms = 1_500
    ready(c, (BTC, DOGE))
    assert c.lev == {BTC: 40, DOGE: 30} and not c.lev_problems and fake.levs[DOGE]["isolated"] == 30
    assert c.leverage(DOGE, 20)["leverage"] == 20
    fake.lev_lag_ms = 60_000
    with pytest.raises(TransientError) as e:                   # still another value: unknown (tried again), not refused
        c.leverage(DOGE, 25)
    assert e.value.code == DC.MISMATCH


@pytest.mark.parametrize("answer", [("err", 200, "51000", "Parameter lever error"),
                                    ("scode", "199", "LeverageTooHigh:Amount[30]>Leverage[20]"), "503_before"])
def test_a_coin_whose_leverage_cannot_be_set_never_stops_the_start(answer):
    """Review 10-24 (5): isolated() at the start notes a coin it cannot set (a refusal, an undocumented answer, an
    endpoint that does not answer) and returns: the executor starts and protects; leverage() sets it before an entry
    and refuses only that entry when it cannot. The key itself refused (IP, signature): Refused."""
    c, fake, clock = make()
    c.sync_time()
    c.one_way()
    fake.fail("POST", "/deepcoin/account/set-leverage", answer)
    assert c.isolated(ETH) is None and ETH in c.lev_problems and ETH not in c.lev
    c.isolated(BTC)
    assert BTC not in c.lev_problems and c.lev[BTC] == 40
    line = c.account_setup([ETH])[1]
    assert not line[0] and "진입 직전에 다시 맞추고" in line[1]
    fake.fail("POST", "/deepcoin/account/set-leverage", answer)
    with pytest.raises(TestnetError):                         # that entry only
        c.leverage(ETH, 20)
    assert c.leverage(ETH, 20)["leverage"] == 20 and ETH not in c.lev_problems
    fake.fail("POST", "/deepcoin/account/set-leverage", ("err", 401, "50111", "Invalid signature"))
    with pytest.raises(Refused):
        c.isolated(DOGE)


def test_a_coin_in_settlement_is_read_again_before_an_entry():
    """Review 10-24 (6): a state other than live in the cached instruments (the funding settlement passes in moments)
    is read again before an entry; one that stays so still refuses."""
    c, fake, clock = make()
    fake.states.update({DOGE: "settlement", ETH: "suspend"})
    ready(c, (DOGE, ETH))
    assert c.spec(DOGE)["status"] == "settlement" and not c.spec(DOGE)["tradable"]
    fake.states[DOGE] = "live"
    clock.t += 60_000
    assert c.leverage(DOGE, 30)["leverage"] == 30
    with pytest.raises(TestnetError) as e:
        c.leverage(ETH, 30)
    assert e.value.code == "NOT_TRADING" and "suspend" in e.value.msg


def test_a_coin_holding_a_long_and_a_short_at_once_is_an_error_never_netted():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 2.0, client_id="pbL")
    other = DC.DeepCoinClient("dk", "ds", "dp", send=fake, clock_ms=clock, sleep=lambda s: None)
    other.one_side = True
    other.market(BTC, "SELL", 1.0, client_id="pbS")           # a short opened next to the long (by hand)
    with pytest.raises(TransientError, match="롱·숏"):
        c.position(BTC)
    with pytest.raises(TransientError):
        c.positions()
    c2, _, _ = make(fake=fake, clock=clock)
    with pytest.raises(Refused, match="롱·숏"):
        c2.one_way()
    assert not c2.one_side and not c2.account_setup([BTC])[0][0]
    edit_route(fake, "/deepcoin/account/positions", lambda d: [{**r, "mrgPosition": "split"} for r in d][:1])
    with pytest.raises(Refused, match="분할"):
        c2.one_way()


def test_position_shapes_and_garbled_rows_are_errors():
    c, fake, clock = make()
    ready(c, (BTC, ETH))
    assert c.position(BTC)["positionAmt"] == "0" and c.positions() == []
    c.market(ETH, "SELL", 0.37, client_id="pbE")               # 3.7 contracts of 0.1 ETH
    p = c.position(ETH)
    assert (p["positionAmt"], p["marginType"], p["leverage"], p["positionSide"]) == ("-0.37", "isolated", "30",
                                                                                    "short")
    assert [x["symbol"] for x in c.positions()] == [ETH]
    for bad in ({"pos": ""}, {"pos": "-3"}, {"posSide": "net"}, {"pos": "abc"}):
        edit_route(fake, "/deepcoin/account/positions", lambda d, b=bad: [{**r, **b} for r in d])
        with pytest.raises(TransientError):                   # never "flat" from a garbled row
            c.position(ETH)
        fake._route = FakeDeepCoin._route.__get__(fake)
    edit_route(fake, "/deepcoin/account/positions", lambda d: None)
    with pytest.raises(TransientError):
        c.positions()
    fake._route = FakeDeepCoin._route.__get__(fake)
    edit_route(fake, "/deepcoin/account/positions", lambda d: [{**r, "isFollow": True} for r in d])
    assert c.positions() == []                                 # a copied position is not this bot's
    with pytest.raises(TestnetError) as e:
        c.leverage_brackets()
    assert e.value.code == "NO_BRACKETS"


# ------------------------------------------------------------------ orders
def test_market_entry_and_close_bodies_and_read_back():
    c, fake, clock = make()
    ready(c, (BTC, ETH))
    o = c.market(BTC, "BUY", 5.0004, client_id="pbAbcE")      # floored to whole contracts
    body = posts(fake)[-1]
    assert body == {"instId": "BTC-USDT-SWAP", "tdMode": "isolated", "side": "buy", "posSide": "long",
                    "mrgPosition": "merge", "ordType": "market", "sz": "5000", "clOrdId": "pbAbcE"}
    assert (o["status"], o["executedQty"], o["avgPrice"], o["reduceOnly"], o["commission"]) == ("FILLED", "5", "100",
                                                                                                 False, "0.25")
    x = c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbAbcX")
    body = posts(fake)[-1]
    assert (body["side"], body["posSide"], body["reduceOnly"], body["sz"]) == ("sell", "long", True, "5000")
    assert x["status"] == "FILLED" and x["reduceOnly"] is True and fake.amt(BTC) == 0
    s = c.market(ETH, "SELL", 0.05, client_id="pbEthS")       # a short: sell/short, 0.5 contracts
    assert posts(fake)[-1]["sz"] == "0.5" and posts(fake)[-1]["posSide"] == "short" and s["executedQty"] == "0.05"
    c.market(ETH, "BUY", 0.05, reduce_only=True, client_id="pbEthX")
    assert posts(fake)[-1]["side"] == "buy" and posts(fake)[-1]["posSide"] == "short" and fake.amt(ETH) == 0
    for qty, code in ((0.0004, "QTY_ZERO"), (0.005, "QTY_ZERO")):
        with pytest.raises(TestnetError) as e:
            c.market(BTC if qty < 0.001 else ETH, "BUY", qty, client_id="pbTiny")
        assert e.value.code == code
    with pytest.raises(TestnetError) as e:                     # DOGE: at least 20 contracts for an entry
        c.market(DOGE, "BUY", 10.0, client_id="pbDoge")
    assert e.value.code == "QTY_MIN"
    with pytest.raises(TestnetError):
        c.market(BTC, "HOLD", 1.0)


def test_a_partly_filled_market_order_reads_its_filled_part():
    c, fake, clock = make()
    ready(c)
    fake.partial = 0.4
    o = c.market(BTC, "BUY", 5.0, client_id="pbP")
    assert (o["status"], o["executedQty"], o["dcState"]) == ("CANCELED", "2", "canceled") and fake.amt(BTC) == 2
    assert c.order(BTC, client_id="pbP")["executedQty"] == "2"
    st = place_stop(c, BTC, "SELL", 95.0, 2.0, client_id="pbS")
    assert covers(st, 2.0)


def test_an_accepted_order_whose_record_lags_is_never_reported_as_not_executed():
    c, fake, clock = make()
    ready(c)
    fake.order_lag_ms = 60_000
    o = c.market(BTC, "BUY", 5.0, client_id="pbLag")
    assert o["orderId"] and o["status"] == "NEW" and "readBack" in o and fake.amt(BTC) == 5
    with pytest.raises(TransientError):                       # sent by this process: unknown, never "not found" yet
        c.order(BTC, client_id="pbLag")
    clock.t += 60_000
    assert c.order(BTC, order_id=o["orderId"])["status"] == "FILLED"


def test_open_orders_cancel_all_and_reconcile():
    c, fake, clock = make()
    ready(c)
    o = fake._new_order({"instId": "BTC-USDT-SWAP", "sz": "3", "side": "buy", "posSide": "long",
                         "tdMode": "isolated", "clOrdId": "byHand"})          # a resting order placed in the app
    got = c.open_orders(BTC)
    assert [(x["orderId"], x["status"], x["origQty"], x["clientOrderId"]) for x in got] == [(o["ordId"], "NEW",
                                                                                            "0.003", "byHand")]
    c.cancel_all(BTC)
    assert fake.orders[o["ordId"]]["state"] == "canceled" and c.open_orders(BTC) == []
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    rep = DC.reconcile(c, BTC)
    assert rep["problem"] == "position without a protective stop" and not rep["repaired"]
    rep = DC.reconcile(c, BTC, stop_price=95.0)
    assert rep["repaired"] and len(live_stops(c, BTC)) == 1 and DC.reconcile(c, BTC)["problem"] is None


# ------------------------------------------------------------------ client ids: mapping and look-ups
def test_client_ids_map_to_a_deterministic_clordid():
    for cid in ("pbe1a2b3c4d5e6fe", "pbAbc", "x" * 20):
        assert DC.ext_id(cid) == cid
    long_id = "pb0123456789abs3r9f8e7d6c"                     # the executor's stop id: > 20 characters
    assert len(long_id) > 20
    m = DC.ext_id(long_id)
    assert m == DC.ext_id(long_id) and len(m) == 20 and m.isalnum() and m.startswith("pbh") and m != DC.ext_id(
        long_id + "x")
    assert DC.ext_id("pb.x-y_z") != "pb.x-y_z" and DC.ext_id("pb.x-y_z").isalnum()
    fresh = DC.ext_id(None)
    assert len(fresh) == 20 and fresh.isalnum() and fresh != DC.ext_id(None)


UNKNOWN_IDS = pytest.mark.parametrize("unknown_ids", ["empty", "error"])   # an id nobody has: [] or an error answer


@UNKNOWN_IDS
def test_a_lost_answer_is_found_by_its_clordid_also_after_a_restart(unknown_ids):
    c, fake, clock = make()
    fake.unknown_ids = unknown_ids
    ready(c)
    long_id = "pbxr5f4d3c2b1a0fe9d8c7b6"
    fake.fail("POST", "/deepcoin/trade/order", "drop_after")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 5.0, client_id=long_id)
    assert fake.amt(BTC) == 5
    got = c.order(BTC, client_id=long_id)                      # GET order by its clOrdId
    assert got["status"] == "FILLED" and got["clientOrderId"] == DC.ext_id(long_id)
    c2, _, _ = make(fake=fake, clock=clock)                    # a new process: no record at all
    ready(c2)
    assert c2.order(BTC, client_id=long_id)["orderId"] == got["orderId"]
    o = c2.market(BTC, "BUY", 5.0, client_id=long_id)          # the same opening id: looked up, never sent again
    assert o["orderId"] == got["orderId"] and len(posts(fake)) == 1 and fake.amt(BTC) == 5
    c2.forget_order(DC.ext_id(long_id))
    real = fake._route

    def no_get_by_cid(m, p, q, b):                             # GET order finds nothing: the lists still do
        if m == "GET" and p == "/deepcoin/trade/order" and "clOrdId" in q:
            return 200, b'{"code":"0","msg":"","data":[]}', {}
        return real(m, p, q, b)
    fake._route = no_get_by_cid
    assert c2.order(BTC, client_id=long_id)["orderId"] == got["orderId"]


@UNKNOWN_IDS
def test_an_order_that_never_arrived_is_not_found_only_after_the_settle_window(unknown_ids):
    c, fake, clock = make()
    fake.unknown_ids = unknown_ids
    ready(c)
    fake.fail("POST", "/deepcoin/trade/order", "drop_before")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 5.0, client_id="pbNever")
    with pytest.raises(TransientError):
        c.order(BTC, client_id="pbNever")
    with pytest.raises(TransientError):                       # an opening id: never sent twice, not even now
        c.market(BTC, "BUY", 5.0, client_id="pbNever")
    clock.t += DC.SETTLE_MS
    with pytest.raises(TestnetError) as e:
        c.order(BTC, client_id="pbNever")
    assert e.value.code == NOT_FOUND[0] and not isinstance(e.value, TransientError)
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 5.0, client_id="pbNever")
    assert len(posts(fake)) == 1 and fake.amt(BTC) == 0         # the one send that was dropped, never another


def test_a_close_is_sent_again_only_once_its_absence_is_settled_and_sized_from_the_position():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    fake.fail("POST", "/deepcoin/trade/order", "drop_before")
    with pytest.raises(TransientError):
        c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    with pytest.raises(TransientError):                       # inside the window: looked up, never re-sent
        c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    fake.set_price(BTC, 99.0)
    c.market(BTC, "SELL", 2.0, reduce_only=True, client_id="pbCut")         # meanwhile part was closed
    clock.t += DC.SETTLE_MS
    x = c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    assert x["executedQty"] == "3" and posts(fake)[-1]["sz"] == "3000" and fake.amt(BTC) == 0


# ------------------------------------------------------------------ stops: trigger orders
def test_stop_body_place_confirm_move_cancel():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS1")
    body = posts(fake, TRIG)[-1]
    assert body == {"instId": "BTC-USDT-SWAP", "productGroup": "Swap", "sz": "5000", "side": "sell",
                    "posSide": "long", "isCrossMargin": "0", "orderType": "market", "triggerPrice": "95",
                    "triggerPxType": "last", "mrgPosition": "merge", "tdMode": "isolated"}
    assert (st["algoStatus"], st["triggerPrice"], st["quantity"], st["workingType"]) == ("NEW", "95", "5",
                                                                                        "CONTRACT_PRICE")
    stops = live_stops(c, BTC)
    assert len(stops) == 1 and covers(stops[0], 5.0) and stops[0]["reduceOnly"] is True
    assert c.list_delay_ms[st["algoId"]] == 0
    mv = move_stop(c, BTC, "SELL", 97.0, 5.0, [st["algoId"]], client_id="pbS2")
    assert mv["result"] == "moved" and [x["triggerPrice"] for x in live_stops(c, BTC)] == ["97"]
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == "CANCELED"
    assert c.algo_order(client_id="pbS2")["algoId"] == mv["stop"]["algoId"]
    assert not fake.unprotected()
    c.cancel_algo(algo_id=mv["stop"]["algoId"])
    with pytest.raises(TestnetError) as e:                     # cancelled: a second cancel is "not found"
        c.cancel_algo(algo_id=mv["stop"]["algoId"])
    assert e.value.code in NOT_FOUND
    assert c.open_algo_orders(BTC) == []
    short = make()[0]
    ready(short, (ETH,))
    short.market(ETH, "SELL", 0.5, client_id="pbSh")
    place_stop(short, ETH, "BUY", 105.0, 0.5, client_id="pbShS")
    b = posts(short.send, TRIG)[-1]
    assert (b["side"], b["posSide"], b["sz"]) == ("buy", "short", "5")


def test_a_stop_past_the_price_is_refused_before_it_is_sent_or_reads_as_would_trigger():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    with pytest.raises(TestnetError) as e:
        c.stop_close(BTC, "SELL", 101.0, 5.0, client_id="pbS")
    assert e.value.code == WOULD_TRIGGER and not posts(fake, TRIG)
    real = fake._trigger

    def moved(q):                                              # the price moves between the check and the send
        fake.prices[BTC] = 94.0
        return real(q)
    fake._trigger, fake.past_stop = moved, "refuse"
    with pytest.raises(TestnetError) as e:
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS2")
    assert e.value.code == WOULD_TRIGGER
    fake._trigger = real
    fake.prices[BTC] = 100.0
    mv = move_stop(c, BTC, "SELL", 101.0, 5.0, [], client_id="pbS3", close_id="pbX")
    assert mv["result"] == "closed" and fake.amt(BTC) == 0


@pytest.mark.parametrize("own_fills, unknown_ids", [(True, "empty"), (False, "empty"), (True, "error"),
                                                     (False, "error")])
def test_a_fired_stop_reads_as_triggered_with_the_order_it_placed(own_fills, unknown_ids):
    c, fake, clock = make()
    fake.own_fills, fake.unknown_ids = own_fills, unknown_ids
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    clock.t += 5_000
    fake.set_price(BTC, 94.0)
    assert fake.amt(BTC) == 0
    got = c.algo_order(algo_id=st["algoId"])
    assert got["algoStatus"] == "TRIGGERED" and got["actualOrderId"]
    assert (got["actualOrderId"] == st["algoId"]) == own_fills
    fills = c._fills(BTC, T0, clock.t, ord_id=got["actualOrderId"])
    assert len(fills) == 1 and fills[0]["side"] == "sell"


@pytest.mark.parametrize("msg", ["System error, please try again", "Order does not exist"])
def test_a_fired_stops_order_is_found_when_the_fills_under_its_own_id_fail(msg):
    """Review 10-24 (8, probe2 P5): an error from the fills under the stop's own ordId still leaves the order history
    to name the order the stop placed."""
    c, fake, clock = make()
    ready(c, (DOGE,))
    c.market(DOGE, "BUY", 100.0, client_id="pbE")
    st = place_stop(c, DOGE, "SELL", 90.0, 100.0, client_id="pbS")
    fake.set_price(DOGE, 89.0)
    child = next(o["ordId"] for o in fake.orders.values() if o["source"] == "13")
    real = fake._route

    def broken(m, p, q, b):
        if (m, p) == ("GET", "/deepcoin/trade/fills") and f"ordId={st['algoId']}" in q:
            return 200, json.dumps({"code": "51600", "msg": msg, "data": None}).encode(), {}
        return real(m, p, q, b)
    fake._route = broken
    got = c.algo_order(algo_id=st["algoId"])
    assert (got["algoStatus"], got["actualOrderId"]) == ("TRIGGERED", child)


def test_a_stop_looked_up_after_a_restart_skips_a_coin_that_cannot_be_read():
    """Review 10-24 (10): a stop id this process has not seen is looked for on every coin; one coin's error does not end
    the scan, and with a coin unread "not found" is never the answer."""
    c, fake, clock = make()
    ready(c, (DOGE,))
    c.market(DOGE, "BUY", 100.0, client_id="pbE")
    st = place_stop(c, DOGE, "SELL", 90.0, 100.0, client_id="pbS")
    real = fake._route

    def eth_down(m, p, q, b):
        if m == "GET" and p.startswith("/deepcoin/trade/trigger-orders") and "ETH-USDT-SWAP" in q:
            return 503, b"<html>busy</html>", {}
        return real(m, p, q, b)
    fake._route = eth_down
    after = make(fake=fake, clock=clock)[0]                    # a restart: the stop's coin is not known
    assert after.algo_order(algo_id=st["algoId"])["algoStatus"] == "NEW"
    c.cancel_algo(algo_id=st["algoId"])
    assert make(fake=fake, clock=clock)[0].algo_order(algo_id=st["algoId"])["algoStatus"] == "CANCELED"
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
    assert DC.trigger_source(1, 95.0, {"last": [96.0], "mark": [94.5]})["verdict"] == "마크 가격"


def test_a_second_stop_firing_without_a_position_reads_as_rejected_never_fired():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    a = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS1")
    b = place_stop(c, BTC, "SELL", 94.0, 5.0, client_id="pbS2")
    fake.set_price(BTC, 93.0)
    got = {x: c.algo_order(algo_id=s["algoId"])["algoStatus"] for x, s in (("a", a), ("b", b))}
    assert got == {"a": "TRIGGERED", "b": "REJECTED"} and fake.amt(BTC) == 0


@UNKNOWN_IDS
def test_a_stop_is_cancelled_only_on_an_explicit_record(unknown_ids):
    c, fake, clock = make()
    fake.unknown_ids = unknown_ids
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    fake.trigger_lag_ms = 10 ** 9                              # the list no longer shows it, no history row: ours
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == DC.UNCONFIRMED
    other, _, _ = make(fake=fake, clock=clock)
    with pytest.raises(TestnetError) as e:                     # someone else's id: not found, never "cancelled"
        other.algo_order(algo_id=st["algoId"])
    assert e.value.code == NOT_FOUND[0]
    c.cancel_algo(algo_id=st["algoId"])
    for broken in ({"errorCode": ""}, {"triggerTime": None}):
        edit_route(fake, "/deepcoin/trade/trigger-orders-history", lambda d, b=broken: [{**r, **b} for r in d])
        with pytest.raises(TransientError):                   # a gap in the record: unknown, never "cancelled"
            c.algo_order(algo_id=st["algoId"])
        fake._route = FakeDeepCoin._route.__get__(fake)
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == "CANCELED"


@pytest.mark.parametrize("history_lag", [0, 5_000])
def test_a_new_stop_the_pending_list_shows_late_is_waited_for(history_lag):
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    fake.trigger_lag_ms, fake.trigger_history_lag_ms = 2_000, history_lag
    t0 = clock.t
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbLag")
    assert st["algoStatus"] == "NEW" and 2_000 <= clock.t - t0 <= DC.PROTECT_WAIT_S * 1000
    assert c.list_delay_ms[st["algoId"]] >= 2_000


def test_a_stop_the_pending_list_does_not_show_is_never_confirmed():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    fake.trigger_lag_ms = 30_000
    t0 = clock.t
    with pytest.raises(ProtectionError, match="UNCONFIRMED"):
        place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbLag")
    assert clock.t - t0 <= DC.PROTECT_WAIT_S * 1000 and len(fake.live_stops(BTC)) == 1


def test_a_new_stop_cancelled_behind_a_lagging_history_never_lets_a_move_cancel_the_old_stop():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    old = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS1")
    fake.kill_new_stops, fake.trigger_history_lag_ms = True, 60_000
    with pytest.raises(ProtectionError, match="UNCONFIRMED"):
        move_stop(c, BTC, "SELL", 97.0, 5.0, [old["algoId"]], client_id="pbS2")
    assert [t["ordId"] for t in fake.live_stops(BTC)] == [old["algoId"]] and not fake.unprotected()
    clock.t += 60_000                                          # the history catches up: cancelled, on its record
    assert c.algo_order(client_id="pbS2")["algoStatus"] == "CANCELED"


def test_a_stop_whose_answer_was_lost_is_found_by_what_was_sent_never_an_older_one():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    other = DC.DeepCoinClient("dk", "ds", "dp", send=fake, clock_ms=clock, sleep=lambda s: None)
    old = other.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbByHand")      # an identical stop resting before
    clock.t += 60_000
    fake.fail("POST", TRIG, "drop_after")
    with pytest.raises(TransientError):
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbLostStop")
    got = c.algo_order(client_id="pbLostStop")
    assert got["algoId"] != old["algoId"] and got["algoStatus"] == "NEW" and len(fake.live_stops(BTC)) == 2
    assert old["algoId"] in c.stop_intents["pbLostStop"]["before"]
    again = c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbLostStop")       # never a second copy
    assert again["algoId"] == got["algoId"] and len(posts(fake, TRIG)) == 2
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
    fake.fail("POST", TRIG, "drop_before")
    with pytest.raises(TransientError):
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS")
    with pytest.raises(TransientError):
        c.algo_order(client_id="pbS")
    with pytest.raises(TransientError):                       # inside the window: never a second copy
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS")
    clock.t += DC.SETTLE_MS
    with pytest.raises(TestnetError) as e:
        c.algo_order(client_id="pbS")
    assert e.value.code == NOT_FOUND[0]
    st = c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS")
    assert st["algoStatus"] == "NEW" and len(posts(fake, TRIG)) == 2 and len(fake.live_stops(BTC)) == 1


def test_two_stops_refused_stops_the_move_with_the_old_stop_in_place():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    old = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS1")
    fake.two_stops = False
    with pytest.raises(TestnetError):
        move_stop(c, BTC, "SELL", 97.0, 5.0, [old["algoId"]], client_id="pbS2")
    assert [t["ordId"] for t in fake.live_stops(BTC)] == [old["algoId"]]


def test_other_trigger_kinds_are_never_counted_as_stops_nor_cancelled():
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    tpsl = {"instType": "SWAP", "instId": "BTC-USDT-SWAP", "ordId": "999", "triggerPx": "0", "ordPx": "0", "sz": "0",
            "ordType": "", "side": "sell", "posSide": "long", "tdMode": "isolated", "triggerOrderType": "TPSL",
            "triggerPxType": "last", "lever": "40", "slTriggerPrice": "90", "cTime": str(T0), "uTime": str(T0)}
    opening = {**tpsl, "ordId": "998", "triggerPx": "120", "sz": "5", "side": "buy", "triggerOrderType": "Conditional"}
    edit_route(fake, "/deepcoin/trade/trigger-orders-pending", lambda d: d + [tpsl, opening])
    algos = {a["algoId"]: a["orderType"] for a in c.open_algo_orders(BTC)}
    assert algos == {st["algoId"]: "STOP_MARKET", "999": "CONDITIONAL", "998": "CONDITIONAL"}
    assert [a["algoId"] for a in live_stops(c, BTC)] == [st["algoId"]]
    c.cancel_all_algo(BTC)
    cancelled = [b["ordId"] for b in posts(fake, "/deepcoin/trade/cancel-trigger-order")]
    assert st["algoId"] in cancelled and "999" not in cancelled


PENDING = "/deepcoin/trade/trigger-orders-pending"


def test_a_trigger_row_whose_kind_or_side_cannot_be_read_is_an_error_never_no_stop():
    """Review 10-24 (3, probe1 P1): a resting stop read as "not a stop" makes the executor place more stops or close
    a protected position. A row of a kind that can be ours whose side or posSide is unreadable, or a row without its
    kind (a pending row's own ordType is the price type, never the kind), is an error."""
    c, fake, clock = make()
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    for bad in ({"posSide": ""}, {"side": None}, {"posSide": "both"}, {"triggerOrderType": ""},
                {"triggerOrderType": None, "ordType": "market"}, {"triggerOrderType": "conditional?"}):
        edit_route(fake, PENDING, lambda d, b=bad: [{**r, **b} for r in d])
        with pytest.raises(TransientError):
            live_stops(c, BTC)
        with pytest.raises(TransientError):                   # the look-up of a lost answer never skips it either
            c._search_stop("pbS")
        fake._route = FakeDeepCoin._route.__get__(fake)
    tpsl = {"instType": "SWAP", "instId": "BTC-USDT-SWAP", "ordId": "999", "triggerPx": "0", "ordPx": "0", "sz": "0",
            "ordType": "", "side": "sell", "posSide": "long", "tdMode": "isolated", "triggerPxType": "last",
            "lever": "40", "slTriggerPrice": "90", "cTime": str(T0), "uTime": str(T0)}     # a TP/SL without its kind
    edit_route(fake, PENDING, lambda d: d + [tpsl])
    with pytest.raises(TransientError):
        c.open_algo_orders(BTC)
    fake._route = FakeDeepCoin._route.__get__(fake)
    edit_route(fake, PENDING, lambda d: d + [{**tpsl, "triggerOrderType": "TPSL", "posSide": ""}])
    assert [a["algoId"] for a in live_stops(c, BTC)] == [st["algoId"]]     # another's kind: its side is not needed
    fake._route = FakeDeepCoin._route.__get__(fake)
    c.cancel_algo(algo_id=st["algoId"])
    edit_route(fake, "/deepcoin/trade/trigger-orders-history", lambda d: [{**r, "ordType": ""} for r in d])
    with pytest.raises(TransientError):                       # a history row without its kind: never "cancelled"
        c.algo_order(algo_id=st["algoId"])
    fake._route = FakeDeepCoin._route.__get__(fake)
    assert c.algo_order(algo_id=st["algoId"])["algoStatus"] == "CANCELED"


def history_row(symbol, ordId, ms, **kw):
    """A trigger-history row as the docs show it (cTime in seconds), of a stop that ended long ago by default."""
    return {"instType": "SWAP", "instId": DC.fx(symbol), "ordId": ordId, "px": "0", "sz": "5", "triggerPx": "50",
            "triggerPxType": "last", "ordType": "Conditional", "side": "sell", "posSide": "net", "tdMode": "cross",
            "lever": "1", "triggerTime": "0", "uTime": str(ms), "cTime": str(ms // 1000), "errorCode": "0",
            "errorMsg": "", "_ended": ms, **kw}


@pytest.mark.parametrize("old", [{}, {"posSide": "", "side": None}, {"ordType": "", "sz": "x"}])
def test_a_lost_stop_is_found_next_to_an_old_history_row_that_cannot_be_ours(old):
    """probe5 N5 (re-review 10-24): a readable row that cannot be ours (posSide net, a documented value) or a row made
    long before the send is "not it": it never turns a lost stop answer into an unknown outcome (the executor would
    close a new position whose stop rests)."""
    c, fake, clock = make(advance=True)
    ready(c, (DOGE,))
    c.market(DOGE, "BUY", 100.0, client_id="pbn5entry")
    fake.trig_hist["1"] = history_row(DOGE, "1", T0 - 10 ** 6, **old)
    fake.fail("POST", TRIG, "drop_after")
    st = place_stop(Guarded(c, ticking(clock)), DOGE, "SELL", 90.0, 100.0, client_id="pbn5stop")
    assert st["algoStatus"] == "NEW" and len(posts(fake, TRIG)) == 1 and len(fake.live_stops(DOGE)) == 1
    fake.trig_hist["2"] = history_row(DOGE, "2", clock.t, posSide="")      # made inside a send's window: may be it
    c.forget_stop("pbn5stop")
    with pytest.raises(TransientError):
        c._search_stop("pbn5stop")


def test_rows_that_cannot_be_ours_or_belong_to_another_coin_never_break_the_stop_list():
    """Re-review 10-24 (2): readable and not ours (posSide net, another kind) is not a stop; another coin's row is not
    in this coin's answer; an unreadable row on a coin without a position protects nothing and is listed as not a
    stop. An unreadable row that may be our stop on a coin with a position (or a stop this process placed) is still an
    error, never "no stop"."""
    c, fake, clock = make()
    ready(c, (BTC, ETH))
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    st = place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    base = {"instType": "SWAP", "ordPx": "0", "sz": "5", "ordType": "", "side": "sell", "posSide": "long",
            "tdMode": "isolated", "triggerPxType": "last", "lever": "30", "cTime": str(T0), "uTime": str(T0)}
    net = {**base, "instId": "BTC-USDT-SWAP", "ordId": "901", "triggerPx": "90", "triggerOrderType": "Conditional",
           "posSide": "net"}
    garbled_eth = {**base, "instId": "ETH-USDT-SWAP", "ordId": "902", "triggerPx": "x", "posSide": ""}   # no kind
    garbled_btc = {**garbled_eth, "instId": "BTC-USDT-SWAP", "ordId": "903"}
    edit_route(fake, PENDING, lambda d: d + [net, garbled_eth])            # every coin's answer carries both
    assert [a["algoId"] for a in live_stops(c, BTC)] == [st["algoId"]]
    assert {a["algoId"]: a["orderType"] for a in c.open_algo_orders(BTC)} == {st["algoId"]: "STOP_MARKET",
                                                                                  "901": "CONDITIONAL"}
    eth = c.open_algo_orders(ETH)                              # flat: the garbled row is listed, never a stop
    assert [(a["algoId"], a["orderType"], bool(a.get("dcUnreadable"))) for a in eth] == [("902", "CONDITIONAL", True)]
    assert live_stops(c, ETH) == []
    fake._route = FakeDeepCoin._route.__get__(fake)
    edit_route(fake, PENDING, lambda d: d + [garbled_btc])
    with pytest.raises(TransientError):                       # BTC holds a position: it may be its stop
        live_stops(c, BTC)
    fake._route = FakeDeepCoin._route.__get__(fake)
    c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    edit_route(fake, PENDING, lambda d: [{**r, "posSide": ""} for r in d])
    with pytest.raises(TransientError):                       # flat, but a stop this process placed
        live_stops(c, BTC)
    fake._route = FakeDeepCoin._route.__get__(fake)


# ------------------------------------------------------------------ 429 and the protective budget
def test_an_opening_order_answered_429_is_never_sent_twice():
    c, fake, clock = make()
    ready(c)
    fake.fail("POST", "/deepcoin/trade/order", "429")
    with pytest.raises(TransientError):
        c.market(BTC, "BUY", 1.0, client_id="pbE2")
    g = Guarded(c, lambda s: None, retries=4)
    fake.fail("POST", "/deepcoin/trade/order", "429_after")   # it ran: the look-up finds it
    o = g.market(BTC, "BUY", 1.0, client_id="pbE3")
    assert o["status"] == "FILLED" and fake.amt(BTC) == 1 and len(posts(fake)) == 2


def test_a_close_answered_429_that_ran_is_found_and_reads_filled():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 2.0, client_id="pbE")
    fake.order_lag_ms = 3_000
    fake.fail("POST", "/deepcoin/trade/order", "429_after")
    o = c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbX1")
    assert (o["status"], o["executedQty"]) == ("FILLED", "1") and fake.amt(BTC) == 1 and len(posts(fake)) == 2


def test_a_close_answered_429_not_found_in_time_stays_unknown_and_never_goes_past_the_position():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbE")
    fake.order_lag_ms = 40_000                                 # shown only after the settle window
    fake.fail("POST", "/deepcoin/trade/order", "429_after")
    t0 = clock.t
    with pytest.raises(DC.RateLimitedUnknown):
        c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbX")
    assert clock.t - t0 <= DC.PROTECT_WAIT_S * 1000 and fake.amt(BTC) == 0
    with pytest.raises(TransientError):
        c.order(BTC, client_id="pbX")
    fake.order_lag_ms = 10 ** 9
    clock.t += DC.SETTLE_MS
    with pytest.raises(TestnetError) as e:                     # sent again only up to the position now: none left
        c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbX")
    assert e.value.code == -2022 and len(posts(fake)) == 2


def test_a_stop_answered_429_that_rests_is_found_and_never_sent_twice():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbE")
    fake.fail("POST", TRIG, "429_after")
    st = place_stop(c, BTC, "SELL", 95.0, 1.0, client_id="pbS1")
    assert st["algoStatus"] == "NEW" and len(fake.live_stops(BTC)) == 1 and len(posts(fake, TRIG)) == 1


def test_a_stop_whose_429_was_a_refusal_is_sent_once_more():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbE")
    g = Guarded(c, ticking(clock), retries=4)
    fake.fail("POST", TRIG, "429")                             # refused: nothing placed
    t0 = clock.t
    st = place_stop(g, BTC, "SELL", 95.0, 1.0, client_id="pbS1")
    assert st["algoStatus"] == "NEW" and [t["ordId"] for t in fake.live_stops(BTC)] == [st["algoId"]]
    assert len(posts(fake, TRIG)) == 2 and clock.t - t0 <= DC.PROTECT_WAIT_S * 1000
    assert c.stop_intents["pbS1"]["sends"] == 2
    fake.fail("POST", "/deepcoin/trade/order", "429", times=2)  # a close is still never sent again by the client
    with pytest.raises(DC.RateLimitedUnknown):
        c.market(BTC, "SELL", 1.0, reduce_only=True, client_id="pbX")
    assert len(posts(fake)) == 2 and fake.amt(BTC) == 1


def test_a_stop_answered_429_that_ran_behind_a_lagging_list_may_rest_twice_never_more():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 1.0, client_id="pbE")
    fake.trigger_lag_ms = 3_000
    fake.fail("POST", TRIG, "429_after")
    st = place_stop(c, BTC, "SELL", 95.0, 1.0, client_id="pbS1")
    assert st["algoStatus"] == "NEW" and len(posts(fake, TRIG)) == 2 and len(fake.live_stops(BTC)) == 2
    assert c.algo_order(client_id="pbS1")["algoStatus"] == "NEW"


def test_protective_calls_end_within_their_budget():
    c, fake, clock = make(advance=True)
    ready(c)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    real = fake._trigger

    def throttled(q):                                          # from the stop's 429 on, its look-ups are throttled too
        fake.fail("GET", "/deepcoin/trade/trigger-orders", ("429", 3), times=100)
        return 429, b'{"code":"429","msg":"Too Many Requests"}', {"Retry-After": "3"}
    fake._trigger = throttled
    t0 = clock.t
    with pytest.raises(DC.RateLimitedUnknown):
        c.stop_close(BTC, "SELL", 95.0, 5.0, client_id="pbS")
    assert 3_000 <= clock.t - t0 <= DC.PROTECT_WAIT_S * 1000
    fake.fails.clear()
    fake._trigger = real
    fake.fail("POST", "/deepcoin/trade/order", ("429", 60))
    t0 = clock.t
    with pytest.raises(RateLimited):
        c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    assert clock.t - t0 <= 1_000 and fake.amt(BTC) == 5


# ------------------------------------------------------------------ missing fields
def strip_field(fake, symbol, field):
    edit_route(fake, "/deepcoin/market/instruments",
               lambda d: [{k: v for k, v in r.items() if not (r["instId"] == DC.fx(symbol) and k == field)}
                          for r in d])


def test_a_missing_entry_only_field_refuses_that_coins_entries_only():
    c, fake, clock = make()
    ready(c, (BTC, DOGE))
    c.market(DOGE, "BUY", 100.0, client_id="pbD")             # opened before the value went missing
    strip_field(fake, DOGE, "minSz")
    c.specs.clear()
    c.spec_ms = None
    sp = c.spec(DOGE)
    assert sp["min_sz"] is None and "minSz" in sp["problem"] and c.spec(BTC)["problem"] is None
    assert "없음 → 새 진입 안 함" in DC.specs_text(c) and "BTCUSDT: 상태 Trading" in DC.specs_text(c)
    for call in (lambda: c.leverage(DOGE, 10), lambda: c.market(DOGE, "BUY", 100.0, client_id="pbD2")):
        with pytest.raises(TestnetError) as e:
            call()
        assert e.value.code == "BAD_SPEC" and "새 진입" in e.value.msg
    assert place_stop(c, DOGE, "SELL", 95.0, 100.0, client_id="pbDs")["algoStatus"] == "NEW"
    assert c.market(DOGE, "SELL", 100.0, reduce_only=True, client_id="pbDx")["status"] == "FILLED"
    assert not c.account_setup([DOGE])[1][0]
    d = DC.DeepCoinDrill(c, wait=lambda s: None, elapsed=lambda: clock.t / 1000)
    with pytest.raises(AssertionError):
        d.check()
    step = next(r for r in d.log if r["step"].startswith("상품 정보"))
    assert not step["ok"] and "minSz" in step["detail"][DOGE]["error"]
    for field in ("lever", "maxMktSz"):
        strip_field(fake, BTC, field)
        c.spec_ms = None
        c._load_instruments()
        assert field in c.spec(BTC)["problem"]


def test_a_missing_unit_is_bad_spec_for_that_coin_only():
    c, fake, clock = make()
    strip_field(fake, ETH, "ctVal")
    with pytest.raises(TestnetError) as e:
        c.spec(ETH)
    assert e.value.code == "BAD_SPEC" and "ctVal" in e.value.msg
    assert c.spec(BTC)["ct_val"] == "0.001"
    assert "ETHUSDT: 상품 정보를 쓸 수 없습니다" in DC.specs_text(c)


def test_the_stop_list_and_records_are_never_empty_from_a_garbled_answer():
    c, fake, clock = make()
    ready(c)
    for path in ("/deepcoin/trade/trigger-orders-pending", "/deepcoin/trade/v2/orders-pending"):
        edit_route(fake, path, lambda d: None)
        with pytest.raises(TransientError):
            c.open_algo_orders(BTC) if "trigger" in path else c.open_orders(BTC)
        fake._route = FakeDeepCoin._route.__get__(fake)
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    place_stop(c, BTC, "SELL", 95.0, 5.0, client_id="pbS")
    edit_route(fake, "/deepcoin/trade/trigger-orders-pending", lambda d: [{**r, "triggerPx": ""} for r in d])
    with pytest.raises(TransientError):                       # a resting stop's level never reads as 0
        c.open_algo_orders(BTC)


# ------------------------------------------------------------------ fills, P&L, funding
def test_fills_carry_deepcoins_own_pnl_checked_against_the_fill_prices():
    c, fake, clock = make()
    ready(c, (ETH,))
    t0 = clock.t
    c.market(ETH, "SELL", 1.0, client_id="pbE")                # 10 contracts short at 100
    clock.t += 60_000
    fake.set_price(ETH, 95.0)
    c.market(ETH, "BUY", 0.4, reduce_only=True, client_id="pbX1")
    clock.t += 60_000
    fake.set_price(ETH, 90.0)
    c.market(ETH, "BUY", 0.6, reduce_only=True, client_id="pbX2")
    fills = c.user_trades(ETH, t0, clock.t)
    got = [(f["side"], f["qty"], f["realizedPnl"], f["realizedSource"], f.get("realizedCheck")) for f in fills]
    assert got == [("SELL", "1", "0", "open", None), ("BUY", "0.4", "2", "pnl", "ok"), ("BUY", "0.6", "6", "pnl", "ok")]
    assert sum(float(f["commission"]) for f in fills) == pytest.approx(0.05 + 0.019 + 0.027)
    assert fake.wallet == pytest.approx(10_000 + 8 - 0.096)
    late = c.user_trades(ETH, t0 + 90_000, clock.t)            # a window holding only the last close: its own pnl
    assert [(f["realizedPnl"], f["realizedSource"], f["realizedCheck"]) for f in late] == [("6", "pnl", "pnl")]


def test_a_pnl_net_of_fees_or_a_missing_record_is_never_a_final_number():
    c, fake, clock = make()
    fake.pnl_net_of_fees = True
    ready(c)
    t0 = clock.t
    c.market(BTC, "BUY", 5.0, client_id="pbE")
    clock.t += 60_000
    fake.set_price(BTC, 110.0)
    c.market(BTC, "SELL", 5.0, reduce_only=True, client_id="pbX")
    fills = c.user_trades(BTC, t0, clock.t)
    assert fills[-1]["realizedCheck"] == "mismatch"             # 50 by the fill prices, 49.725 by the pnl
    fake.pnl_net_of_fees = False
    real = fake._route

    def no_record(m, p, q, b):                                  # the closing order's record is not readable yet
        if m == "GET" and p == "/deepcoin/trade/order":
            return 200, b'{"code":"0","msg":"","data":[]}', {}
        return real(m, p, q, b)
    fake._route = no_record
    fills = c.user_trades(BTC, t0, clock.t)
    assert (fills[-1]["realizedPnl"], fills[-1]["realizedSource"], fills[-1]["realizedCheck"]) == ("50", "replay",
                                                                                                    "unchecked")
    late = c.user_trades(BTC, clock.t, clock.t)                 # the close alone, no record: unknown, never a 0
    assert (late[0]["realizedSource"], late[0]["realizedCheck"]) == ("unknown", "mismatch")


def test_a_full_fills_page_is_read_again_in_halves_and_edges_are_kept():
    c, fake, clock = make()
    ready(c, (DOGE,))
    t0 = clock.t
    for i in range(70):
        c.market(DOGE, "BUY", 20.0, client_id=f"pbB{i}")
        clock.t += 1
        c.market(DOGE, "SELL", 20.0, reduce_only=True, client_id=f"pbC{i}")
        clock.t += 1
    fills = c.user_trades(DOGE, t0, clock.t - 1)
    assert len(fills) == 140 and len({f["id"] for f in fills}) == 140
    last = max(f["time"] for f in fills)
    assert [f["time"] for f in c.user_trades(DOGE, last, last)] == [last]        # begin / end exclusive: padded
    edit_route(fake, "/deepcoin/trade/fills", lambda d: d + d[:1] * 100)
    with pytest.raises(TransientError):                        # a server that ignores the window: an error
        c.user_trades(DOGE, t0, clock.t)


def test_funding_from_the_bills_and_no_transfer_rows():
    c, fake, clock = make()
    ready(c)
    t0 = clock.t
    for i in range(130):                                       # more than one page of bills
        clock.t += 1_000
        fake.add_funding(BTC, -0.5 if i % 2 else 0.25)
    rows = c.income(BTC, None, t0, clock.t)
    assert len(rows) == 130 and rows[0]["incomeType"] == "FUNDING_FEE" and rows[0]["income"] == "0.25"
    assert len({r["tranId"] for r in rows}) == 130
    assert c.income(None, "TRANSFER", t0, clock.t) == []
    assert c.bill_types(t0, clock.t) == {"7": 130}
    edit_route(fake, "/deepcoin/account/bills", lambda d: sorted(d, key=lambda b: -int(b["ts"]))[:100]
               if d and len(d) == 100 else d)
    real = fake._route

    def newer(m, p, q, b):                                     # a cursor read the other way round: an error
        if p == "/deepcoin/account/bills" and "before" in q:
            q = q.replace("before", "after")
        return real(m, p, q, b)
    fake._route = newer
    with pytest.raises(TransientError):
        c.income(BTC, None, t0, clock.t)


# ------------------------------------------------------------------ keys and gates
def test_keys_gates_and_reuse_refusals():
    assert DC.trading_keys("mainnet", LIVE_ENV) == ("dk", "ds", "dp")
    with pytest.raises(Refused, match="테스트넷"):
        DC.trading_keys("testnet", LIVE_ENV)
    with pytest.raises(Refused, match=FLAG):
        DC.trading_keys("mainnet", {**LIVE_ENV, FLAG: ""})
    with pytest.raises(Refused):
        DC.trading_keys("mainnet", {**LIVE_ENV, "DEEPCOIN_LIVE_SECRET": ""})
    with pytest.raises(Refused, match="PASSPHRASE"):
        DC.trading_keys("mainnet", {**LIVE_ENV, "DEEPCOIN_LIVE_PASSPHRASE": " "})
    with pytest.raises(Refused, match="같은 값"):
        DC.trading_keys("mainnet", {**LIVE_ENV, "DEEPCOIN_LIVE_PASSPHRASE": "ds"})
    for name in ("BINANCE_API_KEY", "LIVE_API_KEY", "TESTNET_API_SECRET", "BYBIT_LIVE_API_KEY", "MEXC_LIVE_SECRET",
                 "WOOXPRO_LIVE_KEY", "WOOXPRO_LIVE_MEMO", "FLIPSTER_LIVE_KEY", "FLIPSTER_LIVE_SECRET"):
        with pytest.raises(Refused):
            DC.trading_keys("mainnet", {**LIVE_ENV, name: "dk"})
    with pytest.raises(Refused, match="paper"):
        DC.trading_keys("mainnet", LIVE_ENV, {"BINANCE_API_KEY": "ds"})
    c, kc = DC.clients("mainnet", LIVE_ENV)
    assert type(c) is DC.DeepCoinClient and isinstance(kc, DC.DeepCoinKeyCheckClient) and kc.attested
    assert (c.key, c.secret, c.passphrase) == ("dk", "ds", "dp")


def test_the_owners_statement_is_required():
    c, kc = DC.clients("mainnet", LIVE_ENV)
    DC.check_executor_keys("mainnet", c, kc, LIVE_ENV, {})
    env = {k: v for k, v in LIVE_ENV.items() if k != DC.KEY_CHECKED}
    c2, kc2 = DC.clients("mainnet", env)
    with pytest.raises(Refused, match=DC.KEY_CHECKED):
        DC.check_executor_keys("mainnet", c2, kc2, env, {})
    with pytest.raises(Refused):
        DC.check_executor_keys("mainnet", c, c, LIVE_ENV, {})                # the order client is no key check
    other = DC.DeepCoinClient("dk", "ds", "other")
    with pytest.raises(Refused, match="PASSPHRASE"):
        DC.check_executor_keys("mainnet", other, kc, LIVE_ENV, {})
    fake = FakeDeepCoin()
    fake.clock = Clock()
    kc3 = DC.DeepCoinKeyCheckClient("dk", "ds", "dp", send=fake, clock_ms=fake.clock, sleep=lambda s: None,
                                    attested=True)
    perm = kc3.api_restrictions()
    assert check_permissions(perm) == [] and perm["warnings"] and DC.KEY_CHECKED in perm["warnings"][0]
    kc3.attested = False
    assert any(DC.KEY_CHECKED in p for p in check_permissions(kc3.api_restrictions()))


def test_refuse_unless_allowed():
    c, kc = DC.clients("mainnet", LIVE_ENV)
    DC.refuse_unless_allowed("mainnet", c)
    with pytest.raises(Refused):
        DC.refuse_unless_allowed("testnet", c)
    with pytest.raises(Refused):
        DC.refuse_unless_allowed("mainnet", kc)                  # the key-check class never trades
    with pytest.raises(Refused):
        DC.refuse_unless_allowed("mainnet", DC.public_client())

    class Other(DC.DeepCoinClient):
        HOSTS = ("api.deepcoin.com", "evil.example")
    with pytest.raises(Refused):
        DC.refuse_unless_allowed("mainnet", Other("dk", "ds", "dp"))


def test_agents_never_import_the_module():
    root = ROOT / "paperbot"
    for p in list(root.glob("agents*.py")) + list(root.glob("rooms*.py")) + list((root / "agents").glob("**/*.py")):
        assert "deepcoin" not in p.read_text(encoding="utf-8"), p


def test_the_live_config_the_wrapper_and_the_env_example():
    cfg = ExecConfig.from_file(str(ROOT / "deploy" / "executor.live-deepcoin.json"))
    assert not cfg.problems()
    assert (cfg.exchange, cfg.mode, cfg.db, cfg.paper_db, cfg.account) == (
        "deepcoin", "mainnet", "/var/lib/paperbot/exec/executor-deepcoin-live.db", "/var/lib/paperbot/combo/vwap.db",
        "COMBO@mix")
    assert cfg.net_cost() == {"taker_fee": 0.0005, "slippage": 0.0002}
    base = json.loads((ROOT / "deploy" / "executor.live-flipster.json").read_text(encoding="utf-8"))
    mine = json.loads((ROOT / "deploy" / "executor.live-deepcoin.json").read_text(encoding="utf-8"))
    assert mine["net_costs"].pop("deepcoin") == {"taker_fee": 0.0005, "slippage": 0.0002}
    # owners 10-25 night: its size from its own balance, 40 % margin at every entry (deploy/size_switch.py)
    assert (mine.pop("size_from"), mine.pop("margin_frac")) == ("equity", 0.4)
    assert (cfg.size_from, cfg.margin_frac) == ("equity", 0.4)
    assert {k: v for k, v in mine.items() if k not in ("exchange", "db")} == \
        {k: v for k, v in base.items() if k not in ("exchange", "db")}
    sh = (ROOT / "deploy" / "paperbot-exec.sh").read_text(encoding="utf-8")
    assert "  deepcoin) shift ;;" in sh and "bybit|mexc|wooxpro|flipster) shift" in sh
    env = (ROOT / "deploy" / "executor.env.example").read_text(encoding="utf-8")
    for name in ("DEEPCOIN_LIVE_KEY", "DEEPCOIN_LIVE_SECRET", "DEEPCOIN_LIVE_PASSPHRASE", "DEEPCOIN_LIVE_KEY_CHECKED"):
        assert f"\n{name}=\n" in env


# ------------------------------------------------------------------ the drill
def drill_world(**kw):
    c, fake, clock = make(**kw)
    fake.prices[DOGE] = fake.marks[DOGE] = 0.2
    return c, fake, clock


@pytest.mark.parametrize("own_fills, side, unknown_ids", [(False, 1, "empty"), (True, 1, "error"),
                                                           (False, -1, "error"), (True, -1, "empty")])
def test_drill_check_and_order_cycle_with_the_trigger_test(own_fills, side, unknown_ids):
    c, fake, clock = drill_world()
    fake.own_fills, fake.unknown_ids = own_fills, unknown_ids
    kc = DC.DeepCoinKeyCheckClient("dk", "ds", "dp", send=fake, clock_ms=clock, sleep=lambda s: None, attested=True)
    ours = round(0.2 * (1 + side * 0.004), 6)                  # 0.4 % our way

    def wait(s):
        clock.t += int(s * 1000)
        stops = [float(t["triggerPx"]) for t in fake.live_stops(DOGE)]
        if fake.amt(DOGE) and len(stops) == 1 and side * (0.2 - stops[0]) > 0:
            fake.set_price(DOGE, ours)                         # the test stop goes past the entry (the profit side)
        elif fake.amt(DOGE) and len(stops) == 1 and side * (stops[0] - 0.2) > 0:
            fake.set_price(DOGE, 0.2, mark=ours)               # ... the last price comes back to it (not the mark)
    lines = []
    d = DC.DeepCoinDrill(c, symbol=DOGE, side=side, keycheck=kc, wait=wait, trigger_wait_s=600,
                         elapsed=lambda: clock.t / 1000, say=lines.append)
    ok = DC.run_drill(c, d, "drill", True, pause=lambda s: None)
    fails = [r for r in d.log if not r["ok"]]
    assert ok and not fails, fails
    this, other = ("롱", "숏(--side short)") if side > 0 else ("숏", "롱(--side long)")
    assert lines[-1] == f"끝: drill 모두 [OK] (이번은 {this} 쪽입니다. {other}도 모두 [OK]여야 drill이 끝납니다)"
    steps = {r["step"]: r for r in d.log}
    # 4 (review 10-24): one reduce-only market close in every run, the stop moved to the half left (a stop bigger than
    # the position is refused as a whole when it fires: the fake's default), then the stop fires for the rest
    half = next(r for k, r in steps.items() if k.startswith("줄이기 전용 시장가로 절반 청산"))
    assert half["ok"] and half["detail"]["qty"] == "20" and abs(float(half["detail"]["positionAmt"])) == 20
    closes = [b for b in posts(fake) if b.get("reduceOnly")]
    assert len(closes) == 1 and (closes[0]["side"], closes[0]["posSide"]) == (("sell", "long") if side > 0 else
                                                                             ("buy", "short"))
    assert [b["sz"] for b in posts(fake, TRIG)][-2:] == ["20", "20"]          # the moved stop and the test stop
    assert steps["답을 잃은 주문 찾기(보낸 기록 없이 우리 번호로 다시 조회 - 실행기가 쓰는 길)"]["ok"]
    assert steps["답을 잃은 손절 찾기(보낸 내용: 방향·수량·발동 가격, 보내기 전 목록 제외)"]["ok"]
    assert steps["취소한 손절이 발동 기록에 '발동 안 함'으로 남음(CANCELED)"]["ok"]
    fired = next(r for k, r in steps.items() if k.startswith("손절 발동 시험:"))
    assert fired["detail"]["status"] == "TRIGGERED"
    assert steps["손절을 발동시킨 가격(마지막 가격 / 마크 가격)"]["detail"]["verdict"] == "마지막 가격"
    assert steps["발동한 손절의 체결을 찾음(손절 자신의 ordId, 또는 손절이 낸 주문)"]["ok"]
    assert steps["이익 쪽 손절(계단 잠금 자리, 진입가보다 유리한 곳)이 걸림"]["ok"]
    pnl = next(r for k, r in steps.items() if k.startswith("체결로 계산한 손익"))
    assert pnl["detail"]["fee_rate_pct"] == pytest.approx(0.05, abs=1e-3) and pnl["detail"]["check"] == ["ok"]
    assert steps["실제 수수료율 = 수수료율 API(편도; 다르면 실제 값을 쓰세요)"]["ok"]
    assert fake.amt(DOGE) == 0 and not fake.triggers


def test_drill_prints_each_step_and_ends_flat_without_the_trigger_test():
    c, fake, clock = drill_world()
    lines = []
    d = DC.DeepCoinDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000,
                         say=lines.append)
    assert DC.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert len([x for x in lines if x.startswith("[OK]")]) == len(d.log)
    assert lines[-1] == "끝: drill 모두 [OK] (이번은 롱 쪽입니다. 숏(--side short)도 모두 [OK]여야 drill이 끝납니다)"
    assert fake.amt(DOGE) == 0 and not fake.triggers


def test_the_drill_waits_for_lagging_records_and_ends_flat():
    c, fake, clock = drill_world(advance=True)
    fake.order_lag_ms, fake.trigger_lag_ms = 3_000, 1_000
    d = DC.DeepCoinDrill(c, symbol=DOGE, wait=ticking(clock), trigger_test=False, elapsed=lambda: clock.t / 1000)
    assert DC.run_drill(c, d, "drill", True, pause=lambda s: None), [r for r in d.log if not r["ok"]]
    steps = {r["step"]: r for r in d.log}
    assert steps["진입 주문을 우리 번호(clOrdId)로 찾음(GET order)"]["detail"]["seconds"] >= 3
    stop = next(r for k, r in steps.items() if k.startswith("손절이 딥코인에 걸림"))
    assert stop["detail"]["listed_after_ms"] >= 1_000
    assert fake.amt(DOGE) == 0 and not fake.triggers


def test_the_drill_notes_lists_without_the_clordid_and_still_passes():
    """First live drill (10-25): GET order found the entry by its clOrdId, the pending list / order history did not
    show it. The look-up the executor uses is the step; the lists are a note with what the history shows."""
    c, fake, clock = drill_world()
    edit_route(fake, "/deepcoin/trade/orders-history", lambda d: [{**r, "clOrdId": ""} for r in d])
    lines = []
    d = DC.DeepCoinDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000,
                         say=lines.append)
    assert DC.run_drill(c, d, "drill", True, pause=lambda s: None), [r for r in d.log if not r["ok"]]
    steps = {r["step"]: r for r in d.log}
    lost = steps["답을 잃은 주문 찾기(보낸 기록 없이 우리 번호로 다시 조회 - 실행기가 쓰는 길)"]
    assert lost["ok"] and lost["detail"]["lookup"] == lost["detail"]["want"]
    note = next(x for x in lines if "안 보였습니다" in x)
    assert "'in_newest': True" in note and "'clOrdId_in_newest': ''" in note and "'by_ordId': {" in note
    assert fake.amt(DOGE) == 0


def test_the_drill_notes_lists_with_the_clordid():
    c, fake, clock = drill_world()
    lines = []
    d = DC.DeepCoinDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000,
                         say=lines.append)
    assert DC.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert any("주문 기록에도 같은 clOrdId로 보입니다" in x for x in lines)


def test_the_drill_without_the_confirmation_sends_no_order():
    c, fake, clock = drill_world()
    d = DC.DeepCoinDrill(c, symbol=DOGE, wait=lambda s: None, elapsed=lambda: clock.t / 1000)
    assert DC.run_drill(c, d, "drill", False, pause=lambda s: None)
    assert not posts(fake) and not posts(fake, TRIG) and d.log[-1]["step"] == "주문 단계"


@pytest.mark.parametrize("stop", ["error", "ctrl_c"])
def test_a_drill_stopped_part_way_leaves_the_coin_flat(stop):
    c, fake, clock = drill_world()
    lines = []

    def wait(s):            # the stop is resting and the trigger test waits: then the drill is stopped
        clock.t += int(s * 1000)
        if fake.amt(DOGE) and fake.triggers and clock.t > T0 + 120_000:
            if stop == "ctrl_c":
                raise KeyboardInterrupt("SIGHUP")
            raise ValueError("an unexpected reply")
    d = DC.DeepCoinDrill(c, symbol=DOGE, wait=wait, trigger_wait_s=600, elapsed=lambda: clock.t / 1000,
                         say=lines.append)
    assert not DC.run_drill(c, d, "drill", True, pause=lambda s: None)
    steps = {r["step"]: r for r in d.log}
    assert not steps["멈춤"]["ok"]
    assert steps["정리 후 상태"]["ok"], steps["정리 후 상태"]
    assert fake.amt(DOGE) == 0 and not fake.triggers
    assert lines[-1].startswith("끝: drill [FAIL]")


def test_the_drill_without_the_trigger_test_closes_with_two_reduce_only_orders_on_the_short_side():
    c, fake, clock = drill_world()
    lines = []
    d = DC.DeepCoinDrill(c, symbol=DOGE, side=-1, wait=lambda s: None, trigger_test=False,
                         elapsed=lambda: clock.t / 1000, say=lines.append)
    assert DC.run_drill(c, d, "drill", True, pause=lambda s: None), [r for r in d.log if not r["ok"]]
    closes = [(b["side"], b["posSide"], b["sz"]) for b in posts(fake) if b.get("reduceOnly")]
    assert closes == [("buy", "short", "20"), ("buy", "short", "20")] and posts(fake)[0]["sz"] == "40"
    assert lines[-1].endswith("(이번은 숏 쪽입니다. 롱(--side long)도 모두 [OK]여야 drill이 끝납니다)")
    assert fake.amt(DOGE) == 0 and not fake.triggers
    assert DC.DeepCoinDrill.drill_qty(c.spec(DOGE), 0.2) == 40          # two halves of at least minSz (20)


@pytest.mark.parametrize("held", ["position", "stop"])
def test_the_drill_never_closes_or_cancels_what_it_did_not_open(held):
    """Review 10-24 (2, probe4): a drill stopped before its own entry (the drill coin was not empty) touches nothing."""
    c, fake, clock = drill_world()
    owner = ready(make(fake=fake, clock=clock)[0], (DOGE,))
    if held == "position":                                     # e.g. the executor's trade with its stop
        owner.market(DOGE, "BUY", 500.0, client_id="pbexecentry1")
        place_stop(owner, DOGE, "SELL", 0.19, 500.0, client_id="pbexecstop1")
    else:                                                      # a stop resting without a position
        owner.stop_close(DOGE, "SELL", 0.19, 100.0, client_id="pbexecstop1")
    before = (fake.amt(DOGE), sorted(fake.triggers))
    lines = []
    d = DC.DeepCoinDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000,
                         say=lines.append)
    assert not DC.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert (fake.amt(DOGE), sorted(fake.triggers)) == before and len(posts(fake)) == (1 if held == "position" else 0)
    assert not any(r["step"].startswith("정리") for r in d.log) and not d.entry_sent
    assert any("계정에는 손대지 않았습니다" in x for x in lines)


def test_a_drill_stopped_after_its_entry_cleans_up_only_what_it_made():
    c, fake, clock = drill_world()
    owner = make(fake=fake, clock=clock)[0]
    theirs = {}

    def wait(s):            # the drill's stop rests: someone else puts a stop on the coin, then the drill is stopped
        clock.t += int(s * 1000)
        if fake.amt(DOGE) and fake.triggers and clock.t > T0 + 120_000 and not theirs:
            theirs.update(owner.stop_close(DOGE, "SELL", 0.15, 10.0, client_id="pbOther"))
            raise ValueError("an unexpected reply")
    d = DC.DeepCoinDrill(c, symbol=DOGE, wait=wait, trigger_wait_s=600, elapsed=lambda: clock.t / 1000)
    assert not DC.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert fake.amt(DOGE) == 0 and list(fake.triggers) == [theirs["algoId"]]
    steps = {r["step"]: r for r in d.log}
    assert not steps["정리 후 상태"]["ok"] and steps["정리 후 상태"]["detail"]["stops"] == 1


def test_leave_flat_keeps_the_stop_while_the_position_is_open():
    """Review 10-24 (7, probe1 P2): a close that failed leaves the position with its stop, never without one."""
    c, fake, clock = make()
    ready(c, (DOGE,))
    c.market(DOGE, "BUY", 100.0, client_id="pbE")
    st = place_stop(c, DOGE, "SELL", 90.0, 100.0, client_id="pbS")
    fake.fail("POST", ORDER, "drop_before")
    log = []
    DC.leave_flat(c, DOGE, lambda step, ok, detail: log.append((step, ok)), 1, 100.0)
    assert fake.amt(DOGE) == 100 and [t["ordId"] for t in fake.live_stops(DOGE)] == [st["algoId"]]
    assert ("정리 후 상태", False) in log and any(s.startswith("정리: 포지션이 남아") for s, _ in log)
    log.clear()
    DC.leave_flat(c, DOGE, lambda step, ok, detail: log.append((step, ok)), 1, 100.0)     # once more: closed
    assert fake.amt(DOGE) == 0 and not fake.triggers and log == [("정리 후 상태", True)]


def test_drill_stops_when_two_stops_cannot_rest_at_once_and_leaves_flat():
    c, fake, clock = drill_world()
    fake.two_stops = False
    d = DC.DeepCoinDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000)
    assert not DC.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert fake.amt(DOGE) == 0 and not fake.triggers


def test_drill_fails_when_a_resting_stop_is_in_the_trigger_history():
    c, fake, clock = drill_world()
    fake.history_resting = True                                # the history also lists resting stops (triggerTime 0)
    d = DC.DeepCoinDrill(c, symbol=DOGE, wait=lambda s: None, trigger_test=False, elapsed=lambda: clock.t / 1000)
    assert not DC.run_drill(c, d, "drill", True, pause=lambda s: None)
    assert any(r["step"].startswith("걸려 있는 손절은 발동 기록") and not r["ok"] for r in d.log)
    assert fake.amt(DOGE) == 0 and not fake.triggers


def test_the_cli_specs_needs_no_key(monkeypatch, capsys):
    fake = FakeDeepCoin()
    fake.clock = Clock()
    real = DC.DeepCoinClient

    def public(*a, **k):
        return real("", "", "", public_only=True, send=fake, clock_ms=fake.clock, sleep=lambda s: None)
    monkeypatch.setattr(DC, "public_client", public)
    monkeypatch.delenv("DEEPCOIN_LIVE_KEY", raising=False)
    assert DC.main(["specs"]) == 0
    out = capsys.readouterr().out
    assert "BTCUSDT: 상태 Trading" in out and "DOGEUSDT" in out
    assert DC.main(["check"]) == 2                             # no key in the environment: refused, nothing sent


# ------------------------------------------------------------------ the executor, whole cycle
class Source:
    def __init__(self, clock):
        self.clock, self.intent, self.ts = clock, None, None

    def read(self):
        return self.intent, (self.ts if self.ts is not None else self.clock() - 30_000)


class World:
    def __init__(self, tmp_path, fake=None, advance=False, **cfg_kw):
        self.clock = Clock()
        self.fake = fake or FakeDeepCoin(wallet=10_000.0)
        self.fake.clock = self.clock
        self.src = Source(self.clock)
        self.note = ListNotifier()
        risk = R.RiskConfig(daily_max_loss_usd=500.0, max_drawdown_pct=0.2, max_consecutive_losses=3, max_leverage=40,
                            max_notional_usd=1_000.0, allowed_symbols=(BTC, ETH),
                            kill_file=str(tmp_path / "STOP"))
        self.cfg = ExecConfig(account="COMBO@mix", paper_db=str(tmp_path / "vwap.db"),
                              db=str(tmp_path / "executor-deepcoin-live.db"), qty_scale=1.0, risk=risk, retries=4,
                              sweep_every=1, exchange="deepcoin", mode="mainnet", budget_usd=10_000.0,
                              paper_env_file=str(tmp_path / "live.env"), **cfg_kw)
        self.store = ExecStore(self.cfg.db)
        kw = dict(send=self.fake, clock_ms=self.clock, sleep=lambda s: None)
        self.client = DC.DeepCoinClient("dk", "ds", "dp", **{**kw, "sleep": ticking(self.clock) if advance
                                                            else kw["sleep"]})
        self.keycheck = DC.DeepCoinKeyCheckClient("dk", "ds", "dp", attested=True, **kw)
        self.ex = Executor(self.cfg, self.client, self.src, self.store, self.note, now_ms=self.clock,
                           sleep=lambda s: None, keycheck=self.keycheck, env=dict(LIVE_ENV))
        self.ex.start()

    def loop(self, n=1):
        for _ in range(n):
            self.clock.t += 3_000
            self.ex.loop_once()

    def paper(self, stop, side=1, qty=5.0, lev=20, entry=100.0, symbol=BTC):
        et = self.src.intent.entry_time if self.src.intent else self.clock.t - 60_000
        self.src.intent = Intent(key=f"COMBO@mix|{symbol}|{et}", symbol=symbol, side=side, qty=qty, leverage=lev,
                                 stop=stop, entry_price=entry, entry_time=et)

    def stops(self, symbol=BTC):
        ct = float(SPECS[symbol]["ctVal"])
        return [(float(t["triggerPx"]), float(t["sz"]) * ct) for t in self.fake.live_stops(symbol)]

    def kinds(self):
        return [k for (k,) in self.store.conn.execute("SELECT kind FROM events")]


def test_executor_config_problems():
    risk = R.RiskConfig(max_leverage=40, allowed_symbols=(BTC,), kill_file="/var/lib/paperbot/STOP")
    cfg = ExecConfig(account="A@b", paper_db="p", db="/var/lib/paperbot/exec/x.db", qty_scale=1.0, exchange="deepcoin",
                     mode="testnet", budget_usd=100.0, risk=risk)
    assert any("딥코인에는 테스트넷이 없습니다" in p for p in cfg.problems())
    cfg = ExecConfig(account="A@b", paper_db="p", db="/var/lib/paperbot/exec/x.db", qty_scale=1.0, exchange="deepcoin",
                     mode="mainnet", budget_usd=100.0, risk=risk,
                     net_costs={"deepcoin": {"taker_fee": 0.0005, "slippage": 0.0002}})
    assert not [p for p in cfg.problems() if "net_costs" in p or "exchange" in p or "딥코인" in p]
    cfg = ExecConfig(account="A@b", paper_db="p", db="/var/lib/paperbot/exec/x.db", qty_scale=1.0, exchange="kraken",
                     mode="mainnet", budget_usd=100.0, risk=risk)
    assert any('"deepcoin"' in p for p in cfg.problems())
    from paperbot import executor as E
    assert E.EXCHANGES[-1] == "deepcoin" and E.EX_KO["deepcoin"] == "딥코인"
    assert E.NET_COSTS["deepcoin"] == {"taker_fee": 0.0005, "slippage": 0.0002}
    assert E._prefixes("deepcoin") == {"mainnet": "[딥코인 실거래 실행기]"}
    c, kc = E._clients(ExecConfig(account="A@b", paper_db="p", db="x.db", qty_scale=1.0, exchange="deepcoin",
                                  mode="mainnet", budget_usd=100.0, risk=risk), env=dict(LIVE_ENV))
    assert type(c) is DC.DeepCoinClient and isinstance(kc, DC.DeepCoinKeyCheckClient)


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
    with pytest.raises(Refused, match=DC.KEY_CHECKED):
        Executor(cfg, w.client, w.src, store3, w.note, now_ms=w.clock, sleep=lambda s: None, keycheck=w.keycheck,
                 env={k: v for k, v in LIVE_ENV.items() if k != DC.KEY_CHECKED})


def test_executor_entry_stop_lock_steps_and_exit_from_fills(tmp_path):
    w = World(tmp_path)
    assert w.fake.levs[BTC]["isolated"] == 40 and w.fake.levs[ETH]["isolated"] == 30
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)]
    assert w.fake.levs[BTC]["isolated"] == 20                       # the paper's leverage
    assert w.ex.prefix == "[딥코인 실거래 실행기]" and w.store.get_state("meta")["exchange"] == "deepcoin"
    entry = w.fake.order_bodies[0]
    assert entry["clOrdId"] == f"pb{w.ex.trade['base']}e" and entry["posSide"] == "long"
    for price, lock in [(105.0, 101.1), (109.0, 104.9), (113.0, 109.3)]:
        w.fake.set_price(BTC, price)
        w.paper(stop=lock)
        w.loop()
        assert w.stops() == [(lock, 5.0)], (price, lock)
    assert not w.fake.unprotected()
    stop_bodies = w.fake.trigger_bodies
    assert all(len(b.get("clOrdId", "")) <= 20 for b in w.fake.order_bodies) and len(stop_bodies) == 4
    w.fake.add_funding(BTC, -1.25)
    w.src.intent = None                                               # paper exit
    w.loop(2)
    assert w.fake.amt(BTC) == 0 and not w.fake.triggers and w.ex.trade is None
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


def test_executor_finds_an_entry_whose_answer_was_lost_by_its_clordid(tmp_path):
    w = World(tmp_path)
    w.fake.fail("POST", "/deepcoin/trade/order", "drop_after")
    w.paper(stop=95.0)
    w.loop()                                       # the answer is lost: Guarded looks it up by its clOrdId
    assert w.ex.trade["status"] == "open" and w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)]
    assert len(posts(w.fake)) == 1


@UNKNOWN_IDS
def test_executor_adopts_an_entry_whose_record_lags_and_never_sends_it_twice(tmp_path, unknown_ids):
    w = World(tmp_path)
    w.fake.order_lag_ms, w.fake.unknown_ids = 10_000, unknown_ids
    w.fake.fail("POST", "/deepcoin/trade/order", "drop_after")
    w.paper(stop=95.0)
    w.loop()                                       # not visible yet: unknown, never resent
    assert w.ex.trade["status"] == "entering" and w.fake.amt(BTC) == 5
    w.loop()                                       # the reconcile adopts and protects it
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)]
    assert len(posts(w.fake)) == 1 and not w.fake.unprotected()


def test_executor_keeps_a_position_whose_new_stop_the_list_shows_late(tmp_path):
    w = World(tmp_path, advance=True)
    w.fake.trigger_lag_ms = 2_000
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.amt(BTC) == 5 and w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)]
    w.loop(3)
    assert "protect_failed" not in w.kinds() and "no_stop" not in w.kinds()
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)] and not w.fake.unprotected()


def test_executor_keeps_the_old_stop_when_the_new_one_is_cancelled_behind_a_stale_history(tmp_path):
    w = World(tmp_path, advance=True)
    w.paper(stop=95.0)
    w.loop()
    assert w.stops() == [(95.0, 5.0)]
    w.fake.kill_new_stops, w.fake.trigger_history_lag_ms = True, 60_000
    w.fake.set_price(BTC, 105.0)
    w.paper(stop=101.1)
    w.loop()
    assert "move_failed" in w.kinds() and "protect_failed" not in w.kinds()
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)] and not w.fake.unprotected()


def test_executor_keeps_a_trade_whose_first_stop_was_refused_with_a_429(tmp_path):
    w = World(tmp_path, advance=True)
    real, seen = w.fake._trigger, []

    def place(q):                                    # the first stop: refused with a 429, nothing placed
        if not seen:
            seen.append(1)
            return 429, b'{"code":"429","msg":"Too Many Requests"}', {"Retry-After": "1"}
        return real(q)
    w.fake._trigger = place
    w.paper(stop=95.0)
    w.loop()
    assert "protect_failed" not in w.kinds() and w.ex.trade["status"] == "open"
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)]


def test_executor_cleans_up_the_extra_stop_of_a_429_that_ran(tmp_path):
    w = World(tmp_path, advance=True)
    w.fake.trigger_lag_ms = 3_000
    real, seen = w.fake._trigger, []

    def place(q):                                    # the first stop: it ran, the answer says 429
        out = real(q)
        if not seen:
            seen.append(1)
            return 429, b'{"code":"429","msg":"Too Many Requests"}', {"Retry-After": "1"}
        return out
    w.fake._trigger = place
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.amt(BTC) == 5 and len(w.fake.live_stops(BTC)) == 2
    w.loop()
    assert "extra_stops" in w.kinds() and "protect_failed" not in w.kinds() and "no_stop" not in w.kinds()
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)] and not w.fake.unprotected()


def test_executor_closes_a_position_whose_stop_stays_throttled(tmp_path):
    w = World(tmp_path, advance=True)
    real, seen = w.fake._trigger, []

    def place(q):
        if not seen:
            seen.append(1)
            return 429, b'{"code":"429","msg":"Too Many Requests"}', {"Retry-After": "60"}
        return real(q)
    w.fake._trigger = place
    w.paper(stop=95.0)
    t0 = w.clock.t
    w.loop()
    assert "protect_failed" in w.kinds() and w.fake.amt(BTC) == 0 and not w.fake.triggers
    assert w.clock.t - t0 <= 3_000 + 2 * DC.PROTECT_WAIT_S * 1000


def test_executor_starts_with_a_coin_missing_an_entry_field_and_refuses_only_its_entries(tmp_path):
    fake = FakeDeepCoin(wallet=10_000.0)
    strip_field(fake, ETH, "minSz")
    w = World(tmp_path, fake=fake)
    et = w.clock.t - 60_000
    w.src.intent = Intent(key=f"COMBO@mix|{ETH}|{et}", symbol=ETH, side=1, qty=5.0, leverage=20, stop=95.0,
                          entry_price=100.0, entry_time=et)
    w.loop()
    assert w.fake.amt(ETH) == 0 and w.ex.trade is None and not posts(w.fake)
    texts = [t for k, t in w.store.conn.execute("SELECT kind, text FROM events") if k == "leverage_refused"]
    assert texts and "새 진입" in texts[0]
    w.src.intent = None
    w.paper(stop=95.0)                                       # the other coins still trade
    w.loop()
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)]


def test_executor_closes_an_unknown_position_and_cancels_stray_stops(tmp_path):
    w = World(tmp_path)
    other = DC.DeepCoinClient("dk", "ds", "dp", send=w.fake, clock_ms=w.clock, sleep=lambda s: None)
    other.one_side = True
    other.market(ETH, "SELL", 1.0, client_id="pbHand")        # a position opened by hand
    w.loop()
    assert w.fake.amt(ETH) == 0 and "unknown_position" in w.kinds()
    w.paper(stop=95.0)
    w.loop()
    st = other.stop_close(BTC, "SELL", 90.0, 5.0, client_id="pbHandStop")
    w.src.intent = None
    w.loop(2)
    assert w.fake.amt(BTC) == 0 and not w.fake.triggers and st["algoId"]


@pytest.mark.parametrize("kind", [("err_after", 200, "50013", "System is busy, please try again later"), "403_after",
                                  ("err_after", 200, "51999", "Order expired: matching engine timeout")])
def test_executor_keeps_and_protects_an_entry_that_ran_but_was_answered_otherwise(tmp_path, kind):
    """Review 10-24 (1, probe1 P3): such an entry was "refused" (a position with no trade record, closed later as an
    unknown position), or, with the "expired" words behind a lagging record, re-synced and sent twice."""
    w = World(tmp_path)
    w.fake.order_lag_ms = 10_000                               # the docs' short visibility delay
    w.fake.fail("POST", "/deepcoin/trade/order", kind)
    w.paper(stop=95.0)
    w.loop()                                                   # unknown: never resent, never refused
    assert w.fake.amt(BTC) == 5 and len(posts(w.fake)) == 1 and "entry_refused" not in w.kinds()
    w.loop()                                                   # the reconcile adopts and protects it
    assert w.ex.trade["status"] == "open" and w.stops() == [(95.0, 5.0)] and not w.fake.unprotected()
    assert len(posts(w.fake)) == 1 and w.fake.amt(BTC) == 5


def test_executor_enters_when_the_look_up_before_the_send_fails_once(tmp_path):
    """Review 10-24 (9): nothing was sent, so the entry is sent (once) instead of waiting 60 s as an unknown outcome."""
    w = World(tmp_path)
    w.fake.fail("GET", "/deepcoin/trade/order", "503_before")
    w.paper(stop=95.0)
    w.loop()
    assert w.ex.trade["status"] == "open" and w.fake.amt(BTC) == 5 and len(posts(w.fake)) == 1
    assert w.stops() == [(95.0, 5.0)] and "entry_unknown" not in w.kinds()


def test_executor_never_adds_stops_or_closes_when_the_stop_list_cannot_be_read(tmp_path):
    """Review 10-24 (3): a resting stop whose posSide reads garbled is an error, never "no stop"."""
    w = World(tmp_path)
    w.paper(stop=95.0)
    w.loop()
    real = w.fake._trigger_row
    w.fake._trigger_row = lambda t: {**real(t), "posSide": ""}
    for _ in range(3):
        with pytest.raises(TransientError):                   # the loop's read fails (Executor.run logs, goes on)
            w.loop()
    assert w.fake.amt(BTC) == 5 and len(w.fake.triggers) == 1 and len(posts(w.fake, TRIG)) == 1
    assert "no_stop" not in w.kinds() and "protect_failed" not in w.kinds()
    w.fake._trigger_row = real
    w.loop()
    assert w.stops() == [(95.0, 5.0)] and w.ex.trade["status"] == "open"


def test_executor_starts_and_trades_when_one_coins_leverage_cannot_be_set(tmp_path):
    """Review 10-24 (5): the start never stops for one coin (an open position elsewhere keeps being protected); that
    coin refuses its entries while its leverage cannot be set."""
    fake = FakeDeepCoin(wallet=10_000.0)
    real = fake._route

    def refuse_eth(m, p, q, b):
        if p == "/deepcoin/account/set-leverage" and "ETH-USDT-SWAP" in (b or b"").decode():
            return 200, json.dumps({"code": "0", "msg": "", "data": {"instId": "", "lever": "", "mgnMode": "",
                                                                     "mrgPosition": "", "sCode": "199",
                                                                     "sMsg": "LeverageTooHigh"}}).encode(), {}
        return real(m, p, q, b)
    fake._route = refuse_eth
    w = World(tmp_path, fake=fake)                             # no Refused: it starts
    assert ETH in w.client.lev_problems and "margin_refused" not in w.kinds()
    et = w.clock.t - 60_000
    w.src.intent = Intent(key=f"COMBO@mix|{ETH}|{et}", symbol=ETH, side=1, qty=0.5, leverage=20, stop=95.0,
                          entry_price=100.0, entry_time=et)
    w.loop()
    assert w.fake.amt(ETH) == 0 and "leverage_refused" in w.kinds() and not posts(w.fake)
    w.src.intent = None
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.amt(BTC) == 5 and w.stops() == [(95.0, 5.0)]


def test_executor_starts_behind_a_lagging_leverage_read_back(tmp_path):
    fake = FakeDeepCoin(wallet=10_000.0)
    fake.lev_lag_ms = 2_000
    w = World(tmp_path, fake=fake, advance=True)
    assert not w.client.lev_problems and fake.levs[BTC]["isolated"] == 40
    w.paper(stop=95.0)
    w.loop()
    assert w.fake.amt(BTC) == 5 and w.fake.levs[BTC]["isolated"] == 20 and w.stops() == [(95.0, 5.0)]


def test_executor_resizes_a_stop_bigger_than_the_position_so_that_it_can_fire(tmp_path):
    """The fake refuses a firing trigger order bigger than the position as a whole (``oversize`` "refuse")."""
    w = World(tmp_path)
    w.paper(stop=95.0)
    w.loop()
    other = DC.DeepCoinClient("dk", "ds", "dp", send=w.fake, clock_ms=w.clock, sleep=lambda s: None)
    other.market(BTC, "SELL", 2.0, reduce_only=True, client_id="pbHandCut")      # part closed by hand
    w.loop(2)
    assert w.fake.amt(BTC) == 3 and w.stops() == [(95.0, 3.0)]
    w.clock.t += 10_000
    w.fake.set_price(BTC, 94.0)
    assert w.fake.amt(BTC) == 0


def test_executor_follows_the_ladder_and_the_exit_next_to_odd_trigger_rows(tmp_path):
    """Re-review 10-24 (2): a garbled trigger row on a coin without a position and a posSide-net row on the traded coin
    never stop the loop's sweep (the ladder moves and the paper exit go on)."""
    w = World(tmp_path)
    w.paper(stop=95.0)
    w.loop()
    odd = [{"instType": "SWAP", "instId": "ETH-USDT-SWAP", "ordId": "902", "triggerPx": "x", "ordPx": "0", "sz": "1",
            "ordType": "", "side": "sell", "posSide": "", "tdMode": "isolated", "triggerPxType": "last", "lever": "30",
            "cTime": str(T0), "uTime": str(T0)},
           {"instType": "SWAP", "instId": "BTC-USDT-SWAP", "ordId": "901", "triggerPx": "90", "ordPx": "0", "sz": "5",
            "ordType": "", "side": "sell", "posSide": "net", "tdMode": "cross", "triggerOrderType": "Conditional",
            "triggerPxType": "last", "lever": "1", "cTime": str(T0), "uTime": str(T0)}]
    edit_route(w.fake, PENDING, lambda d: d + odd)
    w.fake.set_price(BTC, 105.0)
    w.paper(stop=101.1)
    w.loop()
    assert w.stops() == [(101.1, 5.0)] and "reconcile_failed" not in w.kinds()
    w.src.intent = None
    w.loop(2)
    assert w.fake.amt(BTC) == 0 and w.ex.trade is None and not w.fake.live_stops(BTC)


def test_executor_drops_an_entry_whose_checks_before_the_send_keep_failing(tmp_path):
    """Re-review 10-24 (3): nothing was sent, so the entry is refused at once, never held as "entering"."""
    w = World(tmp_path)
    w.fake.fail("GET", "/deepcoin/trade/order", "503_before", times=10 ** 6)
    w.paper(stop=95.0)
    w.loop()
    assert w.ex.trade is None and "entry_refused" in w.kinds() and "entry_unknown" not in w.kinds()
    assert not posts(w.fake) and w.fake.amt(BTC) == 0
