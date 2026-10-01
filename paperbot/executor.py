"""Testnet executor: mirrors ONE paper v3 account into real orders on the Binance futures TESTNET.

    TESTNET_API_KEY=... TESTNET_API_SECRET=... \\
        python -m paperbot.executor run --config /etc/paperbot/executor.json
    python -m paperbot.executor status --db /var/lib/paperbot/executor.db
    python -m paperbot.executor clear-halt --config /etc/paperbot/executor.json --by 이름 --note "이유"
    python -m paperbot.executor check-config --config /etc/paperbot/executor.json

What it does (docs/live-safety.md explains it for the owners):
- reads the chosen paper account's open position from paper3.db (read-only);
- paper entry      -> market entry + a protective stop resting on the exchange (algo order,
                      last price), confirmed live;
- paper lock step  -> moves the stop: new stop -> confirmed -> old stop cancelled
                      (-2021 "would immediately trigger" -> reduce-only market close);
- paper exit       -> reduce-only market close, every order cancelled, flat checked.

Every loop, before following the paper account, it reconciles the exchange with its own state:
an unknown position is closed and alerted; a position without a stop gets one at once (or is
closed); a stop smaller than the position is replaced; extra stops are cancelled; a position that
closed on the exchange (stop hit) is booked. Then the risk rules (paperbot/risk.py) run: kill
file, persisted halt, daily loss, drawdown, loss streak -> close everything and halt.

Errors: network failures, timeouts and 5xx are retried with backoff, and an order whose outcome
is unknown is first looked up by its client id (never sent twice). A 4xx refusal is never retried
blindly. 429/418 wait for Retry-After; the rate-limit headers slow the loop down.

Everything (decisions, every order request and answer, trades, halts) goes to the executor's own
SQLite database. One writer: a lock file next to the database stops a second process.

Mode: testnet only. ``mode`` must be "testnet" and the client must point at the testnet host;
anything else refuses to start. A future mainnet mode would need its own switch, its own key
variables and its own host allowlist in a separate client; none of that exists here.
AI agents never import or run this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.parse
from dataclasses import dataclass, fields
from typing import Callable, Optional

from . import risk as R
from .notify import CRITICAL, INFO, WARN, ConsoleNotifier, NullNotifier, Notifier
from .testnet import (ALLOWED_HOSTS, FIRED_ALGO, NOT_FOUND, ProtectionError, RateLimited, TestnetClient,
                      TestnetError, TransientError, _round_down, cancel_stops, covers, live_stops, move_stop,
                      round_stop)

MODE_TESTNET = "testnet"
SUPPORTED_MODES = (MODE_TESTNET,)      # mainnet is deliberately not implemented
TESTNET_HOSTS = ("testnet.binancefuture.com",)
PREFIX = "[테스트넷 실행기]"


class Refused(Exception):
    """The executor will not start (wrong mode, wrong host, missing settings, ...)."""


# ---------------------------------------------------------------- config
@dataclass(frozen=True)
class ExecConfig:
    account: str                          # paper account to mirror, e.g. "V45_AMB@15m"
    paper_db: str                         # paper3.db, opened read-only
    db: str                               # the executor's own database
    qty_scale: float                      # live quantity = paper quantity x qty_scale
    risk: R.RiskConfig
    mode: str = MODE_TESTNET
    poll_s: float = 3.0
    max_entry_age_s: float = 180.0       # paper entries older than this are not followed
    paper_stale_s: float = 300.0         # paper state older than this -> no new entries
    retries: int = 4
    sweep_every: int = 20                # loops between full sweeps of every allowed symbol

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
            out.append(f"mode={self.mode!r}: 이 실행기는 testnet만 지원합니다(실거래 모드는 만들지 않았습니다)")
        if not self.account:
            out.append("따라 할 paper 계좌(account)가 비어 있습니다")
        if not (isinstance(self.qty_scale, (int, float)) and self.qty_scale > 0):
            out.append("qty_scale은 0보다 커야 합니다")
        return out + self.risk.problems()


def refuse_unless_testnet(cfg: ExecConfig, client) -> None:
    if cfg.mode not in SUPPORTED_MODES:
        raise Refused(f"mode={cfg.mode!r}: testnet 외의 모드는 시작하지 않습니다")
    host = urllib.parse.urlparse(getattr(client, "base", "") or "").hostname or ""
    if host not in TESTNET_HOSTS or tuple(ALLOWED_HOSTS) != TESTNET_HOSTS:
        raise Refused(f"주소 {host!r}: testnet(testnet.binancefuture.com) 외에는 연결하지 않습니다")


# ---------------------------------------------------------------- paper side
@dataclass(frozen=True)
class Intent:
    """The paper account's open position: what the exchange should mirror."""
    key: str
    symbol: str
    side: int
    qty: float
    leverage: int
    stop: float
    entry_price: float
    entry_time: int


