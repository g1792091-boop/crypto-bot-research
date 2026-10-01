"""Executor: mirrors ONE paper v3 account into real orders on Binance USD-M futures.

Testnet (fake money) by default. Mainnet (real money) only when every gate in paperbot/mainnet.py holds.

    python -m paperbot.executor run --config /etc/paperbot/executor.json      # keys from the environment
    python -m paperbot.executor preflight --config /etc/paperbot/executor.json  # gates only, no orders
    python -m paperbot.executor status --db /var/lib/paperbot/executor.db
    python -m paperbot.executor clear-halt --config /etc/paperbot/executor.json --by 이름 --note "이유"
    python -m paperbot.executor check-config --config /etc/paperbot/executor.json
    python -m paperbot.executor stage-check --config /etc/paperbot/executor.json

What it does (docs/live-safety.md explains it for the owners):
- reads the chosen paper account's open position from paper3.db (read-only);
- paper entry      -> market entry + a protective stop resting on the exchange (algo order,
                      last price), confirmed live;
  with ``entry_source: "signal"`` the entry is taken as soon as the paper runner SUBMITS the account's
  signal (paper3.db signal_log + the account's pending signal, polled every 1-2 s) instead of 1-2
  minutes later when the paper position appears; the paper position must then appear with the same
  key, or the live position is closed;
- paper lock step  -> moves the stop: new stop -> confirmed -> old stop cancelled
                      (-2021 "would immediately trigger" -> reduce-only market close);
- paper exit       -> reduce-only market close, every order cancelled, flat checked.

Every loop, before following the paper account, it reconciles the exchange with its own state:
an unknown position is closed and alerted; a position without a stop gets one at once (or is
closed); a stop smaller than the position is replaced; extra stops are cancelled; a position that
closed on the exchange (stop hit) is booked. Then the risk rules (paperbot/risk.py) run: kill
file, persisted halt, daily loss, drawdown, loss streak -> close everything and halt.

P&L of each trade comes from the exchange's fills (GET /fapi/v1/userTrades: realizedPnl, commission)
and funding (GET /fapi/v1/income), with the cost ratio of addendum Q6 #4 (paperbot/livepnl.py).
``stage-check`` runs risk.leverage_stage_review on that record.

Errors: network failures, timeouts and 5xx are retried with backoff, and an order whose outcome
is unknown is first looked up by its client id. An OPENING order whose outcome stays unknown is never
sent again (a late first fill plus a resend would double the position): the trade stays "entering" and
the reconcile adopts (and protects) whatever filled. A 4xx refusal is never retried blindly (a -1021
clock refusal re-syncs the server time and is sent once more). 429/418 wait for Retry-After; the
rate-limit headers slow the loop down, except for protective work (the stop after a fill, stop moves,
reduce-only closes). The server time is re-synced periodically.

Each loop checks the kill file and a persisted halt FIRST, with nothing but positionRisk and reduce-only
market orders, so a failing read or a stuck reconcile action never keeps them from closing everything.

Everything (decisions, every order request and answer, trades, fills, halts) goes to the executor's
own SQLite database, one database per mode (the mode is recorded and checked). One writer: a lock
file next to the database stops a second process.

AI agents never import or run this module (tests/test_executor.py checks it).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import hashlib
import json
import math
import os
import signal
import sqlite3
import sys
import time
import urllib.parse
from dataclasses import dataclass, fields
from typing import Callable, Mapping, Optional

from . import livepnl as P
from . import risk as R
from .config import V3_STOP_ATR, V3_SYMBOLS, v3_settings
from .mainnet import (MAINNET_HOSTS, MODE_MAINNET, MODE_TESTNET, PAPER_ENV_FILE, KeyCheckClient, MainnetClient,
                      Refused, online_gates, read_env_file, trading_keys)
from .margin import Brackets
from .notify import CRITICAL, INFO, WARN, ConsoleNotifier, NullNotifier, Notifier
from .sizing import size_position
from .testnet import (ALLOWED_HOSTS, BAD_TIMESTAMP, FIRED_ALGO, NOT_FOUND, ProtectionError, RateLimited,
                      TestnetClient, TestnetError, TransientError, UnknownOutcome, _round_down, cancel_stops, covers,
                      hide_process_memory, live_stops, move_stop, round_stop)

SUPPORTED_MODES = (MODE_TESTNET, MODE_MAINNET)
TESTNET_HOSTS = ("testnet.binancefuture.com",)
PREFIX = {MODE_TESTNET: "[테스트넷 실행기]", MODE_MAINNET: "[실거래 실행기]"}
ENTRY_SOURCES = ("paper", "signal")
# reconcile emergencies: counted with the unplanned halts by stage-check
EMERGENCY_KINDS = ("unknown_position", "wrong_side", "protect_failed", "not_flat", "no_stop", "oversize")
# income types that move money in or out of the futures wallet (not trading P&L)
TRANSFER_TYPES = ("TRANSFER", "INTERNAL_TRANSFER", "CROSS_COLLATERAL_TRANSFER", "STRATEGY_UMFUTURES_TRANSFER",
                  "COIN_SWAP_DEPOSIT", "COIN_SWAP_WITHDRAW")
# income types that belong to a trade's P&L besides its fills
TRADE_INCOME_TYPES = ("FUNDING_FEE", "SPECIAL_FUNDING_FEE", "INSURANCE_CLEAR")
FINAL_ORDER = ("FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH")
USER_TRADES_SPAN = 7 * 86_400_000 - 1     # GET /fapi/v1/userTrades: at most 7 days per request


# ---------------------------------------------------------------- config
@dataclass(frozen=True)
class ExecConfig:
    account: str                          # paper account to mirror, e.g. "V45_AMB@15m"
    paper_db: str                         # paper3.db, opened read-only
    db: str                               # the executor's own database (one per mode)
    qty_scale: float                      # live quantity = paper quantity x qty_scale
    risk: R.RiskConfig
    mode: str = MODE_TESTNET              # "testnet" | "mainnet" (mainnet: every gate in paperbot/mainnet.py)
    budget_usd: Optional[float] = None    # money in the executor's account; mainnet refuses a wallet > 1.2x
    poll_s: float = 3.0
    max_entry_age_s: float = 180.0       # paper entries older than this are not followed
    paper_stale_s: float = 300.0         # paper state older than this -> no new entries
    retries: int = 4
    sweep_every: int = 20                # loops between full sweeps of every allowed symbol
    stop_from: str = "ratio"             # "ratio": same stop distance (%) from the actual fill as the paper
                                         # stop from the paper fill; "price": the paper's stop price itself
    entry_source: str = "paper"          # "paper": follow the paper position; "signal": enter when submitted
    direct_poll_s: float = 1.5           # signal mode: paper3.db polling between loops
    direct_max_age_s: float = 20.0       # signal mode: a signal seen later than this after it was ready -> paper path
    direct_confirm_s: float = 240.0      # signal mode: the paper position must appear within this, or close
    stop_atr: float = V3_STOP_ATR        # signal mode: stop distance when the pending signal has none
    paper_taker_fee: Optional[float] = None   # the paper rules' taker fee (None: measured from paper3.db trades)
    paper_env_file: str = PAPER_ENV_FILE      # the paper runner's env file: its read-only key is refused here
    time_sync_s: float = 600.0           # server time re-sync interval
    equity_every_s: float = 300.0        # equity samples (stage-check drawdown)
    entry_unknown_s: float = 60.0        # an entry whose outcome is unknown: wait this long for it to show up
    transfer_every_s: float = 60.0       # deposits/withdrawals read this often (and before a money halt)

    @classmethod
    def from_dict(cls, d: dict) -> "ExecConfig":
        d = dict(d)
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(d) - known)
        if unknown:
            raise Refused(f"알 수 없는 설정 항목: {', '.join(unknown)}")
        d["risk"] = R.RiskConfig.from_dict(d.get("risk") or {})
        return cls(**d)

    @classmethod
    def from_file(cls, path: str) -> "ExecConfig":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def problems(self) -> list[str]:
        out = []
        if self.mode not in SUPPORTED_MODES:
            out.append(f"mode={self.mode!r}: \"testnet\" 또는 \"mainnet\"만 있습니다")
        if not self.account or "@" not in self.account:
            out.append("따라 할 paper 계좌(account, 예: V45_AMB@15m)가 비어 있거나 형식이 다릅니다")
        if not (isinstance(self.qty_scale, (int, float)) and self.qty_scale > 0):
            out.append("qty_scale은 0보다 커야 합니다")
        if self.stop_from not in ("ratio", "price"):
            out.append("stop_from은 \"ratio\" 또는 \"price\"입니다")
        if self.entry_source not in ENTRY_SOURCES:
            out.append("entry_source는 \"paper\" 또는 \"signal\"입니다")
        if not 0.5 <= float(self.direct_poll_s) <= 5:
            out.append("direct_poll_s는 0.5~5초입니다")
        if self.budget_usd is not None and not (isinstance(self.budget_usd, (int, float)) and self.budget_usd > 0):
            out.append("budget_usd는 0보다 커야 합니다")
        if self.mode == MODE_MAINNET and self.budget_usd is None:
            out.append("실거래(mainnet)는 정한 금액 budget_usd(예: 500)가 필요합니다")
        if self.risk.kill_file and self.db and not _kill_file_visible(self.risk.kill_file, self.db):
            out.append(f"비상 정지 파일 {self.risk.kill_file}은 실행기 DB가 있는 폴더나 그 위 폴더에 둡니다"
                       "(예: /var/lib/paperbot/STOP). /tmp·/home 같은 곳은 서비스 안에서 보이지 않아 "
                       "파일을 만들어도 멈추지 않습니다")
        return out + self.risk.problems()


def _kill_file_visible(kill_file: str, db: str) -> bool:
    """The service sees the folder of its own database (ReadWritePaths) and every folder above it in the same
    view as a person's shell; /tmp (PrivateTmp) and /home (ProtectHome) it does not."""
    kdir = os.path.dirname(os.path.abspath(kill_file))
    ddir = os.path.dirname(os.path.abspath(db))
    return ddir == kdir or ddir.startswith(kdir.rstrip(os.sep) + os.sep)


