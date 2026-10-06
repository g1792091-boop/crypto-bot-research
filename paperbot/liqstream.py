"""Liquidation stream recorder (liq.db): every forced order Binance publishes, for all symbols.

    python -m paperbot.liqstream run    --db liq.db
    python -m paperbot.liqstream status --db liq.db

Source: the public WebSocket stream ``!forceOrder@arr`` (no API key). Binance sends at most the
latest liquidation per symbol per second on this stream, so bursts are undercounted; the counts
are still comparable from day to day. There is no public history, so what is not recorded
here is lost; ``conn_log`` shows when the stream was connected, so gaps are known.

The process runs under systemd (deploy/paperbot-liq.service, Restart=always). It reconnects with
backoff after an error, when no message (not even a ping) arrives for ``idle_s`` seconds, and
every 23 hours (Binance closes connections after 24 hours). One writer: this process.
"""

from __future__ import annotations

import argparse
import json
import signal
import sqlite3
import sys
import time
from typing import Callable, Optional

STREAM = "wss://fstream.binance.com/market/ws/!forceOrder@arr"  # 2026-10: Binance serves market streams under /market (the old /ws path connects but stays silent)

SCHEMA = """
CREATE TABLE IF NOT EXISTS liq (
    event_ts INTEGER NOT NULL, trade_ts INTEGER NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
    order_type TEXT, tif TEXT, qty REAL, price REAL, avg_price REAL, status TEXT,
    last_qty REAL, filled_qty REAL, received_ts INTEGER NOT NULL,
    UNIQUE (symbol, trade_ts, side, filled_qty, avg_price)
);
CREATE INDEX IF NOT EXISTS liq_sym_ts ON liq (symbol, trade_ts);
CREATE TABLE IF NOT EXISTS conn_log (ts INTEGER NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL);
"""


def parse(msg) -> list[tuple]:
    """Rows from one stream message (an event object, or a list of them). Unknown shapes -> []."""
    events = msg if isinstance(msg, list) else [msg]
    out = []
    for e in events:
        if not isinstance(e, dict):
            continue
        e = e.get("data", e)  # combined-stream wrapper
        o = e.get("o") if isinstance(e, dict) else None
        if e.get("e") != "forceOrder" or not isinstance(o, dict):
            continue
        f = lambda k: None if o.get(k) in (None, "") else float(o[k])  # noqa: E731
        out.append((int(e.get("E", 0)), int(o.get("T", 0)), str(o.get("s")), str(o.get("S")), o.get("o"),
                    o.get("f"), f("q"), f("p"), f("ap"), o.get("X"), f("l"), f("z")))
    return out


