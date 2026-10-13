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
kept (league_start): in the database, and in a small file next to it (<stem>_start.json, start_file) that VERSION 1
code, a lost database or a start-over never touch. A fresh database starts at its first run (floored to the 5-minute
grid; CANDLEAGUE_START, with its time zone, rebuilds a lost database AND file from a known start), and a league that
starts over (another candidate list, a new VERSION) starts again from the SAME recorded start, never from a later
'now'. VERSION 1 (until 2026-10-12) replayed from 2026-10-01 and recorded only its install time
(``meta.started_ms``); its first run under VERSION 2 starts over from that install time.
Before a start-over deletes anything, the whole old database is copied next to it (``backup_db``: e.g.
league_replay_from_1001_20261012.db; the install script makes the same copy before the code swap and the engine does
not copy twice). The copies are never shown on the dashboard.
The restarted league (research/exitflex/PREREG_EXITFLEX.md section 11): when the rules file (candleague/data/rules.json,
CANDLEAGUE_RULES) exists and is enabled ("enabled": true is the owners' OK), the league's accounts are candleague/rulex.py's (PREREG
11.2: -n, -nq, -e, -eq, -nflip, or -e, -eq, -eflip in a pool without a new exit; both pools), in the database given by --db, instead of the
candidate accounts; there is no second side league. The install script copies the old database first (``backup``), the start is the
new install time, and the install time written down by the restart script (CANDLEAGUE_EXPECT_START / --expect-start) is checked against
the start before anything is deleted or written (``check_expected_start``): a lost database AND start file would otherwise start the
league at 'now' without a word and move every C1 / C2 date (PREREG 11.3). A fresh database says loudly where its start came from.
Per commit the league also writes ``acct_day`` (signals decided, trades closed, per account and UTC day) and, at every 00:00 UTC,
``acct_mark`` (the realised wallet and the mark value of an open position): PREREG 11.4 items 10-11; the C1 / C2 script reads them.
The rules file may instead hold the owners' exits (2026-10-12, ``"owner_exits"``, rulex.owner_accounts): per pick its current exit
(role ``cand``, id <pick>-e) and the other exits side by side on the same signals, by the same mechanism; the snapshot then carries
``lineup`` (the account kinds in the owners' words) and the judging of CONTRACT 2 says ``na`` (no 기본값 or 동전 accounts).
Catching up (the snapshot's ``catching``) is said only by a snapshot written right after the league started over or
after a committed chunk, while the processed time is more than 30 minutes behind: a restart that makes no progress (a
crash loop, Binance down) writes nothing, so the dashboard shows the engine as stopped, not as catching up.
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

from paperbot.config import V3_INITIAL
from paperbot.engine import engine_state, restore_engine
from paperbot.paramshadow import replay_day

from . import candidates as C
from . import exits as X
from . import league as L
from . import rulex as RX
from . import summary as SM

REPLAY_FROM_MS = 1_790_812_800_000      # 2026-10-01 00:00 UTC: where VERSION 1 replayed from (history; nothing starts there now)
DAY = 86_400_000
FIVE = 300_000
SETTLE_MS = 90_000
# Bump when the meaning of a replay changes: the league starts over FROM ITS RECORDED START (meta.start_ms).
# 2 (owners 2026-10-12): the league starts at its install time; 1: replayed from 2026-10-01 (REPLAY_FROM_MS).
VERSION = 2
CARRY_KEYS = ("summary_day",)     # kv kept through a start-over (no second 09:00 summary on the day of an update)
EQUITY = X.start_equity()          # every account's start wallet: CANDLEAGUE_EQUITY (the owners' league: 1000), else the paper bot's 5000
MIN_TRADES = 30
CATCHING_MS = 30 * 60_000        # the snapshot's ``catching``: processed time this far behind the clock (dash.py, lk.js)
PROGRESS_MS = 15 * 60_000        # ... and a chunk committed (or the league started over) at most this long before


def open_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS trades (account TEXT NOT NULL, exit_time INTEGER NOT NULL, "
                 "data TEXT NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS trades_acct ON trades (account, exit_time)")
    # PREREG_EXITFLEX 11.4 items 10-11 (rule accounts only; empty in a league without them): per account and UTC day the signals decided
    # (offered = entered + skipped while holding + rejected) and the trades closed; at every 00:00 UTC the realised wallet and the mark
    conn.execute("CREATE TABLE IF NOT EXISTS acct_day (account TEXT NOT NULL, day INTEGER NOT NULL, offered INTEGER NOT NULL, "
                 "entered INTEGER NOT NULL, skipped INTEGER NOT NULL, rejected INTEGER NOT NULL, closed INTEGER NOT NULL, "
                 "PRIMARY KEY (account, day))")
    conn.execute("CREATE TABLE IF NOT EXISTS acct_mark (account TEXT NOT NULL, day INTEGER NOT NULL, wallet REAL NOT NULL, "
                 "marked REAL NOT NULL, PRIMARY KEY (account, day))")
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
                       + ([a["rule"], RX.code_version(a["rule"]), a.get("no_entry_from_ms")] if a.get("rule") else [])
                       + (["weekend_off"] if a.get("weekend_off") else [])
                       + (["coin"] if a.get("coin") else [])
                       + (["tighten", a["tighten"]] if a.get("tighten") else [])
                       + (["equity0", X.start_equity()] if X.start_equity() != V3_INITIAL else [])
                       + (["ulad", list(X.ULAD_FIRST + X.ULAD_SECOND + (X.ULAD_STEP,))] if str(a["exit"]).startswith(X.ULAD + "|") else [])
                       for a in accts], sort_keys=True)     # rule accounts: + the rule, what its meaning depends on, and the C1 stop time;
    #                                                         the owner-exit league's weekend switch (an account without it: as before)
    return hashlib.sha256(f"{VERSION}|{body}".encode()).hexdigest()


