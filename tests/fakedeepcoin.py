"""Stateful fake of DeepCoin's REST API (api.deepcoin.com) for tests; no network.

Answers in the shapes of DeepCoin's docs (www.deepcoin.com/docs) and of the public market answers read on 10-24: every
answer {code, msg, data}; an order refusal as code "0" with data.sCode / sMsg ("24" OrderNotFound, "31"
NotEnoughPositionToClose, "1033201232" Order not found on a trigger cancel); a parameter error as code "51"; auth errors
as HTTP 401 with code 5010x; 429 with Retry-After. Every private request's signature is checked as the Access Guide
defines it: Base64(HMAC-SHA256(secret, timestamp + METHOD + requestPath (+ "?" + the query as sent) + body)), with
DC-ACCESS-TIMESTAMP in ISO UTC with milliseconds (within 30 s of the fake's clock, else 50102) and DC-ACCESS-PASSPHRASE.
Instruments "BTC-USDT-SWAP"; sizes are contracts on ``lotSz`` (SPECS: test data shaped like the live answer, ETH and
SOL in 0.1 contracts); orders carry posSide long / short and mrgPosition merge (both required for SWAP), open = buy/long
or sell/short, close = sell/long or buy/short; positions per (coin, posSide), so a coin can hold both sides.

Covers what paperbot/deepcoin.py uses: server time, instruments, tickers (uly filter), mark price, 1m candles (built from
every ``set_price``; newest first, ``after`` inclusive), balances, positions, set-leverage / leverage-info, trade fee,
bills (types 1 P/L, 5 fee, 7 funding; newest first, ``before`` = older than), market orders (GET order by ordId or
clOrdId: history first, then pending), the pending list v2, the order history (newest 100), fills (begin / end
exclusive, newest 100), cancels, trigger orders (resting until the trigger price is crossed, then a market order closes
the position; pending rows with triggerOrderType "Conditional" and cTime in ms; history rows with ordType, triggerTime
and cTime in SECONDS as in the docs' example, errorCode "0" or a failure), trigger cancel.

Unknowns of the real exchange are switches:
- ``two_stops``: whether a second closing trigger order can rest on a coin next to the first (else refused);
- ``stop_price``: "last" or "mark": which price fires a trigger order (the client sends triggerPxType last);
- ``own_fills``: whether a fired trigger's fills carry its own ordId (else a new market order's, no clOrdId);
- ``past_stop``: "trigger" (a trigger already past the price fires at once) or "refuse";
- ``flat_cancels``: whether resting closing triggers are cancelled when their position closes;
- ``order_lag_ms``: an order shows in GET order / the lists only this long after it was made (the docs: a short delay);
- ``fill_lag_ms``: a fill shows this long after it happened;
- ``trigger_lag_ms``: a trigger order shows in the pending list only this long after it was made;
- ``trigger_history_lag_ms``: an ended trigger order shows in the history only this long after it ended (in neither
  list meanwhile);
- ``kill_new_stops``: a trigger order is accepted and cancelled by the exchange right after;
- ``partial``: the next market order fills only that fraction (the rest cancelled);
- ``pnl_net_of_fees``: an order's ``pnl`` net of its fee (the docs do not say);
- ``rate_limit``: (window ms, max requests): beyond it, 429;
- ``unknown_ids``: "empty" (GET order / fills / trigger history for an ordId or clOrdId nobody has: an empty list) or
  "error" (answered code "51603" "Order does not exist": the docs do not say which);
- ``states``: symbol -> instrument state ("live" when absent; suspend / preopen / settlement, the docs' others);
- ``lev_lag_ms``: leverage-info shows the leverage set before a set-leverage until this long after it;
- ``oversize``: "refuse" (the default: a reduce-only market order or a firing trigger order bigger than the position is
  refused as a whole, sCode 31 or the trigger's history row errorCode 31, nothing closed) or "cap" (it closes the
  position); the docs do not say;
- ``history_resting``: the trigger history also lists resting trigger orders (triggerTime 0, errorCode 0): the history
  page's note "triggerTime of 0 indicates the order has not been triggered yet" leaves it open (the drill checks).

Failures are injected per request with ``fail(method, path, kind, times)``: "drop_before" / "drop_after" (TimeoutError
before / after executing), "503_before", "429" or ("429", seconds), "429_after" (executed, then answered 429), "403",
("err", http status, code, msg) and ("scode", sCode, sMsg) (refused, not executed); "403_after" and
("err_after", http status, code, msg) (executed, then answered with that: an order that ran, answered non-zero).
"""

from __future__ import annotations

import base64
import calendar
import hashlib
import hmac
import json
import re
import time
import urllib.parse
from decimal import Decimal

