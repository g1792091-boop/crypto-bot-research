"""Stateful fake of the Binance USD-M futures testnet REST API (for tests; no network).

Covers what paperbot/testnet.py and paperbot/executor.py use: positions (one-way), market orders
(with client ids, partial fills), STOP_MARKET algo orders (place / query / list / cancel, trigger
on the LAST price, -2021 when the stop is already past the price), account balances, rate-limit
headers.

Failures are injected per request with ``fail(method, path, kind, ...)``:
- "drop_before": the request never reaches the exchange (TimeoutError)
- "drop_after":  the exchange executes it, the answer is lost (TimeoutError)
- "503_before" / "503_after": HTTP 503, not executed / executed
- "429":         HTTP 429 with Retry-After
- "418":         HTTP 418 (IP ban)
- ("code", n, msg): HTTP 400 with that Binance error code

After every request the fake records, per open position, whether a live stop covers it
(``timeline``), so tests can assert a position was never left unprotected.

Also: account fills (GET /fapi/v1/userTrades, with realizedPnl and commission), funding (``add_funding``,
GET /fapi/v1/income), leverage brackets, adverse fill slippage (``slip``, ``stop_slip``), and the mainnet
hosts (``FakeFutures(host="fapi.binance.com")``, which also answers GET /sapi/v1/account/apiRestrictions on
api.binance.com from ``restrictions``).
"""

from __future__ import annotations

import json
import urllib.parse

SPECS = {
    "BTCUSDT": {"step": "0.001", "min": "0.001", "tick": "0.1", "notional": "100"},
    "ETHUSDT": {"step": "0.001", "min": "0.001", "tick": "0.01", "notional": "20"},
    "SOLUSDT": {"step": "1", "min": "1", "tick": "0.01", "notional": "5"},
}


