import pytest

from fakefutures import FakeFutures
from paperbot.testnet import (Drill, RateLimited, TestnetClient, TestnetError, TransientError, cancel_everything,
                              covers, live_stops, move_stop, place_stop, reconcile, round_stop)


def client(fake, clock=lambda: 1_000_000):
    return TestnetClient("k", "s", send=fake, clock_ms=clock)


def algo_posts(fake):
    return [c for c in fake.calls if c[0] == "POST" and c[1] == "/fapi/v1/algoOrder"]


def test_refuses_mainnet_hosts():
    for base in ("https://fapi.binance.com", "https://testnet.binancefuture.com.evil.io", "http://localhost",
                 "https://demo-fapi.binance.com"):
        with pytest.raises(ValueError):
            TestnetClient("k", "s", base=base)
    with pytest.raises(ValueError):
        TestnetClient("", "")


@pytest.mark.parametrize("side", [1, -1])
def test_drill_runs_clean_cycle(side):
    fake = FakeFutures()
    log = Drill(client(fake), "BTCUSDT", side=side, notional=200.0, leverage=20, wait=lambda s: None).run()
    assert all(r["ok"] for r in log) and len(log) == 9, log
    assert fake.pos["BTCUSDT"] == 0 and not fake.live_stops() and fake.margin["BTCUSDT"] == "ISOLATED"
    assert fake.lev["BTCUSDT"] == 20
    # protective stops: algo endpoint, CONDITIONAL STOP_MARKET on the LAST price, no price protection
    posts = algo_posts(fake)
    assert len(posts) == 4                     # first, moved, restored, refused (-2021)
    for _, _, q in posts:
        assert q["algoType"] == "CONDITIONAL" and q["type"] == "STOP_MARKET"
        assert q["workingType"] == "CONTRACT_PRICE" and q["priceProtect"] == "false"
        assert q["reduceOnly"] == "true" and float(q["quantity"]) > 0 and "closePosition" not in q
        assert "stopPrice" not in q
    assert not [c for c in fake.calls if c[1] == "/fapi/v1/order" and c[2].get("type") == "STOP_MARKET"]
    moved = next(r for r in log if r["step"] == "stop moved without a gap")
    assert moved["detail"]["during"] == 2
    # unprotected only between the entry and its first stop, and in the deliberate restart check
    first_stop = next(i for i, c in enumerate(fake.calls) if c[1] == "/fapi/v1/algoOrder" and c[0] == "POST")
    bad = [t for t in fake.unprotected_moments("BTCUSDT") if t[0] > first_stop + 1]
    deliberate = [t for t in bad if t[1] == "DELETE" and t[2] == "/fapi/v1/algoOrder"]
    assert len(deliberate) == 1
    assert all(t[1] == "GET" or t in deliberate for t in bad)       # the reconcile reads before repairing
    exit_ = next(r for r in log if "refused (-2021)" in r["step"])
    assert exit_["detail"]["result"] == "closed" and "immediately trigger" in exit_["detail"]["error"]


def test_drill_refuses_dirty_account():
    fake = FakeFutures()
    fake.pos["BTCUSDT"] = 0.002
    with pytest.raises(AssertionError):
        Drill(client(fake), "BTCUSDT", wait=lambda s: None).run()


def test_reconcile_finds_and_repairs_unprotected_position():
    fake = FakeFutures()
    c = client(fake)
    fake.pos["BTCUSDT"], fake.entry["BTCUSDT"] = 0.002, 100.0
    rep = reconcile(c, "BTCUSDT")
    assert rep["problem"] == "position without a protective stop" and not rep["repaired"]
    rep = reconcile(c, "BTCUSDT", stop_price=99.0)
    assert rep["repaired"] and len(fake.live_stops()) == 1 and fake.covered("BTCUSDT")
    fake.pos["BTCUSDT"] = 0.005                    # the position grew: the stop no longer covers it
    assert reconcile(c, "BTCUSDT")["problem"] == "stop smaller than the position"
    fake.pos["BTCUSDT"] = 0.0
    assert reconcile(c, "BTCUSDT")["problem"] == "stop orders without a position"


def test_stop_parameters_and_close_position_mode():
    fake = FakeFutures()
    c = client(fake)
    c.stop_close("BTCUSDT", "SELL", 95.0, qty=0.01, client_id="abc")
    c.stop_close("BTCUSDT", "SELL", 94.0)              # closePosition: no quantity, no reduceOnly
    a, b = [q for _, _, q in algo_posts(fake)]
    assert a["clientAlgoId"] == "abc" and a["quantity"] == "0.01" and a["reduceOnly"] == "true"
    assert b["closePosition"] == "true" and "quantity" not in b and "reduceOnly" not in b
    with pytest.raises(TestnetError) as e:              # why the executor uses quantity + reduceOnly
        c.stop_close("BTCUSDT", "SELL", 93.0)
    assert e.value.code == -4130
    assert round_stop(95.04, 0.1, 1) == 95.1 and round_stop(95.06, 0.1, -1) == 95.0


