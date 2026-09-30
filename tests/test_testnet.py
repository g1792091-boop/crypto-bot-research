import json
import urllib.parse

import pytest

from paperbot.testnet import Drill, TestnetClient, TestnetError, reconcile


class FakeTestnet:
    """In-memory futures testnet: one symbol, market orders fill at the mark price."""

    def __init__(self, mark=100.0):
        self.mark = mark
        self.pos = 0.0
        self.orders = {}
        self.next_id = 1
        self.lev = 20
        self.margin = "CROSSED"
        self.calls = []

    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        assert u.hostname == "testnet.binancefuture.com"
        q = dict(urllib.parse.parse_qsl(u.query if body is None else body.decode()))
        self.calls.append((method, u.path, q))
        if u.path != "/fapi/v1/exchangeInfo" and u.path != "/fapi/v1/premiumIndex":
            assert "signature" in q and headers["X-MBX-APIKEY"] == "k"
        return self.route(method, u.path, q)

    def ok(self, data):
        return 200, json.dumps(data).encode()

    def err(self, code, msg):
        return 400, json.dumps({"code": code, "msg": msg}).encode()

    def route(self, m, path, q):
        if path == "/fapi/v1/exchangeInfo":
            return self.ok({"symbols": [{"symbol": "BTCUSDT", "filters": [
                {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                {"filterType": "MIN_NOTIONAL", "notional": "100"}]}]})
        if path == "/fapi/v1/premiumIndex":
            return self.ok({"markPrice": str(self.mark)})
        if path == "/fapi/v1/positionSide/dual":
            return self.err(-4059, "No need to change position side.")
        if path == "/fapi/v1/marginType":
            if self.margin == "ISOLATED":
                return self.err(-4046, "No need to change margin type.")
            self.margin = "ISOLATED"
            return self.ok({"code": 200})
        if path == "/fapi/v1/leverage":
            self.lev = int(q["leverage"])
            return self.ok({"leverage": self.lev, "symbol": q["symbol"]})
        if path == "/fapi/v1/order" and m == "POST":
            oid = self.next_id
            self.next_id += 1
            if q["type"] == "MARKET":
                qty = float(q["quantity"]) * (1 if q["side"] == "BUY" else -1)
                if q.get("reduceOnly") == "true" and abs(self.pos + qty) > abs(self.pos):
                    return self.err(-2022, "ReduceOnly Order is rejected.")
                self.pos = round(self.pos + qty, 9)
                return self.ok({"orderId": oid, "status": "FILLED", "avgPrice": str(self.mark)})
            o = {"orderId": oid, "type": q["type"], "side": q["side"], "stopPrice": q["stopPrice"],
                 "closePosition": q.get("closePosition"), "workingType": q.get("workingType")}
            self.orders[oid] = o
            return self.ok(o)
        if path == "/fapi/v1/order" and m == "GET":
            return self.ok({"orderId": int(q["orderId"]), "status": "FILLED", "avgPrice": str(self.mark)})
        if path == "/fapi/v1/order" and m == "DELETE":
            self.orders.pop(int(q["orderId"]))
            return self.ok({"status": "CANCELED"})
        if path == "/fapi/v1/allOpenOrders":
            self.orders.clear()
            return self.ok({"code": 200})
        if path == "/fapi/v1/openOrders":
            return self.ok(list(self.orders.values()))
        if path == "/fapi/v2/positionRisk":
            return self.ok([{"symbol": "BTCUSDT", "positionAmt": str(self.pos)}])
        raise AssertionError(f"unexpected {m} {path}")


def client(fake):
    return TestnetClient("k", "s", send=fake, clock_ms=lambda: 1)


def test_refuses_mainnet_hosts():
    for base in ("https://fapi.binance.com", "https://testnet.binancefuture.com.evil.io", "http://localhost"):
        with pytest.raises(ValueError):
            TestnetClient("k", "s", base=base)
    with pytest.raises(ValueError):
        TestnetClient("", "")


@pytest.mark.parametrize("side", [1, -1])
def test_drill_runs_clean_cycle(side):
    fake = FakeTestnet()
    log = Drill(client(fake), "BTCUSDT", side=side, notional=200.0, leverage=20, wait=lambda s: None).run()
    assert all(r["ok"] for r in log) and len(log) == 9
    assert fake.pos == 0 and not fake.orders and fake.margin == "ISOLATED" and fake.lev == 20
    stops = [c for c in fake.calls if c[1] == "/fapi/v1/order" and c[2].get("type") == "STOP_MARKET"]
    assert stops and all(c[2]["workingType"] == "MARK_PRICE" and c[2]["closePosition"] == "true" for c in stops)
    # the stop was always moved new-first: two stops existed before the old one was cancelled
    moved = next(r for r in log if r["step"] == "stop moved without a gap")
    assert moved["detail"]["during"] == 2


def test_drill_refuses_dirty_account():
    fake = FakeTestnet()
    fake.pos = 0.002
    with pytest.raises(AssertionError):
        Drill(client(fake), "BTCUSDT", wait=lambda s: None).run()


def test_reconcile_finds_and_repairs_unprotected_position():
    fake = FakeTestnet()
    c = client(fake)
    fake.pos = 0.002
    rep = reconcile(c, "BTCUSDT")
    assert rep["problem"] == "position without a protective stop" and not rep["repaired"]
    rep = reconcile(c, "BTCUSDT", stop_price=99.0)
    assert rep["repaired"] and len(fake.orders) == 1
    fake.pos = 0.0
    assert reconcile(c, "BTCUSDT")["problem"] == "stop orders without a position"


def test_error_codes_surface():
    fake = FakeTestnet()
    c = client(fake)
    with pytest.raises(TestnetError) as e:
        c.market("BTCUSDT", "SELL", 0.001, reduce_only=True)
    assert e.value.code == -2022
