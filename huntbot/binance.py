"""The one door to Binance: public USD-M REST GETs only (no key, no signed endpoint, no order path).

* host ``fapi.binance.com`` only, redirects refused, a fixed path whitelist (PATHS), timeout 10 s;
* a request-weight budget per rolling minute (default 1,800 of Binance's 2,400) shared by every call of the process,
  plus the funding-rate endpoint's own budget (Binance: 500 per 5 minutes per IP; we use at most 240);
* HTTP 429 / 418 wait for Retry-After (or 60 s) and try again; 5xx, network errors and broken HTTP replies
  (``http.client.HTTPException``: a cut-off body, a bad status line) back off 1, 2, 4 s; at most
  ``max_tries`` tries, then ``BinanceDown``.

``fetch`` is injectable (tests pass a fake; the build machine cannot reach fapi.binance.com).
"""

from __future__ import annotations

import collections
import http.client
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

BASE = "https://fapi.binance.com"
HOST = "fapi.binance.com"
UA = "huntbot-feed (paper only, public data)"
TIMEOUT_S = 10.0
PATHS = frozenset(("/fapi/v1/klines", "/fapi/v1/markPriceKlines", "/fapi/v1/fundingRate", "/fapi/v1/premiumIndex",
                   "/fapi/v1/exchangeInfo", "/fapi/v1/openInterest", "/fapi/v1/time"))
WEIGHT_PER_MIN = 1800              # of Binance's 2,400 per IP; the server runs nothing else that calls Binance
FUNDING_PER_5MIN = 240

# fetch(url, headers, timeout) -> (status, body bytes, headers dict)
Fetch = Callable[[str, dict, float], tuple]


class BinanceError(Exception):
    pass


class BinanceDown(BinanceError):
    """Not reachable or kept failing after the retries."""


def kline_weight(limit: int) -> int:
    return 1 if limit < 100 else 2 if limit < 500 else 5 if limit <= 1000 else 10


def weight_of(path: str, params: dict) -> int:
    if path in ("/fapi/v1/klines", "/fapi/v1/markPriceKlines"):
        return kline_weight(int(params.get("limit", 500)))
    if path == "/fapi/v1/premiumIndex":
        return 1 if params.get("symbol") else 10
    return 1


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # never follow Binance anywhere else
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect)


def urllib_fetch(url: str, headers: dict, timeout: float = TIMEOUT_S) -> tuple:
    req = urllib.request.Request(url, headers=headers)
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read(16 * 1024 * 1024), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:  # noqa: BLE001
            body = b""
        return e.code, body, dict(e.headers or {})


class Budget:
    """At most ``cap`` units in any rolling ``window`` seconds (thread-safe; clock / sleep injectable)."""

    def __init__(self, cap: int, window: float, clock=time.monotonic, sleep=time.sleep):
        self.cap, self.window, self.clock, self.sleep = cap, window, clock, sleep
        self._lock = threading.Lock()
        self._q: "collections.deque[tuple[float, int]]" = collections.deque()
        self._used = 0

    def take(self, n: int) -> None:
        n = min(n, self.cap)
        while True:
            with self._lock:
                now = self.clock()
                while self._q and now - self._q[0][0] >= self.window:
                    self._used -= self._q.popleft()[1]
                if self._used + n <= self.cap:
                    self._q.append((now, n))
                    self._used += n
                    return
                wait = self.window - (now - self._q[0][0])
            self.sleep(max(wait, 0.01))


class Client:
    def __init__(self, fetch: Optional[Fetch] = None, weight_per_min: int = WEIGHT_PER_MIN,
                 funding_per_5min: int = FUNDING_PER_5MIN, max_tries: int = 5, sleep=time.sleep,
                 clock=time.monotonic):
        self.fetch = fetch or urllib_fetch
        self.sleep = sleep
        self.max_tries = max_tries
        self.weight = Budget(weight_per_min, 60.0, clock, sleep)
        self.funding = Budget(funding_per_5min, 300.0, clock, sleep)
        self.requests = 0
        self.used_weight = 0

    def get(self, path: str, params: Optional[dict] = None):
        if path not in PATHS:
            raise ValueError(f"not an allowed Binance path: {path}")
        params = dict(params or {})
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        if urllib.parse.urlsplit(url).hostname != HOST:
            raise ValueError("wrong host")
        w = weight_of(path, params)
        last = "?"
        for i in range(self.max_tries):
            self.weight.take(w)
            if path == "/fapi/v1/fundingRate":
                self.funding.take(1)
            self.requests += 1
            self.used_weight += w
            try:
                status, body, headers = self.fetch(url, {"User-Agent": UA, "Accept": "application/json"}, TIMEOUT_S)
            except (OSError, ValueError, http.client.HTTPException) as e:   # timeout, refused, DNS, a cut-off body
                status, body, headers = 0, b"", {}                             # (IncompleteRead, BadStatusLine, ...)
                last = type(e).__name__
            if status == 200:
                try:
                    return json.loads(body)
                except ValueError:
                    last = "not JSON"
            elif status in (429, 418):
                ra = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
                try:
                    wait = float(ra)
                except (TypeError, ValueError):
                    wait = 60.0
                last = f"HTTP {status}"
                self.sleep(min(max(wait, 1.0), 300.0))
                continue
            elif 400 <= status < 500:
                raise BinanceError(f"{path}: HTTP {status} {body[:200]!r}")
            else:
                last = f"HTTP {status}" if status else last
            self.sleep(min(2 ** i, 16))
        raise BinanceDown(f"{path}: {last} after {self.max_tries} tries")

    # -- the few calls the feed makes
    def klines(self, sym: str, start_ms: int, limit: int = 1000, mark: bool = False) -> list:
        p = "/fapi/v1/markPriceKlines" if mark else "/fapi/v1/klines"
        return self.get(p, {"symbol": sym, "interval": "5m", "startTime": int(start_ms), "limit": int(limit)})

    def funding_rates(self, sym: str, start_ms: int, limit: int = 1000) -> list:
        return self.get("/fapi/v1/fundingRate", {"symbol": sym, "startTime": int(start_ms), "limit": int(limit)})

    def premium_index(self) -> list:
        return self.get("/fapi/v1/premiumIndex")

    def exchange_info(self) -> dict:
        return self.get("/fapi/v1/exchangeInfo")

    def open_interest(self, sym: str) -> dict:
        return self.get("/fapi/v1/openInterest", {"symbol": sym})

    def server_time(self) -> int:
        return int(self.get("/fapi/v1/time")["serverTime"])
