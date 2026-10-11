"""events.db: every entry event of every hunt system on every coin, gate-blocked ones included, as the runner saw it
(the slot the AI judge of docs/aibot/hunt_judge/SPEC.md reads later; the judge is not built here). One writer: the
runner. SQLite WAL, so readers never block it.

It is also the runner's ledger: an event recorded here is never changed or removed. After a restart the runner takes
the events of the bars it had already seen from here and computes only the new bars (live-faithful: a definition that
would repaint its past cannot change the record; such a difference is written to ``repaints``). A change of the signal
code starts a new generation (``generations``): the old rows stay, the new generation is recorded again from
2026-10-01 with ``backfilled = 1``.

Tables
* ``events``: one row per (generation, cell, symbol, signal bar close, side). A cell is one entry on one timeframe
  (the systems ``sys_g1`` and ``sys_none`` share its events; the gate only labels them). ``detected_ms`` = the runner's
  clock when it first computed the event, ``backfilled`` = 1 when that was more than 15 minutes after the bar close
  (catch-up, restart, new generation). ``regime_code`` (0 모름, 1 추세장, 2 횡보장, 3 급변장, 4 보통) and ``gated`` (the
  G1 gate passes) at that bar; close, ATR14, D0 at that bar; ``entry_values`` for the hunt's own entries E1-E3.
  ``action_g1`` / ``action_none``: what the system did with it (OPENED, BLOCKED_GATE, BLOCKED_COIN_BUSY,
  BLOCKED_CAP_SIX, SKIPPED_OTHER, BOTH_SIDES, NO_ATR, PENDING_FILL); ``final`` once no PENDING_FILL is left.
  No money of any kind is stored here.
* view ``events_systems``: the same rows once per system (system id, gate, rule_action), as the judge spec names them.
* ``progress``: per (generation, cell, symbol) the last signal-bar close the ledger covers.
* ``repaints``: events a fresh computation of an already-recorded bar no longer gives (``vanished``) or newly gives
  (``appeared``); the ledger keeps what was seen.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Iterable, Optional

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS generations (gen INTEGER PRIMARY KEY, signal_hash TEXT NOT NULL, created_ms INTEGER NOT NULL,
  note TEXT);
CREATE TABLE IF NOT EXISTS events (event_id INTEGER PRIMARY KEY, gen INTEGER NOT NULL, cell TEXT NOT NULL,
  family TEXT, name TEXT, kind TEXT, tf TEXT NOT NULL, rank INTEGER, sys_g1 TEXT, sys_none TEXT,
  symbol TEXT NOT NULL, side TEXT NOT NULL, bar_close_ms INTEGER NOT NULL, detected_ms INTEGER NOT NULL,
  backfilled INTEGER NOT NULL, regime_code INTEGER, gated INTEGER, close REAL, atr14 REAL, d0 REAL,
  entry_values TEXT, action_g1 TEXT, action_none TEXT, final INTEGER NOT NULL DEFAULT 0, engine_hash TEXT,
  UNIQUE (gen, cell, symbol, bar_close_ms, side));
CREATE INDEX IF NOT EXISTS events_close ON events (bar_close_ms);
CREATE INDEX IF NOT EXISTS events_open ON events (gen, final, cell);
CREATE TABLE IF NOT EXISTS progress (gen INTEGER NOT NULL, cell TEXT NOT NULL, symbol TEXT NOT NULL,
  through_ms INTEGER NOT NULL, PRIMARY KEY (gen, cell, symbol)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS repaints (ts_ms INTEGER NOT NULL, gen INTEGER NOT NULL, cell TEXT NOT NULL,
  symbol TEXT NOT NULL, side TEXT NOT NULL, bar_close_ms INTEGER NOT NULL, kind TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS heartbeat (name TEXT PRIMARY KEY, ts_ms INTEGER NOT NULL, info TEXT);
CREATE VIEW IF NOT EXISTS events_systems AS
  SELECT event_id, gen, sys_g1 AS system, 'G1' AS gate, cell, symbol, tf, side, bar_close_ms, detected_ms,
         backfilled, regime_code, gated, close, atr14, d0, entry_values, action_g1 AS rule_action, final, engine_hash
  FROM events
  UNION ALL
  SELECT event_id, gen, sys_none, 'NONE', cell, symbol, tf, side, bar_close_ms, detected_ms, backfilled,
         regime_code, 1, close, atr14, d0, entry_values, action_none, final, engine_hash
  FROM events;
"""

BACKFILL_MS = 15 * 60_000
SIDES = {1: "LONG", -1: "SHORT"}


