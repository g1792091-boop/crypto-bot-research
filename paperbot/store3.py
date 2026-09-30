"""SQLite store for the paper v3 run (one writer: the live runner).

Tables
- accounts     one row per account (strategy x timeframe, coin-flip, improved copies)
- trades       closed trades, per account
- outcomes     what happened to each signal an account received
- equity       sampled equity per account
- signal_log   every signal computed by the signal service (also record-only 1d)
- state        latest snapshot of every account engine and of the feed (restart recovery)
- alerts       notifier messages

WAL mode; the dashboard and the agents open it read-only.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import Iterable, Optional

from .models import SignalOutcome, TradeRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_ts INTEGER NOT NULL,
    settings_version TEXT NOT NULL,
    parent TEXT,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    entry_time INTEGER NOT NULL,
    exit_time INTEGER NOT NULL,
    exit_reason TEXT NOT NULL,
    leverage INTEGER NOT NULL,
    pnl REAL NOT NULL,
    roe REAL NOT NULL,
    equity_after REAL NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS trades_acct ON trades (account_id, exit_time);
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    step_ts INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    symbol TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS outcomes_acct ON outcomes (account_id, step_ts);
CREATE TABLE IF NOT EXISTS equity (
    account_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    equity REAL NOT NULL,
    drawdown REAL NOT NULL,
    PRIMARY KEY (account_id, ts)
);
CREATE TABLE IF NOT EXISTS signal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bar_close INTEGER NOT NULL,
    timeframe TEXT NOT NULL,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side INTEGER NOT NULL,
    atr REAL,
    ref_price REAL,
    ref_time INTEGER,
    delay_ms INTEGER,
    status TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',
    UNIQUE (bar_close, timeframe, strategy, symbol)
);
CREATE INDEX IF NOT EXISTS siglog_tf ON signal_log (timeframe, bar_close);
CREATE TABLE IF NOT EXISTS state (
    k TEXT PRIMARY KEY,
    ts INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    ts INTEGER NOT NULL,
    level TEXT NOT NULL,
    text TEXT NOT NULL
);
"""


class Store3:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------ accounts
    def add_account(self, account_id: str, strategy: str, timeframe: str, kind: str,
                    created_ts: int, settings_version: str, parent: Optional[str] = None,
                    data: Optional[dict] = None) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO accounts VALUES (?,?,?,?,?,?,?,?)",
            (account_id, strategy, timeframe, kind, created_ts, settings_version, parent,
             json.dumps(data or {})))

    def accounts(self) -> list[dict]:
        cur = self.conn.execute("SELECT account_id, strategy, timeframe, kind, created_ts, "
                                "settings_version, parent, data FROM accounts ORDER BY rowid")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ------------------------------------------------------------ events
    def trade(self, account_id: str, rec: TradeRecord) -> None:
        self.conn.execute(
            "INSERT INTO trades (account_id, symbol, entry_time, exit_time, exit_reason, leverage, "
            "pnl, roe, equity_after, data) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (account_id, rec.symbol, rec.entry_time, rec.exit_time, rec.exit_reason, rec.leverage,
             rec.pnl, rec.roe, rec.equity_after, json.dumps(asdict(rec), default=str)))

    def outcome(self, account_id: str, out: SignalOutcome) -> None:
        self.conn.execute(
            "INSERT INTO outcomes (account_id, step_ts, status, reason, symbol, data) VALUES (?,?,?,?,?,?)",
            (account_id, out.step_ts, out.status, out.reason, out.signal.symbol,
             json.dumps({"signal": asdict(out.signal), "detail": out.detail}, default=str)))

    def equity(self, account_id: str, ts: int, equity: float, drawdown: float) -> None:
        self.conn.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?,?)",
                          (account_id, ts, equity, drawdown))

    def log_signals(self, rows: Iterable[dict]) -> None:
        self.conn.executemany(
            "INSERT OR IGNORE INTO signal_log (bar_close, timeframe, strategy, symbol, side, atr, "
            "ref_price, ref_time, delay_ms, status, data) VALUES "
            "(:bar_close, :timeframe, :strategy, :symbol, :side, :atr, :ref_price, :ref_time, "
            ":delay_ms, :status, :data)",
            [{**r, "data": json.dumps(r.get("data", {}), default=str)} for r in rows])

    def alert(self, ts: int, level: str, text: str) -> None:
        self.conn.execute("INSERT INTO alerts VALUES (?,?,?)", (ts, level, text))

    # ------------------------------------------------------------ state
    def put_state(self, key: str, ts: int, data: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO state VALUES (?,?,?)", (key, ts, json.dumps(data)))

    def get_state(self, key: str) -> Optional[tuple[int, dict]]:
        r = self.conn.execute("SELECT ts, data FROM state WHERE k = ?", (key,)).fetchone()
        return None if r is None else (int(r[0]), json.loads(r[1]))

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