def refuse_unless_allowed(cfg: ExecConfig, client) -> None:
    """The client must point at the host of the configured mode, and be the client class of that mode."""
    if cfg.mode not in SUPPORTED_MODES:
        raise Refused(f"mode={cfg.mode!r}: testnet/mainnet 외의 모드는 시작하지 않습니다")
    host = urllib.parse.urlparse(getattr(client, "base", "") or "").hostname or ""
    if cfg.mode == MODE_TESTNET:
        if host not in TESTNET_HOSTS or tuple(ALLOWED_HOSTS) != TESTNET_HOSTS or isinstance(client, MainnetClient) \
                or tuple(getattr(type(client), "HOSTS", ())) != TESTNET_HOSTS:
            raise Refused(f"주소 {host!r}: testnet 모드는 testnet.binancefuture.com 외에는 연결하지 않습니다")
    else:
        if host not in MAINNET_HOSTS or not isinstance(client, MainnetClient) \
                or tuple(type(client).HOSTS) != MAINNET_HOSTS:
            raise Refused(f"주소 {host!r}: mainnet 모드는 fapi.binance.com 외에는 연결하지 않습니다")


refuse_unless_testnet = refuse_unless_allowed      # the name used before mainnet existed


# ---------------------------------------------------------------- paper side
@dataclass(frozen=True)
class Intent:
    """The paper account's open position (or, in signal mode, the entry it is about to make)."""
    key: str
    symbol: str
    side: int
    qty: float
    leverage: int
    stop: float
    entry_price: float
    entry_time: int
    direct: bool = False                  # taken from the submitted signal, before the paper position exists
    signal_ref: Optional[float] = None    # the paper's reference price (ask for a long, bid for a short)
    signal_ready: Optional[int] = None    # when the signal was ready (ms)


def _ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


class Paper3Source:
    """Reads one account's position from paper3.db (read-only; the paper runner is its writer).
    ``engine`` keeps the account's last state (wallet, pending signals, halted) for signal mode."""

    def __init__(self, path: str, account: str):
        self.path, self.account = path, account
        self.engine: Optional[dict] = None

    def read(self) -> tuple[Optional[Intent], Optional[int]]:
        conn = _ro(self.path)
        try:
            row = conn.execute("SELECT ts, data FROM state WHERE k = 'accounts'").fetchone()
        finally:
            conn.close()
        if row is None:
            self.engine = None
            return None, None
        ts, data = int(row[0]), json.loads(row[1])
        eng = data.get("engines", {}).get(self.account)
        if eng is None:
            raise Refused(f"paper 계좌 {self.account}가 paper3.db에 없습니다")
        self.engine = eng
        p = eng.get("position")
        if not p:
            return None, ts
        return Intent(key=f"{self.account}|{p['symbol']}|{int(p['entry_time'])}", symbol=p["symbol"],
                      side=int(p["side"]), qty=float(p["qty"]), leverage=int(p["leverage"]),
                      stop=float(p["stop_price"]), entry_price=float(p["entry_price"]),
                      entry_time=int(p["entry_time"])), ts


class SignalSource:
    """Signal mode: new SUBMITTED signal_log rows of the account's strategy and timeframe (read-only, cheap:
    a primary-key range). Rows older than the first poll are never acted on (the paper path covers them)."""

    def __init__(self, path: str, account: str):
        self.path = path
        self.strategy, self.timeframe = account.rsplit("@", 1)
        self.last_id: Optional[int] = None

    def new_rows(self) -> list[dict]:
        conn = _ro(self.path)
        try:
            top = conn.execute("SELECT COALESCE(MAX(id), 0) FROM signal_log").fetchone()[0]
            if self.last_id is None:
                self.last_id = int(top)
                return []
            cur = conn.execute("SELECT id, bar_close, symbol, side, atr, ref_price, ref_time FROM signal_log "
                               "WHERE id > ? AND id <= ? AND strategy = ? AND timeframe = ? AND status = 'SUBMITTED' "
                               "ORDER BY id", (self.last_id, top, self.strategy, self.timeframe))
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()
        self.last_id = int(top)
        return rows


