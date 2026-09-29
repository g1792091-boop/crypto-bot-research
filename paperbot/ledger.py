"""SQLite ledger for trades, signal outcomes and equity.

Uses WAL so a crash mid-write does not corrupt earlier rows.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from typing import Iterable, Optional

from .models import Bar, SignalOutcome, TradeRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    settings_version TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step_ts INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bars1m (
    symbol TEXT NOT NULL,
    open_time INTEGER NOT NULL,
    close_time INTEGER NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    mark_open REAL, mark_high REAL, mark_low REAL, mark_close REAL,
    PRIMARY KEY (symbol, open_time)
);
CREATE TABLE IF NOT EXISTS alerts (
    ts INTEGER NOT NULL,
    level TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    pipeline TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    packet_sha TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_calls (
    ts INTEGER NOT NULL,
    day TEXT NOT NULL,
    pipeline TEXT NOT NULL,
    role TEXT NOT NULL,
    model TEXT NOT NULL,
    ok INTEGER NOT NULL,
    tokens INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT NOT NULL,
    started_ts INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS book (
    ts INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    bid REAL NOT NULL, bid_qty REAL, ask REAL NOT NULL, ask_qty REAL,
    exchange_ts INTEGER
);
CREATE INDEX IF NOT EXISTS book_sym_ts ON book (symbol, ts);
CREATE TABLE IF NOT EXISTS equity (
    run_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    equity REAL NOT NULL,
    drawdown REAL NOT NULL
);
"""


class Ledger:
    def __init__(self, path: str, run_id: str, settings_version: str,
                 equity_every: int = 1):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.run_id = run_id
        self.version = settings_version
        self.equity_every = max(1, equity_every)
        self._n = 0

    def trade(self, rec: TradeRecord) -> None:
        self.conn.execute(
            "INSERT INTO trades (run_id, settings_version, data) VALUES (?,?,?)",
            (self.run_id, self.version, json.dumps(asdict(rec))))
        self.conn.commit()

    def outcome(self, out: SignalOutcome) -> None:
        sig = out.signal
        self.conn.execute(
            "INSERT INTO signals (run_id, step_ts, status, reason, symbol, "
            "strategy_id, timeframe, data) VALUES (?,?,?,?,?,?,?,?)",
            (self.run_id, out.step_ts, out.status, out.reason, sig.symbol,
             sig.strategy_id, sig.timeframe,
             json.dumps({"signal": asdict(sig), "detail": out.detail}, default=str)))
        self.conn.commit()

    def equity(self, ts: int, equity: float, drawdown: float) -> None:
        self._n += 1
        if self._n % self.equity_every:
            return
        self.conn.execute("INSERT INTO equity VALUES (?,?,?,?)",
                          (self.run_id, ts, equity, drawdown))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def load_trades(path: str, run_id: Optional[str] = None, book: Optional[str] = None,
                exit_from: Optional[int] = None, exit_to: Optional[int] = None) -> list[TradeRecord]:
    """``book`` matches run ids ending in ``-<book>`` (as written by make_books).
    ``exit_from``/``exit_to`` filter on exit time in ms (inclusive/exclusive)."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    q = "SELECT data FROM trades WHERE 1=1"
    args: list = []
    if run_id:
        q += " AND run_id = ?"
        args.append(run_id)
    if book:
        q += " AND run_id LIKE ?"
        args.append(f"%-{book}")
    rows = conn.execute(q + " ORDER BY id", args).fetchall()
    conn.close()
    out = [TradeRecord(**json.loads(r[0])) for r in rows]
    if exit_from is not None:
        out = [t for t in out if t.exit_time >= exit_from]
    if exit_to is not None:
        out = [t for t in out if t.exit_time < exit_to]
    return out


def record_run(path: str, run_id: str, started_ts: int, info: dict) -> None:
    """What a live run started with (books, strategies, brackets source), so
    the evening review can tell "no strategy connected" from "quiet market"."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO runs VALUES (?,?,?)", (run_id, started_ts, json.dumps(info)))
    conn.commit()
    conn.close()


class RecordingNotifier:
    """Keeps every alert in the ledger (for the operations auditor) and
    passes it on to the real notifier."""

    def __init__(self, path: str, inner, clock_ms=None):
        import time as _time
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.inner = inner
        self.clock_ms = clock_ms or (lambda: int(_time.time() * 1000))

    def send(self, level: str, text: str) -> None:
        try:
            self.conn.execute("INSERT INTO alerts VALUES (?,?,?)", (self.clock_ms(), level, text))
            self.conn.commit()
        finally:
            self.inner.send(level, text)

    def close(self) -> None:
        self.conn.close()


class BarStore:
    """1m bars as seen live, kept for tagging and the what-if lab."""

    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    def add(self, bars: Iterable[Bar]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO bars1m VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(b.symbol, b.open_time, b.close_time, b.open, b.high, b.low, b.close,
              b.mark_open, b.mark_high, b.mark_low, b.mark_close) for b in bars])
        self.conn.commit()

    def load(self, symbol: str, start: int = 0, end: Optional[int] = None) -> list[Bar]:
        q = ("SELECT symbol, open_time, close_time, open, high, low, close, mark_open, "
             "mark_high, mark_low, mark_close FROM bars1m WHERE symbol = ? AND open_time >= ?")
        args: list = [symbol, start]
        if end is not None:
            q += " AND open_time <= ?"
            args.append(end)
        return [Bar(*r) for r in self.conn.execute(q + " ORDER BY open_time", args)]

    def symbols(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT symbol FROM bars1m")]

    def close(self) -> None:
        self.conn.close()


class BookStore:
    """Best bid/ask snapshots taken by the live runner after each closed 1m
    bar. The signal recorder uses them to estimate the fill a market order
    would have got right after a signal bar closed."""

    def __init__(self, path: str, symbols: Iterable[str], clock_ms=None):
        import time as _time
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.symbols = set(symbols)
        self.clock_ms = clock_ms or (lambda: int(_time.time() * 1000))

    def add(self, tickers: list[dict]) -> int:
        now = self.clock_ms()
        rows = [(now, t["symbol"], float(t["bidPrice"]), float(t.get("bidQty") or 0),
                 float(t["askPrice"]), float(t.get("askQty") or 0),
                 int(t["time"]) if t.get("time") else None)
                for t in tickers if t.get("symbol") in self.symbols]
        self.conn.executemany("INSERT INTO book VALUES (?,?,?,?,?,?,?)", rows)
        self.conn.commit()
        return len(rows)

    def close(self) -> None:
        self.conn.close()


def open_book_reader(path: str) -> Optional[sqlite3.Connection]:
    """Read-only connection to the live runner's book snapshots, or None if
    the database or table does not exist. Other processes only read paper.db."""
    import os
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    has = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'book'").fetchone()
    if not has:
        conn.close()
        return None
    return conn


def book_near(conn: sqlite3.Connection, symbol: str, after_ms: int,
              within_ms: int = 180_000) -> Optional[dict]:
    """First snapshot at or after ``after_ms`` (within ``within_ms``)."""
    r = conn.execute("SELECT ts, bid, ask FROM book WHERE symbol = ? AND ts >= ? AND ts <= ? "
                     "ORDER BY ts LIMIT 1", (symbol, after_ms, after_ms + within_ms)).fetchone()
    return {"ts": r[0], "bid": r[1], "ask": r[2]} if r else None
