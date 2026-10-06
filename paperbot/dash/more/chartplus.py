"""차트 위 얹기 (터미널 차트, 차트 화면): market liquidations over the candles and the lower panes' market series.

    GET /api/v4/chartplus/liq?symbol=BTCUSDT&tf=15m&t0=<first candle open, s>
        Market-wide forced orders of one coin from liq.db (paperbot/liqstream.py, read-only), cut into the chart's own
        bars: ``t0`` is the open time (seconds) of the first candle on screen and ``tf`` its width, so bar k is
        t0 + k * step. Per bar and side one bubble: the USDT sum, the count, the USDT-weighted average price and the
        biggest single order (its price and time). Plus ``cells`` for the price-bucket bars along the price axis:
        [bar index, price bucket, long USDT, short USDT] with ``tick`` the bucket's width in price. A SELL forced order
        closes a long, a BUY closes a short (the same rule as /api/liq). HONEST LIMITS, sent with every answer:
        ``since_ts`` (when the recorder started: nothing before it was heard, which is NOT "no liquidations"),
        ``gaps`` (the recorder's own disconnected spans, from conn_log), ``stale`` (no row for 2 hours), and
        ``note_ko``: Binance sends at most one liquidation per coin per second, so bursts are undercounted.
        No file: {"ready": false}. Cached 20 s.

    GET /api/v4/chartplus/series?symbol=BTCUSDT&kind=oi|ls|funding&tf=15m
        The lower panes' market series, fetched by the SERVER from Binance's public futures endpoints (never from the
        browser): ``oi`` = /futures/data/openInterestHist (open interest in USDT), ``ls`` =
        /futures/data/globalLongShortAccountRatio (long / short account ratio), ``funding`` = /fapi/v1/fundingRate
        (the settled rate every 8 hours). The period follows the chart's bar (``PERIOD_OF``). Binance keeps only the
        latest 30 days of the first two, said in ``note_ko``. One cached answer per (coin, kind, period), a short
        timeout (``FETCH_TIMEOUT_S``), one fetch at a time per answer. A failed fetch keeps the last good answer marked
        ``stale``; before any good answer it says {"ready": false, "failed": true, "why_ko": ...}: the page shows its
        own small 못 불러옴 note, never a flat line or a zero.

The CVD pane needs nothing from here: it is computed in the browser from the candles' taker-buy volume (/api/candles
``taker_buy``, kline field 9). A test (or the harness) swaps ``FETCH``; None = dash/app.py ``_get_json``.
"""
from __future__ import annotations

import math
import os
import sqlite3
import threading
import time
from typing import Callable, Optional

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT")
TF_S = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
        "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800, "1M": 2592000}
# the Binance "period" of the history endpoints (5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d) that matches a bar best: never
# finer than Binance has, a bar with no exact period takes the next shorter one
PERIOD_OF = {"1m": "5m", "3m": "5m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h",
             "8h": "6h", "12h": "12h", "1d": "1d", "3d": "1d", "1w": "1d", "1M": "1d"}
