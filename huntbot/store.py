"""The bar store (store.db, SQLite WAL): 5m klines (last price), 5m mark-price klines, funding, open interest, coin
status, the feed's completeness mark. One writer (huntbot-feed); the runner and later the AI judge only read.

Tables (names follow docs/aibot/hunt_judge/SPEC.md 3 where it names them):

* ``bars_5m``  (symbol, open_ms) -> o h l c, v (base volume), qv (quote volume), seen_ms (the feed's clock when the row
  arrived), ins (the feed's insert sequence: the runner reads only rows with ins > what it has)
* ``mark_5m``  (symbol, open_ms) -> o h l c, seen_ms           (stored, not read by the hunt machine: H 2)
* ``funding``  (symbol, calc_ms) -> rate, seen_ms, ins
* ``oi``       (symbol, ts_ms) -> oi, seen_ms
* ``coins``    symbol -> exchange status, trading 0/1, last bar, coin end (last bar with volume when it stopped trading),
  the next funding time the feed expects
* ``kv``       feed state: complete_ms (bars with open < complete_ms are final for every trading coin, funding due by
  then included), ins_seq
* ``heartbeat``, ``feed_log``

Rows are only ever added (INSERT OR IGNORE: the first copy of a bar wins). A bar older than the coin's newest stored
bar (a gap filled later) is counted as late in ``feed_log``; the runner then reloads that coin.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Iterable, Optional

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars_5m (symbol TEXT NOT NULL, open_ms INTEGER NOT NULL, o REAL NOT NULL, h REAL NOT NULL,
  l REAL NOT NULL, c REAL NOT NULL, v REAL NOT NULL, qv REAL NOT NULL, seen_ms INTEGER NOT NULL, ins INTEGER NOT NULL,
  PRIMARY KEY (symbol, open_ms)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS bars_5m_ins ON bars_5m (ins);
CREATE TABLE IF NOT EXISTS mark_5m (symbol TEXT NOT NULL, open_ms INTEGER NOT NULL, o REAL, h REAL, l REAL, c REAL,
  seen_ms INTEGER NOT NULL, PRIMARY KEY (symbol, open_ms)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS funding (symbol TEXT NOT NULL, calc_ms INTEGER NOT NULL, rate REAL NOT NULL,
  seen_ms INTEGER NOT NULL, ins INTEGER NOT NULL, PRIMARY KEY (symbol, calc_ms)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS oi (symbol TEXT NOT NULL, ts_ms INTEGER NOT NULL, oi REAL NOT NULL, seen_ms INTEGER NOT NULL,
  PRIMARY KEY (symbol, ts_ms)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS coins (symbol TEXT PRIMARY KEY, status TEXT, trading INTEGER NOT NULL DEFAULT 0,
  last_bar_ms INTEGER, end_ms INTEGER, expect_funding_ms INTEGER, next_funding_ms INTEGER, updated_ms INTEGER,
  note TEXT);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS heartbeat (name TEXT PRIMARY KEY, ts_ms INTEGER NOT NULL, info TEXT);
CREATE TABLE IF NOT EXISTS feed_log (ts_ms INTEGER NOT NULL, level TEXT NOT NULL, msg TEXT NOT NULL);
"""

COLS = ("ts", "o", "h", "l", "c", "v", "qv")


