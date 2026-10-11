"""후보 리그 runner: catch up from 2026-10-01, then keep up with the market; state in SQLite, snapshots for the dashboard.

    python -m candleague run      [--db ...] [--snap ...] [--candidates ...]   (the service: loops forever)
    python -m candleague once     [...]                                       (one catch-up pass, then exit)
    python -m candleague status   [...]

Each pass processes (done, end] in chunks of at most one UTC day, ``end`` being the last 5-minute boundary whose 5m
kline is final (the 5m cache's own rule): signals of chart bars closing in the chunk (league.chunk_signals), the
chunk's 1m steps (public klines, mark-price klines, funding), league engines stepped (paramshadow.replay_day). The
engine states, the chunk's closed trades and ``done`` are committed together, so a stop at any point resumes cleanly.
Results are the same whether a day is processed at once or in 5-minute pieces (the engine only sees 1m bars).
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from dataclasses import asdict
from typing import Callable, Optional

from paperbot.engine import engine_state, restore_engine
from paperbot.paramshadow import replay_day

from . import candidates as C
from . import exits as X
from . import league as L

START_MS = 1_790_812_800_000            # 2026-10-01 00:00 UTC: the first day after the study's data
DAY = 86_400_000
FIVE = 300_000
SETTLE_MS = 90_000
VERSION = 1                       # bump when the meaning of a replay changes: the league starts over from START_MS
EQUITY = 5000.0
MIN_TRADES = 30


def open_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS trades (account TEXT NOT NULL, exit_time INTEGER NOT NULL, "
                 "data TEXT NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS trades_acct ON trades (account, exit_time)")
    conn.commit()
    return conn


def _get(conn, k: str):
    row = conn.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
    return json.loads(row[0]) if row else None


def _put(conn, k: str, v) -> None:
    conn.execute("INSERT OR REPLACE INTO kv VALUES (?, ?)", (k, json.dumps(v)))


def fingerprint(accts: list[dict]) -> str:
    import hashlib
    body = json.dumps([[a["id"], a["kind"], a["name"], a["tf"], a["combo"], a["exit"], a["role"], a.get("size", 1.0)]
                       for a in accts], sort_keys=True)
    return hashlib.sha256(f"{VERSION}|{body}".encode()).hexdigest()


class League:
    """The league's accounts and their engines over the database ``conn``."""

    def __init__(self, conn, accts: list[dict], brackets: dict, specs: dict, lib, source,
                 fetch_steps: Callable, symbols, start_ms: int = START_MS, log: Callable[[str], None] = print):
        self.conn, self.accts, self.brackets, self.specs = conn, accts, brackets, specs
        self.lib, self.source, self.fetch_steps, self.symbols = lib, source, fetch_steps, list(symbols)
        self.start_ms, self.log = start_ms, log
        self.strategies = L.Strategies()
        meta = _get(conn, "meta") or {}
        fp = fingerprint(accts)
        if meta.get("fingerprint") != fp:
            if meta:
                log("후보 목록이나 계산 방식이 바뀌어 처음(10/01)부터 다시 돌립니다")
            conn.execute("DELETE FROM kv")
            conn.execute("DELETE FROM trades")
            meta = {"fingerprint": fp, "done": start_ms, "started_ms": int(time.time() * 1000)}
            _put(conn, "meta", meta)
            conn.commit()
        self.meta = meta
        self.engines = L.make_engines(accts, brackets, specs)
        saved = _get(conn, "engines") or {}
        for aid, e in self.engines.items():
            if aid in saved:
                restore_engine(e, saved[aid])
        self.active = {a for a, e in self.engines.items() if e.position is not None or e.pending}

    @property
    def done(self) -> int:
        return int(self.meta["done"])

    def advance(self, end: int, on_chunk: Optional[Callable[[], None]] = None) -> int:
        """Process (done, end] in chunks of at most one UTC day; returns the number of chunks done. ``on_chunk`` runs
        after each committed chunk (the catch-up from 10-01 writes its snapshots as it goes)."""
        n = 0
        while self.done < end:
            a = self.done
            b = min(end, (a // DAY + 1) * DAY)
            by_close, notes = L.chunk_signals(self.lib, self.source, self.accts, self.symbols, a, b, self.start_ms,
                                              self.strategies)
            steps = self.fetch_steps(None, self.symbols, a, b)
            replay_day(self.engines, self.active, by_close, steps, self.brackets)
            rows = []
            for aid, e in self.engines.items():
                rows += [(aid, int(t.exit_time), json.dumps(asdict(t))) for t in e.trades]
                e.trades.clear()
            self.conn.executemany("INSERT INTO trades VALUES (?, ?, ?)", rows)
            self.meta["done"] = b
            self.meta["notes"] = notes[-20:]
            _put(self.conn, "engines", {aid: engine_state(e) for aid, e in self.engines.items()})
            _put(self.conn, "meta", self.meta)
            self.conn.commit()
            n += 1
            if on_chunk is not None:
                on_chunk()
        return n


EXCHANGE_FILE = os.path.join(C.ROOT, "research", "fullgrid", "exchange.json")


def load_exchange(path: str, symbols) -> tuple:
    """(brackets, symbol specs, source) from the study's exchange.json (dump_exchange.py on the paper bot server):
    the same leverage table and order-size rules the study used."""
    from paperbot.margin import Brackets
    with open(path) as fh:
        doc = json.load(fh)
    by = {p["symbol"]: Brackets.from_binance(p) for p in doc["brackets"]}
    specs = {s: {"qty_step": float(doc["specs"][s]["qty_step"]), "min_notional": float(doc["specs"][s]["min_notional"])}
             for s in symbols}
    return {s: by[s] for s in symbols}, specs, f"{os.path.basename(path)} ({doc.get('fetched_utc')})"


def final_end(now_ms: int) -> int:
    """The last 5-minute boundary whose 5m bar is final now (dscheck.RestSource's rule)."""
    return (now_ms - SETTLE_MS) // FIVE * FIVE


# ---------------------------------------------------------------- summaries (dashboard, Telegram, judging)
def account_rows(conn, accts: list[dict], engines: dict, ds_money: bool = False) -> list[dict]:
    """Per account: trades, wins, mean P&L per trade as a fraction of the wallet before it, closed-trade drawdown,
    wallet, the open position; DeepSeek money hidden unless ``ds_money`` (D11)."""
    out = []
    for a in accts:
        pnl = [json.loads(d)["pnl"] for (d,) in
               conn.execute("SELECT data FROM trades WHERE account = ? ORDER BY exit_time", (a["id"],))]
        eq, rets, peak, dd = EQUITY, [], EQUITY, 0.0
        for p in pnl:
            rets.append(p / eq if eq > 0 else 0.0)
            eq += p
            peak = max(peak, eq)
            dd = max(dd, 1 - eq / peak if peak > 0 else 0.0)
        e = engines[a["id"]]
        pos = e.position
        row = {"id": a["id"], "role": a["role"], "kind": a["kind"], "name": a["name"], "tf": a["tf"],
               "exit": a["exit"], "exit_ko": X.exit_ko(a["exit"]), "combo": a["combo"], "of": a.get("of"),
               "size": a.get("size", 1.0),
               "source": a.get("source", {}), "trades": len(pnl), "wins": sum(p > 0 for p in pnl),
               "mean_ret": (sum(rets) / len(rets)) if rets else None, "wallet": e.wallet, "max_dd": dd,
               "bust": bool(e.bust),
               "open": None if pos is None else {"symbol": pos.symbol, "side": pos.side, "entry": pos.entry_price,
                                                 "stop": pos.stop_price, "tp": None if math.isnan(pos.tp_price)
                                                 else pos.tp_price, "since": pos.entry_time}}
        if a["kind"] == "ds" and not ds_money:
            for k in ("mean_ret", "wallet", "max_dd"):
                row[k] = None
            if row["open"]:
                row["open"] = {"symbol": pos.symbol, "side": pos.side, "since": pos.entry_time}
        out.append(row)
    return out


def band_status(trades: int, mean: Optional[float], band: Optional[dict]) -> Optional[dict]:
    """The forward mean against the backtest band (PHASE2_PREREG 8) at the largest trade count reached."""
    if not band or mean is None:
        return None
    ns = sorted(int(n) for n in band if int(n) <= trades)
    if not ns:
        return None
    b = band[str(ns[-1])]
    return {"n": ns[-1], "below": bool(mean < b["p5"]), "p5": b["p5"], "median": b["median"]}


def judge(rows: list[dict]) -> dict:
    """{candidate id: verdict} by CONTRACT.md 2: under MIN_TRADES 'early'; else mean > 0, > its cell's base, > its
    flip ('ok' only when all three)."""
    by_id = {r["id"]: r for r in rows}
    out = {}
    for r in rows:
        if r["role"] != "cand":
            continue
        band = band_status(r["trades"], r["mean_ret"], (r.get("source") or {}).get("band"))
        extra = {"band": band} if band else {}
        base = by_id.get(f"base-{r['kind']}-{r['name']}-{r['tf']}")
        flip = by_id.get(f"{r['id']}-flip")
        if r["trades"] < MIN_TRADES or r["mean_ret"] is None:
            out[r["id"]] = {"verdict": "early", "trades": r["trades"], **extra}
            continue
        checks = {"positive": r["mean_ret"] > 0,
                  "beats_base": base is not None and base["mean_ret"] is not None and r["mean_ret"] > base["mean_ret"],
                  "beats_flip": flip is not None and flip["mean_ret"] is not None and r["mean_ret"] > flip["mean_ret"]}
        out[r["id"]] = {"verdict": "ok" if all(checks.values()) else "not_yet", "trades": r["trades"], **checks, **extra}
    return out


LAST_TRADES = 200
TRADE_KEYS = ("symbol", "side", "entry_time", "entry_price", "exit_time", "exit_price", "exit_reason", "leverage",
              "pnl", "roe")


def trade_book(conn, accts: list[dict], ds_money: bool = False, start_ms: int = START_MS) -> dict:
    """{account: {"equity": [[exit ms, wallet after]...] from $5,000, "trades": the last LAST_TRADES, newest first}};
    DeepSeek accounts without money (no equity line, no P&L) unless ``ds_money``."""
    out = {}
    for a in accts:
        rows = [json.loads(d) for (d,) in
                conn.execute("SELECT data FROM trades WHERE account = ? ORDER BY exit_time", (a["id"],))]
        hide = a["kind"] == "ds" and not ds_money
        eq, curve = EQUITY, [[int(start_ms), EQUITY]]
        for t in rows:
            eq += t["pnl"]
            curve.append([int(t["exit_time"]), round(eq, 2)])
        last = [{k: t.get(k) for k in TRADE_KEYS} for t in rows[-LAST_TRADES:]][::-1]
        if hide:
            for t in last:
                t["pnl"] = t["roe"] = None
        out[a["id"]] = {"equity": None if hide else curve, "trades": last}
    return out


def _write(snap: str, name: str, doc) -> None:
    tmp = os.path.join(snap, f".{name}.{os.getpid()}")
    with open(tmp, "w") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, os.path.join(snap, name))


def write_snapshots(snap: str, league: "League", now_ms: int, ds_money: bool = False) -> dict:
    rows = account_rows(league.conn, league.accts, league.engines, ds_money)
    doc = {"generated_ms": now_ms, "done_ms": league.done, "lag_s": max(0, (now_ms - league.done) // 1000),
           "start_ms": league.start_ms, "accounts": rows, "judge": judge(rows), "notes": league.meta.get("notes", []),
           "ds_money": ds_money}
    os.makedirs(snap, exist_ok=True)
    _write(snap, "trades.json", trade_book(league.conn, league.accts, ds_money, league.start_ms))
    _write(snap, "league.json", doc)
    return doc


def main(argv: Optional[list] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("run", "once", "status"))
    ap.add_argument("--db", default=os.environ.get("CANDLEAGUE_DB", "/var/lib/candleague/league.db"))
    ap.add_argument("--snap", default=os.environ.get("CANDLEAGUE_SNAP", "/var/lib/candleague/snap"))
    ap.add_argument("--candidates", default=os.environ.get("CANDLEAGUE_CANDIDATES", C.DEFAULT_FILE))
    ap.add_argument("--every", type=int, default=300, help="seconds between passes (run)")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        with open(os.path.join(a.snap, "league.json")) as fh:
            d = json.load(fh)
        print(f"done {time.strftime('%Y-%m-%d %H:%M', time.gmtime(d['done_ms'] / 1000))} UTC, "
              f"lag {d['lag_s']}s, accounts {len(d['accounts'])}")
        return 0
    from paperbot import sweepsig
    from paperbot.binance import BinanceREST
    from paperbot.config import V3_SYMBOLS
    from paperbot.paramshadow import RestSource, make_fetcher
    rest = BinanceREST()
    brackets, specs, src = load_exchange(os.environ.get("CANDLEAGUE_EXCHANGE", EXCHANGE_FILE), V3_SYMBOLS)
    accts = C.accounts(C.load(a.candidates))
    conn = open_db(a.db)
    source = RestSource(os.path.join(os.path.dirname(a.db), "bars5m.db"), rest=rest)

    def fetch(_rest, syms, s, e):
        return make_fetcher(rest, syms, s, e)(rest, syms, s, e)
    ds_money = os.environ.get("CANDLEAGUE_DS_MONEY") == "1"
    lg = League(conn, accts, brackets, specs, sweepsig.lib(), source, fetch, V3_SYMBOLS)
    from .notify import Notifier
    notifier = Notifier(conn)
    print(f"[후보 리그] {len(accts)} accounts, brackets: {src}, done {lg.done}", flush=True)
    while True:
        now = int(time.time() * 1000)
        n = lg.advance(final_end(now), on_chunk=lambda: write_snapshots(a.snap, lg, int(time.time() * 1000), ds_money))
        doc = write_snapshots(a.snap, lg, now, ds_money)
        notifier.after_pass(doc, now, caught_up=final_end(now) - lg.done < 3 * FIVE)
        if n:
            print(f"[후보 리그] {n} chunk(s), done {time.strftime('%m-%d %H:%M', time.gmtime(lg.done / 1000))} UTC",
                  flush=True)
        if a.cmd == "once":
            return 0
        time.sleep(a.every)
