"""Order handling on the Binance USD-M futures TESTNET (fake money): client, stop protocol, drill.

    TESTNET_API_KEY=... TESTNET_API_SECRET=... python -m paperbot.testnet drill --symbol BTCUSDT
    python -m paperbot.testnet reconcile --symbol BTCUSDT

Why: the paper engine simulates fills. A real bot must also get the exchange side right:
one-way mode, isolated margin, leverage, a market entry, a protective stop that rests ON
THE EXCHANGE (so it still works if the bot dies), moving that stop up for the profit lock
without ever leaving the position unprotected, a clean exit, and a restart check that finds
a position without a stop. The drill runs that cycle with a tiny size and checks every step.

Protective stops (paper v3.1 addendum Q4). Since 2025-12-09 Binance only accepts conditional
orders on the algo endpoints, so a stop is

    POST /fapi/v1/algoOrder  algoType=CONDITIONAL type=STOP_MARKET triggerPrice=<stop>
                             workingType=CONTRACT_PRICE (= last price, like the paper engine)
                             priceProtect=false  quantity=<position> reduceOnly=true

and is read with GET /fapi/v1/algoOrder (algoId or clientAlgoId), listed with
GET /fapi/v1/openAlgoOrders, cancelled with DELETE /fapi/v1/algoOrder and
DELETE /fapi/v1/algoOpenOrders. Parameter names were checked against Binance's official
Python SDK (binance-connector-python, derivatives_trading_usds_futures, 2026-09); what the
first testnet drill must still confirm is listed in docs/live-safety.md.

Stops use ``quantity`` + ``reduceOnly`` rather than ``closePosition``: moving a stop places the
new one BEFORE cancelling the old one, so for a moment two stops on the same side exist, and a
second closePosition stop on the same side is refused by Binance (-4130). ``closePosition`` is
still available (``qty=None``) for a one-off manual stop.

Moving a stop (``move_stop``): place the new stop -> confirm it is live -> cancel the old one.
If the new stop is refused with -2021 ("Order would immediately trigger": the price is already
past it), close the position with a reduce-only market order.

Safety:
- ``TestnetClient`` refuses any host except the futures testnet (a class-level allowlist).
  paperbot/mainnet.py subclasses it for fapi.binance.com behind its own gates (env flag, separate
  key variables, key-permission check, balance guard); the order code here is shared.
- Testnet keys live in their own variables (TESTNET_API_KEY / TESTNET_API_SECRET), never the
  read-only mainnet key used by the paper runner.
- AI agents do not call this module; people run it by hand, and paperbot/executor.py uses it.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

TESTNET = "https://testnet.binancefuture.com"
ALLOWED_HOSTS = ("testnet.binancefuture.com",)

WOULD_TRIGGER = -2021          # "Order would immediately trigger."
BAD_TIMESTAMP = -1021          # "Timestamp for this request is outside of the recvWindow." (clock drift)
NOT_FOUND = (-2013, -2011)     # "Order does not exist." / "Unknown order sent."
_TRANSIENT_CODES = (-1001, -1007, -1008)   # disconnected / backend timeout (status unknown) / overloaded
_RATE_CODES = (-1003,)                     # too many requests
OPEN_ALGO = ("NEW",)                       # an algo order that is resting and can still trigger
FIRED_ALGO = ("TRIGGERING", "TRIGGERED", "FINISHED")

# send(method, url, headers, body) -> (status, body bytes) or (status, body bytes, headers)
Send = Callable[[str, str, dict, Optional[bytes]], tuple]


class TestnetError(Exception):
    """The exchange refused the request (4xx): never retried blindly."""
    __test__ = False  # not a pytest test class

    def __init__(self, status: int, code: Optional[int], msg: str):
        super().__init__(f"HTTP {status} code {code}: {msg}")
        self.status, self.code, self.msg = status, code, msg


class TransientError(TestnetError):
    """Network failure, timeout or 5xx. For an order the outcome is UNKNOWN: look it up by its
    client id before sending it again."""


class UnknownOutcome(TransientError):
    """An order was sent, its answer was lost, and the look-up by client id could not tell whether it is on
    the exchange. Opening orders are then never sent again (a second fill would double the position): the
    executor's reconcile settles it from the position."""


