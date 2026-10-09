"""SQLite store of the demo lab bot (/var/lib/demobot/demo.db): bars, funding, signals, trade outcomes ("cells"),
decisions of the switching accounts, Telegram bookkeeping, and small key/value facts.

Cell row = one possible entry: (coin, timeframe, signal bar, side). Its outcome under every exit is stored as two
blobs: ``f`` float32 [NF] and ``t`` int64 [NT] (layout below). A cell is ``done`` when every exit has finished.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Optional

import numpy as np

from . import grid as G

# float layout of a cell
F_MAIN_R, F_MAIN_G, F_MAIN_REASON = 0, 1, 2
F_TP_R = 3                     # 12
F_TP_G = 15                    # 12
F_L_R = 27                     # 4 (20/30/40/50)
F_L_REASON = 31                # 4
F_L_EXIT = 35                  # 4 raw exit price at L
F_MAIN_EXIT = 39
F_HB_R, F_HB_G, F_HB_EXIT = 40, 41, 42   # exit 13: half at 1R, break-even, rest at 1.5R
NF = 43
# int layout (exit bar open time, ms; -1 while open)
T_MAIN = 0
T_TP = 1                       # 12
T_L = 13                       # 4
T_HB = 17
NT = 18

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS bars(coin TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL,
  PRIMARY KEY(coin, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS funding(coin TEXT, ts INTEGER, rate REAL, PRIMARY KEY(coin, ts)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sigs(coin TEXT, tf TEXT, ts INTEGER, strat TEXT, longs BLOB, shorts BLOB, src TEXT,
  PRIMARY KEY(coin, tf, ts, strat)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS cells(coin TEXT, tf TEXT, ts INTEGER, side INTEGER, e_ts INTEGER, done INTEGER,
  atr REAL, raw REAL, f BLOB, t BLOB, PRIMARY KEY(coin, tf, ts, side)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS cells_open ON cells(done) WHERE done = 0;
CREATE TABLE IF NOT EXISTS decisions(acct TEXT, seq INTEGER, t_ms INTEGER, coin TEXT, L INTEGER, combo INTEGER,
  exit INTEGER, info TEXT, PRIMARY KEY(acct, seq, coin, L)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS notified(acct TEXT, key TEXT, status TEXT, ts_ms INTEGER, PRIMARY KEY(acct, key))
  WITHOUT ROWID;
"""


def default_db() -> str:
    return os.environ.get("DEMOBOT_DB", "/var/lib/demobot/demo.db")


def default_snap() -> str:
    return os.environ.get("DEMOBOT_SNAP", "/var/lib/demobot/snap")


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    path = path or default_db()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


