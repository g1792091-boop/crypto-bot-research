"""Build higher-timeframe bars from 1m bars, aligned to UTC boundaries."""

from __future__ import annotations

from typing import Iterable

from .models import Bar

TF_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
}


class _Bucket:
    __slots__ = ("start", "o", "h", "l", "c", "mo", "mh", "ml", "mc", "n", "mark_ok")

    def __init__(self, b: Bar, start: int):
        self.start = start
        self.o, self.h, self.l, self.c = b.open, b.high, b.low, b.close
        self.mo, self.mh, self.ml, self.mc = b.m_open, b.m_high, b.m_low, b.m_close
        self.mark_ok = b.mark_open is not None
        self.n = 1

    def add(self, b: Bar) -> None:
        self.h = max(self.h, b.high)
        self.l = min(self.l, b.low)
        self.c = b.close
        self.mh = max(self.mh, b.m_high)
        self.ml = min(self.ml, b.m_low)
        self.mc = b.m_close
        self.mark_ok = self.mark_ok and b.mark_open is not None
        self.n += 1


class Aggregator:
    """Feed 1m bars per symbol in order; get completed bars for every
    requested timeframe. A bucket that never receives its last minute is
    emitted as ``partial`` when the next bucket starts."""

    def __init__(self, timeframes: Iterable[str]):
        self.tfs = [tf for tf in TF_MS if tf in set(timeframes)]
        unknown = set(timeframes) - set(TF_MS)
        if unknown:
            raise ValueError(f"unknown timeframes {sorted(unknown)}")
        self.buckets: dict[tuple[str, str], _Bucket] = {}

    def _emit(self, sym: str, tf: str, bk: _Bucket) -> Bar:
        ms = TF_MS[tf]
        expected = ms // TF_MS["1m"]
        m = bk.mark_ok
        return Bar(sym, bk.start, bk.start + ms - 1, bk.o, bk.h, bk.l, bk.c,
                   bk.mo if m else None, bk.mh if m else None,
                   bk.ml if m else None, bk.mc if m else None,
                   partial=bk.n < expected)

    def add(self, b: Bar) -> list[tuple[str, Bar]]:
        out: list[tuple[str, Bar]] = []
        for tf in self.tfs:
            ms = TF_MS[tf]
            if tf == "1m":
                out.append((tf, b))
                continue
            start = b.open_time - b.open_time % ms
            key = (b.symbol, tf)
            bk = self.buckets.get(key)
            if bk is not None and bk.start != start:
                out.append((tf, self._emit(b.symbol, tf, bk)))
                bk = None
            if bk is None:
                bk = _Bucket(b, start)
                self.buckets[key] = bk
            else:
                bk.add(b)
            if b.close_time == start + ms - 1:
                out.append((tf, self._emit(b.symbol, tf, bk)))
                del self.buckets[key]
        return out
