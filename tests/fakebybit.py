"""Stateful fake of Bybit's v5 REST API, category "linear" (for tests; no network).

Answers in the shapes of Bybit's v5 docs (github.com/bybit-exchange/docs, 2026-10): {retCode, retMsg, result, time}.
Every private request's signature is checked (HMAC-SHA256 of timestamp + key + recv window + query string or JSON
body, X-BAPI-* headers) and so is the timestamp against the recv window; request bodies are checked against the
documented parameters (strings for qty / triggerPrice, booleans for reduceOnly / closeOnTrigger, ...).

Covers what paperbot/bybit.py uses: instruments-info, tickers, risk-limit, time, account info and margin mode, wallet
balance, position mode, leverage, positions, market orders (filled at once, but read back as "New" for
``market_lag`` reads: creation is asynchronous), conditional stop orders (trigger on the last price, 110092 / 110093
when the trigger is already past, Untriggered -> Filled with the same order id when hit), cancels (a cancelled
conditional can still show in the open list for ``cancel_lag`` reads), executions (with closedSize and Funding rows),
closed-pnl records, the transaction log (TRADE, SETTLEMENT, TRANSFER_IN/OUT), the key's permissions, rate-limit
headers.

Failures are injected per request with ``fail(method, path, kind, times)``:
- "drop_before" / "drop_after": TimeoutError before / after the exchange executed it
- "cut_after": executed, the answer cut off (http.client.IncompleteRead)
- "503_before" / "503_after": HTTP 503, not executed / executed
- "429": HTTP 429; "403": HTTP 403 (IP ban)
- ("ret", code, msg): HTTP 200 with that retCode, not executed
- ("ret_after", code, msg): executed, then HTTP 200 with that retCode (e.g. 10016 server error)

After every request the fake records, per open position, whether a live stop covers it (``timeline``).
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import urllib.parse
from decimal import Decimal

SPECS = {   # test data only: the client reads every value from instruments-info
    "BTCUSDT": {"step": "0.001", "min": "0.001", "tick": "0.10", "notional": "5", "lev": "100.00"},
    "ETHUSDT": {"step": "0.01", "min": "0.01", "tick": "0.01", "notional": "5", "lev": "100.00"},
    "SOLUSDT": {"step": "0.1", "min": "0.1", "tick": "0.001", "notional": "5", "lev": "75.00"},
    "DOGEUSDT": {"step": "1", "min": "1", "tick": "0.00001", "notional": "5", "lev": "75.00"},
}
SEVEN_DAYS = 7 * 86_400_000


class FakeBybit:
    def __init__(self, prices=None, wallet=10_000.0, fee=0.00055, host="api-testnet.bybit.com", api_key="k",
                 api_secret="s", uta=6):
        self.host, self.api_key, self.api_secret = host, api_key, api_secret
        self.hosts = {host}
        self.clock = lambda: 1_800_000_000_000
        self.skew = 0                      # server clock - test clock (ms)
        self.last = dict(prices or {"BTCUSDT": 100.0, "ETHUSDT": 50.0, "SOLUSDT": 10.0})
        self.pos = {s: Decimal(0) for s in self.last}
        self.entry = {s: 0.0 for s in self.last}
        self.lev = {s: "10" for s in self.last}
        self.hedge = {s: False for s in self.last}
        self.info = {"unifiedMarginStatus": uta, "marginMode": "REGULAR_MARGIN", "isMasterTrader": False,
                     "spotHedgingStatus": "OFF", "updatedTime": "0"}
        self.trade_mode = {s: 0 for s in self.last}          # classic accounts: per symbol (1 = isolated)
        self.wallet, self.fee = wallet, fee
        self.other_coins = {}               # coin -> wallet balance besides USDT
        self.bonus = 0.0
        self.orders = {}                    # orderId -> Bybit order row (every status)
        self.by_link = {}                   # orderLinkId -> orderId
        self.execs, self.closed, self.log = [], [], []
        self.calls, self.failures, self.timeline = [], [], []
        self.n = 0
        self.partial = None                 # the next opening market order fills this fraction
        self.slip = 0.0
        self.stop_slip = 0.0
        self.market_lag = 0
        self.cancel_lag = 0
        self.ghosts = {}                    # orderId -> list reads it still shows as Untriggered after a cancel
        self.lag_left = {}                  # orderId -> reads left that show a new market order as New
        self.closed_hidden = False          # closed-pnl answers nothing (records lag)
        # the docs do not say whose side a closed-pnl record's ``side`` is: "order" (the closing order's side, as the
        # docs' example numbers suggest) or "position" (the closed position's side); the client must not depend on it
        self.closed_side = "order"
        self.closed_tamper = None           # f(record) -> record, applied to closed-pnl answers (a wrong record)
        self.margin_refusal = None          # a reason the account cannot be set to isolated margin
        self.key_info = {"id": "1", "note": "exec", "apiKey": api_key, "readOnly": 0, "secret": "",
                         "permissions": {"ContractTrade": ["Order", "Position"], "Spot": [], "Wallet": [],
                                         "Options": [], "Derivatives": [], "Exchange": [], "Earn": []},
                         "ips": ["158.247.200.152"], "type": 1, "uta": 1, "isMaster": False}
        self.page = 50                      # rows per page of the cursor lists (smaller: tests paging)

    # ------------------------------------------------------------ test controls
    def fail(self, method, path, kind, times=1, when=None):
        """``when(params)``: only requests whose parameters match (e.g. a look-up by orderLinkId)."""
        self.failures.append([method, path, kind, times, when])

    def set_price(self, symbol, price):
        self.last[symbol] = price
        self._trigger(symbol)
        self._snap("PRICE", symbol)

    def live_stops(self, symbol=None):
        return [o for o in self.orders.values() if o["orderStatus"] == "Untriggered"
                and (symbol is None or o["symbol"] == symbol)]

    def covered(self, symbol):
        amt = self.pos[symbol]
        if amt == 0:
            return True
        side = "Sell" if amt > 0 else "Buy"
        for o in self.live_stops(symbol):
            protective = (side == "Sell" and o["triggerDirection"] == 2) or (side == "Buy" and o["triggerDirection"] == 1)
            if o["side"] == side and protective and (o["reduceOnly"] or o["closeOnTrigger"]) and \
                    (Decimal(o["qty"]) == 0 or Decimal(o["qty"]) >= abs(amt)):
                return True
        return False

    def unprotected_moments(self, symbol):
        return [t for t in self.timeline if symbol in t[3] and t[3][symbol][0] != 0 and not t[3][symbol][1]]

    def add_funding(self, symbol, amount, time=None):
        """A funding settlement (+ received): a SETTLEMENT log row and a Funding execution (its execFee is the
        opposite sign: + paid)."""
        t = self.clock() if time is None else time
        self.wallet += amount
        self._log("SETTLEMENT", symbol, t, funding=amount, change=amount, qty=abs(self.pos[symbol]))
        self.n += 1
        self.execs.append({"symbol": symbol, "orderId": f"fund-{self.n}", "orderLinkId": "", "side": "Buy",
                           "orderPrice": "0", "orderQty": "0", "leavesQty": "0", "orderType": "UNKNOWN",
                           "stopOrderType": "UNKNOWN", "execFee": str(-amount), "execId": f"fundexec-{self.n}",
                           "execPrice": str(self.last[symbol]), "execQty": str(abs(self.pos[symbol])),
                           "execType": "Funding", "execValue": "0", "execTime": str(t), "feeCurrency": "",
                           "isMaker": False, "feeRate": "0.0001", "closedSize": "", "seq": self.n})

    def add_resting(self, symbol, side, qty, price, link=""):
        """An active (unfilled) limit order, e.g. placed on the website."""
        oid = self._new_id()
        self.orders[oid] = {"orderId": oid, "orderLinkId": link, "symbol": symbol, "side": side, "orderType": "Limit",
                            "price": str(price), "qty": str(qty), "positionIdx": 0, "timeInForce": "GTC",
                            "reduceOnly": False, "closeOnTrigger": False, "cumExecQty": "0", "avgPrice": "",
                            "leavesQty": str(qty), "orderStatus": "New", "cancelType": "UNKNOWN",
                            "rejectReason": "EC_NoError", "createdTime": str(self.clock()),
                            "updatedTime": str(self.clock()), "stopOrderType": "UNKNOWN", "triggerPrice": "0",
                            "triggerDirection": 0, "triggerBy": "UNKNOWN", "tpslMode": ""}
        if link:
            self.by_link[link] = oid
        return oid

    def add_log(self, kind, amount, time=None):
        """Another transaction-log row that moves the wallet (BONUS, AIRDROP, FEE_REFUND, CURRENCY_BUY, ...)."""
        t = self.clock() if time is None else time
        self.wallet += amount
        self._log(kind, "", t, cash=amount, change=amount)

    def add_transfer(self, amount, time=None):
        t = self.clock() if time is None else time
        self.wallet += amount
        self._log("TRANSFER_IN" if amount > 0 else "TRANSFER_OUT", "", t, cash=amount, change=amount)

    def _log(self, kind, symbol, t, cash=0.0, funding=None, fee=0.0, change=0.0, qty=0, trade_id="", order_id="",
             link=""):
        self.n += 1
        self.log.append({"id": f"{self.n}_{symbol}_{t}", "symbol": symbol, "category": "linear" if symbol else "",
                         "side": "None", "transactionTime": str(t), "type": kind, "transSubType": "", "qty": str(qty),
                         "size": str(self.pos.get(symbol, 0)), "currency": "USDT", "tradePrice": "",
                         "funding": "" if funding is None else str(funding), "fee": str(fee), "cashFlow": str(cash),
                         "change": str(change), "cashBalance": str(self.wallet), "feeRate": "", "bonusChange": "",
                         "tradeId": trade_id, "orderId": order_id, "orderLinkId": link})

    def _snap(self, method, path):
        self.timeline.append((len(self.calls), method, path,
                              {s: (self.pos[s], self.covered(s)) for s in self.pos if self.pos[s] != 0}))

    # ------------------------------------------------------------ transport
    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        assert u.scheme == "https" and u.hostname in self.hosts, url
        if method == "GET":
            assert body is None, "GET with a body"
            assert "cursor=" not in u.query or "cursor=p%3A" in u.query, f"cursor re-encoded: {u.query}"
            payload = u.query
            q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
        else:
            assert method == "POST" and not u.query, (method, url)
            assert headers.get("Content-Type") == "application/json"
            payload = body.decode()
            q = json.loads(payload)
        public = u.path.startswith("/v5/market/")
        if not public:
            assert headers["X-BAPI-API-KEY"] == self.api_key and headers["X-BAPI-SIGN-TYPE"] == "2"
            ts, rw = headers["X-BAPI-TIMESTAMP"], headers["X-BAPI-RECV-WINDOW"]
            want = hmac.new(self.api_secret.encode(), (ts + self.api_key + rw + payload).encode(),
                            hashlib.sha256).hexdigest()
            if headers["X-BAPI-SIGN"] != want:
                return self._answer(10004, "error sign! origin_string[...]", {})
            server = self.clock() + self.skew
            if not server - int(rw) <= int(ts) < server + 1000:
                return self._answer(10002, f"invalid request, please check your server timestamp or recv_window "
                                           f"param. req_timestamp[{ts}],server_timestamp[{server}],recv_window[{rw}]", {})
        f = self._take(method, u.path, q)
        kind = f[2] if f else None
        if kind == "drop_before":
            raise TimeoutError("timed out")
        if kind == "503_before":
            return 503, b"<html>503 Service Unavailable</html>", {}
        if kind == "429":
            return 429, b"", {"X-Bapi-Limit-Reset-Timestamp": str(self.clock() + 2000)}
        if kind == "403":
            return 403, b"access too frequent", {}
        if isinstance(kind, tuple) and kind[0] == "ret":
            return self._answer(kind[1], kind[2], {})
        self.calls.append((method, u.path, q))
        rc, msg, result = self.route(method, u.path, q)
        self._snap(method, u.path)
        if kind == "drop_after":
            raise TimeoutError("timed out after sending")
        if kind == "cut_after":
            raise http.client.IncompleteRead(b"")
        if kind == "503_after":
            return 503, b"<html>503</html>", {}
        if isinstance(kind, tuple) and kind[0] == "ret_after":
            return self._answer(kind[1], kind[2], {})
        return self._answer(rc, msg, result)

    def _answer(self, rc, msg, result):
        data = {"retCode": rc, "retMsg": msg, "result": result, "retExtInfo": {}, "time": self.clock() + self.skew}
        return 200, json.dumps(data).encode(), {"X-Bapi-Limit": "10", "X-Bapi-Limit-Status": "9",
                                                "X-Bapi-Limit-Reset-Timestamp": str(self.clock())}

    def _take(self, method, path, q):
        for f in self.failures:
            if f[0] == method and f[1] == path and f[3] > 0 and (f[4] is None or f[4](q)):
                f[3] -= 1
                return f
        return None

    # ------------------------------------------------------------ exchange logic
    def _fill(self, symbol, signed, price, order_id, link=""):
        """signed: Decimal quantity (+ buy, - sell)."""
        amt = self.pos[symbol]
        closing = Decimal(0)
        realized = 0.0
        if amt != 0 and (amt > 0) != (signed > 0):
            closing = min(abs(signed), abs(amt))
            realized = float(closing) * (price - self.entry[symbol]) * (1 if amt > 0 else -1)
            rec = next((r for r in self.closed if r["orderId"] == order_id), None)
            if rec is None:
                closing_side = "Sell" if amt > 0 else "Buy"
                side = closing_side if self.closed_side == "order" else ("Buy" if amt > 0 else "Sell")
                rec = {"symbol": symbol, "orderId": order_id, "side": side, "qty": "0",
                       "orderPrice": "0", "orderType": "Market", "execType": "Trade", "closedSize": "0",
                       "cumEntryValue": "0", "avgEntryPrice": str(self.entry[symbol]), "cumExitValue": "0",
                       "avgExitPrice": "0", "closedPnl": "0", "fillCount": "0", "leverage": self.lev[symbol],
                       "openFee": "0", "closeFee": "0", "createdTime": str(self.clock()),
                       "updatedTime": str(self.clock())}
                self.closed.append(rec)
            size = Decimal(rec["closedSize"]) + closing
            exit_value = float(rec["cumExitValue"]) + float(closing) * price
            entry_value = float(size) * self.entry[symbol]
            open_fee = float(size) * self.entry[symbol] * self.fee
            close_fee = float(rec["closeFee"]) + float(closing) * price * self.fee
            gross = (exit_value / float(size) - self.entry[symbol]) * float(size) * (1 if amt > 0 else -1)
            rec.update(closedSize=str(size), qty=str(size), cumEntryValue=str(entry_value),
                       cumExitValue=str(exit_value), avgExitPrice=str(exit_value / float(size)),
                       openFee=str(open_fee), closeFee=str(close_fee), closedPnl=str(gross - open_fee - close_fee),
                       fillCount=str(int(rec["fillCount"]) + 1), updatedTime=str(self.clock()))
            if abs(signed) > abs(amt):
                self.entry[symbol] = price
        else:
            tot = abs(amt) + abs(signed)
            self.entry[symbol] = (float(abs(amt)) * self.entry[symbol] + float(abs(signed)) * price) / float(tot)
        fee = float(abs(signed)) * price * self.fee
        self.wallet += realized - fee
        self.pos[symbol] = amt + signed
        if self.pos[symbol] == 0:
            self.entry[symbol] = 0.0
        self.n += 1
        exec_id = f"e{self.n:06d}-0000-4000-8000-{self.n:012d}"
        self.execs.append({"symbol": symbol, "orderId": order_id, "orderLinkId": link, "side": "Buy" if signed > 0
                           else "Sell", "orderPrice": "0", "orderQty": str(abs(signed)), "leavesQty": "0",
                           "orderType": "Market", "stopOrderType": "UNKNOWN", "execFee": str(fee), "execId": exec_id,
                           "execPrice": str(price), "execQty": str(abs(signed)), "execType": "Trade",
                           "execValue": str(float(abs(signed)) * price), "execTime": str(self.clock()),
                           "feeCurrency": "", "isMaker": False, "feeRate": str(self.fee), "markPrice": str(price),
                           "closedSize": str(closing) if closing else "", "seq": self.n})
        self._log("TRADE", symbol, self.clock(), cash=realized, fee=fee, change=realized - fee, qty=abs(signed),
                  trade_id=exec_id, order_id=order_id, link=link)
        return abs(signed)

    def _trigger(self, symbol):
        p = self.last[symbol]
        for o in list(self.live_stops(symbol)):
            trig = float(o["triggerPrice"])
            if not ((o["triggerDirection"] == 1 and p >= trig) or (o["triggerDirection"] == 2 and p <= trig)):
                continue
            amt = self.pos[symbol]
            want = Decimal(o["qty"]) if Decimal(o["qty"]) != 0 else abs(amt)
            if amt == 0 or (amt > 0) == (o["side"] == "Buy"):
                o.update(orderStatus="Cancelled", cancelType="CancelByReduceOnly", updatedTime=str(self.clock()))
                continue
            q = min(want, abs(amt))
            px = p * (1 - self.stop_slip) if o["side"] == "Sell" else p * (1 + self.stop_slip)
            self._fill(symbol, -q if o["side"] == "Sell" else q, px, o["orderId"], o["orderLinkId"])
            o.update(orderStatus="Filled", cumExecQty=str(q), avgPrice=str(px), leavesQty="0",
                     updatedTime=str(self.clock()))

    def _new_id(self):
        self.n += 1
        return f"{self.n:08x}-7b52-4ca9-ac2c-{self.n:012x}"

    def upnl(self):
        return sum(float(self.pos[s]) * (self.last[s] - self.entry[s]) for s in self.pos if self.pos[s])

    def _view(self, o, listing=False):
        """An order as a read shows it (a new market order reads as New for ``market_lag`` reads)."""
        v = dict(o)
        left = self.lag_left.get(o["orderId"], 0)
        if left > 0:
            self.lag_left[o["orderId"]] = left - 1
            v.update(orderStatus="New", cumExecQty="0", avgPrice="", leavesQty=o["qty"])
        return v

    def _range(self, q, default_span=SEVEN_DAYS):
        lo, hi = q.get("startTime"), q.get("endTime")
        assert lo is not None and hi is not None, "both startTime and endTime are passed"
        lo, hi = int(lo), int(hi)
        assert 0 <= hi - lo <= SEVEN_DAYS, "endTime - startTime <= 7 days"
        return lo, hi

    def _paged(self, rows, q):
        limit = min(int(q.get("limit") or 20), self.page)
        cur = q.get("cursor")
        off = int(cur.split(":")[1]) if cur else 0          # sent as given ("p%3A2"), decoded here
        page = rows[off:off + limit]
        nxt = f"p%3A{off + limit}" if off + limit < len(rows) else ""
        return {"list": page, "nextPageCursor": nxt, "category": "linear"}

    def route(self, m, path, q):
        ok = lambda r=None: (0, "OK", r if r is not None else {})  # noqa: E731
        if path == "/v5/market/time":
            t = self.clock() + self.skew
            return ok({"timeSecond": str(t // 1000), "timeNano": str(t * 1_000_000)})
        if path == "/v5/market/instruments-info":
            assert q["category"] == "linear"
            rows = [{"symbol": s, "contractType": "LinearPerpetual", "status": "Trading", "baseCoin": s[:-4],
                     "quoteCoin": "USDT", "settleCoin": "USDT", "priceScale": "2",
                     "leverageFilter": {"minLeverage": "1", "maxLeverage": v["lev"], "leverageStep": "0.01"},
                     "priceFilter": {"minPrice": v["tick"], "maxPrice": "1999999.80", "tickSize": v["tick"]},
                     "lotSizeFilter": {"maxOrderQty": "1190.000", "minOrderQty": v["min"], "qtyStep": v["step"],
                                       "maxMktOrderQty": "500.000", "minNotionalValue": v["notional"]}}
                    for s, v in SPECS.items() if q.get("symbol") in (None, s)]
            return ok({"category": "linear", "list": rows, "nextPageCursor": ""})
        if path == "/v5/market/tickers":
            s = q["symbol"]
            return ok({"category": "linear", "list": [{"symbol": s, "lastPrice": str(self.last[s]),
                                                       "markPrice": str(self.last[s]), "indexPrice": str(self.last[s])}]})
        if path == "/v5/market/risk-limit":
            s = q["symbol"]
            return ok({"category": "linear", "nextPageCursor": "", "list": [
                {"id": 1, "symbol": s, "riskLimitValue": "200000", "maintenanceMargin": "0.5", "initialMargin": "1",
                 "isLowestRisk": 1, "maxLeverage": "100.00", "mmDeduction": ""},
                {"id": 2, "symbol": s, "riskLimitValue": "800000", "maintenanceMargin": "1", "initialMargin": "2",
                 "isLowestRisk": 0, "maxLeverage": "50.00", "mmDeduction": "1000"}]})
        if path == "/v5/user/query-api":
            return ok(dict(self.key_info))
        if path == "/v5/account/info":
            return ok(dict(self.info))
        if path == "/v5/account/set-margin-mode":
            assert q == {"setMarginMode": "ISOLATED_MARGIN"}, q
            if self.info["marginMode"] == "ISOLATED_MARGIN":
                return 110026, "Cross/isolated margin mode is not modified", {}
            busy = any(self.pos.values()) or self.live_stops()
            if busy or self.margin_refusal:
                reason = self.margin_refusal or "You have unclosed hedge mode or isolated mode USDT perpetual positions"
                return 3400045, "Set margin mode failed", {"reasons": [{"reasonCode": "3400208", "reasonMsg": reason}]}
            self.info["marginMode"] = "ISOLATED_MARGIN"
            return ok({"reasons": []})
        if path == "/v5/position/switch-isolated":
            assert self.info["unifiedMarginStatus"] == 1, "switch-isolated is for classic accounts"
            s = q["symbol"]
            assert q["buyLeverage"] == q["sellLeverage"] and q["tradeMode"] in (0, 1)
            if self.trade_mode[s] == q["tradeMode"]:
                return 110026, "Cross/isolated margin mode is not modified", {}
            if self.pos[s] != 0:
                return 110024, "You have an existing position", {}
            self.trade_mode[s], self.lev[s] = q["tradeMode"], q["buyLeverage"]
            return ok()
        if path == "/v5/account/wallet-balance":
            assert q["accountType"] == ("UNIFIED" if self.info["unifiedMarginStatus"] != 1 else "CONTRACT"), q
            up = self.upnl()
            coins = [{"coin": "USDT", "walletBalance": str(self.wallet), "unrealisedPnl": str(up),
                      "equity": str(self.wallet + up), "bonus": str(self.bonus)}]
            coins += [{"coin": c, "walletBalance": str(v), "unrealisedPnl": "0", "equity": str(v), "bonus": "0"}
                      for c, v in self.other_coins.items()]
            return ok({"list": [{"accountType": q["accountType"], "totalWalletBalance": str(self.wallet),
                                 "coin": coins}]})
        if path == "/v5/position/switch-mode":
            assert q["category"] == "linear" and q["mode"] in (0, 3) and (q.get("coin") or q.get("symbol"))
            want = q["mode"] == 3
            todo = [s for s in self.hedge if self.hedge[s] != want and (q.get("symbol") in (None, s))]
            if not todo:
                return 110025, "Position mode is not modified", {}
            for s in todo:
                if self.pos[s] == 0:
                    self.hedge[s] = want
            return ok()
        if path == "/v5/position/set-leverage":
            s = q["symbol"]
            assert q["buyLeverage"] == q["sellLeverage"] and isinstance(q["buyLeverage"], str)
            if float(q["buyLeverage"]) > float(SPECS[s]["lev"]):
                return 10001, "leverage invalid", {}
            if float(self.lev[s]) == float(q["buyLeverage"]):
                return 110043, "Set leverage not modified", {}
            self.lev[s] = q["buyLeverage"]
            return ok()
        if path == "/v5/position/list":
            assert q["category"] == "linear" and (q.get("symbol") or q.get("settleCoin") == "USDT")
            syms = [q["symbol"]] if q.get("symbol") else [s for s in self.pos if self.pos[s] != 0]
            rows = []
            for s in syms:
                amt = self.pos[s]
                if self.hedge[s] and amt == 0:                  # hedge mode: a Buy-side and a Sell-side row
                    rows += [{"positionIdx": i, "symbol": s, "side": "", "size": "0", "avgPrice": "0",
                              "leverage": self.lev[s], "markPrice": str(self.last[s]), "liqPrice": "",
                              "unrealisedPnl": "0", "updatedTime": str(self.clock())} for i in (1, 2)]
                    continue
                rows.append({"positionIdx": 0, "riskId": 1, "riskLimitValue": "200000", "symbol": s,
                             "side": "" if amt == 0 else ("Buy" if amt > 0 else "Sell"), "size": str(abs(amt)),
                             "avgPrice": str(self.entry[s]), "positionValue": str(float(abs(amt)) * self.entry[s]),
                             "tradeMode": 0, "positionStatus": "Normal", "leverage": self.lev[s],
                             "markPrice": str(self.last[s]), "liqPrice": "", "unrealisedPnl":
                                 str(float(amt) * (self.last[s] - self.entry[s])), "curRealisedPnl": "0",
                             "cumRealisedPnl": "0", "createdTime": "0", "updatedTime": str(self.clock()), "seq": 1})
            return ok(self._paged(rows, q))
        if path == "/v5/order/create":
            return self._create(q)
        if path in ("/v5/order/realtime", "/v5/order/history"):
            assert q["category"] == "linear" and (q.get("symbol") or q.get("settleCoin") or q.get("baseCoin")), q
            if q.get("orderId") or q.get("orderLinkId"):
                oid = q.get("orderId") or self.by_link.get(q.get("orderLinkId"))
                o = self.orders.get(oid)
                if o is None or (q.get("symbol") and o["symbol"] != q["symbol"]):
                    return ok({"list": [], "nextPageCursor": "", "category": "linear"})
                return ok({"list": [self._view(o)], "nextPageCursor": "", "category": "linear"})
            if path == "/v5/order/history":
                return ok(self._paged([o for o in self.orders.values() if o["symbol"] == q.get("symbol")], q))
            flt = q.get("orderFilter")
            rows = []
            for o in self.orders.values():
                if q.get("symbol") and o["symbol"] != q["symbol"]:
                    continue
                ghost = self.ghosts.get(o["orderId"], 0)
                if o["orderStatus"] == "Untriggered" or ghost > 0:          # conditional (StopOrder)
                    if ghost > 0:
                        self.ghosts[o["orderId"]] = ghost - 1
                        o = {**o, "orderStatus": "Untriggered"}
                    if flt in (None, "StopOrder"):
                        rows.append(dict(o))
                elif o["orderStatus"] in ("New", "PartiallyFilled"):        # active orders (Order)
                    if flt in (None, "Order"):
                        rows.append(self._view(o))
            return ok(self._paged(rows, q))
        if path == "/v5/order/cancel":
            s = q["symbol"]
            oid = q.get("orderId") or self.by_link.get(q.get("orderLinkId"))
            o = self.orders.get(oid)
            if o is None or o["symbol"] != s:
                return 110001, "Order does not exist.", {}
            if o["orderStatus"] in ("Filled",):
                return 110008, "The order has been completed or cancelled.", {}
            if o["orderStatus"] in ("Cancelled", "Deactivated"):
                return 110010, "The order has been cancelled", {}
            self._cancel(o)
            return ok({"orderId": oid, "orderLinkId": o["orderLinkId"]})
        if path == "/v5/order/cancel-all":
            s = q["symbol"]
            assert q.get("orderFilter") in ("Order", "StopOrder"), q
            done = []
            todo = self.live_stops(s) if q["orderFilter"] == "StopOrder" else \
                [o for o in self.orders.values() if o["symbol"] == s and o["orderStatus"] in ("New", "PartiallyFilled")]
            for o in todo:
                self._cancel(o)
                done.append({"orderId": o["orderId"], "orderLinkId": o["orderLinkId"]})
            return ok({"list": done, "success": "1"})
        if path == "/v5/execution/list":
            lo, hi = self._range(q)
            rows = [dict(e) for e in self.execs if e["symbol"] == q["symbol"] and lo <= int(e["execTime"]) <= hi]
            rows.sort(key=lambda e: -int(e["execTime"]))                 # newest first, like Bybit
            return ok(self._paged(rows, q))
        if path == "/v5/position/closed-pnl":
            lo, hi = self._range(q)
            rows = [] if self.closed_hidden else [dict(r) for r in self.closed if r["symbol"] == q["symbol"]
                                                  and lo <= int(r["createdTime"]) <= hi]
            if self.closed_tamper:
                rows = [self.closed_tamper(r) for r in rows]
            return ok(self._paged(rows, q))
        if path == "/v5/account/transaction-log":
            assert q.get("accountType") == "UNIFIED" and int(q.get("limit") or 20) <= 50
            lo, hi = self._range(q)
            rows = [dict(r) for r in self.log if lo <= int(r["transactionTime"]) <= hi
                    and (not q.get("type") or r["type"] == q["type"])
                    and (not q.get("category") or r["category"] == q["category"])
                    and (not q.get("baseCoin") or r["symbol"].startswith(q["baseCoin"]))]
            return ok(self._paged(rows, q))
        raise AssertionError(f"unexpected {m} {path}")

    def _cancel(self, o):
        o.update(orderStatus="Deactivated" if o["orderStatus"] == "Untriggered" else "Cancelled",
                 cancelType="CancelByUser", updatedTime=str(self.clock()))
        if self.cancel_lag:
            self.ghosts[o["orderId"]] = self.cancel_lag

    def _create(self, q):
        assert q["category"] == "linear" and q["orderType"] == "Market" and q["side"] in ("Buy", "Sell"), q
        assert isinstance(q["qty"], str) and q.get("positionIdx") == 0, q
        for k in ("reduceOnly", "closeOnTrigger"):
            assert k not in q or isinstance(q[k], bool), (k, q[k])
        s = q["symbol"]
        link = q.get("orderLinkId") or ""
        assert len(link) <= 36 and all(c.isalnum() or c in "-_" for c in link), link
        if link and link in self.by_link:
            return 110072, "OrderLinkedID is duplicate", {}
        if self.hedge[s]:
            return 10001, "position idx not match position mode", {}
        qty = Decimal(q["qty"])
        step, mn = Decimal(SPECS[s]["step"]), Decimal(SPECS[s]["min"])
        close_all = qty == 0 and q.get("reduceOnly") and q.get("closeOnTrigger")
        if not close_all and (qty < mn or qty % step != 0):
            return 10001, f"Qty invalid: {q['qty']}", {}
        oid = self._new_id()
        base = {"orderId": oid, "orderLinkId": link, "symbol": s, "side": q["side"], "orderType": "Market",
                "price": "0", "qty": q["qty"], "positionIdx": 0, "timeInForce": "IOC",
                "reduceOnly": bool(q.get("reduceOnly")), "closeOnTrigger": bool(q.get("closeOnTrigger")),
                "cumExecQty": "0", "avgPrice": "", "leavesQty": q["qty"], "cancelType": "UNKNOWN",
                "rejectReason": "EC_NoError", "createdTime": str(self.clock()), "updatedTime": str(self.clock()),
                "stopOrderType": "UNKNOWN", "triggerPrice": "0", "triggerDirection": 0, "triggerBy": "UNKNOWN",
                "tpslMode": ""}
        if q.get("triggerPrice") is not None:
            assert isinstance(q["triggerPrice"], str) and q["triggerDirection"] in (1, 2), q
            assert q["triggerBy"] in ("LastPrice", "MarkPrice", "IndexPrice"), q
            trig, last = float(q["triggerPrice"]), self.last[s]
            if q["triggerDirection"] == 1 and trig <= last:
                return 110092, f"expect Rising, but trigger_price[{trig}] <= current[{last}]??laste", {}
            if q["triggerDirection"] == 2 and trig >= last:
                return 110093, f"expect Falling, but trigger_price[{trig}] >= current[{last}]??last", {}
            if len(self.live_stops(s)) >= 10:
                return 110009, "The number of stop orders exceeds the maximum allowable limit", {}
            base.update(orderStatus="Untriggered", stopOrderType="Stop", triggerPrice=q["triggerPrice"],
                        triggerDirection=q["triggerDirection"], triggerBy=q["triggerBy"])
            self.orders[oid] = base
            if link:
                self.by_link[link] = oid
            return 0, "OK", {"orderId": oid, "orderLinkId": link}
        signed = qty if q["side"] == "Buy" else -qty
        amt = self.pos[s]
        if q.get("reduceOnly"):
            if amt == 0 or (amt > 0) == (signed > 0):
                return 110017, "current position is zero, cannot fix reduce-only order qty", {}
            want = min(qty, abs(amt))
        else:
            want = qty
            if self.partial is not None:
                want = (qty * Decimal(str(self.partial)) / step).to_integral_value(rounding="ROUND_FLOOR") * step
                self.partial = None
        px = self.last[s] * (1 + self.slip if signed > 0 else 1 - self.slip)
        self.orders[oid] = base
        if link:
            self.by_link[link] = oid
        filled = self._fill(s, want if signed > 0 else -want, px, oid, link) if want > 0 else Decimal(0)
        base.update(orderStatus="Filled" if filled == qty else "Cancelled", cumExecQty=str(filled),
                    avgPrice=str(px) if filled else "", leavesQty=str(qty - filled))
        if self.market_lag:
            self.lag_left[oid] = self.market_lag
        return 0, "OK", {"orderId": oid, "orderLinkId": link}