# ---------------------------------------------------------------- store (one writer)
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    level TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    status INTEGER,
    code INTEGER,
    error TEXT,
    params TEXT NOT NULL,
    data TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    key TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side INTEGER NOT NULL,
    qty REAL NOT NULL,
    leverage INTEGER NOT NULL,
    entry_ts INTEGER NOT NULL,
    entry_price REAL,
    stop_initial REAL,
    exit_ts INTEGER,
    exit_reason TEXT,
    pnl REAL,
    data TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS halts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    who TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS state (
    k TEXT PRIMARY KEY,
    ts INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
    symbol TEXT NOT NULL,
    id INTEGER NOT NULL,
    trade_key TEXT NOT NULL,
    ts INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (symbol, id)
);
CREATE TABLE IF NOT EXISTS funding (
    symbol TEXT NOT NULL,
    tran_id INTEGER NOT NULL,
    trade_key TEXT NOT NULL,
    ts INTEGER NOT NULL,
    income REAL NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (symbol, tran_id)
);
CREATE TABLE IF NOT EXISTS equity (
    ts INTEGER PRIMARY KEY,
    equity REAL NOT NULL,
    wallet REAL NOT NULL
);
"""
# columns added after the first testnet release (existing databases are migrated in place)
MIGRATIONS = (
    ("trades", "mode", "TEXT"), ("trades", "pnl_source", "TEXT"), ("trades", "realized", "REAL"),
    ("trades", "commission", "REAL"), ("trades", "funding", "REAL"), ("trades", "slippage", "REAL"),
    ("trades", "real_cost", "REAL"), ("trades", "assumed_cost", "REAL"), ("trades", "cost_ok", "INTEGER"),
    ("halts", "planned", "INTEGER"), ("equity", "transfers", "REAL"),
)


class ExecStore:
    def __init__(self, path: str, lock: bool = True):
        self.lock_fh = None
        if lock:
            import fcntl
            self.lock_fh = open(path + ".lock", "a+")
            try:
                fcntl.flock(self.lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.lock_fh.close()
                raise Refused(f"다른 실행기가 이미 {path}를 쓰고 있습니다(한 번에 하나만)")
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        for table, col, typ in MIGRATIONS:
            have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if col not in have:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.conn.commit()

    def event(self, ts: int, level: str, kind: str, text: str, data: Optional[dict] = None) -> None:
        self.conn.execute("INSERT INTO events (ts, level, kind, text, data) VALUES (?,?,?,?,?)",
                          (ts, level, kind, text, json.dumps(data or {}, default=str, ensure_ascii=False)))

    def request(self, ts: int, a: dict) -> None:
        self.conn.execute("INSERT INTO requests (ts, method, path, status, code, error, params, data) "
                          "VALUES (?,?,?,?,?,?,?,?)",
                          (ts, a["method"], a["path"], a.get("status"), a.get("code"), a.get("error"),
                           json.dumps(a.get("params", {}), default=str),
                           json.dumps(a.get("data"), default=str)[:4000]))

    def trade_open(self, t: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO trades (key, symbol, side, qty, leverage, entry_ts, entry_price, "
                          "stop_initial, data, mode) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (t["key"], t["symbol"], t["side"], t["qty"], t["leverage"], t["entry_ts"],
                           t.get("entry_price"), t.get("stop_initial"), json.dumps(t, default=str), t.get("mode")))

    def trade_close(self, key: str, ts: int, reason: str, pnl: Optional[float], data: dict,
                    source: str = "wallet") -> None:
        self.conn.execute("UPDATE trades SET exit_ts = ?, exit_reason = ?, pnl = ?, data = ?, pnl_source = ? "
                          "WHERE key = ?",
                          (ts, reason, pnl, json.dumps(data, default=str, ensure_ascii=False), source, key))

    def trade_costs(self, key: str, c: dict) -> None:
        """P&L and cost measured from the exchange's fills and funding (replaces the wallet estimate)."""
        self.conn.execute("UPDATE trades SET pnl = ?, pnl_source = 'fills', realized = ?, commission = ?, funding = ?, "
                          "slippage = ?, real_cost = ?, assumed_cost = ?, cost_ok = ? WHERE key = ?",
                          (c["pnl"], c["realized"], c["commission"], c["funding"], c["slippage"], c["real_cost"],
                           c["assumed_cost"], 1 if c["ok"] else 0, key))

    def fills(self, key: str, rows: list) -> None:
        self.conn.executemany("INSERT OR IGNORE INTO fills (symbol, id, trade_key, ts, data) VALUES (?,?,?,?,?)",
                              [(r.get("symbol"), int(r["id"]), key, int(r.get("time") or 0), json.dumps(r))
                               for r in rows])

    def funding(self, key: str, rows: list) -> None:
        self.conn.executemany("INSERT OR IGNORE INTO funding (symbol, tran_id, trade_key, ts, income, data) "
                              "VALUES (?,?,?,?,?,?)",
                              [(r.get("symbol"), int(r["tranId"]), key, int(r.get("time") or 0),
                                float(r.get("income") or 0), json.dumps(r)) for r in rows])

    def equity(self, ts: int, equity: float, wallet: float, transfers: float = 0.0) -> None:
        """``transfers``: net deposits/withdrawals so far (stage-check measures the drawdown without them)."""
        self.conn.execute("INSERT OR REPLACE INTO equity (ts, equity, wallet, transfers) VALUES (?,?,?,?)",
                          (ts, equity, wallet, transfers))

    def halt_log(self, ts: int, action: str, reason: str, who: Optional[str] = None,
                 note: Optional[str] = None, planned: Optional[bool] = None) -> None:
        self.conn.execute("INSERT INTO halts (ts, action, reason, who, note, planned) VALUES (?,?,?,?,?,?)",
                          (ts, action, reason, who, note, None if planned is None else int(planned)))

    def put_state(self, key: str, ts: int, data: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO state VALUES (?,?,?)", (key, ts, json.dumps(data, default=str)))

    def get_state(self, key: str) -> Optional[dict]:
        r = self.conn.execute("SELECT data FROM state WHERE k = ?", (key,)).fetchone()
        return None if r is None else json.loads(r[0])

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()
        if self.lock_fh is not None:
            self.lock_fh.close()
            self.lock_fh = None


# ---------------------------------------------------------------- retries
class Guarded:
    """The exchange client (testnet or mainnet: the same code) with an error policy.

    - reads: network/5xx/429 -> retry with backoff (Retry-After honoured); 4xx -> raise;
    - idempotent writes (leverage, margin type, cancel-all): same as reads;
    - orders (market, stop): sent with a client id; after an unknown outcome the order is looked up
      by that id, and only sent again when the exchange does not have it -- except an OPENING order
      (``resend=False``): it is never sent twice (UnknownOutcome; the reconcile settles it);
    - 418 (IP banned) is never retried here: the loop waits;
    - before every request: wait if the rate-limit headers say we are near a limit, except inside
      ``protecting()`` (the stop after a fill, stop moves, closes: a position must not wait for a minute
      boundary without its stop; 429/418 are still handled)."""

    def __init__(self, client: TestnetClient, sleep: Callable[[float], None], retries: int = 4,
                 base_delay: float = 0.5, max_delay: float = 8.0,
                 on_retry: Optional[Callable[[str, Exception], None]] = None):
        self.c, self.sleep, self.retries = client, sleep, max(1, retries)
        self.base_delay, self.max_delay, self.on_retry = base_delay, max_delay, on_retry
        self.urgent = 0

    def __getattr__(self, name):          # host, base, limits ... (not the endpoints: those are below)
        return getattr(self.c, name)

    @contextlib.contextmanager
    def protecting(self):
        """Protective work: no pacing pauses inside."""
        self.urgent += 1
        try:
            yield
        finally:
            self.urgent -= 1

    def _pace(self) -> None:
        if self.urgent:
            return
        w = self.c.throttle_s()
        if w > 0:
            self.sleep(w)

    def _backoff(self, attempt: int, err: Exception, what: str) -> None:
        if isinstance(err, RateLimited):
            if err.status == 418:
                raise err
            delay = max(err.retry_after, 1.0)
        else:
            delay = min(self.max_delay, self.base_delay * (2 ** attempt))
        if self.on_retry:
            self.on_retry(what, err)
        self.sleep(delay)

    def _resync(self, what: str, err: Exception) -> None:
        """-1021: our clock drifted outside recvWindow. The request was refused (not executed): re-sync and
        send it once more."""
        if self.on_retry:
            self.on_retry(f"{what} (서버 시간 다시 맞춤)", err)
        self.c.sync_time()

    def _retry(self, what: str, fn, *a, **k):
        attempt, resynced = 0, False
        while True:
            self._pace()
            try:
                return fn(*a, **k)
            except (TransientError, RateLimited) as e:
                if attempt >= self.retries - 1:
                    raise
                self._backoff(attempt, e, what)
                attempt += 1
            except TestnetError as e:
                if e.code != BAD_TIMESTAMP or resynced:
                    raise
                resynced = True
                self._resync(what, e)

    def _write(self, what: str, send, lookup, resend: bool = True):
        """Send an order that has a client id; on an unknown outcome, look it up before resending.

        ``resend=False`` (an opening order): once an attempt's outcome is unknown (network failure, timeout,
        5xx) the order is only looked up, never sent again; still not found -> UnknownOutcome. A 429 is a
        refusal (nothing executed) and is sent again after Retry-After either way."""
        last: Optional[Exception] = None
        attempt, resynced, unknown = 0, False, False
        while attempt < self.retries:
            self._pace()
            try:
                return send()
            except (TransientError, RateLimited) as e:
                last = e
                if isinstance(e, RateLimited) and e.status == 418:
                    if unknown:
                        raise UnknownOutcome(e.status, e.code, f"{what}: 결과를 모르는 채 IP 차단(418): {e.msg}") from e
                    raise
                unknown = unknown or not isinstance(e, RateLimited)
                self._backoff(attempt, e, what)
                attempt += 1
                found = self._find(what, lookup, unknown)
                if found is not None:
                    return found
                if unknown and not resend:
                    return self._await(what, lookup, attempt, e)
            except TestnetError as e:
                if e.code == BAD_TIMESTAMP and not resynced:
                    resynced = True
                    self._resync(what, e)
                    continue
                if unknown:
                    # e.g. -4116/-20132 "duplicated", -2022 reduce-only rejected: the first send may have worked
                    try:
                        found = lookup()
                    except TestnetError:
                        found = None
                    if found is not None:
                        return found
                raise
        assert last is not None
        if unknown and not isinstance(last, UnknownOutcome):
            raise UnknownOutcome(last.status, last.code, f"{what}: 결과를 모릅니다({last.msg})") from last
        raise last

    def _find(self, what: str, lookup, unknown: bool):
        """The look-up after a failed send. A look-up that itself fails (429, 418, network) leaves the outcome
        unknown: UnknownOutcome, never a refusal."""
        try:
            return lookup()
        except TestnetError as e:
            if not unknown:
                raise
            raise UnknownOutcome(e.status, e.code, f"{what}: 결과를 모르고 조회도 실패했습니다({e})") from e

    def _await(self, what: str, lookup, attempt: int, err: Exception):
        """An opening order whose outcome is unknown: look it up a few more times, never send it again."""
        while attempt < self.retries:
            self._backoff(attempt, err, what)
            attempt += 1
            found = self._find(what, lookup, True)
            if found is not None:
                return found
        raise UnknownOutcome(getattr(err, "status", 0), getattr(err, "code", None),
                             f"{what}: 결과를 모릅니다. 다시 보내지 않습니다(두 번 들어가지 않게): {err}")

    def _lookup(self, fn, **k):
        try:
            return self._retry("lookup", fn, **k)
        except TestnetError as e:
            if e.code in NOT_FOUND:
                return None
            raise

    # reads
    def sync_time(self):
        return self._retry("time", self.c.sync_time)

    def spec(self, symbol):
        return self._retry("spec", self.c.spec, symbol)

    def mark(self, symbol):
        return self._retry("mark", self.c.mark, symbol)

    def price(self, symbol):
        return self._retry("price", self.c.price, symbol)

    def account(self):
        return self._retry("account", self.c.account)

    def position(self, symbol):
        return self._retry("position", self.c.position, symbol)

    def positions(self):
        return self._retry("positions", self.c.positions)

    def open_orders(self, symbol):
        return self._retry("open orders", self.c.open_orders, symbol)

    def open_algo_orders(self, symbol):
        return self._retry("open algo orders", self.c.open_algo_orders, symbol)

    def algo_order(self, algo_id=None, client_id=None):
        return self._retry("algo order", self.c.algo_order, algo_id=algo_id, client_id=client_id)

    def order(self, symbol, order_id=None, client_id=None):
        return self._retry("order", self.c.order, symbol, order_id=order_id, client_id=client_id)

    def user_trades(self, symbol, start_ms, end_ms):
        return self._retry("fills", self.c.user_trades, symbol, start_ms, end_ms)

    def income(self, symbol, income_type, start_ms, end_ms):
        return self._retry("income", self.c.income, symbol, income_type, start_ms, end_ms)

    def leverage_brackets(self):
        return self._retry("brackets", self.c.leverage_brackets)

    # idempotent writes
    def one_way(self):
        return self._retry("one-way", self.c.one_way)

    def isolated(self, symbol):
        return self._retry("isolated", self.c.isolated, symbol)

    def leverage(self, symbol, lev):
        return self._retry("leverage", self.c.leverage, symbol, lev)

    def cancel_all(self, symbol):
        return self._retry("cancel all", self.c.cancel_all, symbol)

    def cancel_all_algo(self, symbol):
        return self._retry("cancel all algo", self.c.cancel_all_algo, symbol)

    def cancel_algo(self, algo_id=None, client_id=None):
        sent, resynced, attempt = False, False, 0
        while attempt < self.retries:
            self._pace()
            try:
                return self.c.cancel_algo(algo_id=algo_id, client_id=client_id)
            except TestnetError as e:
                if e.code in NOT_FOUND and sent:
                    return {"algoId": algo_id, "gone": True}     # our earlier attempt did it
                if e.code == BAD_TIMESTAMP and not resynced:     # refused, not executed: re-sync and send again
                    resynced = True
                    self._resync("cancel algo", e)
                    continue
                if not isinstance(e, (TransientError, RateLimited)) or attempt == self.retries - 1:
                    raise
                sent = True
                self._backoff(attempt, e, "cancel algo")
                attempt += 1

    # orders
    def market(self, symbol, side, qty, reduce_only=False, client_id=None):
        """A reduce-only order may be sent again after a look-up that found nothing (it can only close); an
        opening order never is."""
        cid = client_id or new_client_id("m")
        return self._write("market", lambda: self.c.market(symbol, side, qty, reduce_only=reduce_only, client_id=cid),
                           lambda: self._lookup(self.c.order, symbol=symbol, client_id=cid), resend=reduce_only)

    def stop_close(self, symbol, side, trigger, qty=None, client_id=None):
        cid = client_id or new_client_id("s")
        return self._write("stop", lambda: self.c.stop_close(symbol, side, trigger, qty=qty, client_id=cid),
                           lambda: self._lookup(self.c.algo_order, client_id=cid))


def new_client_id(tag: str, seed: str = "") -> str:
    """Binance client ids: ^[.A-Z:/a-z0-9_-]{1,36}$."""
    h = hashlib.sha1(f"{seed}|{time.time_ns()}|{os.getpid()}".encode()).hexdigest()[:20]
    return f"pb{tag}{h}"


# ---------------------------------------------------------------- the executor
@dataclass
class Snapshot:
    positions: dict                      # symbol -> signed amount (non-zero only)
    entry: dict                          # symbol -> entry price
    stops: dict                          # symbol -> live STOP_MARKET algo orders
    equity: float
    wallet: float


class Executor:
    def __init__(self, cfg: ExecConfig, client: TestnetClient, source, store: ExecStore,
                 notifier: Optional[Notifier] = None, now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                 sleep: Callable[[float], None] = time.sleep, exists: Callable[[str], bool] = os.path.exists,
                 keycheck: Optional[KeyCheckClient] = None, env: Optional[Mapping] = None,
                 signals: Optional[SignalSource] = None):
        refuse_unless_allowed(cfg, client)
        probs = cfg.problems()
        if probs:
            raise Refused("설정이 끝나지 않아 시작하지 않습니다: " + "; ".join(probs))
        env = os.environ if env is None else env
        paper_env = read_env_file(cfg.paper_env_file)
        if cfg.mode == MODE_MAINNET:
            key, secret = trading_keys(MODE_MAINNET, env, paper_env)        # flag, separate names, no reuse
            if (client.key, client.secret) != (key, secret):
                raise Refused("실거래 실행기의 키가 LIVE_API_KEY/LIVE_API_SECRET와 다릅니다")
            if not isinstance(keycheck, KeyCheckClient) or (keycheck.key, keycheck.secret) != (key, secret):
                raise Refused("실거래는 키 권한 확인(api.binance.com)을 거쳐야 시작합니다")
        else:
            reused = {str(env.get(n) or "") for n in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "LIVE_API_KEY",
                                                       "LIVE_API_SECRET")}
            reused |= {paper_env.get(n, "") for n in ("BINANCE_API_KEY", "BINANCE_API_SECRET")}
            if {client.key, client.secret} & (reused - {""}):
                raise Refused("테스트넷 키가 paper 실행기 키나 실거래 키와 같습니다. testnet 전용 키를 쓰세요")
        self.cfg, self.raw, self.source, self.store = cfg, client, source, store
        self.keycheck = keycheck
        self.notifier = notifier or NullNotifier()
        self.now_ms, self.sleep, self.exists = now_ms, sleep, exists
        self.prefix = PREFIX[cfg.mode]
        bot = store.get_state("bot") or {}
        meta = store.get_state("meta")
        recorded = (meta or {}).get("mode") or bot.get("mode")
        if recorded and recorded != cfg.mode:
            raise Refused(f"이 DB({cfg.db})는 {recorded} 기록입니다. {cfg.mode}는 다른 db 파일을 쓰세요")
        was = (meta or {}).get("account") or bot.get("account")
        if was and was != cfg.account:
            raise Refused(f"이 DB는 paper 계좌 {was}의 기록입니다. 계좌를 바꾸려면 새 db 파일을 쓰세요")
        if meta is None:
            store.put_state("meta", now_ms(), {"mode": cfg.mode, "account": cfg.account, "since": now_ms()})
            store.commit()
        client.on_request = self._audit
        if keycheck is not None:
            keycheck.on_request = self._audit
        self.c = Guarded(client, sleep, cfg.retries,
                         on_retry=lambda what, e: self._event(WARN, "retry", f"{what} 재시도: {e}", notify=False))
        self.trade: Optional[dict] = bot.get("trade")
        self.done: list = list(bot.get("done", []))
        self.risk = R.RiskState.from_dict(bot.get("risk"))
        self.loops = int(bot.get("loops", 0))
        self.specs: dict = {}
        self.errors = 0
        self.move_failures = 0
        self._stale_noted = False
        self.last_sync = 0
        self.last_equity = 0
        self.settle_tries: dict = {}
        self.signals = signals if cfg.entry_source == "signal" else None
        if self.signals is None and cfg.entry_source == "signal":
            self.signals = SignalSource(cfg.paper_db, cfg.account)
        self.new_signals: list = []
        self.brackets: dict = {}
        self.paper_taker = cfg.paper_taker_fee
        self.paper_errors = 0
        self.db_failed = False
        self.stopping = False                   # SIGTERM: finish the loop in progress, then stop
        self.last_transfer_scan = 0

    # ------------------------------------------------------------ records
    def _audit(self, a: dict) -> None:
        if a["method"] != "GET" or a.get("error"):
            self.store.request(self.now_ms(), a)
            self.store.commit()

    def _event(self, level: str, kind: str, text: str, data: Optional[dict] = None, notify: bool = True) -> None:
        """Record, then alert. The alert never depends on the database: a write that fails (disk full) is
        reported once as CRITICAL and every WARN/CRITICAL still goes out."""
        try:
            self.store.event(self.now_ms(), level, kind, text, data)
            self.store.commit()
        except sqlite3.Error as e:
            if not self.db_failed:
                self.db_failed = True
                self.notifier.send(CRITICAL, f"{self.prefix} 실행기 DB에 기록하지 못합니다({type(e).__name__}: {e}). "
                                             "알림은 계속 보냅니다. 디스크를 확인하세요")
        if notify and level in (WARN, CRITICAL):
            self.notifier.send(level, f"{self.prefix} {text}")

    def _save(self, strict: bool = True) -> None:
        try:
            self.store.put_state("bot", self.now_ms(), {
                "trade": self.trade, "done": self.done[-200:], "risk": self.risk.to_dict(), "loops": self.loops,
                "mode": self.cfg.mode, "account": self.cfg.account})
            self.store.commit()
        except sqlite3.Error as e:
            if strict:
                raise
            self._event(CRITICAL, "db_error", f"상태 저장 실패(주문은 계속): {e}", notify=False)

    def _mark_done(self, key: str) -> None:
        if key not in self.done:
            self.done.append(key)

    def _cid(self, t: dict, tag: str) -> str:
        """Deterministic client id per trade and order, saved BEFORE the order is sent (best effort: a database
        that cannot be written must not keep a protective order or a close from going out)."""
        t["n"] = int(t.get("n", 0)) + 1
        self._save(strict=False)
        return f"pb{t['base']}{tag}{t['n']}"

    def _server_ms(self) -> int:
        """The exchange's clock (fills, income and transfers carry exchange time)."""
        return self.now_ms() + int(getattr(self.raw, "offset_ms", 0) or 0)

    def _note_offset(self, off) -> None:
        try:
            big = abs(float(off)) > 1000
        except (TypeError, ValueError):
            return
        self._event(WARN if big else INFO, "time_sync", f"서버 시간 다시 맞춤: 차이 {off} ms"
                    + (" (1초 넘게 어긋남: 서버 시계(chrony)를 확인하세요)" if big else ""),
                    {"offset_ms": off}, notify=big)

    def _spec(self, symbol: str) -> dict:
        if symbol not in self.specs:
            self.specs[symbol] = self.c.spec(symbol)
        return self.specs[symbol]

    # ------------------------------------------------------------ start / loop
    def start(self) -> None:
        off = self.c.sync_time()
        self.last_sync = self.now_ms()
        if off is not None and abs(float(off)) > 1000:
            self._note_offset(off)
        if self.cfg.mode == MODE_MAINNET:
            self._mainnet_gates()
        self.c.one_way()
        for s in self.cfg.risk.allowed_symbols:
            self._spec(s)
            try:
                self.c.isolated(s)
            except TestnetError as e:
                if e.code not in (-4047, -4048):   # open orders / position: cannot change now
                    raise
                self._event(WARN, "margin", f"{s}: 주문이나 포지션이 있어 격리 마진으로 못 바꿨습니다({e.msg})")
        if self.signals is not None:
            self._signal_mode_setup()
        meta = self.store.get_state("meta") or {}
        if not meta.get("live_since"):                     # the first start that passed every gate (stage-check)
            meta = {"mode": self.cfg.mode, "account": self.cfg.account, **meta, "live_since": self.now_ms()}
            self.store.put_state("meta", self.now_ms(), meta)
            self.store.commit()
        self._event(INFO, "start", f"시작: paper 계좌 {self.cfg.account} 따라 하기, {self.cfg.mode}, "
                    f"진입 {'신호 즉시' if self.signals is not None else 'paper 포지션'}, "
                    f"비상 정지 파일 {os.path.abspath(self.cfg.risk.kill_file)}",
                    {"halted": self.risk.halted, "trade": self.trade, "kill_file": self.cfg.risk.kill_file})
        if self.risk.halted:
            self._event(WARN, "halted", f"멈춤 상태로 시작합니다(사람이 풀어야 함): {self.risk.halt_reason}")
        self._save()

    def _mainnet_gates(self) -> None:
        """Online gates before any order: key permissions on api.binance.com and the wallet size.

        The permission read is retried like any other read. If api.binance.com still cannot be reached, that
        is not a refusal (nothing was found wrong): the error escapes, the process exits 1 and systemd starts
        it again in 30 s. A definite problem (permissions, wallet) refuses: exit 2, a person must act."""
        kc = self.keycheck
        kc.offset_ms = self.raw.offset_ms                  # same Binance clock for the signed GET
        acct = self.c.account()
        wallet = float(acct["totalWalletBalance"])
        held = ""
        if self.trade is not None:
            held = (f" 열린 포지션 {self.trade['symbol']}이 있습니다: 그동안은 거래소에 걸린 손절만 지킵니다"
                    "(잠금·청산 따라가기, 비상 정지 파일, 하루 손실 한도는 실행기가 다시 켜질 때까지 멈춤).")
        try:
            perm = self.c._retry("키 권한", kc.api_restrictions)
        except (TransientError, RateLimited) as e:
            self._event(CRITICAL, "mainnet_unreachable", f"api.binance.com 키 권한 확인이 안 됩니다({e}). "
                        "30초 뒤 다시 켭니다(systemd)." + held)
            raise
        except TestnetError as e:
            err = e

            def perm_reader():
                raise err
        else:
            def perm_reader():
                return perm
        problems, warnings = online_gates(perm_reader, wallet, float(self.cfg.budget_usd), acct.get("assets"))
        for w in warnings:
            self._event(WARN, "key_permission", w)
        if problems:
            self._event(CRITICAL, "mainnet_refused", "실거래를 시작하지 않습니다: " + "; ".join(problems) + held)
            raise Refused("; ".join(problems))
        self._event(INFO, "mainnet_gates", f"실거래 관문 통과: 출금 꺼짐, 선물 켜짐, IP 제한 있음, "
                    f"지갑 ${wallet:,.2f} ≤ ${self.cfg.budget_usd * 1.2:,.2f}")

    def _signal_mode_setup(self) -> None:
        """Signal mode needs the exchange's leverage brackets to size like the paper rules; without them it
        falls back to following the paper position."""
        try:
            self.brackets = {p["symbol"]: Brackets.from_binance(p) for p in self.c.leverage_brackets()}
        except (TestnetError, KeyError, TypeError, ValueError) as e:
            self.signals = None
            self._event(WARN, "signal_mode_off", f"레버리지 구간을 못 읽어 빠른 진입을 끄고 paper 포지션을 따라 합니다: {e}")
            return
        if self.paper_taker is None:
            self.paper_taker = P.paper_taker_fee(self.cfg.paper_db)
        try:
            self.signals.new_rows()                        # start from now: older rows are the paper path's
        except sqlite3.Error as e:
            self._event(WARN, "signal_read", f"paper3.db 신호 기록을 못 읽었습니다: {e}", notify=False)

    def run(self, max_loops: Optional[int] = None) -> None:
        """Start (a refused gate raises Refused: exit 2), then loop until ``max_loops`` or SIGTERM. After the
        start nothing ends the loop but SIGTERM: every error, a Refused included, is logged and alerted."""
        self.start()
        n = 0
        while (max_loops is None or n < max_loops) and not self.stopping:
            try:
                self.loop_once()
                self.errors = 0
            except RateLimited as e:
                wait = max(e.retry_after, 120.0 if e.status == 418 else 5.0)
                self._event(CRITICAL if e.status == 418 else WARN, "rate_limit",
                            f"요청 한도 초과({e.status}), {wait:.0f}초 쉽니다")
                self.sleep(wait)
            except Exception as e:  # noqa: BLE001  (log, alert, keep the loop alive)
                self.errors += 1
                level = CRITICAL if self.errors in (3, 10, 30) else WARN
                self._event(level, "loop_error", f"반복 처리 오류 {self.errors}번째: {type(e).__name__}: {e}",
                            notify=self.errors in (1, 3, 10, 30))
            n += 1
            if self.stopping:
                break
            self._wait()
        if self.stopping:
            self._event(INFO, "stop", "끄라는 신호(SIGTERM)를 받아 하던 반복을 마치고 멈춥니다. 열린 포지션과 "
                        "거래소 손절은 그대로 남습니다", {"trade": self.trade})

    def _wait(self) -> None:
        """Sleep until the next loop. In signal mode the wait is cut into ``direct_poll_s`` slices and a new
        submitted signal starts the next loop at once."""
        total = max(self.cfg.poll_s, self.raw.throttle_s())
        if self.signals is None:
            self.sleep(total)
            return
        waited = 0.0
        while waited < total - 1e-9 and not self.stopping:
            step = min(self.cfg.direct_poll_s, total - waited)
            self.sleep(step)
            waited += step
            if self._poll_signals():
                return

    def _poll_signals(self) -> bool:
        if self.signals is None:
            return False
        try:
            rows = self.signals.new_rows()
        except sqlite3.Error as e:
            self._event(WARN, "signal_read", f"paper3.db 신호 기록을 못 읽었습니다: {e}", notify=False)
            return False
        self.new_signals.extend(rows)
        return bool(rows)

    def loop_once(self) -> None:
        self.loops += 1
        now = self.now_ms()
        if now - self.last_sync >= self.cfg.time_sync_s * 1000:
            off = self.c.sync_time()
            self.last_sync = now
            self._event(INFO, "time_sync", f"서버 시간 다시 맞춤: 차이 {off} ms", {"offset_ms": off}, notify=False)
        snap = self._snapshot()
        R.observe_equity(self.risk, self.now_ms(), snap.equity)
        if now - self.last_equity >= self.cfg.equity_every_s * 1000:
            self.store.equity(now, snap.equity, snap.wallet)
            self.last_equity = now
        self._reconcile(snap)
        kill = R.kill_switch_on(self.cfg.risk, self.exists)
        dec = R.check_loop(self.cfg.risk, self.risk, snap.equity, kill)
        if dec.action == R.FLATTEN_HALT:
            self.new_signals = []
            self._flatten_halt(dec)
        else:
            self._poll_signals()
            intent, paper_ts = self.source.read()
            direct = self._direct_intent(paper_ts) if self.new_signals else None
            self._follow(intent, paper_ts, direct)
        self._settle_pending()
        self._save()

    def _snapshot(self) -> Snapshot:
        rows = self.c.positions()
        pos = {r["symbol"]: float(r["positionAmt"]) for r in rows if float(r.get("positionAmt") or 0) != 0}
        entry = {r["symbol"]: float(r.get("entryPrice") or 0) for r in rows}
        syms = set(pos)
        if self.trade:
            syms.add(self.trade["symbol"])
        if self.loops % self.cfg.sweep_every == 1 or self.cfg.sweep_every <= 1:
            syms |= set(self.cfg.risk.allowed_symbols)      # full sweep now and then (rate limits)
        stops = {s: live_stops(self.c, s) for s in sorted(syms)}
        acct = self.c.account()
        return Snapshot(pos, entry, stops, float(acct["totalMarginBalance"]), float(acct["totalWalletBalance"]))

    # ------------------------------------------------------------ reconcile
    def _reconcile(self, snap: Snapshot) -> None:
        t = self.trade
        for sym, amt in snap.positions.items():
            if t is not None and t["symbol"] == sym:
                continue
            self._event(CRITICAL, "unknown_position", f"모르는 포지션 발견: {sym} {amt:+g} → 바로 닫습니다",
                        {"symbol": sym, "amt": amt})
            self._flatten_symbol(sym, "모르는 포지션 정리")
        if t is not None:
            amt = snap.positions.get(t["symbol"], 0.0)
            if t["status"] == "entering":
                if amt == 0:
                    self._event(WARN, "recover", f"재시작 복구: {t['symbol']} 진입 주문이 체결되지 않았습니다 → 진입 취소",
                                {"key": t["key"]})
                    self._mark_done(t["key"])
                    self.trade = t = None
                else:
                    t["status"], t["qty"] = "open", abs(amt)
                    t["entry_price"] = snap.entry.get(t["symbol"]) or t.get("entry_price")
                    self.store.trade_open(t)
                    self._event(WARN, "recover", f"재시작 복구: {t['symbol']} 진입이 체결돼 있습니다 → 손절을 확인합니다",
                                {"key": t["key"], "amt": amt})
            if t is not None and t["status"] == "open":
                if amt == 0:
                    self._closed_on_exchange(t, snap)
                elif (amt > 0) != (t["side"] > 0):
                    self._event(CRITICAL, "wrong_side", f"{t['symbol']} 포지션 방향이 반대입니다({amt:+g}) → 닫고 멈춥니다")
                    self._flatten_symbol(t["symbol"], "방향이 반대인 포지션")
                    if R.halt(self.risk, self.now_ms(), "방향이 반대인 포지션 발견"):
                        self.store.halt_log(self.now_ms(), "halt", self.risk.halt_reason, planned=False)
                else:
                    self._ensure_stop(t, amt, snap.stops.get(t["symbol"], []))
        for sym, stops in snap.stops.items():
            if stops and sym not in snap.positions and (self.trade is None or self.trade["symbol"] != sym):
                self.c.cancel_all_algo(sym)
                self._event(INFO, "stray_orders", f"{sym}: 포지션 없이 남은 손절 {len(stops)}개를 취소했습니다")

    def _ensure_stop(self, t: dict, amt: float, stops: list) -> None:
        spec = self._spec(t["symbol"])
        qty = abs(amt)
        if abs(qty - t["qty"]) > spec["qty_step"] / 2:
            self._event(WARN, "size_mismatch", f"{t['symbol']} 포지션 크기가 {t['qty']:g} → {qty:g}입니다 "
                        "(부분 체결 등). 손절 수량을 맞춥니다")
            t["qty"] = qty
        covering = [s for s in stops if covers(s, amt)]
        exact = [s for s in covering if abs(float(s["triggerPrice"]) - t["stop"]) <= spec["tick"] / 2]
        if exact:
            keep = exact[0]
            t["stop_algo_id"] = keep["algoId"]
            others = [s["algoId"] for s in stops if s["algoId"] != keep["algoId"]]
            if others:
                cancel_stops(self.c, t["symbol"], others)
                self._event(INFO, "extra_stops", f"{t['symbol']}: 남은 손절 {len(others)}개를 정리했습니다")
            return
        if covering:
            self._event(WARN, "stop_level", f"{t['symbol']}: 거래소 손절 위치가 기록({t['stop']:g})과 달라 맞춥니다")
            self._move(t, t["stop"], [s["algoId"] for s in stops], "손절 위치 맞추기")
            return
        self._event(CRITICAL, "no_stop", f"{t['symbol']} 포지션({amt:+g})에 손절이 없습니다 → 바로 다시 겁니다",
                    {"stops": len(stops)})
        self._protect(t, [s["algoId"] for s in stops])

    def _closed_on_exchange(self, t: dict, snap: Snapshot) -> None:
        reason, level = "거래소에서 포지션이 닫혔습니다(이유 미확인)", WARN
        if t.get("stop_algo_id") is not None:
            try:
                o = self.c.algo_order(algo_id=t["stop_algo_id"])
                if o.get("algoStatus") in FIRED_ALGO:
                    reason, level = "거래소 손절(또는 잠금) 발동", INFO
            except TestnetError:
                pass
        t.setdefault("exit_ref", t["stop"])                # the paper rules exit a stop at the stop level
        self.c.cancel_all_algo(t["symbol"])
        self.c.cancel_all(t["symbol"])
        self._finish(t, reason, wallet=snap.wallet, level=level)

    # ------------------------------------------------------------ signal mode (fast entries)
    def _direct_intent(self, paper_ts: Optional[int]) -> Optional[Intent]:
        """The entry the paper account is about to make, from its pending signal, sized with the paper rules.
        None when the paper account will not enter (in a position, halted, bust, sizing refused) or when
        anything is unclear: the paper path then follows the paper position as before."""
        rows, self.new_signals = self.new_signals, []
        eng = getattr(self.source, "engine", None)
        if self.trade is not None or not rows or eng is None:
            return None
        bar = max(int(r["bar_close"]) for r in rows)
        rows = [r for r in rows if int(r["bar_close"]) == bar]
        if eng.get("position") or eng.get("halted") or eng.get("bust"):
            self._event(INFO, "direct_skip", f"paper 계좌가 {'포지션 중' if eng.get('position') else '멈춤/파산'}이라 "
                        "이 신호로 진입하지 않습니다", {"bar_close": bar}, notify=False)
            return None
        pend = [s for s in eng.get("pending", []) if int(s.get("ts", -1)) == bar - 1]
        if not pend:
            self._event(INFO, "direct_wait", "paper 상태에 대기 신호가 없어 paper 포지션을 기다립니다",
                        {"bar_close": bar}, notify=False)
            return None
        prio = list(V3_SYMBOLS)
        pend.sort(key=lambda s: (-float(s.get("score") or 0), prio.index(s["symbol"]) if s["symbol"] in prio
                                 else len(prio), s.get("strategy_id", ""), s.get("timeframe", "")))
        sig = pend[0]
        sym, side = sig["symbol"], int(sig["side"])
        row = next((r for r in rows if r["symbol"] == sym and int(r["side"]) == side), None)
        meta = sig.get("meta") or {}
        ref = float(meta.get("ref_price") or (row or {}).get("ref_price") or 0)
        ready = int(meta.get("ref_time") or (row or {}).get("ref_time") or 0)
        key = f"{self.cfg.account}|{sym}|{bar}"
        if row is None or ref <= 0 or key in self.done:
            return None
        now = self.now_ms()
        if now - ready > self.cfg.direct_max_age_s * 1000:
            self._event(INFO, "direct_late", f"신호를 {(now - ready) / 1000:.0f}초 뒤에 봐서 paper 포지션을 따릅니다",
                        {"key": key}, notify=False)
            return None
        if paper_ts is None or now - paper_ts > self.cfg.paper_stale_s * 1000:
            return None
        atr = sig.get("atr") if sig.get("atr") is not None else row.get("atr")
        dist = float(meta.get("stop_dist") or self.cfg.stop_atr * float(atr or 0))
        if dist <= 0 or sym not in self.brackets or sym not in self.cfg.risk.allowed_symbols:
            return None
        settings = v3_settings(taker_fee=self.paper_taker if self.paper_taker is not None else P.PAPER_TAKER_FEE)
        fill = ref * (1 + side * settings.slippage_frac)
        stop = ref - side * dist
        spec = self._spec(sym)
        dec = size_position(settings, float(eng.get("wallet") or 0), side, fill, stop, sig.get("tier") or "best",
                            self.brackets[sym], atr=None if atr is None else float(atr),
                            qty_step=spec["qty_step"], min_notional=spec["min_notional"])
        if not dec.ok:
            self._event(INFO, "direct_skip", "paper 규칙의 크기 계산이 이 진입을 거절해 따라 하지 않습니다",
                        {"key": key, "reasons": dec.reasons}, notify=False)
            return None
        return Intent(key=key, symbol=sym, side=side, qty=dec.qty, leverage=dec.leverage, stop=stop,
                      entry_price=fill, entry_time=bar, direct=True, signal_ref=ref, signal_ready=ready)

    # ------------------------------------------------------------ follow the paper account
    def _follow(self, intent: Optional[Intent], paper_ts: Optional[int], direct: Optional[Intent] = None) -> None:
        t = self.trade
        if t is not None and t["status"] == "open":
            if t.get("direct") and not t.get("confirmed"):
                if intent is not None and intent.key == t["key"]:
                    self._confirm(t, intent)
                elif paper_ts is not None and paper_ts >= int(t["entry_time"]):
                    self._exit(t, "paper가 이 신호로 진입하지 않았습니다(빠른 진입 취소)")
                    return
                elif self.now_ms() - int(t["entry_time"]) > self.cfg.direct_confirm_s * 1000:
                    self._exit(t, f"paper 포지션이 {self.cfg.direct_confirm_s:.0f}초 안에 나타나지 않아 닫습니다(빠른 진입)")
                    return
                else:
                    return                                   # the exchange stop protects until the paper catches up
            if intent is None or intent.key != t["key"]:
                self._exit(t, "paper 청산 → 거래소 포지션 닫기")
                t = None
            else:
                spec = self._spec(t["symbol"])
                new = self._stop_level(intent.stop, intent.entry_price, t["entry_price"], spec["tick"], t["side"])
                if (new - t["stop"]) * t["side"] > spec["tick"] / 2:
                    self._move(t, new, [s["algoId"] for s in live_stops(self.c, t["symbol"])], "잠금 올리기")
                return
        if self.trade is not None:
            return
        now = self.now_ms()
        if direct is not None and direct.key not in self.done:
            self._enter(direct)
            return
        if intent is None or intent.key in self.done:
            return
        if paper_ts is None or now - paper_ts > self.cfg.paper_stale_s * 1000:
            if not self._stale_noted:
                self._event(WARN, "paper_stale", "paper 기록이 멈춰 있어 새 진입을 하지 않습니다")
                self._stale_noted = True
            return
        self._stale_noted = False
        if now - intent.entry_time > self.cfg.max_entry_age_s * 1000:
            self._mark_done(intent.key)
            self._event(WARN, "late", f"paper 진입이 {(now - intent.entry_time) / 1000:.0f}초 전이라 따라 하지 않습니다",
                        {"key": intent.key})
            return
        self._enter(intent)

    def _confirm(self, t: dict, it: Intent) -> None:
        """The paper position of a fast entry appeared: from here on it is followed like any other."""
        t["confirmed"] = True
        spec = self._spec(t["symbol"])
        paper_qty = _round_down(it.qty * self.cfg.qty_scale, spec["qty_step"])
        diff = {}
        if abs(paper_qty - t["planned_qty"]) > spec["qty_step"] / 2:
            diff["qty"] = (t["planned_qty"], paper_qty)
        if it.leverage != t.get("paper_leverage"):
            diff["leverage"] = (t.get("paper_leverage"), it.leverage)
        self._event(WARN if diff else INFO, "direct_confirmed",
                    "빠른 진입이 paper 포지션과 맞습니다" if not diff else
                    f"빠른 진입 확인, 예상과 다른 값(우리, paper): {diff} (크기는 바꾸지 않습니다)",
                    {"key": t["key"], **diff}, notify=False)
        self.store.trade_open(t)
        self._save()

    def _enter(self, it: Intent) -> None:
        spec = self._spec(it.symbol) if it.symbol in self.cfg.risk.allowed_symbols else None
        if spec is None:
            dec = R.check_entry(self.cfg.risk, self.risk, it.symbol, 1, 1, 1, 1)
        else:
            price = self.c.price(it.symbol)
            qty = _round_down(it.qty * self.cfg.qty_scale, spec["qty_step"])
            dec = R.check_entry(self.cfg.risk, self.risk, it.symbol, qty, price, it.leverage, spec["qty_step"],
                                spec["min_qty"], spec["min_notional"])
        self._event(INFO if dec.ok else WARN, "entry_check", f"진입 검사({it.symbol}): {dec.action} - {dec.text()}",
                    {"key": it.key, "qty": dec.qty, "leverage": dec.leverage, "direct": it.direct})
        if not dec.ok:
            self._mark_done(it.key)
            return
        stop = self._stop_level(it.stop, it.entry_price, price, spec["tick"], it.side)
        if (price - stop) * it.side <= 0:
            self._mark_done(it.key)
            self._event(WARN, "entry_skip", f"{it.symbol} 가격 {price:g}이 이미 paper 손절선 {stop:g}을 지나 진입하지 않습니다")
            return
        open_side = "BUY" if it.side > 0 else "SELL"
        t = {"key": it.key, "base": hashlib.sha1(it.key.encode()).hexdigest()[:12], "symbol": it.symbol,
             "side": it.side, "qty": dec.qty, "leverage": dec.leverage, "stop": stop, "stop_initial": stop,
             "stop_algo_id": None, "status": "entering", "n": 0, "entry_ts": self.now_ms(),
             "wallet_before": float(self.c.account()["totalWalletBalance"]), "paper_entry": it.entry_price,
             "entry_price": None, "entry_ref": price, "entry_time": it.entry_time, "mode": self.cfg.mode,
             "direct": it.direct, "confirmed": not it.direct, "planned_qty": _round_down(
                 it.qty * self.cfg.qty_scale, spec["qty_step"]), "paper_leverage": it.leverage,
             "signal_ref": it.signal_ref, "signal_ready": it.signal_ready}
        self.trade = t
        self._save()                                       # write-ahead: a crash now is recovered by reconcile
        try:
            self.c.leverage(it.symbol, dec.leverage)
        except TestnetError as e:
            self.trade = None
            self._mark_done(it.key)
            self._event(WARN, "leverage_refused", f"{it.symbol} 레버리지 {dec.leverage}배 설정이 거절돼 진입하지 않습니다: {e}")
            return
        try:
            o = self.c.market(it.symbol, open_side, dec.qty, client_id=f"pb{t['base']}e")
        except TransientError as e:
            self._event(WARN, "entry_unknown", f"{it.symbol} 진입 주문 결과를 모릅니다({e}); 다음 확인에서 정리합니다")
            return
        except TestnetError as e:
            self.trade = None
            self._mark_done(it.key)
            self._event(WARN, "entry_refused", f"{it.symbol} 진입 주문이 거절됐습니다: {e}")
            return
        sent = self.now_ms()
        amt = float(self.c.position(it.symbol)["positionAmt"])
        if amt == 0:
            self.trade = None
            self._mark_done(it.key)
            self._event(WARN, "entry_unfilled", f"{it.symbol} 진입 주문이 체결되지 않았습니다(상태 {o.get('status')})")
            return
        t["status"], t["qty"] = "open", abs(amt)
        t["entry_price"] = float(o.get("avgPrice") or 0) or float(self.c.position(it.symbol).get("entryPrice") or 0) \
            or price
        t["stop"] = t["stop_initial"] = self._stop_level(it.stop, it.entry_price, t["entry_price"], spec["tick"], it.side)
        if it.signal_ready:
            t["signal_lag_ms"] = sent - it.signal_ready         # signal ready -> live order answered
        if abs(amt) < dec.qty - spec["qty_step"] / 2:
            self._event(WARN, "partial_fill", f"{it.symbol} 진입이 일부만 체결됐습니다: {abs(amt):g}/{dec.qty:g}")
        self.store.trade_open(t)
        self._save()
        lag = f", 신호 후 {t['signal_lag_ms'] / 1000:.1f}초" if it.signal_ready else ""
        self._event(INFO, "entry", f"진입 {it.symbol} {'롱' if it.side > 0 else '숏'} {abs(amt):g} @ {t['entry_price']:g}, "
                    f"{dec.leverage}배, 손절 {t['stop']:g}{' (빠른 진입' + lag + ')' if it.direct else ''}",
                    {"key": it.key, "direct": it.direct, "signal_lag_ms": t.get("signal_lag_ms")})
        self._protect(t, [])

    def _stop_level(self, paper_stop: float, paper_entry: float, live_ref: Optional[float], tick: float,
                    side: int) -> float:
        """The exchange stop for a paper stop. "ratio" keeps the paper's distance from its fill (the testnet
        price is not the real market price, and a live fill is never exactly the paper fill); "price" copies
        the paper price. Rounded to the tick, never looser."""
        level = paper_stop
        if self.cfg.stop_from == "ratio" and live_ref and paper_entry:
            level = live_ref * paper_stop / paper_entry
        return round_stop(level, tick, side)

    def _protect(self, t: dict, old_ids: list) -> None:
        """Put the intended stop on the exchange (new first, then the old ones go). If that is not
        possible the position is closed: a position without a stop must not stay."""
        close_side = "SELL" if t["side"] > 0 else "BUY"
        try:
            res = move_stop(self.c, t["symbol"], close_side, t["stop"], t["qty"], old_ids,
                            client_id=self._cid(t, "s"), close_id=self._cid(t, "x"))
        except (TestnetError, ProtectionError) as e:
            self._event(CRITICAL, "protect_failed", f"{t['symbol']} 손절을 걸 수 없어 포지션을 닫습니다: {e}")
            self._flatten_symbol(t["symbol"], "손절을 걸 수 없음")
            return
        self._after_move(t, t["stop"], res, "손절 걸기")

    def _move(self, t: dict, new_stop: float, old_ids: list, why: str) -> None:
        close_side = "SELL" if t["side"] > 0 else "BUY"
        try:
            res = move_stop(self.c, t["symbol"], close_side, new_stop, t["qty"], old_ids,
                            client_id=self._cid(t, "s"), close_id=self._cid(t, "x"))
        except (TestnetError, ProtectionError) as e:
            self.move_failures += 1
            self._event(CRITICAL if self.move_failures >= 3 else WARN, "move_failed",
                        f"{t['symbol']} {why} 실패 {self.move_failures}번째(옛 손절 {t['stop']:g}은 그대로): {e}")
            return
        self.move_failures = 0
        self._after_move(t, new_stop, res, why)

    def _after_move(self, t: dict, new_stop: float, res: dict, why: str) -> None:
        if res["result"] == "moved":
            old = t["stop"]
            t["stop"], t["stop_algo_id"] = new_stop, res["stop"]["algoId"]
            self._event(INFO, "stop", f"{t['symbol']} {why}: 손절 {old:g} → {new_stop:g} (거래소 확인)",
                        {"algoId": t["stop_algo_id"], "cancelled": res["cancelled"]})
        elif res["result"] == "closed":
            self._event(WARN, "stop_would_trigger", f"{t['symbol']} {why}: 가격이 이미 {new_stop:g}을 지나 "
                        "시장가로 닫았습니다(-2021)")
            t.setdefault("exit_ref", new_stop)
            if self._settle_flat(t["symbol"]):         # not flat: the next reconcile protects or closes the rest
                self._finish(t, "손절/잠금 가격이 이미 지나 시장가로 닫음")
        else:
            t["stop"], t["stop_algo_id"] = new_stop, res["stop"].get("algoId")
            self._event(INFO, "stop_fired", f"{t['symbol']} {why}: 새 손절이 바로 발동했습니다")
        self._save()

    # ------------------------------------------------------------ closing
    def _settle_flat(self, symbol: str) -> bool:
        self.c.cancel_all_algo(symbol)
        self.c.cancel_all(symbol)
        amt = float(self.c.position(symbol)["positionAmt"])
        if amt != 0:
            self._event(CRITICAL, "not_flat", f"{symbol} 닫은 뒤에도 포지션 {amt:+g}이 남았습니다")
            return False
        return True

    def _exit(self, t: dict, reason: str) -> None:
        amt = float(self.c.position(t["symbol"])["positionAmt"])
        if amt != 0:
            t["exit_ref"] = self.c.price(t["symbol"])
            self.c.market(t["symbol"], "SELL" if amt > 0 else "BUY", abs(amt), reduce_only=True,
                          client_id=self._cid(t, "x"))
        if self._settle_flat(t["symbol"]):
            self._finish(t, reason)

    def _flatten_symbol(self, symbol: str, why: str) -> None:
        t = self.trade if self.trade is not None and self.trade["symbol"] == symbol else None
        amt = float(self.c.position(symbol)["positionAmt"])
        if amt != 0:
            if t is not None:
                t["exit_ref"] = self.c.price(symbol)
            cid = self._cid(t, "x") if t is not None else new_client_id("x", symbol)
            self.c.market(symbol, "SELL" if amt > 0 else "BUY", abs(amt), reduce_only=True, client_id=cid)
        flat = self._settle_flat(symbol)
        if t is not None and flat:
            self._finish(t, why)

    def _finish(self, t: dict, reason: str, wallet: Optional[float] = None, level: str = INFO) -> None:
        if wallet is None:
            wallet = float(self.c.account()["totalWalletBalance"])
        pnl = wallet - float(t.get("wallet_before") or wallet)       # estimate until the fills are read
        t["exit_ts"] = self.now_ms()
        self.store.trade_close(t["key"], t["exit_ts"], reason, pnl, t, "wallet")
        try:
            cost = self._costs(t)
        except Exception as e:  # noqa: BLE001  (a record only: closing the trade must go on)
            cost = None
            self._event(WARN, "fills_unread", f"{t['symbol']} 체결 기록 계산 오류: {type(e).__name__}: {e}", notify=False)
        if cost is not None and cost["fills"]:
            pnl = cost["pnl"]
        R.record_trade(self.risk, pnl)
        self._mark_done(t["key"])
        if self.trade is t or (self.trade is not None and self.trade["key"] == t["key"]):
            self.trade = None
        extra = "" if cost is None else (f" (체결 기준: 실현 ${cost['realized']:+,.2f}, 수수료 ${cost['commission']:,.2f}, "
                                          f"펀딩 ${cost['funding']:+,.2f})")
        self._event(level, "exit", f"청산 {t['symbol']}: {reason}, 손익 ${pnl:+,.2f}{extra} "
                    f"(연속 손실 {self.risk.consecutive_losses}번)", {"key": t["key"], "pnl": pnl})
        self._save()

    # ------------------------------------------------------------ P&L and cost from the exchange's records
    def _costs(self, t: dict) -> Optional[dict]:
        """Read the trade's fills and funding; store them with the measured P&L and cost. None when the
        exchange could not be read (retried later by ``_settle_pending``)."""
        start = int(t["entry_ts"]) - 5_000
        end = int(t.get("exit_ts") or self.now_ms()) + 5_000
        try:
            fills = self.c.user_trades(t["symbol"], start, end)
            funding = self.c.income(t["symbol"], "FUNDING_FEE", start, end)
        except TestnetError as e:
            self._event(WARN, "fills_unread", f"{t['symbol']} 체결 기록을 못 읽어 나중에 다시 계산합니다: {e}", notify=False)
            return None
        taker = self.paper_taker if self.paper_taker is not None else P.PAPER_TAKER_FEE
        c = P.trade_costs(t["side"], fills, funding, t.get("entry_ref"), t.get("exit_ref") or t.get("stop"),
                          taker_fee=taker)
        self.store.fills(t["key"], fills)
        self.store.funding(t["key"], funding)
        if fills:
            self.store.trade_costs(t["key"], c)
        self.store.commit()
        if c["problems"]:
            self._event(INFO, "cost_note", f"{t['symbol']} 비용 측정 메모: {', '.join(c['problems'])}",
                        {"key": t["key"]}, notify=False)
        return c

    def _settle_pending(self) -> None:
        """One closed trade per loop whose P&L is still the wallet estimate: try its fills again (up to 5 times,
        within 6 days: userTrades answers at most 7-day windows)."""
        row = self.store.conn.execute(
            "SELECT key, data FROM trades WHERE exit_ts IS NOT NULL AND COALESCE(pnl_source, 'wallet') = 'wallet' "
            "AND exit_ts > ? ORDER BY exit_ts LIMIT 5", (self.now_ms() - 6 * 86_400_000,)).fetchall()
        for key, data in row:
            if self.settle_tries.get(key, 0) >= 5:
                continue
            self.settle_tries[key] = self.settle_tries.get(key, 0) + 1
            t = json.loads(data)
            if "entry_ts" in t and "side" in t:
                try:
                    self._costs(t)
                except Exception as e:  # noqa: BLE001
                    self._event(WARN, "fills_unread", f"{key} 체결 기록 계산 오류: {e}", notify=False)
            return

    def _flatten_halt(self, dec: R.Decision) -> None:
        if R.halt(self.risk, self.now_ms(), dec.text()):
            self.store.halt_log(self.now_ms(), "halt", dec.text(), planned=True)
            self._event(CRITICAL, "halt", f"거래를 멈춥니다(사람이 풀 때까지): {dec.text()}")
        for row in self.c.positions():
            self._flatten_symbol(row["symbol"], "멈춤: " + dec.text())
        if self.trade is not None and self.trade["status"] == "entering":
            self._mark_done(self.trade["key"])
            self.trade = None