def test_move_stop_keeps_old_until_new_is_live():
    fake = FakeFutures()
    c = client(fake)
    c.market("BTCUSDT", "BUY", 1.0)
    s1 = place_stop(c, "BTCUSDT", "SELL", 95.0, 1.0)
    fake.fail("POST", "/fapi/v1/algoOrder", ("code", -1111, "Precision is over the maximum defined for this asset."))
    with pytest.raises(TestnetError):
        move_stop(c, "BTCUSDT", "SELL", 97.0, 1.0, [s1["algoId"]])
    assert [o["algoId"] for o in fake.live_stops()] == [s1["algoId"]] and fake.covered("BTCUSDT")
    res = move_stop(c, "BTCUSDT", "SELL", 97.0, 1.0, [s1["algoId"]])
    assert res["result"] == "moved" and [float(o["triggerPrice"]) for o in fake.live_stops()] == [97.0]
    assert not fake.unprotected_moments("BTCUSDT")[1:]   # only the entry itself, before the first stop


def test_move_stop_past_price_closes_at_market():
    fake = FakeFutures()
    c = client(fake)
    c.market("BTCUSDT", "SELL", 1.0)                      # short
    s1 = place_stop(c, "BTCUSDT", "BUY", 105.0, 1.0)
    fake.set_price("BTCUSDT", 104.0)
    res = move_stop(c, "BTCUSDT", "BUY", 103.0, 1.0, [s1["algoId"]])   # BUY stop below the price: -2021
    assert res["result"] == "closed" and res["flat"] and fake.pos["BTCUSDT"] == 0
    assert fake.calls[-1][2]["reduceOnly"] == "true"
    # the old stop is the caller's to cancel once two readings agree the position is flat (never on one read)
    assert res["cancelled"] == [] and [o["algoId"] for o in fake.live_stops()] == [s1["algoId"]]
    cancel_everything(c, "BTCUSDT")
    assert not fake.live_stops()


def test_move_stop_never_cancels_the_old_stops_on_one_read_of_zero():
    """-2021, and the one positionRisk read inside move_stop says 0 while the position is open: nothing is closed
    and the old stop must stay (it is the only protection left)."""
    fake = FakeFutures()
    c = client(fake)
    c.market("BTCUSDT", "BUY", 5.0)
    s1 = place_stop(c, "BTCUSDT", "SELL", 95.0, 5.0)
    fake.set_price("BTCUSDT", 98.0)
    orig = fake.route

    def route(m, path, q):
        if (m, path) == ("GET", "/fapi/v2/positionRisk"):
            return 200, [{"symbol": "BTCUSDT", "positionAmt": "0", "entryPrice": "0", "markPrice": "98"}]
        return orig(m, path, q)
    fake.route = route
    res = move_stop(c, "BTCUSDT", "SELL", 99.0, 5.0, [s1["algoId"]])    # SELL stop above the price: -2021
    assert res["result"] == "closed" and res["close"] is None and res["cancelled"] == []
    assert fake.pos["BTCUSDT"] == 5.0 and [o["algoId"] for o in fake.live_stops()] == [s1["algoId"]]
    assert fake.covered("BTCUSDT")


def test_covers():
    stop = {"orderType": "STOP_MARKET", "side": "SELL", "quantity": "2", "algoStatus": "NEW"}
    assert covers(stop, 2.0) and not covers(stop, 3.0) and not covers(stop, -2.0)
    assert covers({**stop, "quantity": "0", "closePosition": True}, 7.0)
    assert not covers({**stop, "algoStatus": "CANCELED"}, 1.0)


def test_error_classes_and_rate_limit_headers():
    fake = FakeFutures()
    c = client(fake)
    with pytest.raises(TestnetError) as e:
        c.market("BTCUSDT", "SELL", 0.001, reduce_only=True)
    assert e.value.code == -2022 and not isinstance(e.value, TransientError)
    fake.fail("GET", "/fapi/v2/positionRisk", "drop_before")
    with pytest.raises(TransientError):
        c.position("BTCUSDT")
    fake.fail("GET", "/fapi/v2/positionRisk", "503_before")
    with pytest.raises(TransientError) as e:
        c.position("BTCUSDT")
    assert e.value.status == 503
    fake.fail("GET", "/fapi/v2/positionRisk", "429")
    with pytest.raises(RateLimited) as e:
        c.position("BTCUSDT")
    assert e.value.retry_after == 2.0
    c.position("BTCUSDT")
    assert c.used["weight_1m"] == fake.weight and c.throttle_s() == 0
    c.used["weight_1m"] = 2300
    assert 0 < c.throttle_s() <= 60
    assert live_stops(c, "BTCUSDT") == []
