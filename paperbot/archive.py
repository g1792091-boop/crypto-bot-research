"""Market data archive for the signal recorder (market.db).

Only the recorder process writes this database (one writer per database,
handover 5.3). Contents, all UTC milliseconds:
    kline5m   closed 5m bars from Binance USD-M futures REST, with volume,
              quote volume, trade count and taker-buy volume
    mark5m    closed 5m mark-price bars
    funding   funding settlements (time, rate, mark price)
    revisions a stored row that the exchange later returned with different
              values; the stored row is kept (the log is never rewritten)
    sync_log / system_log   what was fetched when, code version, events

Bars are added once and never changed. The forming bar (close time not yet
passed on the exchange clock) is never stored.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Callable, Iterable, Optional

from .config import Settings

FIVE_MIN = 300_000
# XRP is recorded for the fixed-date re-judgement (7 coins) and never traded.
RECORD_SYMBOLS: tuple[str, ...] = Settings().symbols + ("XRPUSDT",)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kline5m (
    symbol TEXT NOT NULL, open_time INTEGER NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume REAL NOT NULL, quote_volume REAL, trades INTEGER, taker_buy_volume REAL,
    received_ts INTEGER NOT NULL, src TEXT NOT NULL,
    PRIMARY KEY (symbol, open_time)
);
CREATE TABLE IF NOT EXISTS mark5m (
    symbol TEXT NOT NULL, open_time INTEGER NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    received_ts INTEGER NOT NULL,
    PRIMARY KEY (symbol, open_time)
);
CREATE TABLE IF NOT EXISTS funding (
    symbol TEXT NOT NULL, funding_time INTEGER NOT NULL, rate REAL NOT NULL,
    mark_price REAL, received_ts INTEGER NOT NULL,
    PRIMARY KEY (symbol, funding_time)
);
CREATE TABLE IF NOT EXISTS revisions (
    ts INTEGER NOT NULL, tbl TEXT NOT NULL, symbol TEXT NOT NULL, time INTEGER NOT NULL,
    old TEXT NOT NULL, new TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_log (
    ts INTEGER NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL, added INTEGER NOT NULL,
    revised INTEGER NOT NULL, first_time INTEGER, last_time INTEGER, requests INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS system_log (
    ts INTEGER NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL
);
"""

_KLINE_COLS = ("open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_volume")
_MARK_COLS = ("open", "high", "low", "close")


def _differs(a, b) -> bool:
    if a is None or b is None:
        return a is not b
    a, b = float(a), float(b)
    return abs(a - b) > 1e-12 * max(1.0, abs(a), abs(b))