SPECS = {   # test data shaped like GET /deepcoin/market/instruments?instType=SWAP (10-24)
    "BTCUSDT": {"ctVal": "0.001", "lotSz": "1", "minSz": "1", "tickSz": "0.1", "lever": "125", "maxMktSz": "200000"},
    "ETHUSDT": {"ctVal": "0.1", "lotSz": "0.1", "minSz": "0.1", "tickSz": "0.01", "lever": "125", "maxMktSz": "100000"},
    "SOLUSDT": {"ctVal": "1", "lotSz": "0.1", "minSz": "0.1", "tickSz": "0.01", "lever": "75", "maxMktSz": "30000"},
    "DOGEUSDT": {"ctVal": "1", "lotSz": "1", "minSz": "20", "tickSz": "0.00001", "lever": "75", "maxMktSz": "1500000"},
    "LTCUSDT": {"ctVal": "1", "lotSz": "1", "minSz": "1", "tickSz": "0.01", "lever": "75", "maxMktSz": "4000"},
    "BCHUSDT": {"ctVal": "0.1", "lotSz": "1", "minSz": "1", "tickSz": "0.01", "lever": "75", "maxMktSz": "8000"},
}
CLOSING = (("sell", "long"), ("buy", "short"))
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
CID_RE = re.compile(r"^[A-Za-z0-9]{1,20}$")


def inst(s):
    return f"{s[:-4]}-USDT-SWAP"


def sym(inst_id):
    return inst_id.replace("-USDT-SWAP", "USDT")


def iso_to_ms(ts):
    t = time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
    return calendar.timegm(t) * 1000 + int(ts[20:23])


def num(d):
    d = Decimal(str(d))
    return "0" if d == 0 else format(d.normalize(), "f")


