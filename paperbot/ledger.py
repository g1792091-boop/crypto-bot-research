"""SQLite ledger for trades, signal outcomes and equity.

Uses WAL so a crash mid-write does not corrupt earlier rows.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from .models import SignalOutcome, TradeRecord

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
