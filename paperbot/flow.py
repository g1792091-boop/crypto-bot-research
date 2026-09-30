"""Order-flow archive (flow.db): open interest, long/short ratios, taker flow and premium index.

    python -m paperbot.flow sync   --flow flow.db [--since 2023-10-01]
    python -m paperbot.flow status --flow flow.db

Binance keeps the 5-minute open-interest and ratio statistics for 30 days only, so this runs
every hour (deploy/paperbot-flow.timer). If a run finds that data older than the exchange's
window was never stored, the missing span is written to ``gaps`` and a warning is sent: that
data cannot be fetched again from the exchange (the public archive at data.binance.vision is
the only other source).

Contents (all UTC milliseconds; one writer: this command):
    oi5m             sum_oi, sum_oi_value                    (openInterestHist)
    ls_global5m      ratio, long_share, short_share          (globalLongShortAccountRatio)
    ls_top_account5m ratio, long_share, short_share          (topLongShortAccountRatio)
    ls_top_position5m ratio, long_share, short_share         (topLongShortPositionRatio)
    taker5m          buy_sell_ratio, buy_vol, sell_vol       (takerlongshortRatio)
    premium5m        open, high, low, close of the premium index (premiumIndexKlines; full
                     history is available, so the first run backfills from --since)
Column names of the public archive's daily "metrics" files map to these as:
    sum_open_interest(_value) = oi5m.sum_oi(_value); count_long_short_ratio = ls_global5m.ratio;
    count_toptrader_long_short_ratio = ls_top_account5m.ratio;
    sum_toptrader_long_short_ratio = ls_top_position5m.ratio;
    sum_taker_long_short_vol_ratio = taker5m.buy_sell_ratio.
Stored rows are never changed; a different value returned later goes to ``revisions``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from typing import Callable, Iterable, Optional

from .archive import FIVE_MIN, RECORD_SYMBOLS, _differs

WINDOW_MS = 29 * 86_400_000  # stay a day inside the exchange's 30-day history
PAGE = 500

STATS = {
    # dataset: (table, [(column, response field)])
    "oi": ("oi5m", [("sum_oi", "sumOpenInterest"), ("sum_oi_value", "sumOpenInterestValue")]),
    "ls_global": ("ls_global5m", [("ratio", "longShortRatio"), ("long_share", "longAccount"),
                                  ("short_share", "shortAccount")]),
    "ls_top_account": ("ls_top_account5m", [("ratio", "longShortRatio"), ("long_share", "longAccount"),
                                            ("short_share", "shortAccount")]),
    "ls_top_position": ("ls_top_position5m", [("ratio", "longShortRatio"), ("long_share", "longAccount"),
                                              ("short_share", "shortAccount")]),
    "taker": ("taker5m", [("buy_sell_ratio", "buySellRatio"), ("buy_vol", "buyVol"), ("sell_vol", "sellVol")]),
}
PREMIUM_COLS = ("open", "high", "low", "close")


def _schema() -> str:
    parts = []
    for table, cols in STATS.values():
        body = ", ".join(f"{c} REAL" for c, _f in cols)
        parts.append(f"CREATE TABLE IF NOT EXISTS {table} (symbol TEXT NOT NULL, ts INTEGER NOT NULL, {body}, "
                     f"received_ts INTEGER NOT NULL, PRIMARY KEY (symbol, ts));")
    parts.append("""