class LiqStore:
    def __init__(self, path: str, clock_ms: Optional[Callable[[], int]] = None):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def add(self, rows: list[tuple]) -> int:
        if not rows:
            return 0
        now = self.clock_ms()
        cur = self.conn.executemany("INSERT OR IGNORE INTO liq VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    [r + (now,) for r in rows])
        self.conn.commit()
        return cur.rowcount

    def log(self, event: str, detail) -> None:
        self.conn.execute("INSERT INTO conn_log VALUES (?,?,?)", (self.clock_ms(), event, json.dumps(detail, default=str)))
        self.conn.commit()

    def uptime_share(self, start: int, end: int) -> float:
        """Share of [start, end) with the stream connected, from conn_log."""
        rows = self.conn.execute("SELECT ts, event FROM conn_log WHERE event IN ('connected', 'disconnected') "
                                 "ORDER BY ts").fetchall()
        up, state, t0 = 0, False, start
        for ts, ev in rows:
            if ts >= end:
                break
            if ts > start and state:
                up += ts - max(t0, start)
            state, t0 = (ev == "connected"), ts
        if state:
            up += end - max(t0, start)
        return up / max(1, end - start)

    def close(self) -> None:
        self.conn.close()


class LiqRunner:
    def __init__(self, store: LiqStore, connect: Optional[Callable] = None, notifier=None,
                 idle_s: float = 600.0, max_conn_s: float = 23 * 3600, max_backoff: float = 60.0,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time,
                 alert_after_s: float = 300.0):
        self.store = store
        self.connect = connect or self._ws_connect
        self.notifier = notifier
        self.idle_s, self.max_conn_s, self.max_backoff = idle_s, max_conn_s, max_backoff
        self.sleep, self.clock = sleep, clock
        self.alert_after_s = alert_after_s
        self.stopping = False
        self.ws = None

    def _ws_connect(self):
        import websocket  # websocket-client (requirements.txt)
        return websocket.create_connection(STREAM, timeout=self.idle_s, enable_multithread=False)

    def stop(self, *_a) -> None:
        self.stopping = True
        ws = self.ws
        if ws is not None:  # unblock a pending recv()
            try:
                ws.shutdown()
            except Exception:  # noqa: BLE001
                pass

    def run(self, max_connections: Optional[int] = None) -> None:
        backoff, n, down_since = 1.0, 0, None
        while not self.stopping and (max_connections is None or n < max_connections):
            n += 1
            ws = None
            try:
                ws = self.ws = self.connect()
                self.store.log("connected", {"attempt": n})
                if down_since is not None and self.clock() - down_since >= self.alert_after_s and self.notifier:
                    from .notify import WARN
                    from .notify import secs_ko
                    self.notifier.send(WARN, f"청산 기록 끊김 후 복구\n\n바이낸스 청산 스트림 "
                                             f"{secs_ko(self.clock() - down_since)} 끊김\n지금 다시 연결됨 (그동안 기록은 없음)")
                down_since, backoff = None, 1.0
                opened = self.clock()
                while not self.stopping:
                    if self.clock() - opened >= self.max_conn_s:
                        self.store.log("disconnected", {"reason": "scheduled reconnect"})
                        break
                    raw = ws.recv()  # answers pings; raises on timeout or close
                    if raw in (None, "", b""):
                        continue
                    try:
                        self.store.add(parse(json.loads(raw)))
                    except ValueError as exc:
                        self.store.log("bad_message", {"error": str(exc), "head": str(raw)[:200]})
                if self.stopping:
                    self.store.log("disconnected", {"reason": "stop"})
            except Exception as exc:  # noqa: BLE001  network errors, timeouts, closes
                self.store.log("disconnected", {"error": f"{type(exc).__name__}: {exc}"[:300],
                                                "stopping": self.stopping})
                down_since = down_since or self.clock()
                if self.stopping:
                    break
                self.sleep(backoff)
                backoff = min(self.max_backoff, backoff * 2)
            finally:
                self.ws = None
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:  # noqa: BLE001
                        pass
        self.store.log("stopped", {"connections": n})


def status(store: LiqStore, now_ms: Optional[int] = None) -> dict:
    now = now_ms or int(time.time() * 1000)
    day = 86_400_000
    by_sym = store.conn.execute("SELECT symbol, COUNT(*), SUM(filled_qty * avg_price) FROM liq WHERE trade_ts >= ? "
                                "GROUP BY symbol ORDER BY 3 DESC LIMIT 15", (now - day,)).fetchall()
    return {"connected_share_last_24h": round(store.uptime_share(now - day, now), 4),
            "events_last_24h": store.conn.execute("SELECT COUNT(*) FROM liq WHERE trade_ts >= ?",
                                                  (now - day,)).fetchone()[0],
            "top_symbols_last_24h": [{"symbol": s, "events": c, "usd": round(v or 0)} for s, c, v in by_sym],
            "last_conn_events": [dict(zip(("ts", "event", "detail"), r)) for r in store.conn.execute(
                "SELECT * FROM conn_log ORDER BY ts DESC LIMIT 5").fetchall()]}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("run", "status"))
    ap.add_argument("--db", default="liq.db")
    args = ap.parse_args(argv)
    store = LiqStore(args.db)
    try:
        if args.cmd == "status":
            print(json.dumps(status(store), indent=2, default=str))
            return 0
        from .live import _notifier
        runner = LiqRunner(store, notifier=_notifier())
        signal.signal(signal.SIGTERM, runner.stop)
        signal.signal(signal.SIGINT, runner.stop)
        runner.run()
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
