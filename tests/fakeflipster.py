"""Stateful fake of Flipster's trading API (trading-api.flipster.io) for tests; no network.

Answers in the shapes of Flipster's API reference (api-docs.flipster.io): plain JSON objects and lists, errors as
HTTP 4xx with {"error": {"type", "message", "code"}}, 429 with Retry-After. Every request's signature is checked as
the Quick Tutorial defines it: hex HMAC-SHA256(secret, METHOD + path (+ "?" + query exactly as sent) + api-expires +
the body bytes as sent), and api-expires (unix seconds) must not have passed (401 "Request expired"). Symbols are
"BTCUSDT.PERP"; quantities are base-asset amounts on ``unitOrderQty`` (SPECS: test data only, the client reads every
value from /api/v1/market/contract); times are nanosecond strings.

Covers what paperbot/flipster.py uses: server time, contract info, tradable symbols, ticker (last and mark price), 1m
klines (built from every ``set_price``), account summary and balances, trade mode (refused with RemainingPositionsExist
while a position is open), leverage / margin type (the answer's position row; settings rows in the position list),
positions (one-way), MARKET orders (IOC: ``partial`` fills a fraction and cancels the rest, the answer's quantity then
the filled amount and the status CANCELED), STOP_MARKET orders (pending until the trigger price is crossed, then filled
at that price), pending orders, cancels, order history, execution history (TRADE / TRIGGERED / FUNDING rows, newest
first, ``count`` 64 a page with hasNext), fee-rate levels.

Unknowns of the real exchange are switches:
- ``two_stops``: whether a second STOP_MARKET can rest on a symbol next to the first (else refused);
- ``stop_price``: "last" or "mark": which price fires a STOP_MARKET;
- ``own_fills``: whether a fired stop's fills carry its own orderId (else a new MARKET order's, plus a TRIGGERED row);
- ``past_stop``: "trigger" (a stop already past the price fires at once) or "refuse";
- ``flat_cancels``: whether resting stops are cancelled when their position closes;
- ``settings_rows``: whether the position list shows a row (leverage, margin type) for a coin without a position;
- ``history_lag_ms``: an order shows in the order history only this long after it was made.

Failures are injected per request with ``fail(method, path, kind, times)``: "drop_before" / "drop_after" (TimeoutError
before / after executing), "503_before", "429", "403", ("err", status, type, msg) (refused, not executed).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
import uuid
from decimal import Decimal

SPECS = {   # test data only
    "BTCUSDT": {"step": "0.001", "tick": "0.1", "min": "5", "lev": "100"},
    "ETHUSDT": {"step": "0.01", "tick": "0.01", "min": "5", "lev": "100"},
    "SOLUSDT": {"step": "0.1", "tick": "0.001", "min": "5", "lev": "50"},
    "DOGEUSDT": {"step": "1", "tick": "0.00001", "min": "5", "lev": "50"},
    "LTCUSDT": {"step": "0.01", "tick": "0.01", "min": "5", "lev": "50"},
    "BCHUSDT": {"step": "0.01", "tick": "0.01", "min": "5", "lev": "50"},
}
PAGE = 64


def perp(s):
    return s + ".PERP"


class FakeFlipster:
    def __init__(self, prices=None, wallet=10_000.0, fee=0.0006, api_key="fk", api_secret="fs"):
        self.prices = {s: 100.0 for s in SPECS}
        self.prices.update(prices or {})
        self.marks = dict(self.prices)
        self.wallet, self.fee = wallet, fee
        self.key, self.secret = api_key, api_secret
        self.clock = None
        self.mode = "MULTIPLE_POSITIONS"
        self.levs = {s: ["CROSS", 10] for s in SPECS}
        self.set_levs = set()                      # coins whose leverage was set (their settings row shows)
        self.pos = {s: Decimal(0) for s in SPECS}  # signed base quantity
        self.entry = {s: 0.0 for s in SPECS}
        self.pending: dict = {}                    # orderId -> pending order (stops)
        self.orders: dict = {}                     # orderId -> final order (history)
        self.execs: list = []
        self.bars: dict = {}                       # (symbol, minute ms) -> [o, h, l, c]
        self.calls: list = []
        self.fails: list = []
        self.n = 0
        self.two_stops = True
        self.stop_price = "last"
        self.own_fills = True
        self.past_stop = "trigger"
        self.flat_cancels = True
        self.settings_rows = True
        self.history_lag_ms = 0
        self.partial = None                        # a fraction: the next market order fills only that much
        self.rate_limit = None                     # (window ms, max requests): beyond it, 429
        self.coverage: list = []                   # (call index, symbol, position, covered by a stop)
        self.slippage_sent = []                    # bodies that carried maxSlippagePrice

    # ------------------------------------------------------------ helpers for tests
    def now(self):
        return self.clock() if self.clock else 1_800_000_000_000

    def ns(self, ms=None):
        return str((self.now() if ms is None else ms) * 1_000_000)

    def fail(self, method, path, kind, times=1):
        self.fails.append([method, path, kind, times])

    def set_price(self, symbol, price, mark=None):
        self.prices[symbol] = price
        self.marks[symbol] = price if mark is None else mark
        m = self.now() // 60_000 * 60_000
        b = self.bars.get((symbol, m))
        self.bars[(symbol, m)] = [b[0], max(b[1], price), min(b[2], price), price] if b else [price] * 4
        self._trigger(symbol)

    def amt(self, symbol):
        return float(self.pos[symbol])

    def live_stops(self, symbol=None):
        return [o for o in self.pending.values() if o["orderType"] == "STOP_MARKET"
                and (symbol is None or o["symbol"] == perp(symbol))]

    def add_funding(self, symbol, amount, time=None):
        """A funding payment: ``amount`` + received (the row's execFee is + paid, like a fee)."""
        self.wallet += amount
        self.execs.append({"execId": self._uid(), "orderId": "", "symbol": perp(symbol), "side": "BUY",
                           "orderType": "MARKET", "timeInForce": "IOC", "status": "FILLED", "execType": "FUNDING",
                           "settlementCurrency": "USDT", "orderTime": self.ns(time), "transactTime": self.ns(time),
                           "lastPrice": "0", "lastQty": "0", "execFee": f"{-amount:.8f}",
                           "conditionalOrderType": "INVALID"})

    def unprotected(self):
        """Moments a position had no stop covering it, after its first stop was placed."""
        first = {}
        for i, c in enumerate(self.calls, start=1):
            if c[1] == "POST" and c[2] == "/api/v1/trade/order" and json.loads(c[4]).get("type") == "STOP_MARKET":
                first.setdefault(json.loads(c[4])["symbol"][:-5], i)
        return [c for c in self.coverage if c[2] and not c[3] and c[1] in first and c[0] > first[c[1]]]

    # ------------------------------------------------------------ transport
    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        assert u.scheme == "https" and u.hostname == "trading-api.flipster.io", url
        path, query = u.path, u.query
        self.calls.append((self.now(), method, path, query, body))
        for f in self.fails:
            if f[0] == method and path.startswith(f[1]) and f[3] > 0:
                f[3] -= 1
                kind = f[2]
                if kind == "drop_before":
                    raise TimeoutError("dropped")
                if kind == "503_before":
                    return 503, b"Service Unavailable", {}
                if kind == "429":
                    return 429, json.dumps({"error": {"type": "TooManyRequests", "message": "Too Many Requests",
                                                      "code": 429}}).encode(), {"Retry-After": "1"}
                if kind == "403":
                    return 403, b"<html>forbidden</html>", {}
                if isinstance(kind, tuple) and kind[0] == "err":
                    return self._error(kind[1], kind[2], kind[3])
                if kind == "drop_after":
                    self._route(method, path, query, body)
                    raise TimeoutError("dropped after")
        if self.rate_limit:
            window, most = self.rate_limit
            recent = [c for c in self.calls if self.now() - c[0] < window]
            if len(recent) > most:
                return 429, b'{"error":{"type":"TooManyRequests","message":"Too Many Requests"}}', {"Retry-After": "1"}
        exp = headers.get("api-expires", "")
        if headers.get("api-key") != self.key:
            return self._error(401, "Unauthorized", "Invalid api key")
        if not exp.isdigit() or int(exp) < self.now() // 1000:
            return self._error(401, "Unauthorized", "Request expired")
        signed = path + (f"?{query}" if query else "")
        msg = method.encode() + signed.encode() + exp.encode() + (body or b"")
        if headers.get("api-signature") != hmac.new(self.secret.encode(), msg, hashlib.sha256).hexdigest():
            return self._error(401, "Unauthorized", "Invalid signature")
        if body is not None and headers.get("Content-Type") != "application/json":
            return self._error(400, "BadRequest", "Content-Type must be application/json")
        out = self._route(method, path, query, body)
        self._note_coverage()
        return out

    def _note_coverage(self):
        for s, n in self.pos.items():
            if n:
                side = "SELL" if n > 0 else "BUY"
                cov = sum(Decimal(o["quantity"]) for o in self.live_stops(s) if o["side"] == side)
                self.coverage.append((len(self.calls), s, n, cov >= abs(n)))

    def _ok(self, data):
        return 200, json.dumps(data).encode(), {}

    def _error(self, status, etype, msg, code=None):
        e = {"type": etype, "message": msg}
        if code is not None:
            e["code"] = code
        return status, json.dumps({"error": e}).encode(), {}

    def _uid(self):
        self.n += 1
        return str(uuid.UUID(int=self.n))

    # ------------------------------------------------------------ state
    def _upnl(self, s):
        n = self.pos[s]
        return float(n) * (self.prices[s] - self.entry[s]) if n else 0.0

    def _margin(self, s):
        n = self.pos[s]
        return abs(float(n)) * self.entry[s] / self.levs[s][1] if n else 0.0

    def _fill(self, s, side, qty, price, order):
        """Fill ``qty`` of ``order`` at ``price``: one-way netting (reduceOnly never past the position)."""
        sgn = 1 if side == "BUY" else -1
        n = self.pos[s]
        realized = 0.0
        if n and (n > 0) != (sgn > 0):
            k = min(qty, abs(n))
            realized = float(k) * (price - self.entry[s]) * (1 if n > 0 else -1)
            self.pos[s] = n + sgn * k
            if self.pos[s] == 0:
                self.entry[s] = 0.0
            rest = qty - k
        else:
            rest = qty
        if rest > 0 and not order.get("reduceOnly"):
            q0 = abs(self.pos[s])
            self.entry[s] = float((q0 * Decimal(repr(self.entry[s])) + rest * Decimal(repr(price))) / (q0 + rest))
            self.pos[s] += sgn * rest
        filled = qty if not order.get("reduceOnly") else qty - rest
        fee = float(filled) * price * self.fee
        self.wallet += realized - fee
        t = self.ns()
        self.execs.append({"execId": self._uid(), "orderId": order["orderId"], "symbol": perp(s), "side": side,
                           "orderType": order["orderType"], "price": order.get("price"), "quantity": order["quantity"],
                           "timeInForce": order["timeInForce"], "status": "FILLED", "execType": "TRADE",
                           "settlementCurrency": "USDT", "orderTime": order["orderTime"], "transactTime": t,
                           "lastPrice": repr(price), "lastQty": str(filled), "execFee": f"{fee:.8f}",
                           "cumQty": str(filled), "avgPrice": repr(price), "conditionalOrderType": "INVALID"})
        if self.pos[s] == 0 and self.flat_cancels:
            for oid in [o for o, r in self.pending.items() if r["symbol"] == perp(s) and r.get("reduceOnly")]:
                self._finish(self.pending.pop(oid), "CANCELED", Decimal(0), None)
        return filled

    def _finish(self, order, status, cum, avg):
        order = {**order, "status": status, "cumQty": str(cum), "leavesQty": "0",
                 "avgPrice": repr(avg) if avg else "0", "transactTime": self.ns(), "orderCancelReason": "",
                 "orderRejectReason": "", "conditionalOrderType": order.get("conditionalOrderType", "INVALID")}
        self.orders[order["orderId"]] = order
        return order

    def _trigger(self, s):
        for oid, o in sorted(self.pending.items()):
            if oid not in self.pending or o["symbol"] != perp(s) or o["orderType"] != "STOP_MARKET":
                continue
            px = self.prices[s] if self.stop_price == "last" else self.marks[s]
            trig = float(o["triggerPrice"])
            if (o["side"] == "SELL" and px <= trig) or (o["side"] == "BUY" and px >= trig):
                self._fire(oid, self.prices[s])

    def _fire(self, oid, px):
        o = self.pending.pop(oid)
        s = o["symbol"][:-5]
        q = Decimal(o["quantity"])
        self.execs.append({"execId": self._uid(), "orderId": oid, "symbol": o["symbol"], "side": o["side"],
                           "orderType": "STOP_MARKET", "timeInForce": "GTC", "status": "FILLED",
                           "execType": "TRIGGERED",
                           "settlementCurrency": "USDT", "orderTime": o["orderTime"], "transactTime": self.ns(),
                           "lastPrice": "0", "lastQty": "0", "execFee": "0", "conditionalOrderType": "INVALID"})
        if self.own_fills:
            filled = self._fill(s, o["side"], q, px, o)
            self._finish(o, "FILLED", filled, px)
        else:
            child = {"orderId": self._uid(), "symbol": o["symbol"], "side": o["side"], "orderType": "MARKET",
                     "quantity": o["quantity"], "timeInForce": "IOC", "orderTime": self.ns(), "reduceOnly": True}
            filled = self._fill(s, o["side"], q, px, child)
            self._finish(child, "FILLED", filled, px)
            self._finish(o, "FILLED", Decimal(0), None)

    # ------------------------------------------------------------ routes
    def _route(self, m, path, query, body):
        q = dict(urllib.parse.parse_qsl(query)) if m == "GET" else json.loads(body or b"{}")
        if (m, path) == ("GET", "/api/v1/public/time"):
            return self._ok({"serverTime": self.ns()})
        if (m, path) == ("GET", "/api/v1/market/contract"):
            return self._ok([self._contract(s) for s in SPECS if not q.get("symbol") or q["symbol"] == perp(s)]
                            + [{"symbol": "BTCUSD.PERP", "quoteCurrency": "USD", "tickSize": "0.5",
                                "unitOrderQty": "1", "maxLeverage": "50"}])
        if (m, path) == ("GET", "/api/v1/trade/symbol"):
            return self._ok({"spot": ["BTCUSDT"], "perpetualSwap": [perp(s) for s in SPECS]})
        if (m, path) == ("GET", "/api/v1/market/ticker"):
            s = q["symbol"][:-5]
            return self._ok({"symbol": q["symbol"], "lastPrice": repr(self.prices[s]),
                             "markPrice": repr(self.marks[s]), "bidPrice": repr(self.prices[s]),
                             "askPrice": repr(self.prices[s])})
        if (m, path) == ("GET", "/api/v1/market/kline"):
            s = q["symbol"][:-5]
            lo, hi = int(q["startTime"]) // 1_000_000, int(q["endTime"]) // 1_000_000
            assert q["interval"] == "1" and hi > lo and 100 <= int(q.get("limit", 100)) <= 1000
            rows = [[str(t * 1_000_000), repr(b[0]), repr(b[1]), repr(b[2]), repr(b[3]), "1", "1"]
                    for (sym, t), b in sorted(self.bars.items()) if sym == s and lo <= t <= hi]
            return self._ok(rows[:int(q.get("limit", 100))])
        if (m, path) == ("GET", "/api/v1/market/fee-rate"):
            return self._ok([{"level": 1, "requiredTradeVolume": "1000000", "requiredAssetBalance": "0",
                              "feeRate": "0.00055"},
                             {"level": 0, "requiredTradeVolume": "0", "requiredAssetBalance": "0",
                              "feeRate": str(self.fee)}])
        if (m, path) == ("GET", "/api/v1/account"):
            up = sum(self._upnl(s) for s in SPECS)
            mg = sum(self._margin(s) for s in SPECS)
            return self._ok({"totalWalletBalance": f"{self.wallet:.8f}", "totalUnrealizedPnl": f"{up:.8f}",
                             "totalMarginBalance": f"{self.wallet + up:.8f}", "totalMarginReserved": f"{mg:.8f}",
                             "availableBalance": f"{self.wallet - mg:.8f}"})
        if (m, path) == ("GET", "/api/v1/account/balance"):
            return self._ok([{"asset": "USDT", "balance": f"{self.wallet:.8f}", "availableBalance": "0",
                              "maxWithdrawableAmount": "0"},
                             {"asset": "USDC", "balance": "0", "availableBalance": "0", "maxWithdrawableAmount": "0"}])
        if (m, path) == ("PUT", "/api/v1/account/trade-mode"):
            assert set(q) == {"tradeMode"} and q["tradeMode"] in ("ONE_WAY", "MULTIPLE_POSITIONS")
            if any(self.pos.values()):
                return self._error(400, "RemainingPositionsExist", "Close all positions first")
            self.mode = q["tradeMode"]
            return self._ok({"tradeMode": self.mode})
        if (m, path) == ("POST", "/api/v1/trade/leverage"):
            s = q["symbol"][:-5]
            assert isinstance(q["leverage"], int) and q["marginType"] in ("ISOLATED", "CROSS"), q
            if q["leverage"] > int(SPECS[s]["lev"]):
                return self._error(400, "InvalidLeverage", "leverage too large")
            if self.pos[s] and self.levs[s][0] != q["marginType"]:
                return self._error(400, "PositionExists", "cannot change margin type with a position")
            self.levs[s] = [q["marginType"], q["leverage"]]
            self.set_levs.add(s)
            return self._ok({"position": self._pos_row(s) if self.settings_rows or self.pos[s] else None})
        if (m, path) == ("GET", "/api/v1/account/position"):
            rows = []
            for s in SPECS:
                if q.get("symbol") and q["symbol"] != perp(s):
                    continue
                if self.pos[s] or (self.settings_rows and s in self.set_levs):
                    rows.append(self._pos_row(s))
            return self._ok(rows)
        if (m, path) == ("POST", "/api/v1/trade/order"):
            return self._place(q, body)
        if (m, path) == ("GET", "/api/v1/trade/order"):
            rows = [self._public(o) for o in self.pending.values() if not q.get("symbol") or o["symbol"] == q["symbol"]]
            return self._ok({"orders": rows})
        if (m, path) == ("DELETE", "/api/v1/trade/order"):
            o = self.pending.get(q.get("orderId"))
            if o is None or o["symbol"] != q.get("symbol"):
                return self._error(404, "OrderNotFound", "Order not found")
            self._finish(self.pending.pop(q["orderId"]), "CANCELED", Decimal(0), None)
            return self._ok({})
        if (m, path) == ("GET", "/api/v1/trade/order/history"):
            lo, hi = int(q["startTime"]), int(q["endTime"])
            rows = [o for o in self.orders.values() if o["symbol"] == q.get("symbol", o["symbol"])
                    and lo <= int(o["orderTime"]) <= hi
                    and self.now() - int(o["orderTime"]) // 1_000_000 >= self.history_lag_ms]
            rows.sort(key=lambda o: (int(o["orderTime"]), o["orderId"]), reverse=True)
            return self._page(rows, q, "orderId")
        if (m, path) == ("GET", "/api/v1/trade/execution/history"):
            lo, hi = int(q["startTime"]), int(q["endTime"])
            rows = [e for e in self.execs if lo <= int(e["transactTime"]) <= hi
                    and (not q.get("symbol") or e["symbol"] == q["symbol"])
                    and (not q.get("orderId") or e["orderId"] == q["orderId"])
                    and (not q.get("execType") or e["execType"] == q["execType"])]
            rows.sort(key=lambda e: (int(e["transactTime"]), e["execId"]), reverse=True)
            return self._page(rows, q, "execId")
        return self._error(404, "NotFound", "404 Route Not Found")

    def _page(self, rows, q, key):
        count = int(q.get("count", PAGE))
        if q.get("before"):
            i = next((i for i, r in enumerate(rows) if r[key] == q["before"]), len(rows))
            rows = rows[i + 1:]
        return self._ok({"history": [self._public(r) for r in rows[:count]], "hasPrev": bool(q.get("before")),
                         "hasNext": len(rows) > count})

    def _contract(self, s):
        sp = SPECS[s]
        return {"symbol": perp(s), "quoteCurrency": "USDT", "initMarginRate": "0.01", "maintMarginRate": "0.005",
                "maxLeverage": sp["lev"], "fundingIntervalHours": 8, "tickSize": sp["tick"],
                "unitOrderQty": sp["step"], "notionalMinOrderAmount": sp["min"],
                "notionalMaxOrderAmount": "5000000", "notionalMaxPositionAmount": "10000000"}

    def _pos_row(self, s):
        n = self.pos[s]
        row = {"symbol": perp(s), "slot": 0, "leverage": self.levs[s][1], "marginType": self.levs[s][0],
               "positionSide": None, "positionAmount": None}
        if n:
            row.update(positionSide="LONG" if n > 0 else "SHORT", positionAmount=str(abs(n)),
                       entryPrice=repr(self.entry[s]), markPrice=repr(self.marks[s]),
                       unrealizedPnl=f"{self._upnl(s):.8f}", liquidationPrice="0", totalFee="0")
        return row

    @staticmethod
    def _public(o):
        return {k: v for k, v in o.items() if k not in ("reduceOnly",)}

    def _place(self, q, body):
        s = q["symbol"][:-5]
        sp = SPECS[s]
        assert q["side"] in ("BUY", "SELL") and q["type"] in ("MARKET", "STOP_MARKET"), q
        assert isinstance(q["quantity"], str) and "amount" not in q, q
        qty = Decimal(q["quantity"])
        assert qty > 0 and (qty / Decimal(sp["step"])) == (qty / Decimal(sp["step"])).to_integral_value(), q
        if "maxSlippagePrice" in q:
            self.slippage_sent.append(q)
        if q["type"] == "MARKET":
            if "timeInForce" in q:
                return self._error(400, "BadRequest", "timeInForce must not be set for MARKET orders")
            assert "price" not in q, q
        if self.mode != "ONE_WAY":
            return self._error(400, "InvalidTradeMode", "use the position endpoints in multiple-position mode")
        n = self.pos[s]
        reduce = bool(q.get("reduceOnly"))
        if reduce and not ((q["side"] == "SELL" and n > 0) or (q["side"] == "BUY" and n < 0)):
            return self._error(400, "ReduceOnlyRejected", "reduce-only order would not reduce the position")
        oid = self._uid()
        order = {"orderId": oid, "symbol": q["symbol"], "side": q["side"], "orderType": q["type"],
                 "quantity": q["quantity"], "timeInForce": "IOC" if q["type"] == "MARKET" else "GTC",
                 "orderTime": self.ns(), "reduceOnly": reduce, "leavesQty": q["quantity"]}
        if q["type"] == "STOP_MARKET":
            assert reduce and "maxSlippagePrice" not in q and q.get("price"), q
            px = self.prices[s] if self.stop_price == "last" else self.marks[s]
            trig = float(q["price"])
            past = (q["side"] == "SELL" and px <= trig) or (q["side"] == "BUY" and px >= trig)
            if past and self.past_stop == "refuse":
                return self._error(400, "InvalidTriggerPrice", "trigger price would trigger immediately")
            if not self.two_stops and self.live_stops(s):
                return self._error(400, "TooManyConditionalOrders", "only one stop order per symbol")
            order.update(triggerPrice=q["price"], price=q["price"], status="NEW")
            self.pending[oid] = order
            if past:
                self._fire(oid, self.prices[s])
            return self._ok({"order": self._public(order)})
        if reduce:
            assert "maxSlippagePrice" not in q, q                  # a close must close
        want = qty if self.partial is None else (qty * Decimal(str(self.partial)) / Decimal(sp["step"])
                                                 ).to_integral_value() * Decimal(sp["step"])
        self.partial = None
        filled = self._fill(s, q["side"], want, self.prices[s], order) if want > 0 else Decimal(0)
        status = "FILLED" if filled == qty else "CANCELED"
        done = self._finish(order, status, filled, self.prices[s] if filled else None)
        # the IOC answer: an unfilled part is cancelled, ``quantity`` is then the filled amount (Place Order docs)
        ans = {k: v for k, v in done.items() if k in ("orderId", "symbol", "side", "orderType", "timeInForce")}
        ans.update(quantity=str(filled), status=status, leavesQty="0", price=repr(self.prices[s]))
        return self._ok({"order": ans})