class Tx:
    """`with Tx(conn):` one write transaction."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, et, ev, tb):
        self.conn.execute("ROLLBACK" if et else "COMMIT")
        return False


# ------------------------------------------------------------------ meta
def get_meta(conn, k: str, default=None):
    r = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else default


def set_meta(conn, k: str, v) -> None:
    conn.execute("INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))


# ------------------------------------------------------------------ bars / funding
def put_bars(conn, coin: str, rows) -> int:
    """rows: iterable of (ts_ms, o, h, l, c, v); replaces existing rows of the same time."""
    rows = list(rows)
    conn.executemany("INSERT OR REPLACE INTO bars(coin, ts, o, h, l, c, v) VALUES(?,?,?,?,?,?,?)",
                     [(coin, int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows])
    return len(rows)


def load_bars(conn, coin: str, since_ms: int = 0) -> dict:
    a = conn.execute("SELECT ts, o, h, l, c, v FROM bars WHERE coin=? AND ts>=? ORDER BY ts", (coin, since_ms)).fetchall()
    if not a:
        z = np.zeros(0)
        return {"ts": z.astype(np.int64), "o": z, "h": z, "l": z, "c": z, "v": z}
    x = np.array(a, float)
    return {"ts": x[:, 0].astype(np.int64), "o": x[:, 1], "h": x[:, 2], "l": x[:, 3], "c": x[:, 4], "v": x[:, 5]}


def last_bar_ts(conn, coin: str) -> Optional[int]:
    r = conn.execute("SELECT MAX(ts) FROM bars WHERE coin=?", (coin,)).fetchone()
    return int(r[0]) if r and r[0] is not None else None


def put_funding(conn, coin: str, rows) -> None:
    conn.executemany("INSERT OR REPLACE INTO funding(coin, ts, rate) VALUES(?,?,?)",
                     [(coin, int(t), float(r)) for t, r in rows])


def load_funding(conn, coin: str) -> tuple[np.ndarray, np.ndarray]:
    a = conn.execute("SELECT ts, rate FROM funding WHERE coin=? ORDER BY ts", (coin,)).fetchall()
    if not a:
        return np.zeros(0, np.int64), np.zeros(0)
    x = np.array(a, float)
    return x[:, 0].astype(np.int64), x[:, 1]


# ------------------------------------------------------------------ signals
def put_sigs(conn, coin: str, tf: str, ts_ms: int, strat: str, longs: np.ndarray, shorts: np.ndarray,
             src: str) -> None:
    conn.execute("INSERT OR REPLACE INTO sigs(coin, tf, ts, strat, longs, shorts, src) VALUES(?,?,?,?,?,?,?)",
                 (coin, tf, int(ts_ms), strat, np.asarray(longs, np.int16).tobytes(),
                  np.asarray(shorts, np.int16).tobytes(), src))


def put_sigs_many(conn, rows) -> None:
    """rows: (coin, tf, ts, strat, longs int16 array, shorts int16 array, src)."""
    conn.executemany("INSERT OR REPLACE INTO sigs(coin, tf, ts, strat, longs, shorts, src) VALUES(?,?,?,?,?,?,?)",
                     [(c, tf, int(t), s, np.asarray(lg, np.int16).tobytes(), np.asarray(sh, np.int16).tobytes(), src)
                      for c, tf, t, s, lg, sh, src in rows])


def load_sigs(conn, coin: str, tf: str, strat: str, since_ms: int = 0):
    """(ts int64, combo int16, side int8) flat arrays sorted by time."""
    ts_l, c_l, s_l = [], [], []
    for t, lg, sh in conn.execute("SELECT ts, longs, shorts FROM sigs WHERE coin=? AND tf=? AND strat=? AND ts>=? "
                                  "ORDER BY ts", (coin, tf, strat, since_ms)):
        a = np.frombuffer(lg, np.int16)
        b = np.frombuffer(sh, np.int16)
        if len(a):
            ts_l.append(np.full(len(a), t, np.int64))
            c_l.append(a)
            s_l.append(np.ones(len(a), np.int8))
        if len(b):
            ts_l.append(np.full(len(b), t, np.int64))
            c_l.append(b)
            s_l.append(-np.ones(len(b), np.int8))
    if not ts_l:
        return np.zeros(0, np.int64), np.zeros(0, np.int16), np.zeros(0, np.int8)
    return np.concatenate(ts_l), np.concatenate(c_l), np.concatenate(s_l)


def sig_times(conn, coin: str, tf: str) -> set:
    return {r[0] for r in conn.execute("SELECT DISTINCT ts FROM sigs WHERE coin=? AND tf=?", (coin, tf))}


# ------------------------------------------------------------------ cells
def put_cells(conn, rows) -> None:
    """rows: (coin, tf, ts, side, e_ts, done, atr, raw, f float32[NF], t int64[NT])."""
    conn.executemany("INSERT OR REPLACE INTO cells(coin, tf, ts, side, e_ts, done, atr, raw, f, t) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?)",
                     [(c, tf, int(ts), int(sd), int(e), int(d), float(a), float(rw),
                       np.asarray(f, np.float32).tobytes(), np.asarray(t, np.int64).tobytes())
                      for c, tf, ts, sd, e, d, a, rw, f, t in rows])


def load_cells(conn, coin: str, tf: str, since_ms: int = 0):
    """Arrays of all cells of (coin, tf) since since_ms, sorted by (ts, side): ts, side, e_ts, done, atr, raw,
    F (n, NF) float32, T (n, NT) int64."""
    rows = conn.execute("SELECT ts, side, e_ts, done, atr, raw, f, t FROM cells WHERE coin=? AND tf=? AND ts>=? "
                        "ORDER BY ts, side", (coin, tf, since_ms)).fetchall()
    n = len(rows)
    out = {"ts": np.zeros(n, np.int64), "side": np.zeros(n, np.int8), "e_ts": np.zeros(n, np.int64),
           "done": np.zeros(n, bool), "atr": np.zeros(n), "raw": np.zeros(n),
           "F": np.zeros((n, NF), np.float32), "T": np.zeros((n, NT), np.int64)}
    for i, (ts, sd, e, d, a, rw, f, t) in enumerate(rows):
        out["ts"][i], out["side"][i], out["e_ts"][i], out["done"][i] = ts, sd, e, d
        out["atr"][i], out["raw"][i] = a, rw
        out["F"][i] = np.frombuffer(f, np.float32)
        out["T"][i] = np.frombuffer(t, np.int64)
    return out


# ------------------------------------------------------------------ decisions / notified
def put_decision(conn, acct: str, seq: int, t_ms: int, coin: str, L: int, combo: int, ex: int, info: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO decisions(acct, seq, t_ms, coin, L, combo, exit, info) VALUES(?,?,?,?,?,?,?,?)",
                 (acct, int(seq), int(t_ms), coin, int(L), int(combo), int(ex), json.dumps(info, ensure_ascii=False)))


def load_decisions(conn, acct: str) -> list:
    return [dict(seq=s, t_ms=t, coin=c, L=L, combo=cb, exit=ex, info=json.loads(i or "{}"))
            for s, t, c, L, cb, ex, i in conn.execute(
                "SELECT seq, t_ms, coin, L, combo, exit, info FROM decisions WHERE acct=? ORDER BY seq, coin, L",
                (acct,))]


def notified_keys(conn, acct: str) -> dict:
    return {k: s for k, s in conn.execute("SELECT key, status FROM notified WHERE acct=?", (acct,))}


def put_notified(conn, rows) -> None:
    now = int(time.time() * 1000)
    conn.executemany("INSERT OR REPLACE INTO notified(acct, key, status, ts_ms) VALUES(?,?,?,?)",
                     [(a, k, s, now) for a, k, s in rows])


def db_mb(path: Optional[str] = None) -> float:
    path = path or default_db()
    tot = 0
    for suf in ("", "-wal", "-shm"):
        try:
            tot += os.path.getsize(path + suf)
        except OSError:
            pass
    return tot / 1e6


def write_json(path: str, obj) -> None:
    """Atomic JSON write (temp file + os.replace); NaN/inf become null."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(_clean(obj), fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def write_npz(path: str, **arrs) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **arrs)
    os.replace(tmp, path)


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if np.isfinite(f) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    return o


assert len(G.LEVS) == 4 and NF == F_HB_EXIT + 1 and NT == T_HB + 1
