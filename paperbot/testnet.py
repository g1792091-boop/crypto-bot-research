"""Order-handling drill on the Binance USD-M futures TESTNET (fake money).

    TESTNET_API_KEY=... TESTNET_API_SECRET=... python -m paperbot.testnet drill --symbol BTCUSDT
    python -m paperbot.testnet reconcile --symbol BTCUSDT

Why: the paper engine simulates fills. A real bot must also get the exchange side right:
one-way mode, isolated margin, leverage, a market entry, a protective stop that rests ON
THE EXCHANGE (so it still works if the bot dies), moving that stop up for the profit lock
without ever leaving the position unprotected, a clean exit, and a restart check that finds
a position without a stop. The drill runs that cycle with a tiny size and checks every step.

Safety:
- The client refuses any host except the futures testnet. There is no mainnet code path.
- Testnet keys live in their own variables (TESTNET_API_KEY / TESTNET_API_SECRET), never the
  read-only mainnet key used by the paper runner.
- Agents do not call this module; people run it by hand (live-readiness checks).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
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

# send(method, url, headers, body) -> (status, body bytes)
Send = Callable[[str, str, dict, Optional[bytes]], tuple[int, bytes]]


class TestnetError(Exception):
    __test__ = False  # not a pytest test class

    def __init__(self, status: int, code: Optional[int], msg: str):
        super().__init__(f"HTTP {status} code {code}: {msg}")
        self.status, self.code, self.msg = status, code, msg


def urllib_send(method: str, url: str, headers: dict, body: Optional[bytes]) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _round_down(x: float, step: float) -> float:
    return math.floor(x / step + 1e-9) * step


def _round_to(x: float, step: float) -> float:
    return round(round(x / step) * step, 12)


class TestnetClient:
    __test__ = False

    def __init__(self, api_key: str, api_secret: str, base: str = TESTNET, send: Optional[Send] = None,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000)):
        host = urllib.parse.urlparse(base).hostname or ""
        if host not in ALLOWED_HOSTS:
            raise ValueError(f"refusing host {host!r}: this module only talks to the futures testnet")
        if not (api_key and api_secret):
            raise ValueError("TESTNET_API_KEY and TESTNET_API_SECRET are required")
        self.base, self.key, self.secret = base.rstrip("/"), api_key, api_secret
        self.send = send or urllib_send
        self.clock_ms = clock_ms

    def req(self, method: str, path: str, params: Optional[dict] = None, signed: bool = True):
        p = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {"User-Agent": "paperbot-testnet/0.1", "X-MBX-APIKEY": self.key}
        if signed:
            p["timestamp"] = self.clock_ms()
            p["recvWindow"] = 5000
        q = urllib.parse.urlencode(p)
        if signed:
            q += "&signature=" + hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        if method == "GET" or method == "DELETE":
            status, body = self.send(method, f"{self.base}{path}?{q}", headers, None)
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            status, body = self.send(method, f"{self.base}{path}", headers, q.encode())
        data = json.loads(body or b"null")
        if status != 200:
            code = data.get("code") if isinstance(data, dict) else None
            msg = data.get("msg") if isinstance(data, dict) else str(body[:200])
            raise TestnetError(status, code, msg)
        return data

    # ------------------------------------------------------------ endpoints
    def spec(self, symbol: str) -> dict:
        info = self.req("GET", "/fapi/v1/exchangeInfo", signed=False)
        s = next(x for x in info["symbols"] if x["symbol"] == symbol)
        f = {x["filterType"]: x for x in s["filters"]}
        return {"qty_step": float(f["MARKET_LOT_SIZE"]["stepSize"]), "min_qty": float(f["MARKET_LOT_SIZE"]["minQty"]),
                "tick": float(f["PRICE_FILTER"]["tickSize"]),
                "min_notional": float(f.get("MIN_NOTIONAL", {}).get("notional", 0.0))}

    def mark(self, symbol: str) -> float:
        return float(self.req("GET", "/fapi/v1/premiumIndex", {"symbol": symbol}, signed=False)["markPrice"])

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

    def market(self, symbol: str, side: str, qty: float, reduce_only: bool = False) -> dict:
        return self.req("POST", "/fapi/v1/order", {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty,
                                                   "reduceOnly": "true" if reduce_only else None,
                                                   "newOrderRespType": "RESULT"})

    def stop_close(self, symbol: str, side: str, stop: float) -> dict:
        """Protective stop-market for the whole position, triggered by MARK price, resting on the exchange."""
        return self.req("POST", "/fapi/v1/order", {"symbol": symbol, "side": side, "type": "STOP_MARKET",
                                                   "stopPrice": stop, "closePosition": "true",
                                                   "workingType": "MARK_PRICE", "priceProtect": "true"})

    def order(self, symbol: str, order_id: int) -> dict:
        return self.req("GET", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id})

    def cancel(self, symbol: str, order_id: int) -> dict:
        return self.req("DELETE", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id})

    def cancel_all(self, symbol: str) -> dict:
        return self.req("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol})

    def open_orders(self, symbol: str) -> list:
        return self.req("GET", "/fapi/v1/openOrders", {"symbol": symbol})

    def position(self, symbol: str) -> dict:
        rows = self.req("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
        return next((r for r in rows if r["symbol"] == symbol), {"positionAmt": "0"})


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
        return [o for o in self.client.open_orders(self.symbol) if o["type"] == "STOP_MARKET"]

    def run(self) -> list:
        c, s = self.client, self.symbol
        buy, sell = ("BUY", "SELL") if self.side > 0 else ("SELL", "BUY")
        spec = c.spec(s)
        self._step("clean start", float(c.position(s)["positionAmt"]) == 0 and not c.open_orders(s),
                   "position must be flat and no open orders before the drill")
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
        stop1 = _round_to(entry * (1 - self.side * self.stop_frac), spec["tick"])
        st1 = c.stop_close(s, sell, stop1)
        stops = self._stops()
        self._step("stop rests on exchange", len(stops) == 1 and float(stops[0]["stopPrice"]) == stop1,
                   [(x["orderId"], x["stopPrice"]) for x in stops])
        # profit lock: new stop first, then cancel the old one -> never unprotected
        stop2 = _round_to(entry * (1 - self.side * self.stop_frac / 2), spec["tick"])
        st2 = c.stop_close(s, sell, stop2)
        both = self._stops()
        c.cancel(s, st1["orderId"])
        stops = self._stops()
        self._step("stop moved without a gap", len(both) == 2 and len(stops) == 1 and stops[0]["orderId"] == st2["orderId"],
                   {"during": len(both), "after": [(x["orderId"], x["stopPrice"]) for x in stops]})
        # restart check: drop the stop, reconcile must notice and restore it
        c.cancel(s, st2["orderId"])
        rep = reconcile(c, s, stop_price=stop2)
        self._step("restart check restores a missing stop", rep["repaired"] and len(self._stops()) == 1, rep)
        x = c.market(s, sell, qty, reduce_only=True)
        self._step("exit filled", x.get("status") == "FILLED", {"status": x.get("status"), "avg": x.get("avgPrice")})
        c.cancel_all(s)
        self._step("flat and no orders left", float(c.position(s)["positionAmt"]) == 0 and not c.open_orders(s),
                   {"positionAmt": c.position(s)["positionAmt"], "orders": len(c.open_orders(s))})
        return self.log


def reconcile(c: TestnetClient, symbol: str, stop_price: Optional[float] = None) -> dict:
    """After a restart: a position without a protective stop is the one state that must never
    last. Report it and, when the intended stop is known, put it back."""
    amt = float(c.position(symbol)["positionAmt"])
    stops = [o for o in c.open_orders(symbol) if o["type"] == "STOP_MARKET"]
    out = {"position": amt, "stops": len(stops), "repaired": False, "problem": None}
    if amt != 0 and not stops:
        out["problem"] = "position without a protective stop"
        if stop_price is not None:
            c.stop_close(symbol, "SELL" if amt > 0 else "BUY", stop_price)
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
    c = TestnetClient(os.environ.get("TESTNET_API_KEY", ""), os.environ.get("TESTNET_API_SECRET", ""))
    if args.cmd == "reconcile":
        print(json.dumps(reconcile(c, args.symbol), indent=1))
        return 0
    d = Drill(c, args.symbol, 1 if args.side == "long" else -1, args.notional, args.leverage)
    try:
        d.run()
        ok = True
    except (AssertionError, TestnetError) as e:
        d.log.append({"step": "stopped", "ok": False, "detail": str(e)})
        ok = False
        try:                              # leave the testnet account flat
            amt = float(c.position(args.symbol)["positionAmt"])
            if amt:
                c.market(args.symbol, "SELL" if amt > 0 else "BUY", abs(amt), reduce_only=True)
            c.cancel_all(args.symbol)
        except TestnetError:
            pass
    for row in d.log:
        print(("[OK]  " if row["ok"] else "[FAIL]") + f" {row['step']}: {row['detail']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
