"""봇 매물대 (the 차트's and 터미널's 매물대 overlay, 'compare with the bot's own levels'): read-only.

    GET /api/v4/vplevels?symbol=BTCUSDT&tf=15m

    {"ready": true, "symbol": "BTCUSDT", "tf": "15m", "bar": <open of the last closed bar, ms>,
     "bars": 200, "bins": 50, "share": 0.7,
     "levels": [{"kind": 51, "key": "poc", "ko": "매물 최다 가격", "price": 61234.5},
                {"kind": 52, "key": "vah", "ko": "매물대 위 끝",   "price": 61900.0},
                {"kind": 53, "key": "val", "ko": "매물대 아래 끝", "price": 60800.0}]}
    {"ready": false, "why": "tf"}        the bot uses these levels on its four traded timeframes only (15m / 30m / 1h / 4h)
    {"ready": false, "why": "bars"}      fewer than 200 closed bars, no volume or a flat range (nothing to compute)

The numbers are the bot's own: ``research/entry_study/sr.py volume_profile`` (loaded by ``entry_marks.sr_module``, run
unchanged, the function that makes kinds 51 / 52 / 53 of every recorded signal and of /api/levels' chart lines) on the
last 200 CLOSED bars of the chart's timeframe: 50 equal price bins over their lowest low .. highest high, each bar's whole
volume in the bin of its typical price (high + low + close) / 3, POC = centre of the fullest bin, the 70 % value area
grown from it. The chart's own profile (screens/chart-vp.js) spreads each bar's volume over its whole high-low range
instead, so the two differ a little; this route only lets the owners compare them. Descriptive: nothing trades on it
(research/entry_study found no effect on outcomes).

Cost: the bars come from the dashboard's own bar fetcher (``ctx.frames``: fetch_frame, 60 s cache, one klines request of
about 205 bars, weight 2); the answer is kept per (coin, timeframe, last closed bar) so every viewer and every poll of
the page (every 2 minutes) shares one computation, and a fetch that takes longer than ``TIMEOUT_S`` answers 503 at once
(the page says the bot's lines did not load; it never reads as "no levels") while the fetch finishes in the background.
A failed fetch after a good answer returns that answer marked ``stale``.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException

BARS = 200                      # sr.VP_BARS (checked against the research file when the module runs)
FETCH_BARS = BARS + 5           # the forming bar is dropped by the fetcher
TIMEOUT_S = 6.0
KEYS = ((51, "poc"), (52, "vah"), (53, "val"))      # sr.py KIND: 51 POC, 52 VAH, 53 VAL (the column order of volume_profile)
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="vplevels")


def levels_of(df, tf: str, sr=None) -> dict:
    """The bot's 매물대 on the last closed bar of ``df`` (columns ts, high, low, close, volume), or {"ready": False, "why"}."""
    import numpy as np
    from ... import entry_marks
    sr = sr or entry_marks.sr_module()
    if df is None or len(df) < BARS:
        return {"ready": False, "why": "bars"}
    with entry_marks._contained():
        n = len(df)
        vp = sr.volume_profile(np.asarray(df["high"], float), np.asarray(df["low"], float), np.asarray(df["close"], float),
                               np.asarray(df["volume"], float), np.array([n - 1]))
    row = [float(x) for x in vp[0]]
    if not all(x == x and abs(x) != float("inf") for x in row):
        return {"ready": False, "why": "bars"}
    ts = df["ts"].iloc[-1]
    return {"ready": True, "tf": tf, "bar": int(ts.value // 1_000_000) if hasattr(ts, "value") else int(ts), "bars": int(sr.VP_BARS),
            "bins": int(sr.VP_BINS), "share": float(sr.VP_SHARE),
            "levels": [{"kind": k, "key": key, "ko": entry_marks.KIND_KO.get(k, str(k)), "price": p} for (k, key), p in zip(KEYS, row)]}


class BotProfile:
    """One answer per (coin, timeframe, last closed bar), kept; the last good one is returned stale when a fetch fails."""

    def __init__(self, frames, tfs, clock=time.time):
        self.frames, self.tfs, self.clock = frames, tuple(tfs), clock
        self.lock = threading.Lock()
        self.good: dict = {}                    # (symbol, tf) -> (checked at, answer)
        self.inflight: dict = {}                # (symbol, tf) -> the fetch still running (a slow Binance is asked once, not once per poll)

    def get(self, symbol: str, tf: str) -> dict:
        if tf not in self.tfs:
            return {"ready": False, "why": "tf"}
        key = (symbol, tf)
        with self.lock:
            hit = self.good.get(key)
        if hit and self.clock() - hit[0] < 30:                  # the bar rarely changes inside 30 s: no fetch at all
            return hit[1]
        with self.lock:
            fut = self.inflight.get(key)
            if fut is None or fut.done():
                fut = self.inflight[key] = _POOL.submit(self.frames, symbol, tf, FETCH_BARS)
        try:
            df = fut.result(timeout=TIMEOUT_S)
            out = {**levels_of(df, tf), "symbol": symbol}
        except Exception:  # noqa: BLE001  (Binance slow (TimeoutError) / down / bad bars: the last good answer, else 503)
            if hit and hit[1].get("ready"):
                return {**hit[1], "stale": True}
            raise HTTPException(503, "no price data for the bot's 매물대")
        with self.lock:
            self.good[key] = (self.clock(), out)
        return out


def register(app, ctx) -> dict:
    from ..app import LEVEL_TFS, TICKER_SYMBOLS
    bp = BotProfile(ctx.frames, LEVEL_TFS)

    @app.get("/api/v4/vplevels")
    def get_vplevels(symbol: str = "BTCUSDT", tf: str = "15m"):
        """The bot's own 매물대 (POC / VAH / VAL of its last 200 closed bars) for the chart's comparison lines."""
        if symbol not in TICKER_SYMBOLS:
            raise HTTPException(400, "unknown symbol")
        return bp.get(symbol, tf)

    return {"routes": ["/api/v4/vplevels"], "profile": bp}
