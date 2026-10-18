"""Stateful fake of MEXC's contract API v1 (USDT-M perpetuals) for tests; no network.

Answers in the envelope of MEXC's contract docs: {"success": true, "code": 0, "data": ...} or
{"success": false, "code": <n>, "message": "..."}. Quantities are contracts (``vol``), each worth ``contractSize`` of
the coin (SPECS below: test data only, the client reads every value from /api/v1/contract/detail). Every private
request's signature is checked (hex HMAC-SHA256 of api key + Request-Time + the sorted, URL-encoded GET query, which
must be sent exactly so, or the POST body), and so is Request-Time against the 10 s window (code 513). Bodies are
checked against the documented parameters (side 1-4, openType, leverage for isolated, externalOid <= 32, vol a JSON
number in whole volUnits, triggerType / executeCycle / trend / orderType of plan orders, list bodies of the cancels).

Covers what paperbot/mexc.py uses: ping, contract detail, ticker, account assets (equity, unrealized, bonus), position
mode, leverage per symbol x position type, open positions (one-way; hedge rows when ``mode`` is 1), market orders
(filled at once, read back as uncompleted for ``market_lag`` reads), order look-ups by id and externalOid, cancels,
plan (trigger) orders that trigger on the last price and place a market order whose id they report, expire after
their execution cycle, deals with ``profit`` and ``fee``, funding records and transfer records (paged), the timeline of
which open positions a live stop covers.

Unknowns of the real exchange are switches, so the client is tested against each possibility:
- ``dup_external``: "existing" (a repeated externalOid answers the existing order), "error" (refused, code 2030-like),
  "accept" (a second order is made);
- ``plan_past``: "refuse" (a stop already past the price is refused, code 3004) or "trigger" (it executes at once);
- ``plan_ext``: whether plan order rows echo the externalOid;
- ``profit_net``: whether a deal's ``profit`` is net of its fee;
- ``not_found``: "error" (code 2040) or "null" (success with data null) for an unknown order;
- ``equity_without_margin``: whether the assets' ``equity`` leaves out the isolated position margin.

Failures are injected per request with ``fail(method, path, kind, times, when)`` (``path`` may be a prefix ending in
"/"): "drop_before" / "drop_after" (TimeoutError before / after executing), "cut_after", "503_before" / "503_after",
"429", "403", ("ret", code, msg) (refused, not executed), ("ret_after", code, msg) (executed, then that answer).
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import urllib.parse
from decimal import Decimal

SPECS = {   # test data only
    "BTC_USDT": {"cs": "0.0001", "vu": "1", "min": "1", "pu": "0.1", "lev": 125, "max": "1000000"},
    "ETH_USDT": {"cs": "0.01", "vu": "1", "min": "1", "pu": "0.01", "lev": 100, "max": "500000"},
    "SOL_USDT": {"cs": "0.1", "vu": "1", "min": "1", "pu": "0.001", "lev": 75, "max": "400000"},
    "DOGE_USDT": {"cs": "100", "vu": "1", "min": "1", "pu": "0.00001", "lev": 75, "max": "100000"},
    "LTC_USDT": {"cs": "0.01", "vu": "1", "min": "1", "pu": "0.01", "lev": 75, "max": "100000"},
    "BCH_USDT": {"cs": "0.01", "vu": "1", "min": "1", "pu": "0.01", "lev": 75, "max": "100000"},
    "BTC_USD": {"cs": "100", "vu": "1", "min": "1", "pu": "0.5", "lev": 100, "max": "100000", "settle": "BTC"},
}
NINETY_DAYS = 90 * 86_400_000


def canonical(query: str) -> str:
    items = sorted(urllib.parse.parse_qsl(query, keep_blank_values=True))
    return urllib.parse.urlencode(items, quote_via=urllib.parse.quote)


class FakeMexc:
    def __init__(self, prices=None, wallet=10_000.0, fee=0.0005, host="api.mexc.com", api_key="mk", api_secret="ms"):
        self.host, self.api_key, self.api_secret = host, api_key, api_secret
        self.hosts = {"api.mexc.com", "contract.mexc.com"}
        self.clock = lambda: 1_800_000_000_000
        self.skew = 0
        self.last = dict(prices or {"BTC_USDT": 100.0, "ETH_USDT": 50.0, "SOL_USDT": 10.0, "DOGE_USDT": 0.1,
                                    "LTC_USDT": 60.0, "BCH_USDT": 300.0})
        self.pos = {s: Decimal(0) for s in SPECS}          # signed contracts
        self.entry = {s: 0.0 for s in SPECS}
        self.pos_open = {s: 1 for s in SPECS}               # openType of the position
        self.pos_lev = {s: 0 for s in SPECS}
        self.pos_id = {s: 0 for s in SPECS}
        self.levs = {(s, pt): [1, 10] for s in SPECS for pt in (1, 2)}   # (openType, leverage)
        self.mode = 2
        self.wallet, self.fee, self.bonus = wallet, fee, 0.0
        self.other = {}                                     # currency -> equity besides USDT
        self.orders, self.by_ext = {}, {}
        self.plans = {}
        self.deals, self.funding, self.transfers = [], [], []
        self.calls, self.failures, self.timeline = [], [], []
        self.n = 1000
        self.partial = None
        self.slip = 0.0
        self.market_lag = 0
        self.lag_left = {}
        self.dup_external = "existing"
        self.plan_past = "refuse"
        self.plan_ext = False
        self.profit_net = False
        self.not_found = "error"
        self.profit_tamper = None                           # f(deal) -> deal, applied to order_deals answers
        self.null_positions = False                         # open_positions answers data: null
        self.page = 100
        self.ping_str = True                                # ping answers the time as a string
        self.equity_without_margin = False                  # "equity" leaving out the isolated position margin

    # ------------------------------------------------------------ test controls
    def fail(self, method, path, kind, times=1, when=None):
        self.failures.append([method, path, kind, times, when])

    def set_price(self, symbol, price):
        self.last[symbol] = price
        self._trigger(symbol)
        self._snap("PRICE", symbol)

    def amt(self, symbol):
        """The position in coins (signed)."""
        return self.pos[symbol] * Decimal(SPECS[symbol]["cs"])

    def live_plans(self, symbol=None):
        return [p for p in self.plans.values() if p["state"] == 1 and (symbol is None or p["symbol"] == symbol)]

    def covered(self, symbol):
        amt = self.pos[symbol]
        if amt == 0:
            return True
        for p in self.live_plans(symbol):
            protective = (amt > 0 and p["side"] == 4 and p["triggerType"] == 2) or \
                (amt < 0 and p["side"] == 2 and p["triggerType"] == 1)
            if protective and Decimal(str(p["vol"])) >= abs(amt):
                return True
        return False

    def unprotected_moments(self, symbol):
        return [t for t in self.timeline if symbol in t[3] and t[3][symbol][0] != 0 and not t[3][symbol][1]]

    def add_funding(self, symbol, amount, time=None):
        t = self.clock() if time is None else time
        self.wallet += amount
        self.n += 1
        self.funding.append({"id": self.n, "symbol": symbol, "positionId": self.pos_id[symbol],
                             "positionType": 1 if self.pos[symbol] > 0 else 2,
                             "positionValue": float(abs(self.amt(symbol))) * self.last[symbol], "funding": amount,
                             "rate": -0.0001, "settleTime": t})

    def add_transfer(self, amount, time=None, state="SUCCESS", currency="USDT"):
        t = self.clock() if time is None else time
        if state == "SUCCESS" and currency == "USDT":
            self.wallet += amount
        self.n += 1
        self.transfers.append({"id": self.n, "txid": f"tx{self.n}", "currency": currency, "amount": abs(amount),
                               "type": "IN" if amount > 0 else "OUT", "state": state, "createTime": t,
                               "updateTime": t})

    def add_resting(self, symbol, side, vol, price, ext=""):
        oid = self._id()
        self.orders[oid] = self._order_row(oid, symbol, vol, side, 1, 1, 10, ext, price=price)
        self.orders[oid]["state"] = 2
        if ext:
            self.by_ext[(symbol, ext)] = oid
        return oid

    def _snap(self, method, path):
        self.timeline.append((len(self.calls), method, path,
                              {s: (self.pos[s], self.covered(s)) for s in self.pos if self.pos[s] != 0}))

    # ------------------------------------------------------------ transport
    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        assert u.scheme == "https" and u.hostname in self.hosts, url
        path = u.path
        if method in ("GET", "DELETE"):
            assert body is None, "GET with a body"
            payload = u.query
            assert payload == canonical(payload), f"query not sorted / encoded as signed: {payload}"
            q = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
        else:
            assert method == "POST" and not u.query, (method, url)
            assert headers.get("Content-Type") == "application/json"
            payload = body.decode()
            q = json.loads(payload)
        if path.startswith("/api/v1/private/"):
            assert headers["ApiKey"] == self.api_key and headers["Content-Type"] == "application/json"
            ts = headers["Request-Time"]
            want = hmac.new(self.api_secret.encode(), (self.api_key + ts + payload).encode(),
                            hashlib.sha256).hexdigest()
            if headers["Signature"] != want:
                return self._error(602, "Signature verification failed!")
            server = self.clock() + self.skew
            if abs(server - int(ts)) > 10_000:
                return self._error(513, "Invalid request(for open api serves time more or less than 10s)")
        else:
            assert path.startswith("/api/v1/contract/"), path
            assert "Signature" not in headers
        f = self._take(method, path, q)
        kind = f[2] if f else None
        if kind == "drop_before":
            raise TimeoutError("timed out")
        if kind == "503_before":
            return 503, b"<html>503 Service Unavailable</html>", {}
        if kind == "429":
            return 429, b"", {"Retry-After": "2"}
        if kind == "403":
            return 403, b"<html>Access Denied</html>", {}
        if kind == "404":
            return 404, b"<html>404 Not Found</html>", {}
        if isinstance(kind, tuple) and kind[0] == "ret":
            return self._error(kind[1], kind[2])
        self.calls.append((method, path, q))
        self._expire()
        res = self.route(method, path, q)
        self._snap(method, path)
        if kind == "drop_after":
            raise TimeoutError("timed out after sending")
        if kind == "cut_after":
            raise http.client.IncompleteRead(b"")
        if kind == "503_after":
            return 503, b"<html>503</html>", {}
        if isinstance(kind, tuple) and kind[0] == "ret_after":
            return self._error(kind[1], kind[2])
        return res

    def _ok(self, data):
        return 200, json.dumps({"success": True, "code": 0, "data": data}).encode(), {}

    def _error(self, code, msg):
        return 200, json.dumps({"success": False, "code": code, "message": msg}).encode(), {}

    def _take(self, method, path, q):
        for f in self.failures:
            hit = f[1] == path or (f[1].endswith("/") and path.startswith(f[1]))
            if f[0] == method and hit and f[3] > 0 and (f[4] is None or f[4](q)):
                f[3] -= 1
                return f
        return None

    # ------------------------------------------------------------ exchange logic
    def _id(self):
        self.n += 1
        return str(700_000_000_000_000_000 + self.n)

    def _order_row(self, oid, symbol, vol, side, typ, open_type, lev, ext, price=0):
        return {"orderId": oid, "symbol": symbol, "positionId": self.pos_id[symbol], "price": price, "vol": vol,
                "leverage": lev, "side": side, "category": 1, "orderType": typ, "dealAvgPrice": 0, "dealVol": 0,
                "orderMargin": 0, "takerFee": 0, "makerFee": 0, "profit": 0, "feeCurrency": "USDT",
                "openType": open_type, "state": 1, "externalOid": ext, "errorCode": 0, "usedMargin": 0,
                "createTime": self.clock(), "updateTime": self.clock()}

    def _fill(self, symbol, signed, price, oid):
        """signed: Decimal contracts (+ buy, - sell). Returns the contracts filled."""
        cs = Decimal(SPECS[symbol]["cs"])
        amt = self.pos[symbol]
        realized = 0.0
        if amt != 0 and (amt > 0) != (signed > 0):
            closing = min(abs(signed), abs(amt))
            realized = float(closing * cs) * (price - self.entry[symbol]) * (1 if amt > 0 else -1)
            rest = abs(signed) - closing
            if rest > 0:
                self.entry[symbol] = price
        else:
            tot = abs(amt) + abs(signed)
            self.entry[symbol] = (float(abs(amt)) * self.entry[symbol] + float(abs(signed)) * price) / float(tot)
            if amt == 0:
                self.n += 1
                self.pos_id[symbol] = self.n
        fee = float(abs(signed) * cs) * price * self.fee
        self.wallet += realized - fee
        self.pos[symbol] = amt + signed
        if self.pos[symbol] == 0:
            self.entry[symbol] = 0.0
        o = self.orders[oid]
        self.n += 1
        self.deals.append({"id": self.n, "symbol": symbol, "side": o["side"], "vol": float(abs(signed)),
                           "price": price, "fee": fee, "feeCurrency": "USDT",
                           "profit": realized - (fee if self.profit_net else 0.0), "isTaker": True, "category": 1,
                           "orderId": oid, "timestamp": self.clock()})
        return abs(signed)

    def _trigger(self, symbol):
        p = self.last[symbol]
        for pl in list(self.live_plans(symbol)):
            trig = float(pl["triggerPrice"])
            if (pl["triggerType"] == 1 and p >= trig) or (pl["triggerType"] == 2 and p <= trig):
                self._execute_plan(pl)

    def _execute_plan(self, pl):
        s = pl["symbol"]
        amt = self.pos[s]
        vol = Decimal(str(pl["vol"]))
        side = pl["side"]
        if side in (2, 4):
            if amt == 0 or (side == 4) != (amt > 0):
                pl.update(state=5, errorCode=3, updateTime=self.clock())          # the position does not exist
                return
            vol = min(vol, abs(amt))
        oid = self._id()
        self.orders[oid] = self._order_row(oid, s, float(vol), side, 5, pl["openType"], pl["leverage"], "")
        signed = vol if side in (1, 2) else -vol
        self._fill(s, signed, self.last[s], oid)
        self.orders[oid].update(state=3, dealVol=float(vol), dealAvgPrice=self.last[s])
        pl.update(state=3, orderId=oid, updateTime=self.clock())

    def _expire(self):
        now = self.clock()
        for pl in self.live_plans():
            if now >= pl["createTime"] + pl["executeCycle"] * 3_600_000:
                pl.update(state=4, updateTime=now)

    def upnl(self, symbol=None):
        return sum(float(self.amt(s)) * (self.last[s] - self.entry[s]) for s in self.pos
                   if self.pos[s] and (symbol is None or s == symbol))

    def _paged(self, rows, q, wrap=False):
        assert int(q.get("page_size", 20)) <= 100 and int(q.get("page_num", 1)) >= 1, q
        size = min(int(q.get("page_size", 20)), self.page)
        num = int(q.get("page_num", 1))
        page = rows[(num - 1) * size:num * size]
        if not wrap:
            return page
        total = (len(rows) + size - 1) // size
        return {"pageSize": size, "totalCount": len(rows), "totalPage": total, "currentPage": num, "resultList": page}

    def _range(self, q):
        lo, hi = q.get("start_time"), q.get("end_time")
        if lo is None:
            return self.clock() - 7 * 86_400_000, self.clock()
        lo, hi = int(lo), int(hi)
        assert 0 <= hi - lo <= NINETY_DAYS, "start and end at most 90 days apart"
        return lo, hi

    def _detail(self, s, v):
        return {"symbol": s, "displayName": f"{s}永续", "displayNameEn": f"{s} SWAP", "positionOpenType": 3,
                "baseCoin": s.split("_")[0], "quoteCoin": s.split("_")[1], "settleCoin": v.get("settle", "USDT"),
                "contractSize": float(v["cs"]), "minLeverage": 1, "maxLeverage": v["lev"], "priceScale": 2,
                "volScale": 0, "amountScale": 4, "priceUnit": float(v["pu"]), "volUnit": float(v["vu"]),
                "minVol": float(v["min"]), "maxVol": float(v["max"]), "takerFeeRate": self.fee,
                "makerFeeRate": 0.0001, "state": 0, "apiAllowed": True, "riskLimitType": "BY_VOLUME"}

    def _position_rows(self, symbol=None):
        rows = []
        for s in SPECS:
            if (symbol and s != symbol) or self.pos[s] == 0:
                continue
            amt = self.pos[s]
            rows.append({"positionId": self.pos_id[s], "symbol": s, "positionType": 1 if amt > 0 else 2,
                         "openType": self.pos_open[s], "state": 1, "holdVol": float(abs(amt)), "frozenVol": 0,
                         "closeVol": 0, "holdAvgPrice": self.entry[s], "openAvgPrice": self.entry[s],
                         "closeAvgPrice": 0, "liquidatePrice": 0, "oim": 0, "im": 0, "holdFee": 0, "realised": 0,
                         "leverage": self.pos_lev[s] or self.levs[(s, 1 if amt > 0 else 2)][1],
                         "createTime": self.clock(), "updateTime": self.clock(), "autoAddIm": False})
        return rows

    def busy(self):
        return any(self.pos.values()) or self.live_plans() or \
            any(o["state"] in (1, 2) for o in self.orders.values())

    def route(self, m, path, q):
        P = "/api/v1/private"
        if path == "/api/v1/contract/ping":
            t = self.clock() + self.skew
            return self._ok(str(t) if self.ping_str else t)
        if path == "/api/v1/contract/detail":
            return self._ok([self._detail(s, v) for s, v in SPECS.items() if q.get("symbol") in (None, s)])
        if path == "/api/v1/contract/ticker":
            s = q["symbol"]
            return self._ok({"symbol": s, "lastPrice": self.last[s], "fairPrice": self.last[s],
                             "indexPrice": self.last[s], "bid1": self.last[s], "ask1": self.last[s],
                             "timestamp": self.clock()})
        if path == P + "/account/assets":
            up = self.upnl()
            margin = sum(float(abs(self.amt(s))) * self.entry[s] / max(1, self.pos_lev[s] or 10)
                         for s in self.pos if self.pos[s])
            usdt = {"currency": "USDT", "positionMargin": margin, "frozenBalance": 0,
                    "availableBalance": self.wallet - margin, "cashBalance": self.wallet - margin,
                    "equity": self.wallet + up + self.bonus - (margin if self.equity_without_margin else 0),
                    "unrealized": up, "bonus": self.bonus}
            rows = [{"currency": c, "positionMargin": 0, "frozenBalance": 0, "availableBalance": v, "cashBalance": v,
                     "equity": v, "unrealized": 0, "bonus": 0} for c, v in self.other.items()]
            return self._ok(rows + [usdt])
        if path == P + "/position/position_mode":
            return self._ok(self.mode)
        if path == P + "/position/change_position_mode":
            assert set(q) == {"positionMode"} and q["positionMode"] in (1, 2), q
            if self.busy():
                return self._error(2019, "There is an active open position")
            self.mode = q["positionMode"]
            return 200, json.dumps({"success": True, "code": 0}).encode(), {}
        if path == P + "/position/leverage":
            s = q["symbol"]
            return self._ok([{"level": 1, "maxVol": 463300, "mmr": 0.004, "imr": 0.005, "positionType": pt,
                              "openType": self.levs[(s, pt)][0], "leverage": self.levs[(s, pt)][1],
                              "limitBySys": False, "currentMmr": 0.004} for pt in (1, 2)])
        if path == P + "/position/change_leverage":
            assert isinstance(q["leverage"], int), q
            if "positionId" in q:
                return self._error(600, "Param error!")              # the client never changes an open position
            assert q["openType"] in (1, 2) and q["positionType"] in (1, 2), q
            s = q["symbol"]
            if q["leverage"] > SPECS[s]["lev"] or q["leverage"] < 1:
                return self._error(2006, "Leverage ratio error")
            if self.pos[s] != 0:
                return self._error(2019, "There is an active open position")
            self.levs[(s, q["positionType"])] = [q["openType"], q["leverage"]]
            return 200, json.dumps({"success": True, "code": 0}).encode(), {}
        if path == P + "/position/open_positions":
            if self.null_positions:
                return self._ok(None)
            return self._ok(self._position_rows(q.get("symbol")))
        if path in (P + "/order/create", P + "/order/submit"):
            return self._create(q)
        if path.startswith(P + "/order/get/"):
            return self._order_answer(self.orders.get(path.rsplit("/", 1)[1]))
        if path.startswith(P + "/order/external/"):
            sym, ext = path[len(P + "/order/external/"):].split("/")
            return self._order_answer(self.orders.get(self.by_ext.get((sym, urllib.parse.unquote(ext)))))
        if path.startswith(P + "/order/list/open_orders"):
            sym = path[len(P + "/order/list/open_orders"):].lstrip("/") or None
            rows = [self._view(o) for o in self.orders.values() if o["state"] in (1, 2)
                    and (sym is None or o["symbol"] == sym)]
            return self._ok(self._paged(rows, q))
        if path == P + "/order/cancel":
            assert isinstance(q, list), q
            out = []
            for oid in q:
                o = self.orders.get(str(oid))
                if o is None:
                    out.append({"orderId": oid, "errorCode": 2040, "errorMsg": "order not exist"})
                elif o["state"] not in (1, 2):
                    out.append({"orderId": oid, "errorCode": 2041, "errorMsg": "order state cannot be cancelled"})
                else:
                    o.update(state=4, updateTime=self.clock())
                    out.append({"orderId": oid, "errorCode": 0, "errorMsg": "success"})
            return self._ok(out)
        if path == P + "/order/cancel_all":
            for o in self.orders.values():
                if o["state"] in (1, 2) and o["symbol"] == q.get("symbol", o["symbol"]):
                    o.update(state=4, updateTime=self.clock())
            return 200, json.dumps({"success": True, "code": 0}).encode(), {}
        if path == P + "/planorder/place":
            return self._plan_place(q)
        if path == P + "/planorder/list/orders":
            lo, hi = self._range(q)
            states = {int(x) for x in q["states"].split(",")} if q.get("states") else None
            rows = [self._plan_view(p) for p in sorted(self.plans.values(), key=lambda p: -p["createTime"])
                    if (not q.get("symbol") or p["symbol"] == q["symbol"]) and lo <= p["createTime"] <= hi
                    and (states is None or p["state"] in states)]
            return self._ok(self._paged(rows, q))
        if path == P + "/planorder/cancel":
            assert isinstance(q, list) and all(set(x) == {"symbol", "orderId"} and isinstance(x["orderId"], str)
                                               for x in q), q
            for x in q:
                p = self.plans.get(x["orderId"])
                if p is None or p["symbol"] != x["symbol"]:
                    return self._error(2040, "order not exist")
                if p["state"] != 1:
                    return self._error(2041, "order state cannot be cancelled")
                p.update(state=2, updateTime=self.clock())
            return 200, json.dumps({"success": True, "code": 0}).encode(), {}
        if path == P + "/planorder/cancel_all":
            for p in self.live_plans(q.get("symbol")):
                p.update(state=2, updateTime=self.clock())
            return 200, json.dumps({"success": True, "code": 0}).encode(), {}
        if path == P + "/order/list/order_deals":
            lo, hi = self._range(q)
            rows = [dict(d) for d in sorted(self.deals, key=lambda d: -d["timestamp"])
                    if d["symbol"] == q["symbol"] and lo <= d["timestamp"] <= hi]
            if self.profit_tamper:
                rows = [self.profit_tamper(d) for d in rows]
            return self._ok(self._paged(rows, q))
        if path == P + "/position/funding_records":
            rows = [dict(r) for r in sorted(self.funding, key=lambda r: -r["settleTime"])
                    if not q.get("symbol") or r["symbol"] == q["symbol"]]
            return self._ok(self._paged(rows, q, wrap=True))
        if path == P + "/account/transfer_record":
            rows = [dict(r) for r in sorted(self.transfers, key=lambda r: -r["createTime"])]
            return self._ok(self._paged(rows, q, wrap=True))
        raise AssertionError(f"unexpected {m} {path}")

    def _view(self, o):
        v = dict(o)
        left = self.lag_left.get(o["orderId"], 0)
        if left > 0:
            self.lag_left[o["orderId"]] = left - 1
            v.update(state=2, dealVol=0, dealAvgPrice=0)
        return v

    def _order_answer(self, o):
        if o is None:
            return self._ok(None) if self.not_found == "null" else self._error(2040, "order not exist")
        return self._ok(self._view(o))

    def _plan_view(self, p):
        v = {k: p[k] for k in ("id", "symbol", "leverage", "side", "triggerPrice", "price", "vol", "openType",
                               "triggerType", "state", "executeCycle", "trend", "errorCode", "orderId", "orderType",
                               "createTime", "updateTime")}
        if self.plan_ext:
            v["externalOid"] = p["externalOid"]
        return v

    def _check_vol(self, s, vol):
        assert isinstance(vol, (int, float)) and not isinstance(vol, bool), vol
        d = Decimal(str(vol))
        return d >= Decimal(SPECS[s]["min"]) and d % Decimal(SPECS[s]["vu"]) == 0 and d <= Decimal(SPECS[s]["max"])

    def _create(self, q):
        assert set(q) <= {"symbol", "price", "vol", "leverage", "side", "type", "openType", "positionId",
                          "externalOid", "stopLossPrice", "takeProfitPrice", "positionMode", "reduceOnly"}, q
        s = q["symbol"]
        assert q["side"] in (1, 2, 3, 4) and q["type"] in (5, 6) and q["openType"] in (1, 2), q
        assert "price" not in q, "a market order carries no price"
        ext = q.get("externalOid") or ""
        assert len(ext) <= 32 and all(c.isalnum() or c in "-_" for c in ext), ext
        if q["openType"] == 1 and q["side"] in (1, 3):
            assert isinstance(q.get("leverage"), int), "leverage is required for an isolated opening order"
            if [1, q["leverage"]] != self.levs[(s, 1 if q["side"] == 1 else 2)]:
                return self._error(2021, "The single leverage is not consistent with the existing position leverage")
        if ext and (s, ext) in self.by_ext and self.dup_external != "accept":
            if self.dup_external == "existing":
                return self._ok({"orderId": self.by_ext[(s, ext)], "ts": self.clock()})
            return self._error(2030, "External order ID is duplicate")
        if self.mode != 2:
            return self._error(2022, "Wrong position type")
        if not self._check_vol(s, q["vol"]):
            return self._error(2011, "Order quantity error, please try to modify.")
        vol = Decimal(str(q["vol"]))
        amt = self.pos[s]
        side = q["side"]
        if side in (2, 4):
            if amt == 0 or (side == 4) != (amt > 0):
                return self._error(2009, "Position is not exists or closed.")
            if q["openType"] != self.pos_open[s]:
                return self._error(2002, "Wrong opening type")
            want = min(vol, abs(amt))
        else:
            want = vol
            if self.partial is not None:
                want = (vol * Decimal(str(self.partial))).to_integral_value(rounding="ROUND_FLOOR")
                self.partial = None
            if amt == 0:
                self.pos_open[s], self.pos_lev[s] = q["openType"], q.get("leverage") or 10
        oid = self._id()
        self.orders[oid] = self._order_row(oid, s, q["vol"], side, q["type"], q["openType"], q.get("leverage"), ext)
        if ext:
            self.by_ext[(s, ext)] = oid
        buy = side in (1, 2)
        px = self.last[s] * (1 + self.slip if buy else 1 - self.slip)
        filled = self._fill(s, want if buy else -want, px, oid) if want > 0 else Decimal(0)
        self.orders[oid].update(state=3 if filled == vol else 4, dealVol=float(filled),
                                dealAvgPrice=px if filled else 0, updateTime=self.clock())
        if self.market_lag:
            self.lag_left[oid] = self.market_lag
        return self._ok({"orderId": oid, "ts": self.clock()})

    def _plan_place(self, q):
        assert set(q) <= {"symbol", "price", "vol", "leverage", "side", "openType", "triggerPrice", "triggerType",
                          "executeCycle", "orderType", "trend", "externalOid", "type", "positionMode"}, q
        s = q["symbol"]
        assert q["side"] in (1, 2, 3, 4) and q["openType"] in (1, 2) and q["triggerType"] in (1, 2), q
        assert q["executeCycle"] in (1, 2) and q["orderType"] == 5 and q["trend"] in (1, 2, 3), q
        assert isinstance(q["triggerPrice"], str), q
        ext = q.get("externalOid") or ""
        assert len(ext) <= 32, ext
        if q["openType"] == 1:
            assert isinstance(q.get("leverage"), int), "leverage is required for isolated"
        if not self._check_vol(s, q["vol"]):
            return self._error(2011, "Order quantity error, please try to modify.")
        trig, last = float(q["triggerPrice"]), self.last[s]
        past = (q["triggerType"] == 1 and last >= trig) or (q["triggerType"] == 2 and last <= trig)
        if past and self.plan_past == "refuse":
            return self._error(3004, "Trigger price error")
        if len(self.live_plans(s)) >= 10:
            return self._error(2036, "The orders more than the limit, please contact customer service")
        pid = self._id()
        self.plans[pid] = {"id": pid, "symbol": s, "leverage": q.get("leverage"), "side": q["side"],
                           "triggerPrice": float(q["triggerPrice"]), "price": 0, "vol": q["vol"],
                           "openType": q["openType"], "triggerType": q["triggerType"], "state": 1,
                           "executeCycle": {1: 24, 2: 168}[q["executeCycle"]], "trend": q["trend"], "errorCode": 0,
                           "orderId": 0, "orderType": q["orderType"], "createTime": self.clock(),
                           "updateTime": self.clock(), "externalOid": ext}
        if past:
            self._execute_plan(self.plans[pid])
        return self._ok(int(pid))
