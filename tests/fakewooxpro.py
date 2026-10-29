"""Stateful fake of WOO X Pro's futures API (cloud-api.wooxpro.com, the BitMart futures family) for tests; no network.

Answers in the envelope of WOO X Pro's docs: {"code": 1000, "message": "Ok", "data": ..., "trace": ...}, errors as
HTTP 400 with {"code": <n>, "message": "..."}. Quantities are contracts (``size``, an integer), each worth
``contract_size`` of the coin (SPECS below: test data only, the client reads every value from /contract/public/details).
Every private request's signature is checked: hex HMAC-SHA256(secret, X-API-TIMESTAMP + '#' + memo + '#' + the query
string as sent (GET) or the body (POST)), and X-API-TIMESTAMP against the one-minute window (code 30007). Bodies are
checked against the documented parameters (side 1-4, type market, size a whole number, client_order_id letters and
digits up to 32 and never reused (40050), TP/SL type stop_loss with price_type 1, plan_category 1, category market).

Covers what paperbot/wooxpro.py uses: system time, funding rate, contract details, K-line and mark-price K-line (1m,
built from every ``set_price``), assets, position mode, position-v2 leverage rows, submit-leverage, positions (one-way;
hedge rows when ``mode`` is hedge_mode), market orders (filled at once), order detail, order history, TP/SL stop_loss
orders that trigger on the last price and place a market order (client_order_id "PLAN_<stop id>"), current plan
orders, plan cancels, trades with ``realised_profit`` and ``paid_fees``, funding and transfer flows.

Unknowns of the real exchange are switches:
- ``time_source``: "system" (/system/time answers), "funding" (only the funding rate's timestamp), "none";
- ``two_stops``: whether a second stop_loss order can rest next to the first (else refused, code 40028);
- ``plan_past``: "refuse" (a stop already past the price is refused, code 40031), "invalid" (refused with 40012 "The stop
  loss price is invalid, needs to be lesser / greater than the order price", what the live exchange answered on 10-21
  and 10-28) or "trigger" (it executes at once);
- ``history_plans``: whether order-history shows the stop's own row with its executive_order_id;
- ``placed_cid``: whether the market order a stop placed carries client_order_id "PLAN_<stop id>";
- ``flat_cancels``: whether resting stops are cancelled when their position closes.
- ``max_lev``: each contract's max_leverage (SPECS by default); ``brackets``: its leverage risk limit, [(max leverage,
  notional floor, notional cap[, maintenance margin ratio, 0.005 if left out])] from the smallest (default: max_lev up
  to 200,000 USDT at 0.5 %, half of it up to 1,000,000 at 1 %);
  an opening order whose position would pass the cap of the leverage it is set to is refused with 40029 (the docs'
  "The order's leverage is too large."; what the real exchange answers there only a live order shows).

Failures are injected per request with ``fail(method, path, kind, times)``: "drop_before" / "drop_after" (TimeoutError
before / after executing), "503_before", "503_html" (the gateway's HTML page), "429", "403", ("ret", code, msg)
(refused, not executed).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
from decimal import Decimal

SPECS = {   # test data only
    "BTCUSDT": {"cs": "0.001", "vp": "1", "min": "1", "pp": "0.1", "lev": 100},
    "ETHUSDT": {"cs": "0.01", "vp": "1", "min": "1", "pp": "0.01", "lev": 100},
    "SOLUSDT": {"cs": "0.1", "vp": "1", "min": "1", "pp": "0.001", "lev": 50},
    "DOGEUSDT": {"cs": "10", "vp": "1", "min": "1", "pp": "0.00001", "lev": 50},
    "LTCUSDT": {"cs": "0.1", "vp": "1", "min": "1", "pp": "0.01", "lev": 50},
    "BCHUSDT": {"cs": "0.01", "vp": "1", "min": "1", "pp": "0.01", "lev": 50},
}
OPEN_SIDES, CLOSE_SIDES = (1, 4), (2, 3)


class FakeWooX:
    def __init__(self, prices=None, wallet=10_000.0, fee=0.0006, api_key="wk", api_secret="ws", memo="wm"):
        self.prices = {s: 100.0 for s in SPECS}
        self.prices.update(prices or {})
        self.wallet, self.fee = wallet, fee
        self.key, self.secret, self.memo = api_key, api_secret, memo
        self.clock = None
        self.mode = "hedge_mode"
        self.levs = {s: ["cross", 20] for s in SPECS}
        self.pos = {s: 0 for s in SPECS}          # signed contracts
        self.entry = {s: 0.0 for s in SPECS}
        self.orders: dict = {}                     # order id -> row
        self.plans: dict = {}                      # resting stop id -> row
        self.done_plans: dict = {}                 # finished stop id -> row (with executive_order_id when triggered)
        self.trades: list = []
        self.flows: list = []
        self.bars: dict = {}                       # (symbol, minute ms) -> [o, h, l, c]
        self.calls: list = []
        self.fails: list = []
        self.last_kline_empty = False     # True: GET /contract/public/kline answers [] (as on the owners' server)
        self.cids: set = set()
        self.next_id = 220_000_000_000
        self.time_source = "system"
        self.two_stops = True
        self.plan_past = "refuse"
        self.history_plans = True
        self.placed_cid = True
        self.flat_cancels = True
        self.coverage: list = []                   # (call index, symbol, position contracts, covered by a stop)
        self.max_lev = {s: SPECS[s]["lev"] for s in SPECS}
        self.brackets: dict = {}                   # symbol -> [(max leverage, notional floor, notional cap[, mmr])]

    # ------------------------------------------------------------ helpers for tests
    def now(self):
        return self.clock() if self.clock else 1_800_000_000_000

    def fail(self, method, path, kind, times=1):
        self.fails.append([method, path, kind, times])

    def set_price(self, symbol, price):
        self.prices[symbol] = price
        m = self.now() // 60_000 * 60_000
        b = self.bars.get((symbol, m))
        self.bars[(symbol, m)] = [b[0], max(b[1], price), min(b[2], price), price] if b else [price] * 4
        self._trigger(symbol)

    def amt(self, symbol):
        return float(Decimal(self.pos[symbol]) * Decimal(SPECS[symbol]["cs"]))

    def live_stops(self, symbol=None):
        return [p for p in self.plans.values() if symbol is None or p["symbol"] == symbol]

    def add_funding(self, symbol, amount, time=None):
        self.wallet += amount
        self.flows.append({"symbol": symbol, "type": "Funding Fee", "flow": 3, "amount": f"{amount:.8f}",
                           "asset": "USDT", "account": "futures", "time": str(time or self.now()),
                           "tran_id": str(self._id())})

    def add_transfer(self, amount, time=None):
        self.wallet += amount
        self.flows.append({"symbol": "", "type": "Transfer", "flow": 1, "amount": f"{amount:.8f}", "asset": "USDT",
                           "account": "futures", "time": str(time or self.now()), "tran_id": str(self._id())})

    def unprotected(self):
        """Moments a position had no stop covering it, after its first stop was placed (an entry is read back and its
        position read before the first stop goes out)."""
        first = {}
        for i, c in enumerate(self.calls, start=1):
            if c[2].endswith("submit-tp-sl-order"):
                first.setdefault(json.loads(c[4])["symbol"], i)
        return [c for c in self.coverage if c[2] and not c[3] and c[1] in first and c[0] > first[c[1]]]

    # ------------------------------------------------------------ transport
    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        assert u.scheme == "https" and u.hostname == "cloud-api.wooxpro.com", url
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
                if kind == "503_html":                     # the gateway's page (live 10-29 12:07)
                    return 503, (b"<html>\r\n<head><title>503 Service Temporarily Unavailable</title></head>\r\n<body>"
                                 b"<center><h1>503 Service Temporarily Unavailable</h1></center><hr><center>openresty"
                                 b"</center></body></html>"), {}
                if kind == "429":
                    return 429, json.dumps({"code": 30013, "message": "Request too many requests"}).encode(), {}
                if kind == "403":
                    return 403, b"<html>forbidden</html>", {}
                if isinstance(kind, tuple) and kind[0] == "ret":
                    return self._error(kind[1], kind[2])
                if kind == "drop_after":
                    self._route(method, path, query, body)
                    raise TimeoutError("dropped after")
        private = path.startswith("/contract/private") or path.startswith("/account")
        if private:
            ts = headers.get("X-API-TIMESTAMP", "")
            if headers.get("X-API-KEY") != self.key:
                return 401, json.dumps({"code": 30002, "message": "Header X-API-KEY not found"}).encode(), {}
            if not ts.isdigit() or abs(int(ts) - self.now()) > 60_000:
                return 401, json.dumps({"code": 30007, "message": "Header X-API-TIMESTAMP range"}).encode(), {}
            payload = query if method == "GET" else (body or b"").decode()
            want = hmac.new(self.secret.encode(), f"{ts}#{self.memo}#{payload}".encode(), hashlib.sha256).hexdigest()
            if headers.get("X-API-SIGN") != want:
                return 401, json.dumps({"code": 30005, "message": "Header X-API-SIGN is wrong"}).encode(), {}
            if method == "POST" and headers.get("Content-Type") != "application/json":
                return 400, json.dumps({"code": 30018, "message": "Request Body requires JSON format"}).encode(), {}
        out = self._route(method, path, query, body)
        self._note_coverage()
        return out

    def _note_coverage(self):
        for s, n in self.pos.items():
            if n:
                side = 3 if n > 0 else 2
                cov = sum(int(p["size"]) for p in self.plans.values() if p["symbol"] == s and p["side"] == side)
                self.coverage.append((len(self.calls), s, n, cov >= abs(n)))

    def _ok(self, data):
        return 200, json.dumps({"code": 1000, "message": "Ok", "data": data, "trace": "t"}).encode(), {}

    def _error(self, code, msg):
        return 400, json.dumps({"code": code, "message": msg, "trace": "t"}).encode(), {}

    def _id(self):
        self.next_id += 1
        return self.next_id

    # ------------------------------------------------------------ state
    def _upnl(self, s):
        n = self.pos[s]
        return float(Decimal(n) * Decimal(SPECS[s]["cs"])) * (self.prices[s] - self.entry[s]) if n else 0.0

    def _margin(self, s):
        n = self.pos[s]
        return abs(float(Decimal(n) * Decimal(SPECS[s]["cs"]))) * self.entry[s] / self.levs[s][1] if n else 0.0

    def busy(self):
        return any(self.pos.values()) or bool(self.plans)

    def _fill(self, s, side, size, price, oid, cid):
        """A market fill of ``size`` contracts; side 1 / 4 opens, 2 / 3 closes (never past the position)."""
        cs = Decimal(SPECS[s]["cs"])
        sgn = 1 if side in (1, 2) else -1
        n = self.pos[s]
        realized = 0.0
        if side in CLOSE_SIDES:
            assert (side == 3 and n > 0) or (side == 2 and n < 0)
            size = min(size, abs(n))
            realized = float(Decimal(size) * cs) * (price - self.entry[s]) * (1 if n > 0 else -1)
            self.pos[s] = n + sgn * size
            if self.pos[s] == 0:
                self.entry[s] = 0.0
        else:
            q0, q1 = abs(n), size
            self.entry[s] = (q0 * self.entry[s] + q1 * price) / (q0 + q1)
            self.pos[s] = n + sgn * size
        fee = float(Decimal(size) * cs) * price * self.fee
        self.wallet += realized - fee
        t = self.now()
        self.trades.append({"order_id": str(oid), "trade_id": str(self._id()), "symbol": s, "side": side,
                            "price": repr(price), "vol": str(size), "exec_type": "Taker", "profit": realized > 0,
                            "realised_profit": f"{realized:.8f}", "paid_fees": f"{fee:.8f}", "account": "futures",
                            "create_time": t})
        self.orders[str(oid)] = {"order_id": str(oid), "client_order_id": cid, "price": "0", "size": str(size),
                                 "symbol": s, "state": 4, "side": side, "type": "market",
                                 "position_mode": self.mode, "account": "futures", "leverage": str(self.levs[s][1]),
                                 "open_type": self.levs[s][0], "deal_avg_price": repr(price), "deal_size": str(size),
                                 "create_time": t, "update_time": t}
        if self.pos[s] == 0 and self.flat_cancels:
            for pid in [p for p, r in self.plans.items() if r["symbol"] == s]:
                self.done_plans[pid] = {**self.plans.pop(pid), "state": 4}
        return size

    def _trigger(self, s):
        px = self.prices[s]
        for pid, p in sorted(self.plans.items()):
            if pid not in self.plans or p["symbol"] != s:
                continue
            trig = float(p["trigger_price"])
            if (p["side"] == 3 and px <= trig) or (p["side"] == 2 and px >= trig):
                self._execute(pid, px)

    def _execute(self, pid, px):
        p = self.plans.pop(pid)
        s = p["symbol"]
        n = self.pos[s]
        oid = self._id()
        if (p["side"] == 3 and n > 0) or (p["side"] == 2 and n < 0):
            self._fill(s, p["side"], int(p["size"]), px, oid, f"PLAN_{pid}" if self.placed_cid else "")
        self.done_plans[pid] = {**p, "state": 4, "executive_order_id": str(oid)}

    # ------------------------------------------------------------ routes
    def _route(self, m, path, query, body):
        q = dict(urllib.parse.parse_qsl(query)) if m == "GET" else json.loads(body or b"{}")
        if (m, path) == ("GET", "/system/time"):
            if self.time_source != "system":
                return 404, json.dumps({"error_msg": "404 Route Not Found"}).encode(), {}
            return self._ok({"server_time": self.now()})
        if (m, path) == ("GET", "/contract/public/funding-rate"):
            ts = self.now() if self.time_source in ("system", "funding") else 0
            return self._ok({"timestamp": ts, "symbol": q.get("symbol"), "rate_value": "0.0001"})
        if (m, path) == ("GET", "/contract/public/leverage-bracket"):
            s = q["symbol"]
            rows = [{"bracket": i + 1, "initial_leverage": b[0], "notional_floor": str(b[1]), "notional_cap": str(b[2]),
                     "maint_margin_ratio": str(b[3] if len(b) > 3 else 0.005), "cum": "0"}
                    for i, b in enumerate(self._brackets(s))]
            return self._ok({"rules": [{"symbol": s, "brackets": rows}]})
        if (m, path) == ("GET", "/contract/public/details"):
            rows = [self._detail(s) for s in SPECS if not q.get("symbol") or q["symbol"] == s]
            rows.append({"symbol": "BTCUSD", "product_type": 1, "quote_currency": "USD", "contract_size": "1",
                         "vol_precision": "1", "min_volume": "1", "price_precision": "0.5"})
            return self._ok({"symbols": rows})
        if (m, path) in (("GET", "/contract/public/kline"), ("GET", "/contract/public/markprice-kline")):
            s, lo, hi = q["symbol"], int(q["start_time"]) * 1000, int(q["end_time"]) * 1000
            assert q["step"] == "1" and hi > lo and (hi - lo) // 60_000 <= 500
            rows = [{"timestamp": t // 1000, "open_price": repr(b[0]), "high_price": repr(b[1]),
                     "low_price": repr(b[2]), "close_price": repr(b[3]), "volume": "1"}
                    for (sym, t), b in sorted(self.bars.items()) if sym == s and lo <= t <= hi]
            if self.last_kline_empty and path.endswith("/kline"):
                rows = []                             # the owners' server, 10-20: the last price's candles are empty
            if not rows and path.endswith("markprice-kline"):
                rows = [{"timestamp": self.now() // 60_000 * 60, "close_price": repr(self.prices[s])}]
            return self._ok(rows)
        if (m, path) == ("GET", "/contract/private/assets-detail"):
            up = sum(self._upnl(s) for s in SPECS)
            mg = sum(self._margin(s) for s in SPECS)
            return self._ok([{"currency": "USDT", "position_deposit": f"{mg:.8f}", "frozen_balance": "0",
                              "available_balance": f"{self.wallet - mg:.8f}", "equity": f"{self.wallet + up:.8f}",
                              "unrealized": f"{up:.8f}"},
                             {"currency": "BTC", "position_deposit": "0", "frozen_balance": "0",
                              "available_balance": "0", "equity": "0", "unrealized": "0"}])
        if (m, path) == ("GET", "/contract/private/trade-fee-rate"):
            return self._ok({"symbol": q["symbol"], "taker_fee_rate": str(self.fee), "maker_fee_rate": "0.0002"})
        if (m, path) == ("GET", "/contract/private/get-position-mode"):
            return self._ok({"position_mode": self.mode})
        if (m, path) == ("POST", "/contract/private/set-position-mode"):
            if self.busy():
                return self._error(40017, "It is not possible to change with open positions")
            assert q["position_mode"] in ("one_way_mode", "hedge_mode")
            self.mode = q["position_mode"]
            return self._ok({"position_mode": self.mode})
        if (m, path) == ("GET", "/contract/private/position-v2"):
            s = q["symbol"]
            sides = ["both"] if self.mode == "one_way_mode" else ["long", "short"]
            return self._ok([{"symbol": s, "leverage": str(self.levs[s][1]), "open_type": self.levs[s][0],
                              "position_side": side, "current_amount": str(abs(self.pos[s])),
                              "position_amount": str(self.pos[s]), "account": "futures",
                              "timestamp": self.now()} for side in sides])
        if (m, path) == ("POST", "/contract/private/submit-leverage"):
            s = q["symbol"]
            assert isinstance(q["leverage"], str) and q["open_type"] in ("isolated", "cross")
            if int(q["leverage"]) > self.max_lev[s]:
                return self._error(40029, "The order's leverage is too large.")
            if self.pos[s] and self.levs[s][0] != q["open_type"]:
                return self._error(40022, "The position is not isolated")
            self.levs[s] = [q["open_type"], int(q["leverage"])]
            return self._ok({"symbol": s, "leverage": q["leverage"], "open_type": q["open_type"], "max_value": "100"})
        if (m, path) == ("GET", "/contract/private/position"):
            rows = []
            for s, n in self.pos.items():
                if q.get("symbol") and q["symbol"] != s:
                    continue
                if n:
                    rows.append({"symbol": s, "leverage": str(self.levs[s][1]), "current_amount": str(abs(n)),
                                 "position_type": 1 if n > 0 else 2, "entry_price": repr(self.entry[s]),
                                 "open_avg_price": repr(self.entry[s]), "mark_price": repr(self.prices[s]),
                                 "margin_type": self.levs[s][0].capitalize(), "position_mode": self.mode,
                                 "unrealized_value": f"{self._upnl(s):.8f}", "account": "futures",
                                 "timestamp": self.now()})
            return self._ok(rows)
        if (m, path) == ("POST", "/contract/private/submit-order"):
            return self._submit(q)
        if (m, path) == ("GET", "/contract/private/order"):
            o = self.orders.get(q["order_id"])
            if o is None or o["symbol"] != q["symbol"]:
                return self._error(40035, "The order is not exist")
            return self._ok(o)
        if (m, path) == ("GET", "/contract/private/order-history"):
            rows = [o for o in self.orders.values() if o["symbol"] == q["symbol"]]
            if self.history_plans:
                rows += [{**p, "type": "planorder", "trigger_price": p["trigger_price"],
                          "deal_size": "0", "deal_avg_price": "0"} for p in self.done_plans.values()
                         if p["symbol"] == q["symbol"]]
            if q.get("order_id"):
                rows = [r for r in rows if r["order_id"] == q["order_id"]]
            if q.get("client_order_id"):
                rows = [r for r in rows if r["client_order_id"] == q["client_order_id"]]
            return self._ok(rows[-200:])
        if (m, path) == ("GET", "/contract/private/get-open-orders"):
            return self._ok([])
        if (m, path) == ("POST", "/contract/private/cancel-orders"):
            return self._ok({})
        if (m, path) == ("POST", "/contract/private/submit-tp-sl-order"):
            return self._tpsl(q)
        if (m, path) == ("GET", "/contract/private/current-plan-order"):
            rows = [p for p in self.plans.values() if not q.get("symbol") or p["symbol"] == q["symbol"]]
            return self._ok(rows[:int(q.get("limit", 100))])
        if (m, path) == ("POST", "/contract/private/cancel-plan-order"):
            pid = q.get("order_id")
            if pid not in self.plans or self.plans[pid]["symbol"] != q["symbol"]:
                return self._error(40035, "The order is not exist")
            self.done_plans[pid] = {**self.plans.pop(pid), "state": 4}
            return self._ok({})
        if (m, path) == ("GET", "/contract/private/trades"):
            lo, hi = int(q["start_time"]) * 1000, int(q["end_time"]) * 1000 + 999
            assert hi > lo and hi - lo <= 90 * 86_400_000 + 1000
            rows = [t for t in self.trades if t["symbol"] == q.get("symbol", t["symbol"]) and lo <= t["create_time"] <= hi]
            return self._ok(rows[:200])
        if (m, path) == ("GET", "/contract/private/transaction-history"):
            lo, hi = int(q["start_time"]), int(q["end_time"])
            rows = [r for r in self.flows if r["flow"] == int(q["flow_type"]) and lo <= int(r["time"]) <= hi
                    and (not q.get("symbol") or r["symbol"] == q["symbol"])]
            return self._ok([{k: v for k, v in r.items() if k != "flow"} for r in rows][:int(q["page_size"])])
        return 404, json.dumps({"error_msg": "404 Route Not Found"}).encode(), {}

    def _detail(self, s):
        sp = SPECS[s]
        return {"symbol": s, "product_type": 1, "base_currency": s[:-4], "quote_currency": "USDT",
                "last_price": repr(self.prices[s]), "contract_size": sp["cs"], "min_leverage": "1",
                "max_leverage": str(self.max_lev[s]), "price_precision": sp["pp"], "vol_precision": sp["vp"],
                "max_volume": "100000000", "market_max_volume": "100000000", "min_volume": sp["min"],
                "funding_interval_hours": 8, "status": "Trading"}

    def _brackets(self, s):
        lev = self.max_lev[s]
        return self.brackets.get(s) or [(lev, 0, 200_000, 0.005), (max(1, lev // 2), 200_000, 1_000_000, 0.01)]

    def _cap(self, s, lev):
        """The largest position value at ``lev`` (its brackets from the smallest up), 0 when none allows it."""
        cap = 0
        for lv, _lo, hi, *_mmr in self._brackets(s):
            if lv < lev:
                break
            cap = hi
        return cap

    def _check_cid(self, cid):
        if cid is None:
            return None
        if not (0 < len(cid) <= 32 and cid.isalnum()):
            return self._error(40048, "ClientOrderId only allows a combination of numbers and letters")
        if cid in self.cids:
            return self._error(40050, "Client OrderId duplicated with existing orders")
        return None

    def _submit(self, q):
        s, side, size = q["symbol"], q["side"], q["size"]
        assert q["type"] == "market" and side in (1, 2, 3, 4) and isinstance(size, int) and size > 0
        bad = self._check_cid(q.get("client_order_id"))
        if bad:
            return bad
        if self.mode != "one_way_mode":
            return self._error(40017, "hedge mode not supported by this fake")
        if side in OPEN_SIDES:
            assert q.get("open_type") == "isolated" and q.get("leverage") == str(self.levs[s][1]), q
            if self.levs[s][0] != "isolated":
                return self._error(40022, "The position is not isolated")
            value = (abs(self.pos[s]) + size) * float(SPECS[s]["cs"]) * self.prices[s]
            if value > self._cap(s, self.levs[s][1]):
                return self._error(40029, "The order's leverage is too large.")
        else:
            n = self.pos[s]
            if not ((side == 3 and n > 0) or (side == 2 and n < 0)):
                return self._error(40018, "Your position is closed")
        self.cids.add(q.get("client_order_id"))
        oid = self._id()
        self._fill(s, side, size, self.prices[s], oid, q.get("client_order_id") or "")
        return self._ok({"order_id": oid, "price": "market price"})

    def _tpsl(self, q):
        s, side = q["symbol"], q["side"]
        assert q["type"] == "stop_loss" and side in CLOSE_SIDES and isinstance(q["size"], int) and q["size"] > 0, q
        assert q["price_type"] == 1 and q["plan_category"] == 1 and q["category"] == "market", q
        assert q["executive_price"] == q["trigger_price"], q
        bad = self._check_cid(q.get("client_order_id"))
        if bad:
            return bad
        n = self.pos[s]
        if not ((side == 3 and n > 0) or (side == 2 and n < 0)):
            return self._error(40021, "The position is not exsit")
        if not self.two_stops and any(p["symbol"] == s for p in self.plans.values()):
            return self._error(40028, "Your plan order's count is more than system maximum limit.")
        trig = float(q["trigger_price"])
        px = self.prices[s]
        past = (side == 3 and px <= trig) or (side == 2 and px >= trig)
        if past and self.plan_past == "refuse":
            return self._error(40031, "The deviation between current price and trigger price is too large.")
        if past and self.plan_past == "invalid":
            return self._error(40012, "The stop loss price is invalid, needs to be "
                                      f"{'lesser' if side == 3 else 'greater'} than the order price")
        self.cids.add(q.get("client_order_id"))
        pid = str(self._id())
        self.plans[pid] = {"order_id": pid, "client_order_id": q.get("client_order_id") or "", "symbol": s,
                           "side": side, "type": "stop_loss", "trigger_price": q["trigger_price"],
                           "executive_price": q["executive_price"], "size": str(q["size"]), "price_type": 1,
                           "plan_category": 1, "mode": 1, "position_mode": self.mode, "price_way": 2,
                           "open_type": self.levs[s][0], "leverage": str(self.levs[s][1]), "state": 1,
                           "create_time": self.now(), "update_time": self.now()}
        if past:
            self._execute(pid, px)
        return self._ok({"order_id": pid, "client_order_id": q.get("client_order_id") or ""})