class FakeDeepCoin:
    def __init__(self, prices=None, wallet=10_000.0, fee=0.0005, api_key="dk", api_secret="ds", passphrase="dp"):
        self.prices = {s: 100.0 for s in SPECS}
        self.prices.update(prices or {})
        self.marks = dict(self.prices)
        self.wallet, self.fee = wallet, fee
        self.key, self.secret, self.passphrase = api_key, api_secret, passphrase
        self.clock = None
        self.levs = {s: {"isolated": 10, "cross": 10} for s in SPECS}
        self.pos: dict = {}                        # (symbol, posSide) -> position dict (contracts)
        self.orders: dict = {}                     # ordId -> order record (regular orders)
        self.fills: list = []
        self.bills: list = []
        self.triggers: dict = {}                   # ordId -> resting trigger order
        self.trig_hist: dict = {}                  # ordId -> ended trigger order (history row)
        self.bars: dict = {}                       # (symbol, minute ms) -> [o, h, l, c]
        self.mark_bars: dict = {}
        self.calls: list = []
        self.fails: list = []
        self.n = 1000587866000000
        self.two_stops = True
        self.stop_price = "last"
        self.own_fills = False
        self.past_stop = "trigger"
        self.flat_cancels = False
        self.order_lag_ms = 0
        self.fill_lag_ms = 0
        self.trigger_lag_ms = 0
        self.trigger_history_lag_ms = 0
        self.kill_new_stops = False
        self.partial = None
        self.pnl_net_of_fees = False
        self.rate_limit = None
        self.unknown_ids = "empty"
        self.states: dict = {}
        self.lev_lag_ms = 0
        self.lev_was: dict = {}                    # (symbol, mgnMode) -> (leverage before the last set, set at ms)
        self.oversize = "refuse"
        self.history_resting = False
        self.coverage: list = []                   # (call index, symbol, contracts, covered by a closing trigger)
        self.trigger_bodies: list = []
        self.order_bodies: list = []

    # ------------------------------------------------------------ helpers for tests
    def now(self):
        return self.clock() if self.clock else 1_800_000_000_000

    def fail(self, method, path, kind, times=1):
        self.fails.append([method, path, kind, times])

    def _id(self):
        self.n += 7
        return str(self.n)

    def set_price(self, symbol, price, mark=None):
        self.prices[symbol] = price
        self.marks[symbol] = price if mark is None else mark
        m = self.now() // 60_000 * 60_000
        for bars, px in ((self.bars, price), (self.mark_bars, self.marks[symbol])):
            b = bars.get((symbol, m))
            bars[(symbol, m)] = [b[0], max(b[1], px), min(b[2], px), px] if b else [px] * 4
        self._fire_due(symbol)

    def amt(self, symbol):
        """The net position in base units (+ long, - short)."""
        ct = Decimal(SPECS[symbol]["ctVal"])
        out = Decimal(0)
        for ps, sgn in (("long", 1), ("short", -1)):
            p = self.pos.get((symbol, ps))
            if p:
                out += sgn * p["pos"] * ct
        return float(out)

    def live_stops(self, symbol=None):
        return [t for t in self.triggers.values() if (symbol is None or t["instId"] == inst(symbol))
                and (t["side"], t["posSide"]) in CLOSING]

    def add_funding(self, symbol, amount, ms=None):
        """A funding payment: ``amount`` + received (bill type 7, balChg)."""
        self.wallet += amount
        self._bill("7", amount, ms)

    def unprotected(self):
        """Moments a position had no closing trigger covering it, after its first trigger was placed."""
        first = {}
        for i, c in enumerate(self.calls, start=1):
            if c[1] == "POST" and c[2] == "/deepcoin/trade/trigger-order":
                first.setdefault(sym(json.loads(c[4])["instId"]), i)
        return [c for c in self.coverage if c[2] and not c[3] and c[1] in first and c[0] > first[c[1]]]

    # ------------------------------------------------------------ transport
    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        assert u.scheme == "https" and u.hostname == "api.deepcoin.com" and u.port is None, url
        path, query = u.path, u.query
        self.calls.append((self.now(), method, path, query, body))
        private = not path.startswith("/deepcoin/market/")
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
                    return 429, b'{"code":"429","msg":"Too Many Requests"}', {"Retry-After": str(after)}
                if kind == "429_after":                    # it ran; the answer says 429
                    self._route(method, path, query, body)
                    return 429, b'{"code":"429","msg":"Too Many Requests"}', {"Retry-After": "1"}
                if kind == "403":
                    return 403, b"<html>403 Forbidden</html>", {}
                if kind == "403_after":                    # it ran; the answer is a block page
                    self._route(method, path, query, body)
                    return 403, b"<html>403 Forbidden</html>", {}
                if isinstance(kind, tuple) and kind[0] == "err":
                    return kind[1], json.dumps({"code": kind[2], "msg": kind[3], "data": None}).encode(), {}
                if isinstance(kind, tuple) and kind[0] == "err_after":     # it ran; the answer says something else
                    self._route(method, path, query, body)
                    return kind[1], json.dumps({"code": kind[2], "msg": kind[3], "data": None}).encode(), {}
                if isinstance(kind, tuple) and kind[0] == "scode":
                    return self._ok({"ordId": "", "clOrdId": "", "tag": "", "sCode": kind[1], "sMsg": kind[2]})
                if kind == "drop_after":
                    self._route(method, path, query, body)
                    raise TimeoutError("dropped after")
        if self.rate_limit:
            window, most = self.rate_limit
            if len([c for c in self.calls if self.now() - c[0] < window]) > most:
                return 429, b'{"code":"429","msg":"Too Many Requests"}', {"Retry-After": "1"}
        if private:
            bad = self._auth(method, path, query, body, headers)
            if bad is not None:
                return bad
        if body is not None and headers.get("Content-Type") != "application/json":
            return self._code("51", "Content-Type must be application/json")
        out = self._route(method, path, query, body)
        self._note_coverage()
        return out

    def _auth(self, method, path, query, body, h):
        for name, code in (("DC-ACCESS-KEY", "50103"), ("DC-ACCESS-PASSPHRASE", "50104"), ("DC-ACCESS-SIGN", "50106"),
                           ("DC-ACCESS-TIMESTAMP", "50107")):
            if not h.get(name):
                return self._code(code, f"Request header '{name}' can't be empty.", 401)
        ts = h["DC-ACCESS-TIMESTAMP"]
        if not TS_RE.match(ts):
            return self._code("50112", "Invalid DC-ACCESS-TIMESTAMP", 401)
        if abs(iso_to_ms(ts) - self.now()) > 30_000:
            return self._code("50102", "Request timestamp has expired", 401)
        if h["DC-ACCESS-KEY"] != self.key:
            return self._code("50113", "Invalid DC-ACCESS-KEY", 401)
        if h["DC-ACCESS-PASSPHRASE"] != self.passphrase:
            return self._code("50105", "Request header \"DC-ACCESS-PASSPHRASE\" is incorrect", 401)
        target = path + (f"?{query}" if query else "")
        msg = f"{ts}{method}{target}{(body or b'').decode()}".encode()
        want = base64.b64encode(hmac.new(self.secret.encode(), msg, hashlib.sha256).digest()).decode()
        if h["DC-ACCESS-SIGN"] != want:
            return self._code("50111", "Invalid signature", 401)
        return None

    def _note_coverage(self):
        for (s, ps), p in self.pos.items():
            if p["pos"]:
                side = "sell" if ps == "long" else "buy"
                cov = sum(Decimal(t["sz"]) for t in self.live_stops(s) if t["side"] == side and t["posSide"] == ps)
                self.coverage.append((len(self.calls), s, p["pos"], cov >= p["pos"]))

    @staticmethod
    def _ok(data):
        return 200, json.dumps({"code": "0", "msg": "", "data": data}).encode(), {}

    @staticmethod
    def _code(code, msg, status=200):
        return status, json.dumps({"code": code, "msg": msg, "data": None}).encode(), {}

    def _refuse(self, scode, smsg, **extra):
        return self._ok({"ordId": "", "clOrdId": "", "tag": "", "sCode": scode, "sMsg": smsg, **extra})

    def _unknown(self):
        """An id nobody has, answered as an error (``unknown_ids`` "error")."""
        return self._code("51603", "Order does not exist")

    # ------------------------------------------------------------ state
    def _bill(self, typ, chg, ms=None):
        self.bills.append({"billId": self._id(), "ccy": "USDT", "clientId": "", "balChg": f"{chg:.8f}",
                           "bal": f"{self.wallet:.8f}", "type": typ, "ts": str(self.now() if ms is None else ms)})

    def _upnl(self, s, ps):
        p = self.pos.get((s, ps))
        if not p or not p["pos"]:
            return 0.0
        q = float(p["pos"] * Decimal(SPECS[s]["ctVal"]))
        return q * (self.prices[s] - p["avg"]) * (1 if ps == "long" else -1)

    def _margin(self, s, ps):
        p = self.pos.get((s, ps))
        if not p or not p["pos"]:
            return 0.0
        return float(p["pos"] * Decimal(SPECS[s]["ctVal"])) * p["avg"] / p["lever"]

    def _fill(self, order, contracts, px):
        """Fill ``contracts`` of ``order`` at ``px`` on its (coin, posSide) position: open adds, close reduces."""
        s, ps, side = sym(order["instId"]), order["posSide"], order["side"]
        ct = Decimal(SPECS[s]["ctVal"])
        key = (s, ps)
        p = self.pos.get(key)
        closing = (side, ps) in CLOSING
        realized = 0.0
        if closing:
            have = p["pos"] if p else Decimal(0)
            contracts = min(contracts, have)
            if contracts <= 0:
                return Decimal(0), 0.0
            realized = float(contracts * ct) * (px - p["avg"]) * (1 if ps == "long" else -1)
            p["pos"] -= contracts
            p["uTime"] = str(self.now())
            if p["pos"] == 0:
                del self.pos[key]
                if self.flat_cancels:
                    for oid in [o for o, t in self.triggers.items() if t["instId"] == order["instId"]
                                and t["posSide"] == ps and (t["side"], t["posSide"]) in CLOSING]:
                        self._end_trigger(oid, "0")
        else:
            if p is None:
                p = self.pos[key] = {"pos": Decimal(0), "avg": 0.0, "mgnMode": order["tdMode"],
                                     "lever": self.levs[s][order["tdMode"]], "posId": self._id(),
                                     "cTime": str(self.now()), "uTime": str(self.now())}
            q0 = p["pos"]
            p["avg"] = float((q0 * Decimal(repr(p["avg"])) + contracts * Decimal(repr(px))) / (q0 + contracts))
            p["pos"] += contracts
            p["uTime"] = str(self.now())
        fee = float(contracts * ct) * px * self.fee
        self.wallet += realized - fee
        if closing:
            self._bill("1", realized)
        self._bill("5", -fee)
        self.fills.append({"instType": "SWAP", "instId": order["instId"], "tradeId": self._id(),
                           "ordId": order["ordId"], "clOrdId": order.get("clOrdId", ""), "billId": self._id(),
                           "tag": "", "fillPx": repr(px), "fillSz": num(contracts), "side": side, "posSide": ps,
                           "execType": "T", "feeCcy": "USDT", "fee": f"{fee:.8f}", "ts": str(self.now())})
        return contracts, realized - (fee if self.pnl_net_of_fees else 0.0)

    def _new_order(self, q, source=""):
        oid = self._id()
        s = sym(q["instId"])
        o = {"instType": "SWAP", "instId": q["instId"], "tgtCcy": "", "ccy": "", "ordId": oid,
             "clOrdId": q.get("clOrdId", ""), "tag": "", "px": "", "sz": q["sz"], "pnl": "0", "ordType": "market",
             "side": q["side"], "posSide": q["posSide"], "tdMode": q["tdMode"], "accFillSz": "0", "fillPx": "",
             "tradeId": "", "fillSz": "0", "fillTime": "", "avgPx": "", "state": "live",
             "lever": str(self.levs[s][q["tdMode"]]), "tpTriggerPx": "", "tpTriggerPxType": "", "tpOrdPx": "",
             "slTriggerPx": "", "slTriggerPxType": "", "slOrdPx": "", "feeCcy": "USDT", "fee": "0", "rebateCcy": "",
             "source": source, "reduceOnly": "true" if q.get("reduceOnly") else "false", "rebate": "",
             "category": "normal", "uTime": str(self.now()), "cTime": str(self.now())}
        self.orders[oid] = o
        return o

    def _execute(self, o, want, px):
        """A market order: fill ``want`` contracts (or less), then final."""
        s = sym(o["instId"])
        filled, pnl = self._fill(o, want, px) if want > 0 else (Decimal(0), 0.0)
        ct = Decimal(SPECS[s]["ctVal"])
        fee = float(filled * ct) * px * self.fee
        o.update(accFillSz=num(filled), fillSz=num(filled), fillPx=repr(px) if filled else "",
                 avgPx=repr(px) if filled else "", fee=f"{fee:.8f}", pnl=f"{pnl:.8f}",
                 state="filled" if filled == Decimal(o["sz"]) else "canceled", uTime=str(self.now()),
                 fillTime=str(self.now()))
        return filled

    def _history_row(self, t, error, msg, trigger_time):
        """A trigger-history row (cTime / triggerTime in seconds, as in the docs' example)."""
        return {"instType": "SWAP", "instId": t["instId"], "ordId": t["ordId"], "px": "0", "sz": t["sz"],
                "triggerPx": t["triggerPx"], "triggerPxType": t["triggerPxType"], "ordType": "Conditional",
                "side": t["side"], "posSide": t["posSide"], "tdMode": t["tdMode"], "lever": t["lever"],
                "triggerTime": trigger_time, "uTime": str(self.now()), "cTime": str(int(t["cTime"]) // 1000),
                "errorCode": error, "errorMsg": msg}

    def _end_trigger(self, oid, error="0", msg="", fired=False):
        t = self.triggers.pop(oid)
        row = self._history_row(t, error, msg, str(self.now() // 1000) if fired else "0")
        self.trig_hist[oid] = {**row, "_ended": self.now()}

    def _fire_due(self, s):
        for oid, t in sorted(self.triggers.items()):
            if oid not in self.triggers or t["instId"] != inst(s):
                continue
            px = self.prices[s] if t["triggerPxType"] == "last" and self.stop_price == "last" else self.marks[s]
            trig = float(t["triggerPx"])
            if (t["side"] == "sell" and px <= trig) or (t["side"] == "buy" and px >= trig):
                self._fire(oid)

    def _fire(self, oid):
        t = self.triggers[oid]
        s = sym(t["instId"])
        p = self.pos.get((s, t["posSide"]))
        if (t["side"], t["posSide"]) in CLOSING and not (p and p["pos"]):
            self._end_trigger(oid, "31", "NotEnoughPositionToClose:Position=0", fired=True)
            return
        if (t["side"], t["posSide"]) in CLOSING and self.oversize == "refuse" and Decimal(t["sz"]) > p["pos"]:
            self._end_trigger(oid, "31", f"NotEnoughPositionToClose:Position={num(p['pos'])}", fired=True)
            return                                           # refused as a whole: the position stays open
        q = {"instId": t["instId"], "sz": t["sz"], "side": t["side"], "posSide": t["posSide"], "tdMode": t["tdMode"],
             "reduceOnly": (t["side"], t["posSide"]) in CLOSING}
        child = self._new_order(q, source="13")
        if self.own_fills:                                   # the fills carry the trigger's own ordId
            del self.orders[child["ordId"]]
            child["ordId"] = oid
            self.orders[oid] = child
        self._execute(child, Decimal(t["sz"]), self.prices[s])
        self._end_trigger(oid, "0", "", fired=True)

    # ------------------------------------------------------------ routes
    def _route(self, m, path, query, body):
        q = dict(urllib.parse.parse_qsl(query)) if m == "GET" else json.loads(body or b"{}")
        now = self.now()
        if (m, path) == ("GET", "/deepcoin/market/time"):
            return self._ok({"ts": now})
        if (m, path) == ("GET", "/deepcoin/market/instruments"):
            if q.get("instType") != "SWAP":
                return self._code("51", "The instType field is required")
            return self._ok([self._instrument(s) for s in SPECS if not q.get("instId") or q["instId"] == inst(s)]
                            + [{"instType": "SWAP", "instId": "BTC-USD-SWAP", "uly": "BTC-USD", "ctVal": "1",
                                "lotSz": "1", "minSz": "1", "tickSz": "0.1", "lever": "125", "state": "live",
                                "ctType": "inverse", "settleCcy": "BTC", "productGroup": "Swap"}])
        if (m, path) == ("GET", "/deepcoin/market/tickers"):
            rows = [{"instType": "SWAP", "instId": inst(s), "last": repr(self.prices[s]), "lastSz": "",
                     "askPx": repr(self.prices[s]), "askSz": "100", "bidPx": repr(self.prices[s]), "bidSz": "100",
                     "open24h": "1", "high24h": "1", "low24h": "1", "volCcy24h": "1", "vol24h": "1", "sodUtc0": "",
                     "sodUtc8": "", "ts": str(now)} for s in SPECS if not q.get("uly") or q["uly"] == inst(s)[:-5]]
            return self._ok(rows)
        if (m, path) == ("GET", "/deepcoin/market/mark-price"):
            return self._ok([{"instType": "SWAP", "instId": inst(s), "markPx": repr(self.marks[s]), "ts": str(now)}
                             for s in SPECS if not q.get("instId") or q["instId"] == inst(s)])
        if (m, path) in (("GET", "/deepcoin/market/candles"), ("GET", "/deepcoin/market/mark-price-candles")):
            s = sym(q["instId"])
            assert q.get("bar", "1m") == "1m" and 1 <= int(q.get("limit", 100)) <= 1000, q
            bars = self.bars if path.endswith("/candles") else self.mark_bars
            after = int(q["after"]) if q.get("after") else 10 ** 15
            rows = [[str(t), repr(b[0]), repr(b[1]), repr(b[2]), repr(b[3]), "10", "1000"]
                    for (x, t), b in sorted(bars.items(), reverse=True) if x == s and t <= after]
            return self._ok(rows[:int(q.get("limit", 100))])
        # ---- account
        if (m, path) == ("GET", "/deepcoin/account/balances"):
            up = sum(self._upnl(s, ps) for (s, ps) in self.pos)
            mg = sum(self._margin(s, ps) for (s, ps) in self.pos)
            return self._ok([{"ccy": "USDT", "bal": f"{self.wallet:.8f}", "frozenBal": f"{mg:.8f}",
                              "availBal": f"{self.wallet - mg:.8f}", "unrealizedProfit": f"{up:.8f}",
                              "equity": f"{self.wallet + up:.8f}"}])
        if (m, path) == ("GET", "/deepcoin/account/positions"):
            rows = [self._pos_row(s, ps) for (s, ps) in sorted(self.pos)
                    if not q.get("instId") or q["instId"] == inst(s)]
            return self._ok(rows)
        if (m, path) == ("POST", "/deepcoin/account/set-leverage"):
            s = sym(q["instId"])
            assert set(q) == {"instId", "lever", "mgnMode", "mrgPosition"} and isinstance(q["lever"], str), q
            if int(q["lever"]) > int(SPECS[s]["lever"]):
                return self._ok({"instId": "", "lever": "", "mgnMode": "", "mrgPosition": "", "sCode": "199",
                                 "sMsg": f"LeverageTooHigh:Amount[0]>Leverage[{SPECS[s]['lever']}]"})
            self.lev_was[(s, q["mgnMode"])] = (self.levs[s][q["mgnMode"]], now)
            self.levs[s][q["mgnMode"]] = int(q["lever"])
            return self._ok({"instId": q["instId"], "lever": q["lever"], "mgnMode": q["mgnMode"],
                             "mrgPosition": q["mrgPosition"], "sCode": "0", "sMsg": ""})
        if (m, path) == ("GET", "/deepcoin/account/leverage-info"):
            s = sym(q["instId"])
            lev = self.levs[s][q["mgnMode"]]
            was, at = self.lev_was.get((s, q["mgnMode"]), (lev, None))
            if at is not None and now - at < self.lev_lag_ms:          # the read-back has not caught up yet
                lev = was
            return self._ok({"instId": q["instId"], "lever": lev, "mgnMode": q["mgnMode"],
                             "mrgPosition": q["mrgPosition"]})
        if (m, path) == ("GET", "/deepcoin/account/trade-fee"):
            return self._ok([{"level": "Lv1", "feeGroup": "", "category": "", "instType": "SWAP", "maker": "0.0002",
                              "taker": str(self.fee), "makerU": "0.0002", "takerU": str(self.fee), "makerUSDC": "",
                              "takerUSDC": "", "delivery": "", "exercise": "", "ts": str(now)}])
        if (m, path) == ("GET", "/deepcoin/account/bills"):
            rows = sorted(self.bills, key=lambda b: (int(b["ts"]), int(b["billId"])), reverse=True)
            if q.get("before"):
                rows = [b for b in rows if int(b["ts"]) < int(q["before"])]
            if q.get("after"):
                rows = [b for b in rows if int(b["ts"]) > int(q["after"])]
            return self._ok(rows[:int(q.get("limit", 100))])
        # ---- orders
        if (m, path) == ("POST", "/deepcoin/trade/order"):
            return self._place(q)
        if (m, path) == ("GET", "/deepcoin/trade/order"):
            rows = [o for o in self._visible_orders() if o["instId"] == q["instId"]]
            if q.get("ordId"):
                rows = [o for o in rows if o["ordId"] == q["ordId"]]
            elif q.get("clOrdId"):
                rows = [o for o in rows if o["clOrdId"] == q["clOrdId"]]
            else:
                return self._code("51", "ordId or clOrdId is required")
            done = [o for o in rows if o["state"] in ("filled", "canceled")]        # history first, then pending
            got = sorted(done or rows, key=lambda o: int(o["cTime"]))[-1:]
            if not got and self.unknown_ids == "error":
                return self._unknown()
            return self._ok([self._public(o) for o in got])
        if (m, path) == ("GET", "/deepcoin/trade/v2/orders-pending"):
            assert "index" in q, q
            rows = [o for o in self._visible_orders() if o["state"] in ("live", "partially_filled")
                    and (not q.get("instId") or o["instId"] == q["instId"])]
            lim = int(q.get("limit", 30))
            i = int(q["index"])
            return self._ok([self._public(o) for o in rows[(i - 1) * lim:i * lim]])
        if (m, path) == ("GET", "/deepcoin/trade/orders-history"):
            rows = [o for o in self._visible_orders() if o["state"] in ("filled", "canceled")
                    and (not q.get("instId") or o["instId"] == q["instId"])]
            rows.sort(key=lambda o: int(o["ordId"]), reverse=True)
            return self._ok([self._public(o) for o in rows[:int(q.get("limit", 100))]])
        if (m, path) == ("GET", "/deepcoin/trade/fills"):
            rows = [f for f in self.fills if f["instId"] == q.get("instId", f["instId"])
                    and (not q.get("ordId") or f["ordId"] == q["ordId"])
                    and (not q.get("begin") or int(f["ts"]) > int(q["begin"]))
                    and (not q.get("end") or int(f["ts"]) < int(q["end"]))
                    and now - int(f["ts"]) >= self.fill_lag_ms]
            rows.sort(key=lambda f: (int(f["ts"]), int(f["billId"])), reverse=True)
            if q.get("ordId") and self.unknown_ids == "error" and not any(f["ordId"] == q["ordId"] for f in self.fills):
                return self._unknown()
            return self._ok(rows[:int(q.get("limit", 100))])
        if (m, path) == ("POST", "/deepcoin/trade/cancel-order"):
            o = self.orders.get(q.get("ordId"))
            if o is None or o["state"] not in ("live", "partially_filled") or o["instId"] != q["instId"]:
                return self._refuse("24", "OrderNotFound:1")
            o["state"] = "canceled"
            return self._ok({"ordId": o["ordId"], "clOrdId": o["clOrdId"], "sCode": "0", "sMsg": ""})
        # ---- trigger orders
        if (m, path) == ("POST", "/deepcoin/trade/trigger-order"):
            return self._trigger(q)
        if (m, path) == ("GET", "/deepcoin/trade/trigger-orders-pending"):
            assert q.get("instType") == "SWAP" and q.get("instId"), q
            rows = [self._trigger_row(t) for t in self.triggers.values() if t["instId"] == q["instId"]
                    and now - int(t["cTime"]) >= self.trigger_lag_ms]
            return self._ok(rows[:int(q.get("limit", 100))])
        if (m, path) == ("GET", "/deepcoin/trade/trigger-orders-history"):
            assert q.get("instType") == "SWAP" and q.get("instId"), q
            rows = [{k: v for k, v in r.items() if k != "_ended"} for r in self.trig_hist.values()
                    if r["instId"] == q["instId"] and now - r["_ended"] >= self.trigger_history_lag_ms]
            if self.history_resting:                       # resting ones too, "not triggered yet"
                rows += [self._history_row(t, "0", "", "0") for t in self.triggers.values()
                         if t["instId"] == q["instId"]]
            rows = [r for r in rows if not q.get("ordId") or r["ordId"] == q["ordId"]]
            rows.sort(key=lambda r: int(r["uTime"]), reverse=True)
            if q.get("ordId") and not rows and self.unknown_ids == "error":
                return self._unknown()
            return self._ok(rows[:int(q.get("limit", 100))])
        if (m, path) == ("POST", "/deepcoin/trade/cancel-trigger-order"):
            t = self.triggers.get(q.get("ordId"))
            if t is None or t["instId"] != q.get("instId"):
                return self._ok({"ordId": "", "clOrdId": "", "sCode": "1033201232", "sMsg": "Order not found"})
            self._end_trigger(q["ordId"], "0")
            return self._ok({"ordId": q["ordId"], "clOrdId": "", "sCode": "0", "sMsg": ""})
        return self._code("404", "404 page not found", 404)

    def _visible_orders(self):
        return [o for o in self.orders.values() if self.now() - int(o["cTime"]) >= self.order_lag_ms]

    @staticmethod
    def _public(o):
        return dict(o)

    def _instrument(self, s):
        sp = SPECS[s]
        return {"instType": "SWAP", "instId": inst(s), "uly": inst(s)[:-5], "baseCcy": s[:-4], "quoteCcy": "USDT",
                "ctVal": sp["ctVal"], "ctValCcy": s[:-4], "listTime": "0", "lever": sp["lever"], "tickSz": sp["tickSz"],
                "lotSz": sp["lotSz"], "minSz": sp["minSz"], "ctType": "linear", "alias": "",
                "state": self.states.get(s, "live"),
                "maxLmtSz": sp["maxMktSz"], "maxMktSz": sp["maxMktSz"], "settleCcy": "USDT",
                "expTime": "1635148800000", "productGroup": "SwapU", "symbol": s, "assetType": "crypto"}

    def _pos_row(self, s, ps):
        p = self.pos[(s, ps)]
        return {"instType": "SWAP", "mgnMode": p["mgnMode"], "instId": inst(s), "posId": p["posId"], "posSide": ps,
                "pos": num(p["pos"]), "avgPx": repr(p["avg"]), "lever": str(p["lever"]), "liqPx": "0.1",
                "useMargin": f"{self._margin(s, ps):.8f}", "unrealizedProfit": f"{self._upnl(s, ps):.8f}",
                "lastPx": repr(self.prices[s]), "tpTriggerPx": "", "slTriggerPx": "", "mrgPosition": "merge",
                "isLeading": False, "isFollow": False, "ccy": "USDT", "cTime": p["cTime"], "uTime": p["uTime"]}

    def _trigger_row(self, t):
        return {"instType": "SWAP", "instId": t["instId"], "ordId": t["ordId"], "triggerPx": t["triggerPx"],
                "ordPx": "0", "sz": t["sz"], "ordType": "", "side": t["side"], "posSide": t["posSide"],
                "tdMode": t["tdMode"], "triggerOrderType": "Conditional", "triggerPxType": t["triggerPxType"],
                "lever": t["lever"], "slPrice": "", "slTriggerPrice": "", "tpPrice": "", "tpTriggerPrice": "",
                "closeSLTriggerPrice": "", "closeTPTriggerPrice": "", "cTime": t["cTime"], "uTime": t["cTime"]}

    def _check_sz(self, s, sz, opening):
        sp = SPECS[s]
        try:
            d = Decimal(sz)
        except Exception:  # noqa: BLE001
            return "VolumeNotOnTick"
        if d <= 0 or (d / Decimal(sp["lotSz"])) != (d / Decimal(sp["lotSz"])).to_integral_value():
            return "VolumeNotOnTick"
        if opening and d < Decimal(sp["minSz"]):
            return "LessThanMinVolume"
        return None

    def _place(self, q):
        self.order_bodies.append(dict(q))
        for k in ("instId", "tdMode", "side", "ordType", "sz"):
            if not q.get(k):
                return self._code("51", f"The {k} field is required")
        if not q.get("posSide") or not q.get("mrgPosition"):
            return self._code("51", "posSide and mrgPosition are required for SWAP")
        assert q["ordType"] == "market" and "px" not in q and q["mrgPosition"] == "merge", q
        assert isinstance(q["sz"], str) and q["tdMode"] in ("isolated", "cross"), q
        if "clOrdId" in q and not CID_RE.match(str(q["clOrdId"])):
            return self._code("51", "The clOrdId must match ^[A-Za-z0-9]{1,20}$")
        s = sym(q["instId"])
        closing = (q["side"], q["posSide"]) in CLOSING
        if "reduceOnly" in q:
            assert q["reduceOnly"] is True and closing, q
        bad = self._check_sz(s, q["sz"], not closing)
        if bad:
            return self._refuse("44" if bad == "VolumeNotOnTick" else "194", bad)
        if closing:
            p = self.pos.get((s, q["posSide"]))
            if not p or not p["pos"]:
                return self._refuse("31", "NotEnoughPositionToClose:Position=0")
            if self.oversize == "refuse" and Decimal(q["sz"]) > p["pos"]:
                return self._refuse("31", f"NotEnoughPositionToClose:Position={num(p['pos'])}")
        o = self._new_order(q)
        want = Decimal(q["sz"])
        if self.partial is not None:
            lot = Decimal(SPECS[s]["lotSz"])
            want = (want * Decimal(str(self.partial)) / lot).to_integral_value() * lot
            self.partial = None
        self._execute(o, want, self.prices[s])
        return self._ok({"ordId": o["ordId"], "clOrdId": o["clOrdId"], "tag": "", "sCode": "0", "sMsg": ""})

    def _trigger(self, q):
        self.trigger_bodies.append(dict(q))
        for k in ("instId", "productGroup", "sz", "side", "isCrossMargin", "orderType", "triggerPrice", "tdMode"):
            if q.get(k) in (None, ""):
                return self._code("51", f"The {k} field is required")
        assert "clOrdId" not in q and "reduceOnly" not in q, q          # not request fields of Trigger Order
        assert q["productGroup"] == "Swap" and q["orderType"] == "market" and "price" not in q, q
        assert q.get("posSide") in ("long", "short") and q.get("mrgPosition") == "merge", q
        assert q.get("triggerPxType", "last") in ("last", "mark", "index"), q
        assert (q["isCrossMargin"], q["tdMode"]) in (("0", "isolated"), ("1", "cross")), q
        s = sym(q["instId"])
        tick = Decimal(SPECS[s]["tickSz"])
        assert (Decimal(q["triggerPrice"]) / tick) == (Decimal(q["triggerPrice"]) / tick).to_integral_value(), q
        bad = self._check_sz(s, q["sz"], False)
        if bad:
            return self._refuse("44", bad)
        closing = (q["side"], q["posSide"]) in CLOSING
        if closing and not self.two_stops and [t for t in self.live_stops(s) if t["posSide"] == q["posSide"]]:
            return self._refuse("1033200001", "TooManyConditionalOrders")
        px = self.prices[s] if q.get("triggerPxType", "last") == "last" and self.stop_price == "last" \
            else self.marks[s]
        trig = float(q["triggerPrice"])
        past = (q["side"] == "sell" and px <= trig) or (q["side"] == "buy" and px >= trig)
        if past and self.past_stop == "refuse":
            return self._refuse("49", "TriggerPriceInvalid:WouldTriggerImmediately")
        oid = self._id()
        self.triggers[oid] = {"instId": q["instId"], "ordId": oid, "triggerPx": q["triggerPrice"], "sz": q["sz"],
                              "side": q["side"], "posSide": q["posSide"], "tdMode": q["tdMode"],
                              "triggerPxType": q.get("triggerPxType", "last"),
                              "lever": str(self.levs[s][q["tdMode"]]), "cTime": str(self.now())}
        if past:
            self._fire(oid)
        elif self.kill_new_stops:
            self._end_trigger(oid, "0")                    # accepted, then cancelled by the exchange
        return self._ok({"ordId": oid, "clOrdId": "", "tag": "", "sCode": "0", "sMsg": "Success"})