class Paper3Source:
    """Reads one account's position from paper3.db (read-only; the paper runner is its writer)."""

    def __init__(self, path: str, account: str):
        self.path, self.account = path, account

    def read(self) -> tuple[Optional[Intent], Optional[int]]:
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute("SELECT ts, data FROM state WHERE k = 'accounts'").fetchone()
        finally:
            conn.close()
        if row is None:
            return None, None
        ts, data = int(row[0]), json.loads(row[1])
        eng = data.get("engines", {}).get(self.account)
        if eng is None:
            raise Refused(f"paper 계좌 {self.account}가 paper3.db에 없습니다")
        p = eng.get("position")
        if not p:
            return None, ts
        return Intent(key=f"{self.account}|{p['symbol']}|{int(p['entry_time'])}", symbol=p["symbol"],
                      side=int(p["side"]), qty=float(p["qty"]), leverage=int(p["leverage"]),
                      stop=float(p["stop_price"]), entry_price=float(p["entry_price"]),
                      entry_time=int(p["entry_time"])), ts


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
"""


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
                          "stop_initial, data) VALUES (?,?,?,?,?,?,?,?,?)",
                          (t["key"], t["symbol"], t["side"], t["qty"], t["leverage"], t["entry_ts"],
                           t.get("entry_price"), t.get("stop_initial"), json.dumps(t, default=str)))

    def trade_close(self, key: str, ts: int, reason: str, pnl: Optional[float], data: dict) -> None:
        self.conn.execute("UPDATE trades SET exit_ts = ?, exit_reason = ?, pnl = ?, data = ? WHERE key = ?",
                          (ts, reason, pnl, json.dumps(data, default=str, ensure_ascii=False), key))

    def halt_log(self, ts: int, action: str, reason: str, who: Optional[str] = None,
                 note: Optional[str] = None) -> None:
        self.conn.execute("INSERT INTO halts (ts, action, reason, who, note) VALUES (?,?,?,?,?)",
                          (ts, action, reason, who, note))

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
    """The testnet client with an error policy.

    - reads: network/5xx/429 -> retry with backoff (Retry-After honoured); 4xx -> raise;
    - idempotent writes (leverage, margin type, cancel-all): same as reads;
    - orders (market, stop): sent with a client id; after an unknown outcome the order is looked up
      by that id, and only sent again when the exchange does not have it;
    - 418 (IP banned) is never retried here: the loop waits;
    - before every request: wait if the rate-limit headers say we are near a limit."""

    def __init__(self, client: TestnetClient, sleep: Callable[[float], None], retries: int = 4,
                 base_delay: float = 0.5, max_delay: float = 8.0,
                 on_retry: Optional[Callable[[str, Exception], None]] = None):
        self.c, self.sleep, self.retries = client, sleep, max(1, retries)
        self.base_delay, self.max_delay, self.on_retry = base_delay, max_delay, on_retry

    def __getattr__(self, name):          # host, base, limits ... (not the endpoints: those are below)
        return getattr(self.c, name)

    def _pace(self) -> None:
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

    def _retry(self, what: str, fn, *a, **k):
        for attempt in range(self.retries):
            self._pace()
            try:
                return fn(*a, **k)
            except (TransientError, RateLimited) as e:
                if attempt == self.retries - 1:
                    raise
                self._backoff(attempt, e, what)

    def _write(self, what: str, send, lookup):
        """Send an order that has a client id; on an unknown outcome, look it up before resending."""
        last: Optional[Exception] = None
        for attempt in range(self.retries):
            self._pace()
            try:
                return send()
            except (TransientError, RateLimited) as e:
                last = e
                if isinstance(e, RateLimited) and e.status == 418:
                    raise
                self._backoff(attempt, e, what)
                found = lookup()
                if found is not None:
                    return found
        assert last is not None
        raise last

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
        sent = False
        for attempt in range(self.retries):
            self._pace()
            try:
                return self.c.cancel_algo(algo_id=algo_id, client_id=client_id)
            except TestnetError as e:
                if e.code in NOT_FOUND and sent:
                    return {"algoId": algo_id, "gone": True}     # our earlier attempt did it
                if not isinstance(e, (TransientError, RateLimited)) or attempt == self.retries - 1:
                    raise
                sent = True
                self._backoff(attempt, e, "cancel algo")

    # orders
    def market(self, symbol, side, qty, reduce_only=False, client_id=None):
        cid = client_id or new_client_id("m")
        return self._write("market", lambda: self.c.market(symbol, side, qty, reduce_only=reduce_only, client_id=cid),
                           lambda: self._lookup(self.c.order, symbol=symbol, client_id=cid))

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
                 sleep: Callable[[float], None] = time.sleep, exists: Callable[[str], bool] = os.path.exists):
        refuse_unless_testnet(cfg, client)
        probs = cfg.problems()
        if probs:
            raise Refused("설정이 끝나지 않아 시작하지 않습니다: " + "; ".join(probs))
        self.cfg, self.raw, self.source, self.store = cfg, client, source, store
        self.notifier = notifier or NullNotifier()
        self.now_ms, self.sleep, self.exists = now_ms, sleep, exists
        client.on_request = self._audit
        self.c = Guarded(client, sleep, cfg.retries,
                         on_retry=lambda what, e: self._event(WARN, "retry", f"{what} 재시도: {e}", notify=False))
        st = store.get_state("bot") or {}
        self.trade: Optional[dict] = st.get("trade")
        self.done: list = list(st.get("done", []))
        self.risk = R.RiskState.from_dict(st.get("risk"))
        self.loops = int(st.get("loops", 0))
        self.specs: dict = {}
        self.errors = 0
        self.move_failures = 0
        self._stale_noted = False

    # ------------------------------------------------------------ records
    def _audit(self, a: dict) -> None:
        if a["method"] != "GET" or a.get("error"):
            self.store.request(self.now_ms(), a)
            self.store.commit()

    def _event(self, level: str, kind: str, text: str, data: Optional[dict] = None, notify: bool = True) -> None:
        self.store.event(self.now_ms(), level, kind, text, data)
        self.store.commit()
        if notify and level in (WARN, CRITICAL):
            self.notifier.send(level, f"{PREFIX} {text}")

    def _save(self) -> None:
        self.store.put_state("bot", self.now_ms(), {
            "trade": self.trade, "done": self.done[-200:], "risk": self.risk.to_dict(), "loops": self.loops,
            "mode": self.cfg.mode, "account": self.cfg.account})
        self.store.commit()

    def _mark_done(self, key: str) -> None:
        if key not in self.done:
            self.done.append(key)

    def _cid(self, t: dict, tag: str) -> str:
        """Deterministic client id per trade and order, saved BEFORE the order is sent."""
        t["n"] = int(t.get("n", 0)) + 1
        self._save()
        return f"pb{t['base']}{tag}{t['n']}"

    def _spec(self, symbol: str) -> dict:
        if symbol not in self.specs:
            self.specs[symbol] = self.c.spec(symbol)
        return self.specs[symbol]

    # ------------------------------------------------------------ start / loop
    def start(self) -> None:
        self.c.sync_time()
        self.c.one_way()
        for s in self.cfg.risk.allowed_symbols:
            self._spec(s)
            try:
                self.c.isolated(s)
            except TestnetError as e:
                if e.code not in (-4047, -4048):   # open orders / position: cannot change now
                    raise
                self._event(WARN, "margin", f"{s}: 주문이나 포지션이 있어 격리 마진으로 못 바꿨습니다({e.msg})")
        self._event(INFO, "start", f"시작: paper 계좌 {self.cfg.account} 따라 하기, testnet",
                    {"halted": self.risk.halted, "trade": self.trade})
        if self.risk.halted:
            self._event(WARN, "halted", f"멈춤 상태로 시작합니다(사람이 풀어야 함): {self.risk.halt_reason}")
        self._save()

    def run(self, max_loops: Optional[int] = None) -> None:
        self.start()
        n = 0
        while max_loops is None or n < max_loops:
            try:
                self.loop_once()
                self.errors = 0
            except RateLimited as e:
                wait = max(e.retry_after, 120.0 if e.status == 418 else 5.0)
                self._event(CRITICAL if e.status == 418 else WARN, "rate_limit",
                            f"요청 한도 초과({e.status}), {wait:.0f}초 쉽니다")
                self.sleep(wait)
            except Refused:
                raise
            except Exception as e:  # noqa: BLE001  (log, alert, keep the loop alive)
                self.errors += 1
                level = CRITICAL if self.errors in (3, 10, 30) else WARN
                self._event(level, "loop_error", f"반복 처리 오류 {self.errors}번째: {type(e).__name__}: {e}",
                            notify=self.errors in (1, 3, 10, 30))
            n += 1
            self.sleep(max(self.cfg.poll_s, self.raw.throttle_s()))

    def loop_once(self) -> None:
        self.loops += 1
        snap = self._snapshot()
        R.observe_equity(self.risk, self.now_ms(), snap.equity)
        self._reconcile(snap)
        kill = R.kill_switch_on(self.cfg.risk, self.exists)
        dec = R.check_loop(self.cfg.risk, self.risk, snap.equity, kill)
        if dec.action == R.FLATTEN_HALT:
            self._flatten_halt(dec)
        else:
            intent, paper_ts = self.source.read()
            self._follow(intent, paper_ts)
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
                        self.store.halt_log(self.now_ms(), "halt", self.risk.halt_reason)
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
        self.c.cancel_all_algo(t["symbol"])
        self.c.cancel_all(t["symbol"])
        self._finish(t, reason, wallet=snap.wallet, level=level)

    # ------------------------------------------------------------ follow the paper account
    def _follow(self, intent: Optional[Intent], paper_ts: Optional[int]) -> None:
        t = self.trade
        if t is not None and t["status"] == "open":
            if intent is None or intent.key != t["key"]:
                self._exit(t, "paper 청산 → 거래소 포지션 닫기")
                t = None
            else:
                spec = self._spec(t["symbol"])
                new = round_stop(intent.stop, spec["tick"], t["side"])
                if (new - t["stop"]) * t["side"] > spec["tick"] / 2:
                    self._move(t, new, [s["algoId"] for s in live_stops(self.c, t["symbol"])], "잠금 올리기")
                return
        if self.trade is not None or intent is None or intent.key in self.done:
            return
        now = self.now_ms()
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
                    {"key": it.key, "qty": dec.qty, "leverage": dec.leverage})
        if not dec.ok:
            self._mark_done(it.key)
            return
        stop = round_stop(it.stop, spec["tick"], it.side)
        if (price - stop) * it.side <= 0:
            self._mark_done(it.key)
            self._event(WARN, "entry_skip", f"{it.symbol} 가격 {price:g}이 이미 paper 손절선 {stop:g}을 지나 진입하지 않습니다")
            return
        open_side = "BUY" if it.side > 0 else "SELL"
        t = {"key": it.key, "base": hashlib.sha1(it.key.encode()).hexdigest()[:12], "symbol": it.symbol,
             "side": it.side, "qty": dec.qty, "leverage": dec.leverage, "stop": stop, "stop_initial": stop,
             "stop_algo_id": None, "status": "entering", "n": 0, "entry_ts": self.now_ms(),
             "wallet_before": float(self.c.account()["totalWalletBalance"]), "paper_entry": it.entry_price,
             "entry_price": None}
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
        amt = float(self.c.position(it.symbol)["positionAmt"])
        if amt == 0:
            self.trade = None
            self._mark_done(it.key)
            self._event(WARN, "entry_unfilled", f"{it.symbol} 진입 주문이 체결되지 않았습니다(상태 {o.get('status')})")
            return
        t["status"], t["qty"] = "open", abs(amt)
        t["entry_price"] = float(o.get("avgPrice") or 0) or float(self.c.position(it.symbol).get("entryPrice") or 0)
        if abs(amt) < dec.qty - spec["qty_step"] / 2:
            self._event(WARN, "partial_fill", f"{it.symbol} 진입이 일부만 체결됐습니다: {abs(amt):g}/{dec.qty:g}")
        self.store.trade_open(t)
        self._save()
        self._event(INFO, "entry", f"진입 {it.symbol} {'롱' if it.side > 0 else '숏'} {abs(amt):g} @ {t['entry_price']:g}, "
                    f"{dec.leverage}배, 손절 {stop:g}")
        self._protect(t, [])

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
            self._settle_flat(t["symbol"])
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
            self.c.market(t["symbol"], "SELL" if amt > 0 else "BUY", abs(amt), reduce_only=True,
                          client_id=self._cid(t, "x"))
        if self._settle_flat(t["symbol"]):
            self._finish(t, reason)

    def _flatten_symbol(self, symbol: str, why: str) -> None:
        t = self.trade if self.trade is not None and self.trade["symbol"] == symbol else None
        amt = float(self.c.position(symbol)["positionAmt"])
        if amt != 0:
            cid = self._cid(t, "x") if t is not None else new_client_id("x", symbol)
            self.c.market(symbol, "SELL" if amt > 0 else "BUY", abs(amt), reduce_only=True, client_id=cid)
        flat = self._settle_flat(symbol)
        if t is not None and flat:
            self._finish(t, why)

    def _finish(self, t: dict, reason: str, wallet: Optional[float] = None, level: str = INFO) -> None:
        if wallet is None:
            wallet = float(self.c.account()["totalWalletBalance"])
        pnl = wallet - float(t.get("wallet_before") or wallet)
        R.record_trade(self.risk, pnl)
        self.store.trade_close(t["key"], self.now_ms(), reason, pnl, t)
        self._mark_done(t["key"])
        if self.trade is t or (self.trade is not None and self.trade["key"] == t["key"]):
            self.trade = None
        self._event(level, "exit", f"청산 {t['symbol']}: {reason}, 손익 ${pnl:+,.2f} "
                    f"(연속 손실 {self.risk.consecutive_losses}번)", {"key": t["key"], "pnl": pnl})
        self._save()

    def _flatten_halt(self, dec: R.Decision) -> None:
        if R.halt(self.risk, self.now_ms(), dec.text()):
            self.store.halt_log(self.now_ms(), "halt", dec.text())
            self._event(CRITICAL, "halt", f"거래를 멈춥니다(사람이 풀 때까지): {dec.text()}")
        for row in self.c.positions():
            self._flatten_symbol(row["symbol"], "멈춤: " + dec.text())
        if self.trade is not None and self.trade["status"] == "entering":
            self._mark_done(self.trade["key"])
            self.trade = None


# ---------------------------------------------------------------- CLI
def _notifier() -> Notifier:
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_CRITICAL"):
        from .notify import TelegramNotifier
        return TelegramNotifier()
    return ConsoleNotifier()


def _client() -> TestnetClient:
    key, secret = os.environ.get("TESTNET_API_KEY", ""), os.environ.get("TESTNET_API_SECRET", "")
    if key and key == os.environ.get("BINANCE_API_KEY"):
        raise Refused("TESTNET_API_KEY가 paper 실행기의 BINANCE_API_KEY와 같습니다. testnet 전용 키를 쓰세요")
    return TestnetClient(key, secret)


def cmd_run(args) -> int:
    cfg = ExecConfig.from_file(args.config)
    store = ExecStore(cfg.db)
    try:
        ex = Executor(cfg, _client(), Paper3Source(cfg.paper_db, cfg.account), store, _notifier())
        ex.run(args.max_loops)
    finally:
        store.close()
    return 0


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
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
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
    args = ap.parse_args(argv)
    try:
        return {"run": cmd_run, "clear-halt": cmd_clear, "status": cmd_status, "check-config": cmd_check}[args.cmd](args)
    except Refused as e:
        print(f"시작하지 않습니다: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