class FakeFutures:
    def __init__(self, prices=None, wallet=10_000.0, fee=0.0005, host="testnet.binancefuture.com", api_key="k"):
        self.host, self.api_key = host, api_key
        self.hosts = {host} | ({"api.binance.com"} if host == "fapi.binance.com" else set())
        self.clock = lambda: 0     # exchange time of fills and income (tests bind it to their clock)
        self.server_time = None    # /fapi/v1/time answer (None: 1000, as before)
        self.slip = 0.0            # market orders fill this fraction worse than the last price
        self.stop_slip = 0.0       # triggered stops fill this fraction worse than the trigger price
        self.fills = []            # userTrades rows
        self.income = []           # income rows (FUNDING_FEE)
        self.restrictions = {"ipRestrict": True, "enableReading": True, "enableWithdrawals": False,
                             "enableInternalTransfer": False, "enableMargin": False, "enableFutures": True,
                             "permitsUniversalTransfer": False, "enableSpotAndMarginTrading": False}
        self.last = dict(prices or {"BTCUSDT": 100.0, "ETHUSDT": 50.0, "SOLUSDT": 10.0})
        self.pos = {s: 0.0 for s in self.last}
        self.entry = {s: 0.0 for s in self.last}
        self.wallet, self.fee = wallet, fee
        self.lev = {s: 20 for s in self.last}
        self.margin = {s: "CROSSED" for s in self.last}
        self.dual = False
        self.orders = {}           # regular orders by id (market: filled at once)
        self.by_client = {}        # newClientOrderId -> id
        self.algos = {}            # algoId -> algo order dict (all, any status)
        self.algo_client = {}      # clientAlgoId -> algoId
        self.next_id = 1
        self.calls = []            # (method, path, params) of every request that reached routing
        self.failures = []         # [method, path, kind, extra, remaining]
        self.timeline = []         # (call index, method, path, {symbol: (amt, covered)})
        self.partial = None        # next market order fills this fraction
        self.weight = 0

    # ------------------------------------------------------------ test controls
    def fail(self, method, path, kind, times=1, extra=None):
        self.failures.append([method, path, kind, extra, times])

    def add_funding(self, symbol, amount, time=None):
        """A funding settlement on the open position (+ received, - paid)."""
        self.wallet += amount
        self.income.append({"symbol": symbol, "incomeType": "FUNDING_FEE", "income": str(amount), "asset": "USDT",
                            "info": "", "time": self.clock() if time is None else time,
                            "tranId": 900_000 + len(self.income), "tradeId": ""})

    def set_price(self, symbol, price):
        self.last[symbol] = price
        self._trigger(symbol)
        self._snap("PRICE", symbol)

    def live_stops(self, symbol=None):
        return [o for o in self.algos.values() if o["algoStatus"] == "NEW"
                and (symbol is None or o["symbol"] == symbol)]

    def covered(self, symbol):
        amt = self.pos[symbol]
        if amt == 0:
            return True
        side = "SELL" if amt > 0 else "BUY"
        for o in self.live_stops(symbol):
            if o["side"] == side and (o["closePosition"] or float(o["quantity"]) >= abs(amt) - 1e-12):
                return True
        return False

    def unprotected_moments(self, symbol):
        """Timeline entries where ``symbol`` had a position and no covering stop."""
        return [t for t in self.timeline if symbol in t[3] and t[3][symbol][0] != 0 and not t[3][symbol][1]]

    def _snap(self, method, path):
        self.timeline.append((len(self.calls), method, path,
                              {s: (self.pos[s], self.covered(s)) for s in self.pos if self.pos[s] != 0}))

    # ------------------------------------------------------------ transport
    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        assert u.hostname in self.hosts, u.hostname
        assert (u.hostname == "api.binance.com") == u.path.startswith("/sapi/"), (u.hostname, u.path)
        q = dict(urllib.parse.parse_qsl(u.query if body is None else body.decode()))
        public = u.path in ("/fapi/v1/exchangeInfo", "/fapi/v1/premiumIndex", "/fapi/v1/ticker/price", "/fapi/v1/time")
        if not public:
            assert "signature" in q and headers["X-MBX-APIKEY"] == self.api_key
        q.pop("signature", None)
        q.pop("timestamp", None)
        q.pop("recvWindow", None)
        f = self._take(method, u.path)
        kind = f[2] if f else None
        if kind == "drop_before":
            raise TimeoutError("timed out")
        if kind == "503_before":
            return 503, json.dumps({"code": -1007, "msg": "Timeout waiting for response from backend server."}).encode()
        if kind == "429":
            return 429, json.dumps({"code": -1003, "msg": "Too many requests"}).encode(), {"Retry-After": "2"}
        if kind == "418":
            return 418, json.dumps({"code": -1003, "msg": "banned"}).encode(), {"Retry-After": "60"}
        if isinstance(kind, tuple) and kind[0] == "code":
            return 400, json.dumps({"code": kind[1], "msg": kind[2]}).encode()
        self.calls.append((method, u.path, q))
        self.weight += 1
        status, data = self.route(method, u.path, q)
        self._snap(method, u.path)
        if kind == "drop_after":
            raise TimeoutError("timed out after sending")
        if kind == "503_after":
            return 503, json.dumps({"code": -1007, "msg": "Timeout waiting for response from backend server."}).encode()
        return status, json.dumps(data).encode(), {"X-MBX-USED-WEIGHT-1M": str(self.weight)}

    def _take(self, method, path):
        for f in self.failures:
            if f[0] == method and f[1] == path and f[4] > 0:
                f[4] -= 1
                return f
        return None

    @staticmethod
    def err(code, msg, status=400):
        return status, {"code": code, "msg": msg}

    # ------------------------------------------------------------ exchange logic
    def _fill(self, symbol, signed_qty, price, reduce_only=False, order_id=None):
        amt = self.pos[symbol]
        if reduce_only:
            if amt == 0 or (amt > 0) == (signed_qty > 0):
                return 0.0
            signed_qty = max(-abs(amt), min(abs(amt), signed_qty))
        new = round(amt + signed_qty, 9)
        realized = 0.0
        if amt != 0 and (amt > 0) != (signed_qty > 0):      # closing (part of) a position
            closed = min(abs(signed_qty), abs(amt))
            realized = closed * (price - self.entry[symbol]) * (1 if amt > 0 else -1)
            self.wallet += realized
            if abs(signed_qty) > abs(amt):
                self.entry[symbol] = price
        else:
            tot = abs(amt) + abs(signed_qty)
            self.entry[symbol] = (abs(amt) * self.entry[symbol] + abs(signed_qty) * price) / tot
        fee = abs(signed_qty) * price * self.fee
        self.wallet -= fee
        self.pos[symbol] = new
        if new == 0:
            self.entry[symbol] = 0.0
        self.fills.append({"symbol": symbol, "id": len(self.fills) + 1, "orderId": order_id or 0,
                           "side": "BUY" if signed_qty > 0 else "SELL", "price": str(price),
                           "qty": str(abs(signed_qty)), "realizedPnl": str(realized),
                           "quoteQty": str(abs(signed_qty) * price), "commission": str(fee),
                           "commissionAsset": "USDT", "time": self.clock(), "buyer": signed_qty > 0,
                           "maker": False, "positionSide": "BOTH", "marginAsset": "USDT"})
        return abs(signed_qty)

    def _trigger(self, symbol):
        p = self.last[symbol]
        for o in list(self.live_stops(symbol)):
            hit = p <= float(o["triggerPrice"]) if o["side"] == "SELL" else p >= float(o["triggerPrice"])
            if not hit:
                continue
            amt = self.pos[symbol]
            q = abs(amt) if o["closePosition"] else float(o["quantity"])
            px = p * (1 - self.stop_slip) if o["side"] == "SELL" else p * (1 + self.stop_slip)
            oid = self.next_id
            self.next_id += 1
            done = self._fill(symbol, -q if o["side"] == "SELL" else q, px, reduce_only=True, order_id=oid)
            o["algoStatus"] = "FINISHED"
            o["actualQty"] = str(done)
            o["actualPrice"] = str(px)
            o["actualOrderId"] = str(oid)

    def upnl(self):
        return sum(self.pos[s] * (self.last[s] - self.entry[s]) for s in self.pos if self.pos[s])

    def route(self, m, path, q):
        ok = lambda d: (200, d)  # noqa: E731
        if path == "/fapi/v1/time":
            return ok({"serverTime": 1_000 if self.server_time is None else self.server_time})
        if path == "/sapi/v1/account/apiRestrictions":
            return ok(dict(self.restrictions))
        if path == "/fapi/v1/userTrades":
            lo, hi = int(q.get("startTime", 0)), int(q.get("endTime", 2**62))
            assert hi - lo <= 7 * 86_400_000, "userTrades: at most 7 days per request"
            return ok([dict(f) for f in self.fills if f["symbol"] == q["symbol"] and lo <= f["time"] <= hi])
        if path == "/fapi/v1/income":
            lo, hi = int(q.get("startTime", 0)), int(q.get("endTime", 2**62))
            return ok([dict(r) for r in self.income if (not q.get("symbol") or r["symbol"] == q["symbol"])
                       and (not q.get("incomeType") or r["incomeType"] == q["incomeType"]) and lo <= r["time"] <= hi])
        if path == "/fapi/v1/leverageBracket":
            return ok([{"symbol": s, "brackets": [
                {"bracket": 1, "initialLeverage": 125, "notionalCap": 50_000, "notionalFloor": 0,
                 "maintMarginRatio": 0.004, "cum": 0.0},
                {"bracket": 2, "initialLeverage": 100, "notionalCap": 250_000, "notionalFloor": 50_000,
                 "maintMarginRatio": 0.005, "cum": 50.0},
                {"bracket": 3, "initialLeverage": 50, "notionalCap": 3_000_000, "notionalFloor": 250_000,
                 "maintMarginRatio": 0.01, "cum": 1_300.0}]} for s in self.last])
        if path == "/fapi/v1/exchangeInfo":
            return ok({"rateLimits": [{"rateLimitType": "REQUEST_WEIGHT", "interval": "MINUTE", "intervalNum": 1,
                                       "limit": 2400}],
                       "symbols": [{"symbol": s, "filters": [
                           {"filterType": "MARKET_LOT_SIZE", "stepSize": v["step"], "minQty": v["min"]},
                           {"filterType": "PRICE_FILTER", "tickSize": v["tick"]},
                           {"filterType": "MIN_NOTIONAL", "notional": v["notional"]}]} for s, v in SPECS.items()]})
        if path == "/fapi/v1/premiumIndex":
            return ok({"symbol": q["symbol"], "markPrice": str(self.last[q["symbol"]])})
        if path == "/fapi/v1/ticker/price":
            return ok({"symbol": q["symbol"], "price": str(self.last[q["symbol"]])})
        if path == "/fapi/v1/positionSide/dual":
            if not self.dual:
                return self.err(-4059, "No need to change position side.")
            self.dual = False
            return ok({"code": 200, "msg": "success"})
        if path == "/fapi/v1/marginType":
            s = q["symbol"]
            if self.margin[s] == "ISOLATED":
                return self.err(-4046, "No need to change margin type.")
            if self.pos[s] != 0:
                return self.err(-4048, "Margin type cannot be changed if there exists position.")
            self.margin[s] = "ISOLATED"
            return ok({"code": 200, "msg": "success"})
        if path == "/fapi/v1/leverage":
            self.lev[q["symbol"]] = int(q["leverage"])
            return ok({"leverage": int(q["leverage"]), "symbol": q["symbol"]})
        if path == "/fapi/v1/order" and m == "POST":
            return self._market(q)
        if path == "/fapi/v1/order" and m == "GET":
            oid = int(q["orderId"]) if "orderId" in q else self.by_client.get(q.get("origClientOrderId"))
            if oid not in self.orders:
                return self.err(-2013, "Order does not exist.")
            return ok(self.orders[oid])
        if path == "/fapi/v1/allOpenOrders":
            return ok({"code": 200, "msg": "The operation of cancel all open order is done."})
        if path == "/fapi/v1/openOrders":
            return ok([])
        if path == "/fapi/v1/algoOrder" and m == "POST":
            return self._algo(q)
        if path == "/fapi/v1/algoOrder" and m == "GET":
            aid = int(q["algoId"]) if "algoId" in q else self.algo_client.get(q.get("clientAlgoId"))
            if aid not in self.algos:
                return self.err(-2013, "Order does not exist.")
            return ok(dict(self.algos[aid]))
        if path == "/fapi/v1/algoOrder" and m == "DELETE":
            aid = int(q["algoId"]) if "algoId" in q else self.algo_client.get(q.get("clientAlgoId"))
            o = self.algos.get(aid)
            if o is None or o["algoStatus"] != "NEW":
                return self.err(-2011, "Unknown order sent.")
            o["algoStatus"] = "CANCELED"
            return ok({"algoId": aid, "clientAlgoId": o["clientAlgoId"], "code": "200", "msg": "success"})
        if path == "/fapi/v1/openAlgoOrders":
            return ok([dict(o) for o in self.live_stops(q.get("symbol"))])
        if path == "/fapi/v1/algoOpenOrders" and m == "DELETE":
            for o in self.live_stops(q["symbol"]):
                o["algoStatus"] = "CANCELED"
            return ok({"code": 200, "msg": "The operation of cancel all open order is done."})
        if path == "/fapi/v2/positionRisk":
            syms = [q["symbol"]] if "symbol" in q else list(self.pos)
            return ok([{"symbol": s, "positionAmt": str(self.pos[s]), "entryPrice": str(self.entry[s]),
                        "markPrice": str(self.last[s]), "marginType": self.margin[s].lower(),
                        "leverage": str(self.lev[s])} for s in syms])
        if path == "/fapi/v2/account":
            up = self.upnl()
            return ok({"totalWalletBalance": str(self.wallet), "totalUnrealizedProfit": str(up),
                       "totalMarginBalance": str(self.wallet + up)})
        if path == "/fapi/v1/order" and m == "DELETE":
            return self.err(-2011, "Unknown order sent.")
        raise AssertionError(f"unexpected {m} {path}")

    def _market(self, q):
        cid = q.get("newClientOrderId")
        if cid and cid in self.by_client:
            return self.err(-4116, "ClientOrderId is duplicated.")
        s = q["symbol"]
        qty = float(q["quantity"])
        reduce_only = q.get("reduceOnly") == "true"
        signed = qty if q["side"] == "BUY" else -qty
        amt = self.pos[s]
        if reduce_only and (amt == 0 or (amt > 0) == (signed > 0)):
            return self.err(-2022, "ReduceOnly Order is rejected.")
        frac = 1.0
        if self.partial is not None and not reduce_only:
            frac, self.partial = self.partial, None
        step = float(SPECS[s]["step"])
        want = round(int(qty * frac / step + 1e-9) * step, 9)
        oid = self.next_id
        self.next_id += 1
        px = self.last[s] * (1 + self.slip if signed > 0 else 1 - self.slip)
        filled = self._fill(s, want if signed > 0 else -want, px, reduce_only, order_id=oid) if want > 0 else 0.0
        o = {"orderId": oid, "clientOrderId": cid, "symbol": s, "side": q["side"], "type": "MARKET",
             "origQty": str(qty), "executedQty": str(filled), "avgPrice": str(px if filled else 0),
             "status": "FILLED" if filled >= qty - 1e-12 else ("EXPIRED" if filled == 0 else "PARTIALLY_FILLED"),
             "reduceOnly": reduce_only}
        if o["status"] == "PARTIALLY_FILLED":
            o["status"] = "EXPIRED"                       # a market order that could not fill fully
        self.orders[oid] = o
        if cid:
            self.by_client[cid] = oid
        return 200, o

    def _algo(self, q):
        assert q["algoType"] == "CONDITIONAL" and q["type"] == "STOP_MARKET", q
        assert "stopPrice" not in q, "the algo endpoint takes triggerPrice, not stopPrice"
        cid = q.get("clientAlgoId")
        if cid and cid in self.algo_client and self.algos[self.algo_client[cid]]["algoStatus"] == "NEW":
            return self.err(-20132, "The client algo id is duplicated.")
        s, side, trig = q["symbol"], q["side"], float(q["triggerPrice"])
        close = q.get("closePosition") == "true"
        if close and ("quantity" in q or "reduceOnly" in q):
            return self.err(-4137, "Quantity must be zero with closePosition equals true")
        if close and any(o["side"] == side and o["closePosition"] for o in self.live_stops(s)):
            return self.err(-4130, "An open stop or take profit order with GTE and closePosition in the "
                                   "direction is existing.")
        p = self.last[s]
        if (side == "SELL" and p <= trig) or (side == "BUY" and p >= trig):
            return self.err(-2021, "Order would immediately trigger.")
        aid = self.next_id
        self.next_id += 1
        o = {"algoId": aid, "clientAlgoId": cid or f"auto{aid}", "algoType": "CONDITIONAL", "orderType": "STOP_MARKET",
             "symbol": s, "side": side, "positionSide": "BOTH", "quantity": q.get("quantity", "0"),
             "algoStatus": "NEW", "triggerPrice": q["triggerPrice"], "workingType": q.get("workingType"),
             "priceProtect": q.get("priceProtect") == "true", "closePosition": close,
             "reduceOnly": q.get("reduceOnly") == "true"}
        self.algos[aid] = o
        self.algo_client[o["clientAlgoId"]] = aid
        return 200, dict(o)