def connect(path: str, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    else:
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        conn = sqlite3.connect(path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA journal_size_limit=67108864")        # the WAL file shrinks back after a big backfill
        conn.executescript(SCHEMA)
        conn.commit()
    return conn


class Store:
    def __init__(self, path: str, readonly: bool = False, clock=time.time):
        self.path = path
        self.readonly = readonly
        self.clock = clock
        self.conn = connect(path, readonly)
        self._max_open: dict = {}

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    # ------------------------------------------------------------ kv / log
    def get(self, k: str, default=None):
        row = self.conn.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, k: str, v) -> None:
        self.conn.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, json.dumps(v)))

    def log(self, level: str, msg: str) -> None:
        self.conn.execute("INSERT INTO feed_log VALUES (?, ?, ?)", (self.now_ms(), level, msg[:500]))
        self.conn.execute("DELETE FROM feed_log WHERE ts_ms < ?", (self.now_ms() - 30 * 86_400_000,))

    def heartbeat(self, name: str, info: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO heartbeat VALUES (?, ?, ?)", (name, self.now_ms(), json.dumps(info)))

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        """Roll back AND forget the cached newest bar per coin (the cache may name rows the rollback removed; a
        stale cache would make the next pass start after them and leave a hole for good)."""
        try:
            self.conn.rollback()
        finally:
            self._max_open.clear()

    def _next_ins(self) -> int:
        n = int(self.get("ins_seq", 0)) + 1
        self.put("ins_seq", n)
        return n

    # ------------------------------------------------------------ writes (the feed)
    def max_open(self, sym: str) -> Optional[int]:
        if sym not in self._max_open:
            row = self.conn.execute("SELECT MAX(open_ms) FROM bars_5m WHERE symbol = ?", (sym,)).fetchone()
            self._max_open[sym] = row[0] if row and row[0] is not None else None
        return self._max_open[sym]

    def insert_bars(self, sym: str, rows: Iterable) -> tuple:
        """rows: (open_ms, o, h, l, c, v, qv). Returns (new rows, late rows)."""
        rows = [tuple(r) for r in rows]
        if not rows:
            return 0, 0
        prev = self.max_open(sym)
        seen, ins = self.now_ms(), self._next_ins()
        before = self.conn.total_changes
        self.conn.executemany("INSERT OR IGNORE INTO bars_5m VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              [(sym, int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]),
                                float(r[6]), seen, ins) for r in rows])
        new = self.conn.total_changes - before
        late = 0
        if prev is not None and new:
            late = int(self.conn.execute("SELECT COUNT(*) FROM bars_5m WHERE symbol = ? AND ins = ? AND open_ms < ?",
                                         (sym, ins, prev)).fetchone()[0])
            if late:
                self.log("warn", f"{sym}: {late} late 5m bar(s) inserted before {prev}")
        mx = max(int(r[0]) for r in rows)
        self._max_open[sym] = mx if prev is None else max(prev, mx)
        return new, late

    def insert_marks(self, sym: str, rows: Iterable) -> int:
        rows = [tuple(r) for r in rows]
        if not rows:
            return 0
        seen = self.now_ms()
        before = self.conn.total_changes
        self.conn.executemany("INSERT OR IGNORE INTO mark_5m VALUES (?, ?, ?, ?, ?, ?, ?)",
                              [(sym, int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), seen)
                               for r in rows])
        return self.conn.total_changes - before

    def insert_funding(self, sym: str, rows: Iterable) -> int:
        """rows: (calc_ms, rate)."""
        rows = [tuple(r) for r in rows]
        if not rows:
            return 0
        seen, ins = self.now_ms(), self._next_ins()
        before = self.conn.total_changes
        self.conn.executemany("INSERT OR IGNORE INTO funding VALUES (?, ?, ?, ?, ?)",
                              [(sym, int(r[0]), float(r[1]), seen, ins) for r in rows])
        return self.conn.total_changes - before

    def insert_oi(self, sym: str, ts_ms: int, value: float) -> None:
        self.conn.execute("INSERT OR IGNORE INTO oi VALUES (?, ?, ?, ?)", (sym, int(ts_ms), float(value),
                                                                          self.now_ms()))

    def set_coin(self, sym: str, **kw) -> None:
        self.conn.execute("INSERT OR IGNORE INTO coins (symbol, trading) VALUES (?, 0)", (sym,))
        for k, v in kw.items():
            if k not in ("status", "trading", "last_bar_ms", "end_ms", "expect_funding_ms", "next_funding_ms",
                         "note"):
                raise KeyError(k)
            self.conn.execute(f"UPDATE coins SET {k} = ?, updated_ms = ? WHERE symbol = ?", (v, self.now_ms(), sym))

    # ------------------------------------------------------------ reads (runner, judge, dashboard status)
    def coins(self) -> dict:
        cur = self.conn.execute("SELECT symbol, status, trading, last_bar_ms, end_ms, expect_funding_ms, "
                                "next_funding_ms, updated_ms, note FROM coins")
        keys = ("symbol", "status", "trading", "last_bar_ms", "end_ms", "expect_funding_ms", "next_funding_ms",
                "updated_ms", "note")
        return {r[0]: dict(zip(keys, r)) for r in cur}

    def complete_ms(self) -> Optional[int]:
        return self.get("complete_ms")

    def max_ins(self) -> int:
        row = self.conn.execute("SELECT MAX(ins) FROM bars_5m").fetchone()
        return int(row[0] or 0)

    def load_bars(self, sym: str, from_ms: int = 0, to_ms: Optional[int] = None) -> dict:
        """The coin's stored 5m bars with from_ms <= open < to_ms, sorted (float64 columns, as stored)."""
        q = "SELECT open_ms, o, h, l, c, v, qv FROM bars_5m WHERE symbol = ? AND open_ms >= ?"
        args = [sym, int(from_ms)]
        if to_ms is not None:
            q += " AND open_ms < ?"
            args.append(int(to_ms))
        rows = self.conn.execute(q + " ORDER BY open_ms", args).fetchall()
        return _cols(rows)

    def bars_since(self, ins: int, upto: Optional[int] = None) -> dict:
        """{sym: rows (open_ms, o, h, l, c, v, qv)} inserted with ``ins`` < ins <= ``upto`` (the reader takes ``upto``
        = max_ins() BEFORE this call: rows a feed pass commits in between are left for the next read, never
        skipped)."""
        out: dict = {}
        q, args = "SELECT symbol, open_ms, o, h, l, c, v, qv FROM bars_5m WHERE ins > ?", [int(ins)]
        if upto is not None:
            q += " AND ins <= ?"
            args.append(int(upto))
        for r in self.conn.execute(q + " ORDER BY symbol, open_ms", args):
            out.setdefault(r[0], []).append(r[1:])
        return out

    def count_bars(self, sym: str, from_ms: int, to_ms: int) -> int:
        """Stored bars of the coin with from_ms <= open < to_ms (a primary-key range count)."""
        return int(self.conn.execute("SELECT COUNT(*) FROM bars_5m WHERE symbol = ? AND open_ms >= ? AND open_ms < ?",
                                     (sym, int(from_ms), int(to_ms))).fetchone()[0])

    def first_open(self, sym: str) -> Optional[int]:
        row = self.conn.execute("SELECT MIN(open_ms) FROM bars_5m WHERE symbol = ?", (sym,)).fetchone()
        return row[0] if row and row[0] is not None else None

    def gaps(self, sym: str, from_ms: int = 0) -> list:
        """[(first missing open, first open after the hole)] inside the coin's stored bars (open >= from_ms)."""
        q = ("SELECT open_ms, nxt FROM (SELECT open_ms, LEAD(open_ms) OVER (ORDER BY open_ms) AS nxt FROM bars_5m "
             "WHERE symbol = ? AND open_ms >= ?) WHERE nxt - open_ms > ?")
        return [(int(a) + 300_000, int(b)) for a, b in self.conn.execute(q, (sym, int(from_ms), 300_000))]

    def load_funding(self, sym: str, from_ms: int = 0) -> tuple:
        rows = self.conn.execute("SELECT calc_ms, rate FROM funding WHERE symbol = ? AND calc_ms >= ? ORDER BY calc_ms",
                                 (sym, int(from_ms))).fetchall()
        if not rows:
            return np.zeros(0, np.int64), np.zeros(0)
        a = np.asarray(rows, dtype=object)
        return np.asarray(a[:, 0], np.int64), np.asarray(a[:, 1], np.float64)

    def coverage(self, symbols: Optional[list] = None) -> dict:
        """{symbol: bars, first and last open} by the primary key (no table scan)."""
        if symbols is None:
            symbols = [r[0] for r in self.conn.execute("SELECT symbol FROM coins")]
        out = {}
        for sym in symbols:
            a, b, n = self.conn.execute("SELECT MIN(open_ms), MAX(open_ms), COUNT(*) FROM bars_5m WHERE symbol = ?",
                                        (sym,)).fetchone()
            if n:
                out[sym] = {"bars": n, "first_ms": a, "last_ms": b}
        return out

    def recent_log(self, n: int = 20) -> list:
        return [{"ts_ms": t, "level": lv, "msg": m} for t, lv, m in
                self.conn.execute("SELECT ts_ms, level, msg FROM feed_log ORDER BY ts_ms DESC LIMIT ?", (n,))]

    def heartbeats(self) -> dict:
        return {n: {"ts_ms": t, **(json.loads(i) if i else {})} for n, t, i in
                self.conn.execute("SELECT name, ts_ms, info FROM heartbeat")}


def _cols(rows) -> dict:
    if not rows:
        return {"ts": np.zeros(0, np.int64), **{k: np.zeros(0) for k in COLS[1:]}}
    a = np.asarray(rows, dtype=np.float64)
    out = {"ts": np.asarray([r[0] for r in rows], np.int64)}
    for i, k in enumerate(COLS[1:], start=1):
        out[k] = a[:, i]
    return out
