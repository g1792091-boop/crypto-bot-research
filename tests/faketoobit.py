"""Stateful fake of Toobit's USDT-M futures REST API (api.toobit.com) for tests; no network.

Answers in the shapes of Toobit's USDT-M docs (the toobit-docs/apidocs repository, January 2026) and of ccxt's
toobit.js samples: success as a plain JSON object or list (the settings with "code": 200); errors as HTTP 400 / 401 with
{"code": -XXXX, "msg"}; 429 with Retry-After. Every private request's signature is checked as the docs define it: hex
HMAC-SHA256(secret, the query string followed by the form body) with ``&signature=`` last, X-BB-APIKEY, timestamp
within recvWindow (and not 1 s ahead) of the fake's clock, else -1021. Every request's parameters must be the
endpoint's documented ones (an AssertionError otherwise). Contracts "BTC-SWAP-USDT" in exchangeInfo ``contracts``
(SPECS: test data; ETH's LOT_SIZE in base units, the others in contracts); sizes are whole contracts; positions per
(coin, LONG / SHORT), so a coin can hold both sides (a two-way account). Orders: type LIMIT with priceType MARKET
(filled at the last price), type STOP with stopPrice (resting until the price crosses it, then a market order on its
side).

Unknowns of the real exchange are switches:
- ``close_words``: "docs" (SELL_CLOSE closes a long, BUY_CLOSE a short) or "swapped" (ccxt's reading: the other way);
- ``two_stops``: whether a second closing STOP can rest on a position next to the first (else refused);
- ``locks_close``: a resting closing STOP locks the position's ``available`` quantity (a close or a stop past it is
  refused);
- ``stop_price``: "last" or "mark": which price fires a STOP;
- ``stop_family``: "plan" (ORDER_NEW / ORDER_FILLED / ORDER_CANCELED / ORDER_FAILED) or "regular" (NEW / FILLED ...);
- ``level_field``: "stopPrice" or "triggerPrice": where a STOP row carries its level;
- ``own_fills``: whether a fired STOP's fills carry its own orderId (else a new market order's, no client id);
- ``past_stop``: "trigger" (a STOP already past the price fires at once) or "refuse";
- ``flat_cancels``: whether resting closing STOPs are cancelled when their position closes;
- ``cancel_answer``: "before" (a cancel answers the order's status before it: NEW) or "after" (CANCELED);
- ``cancel_final``: a cancel of an order that ended: "record" (its record, code 200) or "error" (-2013);
- ``query_cid``: whether GET order finds an order by origClientOrderId; ``lists_hide_cid``: the lists show it "";
- ``order_lag_ms`` / ``stop_lag_ms`` / ``fill_lag_ms`` / ``history_lag_ms``: records show only this long after;
- ``kill_new_stops``: a STOP is accepted and cancelled by the exchange right after;
- ``partial`` (a fraction) and ``rest``: the next market order fills only that part; the rest rests (``rest`` True,
  until cancelled) or is cancelled;
- ``pnl_net_of_fees``: a fill's realizedPnl net of its fee; ``unknown_ids``: "error" (-2013) or "empty" ({});
- ``ticker_name``: "contract" (s = BTC-SWAP-USDT) or "plain" (BTCUSDT); ``lev_lag_ms``: accountLeverage lags a set;
- ``oversize``: "refuse" (a close or a firing STOP bigger than the position is refused) or "cap";
- ``balance_is_free``: ``balance`` is the wallet minus the position margin (a reading the drill must catch);
- ``rate_limit``: (window ms, max requests): beyond it, 429.

Failures are injected per request with ``fail(method, path, kind, times)``: "drop_before" / "drop_after" (TimeoutError
before / after executing), "503_before", "429" or ("429", seconds), "429_after" (executed, then answered 429), "403",
"403_after", ("err", http status, code, msg) (refused, not executed) and ("err_after", http status, code, msg)
(executed, then answered with that).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import urllib.parse
from decimal import Decimal

SPECS = {   # test data shaped like exchangeInfo ``contracts`` (filters, contractMultiplier, riskLimits)
    "BTCUSDT": {"ct": "0.001", "step": "1", "min": "1", "max": "100000", "tick": "0.1", "notional": "5", "im": "0.008"},
    "ETHUSDT": {"ct": "0.01", "step": "0.01", "min": "0.01", "max": "1000", "tick": "0.01", "notional": "5",
                "im": "0.01"},                          # LOT_SIZE in base units (0.01 ETH = 1 contract)
    "SOLUSDT": {"ct": "0.1", "step": "1", "min": "1", "max": "50000", "tick": "0.001", "notional": "5", "im": "0.02"},
    "DOGEUSDT": {"ct": "10", "step": "1", "min": "1", "max": "500000", "tick": "0.00001", "notional": "5",
                 "im": "0.02"},
    "LTCUSDT": {"ct": "1", "step": "1", "min": "1", "max": "20000", "tick": "0.01", "notional": "5", "im": "0.02"},
    "BCHUSDT": {"ct": "0.01", "step": "1", "min": "1", "max": "50000", "tick": "0.01", "notional": "5", "im": "0.02"},
}
SIDES = ("BUY_OPEN", "SELL_OPEN", "BUY_CLOSE", "SELL_CLOSE")
CID_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")
TS, RW, CAT = {"timestamp", "recvWindow", "signature"}, set(), {"category"}
ALLOWED = {   # the documented parameters of each endpoint (plus timestamp / recvWindow / signature when signed)
    ("GET", "/api/v1/time"): set(), ("GET", "/api/v1/exchangeInfo"): set(),
    ("GET", "/quote/v1/contract/ticker/price"): {"symbol"}, ("GET", "/quote/v1/markPrice"): {"symbol"},
    ("GET", "/quote/v1/klines"): {"symbol", "interval", "startTime", "endTime", "limit"},
    ("GET", "/api/v1/futures/balance"): CAT, ("GET", "/api/v1/futures/positions"): {"symbol", "side"} | CAT,
    ("GET", "/api/v1/futures/accountLeverage"): {"symbol"} | CAT,
    ("POST", "/api/v1/futures/marginType"): {"symbol", "marginType"} | CAT,
    ("POST", "/api/v1/futures/leverage"): {"symbol", "leverage"} | CAT,
    ("POST", "/api/v1/futures/order"): {"symbol", "side", "type", "quantity", "valueQuantity", "price", "priceType",
                                        "stopPrice", "timeInForce", "newClientOrderId"} | CAT,
    ("GET", "/api/v1/futures/order"): {"orderId", "origClientOrderId", "type"} | CAT,
    ("DELETE", "/api/v1/futures/order"): {"orderId", "origClientOrderId", "type", "symbol"} | CAT,
    ("GET", "/api/v1/futures/openOrders"): {"symbol", "orderId", "type", "limit"} | CAT,
    ("GET", "/api/v1/futures/historyOrders"): {"symbol", "orderId", "type", "startTime", "endTime", "limit"} | CAT,
    ("GET", "/api/v1/futures/userTrades"): {"symbol", "startTime", "endTime", "limit", "fromId", "toId"} | CAT,
    ("GET", "/api/v1/futures/balanceFlow"): {"symbol", "flowType", "fromId", "endId", "startTime", "endTime",
                                             "limit"} | CAT,
    ("GET", "/api/v1/futures/commissionRate"): {"symbol"},
}
PUBLIC = {"/api/v1/time", "/api/v1/exchangeInfo", "/quote/v1/contract/ticker/price", "/quote/v1/markPrice",
          "/quote/v1/klines"}


def tid(s):
    return f"{s[:-4]}-SWAP-USDT"


def sym(t):
    return t.replace("-SWAP-USDT", "USDT")


def num(d):
    d = Decimal(str(d))
    return "0" if d == 0 else format(d.normalize(), "f")


class FakeToobit:
    def __init__(self, prices=None, wallet=10_000.0, fee=0.0006, api_key="tk", api_secret="ts"):
        self.prices = {s: 100.0 for s in SPECS}
        self.prices.update(prices or {})
        self.marks = dict(self.prices)
        self.wallet, self.fee = wallet, fee
        self.key, self.secret = api_key, api_secret
        self.clock = None
        self.levs = {s: {"leverage": 20, "marginType": "CROSS"} for s in SPECS}
        self.lev_was: dict = {}                    # symbol -> (the setting before the last change, changed at ms)
        self.pos: dict = {}                        # (symbol, LONG / SHORT) -> position (contracts)
        self.orders: dict = {}                     # orderId -> record (regular orders and STOP orders)
        self.fills: list = []
        self.flows: list = []
        self.bars: dict = {}
        self.calls: list = []
        self.fails: list = []
        self.n = 2030231266373265000
        self.close_words = "docs"
        self.two_stops = True
        self.locks_close = False
        self.stop_price = "last"
        self.stop_family = "plan"
        self.level_field = "stopPrice"
        self.own_fills = False
        self.past_stop = "trigger"
        self.flat_cancels = False
        self.cancel_answer = "before"
        self.cancel_final = "record"
        self.query_cid = True
        self.lists_hide_cid = False
        self.order_lag_ms = 0
        self.stop_lag_ms = 0
        self.fill_lag_ms = 0
        self.history_lag_ms = 0
        self.kill_new_stops = False
        self.partial = None
        self.rest = False
        self.pnl_net_of_fees = False
        self.unknown_ids = "error"
        self.ticker_name = "contract"
        self.lev_lag_ms = 0
        self.oversize = "refuse"
        self.balance_is_free = False
        self.rate_limit = None
        self.states: dict = {}
        self.coverage: list = []                   # (call index, symbol, contracts, covered by a closing STOP)
        self.order_bodies: list = []
        self.stop_bodies: list = []

    # ------------------------------------------------------------ helpers for tests
    def now(self):
        return self.clock() if self.clock else 1_800_000_000_000

    def fail(self, method, path, kind, times=1):
        self.fails.append([method, path, kind, times])

    def _id(self):
        self.n += 7
        return str(self.n)

    def ct(self, s):
        return Decimal(SPECS[s]["ct"])

    def set_price(self, symbol, price, mark=None):
        self.prices[symbol] = price
        self.marks[symbol] = price if mark is None else mark
        m = self.now() // 60_000 * 60_000
        b = self.bars.get((symbol, m))
        self.bars[(symbol, m)] = [b[0], max(b[1], price), min(b[2], price), price] if b else [price] * 4
        self._fire_due(symbol)

    def amt(self, symbol):
        """The net position in base units (+ long, - short)."""
        out = Decimal(0)
        for ps, sgn in (("LONG", 1), ("SHORT", -1)):
            p = self.pos.get((symbol, ps))
            if p:
                out += sgn * p["pos"] * self.ct(symbol)
        return float(out)

    def stops(self, symbol=None, resting=True):
        return [o for o in self.orders.values() if o["type"] == "STOP"
                and (symbol is None or o["symbol"] == tid(symbol))
                and (not resting or o["status"] in ("ORDER_NEW", "NEW"))]

    def live_stops(self, symbol=None):
        return [o for o in self.stops(symbol) if o["side"].endswith("_CLOSE")]

    def add_funding(self, symbol, amount, ms=None):
        self.wallet += amount
        self._flow(32, "FUND_FEE", "Fund Fee", amount, symbol, ms)

    def add_transfer(self, amount, ms=None):
        self.wallet += amount
        self._flow(51, "USER_ACCOUNT_TRANSFER", "Transfer", amount, None, ms)

    def unprotected(self):
        """Moments a position had no closing STOP covering it, after its first STOP was placed."""
        first = {}
        for i, c in enumerate(self.calls, start=1):
            if c[1] == "POST" and c[2] == "/api/v1/futures/order" and "type=STOP" in (c[4] or b"").decode():
                q = dict(urllib.parse.parse_qsl(c[4].decode()))
                first.setdefault(sym(q["symbol"]), i)
        return [c for c in self.coverage if c[2] and not c[3] and c[1] in first and c[0] > first[c[1]]]

    def closes(self, side):
        """The position side a closing side closes (``close_words``)."""
        docs = {"SELL_CLOSE": "LONG", "BUY_CLOSE": "SHORT"}[side]
        return docs if self.close_words == "docs" else {"LONG": "SHORT", "SHORT": "LONG"}[docs]

    # ------------------------------------------------------------ transport
    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        assert u.scheme == "https" and u.hostname == "api.toobit.com" and u.port is None, url
        path, query = u.path, u.query
        self.calls.append((self.now(), method, path, query, body))
        raw = (body or b"").decode() if method == "POST" else query
        if method != "POST":
            assert body is None, (method, path)
        for f in self.fails:
            if f[0] == method and path.startswith(f[1]) and f[3] > 0:
                f[3] -= 1
                kind = f[2]
                if kind == "drop_before":
                    raise TimeoutError("dropped")
                if kind == "503_before":
                    return 503, b"<html>Service Unavailable</html>", {}
                if kind == "429" or (isinstance(kind, tuple) and kind[0] == "429"):
                    after = kind[1] if isinstance(kind, tuple) else 1
                    return 429, b'{"code":-1003,"msg":"Too many requests."}', {"Retry-After": str(after)}
                if kind == "429_after":
                    self._dispatch(method, path, raw, headers)
                    return 429, b'{"code":-1003,"msg":"Too many requests."}', {"Retry-After": "1"}
                if kind == "403":
                    return 403, b"<html>403 Forbidden</html>", {}
                if kind == "403_after":
                    self._dispatch(method, path, raw, headers)
                    return 403, b"<html>403 Forbidden</html>", {}
                if isinstance(kind, tuple) and kind[0] == "err":
                    return kind[1], json.dumps({"code": kind[2], "msg": kind[3]}).encode(), {}
                if isinstance(kind, tuple) and kind[0] == "err_after":
                    self._dispatch(method, path, raw, headers)
                    return kind[1], json.dumps({"code": kind[2], "msg": kind[3]}).encode(), {}
                if kind == "drop_after":
                    self._dispatch(method, path, raw, headers)
                    raise TimeoutError("dropped after")
        if self.rate_limit:
            window, most = self.rate_limit
            if len([c for c in self.calls if self.now() - c[0] < window]) > most:
                return 429, b'{"code":-1003,"msg":"Too many requests."}', {"Retry-After": "1"}
        out = self._dispatch(method, path, raw, headers)
        self._note_coverage()
        return out

    def _dispatch(self, method, path, raw, headers):
        private = path not in PUBLIC
        q = dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))
        allowed = ALLOWED.get((method, path))
        if allowed is None:
            return self._err(404, -1020, "This operation is not supported.")
        assert set(q) - TS <= allowed, (method, path, sorted(set(q) - TS - allowed))
        if private:
            if method == "POST":
                assert headers.get("Content-Type") == "application/x-www-form-urlencoded", headers
            bad = self._auth(raw, q, headers)
            if bad is not None:
                return bad
            for k in TS:
                q.pop(k, None)
        else:
            assert "signature" not in q and "X-BB-APIKEY" not in headers, (path, q)
        return self._route(method, path, q)

    def _auth(self, raw, q, h):
        if h.get("X-BB-APIKEY") != self.key:
            return self._err(401, -2015, "Invalid API-key, IP, or permissions for action.")
        if not raw.endswith("&signature=" + q.get("signature", "?")) and raw != "signature=" + q.get("signature", "?"):
            return self._err(400, -1022, "Signature for this request is not valid.")
        payload = raw[:raw.rindex("signature=")].rstrip("&")
        want = hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if q["signature"].lower() != want:
            return self._err(400, -1022, "Signature for this request is not valid.")
        try:
            ts, rw = int(q["timestamp"]), int(q.get("recvWindow", 5000))
        except (KeyError, ValueError):
            return self._err(400, -1102, "Mandatory parameter 'timestamp' was not sent, was empty/null, or malformed.")
        if not (ts < self.now() + 1000 and self.now() - ts <= rw):
            return self._err(400, -1021, "Timestamp for this request is outside of the recvWindow.")
        return None

    def _note_coverage(self):
        for (s, ps), p in self.pos.items():
            if p["pos"]:
                cov = sum(Decimal(o["origQty"]) for o in self.live_stops(s) if self.closes(o["side"]) == ps)
                self.coverage.append((len(self.calls), s, p["pos"], cov >= p["pos"]))

    @staticmethod
    def _ok(data):
        return 200, json.dumps(data).encode(), {}

    @staticmethod
    def _err(status, code, msg):
        return status, json.dumps({"code": code, "msg": msg}).encode(), {}

    def _unknown(self):
        if self.unknown_ids == "empty":
            return self._ok({})
        return self._err(400, -2013, "Order does not exist.")

    # ------------------------------------------------------------ state
    def _flow(self, typ, name, label, change, symbol, ms=None):
        self.flows.append({"id": self._id(), "accountId": "1795119090857208834", "coin": "USDT", "coinId": "USDT",
                           "coinName": "USDT", "symbol": symbol or "", "symbolId": tid(symbol) if symbol else "",
                           "flowTypeValue": typ, "flowType": name, "flowName": label, "change": f"{change:.8f}",
                           "total": f"{self.wallet:.8f}", "created": str(self.now() if ms is None else ms)})

    def _upnl(self, s, ps):
        p = self.pos.get((s, ps))
        if not p or not p["pos"]:
            return 0.0
        q = float(p["pos"] * self.ct(s))
        return q * (self.prices[s] - p["avg"]) * (1 if ps == "LONG" else -1)

    def _margin(self, s, ps):
        p = self.pos.get((s, ps))
        if not p or not p["pos"]:
            return 0.0
        return float(p["pos"] * self.ct(s)) * p["avg"] / p["lev"]

    def _locked(self, s, ps):
        if not self.locks_close:
            return Decimal(0)
        return sum((Decimal(o["origQty"]) for o in self.live_stops(s) if self.closes(o["side"]) == ps), Decimal(0))

    def _fill(self, o, contracts, px):
        """Fill ``contracts`` of order ``o`` at ``px``: an opening side adds to its position, a closing one reduces."""
        s, side = sym(o["symbol"]), o["side"]
        closing = side.endswith("_CLOSE")
        ps = self.closes(side) if closing else ("LONG" if side == "BUY_OPEN" else "SHORT")
        key = (s, ps)
        p = self.pos.get(key)
        ct = self.ct(s)
        realized = 0.0
        if closing:
            have = p["pos"] if p else Decimal(0)
            contracts = min(contracts, have)
            if contracts <= 0:
                return Decimal(0)
            realized = float(contracts * ct) * (px - p["avg"]) * (1 if ps == "LONG" else -1)
            p["pos"] -= contracts
            if p["pos"] == 0:
                del self.pos[key]
                if self.flat_cancels:
                    for t in [t for t in self.live_stops(s) if self.closes(t["side"]) == ps]:
                        self._end(t, "CANCELED")
        else:
            if p is None:
                p = self.pos[key] = {"pos": Decimal(0), "avg": 0.0, "lev": self.levs[s]["leverage"],
                                     "mt": self.levs[s]["marginType"], "realized": 0.0}
            q0 = p["pos"]
            p["avg"] = float((q0 * Decimal(repr(p["avg"])) + contracts * Decimal(repr(px))) / (q0 + contracts))
            p["pos"] += contracts
        fee = float(contracts * ct) * px * self.fee
        self.wallet += realized - fee
        if closing:
            self._flow(28, "REALIZED_PNL", "Realized PNL", realized, s)
        self._flow(10, "FEE", "Fee", -fee, s)
        self.fills.append({"time": str(self.now()), "id": self._id(), "orderId": o["orderId"], "symbol": o["symbol"],
                           "price": repr(px), "qty": num(contracts), "commissionAsset": "USDT",
                           "commission": f"{fee:.8f}", "makerRebate": "0", "type": "LIMIT", "isMaker": False,
                           "side": side, "realizedPnl": f"{(realized - (fee if self.pnl_net_of_fees else 0.0)):.8f}"
                           if closing else "0", "ticketId": self._id()})
        return contracts

    def _record(self, q, kind):
        oid = self._id()
        s = sym(q["symbol"])
        o = {"time": str(self.now()), "updateTime": str(self.now()), "orderId": oid,
             "clientOrderId": q.get("newClientOrderId", ""), "symbol": q["symbol"], "price": "0",
             "leverage": str(self.levs[s]["leverage"]), "origQty": q["quantity"], "executedQty": "0", "avgPrice": "0",
             "marginLocked": "0", "type": kind, "side": q["side"], "timeInForce": "GTC",
             "status": ("ORDER_NEW" if self.stop_family == "plan" else "NEW") if kind == "STOP" else "NEW",
             "priceType": q.get("priceType", "INPUT")}
        if kind == "STOP":
            o[self.level_field] = q["stopPrice"]
        self.orders[oid] = o
        return o

    def _execute(self, o, want, px):
        filled = self._fill(o, want, px) if want > 0 else Decimal(0)
        o.update(executedQty=num(filled), avgPrice=repr(px) if filled else "0", updateTime=str(self.now()))
        if filled == Decimal(o["origQty"]):
            o["status"] = "FILLED"
        elif self.rest:
            o["status"] = "PARTIALLY_FILLED" if filled else "NEW"
        else:
            o["status"] = "CANCELED"
        o["_ended"] = self.now()
        return filled

    def _end(self, t, status):
        plan = {"FILLED": "ORDER_FILLED", "CANCELED": "ORDER_CANCELED", "FAILED": "ORDER_FAILED"}
        t["status"] = plan[status] if self.stop_family == "plan" else {"FAILED": "REJECTED"}.get(status, status)
        t["updateTime"] = str(self.now())
        t["_ended"] = self.now()

    def _fire_due(self, s):
        for t in sorted(self.stops(s), key=lambda o: int(o["orderId"])):
            if t["status"] not in ("ORDER_NEW", "NEW"):
                continue
            px = self.prices[s] if self.stop_price == "last" else self.marks[s]
            trig = float(t[self.level_field])
            if (t["side"].startswith("SELL") and px <= trig) or (t["side"].startswith("BUY") and px >= trig):
                self._fire(t)

    def _fire(self, t):
        s = sym(t["symbol"])
        closing = t["side"].endswith("_CLOSE")
        if closing:
            p = self.pos.get((s, self.closes(t["side"])))
            if not (p and p["pos"]) or (self.oversize == "refuse" and Decimal(t["origQty"]) > p["pos"]):
                self._end(t, "FAILED")
                return
        q = {"symbol": t["symbol"], "side": t["side"], "quantity": t["origQty"], "priceType": "MARKET",
             "newClientOrderId": ""}
        child = self._record(q, "LIMIT")
        if self.own_fills:
            del self.orders[child["orderId"]]
            child = dict(child)
            child["orderId"] = t["orderId"]
        self._execute(child, Decimal(t["origQty"]), self.prices[s])
        self._end(t, "FILLED")

    # ------------------------------------------------------------ routes
    def _route(self, m, path, q):
        now = self.now()
        if path == "/api/v1/time":
            return self._ok({"serverTime": now})
        if path == "/api/v1/exchangeInfo":
            return self._ok(self._exchange_info())
        if path == "/quote/v1/contract/ticker/price":
            s = sym(q["symbol"])
            return self._ok([{"s": q["symbol"] if self.ticker_name == "contract" else s, "p": repr(self.prices[s])}])
        if path == "/quote/v1/markPrice":
            return self._ok({"exchangeId": 301, "symbolId": q["symbol"], "price": repr(self.marks[sym(q["symbol"])]),
                             "time": now})
        if path == "/quote/v1/klines":
            s = sym(q["symbol"])
            assert q["interval"] == "1m" and 1 <= int(q.get("limit", 1000)) <= 1000, q
            lo, hi = int(q.get("startTime", 0)), int(q.get("endTime", 10 ** 15))
            rows = [[t, repr(b[0]), repr(b[1]), repr(b[2]), repr(b[3]), "10", t + 59_999, "1000", 3, "5", "500"]
                    for (x, t), b in sorted(self.bars.items()) if x == s and lo <= t <= hi]
            return self._ok(rows[:int(q.get("limit", 1000))])
        # ---- account
        if path == "/api/v1/futures/balance":
            mg = sum(self._margin(s, ps) for (s, ps) in self.pos)
            up = sum(self._upnl(s, ps) for (s, ps) in self.pos)
            bal = self.wallet - (mg if self.balance_is_free else 0.0)
            return self._ok([{"asset": "USDT", "balance": f"{bal:.8f}",
                              "availableBalance": f"{self.wallet - mg + up:.8f}", "positionMargin": f"{mg:.8f}",
                              "orderMargin": "0", "crossUnRealizedPnl": "0"}])
        if path == "/api/v1/futures/positions":
            rows = [self._pos_row(s, ps) for (s, ps) in sorted(self.pos)
                    if (not q.get("symbol") or q["symbol"] == tid(s)) and (not q.get("side") or q["side"] == ps)]
            return self._ok(rows)
        if path == "/api/v1/futures/accountLeverage":
            s = sym(q["symbol"])
            cur = dict(self.levs[s])
            was, at = self.lev_was.get(s, (cur, None))
            if at is not None and now - at < self.lev_lag_ms:
                cur = was
            return self._ok([{"symbol": q["symbol"], "leverage": str(cur["leverage"]),
                              "marginType": cur["marginType"]}])
        if path == "/api/v1/futures/marginType":
            s = sym(q["symbol"])
            assert q["marginType"] in ("ISOLATED", "CROSS"), q
            if any(k[0] == s for k in self.pos) or any(o["symbol"] == q["symbol"] and o["status"] in (
                    "NEW", "PARTIALLY_FILLED", "ORDER_NEW") for o in self.orders.values()):
                return self._err(400, -3128, "The margin mode cannot be changed while you have an open order/position")
            self.lev_was[s] = (dict(self.levs[s]), now)
            self.levs[s]["marginType"] = q["marginType"]
            return self._ok({"code": 200, "symbolId": q["symbol"], "marginType": q["marginType"]})
        if path == "/api/v1/futures/leverage":
            s = sym(q["symbol"])
            lev = int(q["leverage"])
            if lev > int(1 / Decimal(SPECS[s]["im"])) or lev < 1:
                return self._err(400, -1130, "Data sent for paramter 'leverage' is not valid.")
            self.lev_was[s] = (dict(self.levs[s]), now)
            self.levs[s]["leverage"] = lev
            return self._ok({"code": 200, "symbolId": q["symbol"], "leverage": str(lev)})
        if path == "/api/v1/futures/commissionRate":
            return self._ok({"openMakerFee": "0.0002", "openTakerFee": str(self.fee), "closeMakerFee": "0.0002",
                             "closeTakerFee": str(self.fee)})
        # ---- orders
        if (m, path) == ("POST", "/api/v1/futures/order"):
            return self._place(q)
        if (m, path) == ("GET", "/api/v1/futures/order"):
            stop = q.get("type", "LIMIT") == "STOP"
            rows = [o for o in self._visible(stop) if (o["type"] == "STOP") == stop]
            if q.get("orderId"):
                rows = [o for o in rows if o["orderId"] == q["orderId"]]
            elif q.get("origClientOrderId"):
                if not self.query_cid:
                    return self._unknown()
                rows = [o for o in rows if o["clientOrderId"] == q["origClientOrderId"]]
            else:
                return self._err(400, -1102, "Param 'orderId' or 'origClientOrderId' must be sent, but both were "
                                             "empty/null!")
            if not rows:
                return self._unknown()
            return self._ok(self._public(sorted(rows, key=lambda o: int(o["time"]))[-1]))
        if (m, path) == ("DELETE", "/api/v1/futures/order"):
            stop = q.get("type", "LIMIT") == "STOP"
            o = self.orders.get(q.get("orderId"))
            if o is None or (o["type"] == "STOP") != stop or (q.get("symbol") and q["symbol"] != o["symbol"]):
                return self._err(400, -2013, "Order does not exist.")
            if o["status"] not in ("NEW", "PARTIALLY_FILLED", "ORDER_NEW"):
                if self.cancel_final == "error":
                    return self._err(400, -2013, "Order does not exist.")
                return self._ok(self._public(o))
            before = self._public(o)
            if stop:
                self._end(o, "CANCELED")
            else:
                o["status"], o["updateTime"], o["_ended"] = "CANCELED", str(now), now
            return self._ok(before if self.cancel_answer == "before" else self._public(o))
        if (m, path) == ("GET", "/api/v1/futures/openOrders"):
            stop = q.get("type", "LIMIT") == "STOP"
            rows = [o for o in self._visible(stop) if (o["type"] == "STOP") == stop and o["symbol"] == q.get(
                "symbol", o["symbol"]) and o["status"] in ("NEW", "PARTIALLY_FILLED", "ORDER_NEW")]
            assert 1 <= int(q.get("limit", 20)) <= 1000, q
            return self._ok([self._listed(o) for o in rows][:int(q.get("limit", 20))])
        if (m, path) == ("GET", "/api/v1/futures/historyOrders"):
            stop = q.get("type", "LIMIT") == "STOP"
            start = int(q.get("startTime", now - 3 * 86_400_000))
            rows = [o for o in self._visible(stop) if (o["type"] == "STOP") == stop and o["symbol"] == q.get(
                "symbol", o["symbol"]) and o["status"] not in ("NEW", "PARTIALLY_FILLED", "ORDER_NEW")
                and int(o["time"]) >= start and now - o.get("_ended", now) >= (self.history_lag_ms if stop else 0)]
            rows.sort(key=lambda o: int(o["orderId"]), reverse=True)
            return self._ok([self._listed(o) for o in rows][:int(q.get("limit", 20))])
        if (m, path) == ("GET", "/api/v1/futures/userTrades"):
            lo, hi = int(q.get("startTime", 0)), int(q.get("endTime", 10 ** 15))
            rows = [f for f in self.fills if f["symbol"] == q["symbol"] and lo <= int(f["time"]) <= hi
                    and now - int(f["time"]) >= self.fill_lag_ms]
            rows.sort(key=lambda f: (int(f["time"]), int(f["id"])), reverse=True)
            return self._ok(rows[:int(q.get("limit", 20))])
        if (m, path) == ("GET", "/api/v1/futures/balanceFlow"):
            lo, hi = int(q.get("startTime", 0)), int(q.get("endTime", 10 ** 15))
            rows = [r for r in self.flows if lo <= int(r["created"]) <= hi
                    and (not q.get("flowType") or int(q["flowType"]) == r["flowTypeValue"])]
            rows.sort(key=lambda r: (int(r["created"]), int(r["id"])), reverse=True)
            return self._ok(rows[:int(q.get("limit", 20))])
        return self._err(404, -1020, "This operation is not supported.")

    def _visible(self, stop):
        lag = self.stop_lag_ms if stop else self.order_lag_ms
        return [o for o in self.orders.values() if self.now() - int(o["time"]) >= lag]

    @staticmethod
    def _public(o):
        return {k: v for k, v in o.items() if not k.startswith("_")}

    def _listed(self, o):
        r = self._public(o)
        if self.lists_hide_cid:
            r["clientOrderId"] = ""
        return r

    def _exchange_info(self):
        def contract(s):
            sp = SPECS[s]
            return {"filters": [{"minPrice": sp["tick"], "maxPrice": "10000000", "tickSize": sp["tick"],
                                 "filterType": "PRICE_FILTER"},
                                {"minQty": sp["min"], "maxQty": sp["max"], "stepSize": sp["step"],
                                 "filterType": "LOT_SIZE"},
                                {"minNotional": sp["notional"], "filterType": "MIN_NOTIONAL"},
                                {"buyPriceUpRate": "0.05", "sellPriceDownRate": "0.05",
                                 "filterType": "MARKET_TRADING"}],
                    "exchangeId": "301", "symbol": tid(s), "symbolName": tid(s) + "USDT",
                    "status": self.states.get(s, "TRADING"), "baseAsset": tid(s), "baseAssetPrecision": sp["step"],
                    "quoteAsset": "USDT", "quoteAssetPrecision": sp["tick"], "icebergAllowed": False, "inverse": False,
                    "index": s[:-4], "indexToken": s, "marginToken": "USDT", "marginPrecision": "0.0001",
                    "contractMultiplier": sp["ct"], "underlying": s[:-4],
                    "riskLimits": [{"riskLimitId": "200020911", "quantity": "42000.0", "initialMargin": sp["im"],
                                    "maintMargin": str(Decimal(sp["im"]) / 2), "isWhite": False},
                                   {"riskLimitId": "200020912", "quantity": "84000.0", "initialMargin": "0.04",
                                    "maintMargin": "0.02", "isWhite": False}]}
        spot = {"filters": [], "exchangeId": "301", "symbol": "BTCUSDT", "symbolName": "BTCUSDT", "status": "TRADING",
                "baseAsset": "BTC", "quoteAsset": "USDT"}
        inverse = {**contract("BTCUSDT"), "symbol": "BTC-SWAP", "symbolName": "BTC-SWAP", "inverse": True,
                   "marginToken": "BTC", "contractMultiplier": "1.0"}
        return {"timezone": "UTC", "serverTime": str(self.now()), "brokerFilters": [], "symbols": [spot],
                "rateLimits": [{"rateLimitType": "REQUEST_WEIGHT", "interval": "MINUTE", "intervalUnit": 1,
                                "limit": 3000},
                               {"rateLimitType": "ORDERS", "interval": "SECOND", "intervalUnit": 60, "limit": 60}],
                "options": [], "contracts": [contract(s) for s in SPECS] + [inverse], "coins": []}

    def _pos_row(self, s, ps):
        p = self.pos[(s, ps)]
        q = float(p["pos"] * self.ct(s))
        avail = p["pos"] - self._locked(s, ps)
        return {"symbol": tid(s), "side": ps, "avgPrice": repr(p["avg"]), "position": num(p["pos"]),
                "available": num(max(avail, Decimal(0))), "leverage": str(p["lev"]), "lastPrice": repr(self.prices[s]),
                "positionValue": f"{q * self.prices[s]:.8f}", "flp": "0.1", "margin": f"{self._margin(s, ps):.8f}",
                "marginRate": "", "unrealizedPnL": f"{self._upnl(s, ps):.8f}", "profitRate": "0", "realizedPnL": "0",
                "minMargin": "0", "maxNotionalValue": "10000000", "marginType": p["mt"],
                "markPrice": repr(self.marks[s])}

    def _check_qty(self, s, quantity, opening):
        sp = SPECS[s]
        try:
            d = Decimal(quantity)
        except Exception:  # noqa: BLE001
            return -1102, "Mandatory parameter 'quantity' was not sent, was empty/null, or malformed."
        step = Decimal(sp["step"]) if Decimal(sp["step"]) >= 1 else Decimal(sp["step"]) / self.ct(s)
        if d <= 0 or d != d.to_integral_value() or (d / step) != (d / step).to_integral_value():
            return -1137, "Order quantity decimal too long."
        mn = Decimal(sp["min"]) if Decimal(sp["step"]) >= 1 else Decimal(sp["min"]) / self.ct(s)
        if opening and d < mn:
            return -1136, "Order quantity lower than the minimum."
        if opening and float(d * self.ct(s)) * self.prices[s] < float(sp["notional"]):
            return -1140, "Transaction amount lower than the minimum."
        return None

    def _place(self, q):
        for k in ("symbol", "side", "type", "quantity", "newClientOrderId"):
            if not q.get(k):
                return self._err(400, -1102, f"Mandatory parameter '{k}' was not sent, was empty/null, or malformed.")
        s = sym(q["symbol"])
        if s not in SPECS or q["symbol"] != tid(s):
            return self._err(400, -1121, "Invalid symbol.")
        if q["side"] not in SIDES:
            return self._err(400, -1117, "Invalid side.")
        if not CID_RE.match(q["newClientOrderId"]):
            return self._err(400, -1100, "Illegal characters found in parameter 'newClientOrderId'.")
        if any(o["clientOrderId"] == q["newClientOrderId"] and o["status"] in ("NEW", "PARTIALLY_FILLED", "ORDER_NEW")
               for o in self.orders.values()):
            return self._err(400, -1141, "Duplicate clientOrderId")
        closing = q["side"].endswith("_CLOSE")
        bad = self._check_qty(s, q["quantity"], not closing)
        if bad:
            return self._err(400, *bad)
        if q["type"] == "STOP":
            self.stop_bodies.append(dict(q))
            return self._stop(q, s, closing)
        assert q["type"] == "LIMIT" and q.get("priceType") == "MARKET" and "price" not in q, q
        self.order_bodies.append(dict(q))
        want = Decimal(q["quantity"])
        if closing:
            ps = self.closes(q["side"])
            p = self.pos.get((s, ps))
            if not p or not p["pos"]:
                return self._err(400, -2010, "NEW_ORDER_REJECTED: no position to close")
            if want > p["pos"] - self._locked(s, ps):
                if self.oversize == "refuse" or self._locked(s, ps):
                    return self._err(400, -2010, "NEW_ORDER_REJECTED: insufficient position to close")
        o = self._record(q, "LIMIT")
        if self.partial is not None:
            want = (want * Decimal(str(self.partial))).to_integral_value()
            self.partial = None
        self._execute(o, want, self.prices[s])
        return self._ok(self._public({**o, "status": "NEW", "executedQty": "0", "avgPrice": "0"}))

    def _stop(self, q, s, closing):
        assert q.get("priceType") == "MARKET" and q.get("stopPrice") and "price" not in q, q
        tick = Decimal(SPECS[s]["tick"])
        assert (Decimal(q["stopPrice"]) / tick) == (Decimal(q["stopPrice"]) / tick).to_integral_value(), q
        if closing:
            ps = self.closes(q["side"])
            mine = [t for t in self.live_stops(s) if self.closes(t["side"]) == ps]
            if not self.two_stops and mine:
                return self._err(400, -1193, "Create order count limit")
            p = self.pos.get((s, ps))
            if self.locks_close and Decimal(q["quantity"]) > ((p or {}).get("pos", Decimal(0)) - self._locked(s, ps)):
                return self._err(400, -2010, "NEW_ORDER_REJECTED: insufficient position to close")
        px = self.prices[s] if self.stop_price == "last" else self.marks[s]
        trig = float(q["stopPrice"])
        past = (q["side"].startswith("SELL") and px <= trig) or (q["side"].startswith("BUY") and px >= trig)
        if past and self.past_stop == "refuse":
            return self._err(400, -2010, "NEW_ORDER_REJECTED: Order would trigger immediately")
        t = self._record(q, "STOP")
        if past:
            self._fire(t)
        elif self.kill_new_stops:
            self._end(t, "CANCELED")
        return self._ok(self._public({**t, "status": "ORDER_NEW" if self.stop_family == "plan" else "NEW"}))