class RateLimited(TestnetError):
    """429 (slow down) or 418 (IP banned for a while). ``retry_after`` in seconds."""

    def __init__(self, status: int, code: Optional[int], msg: str, retry_after: float = 0.0):
        super().__init__(status, code, msg)
        self.retry_after = retry_after


class ProtectionError(Exception):
    """A protective stop could not be confirmed live."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect. The host allowlist is checked on the base address only, and urllib would carry
    the X-MBX-APIKEY header and the signed query to whatever host (or plain http) a 3xx names. A 3xx is
    answered as an error instead (TestnetError with that status)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _build_opener(*extra) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect, *extra)


_OPENER = _build_opener()


def urllib_send(method: str, url: str, headers: dict, body: Optional[bytes]) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers.items())
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers.items()) if e.headers else {}


def _round_down(x: float, step: float) -> float:
    return round(math.floor(x / step + 1e-9) * step, 12)


def _round_to(x: float, step: float) -> float:
    return round(round(x / step) * step, 12)


def round_stop(price: float, tick: float, side: int) -> float:
    """Round a protective stop to the tick, never looser than asked: up for a long, down for a short."""
    n = price / tick
    n = math.ceil(n - 1e-9) if side > 0 else math.floor(n + 1e-9)
    return round(n * tick, 12)


def algo_type(o: dict) -> str:
    return o.get("orderType") or o.get("type") or ""


def is_stop(o: dict) -> bool:
    return algo_type(o) == "STOP_MARKET"


def _truthy(v) -> bool:
    return v is True or str(v).lower() == "true"


def covers(stop: dict, amt: float, eps: float = 1e-12) -> bool:
    """Does this resting stop close the whole position ``amt`` (signed)?"""
    if amt == 0 or not is_stop(stop) or stop.get("algoStatus", "NEW") not in OPEN_ALGO:
        return False
    if stop.get("side") != ("SELL" if amt > 0 else "BUY"):
        return False
    return _truthy(stop.get("closePosition")) or float(stop.get("quantity") or 0) >= abs(amt) - eps


class TestnetClient:
    """Signed REST client for Binance USD-M futures. This class talks to the TESTNET only.

    The host allowlist is a CLASS attribute (``HOSTS``), checked at construction; the executor checks the
    host again before it starts. paperbot/mainnet.py subclasses it for fapi.binance.com (the same code
    path, another allowlist, other key variables, more guards)."""
    __test__ = False
    HOSTS: tuple = ALLOWED_HOSTS
    DEFAULT_BASE = TESTNET
    KEY_NAMES = ("TESTNET_API_KEY", "TESTNET_API_SECRET")
    AGENT = "paperbot-testnet/0.3"

    def __init__(self, api_key: str, api_secret: str, base: Optional[str] = None, send: Optional[Send] = None,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                 on_request: Optional[Callable[[dict], None]] = None):
        base = base or self.DEFAULT_BASE
        host = urllib.parse.urlparse(base).hostname or ""
        if host not in type(self).HOSTS:
            raise ValueError(f"refusing host {host!r}: {type(self).__name__} only talks to {type(self).HOSTS}")
        if not (api_key and api_secret):
            raise ValueError(f"{self.KEY_NAMES[0]} and {self.KEY_NAMES[1]} are required")
        self.base, self.key, self.secret = base.rstrip("/"), api_key, api_secret
        self.host = host
        self.send = send or urllib_send
        self.clock_ms = clock_ms
        self.offset_ms = 0                 # server time - local time (sync_time)
        self.on_request = on_request       # audit hook: every request with its outcome
        self.limits = {"weight_1m": 2400, "orders_1m": 1200, "orders_10s": 300}
        self.used = {"weight_1m": 0, "orders_1m": 0, "orders_10s": 0}

    # ------------------------------------------------------------ transport
    def _note(self, headers: dict) -> None:
        h = {k.lower(): v for k, v in (headers or {}).items()}
        for key, name in (("weight_1m", "x-mbx-used-weight-1m"), ("orders_1m", "x-mbx-order-count-1m"),
                          ("orders_10s", "x-mbx-order-count-10s")):
            if name in h:
                try:
                    self.used[key] = int(h[name])
                except ValueError:
                    pass

    def throttle_s(self, share: float = 0.8) -> float:
        """Seconds to wait before the next request so we stay under ``share`` of each limit."""
        now = (self.clock_ms() + self.offset_ms) / 1000.0
        wait = 0.0
        if self.used["orders_10s"] >= share * self.limits["orders_10s"]:
            wait = max(wait, 10 - now % 10)
        if self.used["weight_1m"] >= share * self.limits["weight_1m"] or \
                self.used["orders_1m"] >= share * self.limits["orders_1m"]:
            wait = max(wait, 60 - now % 60)
        return wait

    def req(self, method: str, path: str, params: Optional[dict] = None, signed: bool = True):
        p = {k: v for k, v in (params or {}).items() if v is not None}
        audit = {"method": method, "path": path, "params": dict(p)}
        headers = {"User-Agent": self.AGENT, "X-MBX-APIKEY": self.key}
        if signed:
            p["timestamp"] = self.clock_ms() + self.offset_ms
            p["recvWindow"] = 5000
        q = urllib.parse.urlencode(p)
        if signed:
            q += "&signature=" + hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        try:
            if method in ("GET", "DELETE"):
                res = self.send(method, f"{self.base}{path}?{q}", headers, None)
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                res = self.send(method, f"{self.base}{path}", headers, q.encode())
        except (OSError, http.client.HTTPException) as e:
            # timeouts, refused connections, DNS, TLS, and a connection cut in the middle of the answer
            # (IncompleteRead, BadStatusLine: not OSError): the outcome is unknown
            err = TransientError(0, None, f"network: {type(e).__name__}: {e}")
            self._audit(audit, err=err)
            raise err from e
        status, body = res[0], res[1]
        self._note(res[2] if len(res) > 2 else {})
        parsed = True
        try:
            data = json.loads(body) if body else None
            parsed = bool(body)
        except ValueError:
            data, parsed = None, False
        code = data.get("code") if isinstance(data, dict) else None
        msg = data.get("msg") if isinstance(data, dict) else str((body or b"")[:200])
        if isinstance(code, str) and code.lstrip("-").isdigit():
            code = int(code)
        err: Optional[TestnetError] = None
        if status in (429, 418) or code in _RATE_CODES:
            hdr = {k.lower(): v for k, v in (res[2] if len(res) > 2 else {}).items()}
            try:
                after = float(hdr.get("retry-after", 0) or 0)
            except ValueError:
                after = 0.0
            err = RateLimited(status, code, msg or "rate limited", after)
        elif status >= 500 or status in (0, 408) or code in _TRANSIENT_CODES:
            err = TransientError(status, code, msg or "server error")
        elif status == 200 and not parsed:
            # a 200 whose body is empty or not JSON (a proxy or maintenance page): nothing was confirmed
            err = TransientError(status, None, f"응답이 JSON이 아닙니다: {msg}"[:200])
        elif status != 200:
            err = TestnetError(status, code, msg)
        self._audit(audit, status=status, data=data, err=err)
        if err is not None:
            raise err
        return data

    def _audit(self, audit: dict, status: int = 0, data=None, err: Optional[Exception] = None) -> None:
        if self.on_request is None:
            return
        audit.update(status=getattr(err, "status", status), error=None if err is None else str(err),
                     code=getattr(err, "code", None), data=data)
        try:
            self.on_request(audit)
        except Exception:  # noqa: BLE001  (an audit failure must not change order handling)
            pass

    # ------------------------------------------------------------ market data / account
    def sync_time(self) -> int:
        server = int(self.req("GET", "/fapi/v1/time", signed=False)["serverTime"])
        self.offset_ms = server - self.clock_ms()
        return self.offset_ms

    def spec(self, symbol: str) -> dict:
        info = self.req("GET", "/fapi/v1/exchangeInfo", signed=False)
        for rl in info.get("rateLimits", []) or []:
            key = {("REQUEST_WEIGHT", "MINUTE", 1): "weight_1m", ("ORDERS", "MINUTE", 1): "orders_1m",
                   ("ORDERS", "SECOND", 10): "orders_10s"}.get(
                (rl.get("rateLimitType"), rl.get("interval"), rl.get("intervalNum")))
            if key:
                self.limits[key] = int(rl["limit"])
        s = next(x for x in info["symbols"] if x["symbol"] == symbol)
        f = {x["filterType"]: x for x in s["filters"]}
        return {"qty_step": float(f["MARKET_LOT_SIZE"]["stepSize"]), "min_qty": float(f["MARKET_LOT_SIZE"]["minQty"]),
                "tick": float(f["PRICE_FILTER"]["tickSize"]),
                "min_notional": float(f.get("MIN_NOTIONAL", {}).get("notional", 0.0))}

    def mark(self, symbol: str) -> float:
        return float(self.req("GET", "/fapi/v1/premiumIndex", {"symbol": symbol}, signed=False)["markPrice"])

    def price(self, symbol: str) -> float:
        """Last traded price: what a CONTRACT_PRICE stop triggers on."""
        return float(self.req("GET", "/fapi/v1/ticker/price", {"symbol": symbol}, signed=False)["price"])

    def account(self) -> dict:
        return self.req("GET", "/fapi/v2/account")

    def one_way(self) -> None:
        try:
            self.req("POST", "/fapi/v1/positionSide/dual", {"dualSidePosition": "false"})
        except TestnetError as e:
            if e.code != -4059:        # "No need to change position side."
                raise

    def isolated(self, symbol: str) -> None:
        try:
            self.req("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"})
        except TestnetError as e:
            if e.code != -4046:        # "No need to change margin type."
                raise

    def leverage(self, symbol: str, lev: int) -> dict:
        return self.req("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": lev})

    # ------------------------------------------------------------ regular orders
    def market(self, symbol: str, side: str, qty: float, reduce_only: bool = False,
               client_id: Optional[str] = None) -> dict:
        return self.req("POST", "/fapi/v1/order", {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty,
                                                   "reduceOnly": "true" if reduce_only else None,
                                                   "newClientOrderId": client_id, "newOrderRespType": "RESULT"})

    def order(self, symbol: str, order_id: Optional[int] = None, client_id: Optional[str] = None) -> dict:
        return self.req("GET", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id,
                                                  "origClientOrderId": client_id})

    def cancel(self, symbol: str, order_id: int) -> dict:
        return self.req("DELETE", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id})

    def cancel_all(self, symbol: str) -> dict:
        return self.req("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol})

    def open_orders(self, symbol: str) -> list:
        return self.req("GET", "/fapi/v1/openOrders", {"symbol": symbol})

    # ------------------------------------------------------------ algo (conditional) orders
    def stop_close(self, symbol: str, side: str, trigger: float, qty: Optional[float] = None,
                   client_id: Optional[str] = None) -> dict:
        """Protective STOP_MARKET resting on the exchange, triggered by the LAST price.
        With ``qty``: reduce-only for that quantity (two can coexist while a stop is moved).
        Without: closePosition (closes whatever is open; one per side)."""
        p = {"algoType": "CONDITIONAL", "symbol": symbol, "side": side, "type": "STOP_MARKET",
             "triggerPrice": trigger, "workingType": "CONTRACT_PRICE", "priceProtect": "false",
             "clientAlgoId": client_id}
        if qty is None:
            p["closePosition"] = "true"
        else:
            p["quantity"], p["reduceOnly"] = qty, "true"
        return self.req("POST", "/fapi/v1/algoOrder", p)

    def algo_order(self, algo_id: Optional[int] = None, client_id: Optional[str] = None) -> dict:
        return self.req("GET", "/fapi/v1/algoOrder", {"algoId": algo_id, "clientAlgoId": client_id})

    def cancel_algo(self, algo_id: Optional[int] = None, client_id: Optional[str] = None) -> dict:
        return self.req("DELETE", "/fapi/v1/algoOrder", {"algoId": algo_id, "clientAlgoId": client_id})

    def open_algo_orders(self, symbol: str) -> list:
        return self.req("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol})

    def cancel_all_algo(self, symbol: str) -> dict:
        return self.req("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": symbol})

    # ------------------------------------------------------------ positions
    def position(self, symbol: str) -> dict:
        rows = self.req("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
        return next((r for r in rows if r["symbol"] == symbol), {"symbol": symbol, "positionAmt": "0"})

    def positions(self) -> list:
        """Every symbol with a non-zero position."""
        return [r for r in self.req("GET", "/fapi/v2/positionRisk") if float(r.get("positionAmt") or 0) != 0]

    # ------------------------------------------------------------ fills, income, brackets (USER_DATA reads)
    def user_trades(self, symbol: str, start_ms: int, end_ms: int, limit: int = 1000) -> list:
        """Account fills: price, qty, realizedPnl, commission, commissionAsset, orderId, side, time.
        startTime..endTime may span at most 7 days (Binance)."""
        return self.req("GET", "/fapi/v1/userTrades", {"symbol": symbol, "startTime": int(start_ms),
                                                       "endTime": int(end_ms), "limit": limit})

    def income(self, symbol: Optional[str], income_type: Optional[str], start_ms: int, end_ms: int,
               limit: int = 1000) -> list:
        """Income history (FUNDING_FEE, COMMISSION, REALIZED_PNL, ...): symbol, incomeType, income, asset, time,
        tranId."""
        return self.req("GET", "/fapi/v1/income", {"symbol": symbol, "incomeType": income_type,
                                                   "startTime": int(start_ms), "endTime": int(end_ms),
                                                   "limit": limit})

    def leverage_brackets(self) -> list:
        return self.req("GET", "/fapi/v1/leverageBracket")


# ---------------------------------------------------------------- stop protocol (drill and executor)
def live_stops(c, symbol: str) -> list:
    return [o for o in c.open_algo_orders(symbol) if is_stop(o) and o.get("algoStatus", "NEW") in OPEN_ALGO]


def place_stop(c, symbol: str, close_side: str, trigger: float, qty: Optional[float],
               client_id: Optional[str] = None) -> dict:
    """Place a protective stop and confirm it is resting. Raises TestnetError (e.g. -2021) when
    refused, ProtectionError when it was accepted but is not live."""
    o = c.stop_close(symbol, close_side, trigger, qty=qty, client_id=client_id)
    algo_id = o.get("algoId")
    try:
        got = c.algo_order(algo_id=algo_id) if algo_id is not None else c.algo_order(client_id=client_id)
    except TestnetError as e:
        # the algo service answered the POST but cannot find the order a moment later (read-after-write lag):
        # look in the open list, else trust the POST answer; the reconcile reads the open list every loop
        if e.code not in NOT_FOUND:
            raise
        got = next((x for x in c.open_algo_orders(symbol)
                    if (algo_id is not None and x.get("algoId") == algo_id)
                    or (algo_id is None and client_id and x.get("clientAlgoId") == client_id)), None) or o
    status = got.get("algoStatus")
    if status in FIRED_ALGO:
        return {**got, "fired": True}
    if status not in OPEN_ALGO:
        raise ProtectionError(f"stop {got.get('algoId')} is {status}, not live")
    return got


def close_market(c, symbol: str, client_id: Optional[str] = None) -> Optional[dict]:
    """Reduce-only market order for the whole position (None when already flat)."""
    amt = float(c.position(symbol)["positionAmt"])
    if amt == 0:
        return None
    return c.market(symbol, "SELL" if amt > 0 else "BUY", abs(amt), reduce_only=True, client_id=client_id)


def cancel_stops(c, symbol: str, algo_ids) -> list:
    done = []
    for aid in algo_ids:
        try:
            c.cancel_algo(algo_id=aid)
        except TestnetError as e:
            if e.code not in NOT_FOUND:
                raise
        done.append(aid)
    return done


def move_stop(c, symbol: str, close_side: str, trigger: float, qty: Optional[float], old_ids,
              client_id: Optional[str] = None, close_id: Optional[str] = None) -> dict:
    """Move a protective stop without a gap: new stop -> confirmed live -> cancel the old ones.

    result "moved":     the new stop rests, the old ones are cancelled (``left``: old ones whose cancel failed;
                        the position is protected by the new stop, the next reconcile cancels the rest)
    result "closed":    the exchange refused the new stop with -2021 (price already past it), so the
                        position was closed with a reduce-only market order and, once that close filled the
                        whole position, the old stops cancelled (``flat``). A close that filled only part keeps
                        the old stops: they are reduce-only and still cover the rest.
    result "triggered": the new stop fired at once; the old ones are left for the next reconcile
    Any other refusal of the new stop raises, and the old stop is still in place (still protected)."""
    try:
        new = place_stop(c, symbol, close_side, trigger, qty, client_id)
    except TestnetError as e:
        if e.code != WOULD_TRIGGER:
            raise
        amt = float(c.position(symbol)["positionAmt"])
        x = None if amt == 0 else c.market(symbol, "SELL" if amt > 0 else "BUY", abs(amt), reduce_only=True,
                                           client_id=close_id)
        flat = amt == 0 or float((x or {}).get("executedQty") or 0) >= abs(amt) - 1e-12
        cancelled = cancel_stops(c, symbol, old_ids) if flat else []
        return {"result": "closed", "close": x, "cancelled": cancelled, "error": e.msg, "flat": flat}
    if new.get("fired"):
        return {"result": "triggered", "stop": new, "cancelled": []}
    cancelled, left = [], []
    for a in [a for a in old_ids if a != new.get("algoId")]:
        try:                                   # the new stop is live: a failed cancel must not undo the move
            cancelled += cancel_stops(c, symbol, [a])
        except TestnetError:
            left.append(a)
    return {"result": "moved", "stop": new, "cancelled": cancelled, "left": left}


def cancel_everything(c, symbol: str) -> None:
    c.cancel_all_algo(symbol)
    c.cancel_all(symbol)


def hide_process_memory() -> bool:
    """prctl(PR_SET_DUMPABLE, 0): from here on, other processes of the same user (the agent rooms, the dashboard,
    anything else running as paperbot) can no longer read this process's /proc/<pid>/environ (the order keys
    systemd passed in), its memory or its /proc/<pid>/root. Called first by ``python -m paperbot.executor`` and
    ``python -m paperbot.testnet``. Linux only; False when it could not be set."""
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(4, 0, 0, 0, 0) == 0          # 4 = PR_SET_DUMPABLE
    except (OSError, AttributeError):
        return False


# ---------------------------------------------------------------- drill
@dataclass
class Drill:
    client: TestnetClient
    symbol: str
    side: int = 1                   # 1 long, -1 short
    notional: float = 200.0         # USDT, tiny on purpose
    leverage: int = 20
    stop_frac: float = 0.01         # first stop 1% away
    wait: Callable[[float], None] = time.sleep
    log: list = field(default_factory=list)

    def _step(self, name: str, ok: bool, detail) -> None:
        self.log.append({"step": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    def _stops(self) -> list:
        return live_stops(self.client, self.symbol)

    def run(self) -> list:
        c, s = self.client, self.symbol
        buy, sell = ("BUY", "SELL") if self.side > 0 else ("SELL", "BUY")
        spec = c.spec(s)
        self._step("clean start", float(c.position(s)["positionAmt"]) == 0 and not c.open_orders(s)
                   and not c.open_algo_orders(s),
                   "position must be flat and no open (or algo) orders before the drill")
        c.one_way()
        c.isolated(s)
        lev = c.leverage(s, self.leverage)
        self._step("leverage", int(lev["leverage"]) == self.leverage, lev)
        mark = c.mark(s)
        qty = max(_round_down(self.notional / mark, spec["qty_step"]), spec["min_qty"])
        o = c.market(s, buy, qty)
        for _ in range(20):
            if o.get("status") == "FILLED":
                break
            self.wait(0.5)
            o = c.order(s, o["orderId"])
        self._step("entry filled", o.get("status") == "FILLED", {"status": o.get("status"), "avg": o.get("avgPrice")})
        entry = float(o["avgPrice"])
        amt = float(c.position(s)["positionAmt"])
        self._step("position size", abs(amt - self.side * qty) < spec["qty_step"] / 2, {"positionAmt": amt, "qty": qty})
        stop1 = round_stop(entry * (1 - self.side * self.stop_frac), spec["tick"], self.side)
        st1 = place_stop(c, s, sell, stop1, abs(amt))
        stops = self._stops()
        self._step("stop rests on exchange (algo, last price)",
                   len(stops) == 1 and float(stops[0]["triggerPrice"]) == stop1
                   and stops[0].get("workingType", "CONTRACT_PRICE") == "CONTRACT_PRICE",
                   [(x["algoId"], x["triggerPrice"], x.get("workingType")) for x in stops])
        # profit lock: new stop first, confirm it, then cancel the old one -> never unprotected
        stop2 = round_stop(entry * (1 - self.side * self.stop_frac / 2), spec["tick"], self.side)
        seen = {}
        orig = c.cancel_algo

        def watch_cancel(algo_id=None, client_id=None):
            seen.setdefault("during", len(self._stops()))
            return orig(algo_id=algo_id, client_id=client_id)
        c.cancel_algo = watch_cancel
        try:
            mv = move_stop(c, s, sell, stop2, abs(amt), [st1["algoId"]])
        finally:
            c.cancel_algo = orig
        stops = self._stops()
        self._step("stop moved without a gap",
                   mv["result"] == "moved" and seen.get("during") == 2 and len(stops) == 1
                   and stops[0]["algoId"] == mv["stop"]["algoId"],
                   {"during": seen.get("during"), "after": [(x["algoId"], x["triggerPrice"]) for x in stops]})
        # restart check: drop the stop, reconcile must notice and restore it
        c.cancel_algo(algo_id=mv["stop"]["algoId"])
        rep = reconcile(c, s, stop_price=stop2)
        self._step("restart check restores a missing stop", rep["repaired"] and len(self._stops()) == 1, rep)
        # exit through the -2021 path: a stop on the wrong side of the price must be refused
        # and the position closed with a reduce-only market order
        last = c.price(s)
        bad = round_stop(last * (1 + self.side * 0.02), spec["tick"], self.side)
        mv = move_stop(c, s, sell, bad, abs(amt), [x["algoId"] for x in self._stops()])
        self._step("stop past the price is refused (-2021) and the position closed at market",
                   mv["result"] == "closed", {k: mv.get(k) for k in ("result", "error")})
        cancel_everything(c, s)
        self._step("flat and no orders left",
                   float(c.position(s)["positionAmt"]) == 0 and not c.open_orders(s) and not c.open_algo_orders(s),
                   {"positionAmt": c.position(s)["positionAmt"], "orders": len(c.open_orders(s)),
                    "algo_orders": len(c.open_algo_orders(s))})
        return self.log


def reconcile(c: TestnetClient, symbol: str, stop_price: Optional[float] = None) -> dict:
    """After a restart: a position without a protective stop is the one state that must never
    last. Report it and, when the intended stop is known, put it back."""
    amt = float(c.position(symbol)["positionAmt"])
    stops = live_stops(c, symbol)
    covering = [o for o in stops if covers(o, amt)]
    out = {"position": amt, "stops": len(stops), "repaired": False, "problem": None}
    if amt != 0 and not covering:
        out["problem"] = "position without a protective stop" if not stops else "stop smaller than the position"
        if stop_price is not None:
            place_stop(c, symbol, "SELL" if amt > 0 else "BUY", stop_price, abs(amt))
            out["repaired"] = True
    elif amt == 0 and stops:
        out["problem"] = "stop orders without a position"
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["drill", "reconcile"])
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--side", choices=["long", "short"], default="long")
    ap.add_argument("--notional", type=float, default=200.0)
    ap.add_argument("--leverage", type=int, default=20)
    args = ap.parse_args(argv)
    from .mainnet import PAPER_ENV_FILE, Refused, read_env_file, trading_keys
    try:          # never the paper runner's read-only key, never a mainnet key
        key, secret = trading_keys("testnet", os.environ, read_env_file(PAPER_ENV_FILE))
    except Refused as e:
        print(f"시작하지 않습니다: {e}", file=sys.stderr)
        return 2
    c = TestnetClient(key, secret)
    c.sync_time()
    if args.cmd == "reconcile":
        print(json.dumps(reconcile(c, args.symbol), indent=1))
        return 0
    d = Drill(c, args.symbol, 1 if args.side == "long" else -1, args.notional, args.leverage)
    try:
        d.run()
        ok = True
    except (AssertionError, TestnetError, ProtectionError) as e:
        d.log.append({"step": "stopped", "ok": False, "detail": str(e)})
        ok = False
        try:                              # leave the testnet account flat
            close_market(c, args.symbol)
            cancel_everything(c, args.symbol)
        except TestnetError:
            pass
    for row in d.log:
        print(("[OK]  " if row["ok"] else "[FAIL]") + f" {row['step']}: {row['detail']}")
    return 0 if ok else 1


if __name__ == "__main__":
    hide_process_memory()
    sys.exit(main())