CREATE TABLE IF NOT EXISTS premium5m (
    symbol TEXT NOT NULL, ts INTEGER NOT NULL, open REAL, high REAL, low REAL, close REAL,
    received_ts INTEGER NOT NULL, PRIMARY KEY (symbol, ts)
);
CREATE TABLE IF NOT EXISTS revisions (
    ts INTEGER NOT NULL, tbl TEXT NOT NULL, symbol TEXT NOT NULL, time INTEGER NOT NULL,
    old TEXT NOT NULL, new TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gaps (
    ts INTEGER NOT NULL, symbol TEXT NOT NULL, dataset TEXT NOT NULL,
    from_ts INTEGER NOT NULL, to_ts INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_log (
    ts INTEGER NOT NULL, symbol TEXT NOT NULL, dataset TEXT NOT NULL, added INTEGER NOT NULL,
    revised INTEGER NOT NULL, last_time INTEGER, requests INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS system_log (ts INTEGER NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL);
""")
    return "\n".join(parts)


class FlowArchive:
    def __init__(self, path: str, clock_ms: Optional[Callable[[], int]] = None):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_schema())
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def insert(self, table: str, cols: tuple, symbol: str, rows: Iterable[tuple]) -> tuple[int, int]:
        added = revised = 0
        now = self.clock_ms()
        sel = f"SELECT {', '.join(cols)} FROM {table} WHERE symbol = ? AND ts = ?"
        allc = ("symbol", "ts") + cols + ("received_ts",)
        ins = f"INSERT INTO {table} ({', '.join(allc)}) VALUES ({', '.join('?' * len(allc))})"
        for ts, vals in rows:
            old = self.conn.execute(sel, (symbol, ts)).fetchone()
            if old is None:
                self.conn.execute(ins, (symbol, ts) + tuple(vals) + (now,))
                added += 1
            elif any(_differs(o, v) for o, v in zip(old, vals)):
                self.conn.execute("INSERT INTO revisions VALUES (?,?,?,?,?,?)", (
                    now, table, symbol, ts, json.dumps(dict(zip(cols, old))), json.dumps(dict(zip(cols, vals)))))
                revised += 1
        self.conn.commit()
        return added, revised

    def last_time(self, table: str, symbol: str) -> Optional[int]:
        return self.conn.execute(f"SELECT MAX(ts) FROM {table} WHERE symbol = ?", (symbol,)).fetchone()[0]

    def count(self, table: str, symbol: str, start: int, end: int) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE symbol = ? AND ts >= ? AND ts < ?",
                                 (symbol, start, end)).fetchone()[0]

    def log(self, table: str, row: tuple) -> None:
        self.conn.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(row))})", row)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _num(x) -> Optional[float]:
    return None if x in (None, "") else float(x)


def sync(fa: FlowArchive, rest, symbols: Iterable[str], since_ms: int, pace: float = 0.2,
         sleep: Callable[[float], None] = time.sleep) -> dict:
    """Fetch closed 5m statistics from the last stored point (at most 29 days back) up to now on
    the exchange clock, and premium-index 5m bars from the last stored bar (or ``since_ms``)."""
    now = rest.server_time()
    floor = now - WINDOW_MS
    summary: dict = {"exchange_now": now, "symbols": {}, "gaps": []}
    for sym in symbols:
        s: dict = {}
        for ds, (table, fields) in STATS.items():
            cols = tuple(c for c, _f in fields)
            last = fa.last_time(table, sym)
            if last is not None and last + FIVE_MIN < floor:
                fa.log("gaps", (fa.clock_ms(), sym, ds, last + FIVE_MIN, floor))
                summary["gaps"].append({"symbol": sym, "dataset": ds, "from": last + FIVE_MIN, "to": floor})
            start = floor if last is None else max(last, floor)  # the last point is fetched again
            added = revised = reqs = 0
            last_seen = last
            while start < now:
                end = min(start + PAGE * FIVE_MIN, now)
                rows = rest.flow_stats(ds, sym, "5m", start_time=start, end_time=end, limit=PAGE)
                reqs += 1
                vals = []
                for r in rows:
                    ts = int(r["timestamp"])
                    if ts + FIVE_MIN > now:  # the current period is not closed yet
                        continue
                    vals.append((ts, tuple(_num(r.get(f)) for _c, f in fields)))
                a, rv = fa.insert(table, cols, sym, vals)
                added, revised = added + a, revised + rv
                if vals:
                    last_seen = max(last_seen or 0, vals[-1][0])
                start = end + 1
                sleep(pace)
            fa.log("sync_log", (fa.clock_ms(), sym, ds, added, revised, last_seen, reqs))
            s[ds] = {"added": added, "revised": revised, "requests": reqs, "last": last_seen}
        last = fa.last_time("premium5m", sym)
        start = last if last is not None else since_ms
        added = revised = reqs = 0
        while start < now:
            rows = rest.premium_klines(sym, "5m", start_time=start, limit=1500)
            reqs += 1
            closed = [r for r in rows if int(r[6]) < now]
            vals = [(int(r[0]), tuple(float(r[i]) for i in (1, 2, 3, 4))) for r in closed]
            a, rv = fa.insert("premium5m", PREMIUM_COLS, sym, vals)
            added, revised = added + a, revised + rv
            if len(rows) < 1500 or not closed:
                break
            start = int(closed[-1][0]) + FIVE_MIN
            sleep(pace)
        fa.log("sync_log", (fa.clock_ms(), sym, "premium", added, revised, fa.last_time("premium5m", sym), reqs))
        s["premium"] = {"added": added, "revised": revised, "requests": reqs}
        summary["symbols"][sym] = s
    return summary


def status(fa: FlowArchive, symbols: Iterable[str], now_ms: Optional[int] = None) -> dict:
    now = now_ms or int(time.time() * 1000)
    day = 86_400_000
    out: dict = {"coverage_last_24h": {}, "gaps": [], "last_runs": []}
    for sym in symbols:
        out["coverage_last_24h"][sym] = {
            t: f"{fa.count(t, sym, now - day, now)}/288"
            for t in [v[0] for v in STATS.values()] + ["premium5m"]}
    out["gaps"] = [dict(zip(("ts", "symbol", "dataset", "from", "to"), r)) for r in
                   fa.conn.execute("SELECT * FROM gaps ORDER BY ts DESC LIMIT 20").fetchall()]
    out["last_runs"] = [dict(zip(("ts", "event", "detail"), r)) for r in
                        fa.conn.execute("SELECT ts, event, substr(detail, 1, 200) FROM system_log "
                                        "ORDER BY ts DESC LIMIT 5").fetchall()]
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("sync", "status"):
        p = sub.add_parser(name)
        p.add_argument("--flow", default="flow.db")
        p.add_argument("--symbols", default=",".join(RECORD_SYMBOLS))
        if name == "sync":
            p.add_argument("--since", help="premium-index backfill start date (UTC), default 3 years back")
            p.add_argument("--pace", type=float, default=0.2)
    args = ap.parse_args(argv)
    symbols = [s for s in args.symbols.split(",") if s]
    fa = FlowArchive(args.flow)
    try:
        if args.cmd == "status":
            print(json.dumps(status(fa, symbols), indent=2, default=str))
            return 0
        from .live import _notifier, _rest
        from .notify import WARN
        from .record import _since_ms
        summary = sync(fa, _rest(), symbols, _since_ms(args.since), pace=args.pace)
        fa.log("system_log", (fa.clock_ms(), "sync", json.dumps(summary, default=str)))
        if summary["gaps"]:
            _notifier().send(WARN, f"order-flow archive: {len(summary['gaps'])} spans older than the exchange's "
                                   f"30-day window were never stored (first: {summary['gaps'][0]})")
        print(json.dumps(summary, indent=2, default=str))
        return 0
    finally:
        fa.close()


if __name__ == "__main__":
    sys.exit(main())