class Ledger:
    def __init__(self, path: str, signal_hash: str, engine_hash: str = "", clock=time.time):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path, self.clock = path, clock
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.engine_hash = engine_hash
        row = self.conn.execute("SELECT gen, signal_hash FROM generations ORDER BY gen DESC LIMIT 1").fetchone()
        if row is None or row[1] != signal_hash:
            note = "first" if row is None else f"signal code changed (was {row[1][:12]})"
            cur = self.conn.execute("INSERT INTO generations (signal_hash, created_ms, note) VALUES (?, ?, ?)",
                                    (signal_hash, self.now_ms(), note))
            self.gen = int(cur.lastrowid)
            self.new_generation = True
        else:
            self.gen = int(row[0])
            self.new_generation = False
        self.conn.commit()

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    # ------------------------------------------------------------ the book (frozen events) after a restart
    def load_book(self) -> dict:
        """{(cell, symbol): {"through": ms, "long": sorted close ms, "short": sorted close ms}} of this generation."""
        book: dict = {}
        for cell, sym, thr in self.conn.execute("SELECT cell, symbol, through_ms FROM progress WHERE gen = ?",
                                                (self.gen,)):
            book[(cell, sym)] = {"through": int(thr), "long": [], "short": []}
        for cell, sym, side, ms in self.conn.execute("SELECT cell, symbol, side, bar_close_ms FROM events "
                                                     "WHERE gen = ? ORDER BY bar_close_ms", (self.gen,)):
            e = book.get((cell, sym))
            if e is not None and ms <= e["through"]:
                e["long" if side == "LONG" else "short"].append(int(ms))
        for e in book.values():
            e["long"] = np.asarray(e["long"], np.int64)
            e["short"] = np.asarray(e["short"], np.int64)
        return book

    # ------------------------------------------------------------ writes
    def add_events(self, rows: Iterable[dict]) -> int:
        now = self.now_ms()
        vals = []
        for r in rows:
            vals.append((self.gen, r["cell"], r.get("family"), r.get("name"), r.get("kind"), r["tf"], r.get("rank"),
                         r.get("sys_g1"), r.get("sys_none"), r["symbol"], r["side"], int(r["bar_close_ms"]), now,
                         int(now - int(r["bar_close_ms"]) > BACKFILL_MS), r.get("regime_code"), r.get("gated"),
                         r.get("close"), r.get("atr14"), r.get("d0"),
                         json.dumps(r["entry_values"]) if r.get("entry_values") is not None else None,
                         self.engine_hash))
        before = self.conn.total_changes
        self.conn.executemany(
            "INSERT OR IGNORE INTO events (gen, cell, family, name, kind, tf, rank, sys_g1, sys_none, symbol, side, "
            "bar_close_ms, detected_ms, backfilled, regime_code, gated, close, atr14, d0, entry_values, engine_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", vals)
        return self.conn.total_changes - before

    def set_progress(self, items: Iterable[tuple]) -> None:
        self.conn.executemany("INSERT OR REPLACE INTO progress VALUES (?, ?, ?, ?)",
                              [(self.gen, c, s, int(t)) for c, s, t in items])

    def log_repaints(self, items: Iterable[tuple]) -> int:
        now = self.now_ms()
        rows = [(now, self.gen, c, s, side, int(ms), kind) for c, s, side, ms, kind in items]
        self.conn.executemany("INSERT INTO repaints VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    def pending_since(self) -> dict:
        """{cell: earliest bar close among its events without a final action} (this generation)."""
        return {c: int(ms) for c, ms in self.conn.execute(
            "SELECT cell, MIN(bar_close_ms) FROM events WHERE gen = ? AND final = 0 GROUP BY cell", (self.gen,))}

    def set_actions(self, cell: str, acts: dict) -> int:
        """acts: {(symbol, bar_close_ms, side): (action_g1, action_none)}."""
        rows = []
        for (sym, ms, side), (ag, an) in acts.items():
            fin = int(ag is not None and an is not None and "PENDING_FILL" not in (ag, an))
            rows.append((ag, an, fin, self.gen, cell, sym, int(ms), side))
        self.conn.executemany("UPDATE events SET action_g1 = COALESCE(?, action_g1), action_none = COALESCE(?, "
                              "action_none), final = ? WHERE gen = ? AND cell = ? AND symbol = ? AND bar_close_ms = ? "
                              "AND side = ? AND final = 0", rows)
        return len(rows)

    def heartbeat(self, info: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO heartbeat VALUES ('runner', ?, ?)", (self.now_ms(), json.dumps(info)))

    def commit(self) -> None:
        self.conn.commit()

    # ------------------------------------------------------------ reads for the status screen
    def counts(self) -> dict:
        n = self.conn.execute("SELECT COUNT(*), SUM(backfilled), SUM(final = 0) FROM events WHERE gen = ?",
                              (self.gen,)).fetchone()
        rp = self.conn.execute("SELECT COUNT(*) FROM repaints WHERE gen = ?", (self.gen,)).fetchone()[0]
        last = self.conn.execute("SELECT cell, symbol, side, bar_close_ms, kind, ts_ms FROM repaints WHERE gen = ? "
                                 "ORDER BY ts_ms DESC LIMIT 10", (self.gen,)).fetchall()
        return {"generation": self.gen, "events": int(n[0] or 0), "backfilled": int(n[1] or 0),
                "pending": int(n[2] or 0), "repaints": int(rp),
                "repaints_last": [{"cell": c, "symbol": s, "side": sd, "bar_close_ms": ms, "kind": k, "ts_ms": t}
                                  for c, s, sd, ms, k, t in last]}

    def recent(self, cells: Optional[set] = None, since_ms: int = 0, limit: int = 300) -> list:
        q = ("SELECT cell, sys_g1, sys_none, symbol, side, bar_close_ms, detected_ms, backfilled, regime_code, gated, "
             "action_g1, action_none FROM events WHERE gen = ? AND bar_close_ms >= ? ORDER BY bar_close_ms DESC "
             "LIMIT ?")
        keys = ("cell", "sys_g1", "sys_none", "symbol", "side", "bar_close_ms", "detected_ms", "backfilled",
                "regime_code", "gated", "action_g1", "action_none")
        out = []
        for r in self.conn.execute(q, (self.gen, int(since_ms), int(limit) * (10 if cells else 1))):
            d = dict(zip(keys, r))
            if cells is None or d["cell"] in cells:
                out.append(d)
            if len(out) >= limit:
                break
        return out
