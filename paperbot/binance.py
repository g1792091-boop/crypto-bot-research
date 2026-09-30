"""Minimal Binance USD-M futures REST client (standard library only).

Public market data needs no key. ``leverage_brackets`` and
``commission_rate`` are USER_DATA endpoints and need a read-only API key in
BINANCE_API_KEY / BINANCE_API_SECRET.

The transport is injectable so tests run without network access.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from .models import Bar

FAPI = "https://fapi.binance.com"

# fetch(url, headers) -> (status, body, response_headers)
Fetch = Callable[[str, dict], tuple[int, bytes, dict]]


class BinanceError(Exception):
    pass


class RegionBlocked(BinanceError):
    """HTTP 451 (restricted location) or 403 from an edge/proxy."""


def urllib_fetch(url: str, headers: dict, timeout: float = 10.0) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as err:
        return err.code, err.read(), dict(err.headers or {})


class BinanceREST:
    def __init__(self, base_url: str = FAPI, fetch: Optional[Fetch] = None,
                 api_key: Optional[str] = None, api_secret: Optional[str] = None,
                 max_retries: int = 4, backoff: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000)):
        self.base = base_url.rstrip("/")
        self.fetch = fetch or urllib_fetch
        self.api_key = api_key
        self.api_secret = api_secret
        self.max_retries = max_retries
        self.backoff = backoff
        self.sleep = sleep
        self.clock_ms = clock_ms

    # ------------------------------------------------------------ transport
    def _get(self, path: str, params: Optional[dict] = None, signed: bool = False):
        params = dict(params or {})
        headers = {"User-Agent": "paperbot/0.1"}
        if signed:
            if not (self.api_key and self.api_secret):
                raise BinanceError(f"{path} needs BINANCE_API_KEY and BINANCE_API_SECRET")
            params["timestamp"] = self.clock_ms()
            params["recvWindow"] = 5000
            query = urllib.parse.urlencode(params)
            sig = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            query += f"&signature={sig}"
            headers["X-MBX-APIKEY"] = self.api_key
        else:
            query = urllib.parse.urlencode(params)
        url = f"{self.base}{path}" + (f"?{query}" if query else "")

        delay = self.backoff
        last = ""
        for attempt in range(self.max_retries + 1):
            try:
                status, body, rh = self.fetch(url, headers)
            except OSError as exc:  # network down, DNS, timeout
                last = f"{type(exc).__name__}: {exc}"
                status, body, rh = 0, b"", {}
            if status == 200:
                return json.loads(body)
            if status in (451, 403):
                raise RegionBlocked(
                    f"{path}: HTTP {status}. The server's location or network "
                    f"is blocked by Binance or a proxy. {body[:200]!r}")
            if status in (429, 418) or status == 0 or status >= 500:
                wait = float(rh.get("Retry-After") or rh.get("retry-after") or delay)
                last = last or f"HTTP {status}"
                if attempt < self.max_retries:
                    self.sleep(wait)
                    delay *= 2
                    continue
                break
            raise BinanceError(f"{path}: HTTP {status} {body[:300]!r}")
        raise BinanceError(f"{path}: gave up after retries ({last})")

    # ------------------------------------------------------------ endpoints
    def server_time(self) -> int:
        return int(self._get("/fapi/v1/time")["serverTime"])

    def exchange_info(self, symbols) -> dict[str, dict]:
        info = self._get("/fapi/v1/exchangeInfo")
        wanted = set(symbols)
        out = {}
        for s in info["symbols"]:
            if s["symbol"] not in wanted:
                continue
            f = {x["filterType"]: x for x in s["filters"]}
            out[s["symbol"]] = {
                "status": s.get("status"),
                "contract_type": s.get("contractType"),
                "qty_step": float(f["MARKET_LOT_SIZE"]["stepSize"]) if "MARKET_LOT_SIZE" in f
                else float(f["LOT_SIZE"]["stepSize"]),
                "min_qty": float(f["LOT_SIZE"]["minQty"]),
                "tick_size": float(f["PRICE_FILTER"]["tickSize"]),
                "min_notional": float(f.get("MIN_NOTIONAL", {}).get("notional", 0.0)),
            }
        missing = wanted - out.keys()
        if missing:
            raise BinanceError(f"symbols not listed: {sorted(missing)}")
        return out

    def klines(self, symbol: str, interval: str, start_time: Optional[int] = None,
               limit: int = 1500) -> list[list]:
        p = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            p["startTime"] = start_time
        return self._get("/fapi/v1/klines", p)

    def mark_klines(self, symbol: str, interval: str, start_time: Optional[int] = None,
                    limit: int = 1500) -> list[list]:
        p = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            p["startTime"] = start_time
        return self._get("/fapi/v1/markPriceKlines", p)

    def funding_rates(self, symbol: str, start_time: Optional[int] = None,
                      limit: int = 1000) -> list[dict]:
        p = {"symbol": symbol, "limit": limit}
        if start_time is not None:
            p["startTime"] = start_time
        return self._get("/fapi/v1/fundingRate", p)

    # Order-flow statistics. The exchange keeps only the latest 30 days of these.
    FLOW_PATHS = {
        "oi": "/futures/data/openInterestHist",
        "ls_global": "/futures/data/globalLongShortAccountRatio",
        "ls_top_account": "/futures/data/topLongShortAccountRatio",
        "ls_top_position": "/futures/data/topLongShortPositionRatio",
        "taker": "/futures/data/takerlongshortRatio",
    }

    def flow_stats(self, dataset: str, symbol: str, period: str = "5m",
                   start_time: Optional[int] = None, end_time: Optional[int] = None,
                   limit: int = 500) -> list[dict]:
        p = {"symbol": symbol, "period": period, "limit": limit}
        if start_time is not None:
            p["startTime"] = start_time
        if end_time is not None:
            p["endTime"] = end_time
        return self._get(self.FLOW_PATHS[dataset], p)

    def premium_klines(self, symbol: str, interval: str, start_time: Optional[int] = None,
                       limit: int = 1500) -> list[list]:
        p = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            p["startTime"] = start_time
        return self._get("/fapi/v1/premiumIndexKlines", p)

    def book_tickers(self) -> list[dict]:
        """Best bid/ask for every symbol in one request (weight 5)."""
        return self._get("/fapi/v1/ticker/bookTicker")

    def depth(self, symbol: str, limit: int = 20) -> dict:
        return self._get("/fapi/v1/depth", {"symbol": symbol, "limit": limit})

    def leverage_brackets(self) -> list[dict]:
        return self._get("/fapi/v1/leverageBracket", signed=True)

    def commission_rate(self, symbol: str) -> dict:
        return self._get("/fapi/v1/commissionRate", {"symbol": symbol}, signed=True)


def bars_from_klines(symbol: str, rows: list[list],
                     mark_rows: Optional[list[list]] = None) -> list[Bar]:
    """Join last-price and mark-price klines on open time."""
    marks = {int(r[0]): r for r in (mark_rows or [])}
    out = []
    for r in rows:
        ot = int(r[0])
        m = marks.get(ot)
        out.append(Bar(
            symbol, ot, int(r[6]), float(r[1]), float(r[2]), float(r[3]), float(r[4]),
            mark_open=float(m[1]) if m else None, mark_high=float(m[2]) if m else None,
            mark_low=float(m[3]) if m else None, mark_close=float(m[4]) if m else None,
            volume=float(r[5])))
    return out
