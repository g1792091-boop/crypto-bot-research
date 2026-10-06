"""터미널 윗줄의 시장 숫자: 고른 코인의 미결제약정과 롱/숏 계좌 비율 (바이낸스 공개 선물 자료, 읽기 전용).

    GET /api/v4/topstats?symbol=BTCUSDT

    {"ready": true, "symbol": "BTCUSDT", "ts": <when Binance was asked, ms>,
     "oi": {"usd": 5.94e9, "chg_1h": 0.004, "ts": <the newest 5-minute record, ms>, "stale": false} | null,
     "ls": {"ratio": 1.92, "long": 0.6575, "short": 0.3425, "ts": <the newest 5-minute record, ms>, "stale": false} | null,
     "errors": {"oi": "URLError", ...}}              the parts that could not be read (the page shows "—", never 0)

The two parts are independent (one failing never hides the other). Sources, both on fapi.binance.com (public, no key):
    oi  /futures/data/openInterestHist?period=5m&limit=13   open interest in USDT now and an hour earlier
    ls  /futures/data/globalLongShortAccountRatio?period=5m&limit=1   share of ACCOUNTS long / short (not of money)
The 24 h high / low (the day's range bar) come from /api/ticker (/fapi/v1/ticker/24hr, already on the page).

Cost (the dashboard shares this server's Binance IP weight with the bot): 2 weight per coin per ``TTL_S`` (60 s) at most,
whoever asks and however many pages are open, and only for a coin somebody asks for (no thread, no timer); only the 7
traded coins are accepted. Each fetch has a short timeout (``TIMEOUT_S``); a coin is fetched by ONE request at a time
(others get the previous answer at once, or wait for that one fetch when there is none yet), so a hung Binance never
holds a worker for long. A failed part keeps its last good value for ``KEEP_S`` (marked ``stale``), then it is null with
the reason in ``errors``: never a made-up number. A test swaps ``FETCH``.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

BASE = "https://fapi.binance.com"
TTL_S = 60.0
TIMEOUT_S = 4.0
KEEP_S = 15 * 60.0              # a failed part shows its last good value (marked stale) this long, then nothing
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT")
HOUR_MS = 3_600_000

FETCH: Optional[Callable] = None        # tests set this; None = dash/app.py _get_json


def _fetch(url: str):
    if FETCH is not None:
        return FETCH(url)
    from ..app import _get_json
    return _get_json(url, timeout=TIMEOUT_S)


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def parse_oi(rows) -> dict:
    """open interest (USDT) at the newest 5-minute record and its change against the record about an hour earlier.
    ``rows`` is Binance's openInterestHist list, oldest first. Raises ValueError when there is no usable record."""
    pts = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        v, t = _f(r.get("sumOpenInterestValue")), _f(r.get("timestamp"))
        if v is not None and v > 0 and t is not None:
            pts.append((int(t), v))
    if not pts:
        raise ValueError("no open interest record")
    pts.sort()
    t1, v1 = pts[-1]
    chg = None
    older = [(t, v) for t, v in pts if 50 * 60_000 <= t1 - t <= 70 * 60_000]      # about an hour earlier (not a made-up span)
    if older:
        t0, v0 = min(older, key=lambda p: abs((t1 - p[0]) - HOUR_MS))
        chg = round(v1 / v0 - 1, 5)
    return {"usd": round(v1), "chg_1h": chg, "ts": t1}


def parse_ls(rows) -> dict:
    """the global long / short ACCOUNT ratio of the newest record (Binance's globalLongShortAccountRatio, newest last)."""
    last = None
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict):
            last = r
    if last is None:
        raise ValueError("no long/short record")
    ratio, lo, sh, t = _f(last.get("longShortRatio")), _f(last.get("longAccount")), _f(last.get("shortAccount")), _f(last.get("timestamp"))
    if ratio is None or ratio <= 0 or lo is None or sh is None or t is None:
        raise ValueError("bad long/short record")
    return {"ratio": round(ratio, 3), "long": round(lo, 4), "short": round(sh, 4), "ts": int(t)}


def _oi(sym: str) -> dict:
    return parse_oi(_fetch(f"{BASE}/futures/data/openInterestHist?symbol={sym}&period=5m&limit=13"))


def _ls(sym: str) -> dict:
    return parse_ls(_fetch(f"{BASE}/futures/data/globalLongShortAccountRatio?symbol={sym}&period=5m&limit=1"))


PARTS = {"oi": _oi, "ls": _ls}


class TopStats:
    """Per-coin cached answers, each refreshed at most every ``ttl`` seconds by whichever request comes first."""

    def __init__(self, ttl: float = TTL_S, clock: Callable[[], float] = time.time, parts: Optional[dict] = None):
        self.ttl, self.clock = ttl, clock
        self.parts = parts or PARTS
        self.guard = threading.Lock()
        self.locks: dict = {}
        self.cache: dict = {}            # symbol -> (fetched at s, answer)
        self.good: dict = {}             # (symbol, part) -> (fetched at s, value)
        self.fetches = 0

    def get(self, sym: str) -> dict:
        now = self.clock()
        hit = self.cache.get(sym)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        with self.guard:
            lock = self.locks.setdefault(sym, threading.Lock())
        if not lock.acquire(blocking=hit is None):
            return hit[1]                 # another request is already asking Binance: the previous answer, at once
        try:
            hit = self.cache.get(sym)
            now = self.clock()
            if hit and now - hit[0] < self.ttl:
                return hit[1]             # (the request we waited for just filled it)
            self.fetches += 1
            ans = self._fetch_all(sym, now)
            self.cache[sym] = (now, ans)
            return ans
        finally:
            lock.release()

    def _fetch_all(self, sym: str, now: float) -> dict:
        out: dict = {"symbol": sym, "ts": int(now * 1000), "errors": {}}
        # NOT ``with ThreadPoolExecutor``: its exit waits for every worker, so one Binance request that hangs (a socket timeout is per read,
        # a slow drip never trips it) would hold this request thread for as long as it hangs. One shared deadline for both parts instead;
        # a worker still running after it is left to finish alone (it only fills nothing: its answer is dropped).
        ex = ThreadPoolExecutor(max_workers=len(self.parts))
        deadline = time.monotonic() + TIMEOUT_S + 2.0
        try:
            futs = {k: ex.submit(fn, sym) for k, fn in self.parts.items()}
            for k, fut in futs.items():
                try:
                    v = fut.result(timeout=max(0.0, deadline - time.monotonic()))
                    self.good[(sym, k)] = (now, v)
                    out[k] = {**v, "stale": False}
                except Exception as exc:  # noqa: BLE001  (Binance down / blocked / slow / bad answer: the last good one, marked old)
                    g = self.good.get((sym, k))
                    out["errors"][k] = type(exc).__name__ or "Error"
                    out[k] = {**g[1], "stale": True} if g and now - g[0] <= KEEP_S else None
        finally:
            ex.shutdown(wait=False)
        out["ready"] = any(out.get(k) for k in self.parts)
        return out


def register(app, ctx) -> dict:
    from fastapi import HTTPException
    ts = TopStats()

    @app.get("/api/v4/topstats")
    def get_topstats(symbol: str = "BTCUSDT"):
        """Open interest (USDT, 1 h change) and the global long / short account ratio of one traded coin (cached 60 s)."""
        if symbol not in SYMBOLS:
            raise HTTPException(400, "이 코인은 지원하지 않습니다")
        return ts.get(symbol)

    return {"routes": ["/api/v4/topstats"], "topstats": ts}