def league_start(meta: dict, now_ms: int, saved: Optional[dict] = None,
                 explicit: Optional[int] = None) -> tuple[int, int]:
    """(start_ms, started_ms) of a league that starts (over) now, from the database's old ``meta``, the start file next
    to it (``saved``: {start_ms, started_ms}) and an explicit start (CANDLEAGUE_START / --start), in this order:

    1. the database's recorded start (meta.start_ms; a later VERSION or candidate list keeps it) and its install time;
    2. the start file (written with every start: it survives a database that VERSION 1 code started over without
       recording a start, e.g. after moving back to app.old, and a lost database);
    3. an explicit start (a lost database and file rebuilt from a known start): it is the install time too, so the
       dashboard shows no replay before an install;
    4. a VERSION 1 record (replayed from 2026-10-01, no start recorded): its install time meta.started_ms;
    5. a fresh database: now.

    The start is floored to the engine's 5-minute grid (``done`` is always a 5-minute boundary); started_ms, the time
    the league was first installed, is kept as it is."""
    if meta.get("start_ms") is not None:
        start = int(meta["start_ms"])
        started = int(meta.get("started_ms") or (saved or {}).get("started_ms") or start)
    elif saved:
        start, started = int(saved["start_ms"]), int(saved["started_ms"])
    elif explicit is not None:
        start = started = int(explicit)
    elif meta.get("started_ms"):
        start = started = int(meta["started_ms"])
    else:
        start = started = int(now_ms)
    return start // FIVE * FIVE, started


def start_file(db_path: str) -> str:
    """<stem>_start.json next to the database (league_start.json for league.db): the league's start and install time."""
    folder = os.path.dirname(os.path.abspath(db_path))
    return os.path.join(folder, f"{os.path.splitext(os.path.basename(db_path))[0]}_start.json")


