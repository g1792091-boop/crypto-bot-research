"""급등 · 급락 · 음펀비 (the 터미널's top strip): the whole Binance USD-M perpetual market, read-only.

    GET /api/v4/movers

    {"ready": true, "ts": <when Binance was asked, ms>, "n": <perpetuals counted>,
     "up":   [{"s": "PUMPBTCUSDT", "pct": 104.64, "price": 0.1234, "q": 4.5e7}, ... 3],   top 24 h gainers
     "down": [{"s": "SHROOMUSDT", "pct": -31.33, ...}, ... 3],                             top 24 h losers
     "neg":  [{"s": "AGENCYUSDT", "rate": -0.02, "next": <next funding ms>}, ... 3],        most negative funding
     "stale": true when the last fetch failed and this is the previous good answer}

The whole market's numbers (NOT our bots): the page labels them 시장 전체 (우리 봇 아님).

Cost (the dashboard shares this server's Binance IP weight with the bot): ONE ``/fapi/v1/ticker/24hr`` (all symbols,
weight 40) and ONE ``/fapi/v1/premiumIndex`` (all symbols, weight 10) per ``TTL_S`` (60 s) at most, whoever asks and
however many pages are open (one lock: concurrent requests share one fetch), and only while somebody asks (no thread,
no timer): at most 50 weight a minute against Binance's 2,400. The fetch is dash/app.py's ``_get_json`` (urllib with
the dashboard's User-Agent, the same pattern as /api/market); a test swaps ``FETCH``.

Which symbols count: a perpetual is a premiumIndex symbol without a delivery suffix ("_YYMMDD"); a 24 h row counts
only when its last trade is fresh (``FRESH_MS``: delisted / settling symbols keep a frozen ticker with a stale close
time) and it really traded (quote volume over ``MIN_QUOTE``). A failed fetch keeps the last good answer, marked
``stale``; before any good answer it says ``ready: false`` (the page shows 수집 전, never a made-up mover).
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

TICKER_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
PREMIUM_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
TTL_S = 60.0
FRESH_MS = 15 * 60_000          # a 24 h row whose last trade is older than this is a frozen (delisted) symbol
MIN_QUOTE = 100_000.0           # USDT traded in 24 h: below it a % move is one stray trade
TOP_N = 3

FETCH: Optional[Callable] = None        # tests set this; None = dash/app.py _get_json


def _fetch(url: str):
    if FETCH is not None:
        return FETCH(url)
    from ..app import _get_json
    return _get_json(url, timeout=8.0)


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def build(tickers, premium, now_ms: int) -> dict:
    """The answer from the two raw lists (pure: tested without the network)."""
    perps: dict = {}
    for p in premium if isinstance(premium, list) else []:
        s = p.get("symbol") if isinstance(p, dict) else None
        if not isinstance(s, str) or "_" in s:
            continue
        perps[s] = p
    rows = []
    for t in tickers if isinstance(tickers, list) else []:
        s = t.get("symbol") if isinstance(t, dict) else None
        if s not in perps:
            continue
        pct, last, q = _f(t.get("priceChangePercent")), _f(t.get("lastPrice")), _f(t.get("quoteVolume"))
        close_t = _f(t.get("closeTime")) or 0
        if pct is None or not last or q is None or q < MIN_QUOTE or now_ms - close_t > FRESH_MS:
            continue
        rows.append({"s": s, "pct": round(pct, 2), "price": last, "q": round(q)})
    neg = []
    live = {r["s"] for r in rows}
    for s, p in perps.items():
        r, nxt = _f(p.get("lastFundingRate")), _f(p.get("nextFundingTime"))
        if r is None or r >= 0 or s not in live:
            continue
        neg.append({"s": s, "rate": r, "next": int(nxt) if nxt else None})
    up = sorted((r for r in rows if r["pct"] > 0), key=lambda r: -r["pct"])[:TOP_N]
    down = sorted((r for r in rows if r["pct"] < 0), key=lambda r: r["pct"])[:TOP_N]
    neg.sort(key=lambda r: r["rate"])
    return {"ready": bool(rows), "ts": now_ms, "n": len(rows), "up": up, "down": down, "neg": neg[:TOP_N]}


class Movers:
    """One cached answer, refreshed at most every ``ttl`` seconds by whichever request comes first."""

    def __init__(self, ttl: float = TTL_S, clock: Callable[[], float] = time.time):
        self.ttl, self.clock = ttl, clock
        self.lock = threading.Lock()
        self.at = None                  # when the last fetch was made (success or not)
        self.good: Optional[dict] = None
        self.fetches = 0

    def get(self) -> dict:
        with self.lock:
            now = self.clock()
            if self.at is not None and now - self.at < self.ttl:
                return self._answer(stale=self._last_failed)
            self.at = now
            self.fetches += 1
            try:
                tk = _fetch(TICKER_URL)
                pr = _fetch(PREMIUM_URL)
                out = build(tk, pr, int(now * 1000))
                if not out["ready"]:
                    raise ValueError("no rows")
                self.good, self._last_failed = out, False
            except Exception:  # noqa: BLE001  (Binance down / blocked / bad answer: the last good one, marked old)
                self._last_failed = True
            return self._answer(stale=self._last_failed)

    _last_failed = False

    def _answer(self, stale: bool) -> dict:
        if self.good is None:
            return {"ready": False}
        return {**self.good, "stale": True} if stale else self.good


def register(app, ctx) -> dict:
    mv = Movers()

    @app.get("/api/v4/movers")
    def get_movers():
        """Top 24 h gainer / loser and the most negative funding over every Binance USD-M perpetual (cached 60 s)."""
        return mv.get()

    return {"routes": ["/api/v4/movers"], "movers": mv}