# ---------------------------------------------------------------- stage check (leverage stage review)
def stage_review(exec_db: str, paper_db: str, account: str, now_ms: int, qty_scale: float = 1.0) -> dict:
    """risk.leverage_stage_review on the live record (executor db, read-only), the paper account's P&L over
    the same days (paper3.db, read-only) and the cost ratio measured from the fills."""
    conn = _ro(exec_db)
    try:
        def state(k):
            r = conn.execute("SELECT data FROM state WHERE k = ?", (k,)).fetchone()
            return json.loads(r[0]) if r else {}
        meta, bot = state("meta"), state("bot")
        mode = meta.get("mode") or bot.get("mode") or MODE_TESTNET
        cols = ("key", "entry_ts", "exit_ts", "pnl", "pnl_source", "real_cost", "assumed_cost", "cost_ok")
        trades = [dict(zip(cols, r)) for r in conn.execute(f"SELECT {', '.join(cols)} FROM trades ORDER BY entry_ts")]
        curve = [r[0] for r in conn.execute("SELECT equity FROM equity ORDER BY ts")]
        halts = conn.execute("SELECT COUNT(*) FROM halts WHERE action = 'halt' AND COALESCE(planned, 0) = 0"
                             ).fetchone()[0]
        marks = ",".join("?" * len(EMERGENCY_KINDS))
        emerg = dict(conn.execute(f"SELECT kind, COUNT(*) FROM events WHERE kind IN ({marks}) GROUP BY kind",
                                  EMERGENCY_KINDS).fetchall())
    finally:
        conn.close()
    closed = [t for t in trades if t["exit_ts"] is not None and t["pnl"] is not None]
    start = int(meta.get("since") or (trades[0]["entry_ts"] if trades else now_ms))
    cost = P.cost_ratio([{"ok": t["pnl_source"] == "fills" and t["cost_ok"] == 1, "real_cost": t["real_cost"],
                          "assumed_cost": t["assumed_cost"]} for t in closed])
    paper = P.paper_pnl(paper_db, account, start, now_ms)
    unplanned = int(halts) + sum(emerg.values())
    rev = R.leverage_stage_review(closed, start, now_ms, curve, cost["ratio"], None if paper is None else paper["pnl"],
                                  unplanned)
    if mode != MODE_MAINNET:
        rev = {**rev, "ok": False, "next": R.LEVERAGE_STAGES[0],
               "note": "테스트넷 기록입니다. 실거래 단계 판정에는 쓰지 않습니다(참고용). " + rev["note"]}
    return {"mode": mode, "start": start, "now": now_ms, "review": rev, "cost": cost, "paper": paper,
            "paper_scaled": None if paper is None else paper["pnl"] * qty_scale, "unplanned_halts": int(halts),
            "emergencies": emerg, "trades": len(closed),
            "fills_measured": sum(1 for t in closed if t["pnl_source"] == "fills")}


