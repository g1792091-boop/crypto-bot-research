"""Live market data for the 후보 리그 dashboard's terminal (copied from the demo lab's demobot/dash/live.py, which is
tested there; only the coin list, the user agent and the setting's name differ). The dashboard SERVER reads Binance USD-M
public endpoints (no key) and hands the page small cached answers; the browser never talks to Binance (the page's CSP
stays ``connect-src 'self'``).

    GET /api/live                           price, 24 h change, volume, high / low, mark, funding, open interest (6 coins)
    GET /api/klines?coin=BTCUSD&tf=15m&limit=500     candles {"t", "o", "h", "l", "c", "v"} (1m 5m 15m 30m 1h 4h 1d)
    GET /api/market                         funding (last 3), open interest now / 24 h change, long/short account ratio

Rules (CONTRACT 9.1): ``https://fapi.binance.com`` only (redirects refused), timeout 5 s, at most 4 requests per second
from the whole dashboard (one limiter for every viewer), ``User-Agent: demobot-dash``, nothing written to disk. Caches:
live 5 s, klines 10 s per (coin, tf, limit) (at most KLINES_KEEP of them), market 60 s, open interest 30 s. A request
that fails keeps the last good answer and marks it ``"stale": true`` (and is not retried before its cache time is up,
so a Binance outage costs at most one try per cache period); with no good answer yet the reply says
``"unavailable": true``. While one viewer's request is refreshing a key, the others get the last good answer at once
instead of waiting.

``CANDLEAGUE_DASH_LIVE`` = ``on`` (default) | ``fake`` (a deterministic 15m random walk per coin: tests, screenshots, a
sandbox that cannot reach Binance) | ``off`` (every route answers ``{"off": true}``).
"""
from __future__ import annotations

import collections
import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Callable, Optional

import numpy as np


BASE = "https://fapi.binance.com"
HOST = "fapi.binance.com"
UA = "candleague-dash"
TIMEOUT_S = 5.0
RATE_PER_S = 4
MAX_BYTES = 4 * 1024 * 1024           # one answer (the klines at limit 1000 are ~150 KB)
LIVE_TTL, KLINES_TTL, MARKET_TTL, OI_TTL = 5.0, 10.0, 60.0, 30.0
KLINES_KEEP = 32                      # (coin, tf, limit) answers kept in memory
LIMIT_MAX = 1000
KLINE_TFS = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000,
         "1d": 86_400_000}
MODES = ("off", "fake", "on")
PATHS = frozenset(("/fapi/v1/ticker/24hr", "/fapi/v1/premiumIndex", "/fapi/v1/openInterest", "/fapi/v1/klines",
                   "/fapi/v1/fundingRate", "/futures/data/openInterestHist",
                   "/futures/data/globalLongShortAccountRatio"))
M15 = 900_000
H8 = 8 * 3_600_000


COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
FAKE_BASE = {"BTCUSD": 61000.0, "ETHUSD": 2400.0, "SOLUSD": 140.0, "DOGEUSD": 0.11, "LTCUSD": 66.0, "BCHUSD": 330.0}


class _Coins:
    """The demo lab's ``grid`` names this module uses: the coins and their Binance USDT-M symbols."""
    COINS = COINS

    @staticmethod
    def binance_symbol(coin: str) -> str:
        return coin + "T"


grid = _Coins()


def fake_bars(coin: str, now_ms: float, n: int = 3000) -> tuple:
    """(ts, o, h, l, c) of n deterministic 15m bars ending at the last 15m boundary before ``now_ms`` (fake mode)."""
    end = int(now_ms) // M15 * M15
    ts = end - M15 * np.arange(n, 0, -1, dtype=np.int64)
    r = np.random.default_rng(zlib.crc32(coin.encode()))
    c = FAKE_BASE.get(coin, 100.0) * np.exp(np.cumsum(r.standard_t(4, n) * 0.003))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(r.normal(0, 0.0015, n)))
    lo = np.minimum(o, c) * (1 - np.abs(r.normal(0, 0.0015, n)))
    return ts, o, h, lo, c


class LiveError(Exception):
    """A Binance answer that did not come or could not be read."""


class NetError(LiveError):
    """Binance not reachable (timeout, refused, DNS, HTTP error): the rest of a build is not tried."""


