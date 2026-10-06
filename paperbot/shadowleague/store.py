"""The shadow league's SQLite database (shadow_league.db, next to the agents database; all times are UTC milliseconds).

Only the agents tick writes it (it holds the tick lock); the dashboard reads it through view.py, read-only. Nothing in
it is a paper account: these are virtual trades on live bars, for reference only (참고용, 판정 아님).

Tables (the final shape after all migrations; ``schema_ddl`` prints it from the database itself):
  league_meta     small key / value facts (schema_version, the last tick and what it did)
  members         one row per member: its Korean name, its definition (spec_json + sha256), start, when it was first run
  feeds           the closed bars held per coin and timeframe, shared by all members: first / last bar, ATR state, holes,
                  the feed's own state ('ok' / 'error' with the reason, the next allowed fetch)
  bars            the trailing closed bars with their ATR14 (the rest is pruned; history is re-fetched, never invented)
  series_state    the last PROCESSED bar per member, coin and timeframe, and its status (waiting / warming / recording /
                  error) with 'warming up (need N more bars)'
  signals         every detected signal (also the ones the rules skip, with the reason)
  trades          virtual trades: entry, exit, gross and net at 1x after the study's costs, bars held, and the result of
                  the owners' account sizing (acct_*: that timeframe's account)
  clones          coin-flip clones of every trade (K per trade, seeded from the trade id)
  account_daily   the owners'-style virtual account (5,000 USDT, 20 % margin x 20x, one position at a time): equity at the
                  end of each UTC day, per timeframe and for all four together

Migrations only ever add (CREATE TABLE IF NOT EXISTS, ADD COLUMN when the column is missing) and may be run any number
of times; ``schema_version`` in league_meta says how far a file got. A file written by an older version of this code is
brought forward without losing a row.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import urllib.parse
from typing import Any, Iterable, Optional

import numpy as np

from . import DB_NAME
from .zoneflip import atr14, atr_next

SCHEMA_VERSION = 2
KEEP_BARS = 1000                      # trailing bars kept per coin / timeframe (profile 200 + clone window 5 days + hold 48)

# ---------------------------------------------------------------------------------------------------- migrations
V1 = """
CREATE TABLE IF NOT EXISTS league_meta (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    member_id    TEXT PRIMARY KEY,
    name_ko      TEXT NOT NULL,
    detector     TEXT NOT NULL,
    spec_json    TEXT NOT NULL,
    spec_sha256  TEXT NOT NULL,
    start_ms     INTEGER NOT NULL,
    created_ms   INTEGER NOT NULL,
    activated_ms INTEGER,
    last_tick_ms INTEGER,
    halted       TEXT
);
CREATE TABLE IF NOT EXISTS feeds (
    coin          TEXT NOT NULL,
    tf            TEXT NOT NULL,
    first_bar_ms  INTEGER,
    last_bar_ms   INTEGER,
    n_ingested    INTEGER NOT NULL DEFAULT 0,
    holes         INTEGER NOT NULL DEFAULT 0,
    state         TEXT NOT NULL DEFAULT 'new',
    error         TEXT,
    error_since_ms INTEGER,
    error_count   INTEGER NOT NULL DEFAULT 0,
    last_fetch_ms INTEGER,
    last_ok_ms    INTEGER,
    next_try_ms   INTEGER,
    PRIMARY KEY (coin, tf)
);
CREATE TABLE IF NOT EXISTS bars (
    coin   TEXT NOT NULL,
    tf     TEXT NOT NULL,
    t_ms   INTEGER NOT NULL,
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume REAL NOT NULL,
    atr    REAL,
    PRIMARY KEY (coin, tf, t_ms)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS series_state (
    member_id   TEXT NOT NULL,
    coin        TEXT NOT NULL,
    tf          TEXT NOT NULL,
    status      TEXT NOT NULL,
    last_bar_ms INTEGER,
    warm_have   INTEGER NOT NULL DEFAULT 0,
    warm_need   INTEGER NOT NULL DEFAULT 0,
    note        TEXT,
    updated_ms  INTEGER NOT NULL,
    PRIMARY KEY (member_id, coin, tf)
);
CREATE TABLE IF NOT EXISTS signals (
    signal_id   TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL,
    coin        TEXT NOT NULL,
    tf          TEXT NOT NULL,
    side        INTEGER NOT NULL,
    bar_ms      INTEGER NOT NULL,
    break_ms    INTEGER,
    plan_entry  REAL,
    stop        REAL,
    target      REAL,
    rr          REAL,
    touches     INTEGER,
    atr         REAL,
    zone_lo     REAL,
    zone_hi     REAL,
    tz_lo       REAL,
    tz_hi       REAL,
    status      TEXT NOT NULL,
    recorded_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS signals_member ON signals (member_id, bar_ms);
CREATE TABLE IF NOT EXISTS trades (
    trade_id    TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL,
    coin        TEXT NOT NULL,
    tf          TEXT NOT NULL,
    side        INTEGER NOT NULL,
    signal_ms   INTEGER NOT NULL,
    entry_ms    INTEGER NOT NULL,
    entry_px    REAL NOT NULL,
    stop_px     REAL NOT NULL,
    target_px   REAL NOT NULL,
    sl_dist     REAL NOT NULL,
    tp_dist     REAL NOT NULL,
    status      TEXT NOT NULL,
    exit_ms     INTEGER,
    exit_px     REAL,
    reason      TEXT,
    hold        INTEGER,
    gross_raw   REAL,
    gross       REAL,
    fee         REAL,
    funding     REAL,
    net         REAL,
    mae         REAL,
    mfe         REAL,
    recorded_ms INTEGER NOT NULL,
    closed_ms   INTEGER
);
CREATE INDEX IF NOT EXISTS trades_member ON trades (member_id, status, entry_ms);
"""

V2_TABLES = """
CREATE TABLE IF NOT EXISTS clones (
    clone_id    TEXT PRIMARY KEY,
    member_id   TEXT NOT NULL,
    trade_id    TEXT NOT NULL,
    k           INTEGER NOT NULL,
    coin        TEXT NOT NULL,
    tf          TEXT NOT NULL,
    side        INTEGER NOT NULL,
    sl_dist     REAL NOT NULL,
    tp_dist     REAL NOT NULL,
    offset_bars INTEGER NOT NULL,
    target_ms   INTEGER NOT NULL,
    status      TEXT NOT NULL,
    entry_ms    INTEGER,
    entry_px    REAL,
    exit_ms     INTEGER,
    exit_px     REAL,
    reason      TEXT,
    hold        INTEGER,
    gross_raw   REAL,
    gross       REAL,
    fee         REAL,
    funding     REAL,
    net         REAL,
    mae         REAL,
    created_ms  INTEGER NOT NULL,
    resolved_ms INTEGER
);
CREATE INDEX IF NOT EXISTS clones_trade ON clones (trade_id, k);
CREATE INDEX IF NOT EXISTS clones_open ON clones (member_id, status, coin, tf);
CREATE TABLE IF NOT EXISTS account_daily (
    member_id  TEXT NOT NULL,
    scope      TEXT NOT NULL,
    day_ms     INTEGER NOT NULL,
    equity     REAL NOT NULL,
    ret_pct    REAL NOT NULL,
    taken      INTEGER NOT NULL,
    liquidated INTEGER NOT NULL,
    asof_ms    INTEGER NOT NULL,
    PRIMARY KEY (member_id, scope, day_ms)
) WITHOUT ROWID;
"""
V2_TRADE_COLUMNS = (("acct_taken", "INTEGER"), ("acct_ret", "REAL"), ("acct_equity", "REAL"), ("acct_liq", "INTEGER"))


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _m1(conn: sqlite3.Connection) -> None:
    conn.executescript(V1)


def _m2(conn: sqlite3.Connection) -> None:
    conn.executescript(V2_TABLES)
    for name, typ in V2_TRADE_COLUMNS:
        if not _has_column(conn, "trades", name):
            conn.execute(f"ALTER TABLE trades ADD COLUMN {name} {typ}")


MIGRATIONS = ((1, _m1), (2, _m2))        # (version, step): append only, never edit a step that has shipped


def schema_version(conn: sqlite3.Connection) -> int:
    try:
        r = conn.execute("SELECT v FROM league_meta WHERE k = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(r[0]) if r else 0


def migrate(conn: sqlite3.Connection) -> int:
    """Bring a database forward to SCHEMA_VERSION. Idempotent and additive. Returns the version it ends on."""
    have = schema_version(conn)
    for version, step in MIGRATIONS:
        # every step is safe to repeat, so a file that has the tables but no version row (a half-finished run) is fine
        if version > have or not _step_applied(conn, version):
            step(conn)
        conn.execute("INSERT INTO league_meta (k, v) VALUES ('schema_version', ?) "
                     "ON CONFLICT(k) DO UPDATE SET v = excluded.v WHERE CAST(v AS INTEGER) < CAST(excluded.v AS INTEGER)",
                     (str(version),))
    return schema_version(conn)


def _step_applied(conn: sqlite3.Connection, version: int) -> bool:
    if version == 1:
        return _has_column(conn, "trades", "trade_id")
    if version == 2:
        return _has_column(conn, "trades", "acct_taken") and bool(
            conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clones'").fetchone())
    return True


def schema_ddl(conn: sqlite3.Connection) -> list[str]:
    """The DDL of every table and index as the database itself holds it (what the dashboard builder reads)."""
    return [r[0] for r in conn.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, name")]


# ---------------------------------------------------------------------------------------------------- opening
def default_path(agents_db: str) -> str:
    """shadow_league.db in the folder of the agents database (the service may write /var/lib/paperbot)."""
    return os.path.join(os.path.dirname(os.path.abspath(agents_db)), DB_NAME)


def stale_wal(path: str) -> bool:
    """A restored copy (rollback-journal header) with an old non-empty -wal next to it (same rule as rooms_db)."""
    try:
        with open(path, "rb") as fh:
            h = fh.read(20)
        return (len(h) == 20 and h[:16] == b"SQLite format 3\x00" and h[18] == 1
                and os.path.getsize(path + "-wal") > 0)
    except OSError:
        return False


def open_ro(path: str) -> sqlite3.Connection:
    """A read-only connection with Row access. Raises FileNotFoundError when the file is absent and sqlite3.Error when
    it cannot be read (the caller says so; it never reads as 'nothing')."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    if stale_wal(path):
        raise sqlite3.DatabaseError("restored database with an old -wal next to it (delete the -wal and -shm)")
    uri = "file:" + urllib.parse.quote(os.path.abspath(path)) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.Error:
        conn.close()
        raise
    return conn


class Store:
    """The writer's handle (the agents tick). Every method takes and returns plain values or dicts."""

    def __init__(self, path: str):
        if stale_wal(path):
            raise sqlite3.DatabaseError(f"{path}: restored copy with an old -wal next to it; delete the -wal and -shm")
        self.path = path
        self.conn = sqlite3.connect(path, timeout=10, isolation_level=None)      # autocommit; tx() makes the groups
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.version = migrate(self.conn)             # additive and repeatable: no outer transaction needed

    def close(self) -> None:
        self.conn.close()

    @contextlib.contextmanager
    def tx(self):
        """One transaction: all of a series' rows for a chunk of bars are written together or not at all."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # ------------------------------------------------------------------------------------------------ meta
    def get_meta(self, key: str, default: Any = None) -> Any:
        r = self.conn.execute("SELECT v FROM league_meta WHERE k = ?", (key,)).fetchone()
        return default if r is None else json.loads(r[0])

    def set_meta(self, key: str, value: Any) -> None:
        self.conn.execute("INSERT INTO league_meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                          (key, json.dumps(value, ensure_ascii=False, sort_keys=True)))

    # ------------------------------------------------------------------------------------------------ members
    def member(self, member_id: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM members WHERE member_id = ?", (member_id,)).fetchone()
        return None if r is None else dict(r)

    def add_member(self, member_id: str, name_ko: str, detector: str, spec: dict, spec_sha256: str, start_ms: int,
                   now_ms: int) -> dict:
        self.conn.execute(
            "INSERT OR IGNORE INTO members (member_id, name_ko, detector, spec_json, spec_sha256, start_ms, created_ms) "
            "VALUES (?,?,?,?,?,?,?)",
            (member_id, name_ko, detector, json.dumps(spec, ensure_ascii=False, sort_keys=True), spec_sha256,
             int(start_ms), int(now_ms)))
        return self.member(member_id)

    def touch_member(self, member_id: str, now_ms: int, activate: bool = True) -> None:
        self.conn.execute("UPDATE members SET last_tick_ms = ?, activated_ms = COALESCE(activated_ms, ?) "
                          "WHERE member_id = ?", (int(now_ms), int(now_ms) if activate else None, member_id))

    def halt_member(self, member_id: str, why: Optional[str]) -> None:
        self.conn.execute("UPDATE members SET halted = ? WHERE member_id = ?", (why, member_id))

    # ------------------------------------------------------------------------------------------------ feeds and bars
    def feed(self, coin: str, tf: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM feeds WHERE coin = ? AND tf = ?", (coin, tf)).fetchone()
        return None if r is None else dict(r)

    def ensure_feed(self, coin: str, tf: str) -> dict:
        self.conn.execute("INSERT OR IGNORE INTO feeds (coin, tf) VALUES (?, ?)", (coin, tf))
        return self.feed(coin, tf)

    def load_bars(self, coin: str, tf: str) -> dict:
        """{'t','o','h','l','c','v','atr'} numpy arrays of the stored bars, oldest first (atr is NaN for the first 13)."""
        rows = self.conn.execute("SELECT t_ms, open, high, low, close, volume, atr FROM bars WHERE coin = ? AND tf = ? "
                                 "ORDER BY t_ms", (coin, tf)).fetchall()
        if not rows:
            e = np.array([])
            return {"t": np.array([], np.int64), "o": e, "h": e, "l": e, "c": e, "v": e, "atr": e}
        a = np.array([[x if x is not None else np.nan for x in r] for r in rows], dtype=float)
        return {"t": np.array([r[0] for r in rows], dtype=np.int64), "o": a[:, 1], "h": a[:, 2], "l": a[:, 3],
                "c": a[:, 4], "v": a[:, 5], "atr": a[:, 6]}

    def ingest_bars(self, coin: str, tf: str, tf_ms: int, bars: list, now_ms: int) -> dict:
        """Append closed bars [t, o, h, l, c, v] (strictly after the newest stored one, oldest first) with their ATR14.
        A bar with no volume (the exchange's fill for an interval without trades) is dropped like the study did, and
        a missing bar between two stored ones counts as a hole. Returns {'added', 'holes', 'dropped'}."""
        f = self.ensure_feed(coin, tf)
        last_t = f["last_bar_ms"]
        keep, dropped = [], 0
        for b in bars:
            if last_t is not None and int(b[0]) <= last_t:
                continue
            if not (b[5] > 0):
                dropped += 1
                continue
            keep.append(b)
        if not keep:
            return {"added": 0, "holes": 0, "dropped": dropped}
        h = np.array([b[2] for b in keep], float)
        l = np.array([b[3] for b in keep], float)
        c = np.array([b[4] for b in keep], float)
        prev = self.conn.execute("SELECT close, atr FROM bars WHERE coin = ? AND tf = ? AND t_ms = ?",
                                 (coin, tf, last_t)).fetchone() if last_t is not None else None
        if prev is None:
            atr = atr14(h, l, c)
        elif prev["atr"] is None:                        # fewer than 14 bars so far: redo the (short) start together
            old = self.load_bars(coin, tf)
            atr = atr14(np.r_[old["h"], h], np.r_[old["l"], l], np.r_[old["c"], c])[len(old["h"]):]
        else:
            atr = np.empty(len(keep))
            a, pc = float(prev["atr"]), float(prev["close"])
            for i in range(len(keep)):
                a = atr_next(a, pc, float(h[i]), float(l[i]))
                atr[i] = a
                pc = float(c[i])
        holes, t_prev = 0, last_t
        for b in keep:
            t = int(b[0])
            if t_prev is not None and t - t_prev != tf_ms:
                holes += max(0, (t - t_prev) // tf_ms - 1)
            t_prev = t
        rows = [(coin, tf, int(b[0]), float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5]),
                 None if not np.isfinite(a) else float(a)) for b, a in zip(keep, atr)]
        self.conn.executemany("INSERT OR IGNORE INTO bars (coin, tf, t_ms, open, high, low, close, volume, atr) "
                              "VALUES (?,?,?,?,?,?,?,?,?)", rows)
        self.conn.execute(
            "UPDATE feeds SET first_bar_ms = COALESCE(first_bar_ms, ?), last_bar_ms = ?, n_ingested = n_ingested + ?, "
            "holes = holes + ? WHERE coin = ? AND tf = ?",
            (int(keep[0][0]), int(keep[-1][0]), len(rows), holes, coin, tf))
        return {"added": len(rows), "holes": holes, "dropped": dropped}

    def feed_ok(self, coin: str, tf: str, now_ms: int) -> None:
        self.conn.execute("UPDATE feeds SET state = 'ok', error = NULL, error_since_ms = NULL, error_count = 0, "
                          "last_fetch_ms = ?, last_ok_ms = ?, next_try_ms = NULL WHERE coin = ? AND tf = ?",
                          (int(now_ms), int(now_ms), coin, tf))

    def feed_error(self, coin: str, tf: str, now_ms: int, reason: str, next_try_ms: int) -> None:
        self.conn.execute(
            "UPDATE feeds SET state = 'error', error = ?, error_since_ms = COALESCE(error_since_ms, ?), "
            "error_count = error_count + 1, last_fetch_ms = ?, next_try_ms = ? WHERE coin = ? AND tf = ?",
            (reason[:300], int(now_ms), int(now_ms), int(next_try_ms), coin, tf))

    # ------------------------------------------------------------------------------------------------ series state
    def series(self, member_id: str, coin: str, tf: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM series_state WHERE member_id = ? AND coin = ? AND tf = ?",
                              (member_id, coin, tf)).fetchone()
        return None if r is None else dict(r)

    def put_series(self, member_id: str, coin: str, tf: str, status: str, now_ms: int, last_bar_ms: Optional[int] = None,
                   warm_have: int = 0, warm_need: int = 0, note: Optional[str] = None, keep_cursor: bool = True) -> None:
        """Set a series' status. The cursor (last processed bar) only moves forward and is kept when not given."""
        old = self.series(member_id, coin, tf)
        cur = last_bar_ms
        if keep_cursor and old and old["last_bar_ms"] is not None:
            cur = old["last_bar_ms"] if cur is None else max(int(cur), int(old["last_bar_ms"]))
        self.conn.execute(
            "INSERT INTO series_state (member_id, coin, tf, status, last_bar_ms, warm_have, warm_need, note, updated_ms) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(member_id, coin, tf) DO UPDATE SET status = excluded.status, "
            "last_bar_ms = excluded.last_bar_ms, warm_have = excluded.warm_have, warm_need = excluded.warm_need, "
            "note = excluded.note, updated_ms = excluded.updated_ms",
            (member_id, coin, tf, status, cur, int(warm_have), int(warm_need), note, int(now_ms)))

    def series_rows(self, member_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM series_state WHERE member_id = ? ORDER BY coin, tf",
                                                   (member_id,))]

    # ------------------------------------------------------------------------------------------------ signals and trades
    def add_signal(self, row: dict) -> bool:
        cols = ("signal_id", "member_id", "coin", "tf", "side", "bar_ms", "break_ms", "plan_entry", "stop", "target",
                "rr", "touches", "atr", "zone_lo", "zone_hi", "tz_lo", "tz_hi", "status", "recorded_ms")
        cur = self.conn.execute(f"INSERT OR IGNORE INTO signals ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                tuple(_py(row.get(c)) for c in cols))
        return cur.rowcount == 1

    def signal(self, signal_id: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM signals WHERE signal_id = ?", (signal_id,)).fetchone()
        return None if r is None else dict(r)

    def set_signal_status(self, signal_id: str, status: str) -> None:
        self.conn.execute("UPDATE signals SET status = ? WHERE signal_id = ?", (status, signal_id))

    def pending_signals(self, member_id: str, coin: str, tf: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM signals WHERE member_id = ? AND coin = ? AND tf = ? AND status = 'pending_entry' "
            "ORDER BY bar_ms", (member_id, coin, tf))]

    def add_trade(self, row: dict) -> bool:
        cols = ("trade_id", "member_id", "coin", "tf", "side", "signal_ms", "entry_ms", "entry_px", "stop_px",
                "target_px", "sl_dist", "tp_dist", "status", "exit_ms", "exit_px", "reason", "hold", "gross_raw",
                "gross", "fee", "funding", "net", "mae", "mfe", "recorded_ms", "closed_ms")
        cur = self.conn.execute(f"INSERT OR IGNORE INTO trades ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                tuple(_py(row.get(c)) for c in cols))
        return cur.rowcount == 1

    def close_trade(self, trade_id: str, row: dict, now_ms: int) -> None:
        self.conn.execute(
            "UPDATE trades SET status = 'closed', exit_ms = ?, exit_px = ?, reason = ?, hold = ?, gross_raw = ?, "
            "gross = ?, fee = ?, funding = ?, net = ?, mae = ?, mfe = ?, closed_ms = ? "
            "WHERE trade_id = ? AND status = 'open'",
            tuple(_py(row[k]) for k in ("exit_ms", "exit_px", "reason", "hold", "gross_raw", "gross", "fee", "funding",
                                        "net", "mae", "mfe")) + (int(now_ms), trade_id))

    def trade(self, trade_id: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM trades WHERE trade_id = ?", (trade_id,)).fetchone()
        return None if r is None else dict(r)

    def open_trade(self, member_id: str, coin: str, tf: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM trades WHERE member_id = ? AND coin = ? AND tf = ? AND status = 'open' "
                              "ORDER BY entry_ms LIMIT 1", (member_id, coin, tf)).fetchone()
        return None if r is None else dict(r)

    def last_exit_ms(self, member_id: str, coin: str, tf: str) -> Optional[int]:
        r = self.conn.execute("SELECT MAX(exit_ms) FROM trades WHERE member_id = ? AND coin = ? AND tf = ? "
                              "AND status = 'closed'", (member_id, coin, tf)).fetchone()
        return None if r is None or r[0] is None else int(r[0])

    def trades(self, member_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM trades WHERE member_id = ? ORDER BY entry_ms, coin, tf",
                                                   (member_id,))]

    def set_trade_account(self, rows: Iterable[tuple]) -> None:
        """rows: (acct_taken, acct_ret, acct_equity, acct_liq, trade_id)."""
        self.conn.executemany("UPDATE trades SET acct_taken = ?, acct_ret = ?, acct_equity = ?, acct_liq = ? "
                              "WHERE trade_id = ?", [tuple(_py(x) for x in r) for r in rows])

    # ------------------------------------------------------------------------------------------------ clones
    def add_clones(self, rows: list[dict]) -> int:
        cols = ("clone_id", "member_id", "trade_id", "k", "coin", "tf", "side", "sl_dist", "tp_dist", "offset_bars",
                "target_ms", "status", "created_ms")
        n = 0
        for r in rows:
            n += self.conn.execute(f"INSERT OR IGNORE INTO clones ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                   tuple(_py(r.get(c)) for c in cols)).rowcount
        return n

    def pending_clones(self, member_id: str, coin: Optional[str] = None, tf: Optional[str] = None) -> list[dict]:
        q, a = "SELECT * FROM clones WHERE member_id = ? AND status = 'pending'", [member_id]
        if coin is not None:
            q, a = q + " AND coin = ? AND tf = ?", a + [coin, tf]
        return [dict(r) for r in self.conn.execute(q + " ORDER BY target_ms, clone_id", a)]

    def oldest_pending_clone_ms(self, coin: str, tf: str) -> Optional[int]:
        """The earliest entry bar any member's pending clone of this coin / timeframe still needs (None = no pending clone)."""
        r = self.conn.execute("SELECT MIN(target_ms) FROM clones WHERE coin = ? AND tf = ? AND status = 'pending'",
                              (coin, tf)).fetchone()
        return None if r is None or r[0] is None else int(r[0])

    def pending_clone_series(self, member_id: str) -> list[tuple]:
        return [(r[0], r[1]) for r in self.conn.execute(
            "SELECT DISTINCT coin, tf FROM clones WHERE member_id = ? AND status = 'pending' ORDER BY coin, tf",
            (member_id,))]

    def update_clone(self, clone_id: str, row: dict) -> None:
        cols = ("status", "entry_ms", "entry_px", "exit_ms", "exit_px", "reason", "hold", "gross_raw", "gross", "fee",
                "funding", "net", "mae", "resolved_ms")
        self.conn.execute(f"UPDATE clones SET {', '.join(c + ' = ?' for c in cols)} WHERE clone_id = ?",
                          tuple(_py(row.get(c)) for c in cols) + (clone_id,))

    def clones_of(self, member_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM clones WHERE member_id = ? ORDER BY trade_id, k",
                                                   (member_id,))]

    # ------------------------------------------------------------------------------------------------ account
    def replace_account_daily(self, member_id: str, scope: str, rows: list[dict]) -> None:
        self.conn.execute("DELETE FROM account_daily WHERE member_id = ? AND scope = ?", (member_id, scope))
        self.conn.executemany(
            "INSERT INTO account_daily (member_id, scope, day_ms, equity, ret_pct, taken, liquidated, asof_ms) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(member_id, scope, int(r["day_ms"]), float(r["equity"]), float(r["ret_pct"]), int(r["taken"]),
              int(r["liquidated"]), int(r["asof_ms"])) for r in rows])


def _py(x: Any) -> Any:
    """numpy scalars to plain Python values for sqlite (NaN is stored as NULL, never as a number)."""
    if x is None:
        return None
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return None if x != x else x
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return int(bool(x))
    if isinstance(x, bool):
        return int(x)
    return x