class MarketArchive:
    def __init__(self, path: str, clock_ms: Optional[Callable[[], int]] = None):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    # ------------------------------------------------------------ writes
    def _insert(self, table: str, key_col: str, cols: tuple, symbol: str,
                rows: Iterable[tuple], extra: dict) -> tuple[int, int]:
        added = revised = 0
        now = self.clock_ms()
        sel = f"SELECT {', '.join(cols)} FROM {table} WHERE symbol = ? AND {key_col} = ?"
        allcols = ("symbol", key_col) + cols + tuple(extra)
        ins = f"INSERT INTO {table} ({', '.join(allcols)}) VALUES ({', '.join('?' * len(allcols))})"
        for key, vals in rows:
            old = self.conn.execute(sel, (symbol, key)).fetchone()
            if old is None:
                self.conn.execute(ins, (symbol, key) + tuple(vals) + tuple(extra.values()))
                added += 1
            elif any(_differs(o, v) for o, v in zip(old, vals)):
                self.conn.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?)", (
                    now, table, symbol, key, json.dumps(dict(zip(cols, old))),
                    json.dumps(dict(zip(cols, vals)))))
                revised += 1
        self.conn.commit()
        return added, revised

    def insert_klines(self, symbol: str, rows: list[list], exchange_now: int,
                      src: str = "rest") -> tuple[int, int, Optional[int]]:
        """Binance kline rows. Rows whose close time has not passed on the
        exchange clock (the forming bar) are skipped. Returns (added, revised,
        last closed open time)."""
        closed = [r for r in rows if int(r[6]) < exchange_now]
        vals = [(int(r[0]), (float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]),
                             float(r[7]), int(r[8]), float(r[9]))) for r in closed]
        a, rv = self._insert("kline5m", "open_time", _KLINE_COLS, symbol, vals,
                             {"received_ts": self.clock_ms(), "src": src})
        return a, rv, (int(closed[-1][0]) if closed else None)

    def insert_marks(self, symbol: str, rows: list[list], exchange_now: int) -> tuple[int, int, Optional[int]]:
        closed = [r for r in rows if int(r[6]) < exchange_now]
        vals = [(int(r[0]), (float(r[1]), float(r[2]), float(r[3]), float(r[4]))) for r in closed]
        a, rv = self._insert("mark5m", "open_time", _MARK_COLS, symbol, vals,
                             {"received_ts": self.clock_ms()})
        return a, rv, (int(closed[-1][0]) if closed else None)

    def insert_funding(self, symbol: str, rows: list[dict]) -> tuple[int, int, Optional[int]]:
        vals = [(int(r["fundingTime"]), (float(r["fundingRate"]),
                                         float(r["markPrice"]) if r.get("markPrice") not in (None, "") else None))
                for r in rows]
        a, rv = self._insert("funding", "funding_time", ("rate", "mark_price"), symbol, vals,
                             {"received_ts": self.clock_ms()})
        return a, rv, (vals[-1][0] if vals else None)

    def log_sync(self, symbol: str, kind: str, added: int, revised: int, first: Optional[int],
                 last: Optional[int], requests: int) -> None:
        self.conn.execute("INSERT INTO sync_log VALUES (?,?,?,?,?,?,?,?)",
                          (self.clock_ms(), symbol, kind, added, revised, first, last, requests))
        self.conn.commit()

    def log_system(self, event: str, detail) -> None:
        self.conn.execute("INSERT INTO system_log VALUES (?,?,?)",
                          (self.clock_ms(), event, json.dumps(detail, default=str)))
        self.conn.commit()

    # ------------------------------------------------------------ reads
    def last_time(self, table: str, symbol: str) -> Optional[int]:
        col = "funding_time" if table == "funding" else "open_time"
        return self.conn.execute(f"SELECT MAX({col}) FROM {table} WHERE symbol = ?",
                                 (symbol,)).fetchone()[0]

    def first_time(self, table: str, symbol: str) -> Optional[int]:
        col = "funding_time" if table == "funding" else "open_time"
        return self.conn.execute(f"SELECT MIN({col}) FROM {table} WHERE symbol = ?",
                                 (symbol,)).fetchone()[0]

    def load_5m(self, symbol: str, start: Optional[int] = None, end: Optional[int] = None):
        """pandas DataFrame in the layout sweep_lib.read_ohlcv produces:
        ts (datetime64[ns, UTC], bar open), open, high, low, close, volume."""
        import pandas as pd
        q = "SELECT open_time, open, high, low, close, volume FROM kline5m WHERE symbol = ?"
        args: list = [symbol]
        if start is not None:
            q += " AND open_time >= ?"
            args.append(start)
        if end is not None:
            q += " AND open_time < ?"
            args.append(end)
        rows = self.conn.execute(q + " ORDER BY open_time", args).fetchall()
        df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"])
        out = pd.DataFrame({"ts": pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
                            .astype("datetime64[ns, UTC]")})
        for k in ("open", "high", "low", "close", "volume"):
            out[k] = df[k].astype(float).to_numpy()
        return out

    def coverage(self, symbol: str, start: int, end: int, table: str = "kline5m") -> dict:
        n = self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE symbol = ? AND open_time >= ? "
                              f"AND open_time < ?", (symbol, start, end)).fetchone()[0]
        expected = max(0, (end - start) // FIVE_MIN)
        return {"recorded": n, "expected": expected, "missing": max(0, expected - n),
                "last_open": self.last_time(table, symbol)}

    def close(self) -> None:
        self.conn.close()


def sync(archive: MarketArchive, rest, symbols: Iterable[str], since_ms: int,
         pace: float = 0.15, sleep: Callable[[float], None] = time.sleep,
         page: int = 1000) -> dict:
    """Fetch closed 5m bars, 5m mark bars and funding from the last stored
    row (or ``since_ms`` for a new symbol) up to now on the exchange clock.
    The last stored bar is fetched again so a changed value is noticed.
    ``pace`` spaces requests (limit-1000 klines weigh 5 of the 2,400/min budget)."""
    exchange_now = rest.server_time()
    summary: dict = {"exchange_now": exchange_now, "symbols": {}}
    for sym in symbols:
        s: dict = {}
        for kind, table, fetch, insert in (
                ("kline", "kline5m", rest.klines, archive.insert_klines),
                ("mark", "mark5m", rest.mark_klines, archive.insert_marks)):
            last = archive.last_time(table, sym)
            start = last if last is not None else since_ms
            added = revised = reqs = 0
            first_new = last_seen = None
            while start < exchange_now:
                rows = fetch(sym, "5m", start_time=start, limit=page)
                reqs += 1
                if not rows:
                    break
                a, rv, last_closed = insert(sym, rows, exchange_now)
                added += a
                revised += rv
                if a and first_new is None:
                    first_new = int(rows[0][0])
                if last_closed is not None:
                    last_seen = last_closed
                nxt = int(rows[-1][0]) + FIVE_MIN
                if len(rows) < page or nxt <= start or last_closed is None:
                    break
                start = nxt
                sleep(pace)
            archive.log_sync(sym, kind, added, revised, first_new, last_seen, reqs)
            s[kind] = {"added": added, "revised": revised, "requests": reqs, "last_open": last_seen}
        last_f = archive.last_time("funding", sym)
        start = last_f + 1 if last_f is not None else since_ms
        added = revised = reqs = 0
        last_ft = None
        while True:
            rows = rest.funding_rates(sym, start_time=start, limit=page)
            reqs += 1
            if not rows:
                break
            a, rv, lt = archive.insert_funding(sym, rows)
            added += a
            revised += rv
            last_ft = lt
            if len(rows) < page or lt is None:
                break
            start = lt + 1
            sleep(pace)
        archive.log_sync(sym, "funding", added, revised, None, last_ft, reqs)
        s["funding"] = {"added": added, "revised": revised, "requests": reqs}
        summary["symbols"][sym] = s
        sleep(pace)
    return summary