PERIOD_S = {"5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200, "1d": 86400}
KINDS = ("oi", "ls", "funding")
BASE_URL = "https://fapi.binance.com"
FETCH_TIMEOUT_S = 4.0
LIQ_TTL_S = 20.0
FAIL_RETRY_S = 20.0               # after a failed fetch the next try waits this long (the answer says so)
LIQ_STALE_MS = 2 * 3_600_000
BARS_MAX = 1500
CELLS_MAX = 20_000
GAP_MIN_MS = 45_000              # a disconnected span shorter than this is the scheduled 23-hour reconnect, not a gap
GAPS_MAX = 40
NOTE_LIQ_KO = "바이낸스 시장 전체 (우리 봇 아님) · 우리 기록기가 켜진 뒤 들은 것만 · 코인마다 1초에 1건만 알려 줘서 실제보다 적음"
NOTE_SERIES_KO = {
    "oi": "바이낸스가 주는 미결제약정 기록은 최근 30일뿐이라, 그 앞 구간은 비어 있습니다",
    "ls": "바이낸스가 주는 롱/숏 비율 기록은 최근 30일뿐이라, 그 앞 구간은 비어 있습니다",
    "funding": "바이낸스가 8시간마다 정산한 펀딩비 (그 사이는 비워 둠)",
}

FETCH: Optional[Callable] = None        # tests set this; None = dash/app.py _get_json


def _fetch(url: str):
    if FETCH is not None:
        return FETCH(url)
    from ..app import _get_json
    return _get_json(url, timeout=FETCH_TIMEOUT_S)


def _f(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _ro(path: Optional[str]) -> Optional[sqlite3.Connection]:
    if not path or not os.path.exists(path):
        return None
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        c.execute("PRAGMA query_only = 1")
        return c
    except sqlite3.Error:
        return None


def nice_tick(x: float) -> float:
    """A round price step (1, 2 or 5 x 10^k) at or just above ``x`` (> 0)."""
    if not (x > 0) or not math.isfinite(x):
        return 1.0
    e = math.floor(math.log10(x))
    m = x / 10 ** e
    for k in (1, 2, 5, 10):
        if m <= k + 1e-9:
            return k * 10 ** e
    return 10 ** (e + 1)


# ---------------------------------------------------------------- the liquidation bars
_USD = "COALESCE(NULLIF(avg_price, 0), price) * COALESCE(NULLIF(filled_qty, 0), qty)"
_PX = "COALESCE(NULLIF(avg_price, 0), price)"


def _gaps(c: sqlite3.Connection, lo: int, now: int) -> tuple:
    """(recorder start or None, [[from, to], ...] the spans in [lo, now] the stream was NOT connected, from conn_log)."""
    try:
        ev = [(int(t), e) for t, e in c.execute("SELECT ts, event FROM conn_log WHERE event IN ('connected', 'disconnected', 'stopped') ORDER BY ts")]
    except sqlite3.Error:
        return None, []
    start = next((t for t, e in ev if e == "connected"), None)
    out, down = [], None
    for t, e in ev:
        if e == "connected":
            if down is not None and t - down >= GAP_MIN_MS:
                out.append([down, t])
            down = None
        elif down is None:
            down = t
    if down is not None and now - down >= GAP_MIN_MS:
        out.append([down, now])
    out = [[max(a, lo), b] for a, b in out if b > lo]
    return start, out[-GAPS_MAX:]


def liq_bars(liq_path: Optional[str], symbol: str, t0_s: int, step_s: int, now_ms: int) -> dict:
    """The answer of /api/v4/chartplus/liq (pure given the file: tested without the server)."""
    note = NOTE_LIQ_KO
    if not liq_path or not os.path.exists(liq_path):
        return {"ready": False, "recorder": False, "why": "liq.db 없음 (강제청산 기록기가 아직 돌지 않음)", "note_ko": note}
    c = _ro(liq_path)
    if c is None:                                   # the file is there but cannot be opened: not "no recorder", not "no liquidations"
        return {"ready": False, "failed": True, "recorder": True, "why": "liq.db를 열지 못함", "note_ko": note}
    lo, step_ms = int(t0_s) * 1000, int(step_s) * 1000
    try:
        start, gaps = _gaps(c, lo, now_ms)
        newest = c.execute("SELECT received_ts FROM liq ORDER BY rowid DESC LIMIT 1").fetchone()
        newest = int(newest[0]) if newest and newest[0] is not None else None
        first = c.execute("SELECT received_ts FROM liq ORDER BY rowid LIMIT 1").fetchone()
        first = int(first[0]) if first and first[0] is not None else None
        since = start if start is not None else first
        recent = [r[0] for r in c.execute(f"SELECT {_PX} FROM liq WHERE symbol = ? ORDER BY trade_ts DESC LIMIT 201", (symbol,)) if r[0]]
        tick = nice_tick(sorted(recent)[len(recent) // 2] * 0.0002) if recent else None
        inner = (f"SELECT (trade_ts - {lo}) / {step_ms} AS b, side, {_PX} AS px, {_USD} AS usd, trade_ts AS ts FROM liq "
                 f"WHERE symbol = ? AND trade_ts >= ? AND trade_ts <= ?")
        bars = []
        # per bar and side (the "bare" px / ts columns of MAX(usd) are the biggest order's: SQLite's documented rule)
        for b, side, n, usd, upx, big, bpx, bts in c.execute(
                f"SELECT b, side, COUNT(*), SUM(usd), SUM(usd * px), MAX(usd), px, ts FROM ({inner}) GROUP BY b, side ORDER BY b",
                (symbol, lo, now_ms)):
            if usd is None or not usd > 0:
                continue
            bars.append({"t": int(t0_s) + int(b) * int(step_s), "side": "long" if side == "SELL" else "short", "usd": round(float(usd), 2),
                         "n": int(n), "px": round(float(upx) / float(usd), 8),
                         "big": {"usd": round(float(big), 2), "px": float(bpx), "ts": int(bts)}})
        cells, capped = [], False
        if tick:
            for b, pb, side, usd in c.execute(
                    f"SELECT b, CAST(px / ? AS INTEGER), side, SUM(usd) FROM ({inner}) GROUP BY 1, 2, side ORDER BY 1, 2",
                    (float(tick), symbol, lo, now_ms)):
                if len(cells) >= CELLS_MAX:
                    capped = True
                    break
                if cells and cells[-1][0] == int(b) and cells[-1][1] == int(pb):
                    cell = cells[-1]
                else:
                    cell = [int(b), int(pb), 0.0, 0.0]
                    cells.append(cell)
                cell[2 if side == "SELL" else 3] += round(float(usd or 0), 2)
    except sqlite3.Error as exc:
        return {"ready": False, "failed": True, "recorder": True, "why": f"liq.db를 읽지 못함 ({type(exc).__name__})", "note_ko": note}
    finally:
        c.close()
    return {"ready": True, "recorder": True, "symbol": symbol, "step_s": int(step_s), "t0": int(t0_s), "since_ts": since,
            "last_record_ts": newest, "stale": newest is None or now_ms - newest > LIQ_STALE_MS, "gaps": gaps, "tick": tick,
            "bars": bars, "cells": cells, "capped": capped, "n": sum(b["n"] for b in bars), "at": now_ms, "note_ko": note}


# ---------------------------------------------------------------- the lower panes' market series (Binance, by the server)
def parse_series(kind: str, rows) -> list:
    """Binance rows -> [[ts ms, value, ...]] oldest first, finite numbers only.
    oi: [ts, open interest in USDT] · ls: [ts, long/short account ratio, long account share] · funding: [ts, rate]."""
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        if kind == "oi":
            ts, v = _f(r.get("timestamp")), _f(r.get("sumOpenInterestValue"))
            row = [int(ts), v] if ts is not None and v is not None and v >= 0 else None
        elif kind == "ls":
            ts, v, la = _f(r.get("timestamp")), _f(r.get("longShortRatio")), _f(r.get("longAccount"))
            row = [int(ts), v, la] if ts is not None and v is not None and v > 0 else None
        else:
            ts, v = _f(r.get("fundingTime")), _f(r.get("fundingRate"))
            row = [int(ts), v] if ts is not None and v is not None else None
        if row:
            out.append(row)
    out.sort(key=lambda x: x[0])
    return out


def series_url(symbol: str, kind: str, period: str) -> str:
    if kind == "oi":
        return f"{BASE_URL}/futures/data/openInterestHist?symbol={symbol}&period={period}&limit=500"
    if kind == "ls":
        return f"{BASE_URL}/futures/data/globalLongShortAccountRatio?symbol={symbol}&period={period}&limit=500"
    return f"{BASE_URL}/fapi/v1/fundingRate?symbol={symbol}&limit=1000"


def series_ttl(kind: str, period: str) -> float:
    if kind == "funding":
        return 600.0
    return 60.0 if PERIOD_S.get(period, 900) <= 1800 else 180.0


class Series:
    """One cached answer per (coin, kind, period), refreshed by whichever request comes first after its TTL. One fetch at
    a time per answer (a second request waits for the first one's result, never starts another), a short timeout, a
    failed fetch kept for FAIL_RETRY_S so a dead Binance is not asked on every page poll."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.cells: dict = {}
        self.fetches = 0

    def _cell(self, key) -> dict:
        with self.lock:
            if len(self.cells) > 200:
                self.cells.clear()
            return self.cells.setdefault(key, {"lock": threading.Lock(), "good": None, "at": None, "failed_at": None, "why": None})

    def get(self, symbol: str, kind: str, tf: str) -> dict:
        period = PERIOD_OF[tf] if kind != "funding" else "8h"
        cell = self._cell((symbol, kind, period))
        ttl = series_ttl(kind, period)
        now = self.clock()
        if cell["good"] is not None and cell["at"] is not None and now - cell["at"] < ttl:
            return self._answer(cell, symbol, kind, period, stale=False)
        if cell["failed_at"] is not None and now - cell["failed_at"] < FAIL_RETRY_S:
            return self._answer(cell, symbol, kind, period, stale=True)
        with cell["lock"]:
            now = self.clock()
            if cell["good"] is not None and cell["at"] is not None and now - cell["at"] < ttl:
                return self._answer(cell, symbol, kind, period, stale=False)
            if cell["failed_at"] is not None and now - cell["failed_at"] < FAIL_RETRY_S:
                return self._answer(cell, symbol, kind, period, stale=True)
            self.fetches += 1
            try:
                pts = parse_series(kind, _fetch(series_url(symbol, kind, period)))
                if not pts:
                    raise ValueError("empty")
                cell["good"], cell["at"], cell["failed_at"], cell["why"] = pts, now, None, None
            except Exception as exc:  # noqa: BLE001  (Binance down / blocked / slow / odd answer: the last good one, marked old)
                cell["failed_at"] = now
                cell["why"] = "시간 초과" if "timed out" in str(exc).lower() or type(exc).__name__ in ("TimeoutError", "timeout") else \
                    "받은 자료가 비어 있음" if isinstance(exc, ValueError) else "연결 실패"
            return self._answer(cell, symbol, kind, period, stale=cell["failed_at"] is not None)

    def _answer(self, cell: dict, symbol: str, kind: str, period: str, stale: bool) -> dict:
        good = cell["good"]
        if good is None:
            return {"ready": False, "failed": True, "kind": kind, "symbol": symbol,
                    "why_ko": f"바이낸스에서 못 불러옴 ({cell['why'] or '연결 실패'})", "retry_s": int(FAIL_RETRY_S)}
        out = {"ready": True, "kind": kind, "symbol": symbol, "period": period, "period_s": PERIOD_S.get(period, 28800),
               "points": good, "oldest": good[0][0], "newest": good[-1][0], "fetched_at": int(cell["at"] * 1000),
               "stale": bool(stale), "note_ko": NOTE_SERIES_KO[kind]}
        if stale:
            out["why_ko"] = f"바이낸스에서 새로 못 불러옴 ({cell['why'] or '연결 실패'}) · 아래는 마지막으로 받은 값"
        return out


def register(app, ctx) -> dict:
    here = os.path.dirname(os.path.abspath(ctx.db))
    cache: dict = {}
    lock = threading.Lock()
    series = Series()
    from fastapi import HTTPException

    def cached(key, ttl: float, fn):
        hit = cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        with lock:
            hit = cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
            if len(cache) > 64:
                cache.clear()
            v = fn()
            cache[key] = (time.time(), v)
            return v

    @app.get("/api/v4/chartplus/liq")
    def get_chartplus_liq(symbol: str = "BTCUSDT", tf: str = "15m", t0: int = 0):
        """Market-wide forced orders of one coin cut into the chart's bars + price buckets (liq.db, read-only, 20 s)."""
        if symbol not in SYMBOLS:
            raise HTTPException(400, "unknown symbol")
        if tf not in TF_S:
            raise HTTPException(400, "unknown interval")
        step = TF_S[tf]
        now = int(time.time() * 1000)
        t0 = int(t0)
        if t0 <= 0 or t0 * 1000 > now:
            raise HTTPException(400, "bad t0")
        floor_t = now // 1000 - BARS_MAX * step                # at most BARS_MAX bars back (kept on the client's bar grid)
        if t0 < floor_t:
            t0 += -(-(floor_t - t0) // step) * step
        return cached(("liq", symbol, tf, t0), LIQ_TTL_S, lambda: liq_bars(os.path.join(here, "liq.db"), symbol, t0, step, now))

    @app.get("/api/v4/chartplus/series")
    def get_chartplus_series(symbol: str = "BTCUSDT", kind: str = "oi", tf: str = "15m"):
        """Open interest / long-short ratio / funding history of one coin, fetched from Binance by the server (cached)."""
        if symbol not in SYMBOLS:
            raise HTTPException(400, "unknown symbol")
        if kind not in KINDS:
            raise HTTPException(400, "unknown kind")
        if tf not in TF_S:
            raise HTTPException(400, "unknown interval")
        return series.get(symbol, kind, tf)

    return {"routes": ["/api/v4/chartplus/liq", "/api/v4/chartplus/series"], "series": series}