# ---------------------------------------------------------------- the one door to Binance
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):      # never follow Binance anywhere else
        raise NetError(f"redirect refused ({code})")


_OPENER = urllib.request.build_opener(_NoRedirect)


def binance_get(path: str, params: Optional[dict] = None, timeout: float = TIMEOUT_S):
    """GET one public Binance USD-M endpoint (a path of PATHS) and parse its JSON. Raises NetError / LiveError."""
    if path not in PATHS:
        raise ValueError(f"not an allowed Binance path: {path}")
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    if urllib.parse.urlsplit(url).hostname != HOST:                            # (BASE is a constant; belt and braces)
        raise ValueError("wrong host")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            if r.status != 200:
                raise NetError(f"HTTP {r.status}")
            raw = r.read(MAX_BYTES + 1)
    except NetError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:                # timeout, refused, HTTP 4xx / 5xx
        raise NetError(type(e).__name__) from None
    if len(raw) > MAX_BYTES:
        raise LiveError("answer too large")
    try:
        return json.loads(raw)
    except ValueError:
        raise LiveError("not JSON") from None


class RateLimiter:
    """At most ``n`` acquisitions in any rolling second, shared by every thread (a sliding window of stamps).
    clock / sleep are injectable for tests; a wait longer than max_wait raises LiveError."""

    def __init__(self, n: int = RATE_PER_S, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, max_wait: float = 15.0):
        self.n, self.clock, self.sleep, self.max_wait = n, clock, sleep, max_wait
        self._lock = threading.Lock()
        self._stamps: "collections.deque[float]" = collections.deque()

    def acquire(self) -> None:
        start = self.clock()
        while True:
            with self._lock:
                now = self.clock()
                while self._stamps and now - self._stamps[0] >= 1.0:
                    self._stamps.popleft()
                if len(self._stamps) < self.n:
                    self._stamps.append(now)
                    return
                wait = 1.0 - (now - self._stamps[0])
            if now + wait - start > self.max_wait:
                raise LiveError("rate limit: waited too long")
            self.sleep(max(wait, 0.001))


