"""후보 리그 runner: the league starts at its install time, catches up to now, then keeps up with the market; state in
SQLite, snapshots for the dashboard.

    python -m candleague run      [--db ...] [--snap ...] [--candidates ...]   (the service: loops forever)
    python -m candleague once     [...]                                       (one catch-up pass, then exit)
    python -m candleague status   [...]
    python -m candleague backup   [...]   (install script, engine stopped: copy the database when this code starts over)

Each pass processes (done, end] in chunks of at most one UTC day, ``end`` being the last 5-minute boundary whose 5m
kline is final (the 5m cache's own rule): signals of chart bars closing in the chunk (league.chunk_signals), the
chunk's 1m steps (public klines, mark-price klines, funding), league engines stepped (paramshadow.replay_day). The
engine states, the chunk's closed trades and ``done`` are committed together, so a stop at any point resumes cleanly.
Results are the same whether a day is processed at once or in 5-minute pieces (the engine only sees 1m bars).

The start (owners 2026-10-12: "커스텀값 봇 돌린 시점부터 ... 규칙봇 형식처럼"): every account starts with $5,000 at the
league's start ``meta.start_ms`` and every trade, balance and day count is from then on. The start is recorded once and
kept: a fresh database starts at its first run (floored to the 5-minute grid; CANDLEAGUE_START rebuilds a lost
database from a known start), and a league that starts over (another candidate list, a new VERSION) starts again from
the SAME recorded start, never from a later 'now'. VERSION 1 (until 2026-10-12) replayed from 2026-10-01 and recorded
only its install time (``meta.started_ms``); its first run under VERSION 2 starts over from that install time.
Before a start-over deletes anything, the whole old database is copied next to it (``backup_db``: e.g.
league_replay_from_1001_20261012.db; the install script makes the same copy before the code swap and the engine does
not copy twice). The copies are never shown on the dashboard.
"""

from __future__ import annotations

import glob
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
from . import summary as SM

REPLAY_FROM_MS = 1_790_812_800_000      # 2026-10-01 00:00 UTC: where VERSION 1 replayed from (history; nothing starts there now)
DAY = 86_400_000
FIVE = 300_000
SETTLE_MS = 90_000
# Bump when the meaning of a replay changes: the league starts over FROM ITS RECORDED START (meta.start_ms).
# 2 (owners 2026-10-12): the league starts at its install time; 1: replayed from 2026-10-01 (REPLAY_FROM_MS).
VERSION = 2
CARRY_KEYS = ("summary_day",)     # kv kept through a start-over (no second 09:00 summary on the day of an update)
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


def league_start(meta: dict, fresh_ms: int, now_ms: int) -> tuple[int, int]:
    """(start_ms, started_ms) of a league that starts (over) now from the database's old ``meta``.

    The start is the recorded meta.start_ms when there is one (a later VERSION or candidate list keeps it); a VERSION 1
    record (replayed from 2026-10-01, no start recorded) starts at its install time meta.started_ms; a fresh database
    at ``fresh_ms``. Floored to the engine's 5-minute grid (``done`` is always a 5-minute boundary). started_ms, the
    time the league was first installed, is kept as it is (``now_ms`` for a fresh database)."""
    started = int(meta.get("started_ms") or now_ms)
    if meta.get("start_ms") is not None:
        start = int(meta["start_ms"])
    elif meta.get("started_ms"):
        start = started
    else:
        start = int(fresh_ms)
    return start // FIVE * FIVE, started


def _utc(ms: int, fmt: str) -> str:
    return time.strftime(fmt, time.gmtime(ms / 1000))


def _record_of(conn) -> Optional[tuple]:
    """(fingerprint, done, trade rows) of a league database: what makes two copies the same record."""
    try:
        meta = _get(conn, "meta") or {}
        n = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    except sqlite3.Error:
        return None
    return meta.get("fingerprint"), meta.get("done"), int(n)