def _day(ms: int) -> str:
    return _dt.datetime.fromtimestamp(ms / 1000, _dt.timezone(_dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")


def stage_text(r: dict, account: str) -> str:
    rev, cost, paper = r["review"], r["cost"], r["paper"]
    lines = [f"레버리지 단계 점검 ({'실거래' if r['mode'] == MODE_MAINNET else '테스트넷'} 기록, "
             f"{_day(r['start'])} ~ {_day(r['now'])})"]
    lines += [f"- {x}" for x in rev["reasons"]]
    if cost["ratio"] is None:
        lines.append(f"비용: 아직 잰 거래가 없습니다 (체결 기록으로 잰 거래 {cost['measured']}/{cost['trades']}건)")
    else:
        lines.append(f"비용: 실제 ${cost['real']:,.2f} ÷ paper 규칙 가정 ${cost['assumed']:,.2f} = {cost['ratio']:.2f} "
                     f"(체결 기록으로 잰 거래 {cost['measured']}/{cost['trades']}건)")
    if paper is None:
        lines.append(f"paper 계좌 {account}: paper3.db를 읽지 못했습니다")
    else:
        lines.append(f"paper 계좌 {account} 같은 기간: 끝난 거래 {paper['trades']}건, 손익 ${paper['pnl']:+,.2f} "
                     f"(실행기 크기로 환산 ${r['paper_scaled']:+,.2f})")
    if r["emergencies"] or r["unplanned_halts"]:
        kinds = ", ".join(f"{k} {v}번" for k, v in sorted(r["emergencies"].items()))
        lines.append(f"계획에 없던 일: 멈춤 {r['unplanned_halts']}번" + (f", 대조 비상 처리 {kinds}" if kinds else ""))
    lines.append(f"결론: {'통과' if rev['ok'] else '아직 아님'} — 최대 레버리지 {rev['next']}배. {rev['note']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI
def _notifier() -> Notifier:
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_CRITICAL"):
        from .notify import TelegramNotifier
        return TelegramNotifier()
    return ConsoleNotifier()


def _clients(cfg: ExecConfig, env: Optional[Mapping] = None):
    """(order client, key-permission client or None) for the configured mode, keys from the environment."""
    env = os.environ if env is None else env
    key, secret = trading_keys(cfg.mode, env, read_env_file(cfg.paper_env_file))
    if cfg.mode == MODE_MAINNET:
        return MainnetClient(key, secret), KeyCheckClient(key, secret)
    return TestnetClient(key, secret), None


def _client() -> TestnetClient:           # kept for scripts written against the testnet-only version
    return _clients(ExecConfig("x@1m", "", "", 1.0, R.RiskConfig()))[0]


def cmd_run(args) -> int:
    cfg = ExecConfig.from_file(args.config)
    store = ExecStore(cfg.db)
    try:
        client, keycheck = _clients(cfg)
        ex = Executor(cfg, client, Paper3Source(cfg.paper_db, cfg.account), store, _notifier(), keycheck=keycheck)
        ex.run(args.max_loops)
    finally:
        store.close()
    return 0


def preflight(cfg: ExecConfig, client, keycheck, out=print) -> bool:
    """Every gate, no order: config, host, server time, (mainnet) key permissions and wallet, paper3.db."""
    ok = True

    def line(good: bool, text: str) -> None:
        nonlocal ok
        ok = ok and good
        out(("[OK]   " if good else "[FAIL] ") + text)

    probs = cfg.problems()
    line(not probs, "설정 완료" if not probs else "설정: " + "; ".join(probs))
    try:
        refuse_unless_allowed(cfg, client)
        line(True, f"주소 {client.host} ({cfg.mode})")
    except Refused as e:
        line(False, str(e))
        return False
    try:
        off = client.sync_time()
        line(abs(off) < 1000, f"서버 시간 차이 {off} ms (1초 미만이어야 함)")
        acct = client.account()
        wallet = float(acct["totalWalletBalance"])
        line(True, f"선물 지갑 ${wallet:,.2f}")
    except (TestnetError, OSError, KeyError, ValueError) as e:
        line(False, f"거래소 연결: {e}")
        return False
    if cfg.mode == MODE_MAINNET:
        keycheck.offset_ms = client.offset_ms
        problems, warnings = online_gates(keycheck.api_restrictions, wallet, float(cfg.budget_usd or 0))
        for p in problems:
            line(False, p)
        if not problems:
            line(True, "키 권한: 출금 꺼짐, 선물 켜짐, IP 제한 있음; 지갑이 정한 금액의 1.2배 이하")
        for w in warnings:
            out("[주의] " + w)
    try:
        intent, ts = Paper3Source(cfg.paper_db, cfg.account).read()
        line(ts is not None, f"paper3.db 계좌 {cfg.account} 읽기" + ("" if ts is not None else ": 상태 없음"))
        if cfg.entry_source == "signal":
            SignalSource(cfg.paper_db, cfg.account).new_rows()
            line(True, "paper3.db 신호 기록(signal_log) 읽기")
    except (Refused, sqlite3.Error) as e:
        line(False, f"paper3.db: {e}")
    return ok


def cmd_preflight(args) -> int:
    cfg = ExecConfig.from_file(args.config)
    client, keycheck = _clients(cfg)
    good = preflight(cfg, client, keycheck)
    print("관문 모두 통과(주문은 하지 않았습니다)" if good else "통과하지 못한 항목이 있습니다")
    return 0 if good else 1


def cmd_stage(args) -> int:
    cfg = ExecConfig.from_file(args.config)
    r = stage_review(cfg.db, cfg.paper_db, cfg.account, int(time.time() * 1000), cfg.qty_scale)
    print(stage_text(r, cfg.account))
    return 0 if r["review"]["ok"] else 1


def cmd_clear(args) -> int:
    cfg = ExecConfig.from_file(args.config)
    kill = R.kill_switch_on(cfg.risk)
    if kill:
        print(f"먼저 비상 정지 파일을 지우세요: {kill}")
        return 1
    store = ExecStore(cfg.db)          # fails while the executor runs: stop it first
    try:
        st = store.get_state("bot") or {}
        rs = R.RiskState.from_dict(st.get("risk"))
        if not rs.halted:
            print("멈춤 상태가 아닙니다")
            return 0
        reason = R.clear_halt(rs)
        now = int(time.time() * 1000)
        store.halt_log(now, "clear", reason, args.by, args.note)
        store.event(now, WARN, "halt_cleared", f"{args.by}님이 멈춤을 풀었습니다: {reason} (메모: {args.note})")
        st["risk"] = rs.to_dict()
        store.put_state("bot", now, st)
        store.commit()
        print(f"멈춤을 풀었습니다: {reason}")
    finally:
        store.close()
    return 0


def cmd_status(args) -> int:
    conn = _ro(args.db)
    r = conn.execute("SELECT ts, data FROM state WHERE k = 'bot'").fetchone()
    if r is None:
        print("아직 상태가 없습니다")
        return 1
    st = json.loads(r[1])
    rs = st.get("risk", {})
    print(f"계좌 {st.get('account')} ({st.get('mode')}), 반복 {st.get('loops')}, "
          f"멈춤 {'예: ' + rs.get('halt_reason', '') if rs.get('halted') else '아니오'}")
    print(f"포지션: {json.dumps(st.get('trade'), ensure_ascii=False)}")
    for ts, level, text in conn.execute("SELECT ts, level, text FROM events ORDER BY id DESC LIMIT 15"):
        print(f"  {ts} [{level}] {text}")
    return 0


def cmd_check(args) -> int:
    try:
        cfg = ExecConfig.from_file(args.config)
    except (Refused, ValueError, TypeError) as e:
        print(f"설정 파일 오류: {e}")
        return 1
    probs = cfg.problems()
    for p in probs:
        print(f"- {p}")
    print("준비됨" if not probs else f"{len(probs)}개를 채워야 합니다")
    return 0 if not probs else 1


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", required=True)
    r.add_argument("--max-loops", type=int)
    c = sub.add_parser("clear-halt")
    c.add_argument("--config", required=True)
    c.add_argument("--by", required=True)
    c.add_argument("--note", default="")
    s = sub.add_parser("status")
    s.add_argument("--db", required=True)
    k = sub.add_parser("check-config")
    k.add_argument("--config", required=True)
    f = sub.add_parser("preflight")
    f.add_argument("--config", required=True)
    g = sub.add_parser("stage-check")
    g.add_argument("--config", required=True)
    args = ap.parse_args(argv)
    try:
        return {"run": cmd_run, "clear-halt": cmd_clear, "status": cmd_status, "check-config": cmd_check,
                "preflight": cmd_preflight, "stage-check": cmd_stage}[args.cmd](args)
    except Refused as e:
        print(f"시작하지 않습니다: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
