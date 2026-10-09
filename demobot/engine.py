"""The demo lab bot's state and data path: bars -> signals of every setting -> trade outcomes (cells).

* ``warm``: the first fill. 26 weeks of history (plus indicator warm-up) from Binance, signals of all 1,666 settings
  on every bar (full series, as the 5-year study), outcomes of every bar and side.
* ``tick``: every closed 15m bar. New bars; signals of all settings on a trailing window of WINDOW bars of the
  timeframe (the last bar only); new cells; open cells recomputed with the new bars.

Accounts, ranking, judgment and snapshots are in their own modules and read this state.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import numpy as np

from . import cells as CL
from . import data as D
from . import grid as G
from . import locked as LK
from . import store as ST

WEEK_MS = 7 * 86400 * 1000
HISTORY_WEEKS = 26
WINDOW = 1500                     # trailing bars of the timeframe for live signals
WARMUP_15M = 3200                 # 15m bars fetched before the history start (indicator warm-up, 30m needs 2x)
BULK_FROM = 6                     # more new bars than this in one tick: one series for all of them
RETAIN_MS = (HISTORY_WEEKS * 7 + 35) * 86400 * 1000   # signals kept in memory (26 weeks + the friend rule's margin)


class SigBuf:
    """Signals of one (coin, tf, strat): flat arrays (ts, combo, side) in time order, appendable."""

    def __init__(self):
        self.parts = []
        self._cat = None

    def add(self, ts: np.ndarray, combo: np.ndarray, side: np.ndarray) -> None:
        if len(ts):
            self.parts.append((np.asarray(ts, np.int64), np.asarray(combo, np.int16), np.asarray(side, np.int8)))
            self._cat = None

    def arrays(self):
        if self._cat is None:
            if not self.parts:
                self._cat = (np.zeros(0, np.int64), np.zeros(0, np.int16), np.zeros(0, np.int8))
            else:
                ts = np.concatenate([p[0] for p in self.parts])
                cb = np.concatenate([p[1] for p in self.parts])
                sd = np.concatenate([p[2] for p in self.parts])
                o = np.argsort(ts, kind="stable")
                self._cat = (ts[o], cb[o], sd[o])
                self.parts = [self._cat]
        return self._cat

    def trim(self, min_ts: int) -> None:
        """Drop signals older than min_ts from memory (the database keeps them)."""
        ts, cb, sd = self.arrays()
        a = int(np.searchsorted(ts, min_ts))
        if a:
            self._cat = (ts[a:].copy(), cb[a:].copy(), sd[a:].copy())
            self.parts = [self._cat]

    def last_ts(self) -> Optional[int]:
        ts = self.arrays()[0]
        return int(ts[-1]) if len(ts) else None


class Engine:
    def __init__(self, conn, market: Optional[D.Market] = None, clock_ms: Callable[[], int] = None,
                 log: Callable[..., None] = print):
        self.conn = conn
        self.market = market or D.Market()
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.log = log
        self.b15 = {c: None for c in G.COINS}
        self.forming = {c: None for c in G.COINS}
        self.books = {(c, tf): CL.Book(c, tf) for c in G.COINS for tf in G.TFS}
        self.sigs = {(c, tf, s): SigBuf() for c in G.COINS for tf in G.TFS for s in G.STRATS}
        self.funding = {c: (np.zeros(0, np.int64), np.zeros(0)) for c in G.COINS}
        self.issues: list = []
        self.new_sig_bars: list = []     # (coin, tf, ts) signal bars added by the last tick

    # ------------------------------------------------------------------ facts
    @property
    def history_start(self) -> Optional[int]:
        return ST.get_meta(self.conn, "history_start_ms")

    @property
    def live_start(self) -> Optional[int]:
        return ST.get_meta(self.conn, "live_start_ms")

    def last_bar(self, tf: str = "15m") -> Optional[int]:
        vals = [int(b.ts[-1]) for (c, t), b in self.books.items() if t == tf and len(b)]
        return min(vals) if vals else None

    def bars_tf(self, coin: str, tf: str) -> dict:
        b = self.b15[coin]
        if tf == "15m":
            return b
        return D.to30(b)

    # ------------------------------------------------------------------ load
    def load(self) -> None:
        """Everything from the database (restart)."""
        hs = self.history_start
        if hs is None:
            raise RuntimeError("no history yet: run `python -m demobot warm` first")
        forming = ST.get_meta(self.conn, "forming", {}) or {}
        for c in G.COINS:
            self.b15[c] = ST.load_bars(self.conn, c)
            self.funding[c] = ST.load_funding(self.conn, c)
            f = forming.get(c)
            self.forming[c] = tuple(f) if f else None
            for tf in G.TFS:
                book = self.books[(c, tf)]
                book.load(self.conn)
                # open cells are stored only when created: bring them up to the stored bars (no write)
                rows = book.open_rows()
                for c0 in range(0, len(rows), 4000):
                    book.update(rows[c0:c0 + 4000], self.b15[c], forming=self.forming[c], only_changed=True)
                for s in G.STRATS:
                    buf = SigBuf()
                    keep = self.clock_ms() - RETAIN_MS
                    ls = self.live_start
                    if ls:
                        keep = min(keep, ls - 35 * 86400 * 1000)
                    buf.add(*ST.load_sigs(self.conn, c, tf, s, since_ms=max(hs, keep)))
                    self.sigs[(c, tf, s)] = buf

    # ------------------------------------------------------------------ warm
    def warm(self, weeks: float = HISTORY_WEEKS, end_ms: Optional[int] = None) -> dict:
        """First fill: history bars, all signals and all cells. Safe to run again (replaces the history)."""
        t_start = time.time()
        now = end_ms if end_ms is not None else self.clock_ms()
        last_close = (now // D.M15) * D.M15             # bars before this open time are closed
        hist0 = int(last_close - weeks * WEEK_MS) // D.M30 * D.M30
        fetch0 = hist0 - WARMUP_15M * D.M15
        out = {"history_start_ms": hist0}
        for c in G.COINS:
            rows, forming = self.market.history15(c, fetch0, end_ms=end_ms)
            with ST.Tx(self.conn):
                ST.put_bars(self.conn, c, rows)
            self.forming[c] = forming
            self.log("warm bars", c, len(rows))
            try:
                fr = self.market.funding(c, start_ms=fetch0)
                with ST.Tx(self.conn):
                    ST.put_funding(self.conn, c, fr)
            except Exception as exc:          # funding is optional for the accounts
                self.issues.append(f"funding {c}: {type(exc).__name__}")
        for c in G.COINS:
            self.b15[c] = ST.load_bars(self.conn, c)
            self.funding[c] = ST.load_funding(self.conn, c)
            gp = D.gaps(self.b15[c]["ts"])
            if gp:
                self.issues.append(f"{c}: {gp} missing 15m bars in the history")
        with ST.Tx(self.conn):
            self.conn.execute("DELETE FROM sigs")
            self.conn.execute("DELETE FROM cells")
        for c in G.COINS:
            for tf in G.TFS:
                t0 = time.time()
                bt = self.bars_tf(c, tf)
                df = LK.frame(bt["ts"], bt["o"], bt["h"], bt["l"], bt["c"], bt["v"], tf)
                atr = LK.atr14(df)
                keep = np.flatnonzero(bt["ts"] >= hist0)
                rows = []
                buf = {}
                for s in G.STRATS:
                    sides = LK.grid_sides(s, df, tf)              # (ncombo, nbars)
                    sub = sides[:, keep]
                    cb, bi = np.nonzero(sub)
                    sd = sub[cb, bi]
                    ts_sig = bt["ts"][keep][bi]
                    o = np.lexsort((cb, ts_sig))
                    cb, sd, ts_sig = cb[o].astype(np.int16), sd[o].astype(np.int8), ts_sig[o]
                    b = SigBuf()
                    b.add(ts_sig, cb, sd)
                    buf[s] = b
                    # one DB row per bar: longs / shorts combo lists
                    for t in np.unique(ts_sig):
                        a, z = np.searchsorted(ts_sig, [t, t + 1])
                        cc, ss = cb[a:z], sd[a:z]
                        rows.append((c, tf, int(t), s, cc[ss > 0], cc[ss < 0], "warm"))
                with ST.Tx(self.conn):
                    ST.put_sigs_many(self.conn, rows)
                for s in G.STRATS:
                    self.sigs[(c, tf, s)] = buf[s]
                book = CL.Book(c, tf)
                kk = book.add_bars(bt["ts"][keep], atr[keep])
                dbrows = []
                for c0 in range(0, len(kk), 4000):
                    dbrows.extend(book.update(kk[c0:c0 + 4000], self.b15[c], forming=self.forming[c]))
                with ST.Tx(self.conn):
                    ST.put_cells(self.conn, dbrows)
                self.books[(c, tf)] = book
                self.log("warm", c, tf, "signals", sum(len(buf[s].arrays()[0]) for s in G.STRATS), "cells",
                         len(dbrows), f"{time.time() - t0:.0f}s")
        with ST.Tx(self.conn):
            ST.set_meta(self.conn, "history_start_ms", int(hist0))
            ST.set_meta(self.conn, "warm_done_ms", int(self.clock_ms()))
            ST.set_meta(self.conn, "warm_issues", self.issues)
        out["seconds"] = round(time.time() - t_start, 1)
        out["issues"] = list(self.issues)
        return out

    # ------------------------------------------------------------------ tick
    def fetch_new(self) -> dict:
        """New closed 15m bars of every coin (paged when behind). Returns {coin: n_new}."""
        got = {}
        for c in G.COINS:
            b = self.b15[c]
            last = int(b["ts"][-1]) if b is not None and len(b["ts"]) else None
            start = (last + D.M15) if last is not None else None
            try:
                if start is not None and self.clock_ms() - start > 4 * D.M15:
                    rows, forming = self.market.history15(c, start)
                else:
                    rows, forming = self.market.klines15(c, start_ms=start, limit=6 if start else 1500)
            except Exception as exc:
                self.issues.append(f"{c} 시세 받기 실패: {type(exc).__name__}")
                got[c] = 0
                continue
            rows = [r for r in rows if last is None or r[0] > last]
            self.forming[c] = forming
            if rows:
                with ST.Tx(self.conn):
                    ST.put_bars(self.conn, c, rows)
                arr = np.array(rows, float)
                nb = {"ts": arr[:, 0].astype(np.int64), "o": arr[:, 1], "h": arr[:, 2], "l": arr[:, 3],
                      "c": arr[:, 4], "v": arr[:, 5]}
                if b is None or not len(b["ts"]):
                    self.b15[c] = nb
                else:
                    self.b15[c] = {k: np.concatenate([b[k], nb[k]]) for k in b}
            got[c] = len(rows)
        ST.set_meta(self.conn, "forming", {c: list(v) if v else None for c, v in self.forming.items()})
        return got

    def refresh_funding(self) -> None:
        for c in G.COINS:
            ts, _r = self.funding[c]
            start = int(ts[-1]) + 1 if len(ts) else self.history_start
            try:
                fr = self.market.funding(c, start_ms=start)
            except Exception as exc:
                self.issues.append(f"{c} 펀딩비 받기 실패: {type(exc).__name__}")
                continue
            if fr:
                with ST.Tx(self.conn):
                    ST.put_funding(self.conn, c, fr)
                self.funding[c] = ST.load_funding(self.conn, c)

    def signals_for_new_bars(self) -> list:
        """Signals of all settings for every signal bar newer than the book's last bar. Returns the new
        (coin, tf, ts) bars."""
        new = []
        for c in G.COINS:
            for tf in G.TFS:
                book = self.books[(c, tf)]
                bt = self.bars_tf(c, tf)
                if not len(bt["ts"]):
                    continue
                last = int(book.ts[-1]) if len(book) else self.history_start - 1
                pos = np.flatnonzero(bt["ts"] > last)
                if not len(pos):
                    continue
                lo = max(0, int(pos[0]) - WINDOW + 1)
                rows = []
                bars_new = bt["ts"][pos]
                atr_new = np.full(len(pos), np.nan)
                if len(pos) > BULK_FROM:
                    sl = slice(lo, int(pos[-1]) + 1)
                    df = LK.frame(bt["ts"][sl], bt["o"][sl], bt["h"][sl], bt["l"][sl], bt["c"][sl], bt["v"][sl], tf)
                    atr = LK.atr14(df)
                    rel = pos - lo
                    atr_new = atr[rel]
                    for s in G.STRATS:
                        sides = LK.grid_sides(s, df, tf)[:, rel]
                        self._store_sides(c, tf, s, bars_new, sides, rows)
                else:
                    for j, p in enumerate(pos):
                        sl = slice(max(0, int(p) - WINDOW + 1), int(p) + 1)
                        df = LK.frame(bt["ts"][sl], bt["o"][sl], bt["h"][sl], bt["l"][sl], bt["c"][sl],
                                      bt["v"][sl], tf)
                        atr_new[j] = LK.atr14(df)[-1]
                        for s in G.STRATS:
                            sides = LK.grid_sides(s, df, tf, last_only=True)[:, None]
                            self._store_sides(c, tf, s, bars_new[j:j + 1], sides, rows)
                with ST.Tx(self.conn):
                    ST.put_sigs_many(self.conn, rows)
                book.add_bars(bars_new, atr_new)
                new.extend((c, tf, int(t)) for t in bars_new)
        return new

    def _store_sides(self, c, tf, s, bars_ts, sides, rows) -> None:
        cb, bi = np.nonzero(sides)
        sd = sides[cb, bi]
        ts_sig = bars_ts[bi]
        o = np.lexsort((cb, ts_sig))
        cb, sd, ts_sig = cb[o].astype(np.int16), sd[o].astype(np.int8), ts_sig[o]
        self.sigs[(c, tf, s)].add(ts_sig, cb, sd)
        for t in bars_ts:
            m = ts_sig == t
            rows.append((c, tf, int(t), s, cb[m & (sd > 0)], cb[m & (sd < 0)], "live"))

    def update_cells(self) -> int:
        """Compute new and open cells with the current bars; returns the number of rows written."""
        n = 0
        for (c, tf), book in self.books.items():
            rows = book.open_rows()
            if not len(rows) or self.b15[c] is None:
                continue
            dbrows = []
            for c0 in range(0, len(rows), 4000):
                dbrows.extend(book.update(rows[c0:c0 + 4000], self.b15[c], forming=self.forming[c],
                                          only_changed=True))
            with ST.Tx(self.conn):
                ST.put_cells(self.conn, dbrows)
            n += len(dbrows)
        return n

    def tick(self) -> dict:
        """One live step. Returns facts for the status snapshot."""
        t0 = time.time()
        self.issues = []
        got = self.fetch_new()
        if self.live_start is None:
            ls = self.last_bar("15m")
            with ST.Tx(self.conn):
                ST.set_meta(self.conn, "live_start_ms", int((ls or 0) + D.M15))
        new = self.signals_for_new_bars()
        self.new_sig_bars = new
        cut = self.clock_ms() - RETAIN_MS
        if self.live_start:                    # the accounts replay every live signal: never drop those
            cut = min(cut, self.live_start - 35 * 86400 * 1000)
        for buf in self.sigs.values():
            if buf.parts and buf.arrays()[0][:1].size and buf.arrays()[0][0] < cut - 86400 * 1000:
                buf.trim(cut)
        ncell = self.update_cells()
        for c in G.COINS:
            gp = D.gaps(self.b15[c]["ts"][-200:]) if self.b15[c] is not None else 0
            if gp:
                self.issues.append(f"{G.coin_ko(c)} 최근 15분봉 {gp}개 빠짐")
        return {"new_bars": got, "new_signal_bars": len(new), "cells_written": ncell,
                "seconds": round(time.time() - t0, 1)}
