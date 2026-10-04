"""Live 1m bar feed from Binance USD-M REST, with gap backfill.

Each ``poll()`` fetches every closed 1m bar (last price and mark price) since
the last one seen, per symbol, and returns aligned steps
``(open_time, {symbol: Bar}, {symbol: funding_rate})`` in time order.

A step is released when every symbol has its bar, or once ``grace_ms`` has
passed after the bar closed (then missing symbols are reported as a data
gap). Only bars that closed at least ``settle_ms`` before the server clock
are used, so a still-forming bar is never passed on, nor one read in the
first moments after its close, when the exchange can still return a row
without the minute's last trades (docs/signal-recording.md, "1분봉을 확정 전에
읽는 문제").
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable, Optional

from .binance import BinanceREST, bars_from_klines
from .models import Bar
from .notify import INFO, WARN

MIN_MS = 60_000


class LiveFeed:
    def __init__(self, rest: BinanceREST, symbols, start_time: Optional[int] = None,
                 grace_ms: int = 20_000, stale_after_ms: int = 4 * MIN_MS,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                 on_event: Optional[Callable[[str, str], None]] = None,
                 clock_check_every: int = 60, max_clock_skew_ms: int = 1000,
                 settle_ms: int = 5_000):
        self.rest = rest
        self.symbols = list(symbols)
        self.grace_ms = grace_ms
        self.stale_after_ms = stale_after_ms
        self.clock_ms = clock_ms
        self.on_event = on_event or (lambda level, text: None)
        self.clock_check_every = clock_check_every
        self.max_clock_skew_ms = max_clock_skew_ms
        self.settle_ms = settle_ms

        self.next_open: dict[str, Optional[int]] = {s: start_time for s in self.symbols}
        self.buffer: dict[int, dict[str, Bar]] = defaultdict(dict)
        self.funding: dict[int, dict[str, float]] = defaultdict(dict)
        self.funding_since: dict[str, Optional[int]] = {s: start_time for s in self.symbols}
        self.last_emitted: Optional[int] = None
        self.last_progress_ms: Optional[int] = None
        self.stale = False
        self.skew_ms = 0
        self._polls = 0

    # ------------------------------------------------------------ clock
    def server_now(self) -> int:
        return self.clock_ms() + self.skew_ms

    def _check_clock(self) -> None:
        local = self.clock_ms()
        server = self.rest.server_time()
        self.skew_ms = server - local
        if abs(self.skew_ms) > self.max_clock_skew_ms:
            self.on_event(WARN, f"local clock off by {self.skew_ms} ms from Binance; "
                                f"using server time")

    # ------------------------------------------------------------ fetch
    def _fetch_symbol(self, sym: str, now: int) -> None:
        start = self.next_open[sym]
        if start is None:
            rows = self.rest.klines(sym, "1m", limit=3)
            closed = [r for r in rows if int(r[6]) + self.settle_ms < now]
            if not closed:
                return
            start = int(closed[-1][0])
            self.next_open[sym] = start
            if self.funding_since[sym] is None:
                self.funding_since[sym] = start
        while True:
            rows = self.rest.klines(sym, "1m", start_time=start, limit=1500)
            rows = [r for r in rows if int(r[6]) + self.settle_ms < now and int(r[0]) >= start]
            if not rows:
                return
            marks = self.rest.mark_klines(sym, "1m", start_time=start, limit=1500)
            bars = bars_from_klines(sym, rows, marks)
            missing_mark = sum(1 for b in bars if b.mark_open is None)
            if missing_mark:
                self.on_event(INFO, f"{sym}: {missing_mark} bars without mark price; "
                                    f"last price used for liquidation checks")
            expected = start
            for b in bars:
                if b.open_time != expected:
                    self.on_event(WARN, f"{sym}: exchange returned no bars for "
                                        f"{(b.open_time - expected) // MIN_MS} min "
                                        f"from {expected}")
                self.buffer[b.open_time][sym] = b
                expected = b.open_time + MIN_MS
            start = bars[-1].open_time + MIN_MS
            self.next_open[sym] = start
            if len(rows) < 1500:
                return

    def _fetch_funding(self, sym: str) -> None:
        since = self.funding_since[sym]
        if since is None:
            return
        rows = self.rest.funding_rates(sym, start_time=since)
        for r in rows:
            ft = int(r["fundingTime"])
            if ft < since:
                continue
            bucket = ft - ft % MIN_MS
            self.funding[bucket][sym] = float(r["fundingRate"])
            self.funding_since[sym] = ft + 1

    # ------------------------------------------------------------ poll
    def poll(self) -> list[tuple[int, dict[str, Bar], dict[str, float]]]:
        if self._polls % self.clock_check_every == 0:
            self._check_clock()
        self._polls += 1
        now = self.server_now()
        for sym in self.symbols:
            self._fetch_symbol(sym, now)
            self._fetch_funding(sym)

        steps = []
        for t in sorted(self.buffer):
            bars = self.buffer[t]
            complete = len(bars) == len(self.symbols)
            overdue = now > t + MIN_MS + self.grace_ms
            if not (complete or overdue):
                break
            if not complete:
                missing = sorted(set(self.symbols) - bars.keys())
                self.on_event(WARN, f"data gap at {t}: no bar for {missing}")
            steps.append((t, bars, self.funding.pop(t, {})))
            del self.buffer[t]
            self.last_emitted = t
        for t in [k for k in self.funding if self.last_emitted is not None and k <= self.last_emitted]:
            # Funding for a minute already released (arrived late): apply on next step.
            late = self.funding.pop(t)
            if steps:
                steps[-1][2].update(late)
            else:
                self.funding[self.last_emitted + MIN_MS].update(late)

        if steps:
            self.last_progress_ms = now
            if self.stale:
                self.stale = False
                self.on_event(INFO, "market data flowing again")
        elif self.last_progress_ms is not None and now - self.last_progress_ms > self.stale_after_ms:
            if not self.stale:
                self.stale = True
                self.on_event(WARN, f"no new closed bars for "
                                    f"{(now - self.last_progress_ms) // 1000}s")
        return steps