def backup_db(conn, db_path: str, meta: dict, now_ms: int) -> str:
    """Copy the whole league database ``conn`` (file ``db_path``) next to it before a start-over deletes its record:
    <stem>_replay_from_1001_<UTC date>.db for the VERSION 1 replay, <stem>_from_<MMDD>_<UTC date>.db for a later
    record (MMDD: its start). SQLite's backup (consistent while the WAL holds pages), stored as one plain file. A copy
    of the same record already there (the install script's, made before the code swap) is kept and not made again.
    Returns the copy's path; raises OSError / sqlite3.Error when it cannot copy (the caller then deletes nothing)."""
    folder = os.path.dirname(os.path.abspath(db_path))
    stem = os.path.splitext(os.path.basename(db_path))[0]
    mine = _record_of(conn)
    for old in sorted(glob.glob(os.path.join(folder, f"{stem}_*.db"))):
        try:
            c = sqlite3.connect(f"file:{old}?immutable=1", uri=True)
            try:
                if _record_of(c) == mine:
                    return old
            finally:
                c.close()
        except sqlite3.Error:
            continue
    what = "replay_from_1001" if meta.get("start_ms") is None else f"from_{_utc(int(meta['start_ms']), '%m%d')}"
    base = os.path.join(folder, f"{stem}_{what}_{_utc(now_ms, '%Y%m%d')}")
    path, k = base + ".db", 1
    while os.path.exists(path):
        k += 1
        path = f"{base}_{k}.db"
    tmp = f"{path}.part"
    try:
        dst = sqlite3.connect(tmp)
        try:
            conn.commit()
            conn.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
            dst.commit()
        finally:
            dst.close()
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