def read_start_file(db_path: Optional[str]) -> Optional[dict]:
    """{start_ms, started_ms} from start_file(db_path); None when there is none or it cannot be read."""
    if not db_path:
        return None
    try:
        with open(start_file(db_path)) as fh:
            d = json.load(fh)
        return {"start_ms": int(d["start_ms"]), "started_ms": int(d["started_ms"])}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_start_file(db_path: str, start_ms: int, started_ms: int, log: Callable[[str], None] = print) -> None:
    """Write start_file(db_path) atomically; a failure is logged (the database still records the start)."""
    path = start_file(db_path)
    tmp = f"{path}.{os.getpid()}.part"
    try:
        with open(tmp, "w") as fh:
            json.dump({"start_ms": int(start_ms), "started_ms": int(started_ms),
                       "start_utc": _utc(int(start_ms), "%Y-%m-%dT%H:%MZ"),
                       "note": "후보 리그의 시작 시각 (지우지 마세요: 엔진이 다시 계산할 때 이 시각부터 시작합니다)"}, fh,
                      ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        log(f"[후보 리그] 시작 시각 파일을 쓰지 못했습니다 ({type(exc).__name__}): {path}")
        try:
            os.remove(tmp)
        except OSError:
            pass


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


class StartMismatch(RuntimeError):
    """The league's start is not the install time it was told to expect (PREREG_EXITFLEX 11.3): it stops before any trade is shown."""


def check_expected_start(start_ms: int, expect_ms: Optional[int], where: str = "") -> None:
    """PREREG 11.3: the league's start must equal the install time floored to 5 minutes. A lost database AND start file would
    otherwise start the league at 'now' without a word and move every C1 / C2 date, which count days from the install. ``expect_ms``
    None = no expectation (the league as before). Raises StartMismatch with the way out (CANDLEAGUE_START = the install time)."""
    if expect_ms is None:
        return
    want = int(expect_ms) // FIVE * FIVE
    if int(start_ms) != want:
        raise StartMismatch(
            f"{where}시작 시각 {_utc(int(start_ms), '%Y-%m-%d %H:%M')} UTC가 설치 시각 {_utc(want, '%Y-%m-%d %H:%M')} UTC(5분 단위)와 다릅니다. "
            f"리그를 멈춥니다. 데이터베이스와 시작 시각 파일이 모두 없어졌다면 CANDLEAGUE_START={_utc(want, '%Y-%m-%dT%H:%MZ')} 로 "
            f"설치 시각부터 다시 만드세요.")


class League:
    """The league's accounts and their engines over the database ``conn``.

    ``start_ms`` is an explicit start (CANDLEAGUE_START), used only when neither the database nor its start file
    records one (league_start). ``expect_start_ms`` (CANDLEAGUE_EXPECT_START: the install time the restart script wrote down,
    PREREG_EXITFLEX 11.3) is checked against the start BEFORE anything is deleted or written: a different start raises
    StartMismatch (``check_expected_start``). ``db_path`` (the file of ``conn``) is where a start-over keeps its copy of the old
    record and where the start file lives; without it (tests on a database of their own) nothing is copied or written
    next to it. ``reset`` is True when this construction started the league (over); ``advanced_ms`` is the wall time
    of the last start-over or committed chunk of this process (None before either: the snapshot then never says
    'catching up')."""

    def __init__(self, conn, accts: list[dict], brackets: dict, specs: dict, lib, source,
                 fetch_steps: Callable, symbols, start_ms: Optional[int] = None, log: Callable[[str], None] = print,
                 db_path: Optional[str] = None, now_ms: Optional[int] = None,
                 clock: Optional[Callable[[], int]] = None, expect_start_ms: Optional[int] = None):
        self.conn, self.accts, self.brackets, self.specs = conn, accts, brackets, specs
        self.lib, self.source, self.fetch_steps, self.symbols = lib, source, fetch_steps, list(symbols)
        self.log = log
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.strategies = L.Strategies()
        now = self.clock() if now_ms is None else int(now_ms)
        meta = _get(conn, "meta") or {}
        saved = read_start_file(db_path)
        fp = fingerprint(accts)
        self.reset = meta.get("fingerprint") != fp or meta.get("start_ms") is None
        self.advanced_ms: Optional[int] = None
        if not self.reset:
            check_expected_start(int(meta["start_ms"]), expect_start_ms, "데이터베이스의 ")
        if self.reset:
            start, started = league_start(meta, now, saved, start_ms)
            check_expected_start(start, expect_start_ms)                # before anything is copied, deleted or written
            backup = None
            if meta and db_path:
                backup = backup_db(conn, db_path, meta, now)          # raises: nothing is deleted without a copy
            if meta:
                log(f"후보 목록이나 계산 방식이 바뀌어 시작 시각({_utc(start, '%m-%d %H:%M')} UTC)부터 새로 계산합니다"
                    + (f" (이전 기록 복사: {os.path.basename(backup)})" if backup else ""))
            else:                                                     # a fresh database: say where its start came from, loudly (11.3)
                src = "시작 시각 파일" if saved else "CANDLEAGUE_START" if start_ms is not None else "지금(기록된 시작 없음)"
                old = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(db_path)),
                                                    os.path.splitext(os.path.basename(db_path))[0] + "_*.db"))) if db_path else []
                log(f"[후보 리그] 새 데이터베이스를 만듭니다: 시작 {_utc(start, '%Y-%m-%d %H:%M')} UTC ({src})"
                    + (f"; 같은 폴더에 이전 기록 복사 {len(old)}개가 있습니다 ({os.path.basename(old[-1])})" if old else ""))
                if src.startswith("지금") and expect_start_ms is None:
                    log("[후보 리그] 경고: 시작 시각이 지금으로 정해졌습니다. 설치 시각과 다르면 CANDLEAGUE_EXPECT_START를 주어 막으세요")
            keep = {k: _get(conn, k) for k in CARRY_KEYS}
            conn.execute("DELETE FROM kv")
            conn.execute("DELETE FROM trades")
            conn.execute("DELETE FROM acct_day")
            conn.execute("DELETE FROM acct_mark")
            meta = {"fingerprint": fp, "done": start, "start_ms": start, "started_ms": started, "reset_ms": now}
            if backup:
                meta["backup"] = os.path.basename(backup)
            _put(conn, "meta", meta)
            for k, v in keep.items():
                if v is not None:
                    _put(conn, k, v)
            conn.commit()
            self.advanced_ms = now
        self.meta = meta
        self.start_ms = int(meta["start_ms"])
        if db_path and saved != {"start_ms": self.start_ms, "started_ms": int(meta.get("started_ms") or self.start_ms)}:
            if saved is not None and not self.reset:
                log(f"[후보 리그] 시작 시각 파일({_utc(saved['start_ms'], '%Y-%m-%d %H:%M')} UTC)이 데이터베이스의 시작"
                    f"({_utc(self.start_ms, '%Y-%m-%d %H:%M')} UTC)과 달라 데이터베이스의 값으로 고칩니다")
            write_start_file(db_path, self.start_ms, int(meta.get("started_ms") or self.start_ms), log)
        self.engines = L.make_engines(accts, brackets, specs)
        saved_engines = _get(conn, "engines") or {}
        for aid, e in self.engines.items():
            if aid in saved_engines:
                restore_engine(e, saved_engines[aid])
        self.active = {a for a, e in self.engines.items() if e.position is not None or e.pending}
        # rule accounts (candleague.rulex): their signals and chart records come from RX.chunk_rule, the others from
        # L.chunk_signals; a restored rule position's state is checked against a recomputation from the bars
        self.rule_accts = [a for a in accts if a.get("rule")]
        self.plain_accts = [a for a in accts if not a.get("rule")]
        # a league with rule accounts places fills and checks on each coin's own minutes, as the study's kernel does
        # (RX.replay_day): {coin: its last minute present} and {coin: funding waiting for the coin's next minute}, kept in
        # the database with the engines
        self.seen: dict = {k: int(v) for k, v in (_get(conn, "seen") or {}).items()} if self.rule_accts else {}
        self.fund_wait: dict = {k: float(v) for k, v in (_get(conn, "fund_wait") or {}).items()} if self.rule_accts else {}
        self.last_close: dict = {k: float(v) for k, v in (_get(conn, "last_close") or {}).items()} if self.rule_accts else {}
        if self.rule_accts:
            for e in self.engines.values():
                e.rx_seen = self.seen
        self.restore_notes: list[str] = []
        if any(self.engines[a["id"]].position is not None for a in self.rule_accts):
            self.restore_notes = RX.audit_restored(self, log)

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
            if not self.rule_accts:
                by_close, notes = L.chunk_signals(self.lib, self.source, self.accts, self.symbols, a, b, self.start_ms,
                                                  self.strategies)
            else:                       # rule accounts: their own signals and chart records (rulex), the others as before
                by_close, notes = (L.chunk_signals(self.lib, self.source, self.plain_accts, self.symbols, a, b,
                                                   self.start_ms, self.strategies) if self.plain_accts else ({}, []))
                rule_close, rule_notes = RX.chunk_rule(self.lib, self.source, self.rule_accts, self.symbols, a, b,
                                                       self.start_ms, self.strategies)
                for close, items in rule_close.items():
                    by_close.setdefault(close, []).extend(items)
                notes = self.restore_notes + notes + rule_notes
                self.restore_notes = []
            steps = self.fetch_steps(None, self.symbols, a, b)
            stats: dict = {}
            if self.rule_accts:
                RX.replay_day(self.engines, self.active, by_close, steps, self.brackets, self.seen, self.fund_wait, stats,
                              self.last_close)
            else:
                replay_day(self.engines, self.active, by_close, steps, self.brackets)
            rows = []
            for aid, e in self.engines.items():
                rows += [(aid, int(t.exit_time), json.dumps(asdict(t))) for t in e.trades]
                for t in e.trades:                                  # PREREG 11.4 item 10: trades closed per account and UTC day
                    stats.setdefault((aid, int(t.exit_time) // DAY * DAY), [0, 0, 0])
                e.trades.clear()
            self.conn.executemany("INSERT INTO trades VALUES (?, ?, ?)", rows)
            if self.rule_accts:
                closed: dict = {}
                for aid, exit_time, _d in rows:
                    closed[(aid, exit_time // DAY * DAY)] = closed.get((aid, exit_time // DAY * DAY), 0) + 1
                self.conn.executemany(
                    "INSERT INTO acct_day VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(account, day) DO UPDATE SET "
                    "offered = offered + excluded.offered, entered = entered + excluded.entered, skipped = skipped + excluded.skipped, "
                    "rejected = rejected + excluded.rejected, closed = closed + excluded.closed",
                    [(aid, day, sum(c), c[0], c[1], c[2], closed.get((aid, day), 0)) for (aid, day), c in sorted(stats.items())])
                if b % DAY == 0:                                    # 00:00 UTC (PREREG 11.4 item 11): the realised wallet and the mark
                    self.conn.executemany("INSERT OR REPLACE INTO acct_mark VALUES (?, ?, ?, ?)",
                                          [(aid, b, e.wallet, RX.mark_value(e, self.last_close)) for aid, e in self.engines.items()])
            self.meta["done"] = b
            self.meta["notes"] = notes[-20:]
            _put(self.conn, "engines", {aid: engine_state(e) for aid, e in self.engines.items()})
            if self.rule_accts:
                _put(self.conn, "seen", self.seen)
                _put(self.conn, "fund_wait", self.fund_wait)
                _put(self.conn, "last_close", self.last_close)
            _put(self.conn, "meta", self.meta)
            self.conn.commit()
            self.advanced_ms = self.clock()
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


HOLD_HOURS = (4, 8, 18)


def hold_stats(trades: list[dict]) -> dict:
    """PREREG_EXITFLEX 11.4 item 12: hold-time aggregates over every closed trade since the start: count, median hold hours and the
    shares held more than 4 h, 8 h and 18 h (hold hours and counts only, so a DeepSeek row may carry them, D11)."""
    import statistics
    h = [(t["exit_time"] - t["entry_time"]) / 3_600_000.0 for t in trades if t.get("entry_time") is not None and t.get("exit_time") is not None]
    if not h:
        return {"n": 0, "median": None, **{f"share_gt{x}": None for x in HOLD_HOURS}}
    return {"n": len(h), "median": round(statistics.median(h), 3), **{f"share_gt{x}": round(sum(v > x for v in h) / len(h), 4) for x in HOLD_HOURS}}


def day_counts(conn) -> dict:
    """{account: {offered, entered, skipped, rejected, closed}} summed over the days of ``acct_day`` (PREREG 11.4 item 10)."""
    try:
        rows = conn.execute("SELECT account, SUM(offered), SUM(entered), SUM(skipped), SUM(rejected), SUM(closed) FROM acct_day GROUP BY account")
        return {r[0]: dict(zip(("offered", "entered", "skipped", "rejected", "closed"), (int(x or 0) for x in r[1:]))) for r in rows}
    except sqlite3.Error:
        return {}


def account_rows(conn, accts: list[dict], engines: dict, ds_money: bool = False, book: Optional[dict] = None) -> list[dict]:
    """Per account: trades, wins, mean P&L per trade as a fraction of the wallet before it, closed-trade drawdown,
    wallet, the open position; DeepSeek money hidden unless ``ds_money`` (D11)."""
    book = closed_trades(conn, accts) if book is None else book
    counts = day_counts(conn) if any(a.get("rule") for a in accts) else {}
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
        if a.get("rule"):
            row.update(rule=a["rule"].get("id"), rule_ko=RX.rule_ko(a["rule"]), pick=a.get("pick"), hold=hold_stats(book[a["id"]]),
                       counts=counts.get(a["id"]) or dict(offered=0, entered=0, skipped=0, rejected=0, closed=0),
                       no_entry_from_ms=a.get("no_entry_from_ms"))
        if a.get("ox"):                       # the owner-exit league: which of the pick's accounts this is, in the owners' words
            row.update(role_ko=a["ox"]["label_ko"], role_short=a["ox"]["short_ko"], weekend_off=bool(a.get("weekend_off")))
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
        if r.get("role_ko") and base is None and flip is None:   # the owner-exit league (no 기본값, no 동전): no CONTRACT 2 verdict
            out[r["id"]] = {"verdict": "na", "trades": r["trades"], **extra}
            continue
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


def catching(league: "League", now_ms: int) -> bool:
    """The snapshot's ``catching`` (dash.py catching_up, lk.js catchingUp): processed time more than CATCHING_MS behind
    ``now_ms`` AND progress just made (a start-over or a committed chunk within PROGRESS_MS). A snapshot written
    without progress says False, so a stuck engine shows by its lag ('처리가 늦음'), never as 'catching up'."""
    adv = league.advanced_ms
    return bool(adv is not None and now_ms - adv <= PROGRESS_MS and now_ms - league.done > CATCHING_MS)


def write_snapshots(snap: str, league: "League", now_ms: int, ds_money: bool = False,
                    pass_s: Optional[float] = None) -> dict:
    book = closed_trades(league.conn, league.accts)
    rows = account_rows(league.conn, league.accts, league.engines, ds_money, book)
    # the verdicts from the full rows (labels and counts only: a hidden DeepSeek pick still gets its pass / fail label)
    verdicts = judge(rows if ds_money else account_rows(league.conn, league.accts, league.engines, True, book))
    doc = {"equity0": EQUITY, "generated_ms": now_ms, "done_ms": league.done, "lag_s": max(0, (now_ms - league.done) // 1000),
           "catching": catching(league, now_ms), "start_ms": league.start_ms, "started_ms": league.meta.get("started_ms"), "accounts": rows,
           "judge": verdicts, "notes": league.meta.get("notes", []), "ds_money": ds_money,
           "watch": SM.watch_summary(league.accts, book, now_ms, ds_money), "server": server_info(pass_s)}
    lu = RX.lineup(league.accts)
    if lu:                                    # the owner-exit league: its account kinds, in order, for the dashboard and Telegram
        doc["lineup"] = lu
        # ... and their scoreboard, the main accounts against the control, the rules' events (summary.owner_views; DeepSeek money by ds_money)
        doc.update(SM.owner_views(lu, league.accts, book, rows, league.start_ms, league.done, ds_money, SM.narrowed_keys(league.conn),
                                  EQUITY))
    os.makedirs(snap, exist_ok=True)
    _write(snap, "trades.json", trade_book(league.conn, league.accts, ds_money, league.start_ms, book))
    _write(snap, "league.json", doc)
    return doc


def parse_start(text: Optional[str]) -> Optional[int]:
    """CANDLEAGUE_START / --start: a time WITH its time zone ("2026-10-11T12:00+09:00", "2026-10-11T03:00Z") or epoch
    ms; None when empty. A time without a zone is refused (12:00 read as UTC would start 9 hours late), and so is
    anything else that is not a time: ValueError with the reason in Korean. Only a league with no recorded start uses
    it (league_start)."""
    import datetime
    t = (text or "").strip()
    if not t:
        return None
    if t.isdigit():
        return int(t)
    iso = t.replace(" ", "T")
    if iso[-1:] in ("Z", "z"):
        iso = iso[:-1] + "+00:00"
    try:
        d = datetime.datetime.fromisoformat(iso)
    except ValueError:
        raise ValueError(f"CANDLEAGUE_START {t!r}: 시각으로 읽을 수 없습니다 (예: 2026-10-11T12:00+09:00)") from None
    if d.tzinfo is None:
        raise ValueError(f"CANDLEAGUE_START {t!r}: 시간대를 붙여 주세요 (한국 시각이면 2026-10-11T12:00+09:00)")
    return int(d.timestamp() * 1000)


def recorded_start(conn, db_path: Optional[str]) -> bool:
    """The league already records its start (in the database or in its start file): CANDLEAGUE_START is not used."""
    try:
        meta = _get(conn, "meta") or {}
    except sqlite3.Error:
        meta = {}
    return meta.get("start_ms") is not None or read_start_file(db_path) is not None


def explicit_start(text: Optional[str], conn, db_path: Optional[str], log: Callable[[str], None] = print) -> Optional[int]:
    """The CANDLEAGUE_START a league would use: None when it is empty or a start is already recorded (then it is not
    even read, so a stray value never stops the engine); else parse_start (a bad value raises: a wrong start would be
    recorded for good)."""
    if not (text or "").strip():
        return None
    if recorded_start(conn, db_path):
        log("[후보 리그] CANDLEAGUE_START는 쓰지 않습니다 (시작 시각이 이미 기록되어 있음)")
        return None
    return parse_start(text)


def plan_start(db: str, accts: list[dict], explicit: Optional[int] = None,
               now_ms: Optional[int] = None) -> Optional[tuple[bool, int, int]]:
    """(starts over, start_ms, started_ms) the code would use on its next construction over the database ``db``;
    None when there is no database."""
    if not os.path.exists(db):
        return None
    conn = sqlite3.connect(db, timeout=30)
    try:
        try:
            meta = _get(conn, "meta") or {}
        except sqlite3.Error:
            meta = {}
    finally:
        conn.close()
    now = int(time.time() * 1000) if now_ms is None else now_ms
    reset = meta.get("fingerprint") != fingerprint(accts) or meta.get("start_ms") is None
    if not reset:
        return False, int(meta["start_ms"]), int(meta.get("started_ms") or meta["start_ms"])
    start, started = league_start(meta, now, read_start_file(db), explicit)
    return True, start, started


def _kst(ms: int) -> str:
    return _utc(ms + 9 * 3_600_000, "%m/%d %H:%M")


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


def league_accounts(rules_path: Optional[str], cands: list[dict]) -> list[dict]:
    """The accounts the league runs: the restarted league's (candleague/rulex.py, PREREG_EXITFLEX 11.2, both pools) when a rule config
    file exists and is enabled ("enabled": true is the owners' OK), else the candidate accounts as before. A file that exists, is
    enabled and cannot be run raises RX.RuleConfigError (the league never starts on the old accounts in its place). A file of the
    owner-exit form gives the owners' exit accounts (RX.owner_accounts) the same way."""
    accts = RX.load_accounts(rules_path or None, cands)
    return C.accounts(cands) if accts is None else accts


def main(argv: Optional[list] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("run", "once", "status", "backup"))
    ap.add_argument("--db", default=os.environ.get("CANDLEAGUE_DB", "/var/lib/candleague/league.db"))
    ap.add_argument("--snap", default=os.environ.get("CANDLEAGUE_SNAP", "/var/lib/candleague/snap"))
    ap.add_argument("--candidates", default=os.environ.get("CANDLEAGUE_CANDIDATES", C.DEFAULT_FILE))
    ap.add_argument("--start", default=os.environ.get("CANDLEAGUE_START", ""),
                    help="start of a league with no recorded start only (rebuild a lost league.db and its start file), "
                         "with its time zone, e.g. 2026-10-11T12:00+09:00")
    ap.add_argument("--expect-start", default=os.environ.get("CANDLEAGUE_EXPECT_START", ""),
                    help="the install time the restart script wrote down (with its time zone, or epoch ms): the league refuses to run "
                         "when its start is not this time floored to 5 minutes (PREREG_EXITFLEX 11.3)")
    ap.add_argument("--every", type=int, default=300, help="seconds between passes (run)")
    ap.add_argument("--rules", default=os.environ.get(RX.RULES_ENV, ""),
                    help=f"rule config (default {RX.DEFAULT_FILE}): when it exists and is enabled, the league IS the restarted league "
                         "of PREREG_EXITFLEX 11 (its accounts are candleague/rulex.py's, in the database given by --db)")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        with open(os.path.join(a.snap, "league.json")) as fh:
            d = json.load(fh)
        st = d.get("start_ms")
        print(f"start {time.strftime('%Y-%m-%d %H:%M', time.gmtime(st / 1000)) if st else '-'} UTC, "
              f"done {time.strftime('%Y-%m-%d %H:%M', time.gmtime(d['done_ms'] / 1000))} UTC, "
              f"lag {d['lag_s']}s, accounts {len(d['accounts'])}")
        return 0
    try:
        expect = parse_start(a.expect_start)
    except ValueError as exc:
        raise SystemExit(f"[후보 리그] {exc}") from None
    cands = C.load(a.candidates)
    try:
        accts = league_accounts(a.rules, cands)
    except RX.RuleConfigError as exc:
        if a.cmd == "backup":
            print(f"[후보 리그] 규칙 계좌 설정을 읽지 못했습니다: {exc}", flush=True)
            return 1
        raise SystemExit(f"[후보 리그] 규칙 계좌 설정을 쓸 수 없어 멈춥니다 (옛 계좌로 대신 돌리지 않습니다): {exc}") from None
    if a.cmd == "backup":
        explicit = None
        if os.path.exists(a.db):
            c = sqlite3.connect(a.db, timeout=30)
            try:
                explicit = explicit_start(a.start, c, a.db, log=lambda s: print(s, flush=True))
            except ValueError as exc:
                print(f"[후보 리그] {exc}", flush=True)
                return 1
            finally:
                c.close()
        had = set(glob.glob(os.path.join(os.path.dirname(os.path.abspath(a.db)), "*.db")))
        path = backup_if_reset(a.db, accts)
        print("[후보 리그] 기록 복사 필요 없음 (이어서 계산)" if not path else
              f"[후보 리그] 새로 시작하기 전 기록을 이미 복사해 두었습니다: {path}" if path in had else
              f"[후보 리그] 새로 시작하기 전 기록 복사: {path}", flush=True)
        plan = plan_start(a.db, accts, explicit)
        if plan:
            reset, st, started = plan
            print(f"[후보 리그] {'새 시작' if reset else '시작 그대로'}: {_kst(st)} KST"
                  f" (설치한 때 {_kst(started)} KST)" + (" · 모든 계좌 $5,000으로 이 시각부터 다시 계산" if reset else ""),
                  flush=True)
            try:
                check_expected_start(st, expect)
            except StartMismatch as exc:
                print(f"[후보 리그] {exc}", flush=True)
                return 1
        return 0
    from paperbot import sweepsig
    from paperbot.binance import BinanceREST
    from paperbot.config import V3_SYMBOLS
    from paperbot.paramshadow import RestSource, make_fetcher
    rest = BinanceREST()
    brackets, specs, src = load_exchange(os.environ.get("CANDLEAGUE_EXCHANGE", EXCHANGE_FILE), V3_SYMBOLS)
    conn = open_db(a.db)
    source = RestSource(os.path.join(os.path.dirname(a.db), "bars5m.db"), rest=rest)

    def fetch(_rest, syms, s, e):
        return make_fetcher(rest, syms, s, e)(rest, syms, s, e)
    # owners 2026-10-11: DeepSeek money shown like core; 0 / off / false / no hides it again
    ds_money = os.environ.get("CANDLEAGUE_DS_MONEY", "1").strip().lower() not in ("0", "off", "false", "no")
    try:
        explicit = explicit_start(a.start, conn, a.db, log=lambda s: print(s, flush=True))
    except ValueError as exc:            # only for a league with no recorded start: refuse rather than record a wrong one
        raise SystemExit(f"[후보 리그] {exc}") from None
    try:
        lg = League(conn, accts, brackets, specs, sweepsig.lib(), source, fetch, V3_SYMBOLS, start_ms=explicit, db_path=a.db,
                    expect_start_ms=expect, log=lambda s: print(s, flush=True))
    except StartMismatch as exc:         # before any trade is shown (11.3)
        raise SystemExit(f"[후보 리그] {exc}") from None
    from .notify import Notifier
    notifier = Notifier(conn)
    print(f"[후보 리그] {len(accts)} accounts, brackets: {src}, start {_utc(lg.start_ms, '%Y-%m-%d %H:%M')} UTC, "
          f"done {_utc(lg.done, '%Y-%m-%d %H:%M')} UTC", flush=True)
    if lg.reset:          # a start-over replaces the old screens at once; a plain restart writes only after progress
        write_snapshots(a.snap, lg, int(time.time() * 1000), ds_money)
    while True:
        now = int(time.time() * 1000)
        t0 = time.monotonic()
        catching_up = final_end(now) - lg.done > 3 * FIVE    # a catch-up writes after each day; a live pass once, below
        n = lg.advance(final_end(now), on_chunk=(lambda: write_snapshots(a.snap, lg, int(time.time() * 1000), ds_money))
                       if catching_up else None)
        now = int(time.time() * 1000)                        # after the pass: the snapshot's time, the caught-up test
        doc = write_snapshots(a.snap, lg, now, ds_money, pass_s=time.monotonic() - t0)
        notifier.after_pass(doc, now, caught_up=final_end(now) - lg.done < 3 * FIVE)
        if n:
            print(f"[후보 리그] {n} chunk(s), done {time.strftime('%m-%d %H:%M', time.gmtime(lg.done / 1000))} UTC",
                  flush=True)
        if a.cmd == "once":
            return 0
        time.sleep(a.every)
