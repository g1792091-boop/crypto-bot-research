"""Binance USD-M public market data for the demo lab bot (no key): 15m klines and funding rates, and the 30m bars
built from 15m bars (the 5-year study built its 30m bars the same way).

Only bars that closed at least SETTLE_MS before now are stored. The forming bar's open (the entry price of a signal
at the last close) is returned separately.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Callable, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from paperbot.binance import BinanceREST  # noqa: E402

from . import grid as G  # noqa: E402

M15 = 15 * 60 * 1000
M30 = 30 * 60 * 1000
SETTLE_MS = 8_000          # the rule bot's feed waits the same after a close (feed.py settle_ms)


class Market:
    """Public endpoints only. ``rest`` is injectable (tests replay recorded bars)."""

    def __init__(self, rest: Optional[BinanceREST] = None, clock_ms: Callable[[], int] = None,
                 pause: Callable[[float], None] = time.sleep):
        self.rest = rest or BinanceREST(max_retries=4, backoff=2.0)
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.pause = pause

    def klines15(self, coin: str, start_ms: Optional[int] = None, limit: int = 1500):
        """(closed rows [(ts, o, h, l, c, v)], forming (ts, open) or None)."""
        rows = self.rest.klines(G.binance_symbol(coin), "15m", start_time=start_ms, limit=limit)
        now = self.clock_ms()
        closed, forming = [], None
        for r in rows:
            t0, close_t = int(r[0]), int(r[6])
            if close_t + SETTLE_MS < now:
                closed.append((t0, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
            elif t0 <= now:
                forming = (t0, float(r[1]))
        return closed, forming

    def history15(self, coin: str, start_ms: int, end_ms: Optional[int] = None, gap_s: float = 1.5):
        """All closed 15m bars from start_ms (inclusive) up to now (or end_ms, exclusive), paged by 1500."""
        out = []
        forming = None
        t = int(start_ms)
        while True:
            rows, forming = self.klines15(coin, start_ms=t, limit=1500)
            rows = [r for r in rows if r[0] >= t and (end_ms is None or r[0] < end_ms)]
            out.extend(rows)
            if len(rows) < 1500 or (end_ms is not None and rows and rows[-1][0] + M15 >= end_ms):
                break
            t = rows[-1][0] + M15
            self.pause(gap_s)
        dedup = {}
        for r in out:
            dedup[r[0]] = r
        return [dedup[k] for k in sorted(dedup)], forming

    def funding(self, coin: str, start_ms: Optional[int] = None, limit: int = 1000):
        rows = self.rest.funding_rates(G.binance_symbol(coin), start_time=start_ms, limit=limit)
        return [(int(r["fundingTime"]), float(r["fundingRate"])) for r in rows]


def to30(b15: dict) -> dict:
    """30m bars from 15m bars: pairs (hh:00 + hh:15, hh:30 + hh:45) that are both present; incomplete pairs dropped."""
    ts = b15["ts"]
    if len(ts) < 2:
        z = np.zeros(0)
        return {"ts": z.astype(np.int64), "o": z, "h": z, "l": z, "c": z, "v": z, "i15": z.astype(np.int64)}
    first = (ts % M30) == 0
    i = np.flatnonzero(first[:-1] & (ts[1:] == ts[:-1] + M15))
    j = i + 1
    return {"ts": ts[i], "o": b15["o"][i], "h": np.maximum(b15["h"][i], b15["h"][j]),
            "l": np.minimum(b15["l"][i], b15["l"][j]), "c": b15["c"][j], "v": b15["v"][i] + b15["v"][j],
            "i15": j.astype(np.int64)}


def gaps(ts: np.ndarray, step: int = M15) -> int:
    """Number of missing 15m bars inside the series."""
    if len(ts) < 2:
        return 0
    d = np.diff(ts)
    return int(np.sum(np.maximum(d // step - 1, 0)))