class League:
    """The league's accounts and their engines over the database ``conn``.

    ``start_ms`` is only the start of a league with nothing recorded yet (a fresh database; default: now floored to
    5 minutes). ``db_path`` (the file of ``conn``) is where a start-over keeps its copy of the old record; without it
    (tests on a database of their own) nothing is copied."""

    def __init__(self, conn, accts: list[dict], brackets: dict, specs: dict, lib, source,
                 fetch_steps: Callable, symbols, start_ms: Optional[int] = None, log: Callable[[str], None] = print,
                 db_path: Optional[str] = None, now_ms: Optional[int] = None):
        self.conn, self.accts, self.brackets, self.specs = conn, accts, brackets, specs
        self.lib, self.source, self.fetch_steps, self.symbols = lib, source, fetch_steps, list(symbols)
        self.log = log
        self.strategies = L.Strategies()
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        meta = _get(conn, "meta") or {}
        fp = fingerprint(accts)
        if meta.get("fingerprint") != fp or meta.get("start_ms") is None:
            start, started = league_start(meta, now if start_ms is None else int(start_ms), now)
            backup = None
            if meta and db_path:
                backup = backup_db(conn, db_path, meta, now)          # raises: nothing is deleted without a copy
            if meta:
                log(f"후보 목록이나 계산 방식이 바뀌어 시작 시각({_utc(start, '%m-%d %H:%M')} UTC)부터 새로 계산합니다"
                    + (f" (이전 기록 복사: {os.path.basename(backup)})" if backup else ""))
            keep = {k: _get(conn, k) for k in CARRY_KEYS}
            conn.execute("DELETE FROM kv")
            conn.execute("DELETE FROM trades")
            meta = {"fingerprint": fp, "done": start, "start_ms": start, "started_ms": started, "reset_ms": now}
            if backup:
                meta["backup"] = os.path.basename(backup)
            _put(conn, "meta", meta)
            for k, v in keep.items():
                if v is not None:
                    _put(conn, k, v)
            conn.commit()
        self.meta = meta
        self.start_ms = int(meta["start_ms"])
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
        after each committed chunk (a catch-up writes its snapshots as it goes)."""
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
def closed_trades(conn, accts: list[dict]) -> dict:
    """{account: its closed trades in exit order, the TRADE_KEYS fields only}: one read for every summary of a
    snapshot (the stored trade also carries its entry context, which no summary uses and would only take memory)."""
    book = {a["id"]: [] for a in accts}
    for aid, d in conn.execute("SELECT account, data FROM trades ORDER BY account, exit_time, rowid"):
        if aid in book:
            t = json.loads(d)
            book[aid].append({k: _finite(t.get(k)) for k in TRADE_KEYS})
    return book


def account_rows(conn, accts: list[dict], engines: dict, ds_money: bool = False, book: Optional[dict] = None) -> list[dict]:
    """Per account: trades, wins, mean P&L per trade as a fraction of the wallet before it, closed-trade drawdown,
    wallet, the open position; DeepSeek money hidden unless ``ds_money`` (D11)."""
    book = closed_trades(conn, accts) if book is None else book
    out = []
    for a in accts:
        pnl = [t["pnl"] for t in book[a["id"]]]
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
                                                 else pos.tp_price, "since": pos.entry_time, "lev": pos.leverage}}
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
              "pnl", "roe", "stop_initial", "tp_price", "mae_price", "mfe_price")
PRICE_KEYS = ("entry_price", "exit_price", "stop_initial", "tp_price", "mae_price", "mfe_price")


def _finite(v):
    """A stored NaN (a trade without a take-profit) as None: the snapshot is JSON a browser can read."""
    return None if isinstance(v, float) and not math.isfinite(v) else v


def trade_book(conn, accts: list[dict], ds_money: bool, start_ms: int, book: Optional[dict] = None) -> dict:
    """{account: {"equity": [[exit ms, wallet after]...] from $5,000, "trades": the last LAST_TRADES, newest first}};
    DeepSeek accounts without money (no equity line, no P&L) unless ``ds_money``."""
    book = closed_trades(conn, accts) if book is None else book
    out = {}
    for a in accts:
        rows = book[a["id"]]
        hide = a["kind"] == "ds" and not ds_money
        eq, curve = EQUITY, [[int(start_ms), EQUITY]]
        for t in rows:
            eq += t["pnl"]
            curve.append([int(t["exit_time"]), round(eq, 2)])
        last = [{k: t.get(k) for k in TRADE_KEYS} for t in rows[-LAST_TRADES:]][::-1]
        if hide:
            for t in last:                     # win / loss stays (a label); the money and the prices go
                t["win"] = bool(t["pnl"] is not None and t["pnl"] > 0)
                t["pnl"] = t["roe"] = None
                for k in PRICE_KEYS:
                    t[k] = None
        out[a["id"]] = {"equity": None if hide else curve, "trades": last}
    return out


def _write(snap: str, name: str, doc) -> None:
    tmp = os.path.join(snap, f".{name}.{os.getpid()}")
    with open(tmp, "w") as fh:
        json.dump(doc, fh, ensure_ascii=False)
    os.replace(tmp, os.path.join(snap, name))


def server_info(pass_s: Optional[float] = None) -> dict:
    """What the 상태 screen shows about the machine: load, CPUs, this process's peak memory, the last pass's time."""
    import resource
    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        load = None
    return {"load": load, "cpus": os.cpu_count(), "rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "pass_s": None if pass_s is None else round(pass_s, 2)}


def write_snapshots(snap: str, league: "League", now_ms: int, ds_money: bool = False,
                    pass_s: Optional[float] = None) -> dict:
    book = closed_trades(league.conn, league.accts)
    rows = account_rows(league.conn, league.accts, league.engines, ds_money, book)
    # the verdicts from the full rows (labels and counts only: a hidden DeepSeek pick still gets its pass / fail label)
    verdicts = judge(rows if ds_money else account_rows(league.conn, league.accts, league.engines, True, book))
    doc = {"generated_ms": now_ms, "done_ms": league.done, "lag_s": max(0, (now_ms - league.done) // 1000),
           "start_ms": league.start_ms, "started_ms": league.meta.get("started_ms"), "accounts": rows,
           "judge": verdicts, "notes": league.meta.get("notes", []), "ds_money": ds_money,
           "watch": SM.watch_summary(league.accts, book, now_ms, ds_money), "server": server_info(pass_s)}
    os.makedirs(snap, exist_ok=True)
    _write(snap, "trades.json", trade_book(league.conn, league.accts, ds_money, league.start_ms, book))
    _write(snap, "league.json", doc)
    return doc


def parse_start(text: Optional[str]) -> Optional[int]:
    """CANDLEAGUE_START / --start: a UTC time "2026-10-11T03:00Z" (or "2026-10-11 03:00") or epoch ms; None when empty.
    Only a fresh database uses it (to rebuild a lost league.db from its known start); a recorded start always wins."""
    import datetime
    t = (text or "").strip()
    if not t:
        return None
    if t.isdigit():
        return int(t)
    t = t.replace(" ", "T").rstrip("Zz")
    d = datetime.datetime.fromisoformat(t)
    return int(d.replace(tzinfo=d.tzinfo or datetime.timezone.utc).timestamp() * 1000)


def backup_if_reset(db: str, accts: list[dict], now_ms: Optional[int] = None) -> Optional[str]:
    """The install script's step while the engine is stopped, before the code swap: when this code would start the
    league over (its fingerprint differs from the database's), copy the database next to it now (backup_db; the engine
    finds this copy and does not make another). None when there is nothing to copy."""
    if not os.path.exists(db):
        return None
    conn = sqlite3.connect(db, timeout=30)
    try:
        try:
            meta = _get(conn, "meta")
        except sqlite3.Error:
            return None
        if not meta or (meta.get("fingerprint") == fingerprint(accts) and meta.get("start_ms") is not None):
            return None
        return backup_db(conn, db, meta, int(time.time() * 1000) if now_ms is None else now_ms)
    finally:
        conn.close()


def main(argv: Optional[list] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("run", "once", "status", "backup"))
    ap.add_argument("--db", default=os.environ.get("CANDLEAGUE_DB", "/var/lib/candleague/league.db"))
    ap.add_argument("--snap", default=os.environ.get("CANDLEAGUE_SNAP", "/var/lib/candleague/snap"))
    ap.add_argument("--candidates", default=os.environ.get("CANDLEAGUE_CANDIDATES", C.DEFAULT_FILE))
    ap.add_argument("--start", default=os.environ.get("CANDLEAGUE_START", ""),
                    help="UTC start of a FRESH database only (rebuild a lost league.db), e.g. 2026-10-11T03:00Z")
    ap.add_argument("--every", type=int, default=300, help="seconds between passes (run)")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        with open(os.path.join(a.snap, "league.json")) as fh:
            d = json.load(fh)
        st = d.get("start_ms")
        print(f"start {time.strftime('%Y-%m-%d %H:%M', time.gmtime(st / 1000)) if st else '-'} UTC, "
              f"done {time.strftime('%Y-%m-%d %H:%M', time.gmtime(d['done_ms'] / 1000))} UTC, "
              f"lag {d['lag_s']}s, accounts {len(d['accounts'])}")
        return 0
    if a.cmd == "backup":
        had = set(glob.glob(os.path.join(os.path.dirname(os.path.abspath(a.db)), "*.db")))
        path = backup_if_reset(a.db, C.accounts(C.load(a.candidates)))
        print("[후보 리그] 기록 복사 필요 없음 (이어서 계산)" if not path else
              f"[후보 리그] 새로 시작하기 전 기록을 이미 복사해 두었습니다: {path}" if path in had else
              f"[후보 리그] 새로 시작하기 전 기록 복사: {path}", flush=True)
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
    # owners 2026-10-11: DeepSeek money shown like core; 0 / off / false / no hides it again
    ds_money = os.environ.get("CANDLEAGUE_DS_MONEY", "1").strip().lower() not in ("0", "off", "false", "no")
    lg = League(conn, accts, brackets, specs, sweepsig.lib(), source, fetch, V3_SYMBOLS, start_ms=parse_start(a.start),
                db_path=a.db)
    from .notify import Notifier
    notifier = Notifier(conn)
    print(f"[후보 리그] {len(accts)} accounts, brackets: {src}, start {_utc(lg.start_ms, '%Y-%m-%d %H:%M')} UTC, "
          f"done {_utc(lg.done, '%Y-%m-%d %H:%M')} UTC", flush=True)
    write_snapshots(a.snap, lg, int(time.time() * 1000), ds_money)   # at once: a start-over replaces the old screens now
    while True:
        now = int(time.time() * 1000)
        t0 = time.monotonic()
        catching = final_end(now) - lg.done > 3 * FIVE      # a catch-up writes after each day; a live pass once, below
        n = lg.advance(final_end(now), on_chunk=(lambda: write_snapshots(a.snap, lg, int(time.time() * 1000), ds_money))
                       if catching else None)
        now = int(time.time() * 1000)                        # after the pass: the snapshot's time, the caught-up test
        doc = write_snapshots(a.snap, lg, now, ds_money, pass_s=time.monotonic() - t0)
        notifier.after_pass(doc, now, caught_up=final_end(now) - lg.done < 3 * FIVE)
        if n:
            print(f"[후보 리그] {n} chunk(s), done {time.strftime('%m-%d %H:%M', time.gmtime(lg.done / 1000))} UTC",
                  flush=True)
        if a.cmd == "once":
            return 0
        time.sleep(a.every)