# ---------------------------------------------------------------- small readers
def _fin(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _need(x) -> float:
    v = _fin(x)
    if v is None:
        raise LiveError("bad number")
    return v


def _int(x) -> Optional[int]:
    v = _fin(x)
    return None if v is None else int(v)


def _clean(o):
    """NaN / inf -> None anywhere (the answers go out with allow_nan=False)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


class _Entry:
    __slots__ = ("at", "good", "stale", "err")

    def __init__(self, at, good, stale, err=None):
        self.at, self.good, self.stale, self.err = at, good, stale, err


# ---------------------------------------------------------------- the cache + the three answers
class Live:
    """mode: on | fake | off. fetch(path, params) -> parsed JSON (default binance_get, tests pass a fake);
    bars(coin) -> (ts, o, h, l, c) 15m arrays or None (fake mode; the dashboard passes its snapshot reader)."""

    def __init__(self, mode: str = "on", fetch: Optional[Callable] = None, bars: Optional[Callable] = None,
                 limiter: Optional[RateLimiter] = None, clock: Callable[[], float] = time.time):
        if mode not in MODES:
            raise ValueError(f"CANDLEAGUE_DASH_LIVE: {' | '.join(MODES)}")
        self.mode = mode
        self._fetch = fetch or binance_get
        self._bars = bars
        self.limiter = limiter or RateLimiter()
        self.clock = clock
        self._lock = threading.Lock()
        self._cache: "collections.OrderedDict[tuple, _Entry]" = collections.OrderedDict()
        self._locks: dict = {}                                    # one per key: a key refreshes once at a time (the
        # nested refreshes always go market -> live -> open interest, so per-key locks never wait in a circle)
        self.requests = 0                                         # Binance requests made (tests, the status line)

    @classmethod
    def from_env(cls, bars: Optional[Callable] = None) -> "Live":
        mode = (os.environ.get("CANDLEAGUE_DASH_LIVE") or "on").strip().lower()
        return cls(mode if mode in MODES else "on", bars=bars)

    # -- plumbing
    def _get(self, path: str, params: Optional[dict] = None):
        self.limiter.acquire()
        with self._lock:
            self.requests += 1
        return self._fetch(path, params or {})

    def _cached(self, key: tuple, ttl: float, build: Callable, keep: Optional[int] = None):
        """(value or None, stale, error) of a key: the cached value while it is younger than ttl; else build() it
        (one thread at a time per key; the others get the last good value right away). A failed build keeps the
        last good value, marked stale, until the next try after ttl."""
        now = self.clock()
        with self._lock:
            e = self._cache.get(key)
        if e is not None and now - e.at < ttl:
            return e.good, e.stale, e.err
        with self._lock:
            lk = self._locks.setdefault(key, threading.Lock())
        if not lk.acquire(blocking=e is None or e.good is None):
            return e.good, e.stale, e.err                          # someone is refreshing it: the last good one
        try:
            with self._lock:
                e = self._cache.get(key)
            now = self.clock()
            if e is not None and now - e.at < ttl:                 # refreshed while this thread waited
                return e.good, e.stale, e.err
            try:                                                   # (stamped when the answer is in: a build that
                v = build()                                        # waited for the rate limit keeps its full ttl)
                ne = _Entry(self.clock(), v, False)
            except (LiveError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as err:
                ne = _Entry(self.clock(), e.good if e else None, True, type(err).__name__ if not isinstance(err, LiveError)
                            else str(err)[:80])
            with self._lock:
                self._cache[key] = ne
                self._cache.move_to_end(key)
                if keep is not None:
                    kl = [k for k in self._cache if k[0] == key[0]]
                    for k in kl[:max(0, len(kl) - keep)]:
                        del self._cache[k]
                        self._locks.pop(k, None)
            return ne.good, ne.stale, ne.err
        finally:
            lk.release()

    # -- /api/live
    def live(self) -> dict:
        if self.mode == "off":
            return {"off": True}
        v, stale, err = self._cached(("live",), LIVE_TTL, self._fake_live if self.mode == "fake" else self._build_live)
        if v is None:
            return {"generated_ms": int(self.clock() * 1000), "coins": [], "stale": True, "unavailable": True,
                    "error": err}
        return {**v, "stale": stale}

    def _open_interest(self) -> dict:
        """symbol -> open interest (contracts), cached 30 s (it moves slowly; 7 requests)."""
        def build():
            out = {}
            for coin in grid.COINS:
                sym = grid.binance_symbol(coin)
                try:
                    d = self._get("/fapi/v1/openInterest", {"symbol": sym})
                    out[sym] = _fin(d.get("openInterest")) if isinstance(d, dict) else None
                except NetError:
                    raise
                except LiveError:
                    out[sym] = None
            return out
        v, _stale, _err = self._cached(("oi",), OI_TTL, build)
        return v or {}

    def _build_live(self) -> dict:
        try:
            prem = self._get("/fapi/v1/premiumIndex")              # every symbol in one answer
        except NetError:
            raise
        except LiveError:
            prem = None
        pm = {p.get("symbol"): p for p in prem if isinstance(p, dict)} if isinstance(prem, list) else {}
        oi = self._open_interest()
        rows, good = [], 0
        for coin in grid.COINS:
            sym = grid.binance_symbol(coin)
            row = {"coin": coin, "price": None, "change_pct": None, "quote_volume": None, "high": None, "low": None,
                   "mark": None, "funding_rate": None, "next_funding_ms": None, "open_interest": oi.get(sym),
                   "ok": False}
            try:
                t = self._get("/fapi/v1/ticker/24hr", {"symbol": sym})
                if not isinstance(t, dict):
                    raise LiveError("bad ticker")
                row.update(price=_need(t.get("lastPrice")), change_pct=_fin(t.get("priceChangePercent")),
                           quote_volume=_fin(t.get("quoteVolume")), high=_fin(t.get("highPrice")),
                           low=_fin(t.get("lowPrice")), ok=True)
                good += 1
            except NetError:
                raise
            except LiveError:
                pass
            p = pm.get(sym) or {}
            row.update(mark=_fin(p.get("markPrice")), funding_rate=_fin(p.get("lastFundingRate")),
                       next_funding_ms=_int(p.get("nextFundingTime")))
            rows.append(row)
        if not good:
            raise LiveError("no ticker")
        return _clean({"generated_ms": int(self.clock() * 1000), "source": "binance", "coins": rows})

    # -- /api/klines
    def klines(self, coin: str, tf: str, limit: int) -> dict:
        """coin / tf / limit must already be whitelisted (app.klines_query)."""
        if self.mode == "off":
            return {"off": True}
        build = (lambda: self._fake_klines(coin, tf, limit)) if self.mode == "fake" else \
            (lambda: self._build_klines(coin, tf, limit))
        v, stale, err = self._cached(("k", coin, tf, limit), KLINES_TTL, build, keep=KLINES_KEEP)
        if v is None:
            return {"coin": coin, "tf": tf, "limit": limit, "generated_ms": int(self.clock() * 1000), "stale": True,
                    "unavailable": True, "error": err, "bars": {k: [] for k in "tohlcv"}}
        return {**v, "stale": stale}

    def _build_klines(self, coin: str, tf: str, limit: int) -> dict:
        raw = self._get("/fapi/v1/klines", {"symbol": grid.binance_symbol(coin), "interval": tf, "limit": limit})
        if not isinstance(raw, list):
            raise LiveError("bad klines")
        cols = {k: [] for k in "tohlcv"}
        last = -1
        for r in raw:
            if not isinstance(r, list) or len(r) < 6:
                continue
            t = _int(r[0])
            vals = [_fin(x) for x in r[1:6]]
            if t is None or t <= last or any(x is None for x in vals):
                continue
            last = t
            cols["t"].append(t)
            for k, x in zip("ohlcv", vals):
                cols[k].append(x)
        if not cols["t"]:
            raise LiveError("no bars")
        return {"coin": coin, "tf": tf, "limit": limit, "generated_ms": int(self.clock() * 1000), "bars": cols}

    # -- /api/market
    def market(self) -> dict:
        if self.mode == "off":
            return {"off": True}
        v, stale, err = self._cached(("market",), MARKET_TTL, self._fake_market if self.mode == "fake" else self._build_market)
        if v is None:
            return {"generated_ms": int(self.clock() * 1000), "coins": [], "stale": True, "unavailable": True, "error": err}
        return {**v, "stale": stale}

    def _build_market(self) -> dict:
        lv = self.live()
        lmap = {c.get("coin"): c for c in lv.get("coins") or []}
        rows, good = [], 0
        for coin in grid.COINS:
            sym = grid.binance_symbol(coin)
            lc = lmap.get(coin) or {}
            row = {"coin": coin, "price": lc.get("price"), "change_pct": lc.get("change_pct"),
                   "funding_rate": lc.get("funding_rate"), "next_funding_ms": lc.get("next_funding_ms"),
                   "funding": [], "open_interest": lc.get("open_interest"), "oi_change_24h_pct": None, "oi_hist": [],
                   "oi_value_usd": None, "ls_ratio": [], "ls_now": None, "long_share": None, "ok": False}
            try:
                f = self._get("/fapi/v1/fundingRate", {"symbol": sym, "limit": 3})
                row["funding"] = [[_int(x.get("fundingTime")), _fin(x.get("fundingRate"))] for x in f
                                  if isinstance(x, dict) and _int(x.get("fundingTime")) is not None][-3:]
                oh = self._get("/futures/data/openInterestHist", {"symbol": sym, "period": "1h", "limit": 25})
                pts = [[_int(x.get("timestamp")), _fin(x.get("sumOpenInterest")), _fin(x.get("sumOpenInterestValue"))]
                       for x in oh if isinstance(x, dict) and _int(x.get("timestamp")) is not None]
                pts.sort(key=lambda p: p[0])
                row["oi_hist"] = [[p[0], p[1]] for p in pts if p[1] is not None]
                if len(row["oi_hist"]) >= 2 and row["oi_hist"][0][1]:
                    row["oi_change_24h_pct"] = (row["oi_hist"][-1][1] / row["oi_hist"][0][1] - 1) * 100
                if pts and pts[-1][2] is not None:
                    row["oi_value_usd"] = pts[-1][2]
                if row["open_interest"] is None and row["oi_hist"]:
                    row["open_interest"] = row["oi_hist"][-1][1]
                ls = self._get("/futures/data/globalLongShortAccountRatio", {"symbol": sym, "period": "1h", "limit": 24})
                lp = [[_int(x.get("timestamp")), _fin(x.get("longShortRatio")), _fin(x.get("longAccount"))]
                      for x in ls if isinstance(x, dict) and _int(x.get("timestamp")) is not None]
                lp.sort(key=lambda p: p[0])
                row["ls_ratio"] = [p for p in lp if p[1] is not None]
                if row["ls_ratio"]:
                    row["ls_now"], row["long_share"] = row["ls_ratio"][-1][1], row["ls_ratio"][-1][2]
                row["ok"] = True
                good += 1
            except NetError:
                raise
            except (LiveError, AttributeError, TypeError):
                pass
            rows.append(row)
        if not good:
            raise LiveError("no market rows")
        return _clean({"generated_ms": int(self.clock() * 1000), "source": "binance", "coins": rows})

    # ---------------------------------------------------------------- fake mode (snap/bars + deterministic noise)
    def _base(self, coin: str):
        arr = self._bars(coin) if self._bars else fake_bars(coin, self.clock() * 1000)
        if arr is None or isinstance(arr, str) or not len(arr[0]):
            raise LiveError("no bars file")
        return arr

    @staticmethod
    def _rng(*parts) -> np.random.Generator:
        return np.random.default_rng(zlib.crc32("|".join(str(p) for p in parts).encode()))

    def _fake_live(self) -> dict:
        now = int(self.clock() * 1000)
        bucket = now // 5000
        rows = []
        for coin in grid.COINS:
            try:
                ts, o, h, lo_, c = self._base(coin)
            except LiveError:
                rows.append({"coin": coin, "price": None, "change_pct": None, "quote_volume": None, "high": None,
                             "low": None, "mark": None, "funding_rate": None, "next_funding_ms": None,
                             "open_interest": None, "ok": False})
                continue
            r = self._rng("live", coin, bucket)
            last = float(c[-1])
            px = last * math.exp(float(r.normal(0, 0.0004)))
            day = max(0, len(c) - 96)
            ref = float(o[day])
            notional = {"BTCUSD": 9.5e9, "ETHUSD": 5.2e9, "SOLUSD": 1.6e9, "DOGEUSD": 9e8, "LTCUSD": 3.1e8,
                        "BCHUSD": 2.4e8, "XRPUSD": 1.1e9}.get(coin, 5e8)
            rows.append({"coin": coin, "price": px, "change_pct": (px / ref - 1) * 100,
                         "quote_volume": notional * (1 + 0.1 * math.sin(bucket / 50 + len(coin))),
                         "high": max(float(np.max(h[day:])), px), "low": min(float(np.min(lo_[day:])), px),
                         "mark": px * (1 + float(r.normal(0, 0.00005))), "funding_rate": self._fake_rate(coin, now // H8),
                         "next_funding_ms": (now // H8 + 1) * H8, "open_interest": self._fake_oi(coin, now // 3_600_000) / px,
                         "ok": True})
        if not any(x["ok"] for x in rows):
            raise LiveError("no bars file")
        return _clean({"generated_ms": now, "source": "fake", "coins": rows})

    def _fake_rate(self, coin: str, k: int) -> float:
        base = {"BTCUSD": 0.0001, "ETHUSD": 0.00008, "SOLUSD": 0.00012, "DOGEUSD": 0.00015, "LTCUSD": 0.00005,
                "BCHUSD": 0.00009, "XRPUSD": 0.0001}.get(coin, 0.0001)
        return round(base + float(self._rng("fund", coin, k).normal(0, 0.00006)), 6)

    def _fake_oi(self, coin: str, hour: int) -> float:
        """Open interest in USD at an hour (a slow deterministic walk)."""
        base = {"BTCUSD": 8.1e9, "ETHUSD": 5.4e9, "SOLUSD": 1.9e9, "DOGEUSD": 1.2e9, "LTCUSD": 4.1e8, "BCHUSD": 3.3e8,
                "XRPUSD": 1.5e9}.get(coin, 5e8)
        walk = sum(float(self._rng("oi", coin, hour - j).normal(0, 0.006)) for j in range(48))
        return base * math.exp(walk)

    def _fake_klines(self, coin: str, tf: str, limit: int) -> dict:
        ts, o, h, lo_, c = self._base(coin)
        step = TF_MS[tf]
        cols = {k: [] for k in "tohlcv"}
        if step >= M15:                                          # 15m and longer: group the 15m bars
            need = limit * (step // M15) + step // M15
            ts, o, h, lo_, c = ts[-need:], o[-need:], h[-need:], lo_[-need:], c[-need:]
            g = ts // step
            cut = np.flatnonzero(np.diff(g)) + 1
            for a, b in zip(np.r_[0, cut], np.r_[cut, len(ts)]):
                cols["t"].append(int(g[a] * step))
                cols["o"].append(float(o[a]))
                cols["h"].append(float(np.max(h[a:b])))
                cols["l"].append(float(np.min(lo_[a:b])))
                cols["c"].append(float(c[b - 1]))
        else:                                                    # 1m / 5m: a deterministic path inside each 15m bar
            k = M15 // step
            n15 = -(-limit // k) + 1
            for i in range(max(0, len(ts) - n15), len(ts)):
                r = self._rng("sub", coin, tf, int(ts[i]))
                lo, hi, oo, cc = float(lo_[i]), float(h[i]), float(o[i]), float(c[i])
                steps = np.cumsum(r.normal(0, 1, k))
                path = oo + (cc - oo) * np.arange(1, k + 1) / k + (steps - steps[-1] * np.arange(1, k + 1) / k) * (hi - lo) / 6
                path = np.clip(path, lo, hi)
                path[-1] = cc
                prev = oo
                for j in range(k):
                    a, b = prev, float(path[j])
                    wick = abs(float(r.normal(0, 0.25))) * (hi - lo) / k
                    cols["t"].append(int(ts[i]) + j * step)
                    cols["o"].append(a)
                    cols["h"].append(min(hi, max(a, b) + wick))
                    cols["l"].append(max(lo, min(a, b) - wick))
                    cols["c"].append(b)
                    prev = b
        for k_ in "tohlc":
            cols[k_] = cols[k_][-limit:]
        for t0, oo, cc in zip(cols["t"], cols["o"], cols["c"]):
            r = self._rng("vol", coin, tf, t0)
            cols["v"].append(round(float(r.lognormal(0, 0.4)) * (1 + 40 * abs(cc / oo - 1)) * 100 * step / M15, 3))
        return _clean({"coin": coin, "tf": tf, "limit": limit, "generated_ms": int(self.clock() * 1000),
                       "source": "fake", "bars": cols})

    def _fake_market(self) -> dict:
        lv = self.live()
        lmap = {x.get("coin"): x for x in lv.get("coins") or []}
        now = int(self.clock() * 1000)
        hour = now // 3_600_000
        rows = []
        for coin in grid.COINS:
            lc = lmap.get(coin) or {}
            if not lc.get("ok"):
                continue
            px = lc["price"]
            funding = [[int(k * H8), self._fake_rate(coin, k - 1)] for k in range(now // H8 - 2, now // H8 + 1)]
            oi = [[int((hour - 24 + j) * 3_600_000), self._fake_oi(coin, hour - 24 + j) / px] for j in range(25)]
            r = self._rng("ls", coin, hour)
            base = 1.0 + 0.9 * float(self._rng("lsb", coin).random())
            ls = []
            for j in range(24):
                x = base * math.exp(0.08 * math.sin((hour - 23 + j) / 3.0 + len(coin)) + float(r.normal(0, 0.02)))
                ls.append([int((hour - 23 + j) * 3_600_000), round(x, 4), round(x / (1 + x), 4)])
            rows.append({"coin": coin, "price": px, "change_pct": lc.get("change_pct"), "funding_rate": lc.get("funding_rate"),
                         "next_funding_ms": lc.get("next_funding_ms"), "funding": funding,
                         "open_interest": lc.get("open_interest"), "oi_change_24h_pct": (oi[-1][1] / oi[0][1] - 1) * 100,
                         "oi_hist": oi, "oi_value_usd": oi[-1][1] * px, "ls_ratio": ls, "ls_now": ls[-1][1],
                         "long_share": ls[-1][2], "ok": True})
        if not rows:
            raise LiveError("no bars file")
        return _clean({"generated_ms": now, "source": "fake", "coins": rows})
