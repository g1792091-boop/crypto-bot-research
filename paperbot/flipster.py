"""Flipster USDT perpetual futures (trading-api.flipster.io) for the executor: client, host allowlist, keys, key check,
the client-id ledger, drill. ``"exchange": "flipster"`` in the executor config uses it (mainnet only: Flipster has no
testnet); the Binance, Bybit, MEXC and WOO X Pro paths are unchanged. Owners 10-23: "플립스터로 확정할게 만들어줘": the
third executor, following the paper bot "VWAP 개선판" (docs/flipster-ko.md).

    python -m paperbot.flipster specs                      # the 6 coins' live contract specs (needs the key: Flipster's
                                                           # contract info is a private endpoint)
    python -m paperbot.flipster check                      # read-only checks + one-way mode + leverage 40/30 (no order)
    python -m paperbot.flipster drill --confirm-order REAL_ORDER [--symbol DOGEUSDT]   # + one smallest-size order cycle
                                                           # and the stop-trigger test (--no-trigger-test skips it)

Sources (read as data, 2026-10-23; trading-api.flipster.io is not reachable from where this was written): Flipster's
own API docs, api-docs.flipster.io (llms.txt, Introduction, Quick Tutorial, Essential Concepts, the API reference pages
with their OpenAPI blocks): base URL https://trading-api.flipster.io, every endpoint signed (contract info and klines
too); headers api-key / api-expires (unix SECONDS when the request expires) / api-signature = hex HMAC-SHA256(secret,
METHOD + path (+ "?" + query exactly as sent) + str(expires) + the body bytes as sent); symbols "BTCUSDT.PERP"; errors
{error: {type, message, code}}; rate limits per API key as requests per second and per minute, numbers not published,
429 with Retry-After; trade modes ONE_WAY / MULTIPLE_POSITIONS (PUT only, refused with RemainingPositionsExist while a
position is open; no endpoint reads the mode); POST /trade/order (MARKET is IOC inside: ``timeInForce`` must be absent,
an unfilled part is cancelled, the answer's ``quantity`` is then the FILLED amount and the status CANCELED; STOP_MARKET:
``price`` = the trigger; ``reduceOnly``; optional ``maxSlippagePrice``); pending orders, order history and execution
history (nanosecond times, cursors, hasNext; execType TRADE / FUNDING / TRIGGERED ...). There is no client order id
anywhere: see the ledger below.

The client answers in the SAME shapes the executor reads from the Binance client (paperbot/testnet.py), like
paperbot/wooxpro.py, so the executor, the stop protocol (place_stop / move_stop / live_stops / covers) and livepnl run
unchanged. Quantities are base-asset amounts on the contract's ``unitOrderQty`` step (live contract info, never a
hard-coded size).

  Binance client call          Flipster (trading-api.flipster.io)
  spec(symbol)                 GET  /api/v1/market/contract (all, cached) + /api/v1/trade/symbol (tradable perps)
  price / mark                 GET  /api/v1/market/ticker?symbol=  lastPrice / markPrice
  klines (1m)                  GET  /api/v1/market/kline interval "1", startTime / endTime in ns, <= 1000 rows
  sync_time                    GET  /api/v1/public/time {serverTime: ns}; api-expires = the server clock + 10 s
  account()                    GET  /api/v1/account (totalWalletBalance, totalUnrealizedPnl, totalMarginBalance, ...)
                               + /api/v1/account/balance for the assets list (cached 60 s)
  one_way()                    PUT  /api/v1/account/trade-mode ONE_WAY, the answer read back (see one_way)
  isolated(symbol)             POST /api/v1/trade/leverage marginType ISOLATED (BTC 40x, others 30x), read back from the
                               answer's position row, else /api/v1/account/position
  market(...)                  ledger intent row, then POST /api/v1/trade/order type MARKET (no timeInForce, no
                               maxSlippagePrice), reduceOnly for closes; read back: executed qty / average / fee from
                               the execution history by orderId (TRADE rows), the order answer as a first look
  order(symbol, id / cid)      the ledger (cid -> orderId, or the order history search below), then the pending list,
                               the order history and the executions of that orderId
  stop_close(...)              ledger intent row, then POST /api/v1/trade/order type STOP_MARKET, closing side,
                               reduceOnly, price = the trigger, quantity = the position's
  algo_order / open_algo_orders GET /api/v1/trade/order (pending STOP_MARKET rows); a stop no longer pending: its order
                               history row and its executions (TRADE: fired, fills under its own orderId)
  cancel_algo / cancel / ...   DELETE /api/v1/trade/order {symbol, orderId} (cancel_all / cancel_all_algo: each
                               pending order / stop of the symbol)
  position / positions         GET  /api/v1/account/position  positionSide LONG / SHORT, positionAmount (base asset)
  user_trades                  GET  /api/v1/trade/execution/history execType TRADE -> fills; realized P&L replayed from
                               the fills' own prices (paperbot/mexc.py fills_from_deals; our reduce-only orders from the
                               ledger mark the closing fills). Flipster gives no per-fill P&L: the drill checks the
                               replay against the wallet change
  income                       the execution history's FUNDING rows (FUNDING_FEE, ``income`` = -execFee). The docs offer
                               no deposit / withdrawal history: no TRANSFER rows (a transfer moves no loss baseline; the
                               live configs set no daily-loss or drawdown halt)

The client-id ledger. The executor identifies its orders by client ids (its entry ``pb{base}e`` is deterministic and
looked up again after a restart; Guarded looks up every order whose answer was lost before deciding anything). Flipster
has no such field, so the ids live in the table ``flipster_ids`` of the executor's OWN database (``cfg.db``: kept and
backed up with the executor's record; the drill and check use one in memory). Before an order is sent its intent row is
written (cid, symbol, side, type, qty, reduce_only, trigger, sent_ms, no orderId); the answer's orderId is written into
it. A look-up by cid: a row with an orderId reads that order. A row without one (the answer was lost, or a crash came
between the send and the write) is searched for in the pending list and the order history of its symbol from sent_ms -
3 s: same side, type, quantity (within half a step; a market order that was partly filled shows its filled amount,
CANCELED), trigger, reduceOnly when the row carries it, and an orderId no other cid holds. Exactly one: it is bound to
the cid and returned. Several: an "unknown" error (never "not found"). None: "not found" only 25 s after sent_ms (the
history is surely written by then), a TransientError before. No row at all: not found. An opening order is never sent
twice (a cid already in the ledger is looked up, never sent again; Guarded never resends one either); a reduce-only
order is sent again only after its earlier send was found to be absent past the 25 s. A row is written durably before an
opening order goes out (not possible: the entry is refused, nothing sent); a stop or a close still goes out when the
database cannot be written (its row is kept in memory: protection first). Rows older than 30 days are trimmed.

maxSlippagePrice is never sent. A close must close (a price cap could leave part of the position open). The docs mark it
optional for every order, the paper rules assume a plain market fill and the owners trade market orders only, so an
opening order goes without it too; the drill's entry checks that such an order fills.

What only a live run can confirm (docs/flipster-ko.md; the drill checks each): two reduce-only STOP_MARKET orders
resting at once (the stop protocol needs it for a moment: new stop -> confirmed -> old one cancelled); a stop actually
firing and closing the position (the trigger test lets one fire for real) and whether the last or the mark price fired
it; whether the fired stop's fills carry its own orderId; that a plain market order (no maxSlippagePrice) fills; the
real taker fee (Flipster charges its full fee; the payback app pays back outside the bot); the server time offset; the
realized P&L replayed from the fills against the wallet change; the ledger's history search finding a just-sent order
by its cid; the sign of the FUNDING rows (compared with the app); which price the 1m candles are of; that the leverage
read-back shows the set leverage (the position list may show no row for a coin without a position: then the setting is
checked on the drill's position).

Safety:
- ``FlipsterClient`` talks to trading-api.flipster.io only (class-level allowlist, https only, checked at construction;
  the executor checks again, and that its ledger is in the executor's own database). Mainnet only.
- Keys: FLIPSTER_LIVE_KEY / FLIPSTER_LIVE_SECRET behind PAPERBOT_LIVE_MAINNET=I_UNDERSTAND; never the paper runner's
  key, a Binance, Bybit, MEXC or WOO X Pro key.
- Key gate: the API does not report a key's permissions. The gate proves the key reads the account; "read + trade only,
  no withdrawal, server IP bound" is the owners' statement FLIPSTER_LIVE_KEY_CHECKED=TRADE_ONLY_NO_WITHDRAW_IP_BOUND
  (refused without it), shown as a warning at every start.
- An order that was accepted (it has an orderId) is never reported as not executed; a lost answer is looked up through
  the ledger; an opening order is never sent twice (an opening order's 429 is an unknown outcome too: looked up, never
  resent).
- A position's size, the account equity and the stop list are never read as 0 / flat / empty from a missing or garbled
  field: such an answer is an error.
- AI agents never import this module (tests/test_flipster.py checks it).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import json
import math
import os
import signal
import sqlite3
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Callable, Optional

from . import bybit as BY
from . import mexc as MX
from . import wooxpro as WX
from .livepnl import balanced
from .mainnet import (FLAG, FLAG_VALUE, LIVE_KEY_NAMES as BINANCE_LIVE_KEY_NAMES, MODE_MAINNET, PAPER_ENV_FILE,
                      PAPER_KEY_NAMES, TESTNET_KEY_NAMES as BINANCE_TESTNET_KEY_NAMES, Refused, check_permissions,
                      read_env_file)
from .testnet import (BAD_TIMESTAMP, NOT_FOUND, WOULD_TRIGGER, RateLimited, TestnetError, TransientError,
                      cancel_everything, covers, hide_process_memory, live_stops, move_stop, place_stop, round_stop,
                      urllib_send)

SETTLE = "USDT"
PERP = ".PERP"
FLIPSTER_BASE = "https://trading-api.flipster.io"
FLIPSTER_HOSTS = ("trading-api.flipster.io",)
API = "/api/v1"
ORDER = API + "/trade/order"
LIVE_KEY_NAMES = ("FLIPSTER_LIVE_KEY", "FLIPSTER_LIVE_SECRET")
KEY_CHECKED = "FLIPSTER_LIVE_KEY_CHECKED"             # the owners' statement: what the API cannot report
KEY_CHECKED_VALUE = "TRADE_ONLY_NO_WITHDRAW_IP_BOUND"
DRILL_CONFIRM = "REAL_ORDER"
DRILL_ORDER_USDT = 6.0                                # the drill's order: about $6 (above the contract's minimum)
DRILL_MIN_GAP_S = 0.5                                 # the drill's requests at least this far apart (limits unknown)
DRILL_PAUSE_S = 3.0
TRIGGER_GAP = 0.001                                   # the trigger test's stop: 0.1 % from the last price
TRIGGER_WAIT_S = 1200                                 # ... waited for at most 20 minutes
PROFIT_GAP = 0.0015                                   # first the price is waited for 0.15 % past the entry, so the test
PROFIT_WAIT_S = 600                                   # stop rests on the profit side (a lock's place); at most 10 min
FIXED_LEVERAGE = MX.FIXED_LEVERAGE                    # owners 2026-10-17: BTC 40x, the other coins 30x
DEFAULT_LEVERAGE = MX.DEFAULT_LEVERAGE
COINS = MX.COINS
PREFIX = {MODE_MAINNET: "[플립스터 실거래 실행기]"}

EXPIRES_S = 10                                        # api-expires: the server clock + 10 s (replay window)
ONE_WAY = "ONE_WAY"
ISOLATED = "ISOLATED"
MARKET, STOP = "MARKET", "STOP_MARKET"
OPEN_STATUS = ("PENDING_NEW", "NEW", "PARTIALLY_FILLED")
FINAL_STATUS = ("FILLED", "CANCELED", "REJECTED")
ORDER_FINAL = ("FILLED", "CANCELED", "REJECTED", "EXPIRED")      # the Binance-shaped statuses this client answers
ORDER_WAITS = (0.05, 0.1, 0.2, 0.4, 0.8)             # a market order's fills are read again after these (s)
KLINE_ROWS = 1000                                     # GET /market/kline: limit 100..1000
WORKING_TYPE = "EXCHANGE_DEFAULT"                     # which price fires a STOP_MARKET: the drill checks it
SETTLE_MS = 25_000                                    # ledger: an order sent this long ago is surely in the history
MATCH_BEFORE_MS = 3_000                               # ... and was created at most this long before its intent row
LEDGER_KEEP_MS = 30 * 86_400_000                      # ledger rows older than this are trimmed
HISTORY_SPAN_MS = 7 * 86_400_000                      # an order looked up by id without a ledger row: the last 7 days
HISTORY_DEPTH = 24                                    # a full history page is read again in halves, at most this deep
HISTORY_REQUESTS = 64                                 # ... and with at most this many requests
BALANCE_CACHE_MS = 60_000                             # the assets list (only the start gates read it)
REMAINING = "RemainingPositionsExist"                 # PUT trade-mode while a position is open (the docs' name)
REMAINING_CODE = "REMAINING_POSITIONS"
AMBIGUOUS = "AMBIGUOUS_ORDER"                         # ledger: several orders fit a lost answer (never "not found")
# requests per window, all endpoints together (the docs give per-key RPS and RPM quotas without numbers): kept well
# under what a market-data client usually gets; a 429 answer is handled (reads again after Retry-After)
RATE_WINDOWS = ((1_000, 8), (60_000, 240))
READ_RETRIES = 3                                      # a read refused for the rate (429): read again after a pause
READ_PAUSE_S = 1.0
# writes that may be sent again after a 429 (refused, nothing ran): settings, cancels, a stop (it is reduce-only; a
# second copy is cancelled as an extra stop). Never a market order (market(): looked up, never sent twice)
RETRY_WRITES = frozenset({"leverage_set", "trade_mode", "cancel", "stop_place"})
EXPIRED_WORDS = ("expire", "timestamp", "recvwindow")
NOT_FOUND_WORDS = ("notfound", "not found", "notexist", "not exist", "unknownorder", "unknown order")


def hosts_for(mode: str) -> tuple:
    return FLIPSTER_HOSTS                  # one host list: mainnet only


# ---------------------------------------------------------------- numbers and names
def _dec(v, what: str = "value") -> Decimal:
    """A number the decision depends on (a size, a price, the equity): missing or garbled is an error, never 0."""
    if v is None or v == "" or isinstance(v, bool):
        raise TransientError(200, None, f"플립스터 응답에 {what} 값이 없습니다")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError) as e:
        raise TransientError(200, None, f"플립스터 응답의 {what} 값이 이상합니다: {v!r}") from e
    if not d.is_finite():
        raise TransientError(200, None, f"플립스터 응답의 {what} 값이 이상합니다: {v!r}")
    return d


_f, _num, _int, _price_str, _id60 = MX._f, MX._num, MX._int, MX._price_str, MX._id60


def fx(symbol: str) -> str:
    """BTCUSDT -> BTCUSDT.PERP."""
    if not symbol.endswith(SETTLE) or len(symbol) <= len(SETTLE):
        raise TestnetError(400, "NO_SYMBOL", f"{symbol}: USDT 무기한 이름이 아닙니다")
    return symbol + PERP


def bn(flipster_symbol) -> str:
    """BTCUSDT.PERP -> BTCUSDT; anything that is not a USDT perpetual -> "" (never traded here)."""
    s = str(flipster_symbol or "")
    return s[:-len(PERP)] if s.endswith(SETTLE + PERP) else ""


def to_ms(v, what: str = "time") -> int:
    """A Flipster time (nanoseconds as a string; tolerant of µs / ms / s) -> ms."""
    n = int(_dec(v, what))
    if n > 10 ** 17:
        return n // 1_000_000
    if n > 10 ** 14:
        return n // 1_000
    if n > 10 ** 11:
        return n
    return n * 1000


def ns(ms: int) -> str:
    return str(int(ms) * 1_000_000)


def new_cid() -> str:
    """A client id for an order sent without one (the drill's clean-up): the ledger still records it."""
    return "pb" + hashlib.sha1(f"{time.time_ns()}|{os.getpid()}".encode()).hexdigest()[:24]


def query_string(params: dict) -> str:
    """The GET query exactly as sent and signed: sorted by name, URL-encoded, booleans as true/false."""
    items = []
    for k in sorted(params):
        v = params[k]
        if v is None:
            continue
        if v is True or v is False:
            v = "true" if v else "false"
        items.append((k, str(v)))
    return urllib.parse.urlencode(items, quote_via=urllib.parse.quote)


def body_string(body) -> str:
    """The JSON body exactly as sent and signed (compact)."""
    return json.dumps(body, separators=(",", ":"))


def signature(secret: str, method: str, path: str, expires: int, body: Optional[bytes] = None) -> str:
    """hex HMAC-SHA256(secret, METHOD + path (with "?query" as sent) + str(expires) + body bytes) (Quick Tutorial)."""
    msg = method.upper().encode() + path.encode() + str(int(expires)).encode() + (body or b"")
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def fills_from_execs(rows: list, symbol: str, reduce_ids: set) -> list:
    """Flipster TRADE executions -> Binance userTrades-like fills. Flipster's fills carry no open/close flag and no
    realized P&L: in one-way mode a fill opposite to the running position closes it, so the realized P&L is replayed
    from the fills' own prices in time order (paperbot/mexc.py fills_from_deals, quantities in the base asset). A fill
    of one of OUR reduce-only orders (``reduce_ids``, from the ledger) is a closing fill even when the list starts after
    its position opened (its realized P&L is then unknown: 0, ``realizedSource`` "unknown")."""
    deals = []
    for r in rows:
        side = r.get("side")
        if side not in ("BUY", "SELL"):
            raise TransientError(200, None, f"{symbol}: 체결 방향이 이상합니다({side!r})")
        oid = str(r.get("orderId") or "")
        if not oid or r.get("execId") in (None, ""):
            raise TransientError(200, None, f"{symbol}: 체결에 주문 번호나 체결 번호가 없습니다")
        closing = oid in reduce_ids
        code = (MX.CLOSE_SHORT if side == "BUY" else MX.CLOSE_LONG) if closing else \
            (MX.OPEN_LONG if side == "BUY" else MX.OPEN_SHORT)
        deals.append({"id": r.get("execId"), "orderId": oid, "vol": _num(_dec(r.get("lastQty"), "lastQty")),
                      "price": _num(_dec(r.get("lastPrice"), "lastPrice")), "side": code,
                      "timestamp": to_ms(r.get("transactTime"), "transactTime"), "profit": None,
                      "fee": _num(_dec(r.get("execFee"), "execFee")),
                      "feeCurrency": r.get("settlementCurrency") or SETTLE})
    out = MX.fills_from_deals(deals, 1, symbol)
    for f in out:
        f.pop("mexcSide", None)
        f.pop("mexcProfit", None)
        f["execId"] = f.pop("dealId")
        f.pop("vol", None)
        f["reduceOnly"] = f["orderId"] in reduce_ids
    return out


def permission_record(attested: bool, account_read: bool) -> dict:
    """The Binance apiRestrictions fields mainnet.check_permissions reads. Flipster reports no key permissions: reading
    the account is what this key was seen to do; "read + trade only, no withdrawal, server IP bound" is the owners'
    statement (``attested``), never assumed."""
    extra = []
    if not attested:
        extra.append(f"플립스터는 키 권한을 API로 알려 주지 않습니다. 키를 '읽기 + 거래만, 출금 없음, 서버 IP만'으로 만든 것을 "
                     f"확인한 뒤 /etc/paperbot/executor.env에 {KEY_CHECKED}={KEY_CHECKED_VALUE} 를 넣으세요")
    return {
        "enableReading": bool(account_read),
        "enableWithdrawals": False if attested else None,
        "enableFutures": bool(account_read and attested),
        "ipRestrict": True if attested else None,
        "extraProblems": extra,
        "warnings": [f"플립스터는 키 권한을 API로 알려 주지 않습니다. 확인한 것: 계정 읽기. 거래 권한·출금 없음·서버 IP "
                     f"제한은 두 분이 확인한 내용({KEY_CHECKED})입니다"] if attested else [],
        "attested": attested,
    }


# ---------------------------------------------------------------- the client-id ledger
LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS flipster_ids (
    cid TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    type TEXT NOT NULL,
    qty TEXT NOT NULL,
    reduce_only INTEGER NOT NULL,
    trig TEXT,
    sent_ms INTEGER NOT NULL,
    order_id TEXT,
    state TEXT NOT NULL,
    how TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS flipster_ids_order ON flipster_ids (order_id);
CREATE TABLE IF NOT EXISTS flipster_meta (
    k TEXT PRIMARY KEY,
    ts INTEGER NOT NULL,
    v TEXT NOT NULL
);
"""
LEDGER_COLS = ("cid", "symbol", "side", "type", "qty", "reduce_only", "trig", "sent_ms", "order_id", "state", "how",
               "note")


class IdLedger:
    """Client id -> Flipster orderId, persistent (module docstring). ``path``: the executor's own database (the tables
    flipster_ids / flipster_meta next to its record); None: memory only (the drill and check). Each read and write
    opens its own short connection and commits at once: no transaction is ever held while a request is in flight, and
    the executor's own connection (paperbot/executor.py ExecStore) can still switch the file out of WAL mode at a clean
    stop. A read that fails is an error (TransientError), never "no row"."""

    def __init__(self, path: Optional[str] = None, timeout_s: float = 2.0):
        self.path = path
        self.timeout_s = timeout_s
        self.rows: dict = {}          # cid -> row: written by this process (all rows when there is no file)
        self.meta: dict = {}
        self.failed: Optional[str] = None      # the last write that did not reach the file

    # ------------------------------------------------------------ storage
    def _write(self, sql: str, args: tuple = ()) -> bool:
        if self.path is None:
            return True
        try:
            conn = sqlite3.connect(self.path, timeout=self.timeout_s)
            try:
                conn.executescript(LEDGER_SCHEMA)
                conn.execute(sql, args)
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as e:
            self.failed = f"{type(e).__name__}: {e}"
            return False
        self.failed = None
        return True

    def _read(self, sql: str, args: tuple = ()) -> list:
        if self.path is None or not os.path.exists(self.path):
            return []
        uri = "file:" + urllib.parse.quote(os.path.abspath(self.path)) + "?mode=rw"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=self.timeout_s)
            try:
                return conn.execute(sql, args).fetchall()
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return []
            raise TransientError(0, None, f"주문 장부(flipster_ids)를 읽지 못했습니다: {e}") from e
        except sqlite3.Error as e:
            raise TransientError(0, None, f"주문 장부(flipster_ids)를 읽지 못했습니다: {e}") from e

    @staticmethod
    def _row(t) -> dict:
        r = dict(zip(LEDGER_COLS, t))
        r["reduce_only"] = bool(r["reduce_only"])
        r["sent_ms"] = int(r["sent_ms"])
        return r

    # ------------------------------------------------------------ rows
    def put(self, cid: str, symbol: str, side: str, otype: str, qty: str, reduce_only: bool, trig: Optional[str],
            sent_ms: int) -> bool:
        """The intent row, before the order is sent. True when it is durable (or there is no file to write)."""
        row = {"cid": cid, "symbol": symbol, "side": side, "type": otype, "qty": str(qty),
               "reduce_only": bool(reduce_only), "trig": trig, "sent_ms": int(sent_ms), "order_id": None,
               "state": "sent", "how": None, "note": None}
        self.rows[cid] = row
        self.trim(sent_ms)
        return self._write("INSERT OR REPLACE INTO flipster_ids (cid, symbol, side, type, qty, reduce_only, trig, "
                           "sent_ms, order_id, state, how, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           tuple(row[k] if k != "reduce_only" else int(row[k]) for k in LEDGER_COLS))

    def bind(self, cid: str, order_id: str, how: str = "answer") -> bool:
        row = self.get(cid)
        if row is not None:
            self.rows[cid] = {**row, "order_id": str(order_id), "state": "placed", "how": how}
        return self._write("UPDATE flipster_ids SET order_id = ?, state = 'placed', how = ? WHERE cid = ?",
                           (str(order_id), how, cid))

    def refused(self, cid: str, why: str) -> bool:
        """The exchange refused the order: nothing was placed (a look-up answers "not found" at once)."""
        row = self.get(cid)
        if row is not None:
            self.rows[cid] = {**row, "state": "refused", "note": why[:200]}
        return self._write("UPDATE flipster_ids SET state = 'refused', note = ? WHERE cid = ?", (why[:200], cid))

    def forget_order(self, cid: str) -> None:
        """Drill only: the row as if the order's answer had been lost (its orderId unknown)."""
        row = self.get(cid)
        if row is not None:
            self.rows[cid] = {**row, "order_id": None, "state": "sent", "how": None}
        self._write("UPDATE flipster_ids SET order_id = NULL, state = 'sent', how = NULL WHERE cid = ?", (cid,))

    def get(self, cid: str) -> Optional[dict]:
        if cid in self.rows:
            return dict(self.rows[cid])
        got = self._read(f"SELECT {', '.join(LEDGER_COLS)} FROM flipster_ids WHERE cid = ?", (cid,))
        return self._row(got[0]) if got else None

    def by_order(self, order_id) -> Optional[dict]:
        oid = str(order_id)
        hit = next((r for r in self.rows.values() if r.get("order_id") == oid), None)
        if hit is not None:
            return dict(hit)
        got = self._read(f"SELECT {', '.join(LEDGER_COLS)} FROM flipster_ids WHERE order_id = ?", (oid,))
        return self._row(got[0]) if got else None

    def reduce_only_ids(self, order_ids) -> set:
        """Which of these orderIds are our reduce-only orders (closes, stops)."""
        ids = {str(x) for x in order_ids}
        out = {r["order_id"] for r in self.rows.values() if r.get("order_id") in ids and r.get("reduce_only")}
        rest = sorted(ids - out)
        for i in range(0, len(rest), 400):
            part = rest[i:i + 400]
            marks = ",".join("?" * len(part))
            out |= {str(t[0]) for t in self._read(
                f"SELECT order_id FROM flipster_ids WHERE reduce_only = 1 AND order_id IN ({marks})", tuple(part))}
        return out

    def trim(self, now_ms: int) -> None:
        cut = int(now_ms) - LEDGER_KEEP_MS
        for cid in [c for c, r in self.rows.items() if r["sent_ms"] < cut]:
            self.rows.pop(cid, None)
        self._write("DELETE FROM flipster_ids WHERE sent_ms < ?", (cut,))

    def put_meta(self, k: str, v: str, ts: int) -> bool:
        self.meta[k] = v
        return self._write("INSERT OR REPLACE INTO flipster_meta (k, ts, v) VALUES (?,?,?)", (k, int(ts), str(v)))

    def get_meta(self, k: str) -> Optional[str]:
        if k in self.meta:
            return self.meta[k]
        got = self._read("SELECT v FROM flipster_meta WHERE k = ?", (k,))
        return str(got[0][0]) if got else None


# ---------------------------------------------------------------- client
class FlipsterClient:
    """Signed REST client for Flipster USDT perpetuals, real money only. Answers are translated into the Binance
    client's shapes (see the module docstring)."""
    __test__ = False
    HOSTS: tuple = FLIPSTER_HOSTS
    DEFAULT_BASE = FLIPSTER_BASE
    KEY_NAMES = LIVE_KEY_NAMES
    AGENT = "paperbot-flipster-live/0.1"
    EXCHANGE = "flipster"
    PNL_RECORD = "플립스터 지갑 변화"
    # a stop bigger than the position is replaced by one of the position's size (the executor's _cover)
    EXACT_STOP_SIZE = True
    # the executor adds a random part to its stop and close ids: a ledger row is never reused
    UNIQUE_CLIENT_IDS = True

    def __init__(self, api_key: str, api_secret: str, base: Optional[str] = None, send=None,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                 on_request: Optional[Callable[[dict], None]] = None, sleep: Callable[[float], None] = time.sleep,
                 ledger: Optional[IdLedger] = None):
        base = (base or self.DEFAULT_BASE).rstrip("/")
        u = urllib.parse.urlparse(base)
        host = u.hostname or ""
        if host not in type(self).HOSTS or u.scheme != "https" or u.path not in ("",) or u.port not in (None, 443):
            raise ValueError(f"refusing {base!r}: {type(self).__name__} only talks to https://{type(self).HOSTS}")
        if not (api_key and api_secret):
            raise ValueError(f"{self.KEY_NAMES[0]} and {self.KEY_NAMES[1]} are required")
        self.base, self.host, self.key, self.secret = base, host, api_key, api_secret
        self.send = send or urllib_send
        self.clock_ms = clock_ms
        self.sleep = sleep
        self.offset_ms = 0
        self.time_source = "local"
        self.on_request = on_request
        self.ledger = ledger if ledger is not None else IdLedger(None)
        self.specs: dict = {}            # BTCUSDT -> spec (live contract info, cached for the process)
        self.contract_ms: Optional[int] = None
        self.hits: list = []             # request times (ms) in the longest rate window
        self.rate_answers = 0            # 429 answers seen (the drill reports them)
        self.order_symbol: dict = {}     # orderId -> symbol (a cancel needs the symbol)
        self.lev: dict = {}              # symbol -> leverage set by leverage() / isolated()
        self.lev_unverified: set = set()  # symbols whose leverage the exchange showed no row for (the drill checks)
        self.trade_mode: Optional[str] = None
        self.trade_mode_source = ""
        self.balance_cache: Optional[tuple] = None
        self.kline_source = "kline"

    # ------------------------------------------------------------ transport
    def _now(self) -> int:
        return int(self.clock_ms() + self.offset_ms)

    def _recent(self, window_ms: int) -> list:
        now = self.clock_ms()
        return [t for t in self.hits if now - t < window_ms]

    def _pace(self) -> None:
        """Never past the client's own request budget (RATE_WINDOWS): wait until the oldest request of a full window
        leaves it."""
        for window, limit in RATE_WINDOWS:
            lst = self._recent(window)
            if len(lst) >= limit:
                wait = (min(lst) + window - self.clock_ms()) / 1000.0
                if wait > 0:
                    self.sleep(min(wait, window / 1000.0))
        longest = max(w for w, _ in RATE_WINDOWS)
        self.hits = self._recent(longest) + [self.clock_ms()]

    def throttle_s(self, share: float = 0.8) -> float:
        """Seconds to wait before the next loop: a window that used ``share`` of its budget waits for its oldest
        request to leave it."""
        now = self.clock_ms()
        wait = 0.0
        for window, limit in RATE_WINDOWS:
            recent = self._recent(window)
            if len(recent) >= share * limit:
                wait = max(wait, (min(recent) + window - now) / 1000.0)
        return max(0.0, min(wait, 60.0))

    def _expires(self) -> int:
        return self._now() // 1000 + EXPIRES_S

    def req(self, method: str, path: str, params=None, limit_key: Optional[str] = None):
        """One signed request. ``params``: the GET query or the JSON body. A read (GET) refused for the rate (429) is
        read again after Retry-After (at most READ_RETRIES times); so is a RETRY_WRITES write. Any other write is never
        sent again here (the executor decides)."""
        for attempt in range(READ_RETRIES + 1):
            try:
                return self._req_once(method, path, params, limit_key)
            except RateLimited as e:
                again = method == "GET" or (limit_key or "") in RETRY_WRITES
                if not again or e.status != 429 or attempt == READ_RETRIES:
                    raise
                self.sleep(min(max(float(getattr(e, "retry_after", 0) or 0), READ_PAUSE_S * (attempt + 1)), 5.0))
        raise AssertionError("unreachable")

    def _req_once(self, method: str, path: str, params=None, limit_key: Optional[str] = None):
        audit = {"method": method, "path": path, "params": dict(params or {})}
        headers = {"User-Agent": self.AGENT, "Accept": "application/json"}
        target, body = path, None
        if method == "GET":
            q = query_string(params or {})
            target = f"{path}?{q}" if q else path
        else:
            body_obj = {k: v for k, v in (params or {}).items() if v is not None}
            audit["params"] = dict(body_obj)
            body = body_string(body_obj).encode()
            headers["Content-Type"] = "application/json"
        expires = self._expires()
        headers.update({"api-key": self.key, "api-expires": str(expires),
                        "api-signature": signature(self.secret, method, target, expires, body)})
        self._pace()
        try:
            res = self.send(method, f"{self.base}{target}", headers, body)
        except (OSError, http.client.HTTPException) as e:
            err = TransientError(0, None, f"network: {type(e).__name__}: {e}")
            self._audit(audit, err=err)
            raise err from e
        status, raw = res[0], res[1]
        hdr = {k.lower(): v for k, v in (res[2] if len(res) > 2 else {}).items()}
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = None
        err: Optional[TestnetError] = None
        if status >= 500 or status in (0, 408):
            # a server error: the request may have run (an order is looked up, never resent)
            err = TransientError(status, None, f"server error {status}: {str((raw or b'')[:200])}")
        elif status == 429:
            self.rate_answers += 1
            try:
                after = float(hdr.get("retry-after") or 1.0)
            except ValueError:
                after = 1.0
            err = RateLimited(429, None, f"rate limited: {str((raw or b'')[:200])}", after)
        elif status != 200 or (isinstance(data, dict) and isinstance(data.get("error"), dict)):
            err = self._error(status, data, raw)
        elif data is None:
            err = TransientError(status, None, f"응답이 JSON이 아닙니다: {str((raw or b'')[:200])}")
        self._audit(audit, status=status, data=data, err=err)
        if err is not None:
            raise err
        return data

    def _error(self, status: int, data, raw) -> TestnetError:
        e = data.get("error") if isinstance(data, dict) else None
        e = e if isinstance(e, dict) else {}
        etype, code = str(e.get("type") or ""), e.get("code")
        msg = str(e.get("message") or "") or str((raw or b"")[:200])
        text = f"{msg} (플립스터 HTTP {status} {etype or '-'}{'' if code is None else f' {code}'})"
        low = f"{etype} {msg}".lower().replace("_", "")
        if any(w in low for w in EXPIRED_WORDS):
            err = TestnetError(400, BAD_TIMESTAMP, text)       # expired / clock: refused, not executed
        elif REMAINING.lower() in low.replace(" ", ""):
            err = TestnetError(400, REMAINING_CODE, text)
        elif status == 404 or ("order" in low and any(w in low for w in NOT_FOUND_WORDS)):
            err = TestnetError(404, NOT_FOUND[0], text)
        elif status in (403, 418):
            # an IP block or a key without the permission: never retried in the request, the loop waits (the
            # executor's 418 ban handling)
            err = RateLimited(418, code, f"HTTP {status} (허용 안 된 IP·권한 없는 키·차단): {text}"[:300], 300.0)
        elif status == 401:
            err = TestnetError(401, "AUTH", f"키·서명이 거절됐습니다: {text}")
        else:
            err = TestnetError(status if status and status != 200 else 400,
                               code if code is not None else (etype or None), text)
        err.flipster_type = etype
        return err

    def _audit(self, audit: dict, status: int = 0, data=None, err: Optional[Exception] = None) -> None:
        if self.on_request is None:
            return
        audit.update(status=getattr(err, "status", status), error=None if err is None else str(err),
                     code=getattr(err, "code", None), data=data)
        try:
            self.on_request(audit)
        except Exception:  # noqa: BLE001  (an audit failure must not change order handling)
            pass

    # ------------------------------------------------------------ market data
    def sync_time(self) -> int:
        """The server clock (GET /api/v1/public/time, nanoseconds): api-expires is counted on it. A refused answer: the
        local clock (chrony); a garbled one is an error."""
        t0 = self.clock_ms()
        try:
            data = self.req("GET", API + "/public/time", limit_key="time")
        except (TransientError, RateLimited):
            raise
        except TestnetError:
            self.offset_ms, self.time_source = 0, "local"
            return 0
        t1 = self.clock_ms()
        server = to_ms((data or {}).get("serverTime") if isinstance(data, dict) else None, "serverTime")
        self.offset_ms = server - (t0 + t1) // 2
        self.time_source = API + "/public/time"
        return self.offset_ms

    def _load_contracts(self) -> None:
        now = self.clock_ms()
        if self.contract_ms is not None and now - self.contract_ms < 5_000:
            return
        data = self.req("GET", API + "/market/contract", limit_key="contract")
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else None
        if rows is None:
            raise TransientError(200, None, f"계약 정보 응답이 이상합니다: {str(data)[:80]!r}")
        tradable = self.req("GET", API + "/trade/symbol", limit_key="symbols")
        perps = (tradable or {}).get("perpetualSwap") if isinstance(tradable, dict) else None
        if not isinstance(perps, list):
            raise TransientError(200, None, f"거래 가능 종목 응답이 이상합니다: {str(tradable)[:80]!r}")
        self.contract_ms = now
        perps = {str(p) for p in perps}
        for row in rows:
            if not isinstance(row, dict) or row.get("quoteCurrency") != SETTLE or not bn(row.get("symbol")):
                continue
            try:
                self.specs[bn(row["symbol"])] = self._spec_row(row, str(row["symbol"]) in perps)
            except TestnetError:
                continue                                   # a contract with garbled units is never traded

    @staticmethod
    def _spec_row(row: dict, tradable: bool) -> dict:
        step, tick = _dec(row.get("unitOrderQty"), "unitOrderQty"), _dec(row.get("tickSize"), "tickSize")
        lev = _dec(row.get("maxLeverage"), "maxLeverage")
        if step <= 0 or tick <= 0 or lev <= 0:
            raise TestnetError(400, "BAD_SPEC", f"{row.get('symbol')}: 계약 단위 정보가 이상합니다")
        mn = row.get("notionalMinOrderAmount")
        mx = row.get("notionalMaxOrderAmount")
        return {"qty_step": float(step), "min_qty": float(step), "tick": float(tick),
                "min_notional": float(_dec(mn, "notionalMinOrderAmount")) if mn not in (None, "") else 0.0,
                "max_notional": float(_dec(mx, "notionalMaxOrderAmount")) if mx not in (None, "") else None,
                "max_leverage": float(lev), "status": "Trading" if tradable else "NOT_TRADABLE",
                "tradable": tradable, "tick_str": _num(tick), "qty_step_str": _num(step),
                "funding_interval_hours": row.get("fundingIntervalHours"),
                "init_margin_rate": row.get("initMarginRate"), "maint_margin_rate": row.get("maintMarginRate"),
                "min_notional_known": mn not in (None, "")}

    def spec(self, symbol: str) -> dict:
        """The contract's live spec (cached): qty_step = unitOrderQty (also the smallest order), tick = tickSize,
        min_notional = notionalMinOrderAmount, status "Trading" only when the symbol is in the tradable list."""
        if symbol not in self.specs:
            self._load_contracts()
        if symbol not in self.specs:
            raise TestnetError(400, "NO_SYMBOL", f"{symbol}: 플립스터 USDT 무기한 계약에 없습니다")
        return dict(self.specs[symbol])

    def _spec(self, symbol: str) -> dict:
        return self.specs.get(symbol) or self.spec(symbol)

    def _qty(self, symbol: str, qty: float) -> Decimal:
        """A base quantity on the step, floored (never more than asked)."""
        step = Decimal(self._spec(symbol)["qty_step_str"])
        n = (Decimal(repr(float(qty))) / step + Decimal("1e-9")).to_integral_value(rounding=ROUND_FLOOR)
        return n * step

    def _check_qty(self, symbol: str, q: Decimal, qty: float, what: str) -> None:
        if q <= 0:
            raise TestnetError(400, "QTY_ZERO", f"{symbol}: {what} 수량 {qty}이 최소 단위 "
                                                f"{self._spec(symbol)['qty_step_str']}보다 작습니다")

    def ticker(self, symbol: str) -> dict:
        data = self.req("GET", API + "/market/ticker", {"symbol": fx(symbol)}, limit_key="ticker")
        rows = data if isinstance(data, list) else [data]
        row = next((r for r in rows if isinstance(r, dict) and r.get("symbol") == fx(symbol)), None)
        if row is None:
            raise TransientError(200, None, f"{symbol}: 시세가 비어 있습니다")
        return row

    def price(self, symbol: str) -> float:
        """Last traded price."""
        return float(_dec(self.ticker(symbol).get("lastPrice"), "lastPrice"))

    def mark(self, symbol: str) -> float:
        return float(_dec(self.ticker(symbol).get("markPrice"), "markPrice"))

    def klines(self, symbol: str, start_ms: int, end_ms: int) -> list:
        """1m candles opened in [start_ms, end_ms], the one still forming included: [(open ms, high, low, close)],
        oldest first. GET /api/v1/market/kline interval "1", startTime / endTime required (nanoseconds), at most 1000
        rows a request (read in pieces of 1000 minutes). The docs do not say whose price the candles are of; the drill
        compares the newest close with the ticker's last price."""
        lo = int(start_ms) - int(start_ms) % 60_000
        out = {}
        a = lo
        while a <= int(end_ms):
            b = min(int(end_ms), a + (KLINE_ROWS - 1) * 60_000)
            data = self.req("GET", API + "/market/kline", {"symbol": fx(symbol), "interval": "1", "startTime": ns(a),
                                                          "endTime": ns(max(b, a + 1)), "limit": KLINE_ROWS},
                            limit_key="kline")
            if not isinstance(data, list):
                raise TransientError(200, None, f"{symbol}: 1분봉 응답이 목록이 아닙니다 {str(data)[:80]!r}")
            for r in data:
                if not isinstance(r, (list, tuple)) or len(r) < 5:
                    raise TransientError(200, None, f"{symbol}: 1분봉 응답의 모양이 다릅니다")
                ms = to_ms(r[0], "kline startTime")
                if lo <= ms <= int(end_ms):
                    out[ms] = (ms, float(_dec(r[2], "high")), float(_dec(r[3], "low")), float(_dec(r[4], "close")))
            a = b + 60_000
        return [out[k] for k in sorted(out)]

    def leverage_brackets(self) -> list:
        """Signal mode needs Binance-like notional brackets: not offered (the executor follows the paper position)."""
        raise TestnetError(400, "NO_BRACKETS", "플립스터는 빠른 진입(signal) 크기 계산용 레버리지 구간을 주지 않습니다")

    # ------------------------------------------------------------ account
    def _assets(self) -> list:
        now = self.clock_ms()
        if self.balance_cache is not None and now - self.balance_cache[0] < BALANCE_CACHE_MS:
            return self.balance_cache[1]
        data = self.req("GET", API + "/account/balance", limit_key="balance")
        if not isinstance(data, list):
            raise TransientError(200, None, f"잔고 응답이 목록이 아닙니다: {str(data)[:80]!r}")
        out = []
        for r in data:
            if not isinstance(r, dict) or not r.get("asset"):
                raise TransientError(200, None, "잔고 응답의 모양이 다릅니다")
            out.append({"asset": str(r["asset"]), "walletBalance": _num(_dec(r.get("balance"), "balance")),
                        "availableBalance": str(r.get("availableBalance"))})
        self.balance_cache = (now, out)
        return out

    def account(self) -> dict:
        """GET /api/v1/account: wallet, unrealized P&L, equity (totalMarginBalance), available; never $0 from a gap."""
        data = self.req("GET", API + "/account", limit_key="account")
        if not isinstance(data, dict):
            raise TransientError(200, None, f"계정 응답이 이상합니다: {str(data)[:80]!r}")
        wallet = _dec(data.get("totalWalletBalance"), "totalWalletBalance")
        unreal = _dec(data.get("totalUnrealizedPnl"), "totalUnrealizedPnl")
        equity = _dec(data.get("totalMarginBalance"), "totalMarginBalance")
        avail = _dec(data.get("availableBalance"), "availableBalance")
        return {"totalWalletBalance": _num(wallet), "totalUnrealizedProfit": _num(unreal),
                "totalMarginBalance": _num(equity), "availableBalance": _num(avail),
                "positionMargin": str(data.get("totalMarginReserved") or "0"), "assets": self._assets()}

    def fee_rate(self, symbol: Optional[str] = None) -> dict:
        """GET /api/v1/market/fee-rate: a list of fee levels {level, requiredTradeVolume, requiredAssetBalance,
        feeRate}. The docs call it the account's rates but name no field that marks the account's own level and do
        not say whether feeRate is a fraction or a percent: the lowest level's value is answered as both rates, with
        every level (``levels``); the drill compares it with the fee measured on its fills."""
        data = self.req("GET", API + "/market/fee-rate", limit_key="fee_rate")
        rows = [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
        if not rows:
            raise TransientError(200, None, f"수수료율 응답이 이상합니다: {str(data)[:80]!r}")
        first = min(rows, key=lambda r: _int(r.get("level")))
        rate = float(_dec(first.get("feeRate"), "feeRate"))
        return {"taker": rate, "maker": rate, "level": first.get("level"), "rows": len(rows),
                "levels": [(r.get("level"), r.get("feeRate")) for r in rows][:10]}

    def one_way(self) -> None:
        """One-way trade mode (the executor's Binance assumption). The API has no read of the mode: PUT ONE_WAY and its
        answer must say ONE_WAY (recorded in the ledger's flipster_meta). The docs refuse the switch while a position is
        open (RemainingPositionsExist): then this executor's own earlier confirmation (the record) is accepted when no
        coin shows more than one position; without one: Refused (the executor does not start)."""
        try:
            data = self.req("PUT", API + "/account/trade-mode", {"tradeMode": ONE_WAY}, limit_key="trade_mode")
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            if e.code != REMAINING_CODE:
                raise Refused(f"플립스터 거래 모드를 단방향(ONE_WAY)으로 바꿀 수 없어 거래하지 않습니다: {e.msg}") from e
            seen = self.ledger.get_meta("trade_mode")
            if seen == ONE_WAY:
                self._position_rows(None)                  # more than one position on a coin raises
                self.trade_mode, self.trade_mode_source = ONE_WAY, "record"
                return
            raise Refused("플립스터 포지션이 열려 있어 거래 모드를 단방향(ONE_WAY)으로 맞추지 못했고, 이 실행기가 단방향을 "
                          "확인한 기록도 없습니다. 앱에서 포지션을 정리한 뒤 다시 켜세요") from e
        mode = data.get("tradeMode") if isinstance(data, dict) else None
        if mode != ONE_WAY:
            raise Refused(f"플립스터 거래 모드 답이 단방향(ONE_WAY)이 아닙니다({mode!r}). 거래하지 않습니다")
        self.trade_mode, self.trade_mode_source = ONE_WAY, "answer"
        self.ledger.put_meta("trade_mode", ONE_WAY, self._now())

    def _settings(self, symbol: str, answer=None) -> Optional[dict]:
        """The coin's leverage and margin type as Flipster shows them: the leverage answer's position row, else the
        position list's row (open or not). None: no row shows it."""
        if isinstance(answer, dict) and isinstance(answer.get("position"), dict) \
                and answer["position"].get("symbol") == fx(symbol):
            return answer["position"]
        data = self.req("GET", API + "/account/position", {"symbol": fx(symbol)}, limit_key="position")
        if not isinstance(data, list):
            raise TransientError(200, None, f"{symbol}: 포지션 응답이 목록이 아닙니다")
        return next((r for r in data if isinstance(r, dict) and r.get("symbol") == fx(symbol)), None)

    @staticmethod
    def _lev_ok(row: dict, lev: int) -> bool:
        return _int(row.get("leverage")) == lev and str(row.get("marginType") or "").upper() == ISOLATED

    def _set_leverage(self, symbol: str, lev: int) -> None:
        """Isolated ``lev``, then read back. A row that shows it already: nothing is sent. No row shows the setting
        after the answer: accepted on the answer (``lev_unverified``; the drill checks it on its position)."""
        row = self._settings(symbol)
        if row is not None and self._lev_ok(row, lev):
            self.lev_unverified.discard(symbol)
            return
        ans = self.req("POST", API + "/trade/leverage", {"symbol": fx(symbol), "leverage": int(lev),
                                                         "marginType": ISOLATED}, limit_key="leverage_set")
        row = self._settings(symbol, ans)
        if row is None:
            self.lev_unverified.add(symbol)
            return
        if not self._lev_ok(row, lev):
            raise TestnetError(400, "LEVERAGE_MISMATCH", f"{symbol}: 격리 {lev}배로 맞추지 못했습니다(읽은 값 "
                                                         f"{row.get('marginType')} {row.get('leverage')})")
        self.lev_unverified.discard(symbol)

    def isolated(self, symbol: str) -> None:
        """Isolated margin with the owners' leverage (BTC 40x, others 30x), read back. A position open on the symbol:
        TestnetError -4048 unless it is isolated already (the executor warns and keeps protecting it). Not possible
        otherwise: Refused (the executor does not start)."""
        sp = self._spec(symbol)
        rows = self._position_rows(symbol)
        if rows:
            if str(rows[0].get("marginType") or "").upper() == ISOLATED:
                return None
            raise TestnetError(400, -4048, f"{symbol}: 교차(cross) 포지션이 열려 있어 격리로 맞추지 못했습니다")
        lev = int(min(FIXED_LEVERAGE.get(symbol, DEFAULT_LEVERAGE), sp.get("max_leverage") or 10 ** 6))
        try:
            self._set_leverage(symbol, lev)
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            raise Refused(f"플립스터 {symbol}을 격리 {lev}배로 맞출 수 없어 거래하지 않습니다: {e.msg}") from e
        self.lev[symbol] = lev

    def leverage(self, symbol: str, lev: int) -> dict:
        """Set the symbol's isolated leverage and read it back. Refused (TestnetError) unless this process confirmed
        one-way mode and the contract is tradable: the executor never opens a position otherwise."""
        lev = int(lev)
        sp = self._spec(symbol)
        if sp.get("max_leverage") and lev > sp["max_leverage"]:
            raise TestnetError(400, "LEVERAGE_MAX", f"{symbol}: 레버리지 {lev}배가 최대 {sp['max_leverage']:g}배를 넘습니다")
        if not sp.get("tradable"):
            raise TestnetError(400, "NOT_TRADING", f"{symbol}: API 거래 가능 종목이 아니라 거래하지 않습니다")
        if self.trade_mode != ONE_WAY:
            raise TestnetError(400, "NOT_ONE_WAY", "플립스터 거래 모드가 단방향(ONE_WAY)으로 확인되지 않아 진입하지 않습니다")
        rows = self._position_rows(symbol)
        if rows:
            if self._lev_ok(rows[0], lev):
                self.lev[symbol] = lev
                return {"symbol": symbol, "leverage": lev, "marginType": "isolated"}
            raise TestnetError(400, "POSITION_OPEN", f"{symbol}: 포지션이 있어 레버리지를 바꾸지 않습니다")
        self._set_leverage(symbol, lev)
        self.lev[symbol] = lev
        return {"symbol": symbol, "leverage": lev, "marginType": "isolated",
                "verified": symbol not in self.lev_unverified}

    def account_setup(self, symbols) -> list:
        """(ok, Korean text) lines for preflight, reads only: the trade mode on record, each coin's contract and
        leverage as Flipster shows them."""
        seen = self.ledger.get_meta("trade_mode")
        out = [(True, "거래 모드: API로 읽을 수 없음. 실행기가 켤 때 단방향(ONE_WAY)으로 맞추고 답을 확인합니다"
                + (" (이 실행기 기록: 단방향 확인됨)" if seen == ONE_WAY else ""))]
        for s in symbols:
            sp = self._spec(s)
            row = self._settings(s)
            lev = f"{row.get('marginType')} {row.get('leverage')}" if row else "?(포지션 목록에 줄 없음)"
            out.append((bool(sp.get("tradable")),
                        f"{s}: {'API 거래 가능' if sp.get('tradable') else 'API 거래 불가'}, 수량 단위 {sp['qty_step_str']}, "
                        f"가격 단위 {sp['tick_str']}, 최소 주문 ${sp['min_notional']:g}, 최대 {sp['max_leverage']:g}배, "
                        f"지금 레버리지 {lev}"))
        return out

    # ------------------------------------------------------------ order records
    @staticmethod
    def _need(row: dict, key: str, what: str):
        v = row.get(key)
        if v in (None, ""):
            raise TransientError(200, None, f"{what}에 {key} 값이 없습니다")
        return v

    def _pending(self, symbol: Optional[str]) -> list:
        """Pending orders (one symbol or all). The answer must carry its list: never "none" from a missing one."""
        data = self.req("GET", ORDER, {"symbol": fx(symbol)} if symbol else None, limit_key="pending")
        rows = data.get("orders") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise TransientError(200, None, f"대기 주문 응답이 목록이 아닙니다: {str(data)[:80]!r}")
        out = []
        for r in rows:
            if not isinstance(r, dict) or r.get("orderId") in (None, "") or not r.get("orderType"):
                raise TransientError(200, None, "대기 주문 응답의 모양이 다릅니다")
            if symbol and r.get("symbol") != fx(symbol):
                continue
            if bn(r.get("symbol")):
                self.order_symbol[str(r["orderId"])] = bn(r["symbol"])
                out.append(r)
        return out

    def _pages(self, path: str, params: dict, lo_ms: int, hi_ms: int, what: str, depth: int = 0,
               budget: Optional[list] = None) -> list:
        """A history (orders or executions) in [lo_ms, hi_ms]: one page, or (hasNext: more than one page) the window
        read again in two halves, never past a cursor whose meaning the docs leave open. At most HISTORY_REQUESTS
        requests (a server that ignored the time filter would otherwise split forever): past that, an error."""
        budget = [HISTORY_REQUESTS] if budget is None else budget
        if budget[0] <= 0:
            raise TransientError(0, None, f"{what}: 기록이 너무 많아 나눠 읽지 못했습니다(요청 {HISTORY_REQUESTS}번)")
        budget[0] -= 1
        p = {**params, "startTime": ns(lo_ms), "endTime": ns(hi_ms)}
        data = self.req("GET", path, p, limit_key=what)
        rows = data.get("history") if isinstance(data, dict) else None
        more = data.get("hasNext") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not isinstance(more, bool):
            raise TransientError(200, None, f"{what} 응답이 이상합니다: {str(data)[:80]!r}")
        if more:
            if depth >= HISTORY_DEPTH or hi_ms - lo_ms < 2:
                raise TransientError(0, None, f"{what}: 기록이 너무 많아 나눠 읽지 못했습니다")
            mid = (lo_ms + hi_ms) // 2
            return self._pages(path, params, lo_ms, mid, what, depth + 1, budget) + \
                self._pages(path, params, mid + 1, hi_ms, what, depth + 1, budget)
        return [r for r in rows if isinstance(r, dict)]

    def _history(self, symbol: str, lo_ms: int, hi_ms: int) -> list:
        return self._pages(ORDER + "/history", {"productType": "PERPETUAL", "symbol": fx(symbol)}, lo_ms, hi_ms,
                           "order_history")

    def _execs(self, symbol: Optional[str], lo_ms: int, hi_ms: int, order_id=None,
               exec_type: Optional[str] = None) -> list:
        p = {"productType": "PERPETUAL"}
        if symbol:
            p["symbol"] = fx(symbol)
        if order_id is not None:
            p["orderId"] = str(order_id)
        if exec_type:
            p["execType"] = exec_type
        rows = self._pages(API + "/trade/execution/history", p, lo_ms, hi_ms, "executions")
        seen, out = set(), []
        for r in rows:
            if symbol and r.get("symbol") != fx(symbol):
                continue
            if order_id is not None and str(r.get("orderId")) != str(order_id):
                continue
            if exec_type and r.get("execType") != exec_type:
                continue                                   # a server that ignores the filter: never another kind
            k = str(r.get("execId"))
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    def _window(self, sent_ms: Optional[int]) -> tuple:
        now = self._now()
        lo = (sent_ms - MATCH_BEFORE_MS - 10_000) if sent_ms else now - HISTORY_SPAN_MS
        return lo, now + 5_000

    def _record(self, symbol: str, oid: str, sent_ms: Optional[int]) -> Optional[dict]:
        """The order's row: the pending list, else the order history."""
        row = next((r for r in self._pending(symbol) if str(r.get("orderId")) == oid), None)
        if row is not None:
            return row
        lo, hi = self._window(sent_ms)
        return next((r for r in self._history(symbol, lo, hi) if str(r.get("orderId")) == oid), None)

    def _fills_of(self, symbol: str, oid: str, sent_ms: Optional[int]) -> list:
        lo, hi = self._window(sent_ms)
        return self._execs(symbol, lo, hi, order_id=oid, exec_type="TRADE")

    def _compose(self, symbol: str, oid: str, row: Optional[dict], record: Optional[dict], fills: list) -> dict:
        """One order in the Binance shape. Executed quantity, average price and fee from its TRADE executions; the
        record's (answer's) filled amount stands in while they lag. Status: never from the record's status alone (a
        market order is IOC: CANCELED with part filled)."""
        rec = record or {}
        sp = self._spec(symbol)
        half = Decimal(sp["qty_step_str"]) / 2
        orig = _dec(row["qty"], "qty") if row else _dec(rec.get("quantity"), "quantity")
        raw = str(rec.get("status") or "")
        if record is not None and raw not in OPEN_STATUS + FINAL_STATUS:
            raise TransientError(200, None, f"주문 상태가 이상합니다({rec.get('status')!r})")
        ex_q = sum((_dec(f.get("lastQty"), "lastQty") for f in fills), Decimal(0))
        ex_n = sum((_dec(f.get("lastQty"), "lastQty") * _dec(f.get("lastPrice"), "lastPrice") for f in fills),
                   Decimal(0))
        fee = sum((_dec(f.get("execFee"), "execFee") for f in fills), Decimal(0))
        if rec.get("cumQty") not in (None, ""):
            rec_q = _dec(rec.get("cumQty"), "cumQty")
        elif raw in ("FILLED", "CANCELED") and rec.get("quantity") not in (None, ""):
            # the order answer of a final market (IOC) order: ``quantity`` is the filled amount (Place Order docs)
            rec_q = _dec(rec.get("quantity"), "quantity")
        else:
            rec_q = Decimal(0)
        lag = ex_q + half < rec_q
        executed = rec_q if lag else ex_q
        if fills and not lag:
            avg = ex_n / ex_q if ex_q > 0 else Decimal(0)
        elif executed > 0 and rec.get("avgPrice") not in (None, ""):
            avg = _dec(rec.get("avgPrice"), "avgPrice")
        else:
            avg = Decimal(0)
        final = raw in FINAL_STATUS or (not record and ex_q > 0 and ex_q + half >= orig)
        if raw == "REJECTED" and executed == 0:
            status = "REJECTED"
        elif final and executed + half >= orig:
            status = "FILLED"
        elif final:
            status = "CANCELED"                            # IOC: the unfilled part was cancelled (part may be filled)
        else:
            status = "PARTIALLY_FILLED" if executed > 0 else "NEW"
        side = (row or {}).get("side") or rec.get("side")
        otype = (row or {}).get("type") or rec.get("orderType")
        out = {"orderId": oid, "clientOrderId": (row or {}).get("cid") or "", "symbol": symbol, "side": side,
               "type": otype, "origQty": _num(orig), "executedQty": _num(executed),
               "avgPrice": _num(avg) if executed > 0 and avg > 0 else "0", "status": status,
               "reduceOnly": bool((row or {}).get("reduce_only")), "commission": _num(fee),
               "fills": len(fills), "flipsterStatus": raw or None,
               "time": to_ms(rec["orderTime"]) if rec.get("orderTime") not in (None, "") else None}
        if lag:
            out["readBack"] = "체결 기록이 아직 주문 기록보다 적습니다(주문 기록의 체결량을 씀)"
        return out

    def _by_id(self, symbol: str, oid: str, row: Optional[dict]) -> dict:
        """An order by its orderId (any state). Not anywhere: TestnetError -2013, unless it is one we placed (the
        ledger has its orderId): an accepted order is never reported as not executed (TransientError)."""
        sent = row["sent_ms"] if row else None
        record = self._record(symbol, oid, sent)
        fills = self._fills_of(symbol, oid, sent)
        if record is None and not fills:
            if row is not None:
                raise TransientError(200, None, f"주문 {oid}이 플립스터 기록에 아직 안 보입니다(접수된 주문: 결과 확인 중)")
            raise TestnetError(404, NOT_FOUND[0], "Order does not exist.")
        return self._compose(symbol, oid, row, record, fills)

    # ------------------------------------------------------------ the ledger look-up
    def _matches(self, r: dict, row: dict) -> bool:
        if r.get("side") != row["side"] or r.get("orderType") != row["type"] or bn(r.get("symbol")) != row["symbol"]:
            return False
        half = Decimal(self._spec(row["symbol"])["qty_step_str"]) / 2
        want = Decimal(row["qty"])
        try:
            q = Decimal(str(r.get("quantity")))
        except (InvalidOperation, ValueError):
            return False
        if abs(q - want) > half and not (row["type"] == MARKET and r.get("status") == "CANCELED" and q <= want + half):
            return False
        if row["type"] == STOP:
            tick = Decimal(self._spec(row["symbol"])["tick_str"])
            trig = r.get("triggerPrice") if r.get("triggerPrice") not in (None, "") else r.get("price")
            try:
                if abs(Decimal(str(trig)) - Decimal(str(row["trig"]))) > tick / 2:
                    return False
            except (InvalidOperation, ValueError):
                return False
        if "reduceOnly" in r and bool(r.get("reduceOnly")) != row["reduce_only"]:
            return False
        if r.get("orderTime") not in (None, ""):
            t = to_ms(r["orderTime"])
            if not row["sent_ms"] - MATCH_BEFORE_MS <= t <= row["sent_ms"] + SETTLE_MS:
                return False
        return True

    def _search(self, row: dict) -> list:
        """Orders that fit a ledger row whose answer was lost: the pending list and the order history from
        sent_ms - 3 s, held by no other cid."""
        sym = row["symbol"]
        lo = row["sent_ms"] - MATCH_BEFORE_MS
        hi = max(self._now(), row["sent_ms"]) + 5_000
        found: dict = {}
        for r in self._pending(sym) + self._history(sym, lo, hi):
            oid = str(r.get("orderId") or "")
            if not oid or oid in found or not self._matches(r, row):
                continue
            other = self.ledger.by_order(oid)
            if other is not None and other["cid"] != row["cid"]:
                continue
            found[oid] = r
        return list(found.values())

    def _resolve(self, cid: str) -> tuple:
        """(ledger row, orderId) for a client id (module docstring: the ledger)."""
        row = self.ledger.get(cid)
        if row is None or row["state"] == "refused":
            raise TestnetError(404, NOT_FOUND[0], f"주문 {cid}이 없습니다" + (" (거절된 주문)" if row else ""))
        if row.get("order_id"):
            return row, str(row["order_id"])
        hits = self._search(row)
        if len(hits) == 1:
            oid = str(hits[0]["orderId"])
            self.ledger.bind(cid, oid, how="search")
            self.order_symbol[oid] = row["symbol"]
            return {**row, "order_id": oid}, oid
        if len(hits) > 1:
            raise TestnetError(409, AMBIGUOUS, f"주문 {cid}: 답을 잃은 주문에 맞는 주문이 {len(hits)}개라 어느 것인지 모릅니다"
                                               f"({', '.join(str(h.get('orderId')) for h in hits)})")
        if self._now() - row["sent_ms"] < SETTLE_MS:
            age = (self._now() - row["sent_ms"]) / 1000
            raise TransientError(200, None, f"주문 {cid}: 아직 주문 기록에 안 보입니다(보낸 지 {age:.0f}초, "
                                            f"{SETTLE_MS // 1000}초까지 기다림)")
        raise TestnetError(404, NOT_FOUND[0], f"주문 {cid}이 플립스터에 없습니다({SETTLE_MS // 1000}초 지나도 기록에 없음)")

    # ------------------------------------------------------------ orders
    def market(self, symbol: str, side: str, qty: float, reduce_only: bool = False,
               client_id: Optional[str] = None) -> dict:
        """Market order (IOC on Flipster), then read back from its fills. reduce_only: closes only. Never
        maxSlippagePrice, never timeInForce (module docstring). An opening order is never sent twice: a client id
        already in the ledger is looked up instead; its rate-limit answer is an unknown outcome (looked up)."""
        if side not in ("BUY", "SELL"):
            raise TestnetError(400, "BAD_SIDE", f"주문 방향 {side!r}")
        q = self._qty(symbol, qty)
        self._check_qty(symbol, q, qty, "주문")
        cid = client_id or new_cid()
        earlier = self._earlier(cid, reduce_only)
        if earlier is not None:                            # the same order: read it, never send it again
            return self._read_back(symbol, earlier[1], earlier[0], None)
        body = {"symbol": fx(symbol), "side": side, "type": MARKET, "quantity": _num(q)}
        if reduce_only:
            body["reduceOnly"] = True
        sent = self._now()
        durable = self.ledger.put(cid, symbol, side, MARKET, _num(q), reduce_only, None, sent)
        if not durable and not reduce_only:
            raise TestnetError(500, "LEDGER", f"주문 장부에 쓰지 못해 진입 주문을 보내지 않았습니다({self.ledger.failed})")
        row = self.ledger.get(cid)
        try:
            data = self.req("POST", ORDER, body, limit_key="market")
        except RateLimited as e:
            if not reduce_only and e.status == 429:
                raise TransientError(e.status, e.code, f"진입 주문에 요청 한도 답(결과 모름, 다시 보내지 않음): {e.msg}") from e
            self.ledger.refused(cid, str(e))
            raise
        except TransientError:
            raise                                          # unknown outcome: looked up by the cid (the ledger)
        except TestnetError as e:
            self.ledger.refused(cid, str(e))
            raise
        order = data.get("order") if isinstance(data, dict) else None
        oid = order.get("orderId") if isinstance(order, dict) else None
        if oid in (None, "") or isinstance(oid, (dict, list, bool)):
            raise TransientError(200, None, "주문 번호가 없는 응답(결과 모름)")
        oid = str(oid)
        self.ledger.bind(cid, oid)
        self.order_symbol[oid] = symbol
        return self._read_back(symbol, oid, {**row, "order_id": oid}, order)

    def _earlier(self, cid: str, reduce_only: bool) -> Optional[tuple]:
        """A client id already in the ledger (and not refused): (row, orderId) of the order it placed. None: no such
        row, or its earlier send was found absent past the settle window (only a reduce-only order is then sent again).
        An opening order is never sent twice: any other outcome is an unknown one (TransientError)."""
        old = self.ledger.get(cid)
        if old is None or old["state"] == "refused":
            return None
        if old.get("order_id"):
            return old, str(old["order_id"])
        try:
            return self._resolve(cid)
        except TestnetError as e:
            if e.code in NOT_FOUND and not isinstance(e, TransientError) and reduce_only:
                return None
            raise TransientError(e.status, e.code, f"이 번호({cid})로 이미 보낸 주문의 결과를 모릅니다. 다시 보내지 "
                                                   f"않습니다: {e.msg}") from e

    def _read_back(self, symbol: str, oid: str, row: dict, answer: Optional[dict]) -> dict:
        """The accepted order, its fills read until they account for what the order record says was filled (a few
        short waits). It WAS accepted (it has an orderId): a failed read never escapes as if it had not run; the last
        state seen (or the answer) is returned and the executor settles it from the position."""
        first = self._compose(symbol, oid, row, answer, []) if isinstance(answer, dict) else \
            {"orderId": oid, "clientOrderId": row.get("cid") or "", "symbol": symbol, "side": row.get("side"),
             "type": row.get("type"), "origQty": row.get("qty"), "executedQty": "0", "avgPrice": "0",
             "status": "NEW", "reduceOnly": bool(row.get("reduce_only"))}
        best = first
        for w in (0.0,) + ORDER_WAITS:
            if w:
                self.sleep(w)
            try:
                record = answer if isinstance(answer, dict) and answer.get("status") in FINAL_STATUS else \
                    (self._record(symbol, oid, row.get("sent_ms")) or answer)
                fills = self._fills_of(symbol, oid, row.get("sent_ms"))
                best = self._compose(symbol, oid, row, record, fills)
            except TestnetError as e:
                return {**best, "readBack": f"읽기 실패: {e}"}
            if best["status"] in ORDER_FINAL and "readBack" not in best:
                break
        return best

    def order(self, symbol: str, order_id=None, client_id: Optional[str] = None) -> dict:
        if order_id is not None:
            oid = str(order_id)
            return self._by_id(symbol, oid, self.ledger.by_order(oid))
        row, oid = self._resolve(str(client_id))
        return self._by_id(row["symbol"], oid, row)

    def _delete(self, symbol: str, oid: str) -> None:
        self.req("DELETE", ORDER, {"symbol": fx(symbol), "orderId": str(oid)}, limit_key="cancel")

    def cancel(self, symbol: str, order_id) -> dict:
        self._delete(symbol, str(order_id))
        return {"orderId": str(order_id), "status": "CANCELED"}

    def _cancel_each(self, rows: list, symbol: str) -> None:
        for r in rows:
            try:
                self._delete(symbol, str(r["orderId"]))
            except TestnetError as e:
                if e.code not in NOT_FOUND or isinstance(e, TransientError):
                    raise

    def cancel_all(self, symbol: str) -> dict:
        """No documented cancel-all: each pending order (not a stop) is cancelled by its id."""
        self._cancel_each([r for r in self._pending(symbol) if r.get("orderType") != STOP], symbol)
        return {"code": 200, "msg": "ok"}

    def open_orders(self, symbol: str) -> list:
        out = []
        for r in self._pending(symbol):
            if r.get("orderType") == STOP:
                continue
            oid = str(r["orderId"])
            out.append(self._compose(symbol, oid, self.ledger.by_order(oid), r, []))
        return out

    # ------------------------------------------------------------ STOP_MARKET orders: the exchange-side stops
    def _algo_dict(self, row: dict, status: str = "NEW", actual: str = "", ledger_row: Optional[dict] = None) -> dict:
        oid = str(self._need(row, "orderId", "조건 주문"))
        sym = bn(row.get("symbol")) or (ledger_row or {}).get("symbol") or self.order_symbol.get(oid, "")
        lrow = ledger_row if ledger_row is not None else self.ledger.by_order(oid)
        trig = row.get("triggerPrice") if row.get("triggerPrice") not in (None, "") else row.get("price")
        if status == "NEW":                                # a resting stop's level is never read as 0 from a gap
            trig = _num(_dec(trig, "triggerPrice"))
        qty = row.get("quantity")
        self.order_symbol[oid] = sym
        return {"algoId": oid, "clientAlgoId": (lrow or {}).get("cid") or "", "symbol": sym,
                "side": row.get("side") or (lrow or {}).get("side"),
                "orderType": STOP if (row.get("orderType") or (lrow or {}).get("type")) == STOP else "CONDITIONAL",
                "algoType": "CONDITIONAL",
                "triggerPrice": _num(_dec(trig, "triggerPrice")) if trig not in (None, "") else "0",
                "quantity": _num(_dec(qty, "quantity")) if status == "NEW" or qty not in (None, "") else "0",
                "closePosition": False,
                # the pending list carries no reduceOnly: ours (the ledger) are; a stop placed by hand: unknown
                "reduceOnly": True if (lrow or {}).get("reduce_only") else None, "foreign": lrow is None,
                "workingType": WORKING_TYPE, "priceProtect": False, "algoStatus": status,
                "flipsterStatus": row.get("status"), "actualOrderId": actual,
                "createTime": to_ms(row["orderTime"]) if row.get("orderTime") not in (None, "") else None}

    def _resting(self, symbol: Optional[str]) -> list:
        """Pending STOP_MARKET orders that can still fire (NEW / PENDING_NEW). A status the docs do not list is an
        error, never "no stop"."""
        out = []
        for r in self._pending(symbol):
            if r.get("orderType") != STOP:
                continue
            if r.get("status") not in OPEN_STATUS + FINAL_STATUS:
                raise TransientError(200, None, f"조건 주문 {r.get('orderId')}의 상태가 이상합니다({r.get('status')!r})")
            if r.get("status") in ("NEW", "PENDING_NEW"):
                out.append(r)
        return out

    def stop_close(self, symbol: str, side: str, trigger: float, qty: Optional[float] = None,
                   client_id: Optional[str] = None) -> dict:
        """Protective stop resting on Flipster: a closing-side STOP_MARKET, reduceOnly, ``price`` = the trigger. ``qty``
        the position's size (two can coexist while a stop is moved); None: the position's size now. A level the last
        price is already past is refused before anything is sent (the executor's -2021: close at market)."""
        sp = self._spec(symbol)
        trig = _price_str(trigger, sp["tick_str"])
        if qty is None:
            qty = abs(float(self.position(symbol)["positionAmt"]))
        q = self._qty(symbol, qty)
        self._check_qty(symbol, q, qty, "손절")
        cid = client_id or new_cid()
        earlier = self._earlier(cid, True)
        if earlier is not None:                            # this stop was placed: never a second copy
            return self.algo_order(algo_id=earlier[1])
        last = self.price(symbol)
        if (side == "SELL" and last <= float(trig)) or (side == "BUY" and last >= float(trig)):
            raise TestnetError(400, WOULD_TRIGGER, f"Order would immediately trigger (플립스터: 마지막 가격 {last:g}, "
                                                   f"손절 {trig})")
        body = {"symbol": fx(symbol), "side": side, "type": STOP, "quantity": _num(q), "price": trig,
                "reduceOnly": True}
        self.ledger.put(cid, symbol, side, STOP, _num(q), True, trig, self._now())   # protection first: kept in memory
        try:
            data = self.req("POST", ORDER, body, limit_key="stop_place")
        except TransientError:
            raise                                          # unknown outcome: looked up by the cid (the ledger)
        except RateLimited as e:
            self.ledger.refused(cid, str(e))
            raise
        except TestnetError as e:
            self.ledger.refused(cid, str(e))
            raise self._would_trigger(e, symbol, side, float(trig)) from e
        order = data.get("order") if isinstance(data, dict) else None
        sid = order.get("orderId") if isinstance(order, dict) else None
        if sid in (None, "") or isinstance(sid, (dict, list, bool)):
            raise TransientError(200, None, "손절 주문 번호가 없는 응답(결과 모름)")
        sid = str(sid)
        self.ledger.bind(cid, sid)
        self.order_symbol[sid] = symbol
        return {"algoId": sid, "clientAlgoId": cid, "symbol": symbol, "side": side, "orderType": STOP,
                "algoType": "CONDITIONAL", "triggerPrice": _num(Decimal(trig)), "quantity": _num(q),
                "closePosition": False, "reduceOnly": True, "workingType": WORKING_TYPE, "algoStatus": "NEW"}

    def _would_trigger(self, e: TestnetError, symbol: str, side: str, trig: float) -> TestnetError:
        """A refused stop while the last price is already past it: the executor's "would immediately trigger" (-2021:
        close at market). Anything else stays as it was."""
        if e.code == WOULD_TRIGGER:
            return e
        try:
            last = self.price(symbol)
        except TestnetError:
            return e
        if (side == "SELL" and last <= trig) or (side == "BUY" and last >= trig):
            return TestnetError(e.status, WOULD_TRIGGER, f"Order would immediately trigger (플립스터: {e.msg}; 마지막 "
                                                         f"가격 {last:g}, 손절 {trig:g})")
        return e

    def _finished_stop(self, sid: str, symbol: str, lrow: Optional[dict]) -> Optional[dict]:
        """A stop that no longer rests: its order history row and its executions. TRADE executions under its own
        orderId (or a FILLED row, or a TRIGGERED execution): fired (``actualOrderId`` its own id when its fills carry
        it). Otherwise CANCELED."""
        sent = lrow["sent_ms"] if lrow else None
        lo, hi = self._window(sent)
        rec = next((r for r in self._history(symbol, lo, hi) if str(r.get("orderId")) == sid), None)
        ex = self._execs(symbol, lo, hi, order_id=sid)
        if rec is None and not ex:
            return None
        trades = [r for r in ex if r.get("execType") == "TRADE"]
        fired = bool(trades) or any(r.get("execType") == "TRIGGERED" for r in ex) or (rec or {}).get("status") == \
            "FILLED" or _f((rec or {}).get("cumQty")) > 0
        base = rec or {"orderId": sid, "symbol": fx(symbol), "side": (lrow or {}).get("side"), "orderType": STOP,
                       "quantity": (lrow or {}).get("qty"), "triggerPrice": (lrow or {}).get("trig"),
                       "status": "FILLED" if fired else "CANCELED"}
        return self._algo_dict(base, "TRIGGERED" if fired else "CANCELED", sid if trades else "", lrow)

    def algo_order(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        lrow = None
        if algo_id is None:
            lrow, algo_id = self._resolve(str(client_id))
        algo_id = str(algo_id)
        lrow = lrow or self.ledger.by_order(algo_id)
        sym = (lrow or {}).get("symbol") or self.order_symbol.get(algo_id) or None
        rows = self._pending(sym)
        row = next((r for r in rows if str(r.get("orderId")) == algo_id), None)
        if row is not None:
            sym = bn(row.get("symbol")) or sym
            if row.get("status") in ("NEW", "PENDING_NEW"):
                return self._algo_dict(row, "NEW", ledger_row=lrow)
            if row.get("status") == "PARTIALLY_FILLED":
                return self._algo_dict(row, "TRIGGERING", algo_id, lrow)
        for s in ([sym] if sym else list(COINS)):
            done = self._finished_stop(algo_id, s, lrow)
            if done is not None:
                return done
        if lrow is not None:
            raise TransientError(200, None, f"손절 {algo_id}이 플립스터 목록·기록에 아직 안 보입니다(접수된 주문)")
        raise TestnetError(404, NOT_FOUND[0], f"조건 주문 {algo_id}이 없습니다")

    def cancel_algo(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        cid = client_id
        if algo_id is None:
            row, algo_id = self._resolve(str(client_id))
            cid = row["cid"]
        algo_id = str(algo_id)
        lrow = self.ledger.by_order(algo_id)
        sym = (lrow or {}).get("symbol") or self.order_symbol.get(algo_id) or self.algo_order(algo_id=algo_id)["symbol"]
        try:
            self._delete(sym, algo_id)
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            if e.code in NOT_FOUND:
                raise
            try:                                           # an undocumented refusal: is it still resting?
                cur = self.algo_order(algo_id=algo_id)
            except TestnetError:
                raise e
            if cur["algoStatus"] != "NEW":
                raise TestnetError(400, NOT_FOUND[1], f"이미 끝난 조건 주문({cur['algoStatus']}): {e.msg}") from e
            raise
        return {"algoId": algo_id, "clientAlgoId": cid or (lrow or {}).get("cid") or "", "code": "200",
                "msg": "success"}

    def open_algo_orders(self, symbol: str) -> list:
        return [self._algo_dict(r) for r in self._resting(symbol)]

    def cancel_all_algo(self, symbol: str) -> dict:
        """No documented "cancel every stop" call: each pending STOP_MARKET of the symbol is cancelled by its id."""
        self._cancel_each([r for r in self._pending(symbol) if r.get("orderType") == STOP], symbol)
        return {"code": 200, "msg": "ok"}

    # ------------------------------------------------------------ positions
    def _position_rows(self, symbol: Optional[str] = None) -> list:
        """Open position rows (positionSide LONG / SHORT with a positionAmount). A row with neither is a coin's settings
        (flat). The answer must be a list, and a row must be readable: never "flat" from a missing or garbled field."""
        data = self.req("GET", API + "/account/position", {"symbol": fx(symbol)} if symbol else None,
                        limit_key="position")
        if not isinstance(data, list):
            raise TransientError(200, None, f"포지션 응답이 목록이 아닙니다: {str(data)[:80]!r}")
        out, per = [], {}
        for r in data:
            if not isinstance(r, dict):
                raise TransientError(200, None, "포지션 응답이 이상합니다")
            sym = bn(r.get("symbol"))
            if not sym or (symbol and sym != symbol):
                continue
            side, amt = r.get("positionSide"), r.get("positionAmount")
            if side in (None, ""):
                if amt not in (None, "") and _dec(amt, "positionAmount") != 0:
                    raise TransientError(200, None, f"{sym}: 포지션 방향 없이 수량 {amt!r}이 있습니다")
                continue
            if side not in ("LONG", "SHORT"):
                raise TransientError(200, None, f"{sym}: 포지션 방향이 이상합니다({side!r})")
            a = _dec(amt, "positionAmount")
            if a == 0:
                continue
            if a < 0 and side == "LONG":
                raise TransientError(200, None, f"{sym}: 포지션 방향이 이상합니다(LONG, 수량 {amt!r})")
            per[sym] = per.get(sym, 0) + 1
            out.append(r)
        many = sorted(s for s, n in per.items() if n > 1)
        if many:
            raise TransientError(200, None, f"{', '.join(many)}: 한 코인에 포지션이 둘 이상입니다(단방향이 아님)")
        return out

    def _position_dict(self, symbol: str, rows: list) -> dict:
        main = rows[0] if rows else {}
        amt = Decimal(0)
        if rows:
            q = abs(_dec(main.get("positionAmount"), "positionAmount"))   # the side comes from positionSide only
            amt = q if main.get("positionSide") == "LONG" else -q
        mt = str(main.get("marginType") or "").lower()
        return {"symbol": symbol, "positionAmt": _num(amt), "entryPrice": str(main.get("entryPrice") or "0"),
                "markPrice": str(main.get("markPrice") or "0"),
                "liquidationPrice": str(main.get("liquidationPrice") or "0"),
                "unRealizedProfit": str(main.get("unrealizedPnl") or "0"), "leverage": str(main.get("leverage") or ""),
                "marginType": mt if mt in ("isolated", "cross") else "", "hedge": False,
                "positionSide": main.get("positionSide"), "totalFee": main.get("totalFee")}

    def position(self, symbol: str) -> dict:
        return self._position_dict(symbol, self._position_rows(symbol))

    def positions(self) -> list:
        by: dict = {}
        for r in self._position_rows(None):
            by.setdefault(bn(r.get("symbol")), []).append(r)
        out = [self._position_dict(s, rs) for s, rs in by.items() if s]
        return [p for p in out if float(p["positionAmt"]) != 0]

    # ------------------------------------------------------------ fills, P&L, funding
    def user_trades(self, symbol: str, start_ms: int, end_ms: int, limit: int = 1000) -> list:
        """Account fills (Binance userTrades shape) from the TRADE executions: price, qty, realizedPnl (replayed, see
        fills_from_execs), commission (execFee: + paid), commissionAsset, orderId, side, time."""
        rows = self._execs(symbol, int(start_ms), int(end_ms), exec_type="TRADE")
        reduce_ids = self.ledger.reduce_only_ids({str(r.get("orderId")) for r in rows})
        return fills_from_execs(rows, symbol, reduce_ids)

    def income(self, symbol: Optional[str], income_type: Optional[str], start_ms: int, end_ms: int,
               limit: int = 1000) -> list:
        """Funding in the Binance income shape (``income``: + received) from the FUNDING executions: ``income`` =
        -execFee (a fee is + paid; the drill shows the rows to compare with the app). The docs offer no history of
        deposits and withdrawals: no TRANSFER rows."""
        if income_type not in (None, "FUNDING_FEE"):
            return []
        out = []
        lo, hi = int(start_ms), int(end_ms)
        for r in self._execs(symbol, lo, hi, exec_type="FUNDING"):
            t = to_ms(r.get("transactTime"), "transactTime")
            if not lo <= t <= hi:
                continue
            sym = bn(r.get("symbol"))
            out.append({"symbol": sym, "incomeType": "FUNDING_FEE",
                        "income": _num(-_dec(r.get("execFee"), "execFee")),
                        "asset": r.get("settlementCurrency") or SETTLE, "time": t,
                        "tranId": _id60("funding", r.get("execId"), sym, t), "info": "FUNDING"})
        return sorted(out, key=lambda r: int(r["time"]))


class FlipsterKeyCheckClient(FlipsterClient):
    """The key check (reads only): the account. The API reports no key permissions: "read + trade only, no withdrawal,
    server IP bound" comes from the owners' statement ``attested`` (FLIPSTER_LIVE_KEY_CHECKED)."""
    __test__ = False

    def __init__(self, *a, attested: bool = False, **k):
        super().__init__(*a, **k)
        self.attested = attested

    def api_restrictions(self):
        data = self.req("GET", API + "/account", limit_key="account")
        if not isinstance(data, dict) or data.get("totalWalletBalance") in (None, ""):
            return None                                     # nothing verified
        return permission_record(self.attested, True)


# ---------------------------------------------------------------- keys, allowlist, the executor's clients
def _values(env, names) -> set:
    return {str((env or {}).get(n) or "").strip() for n in names} - {""}


def trading_keys(mode: str, env, paper_env=None) -> tuple[str, str]:
    """The Flipster key and secret, or Refused. Mainnet only, behind PAPERBOT_LIVE_MAINNET=I_UNDERSTAND. Never the paper
    runner's key, a Binance, Bybit, MEXC or WOO X Pro key."""
    if mode != MODE_MAINNET:
        raise Refused(f"플립스터에는 테스트넷이 없습니다: \"exchange\": \"flipster\"는 \"mode\": \"mainnet\"만 됩니다"
                      f"(지금 {mode!r})")
    if (env.get(FLAG) or "") != FLAG_VALUE:
        raise Refused(f"실거래 스위치가 꺼져 있습니다: 환경 변수 {FLAG}={FLAG_VALUE} 가 필요합니다")
    key, secret = (str(env.get(n) or "").strip() for n in LIVE_KEY_NAMES)
    if not (key and secret):
        raise Refused(f"{LIVE_KEY_NAMES[0]} / {LIVE_KEY_NAMES[1]} 가 비어 있습니다")
    if key == secret:
        raise Refused(f"{LIVE_KEY_NAMES[0]}와 {LIVE_KEY_NAMES[1]}가 같습니다")
    if {key, secret} & (_values(env, PAPER_KEY_NAMES) | _values(paper_env, PAPER_KEY_NAMES)):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 paper 실행기의 읽기 전용 키(BINANCE_API_KEY)와 같습니다")
    if {key, secret} & _values(env, BINANCE_LIVE_KEY_NAMES + BINANCE_TESTNET_KEY_NAMES):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 바이낸스 키(LIVE_*/TESTNET_*)와 같습니다. 거래소마다 다른 키를 씁니다")
    if {key, secret} & _values(env, BY.LIVE_KEY_NAMES + BY.TESTNET_KEY_NAMES):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 바이비트 키(BYBIT_*)와 같습니다. 거래소마다 다른 키를 씁니다")
    if {key, secret} & _values(env, MX.LIVE_KEY_NAMES):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 MEXC 키(MEXC_*)와 같습니다. 거래소마다 다른 키를 씁니다")
    if {key, secret} & _values(env, WX.LIVE_KEY_NAMES + (WX.MEMO_NAME,)):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 WOO X Pro 키(WOOXPRO_*)와 같습니다. 거래소마다 다른 키를 "
                      "씁니다")
    return key, secret


def attested(env) -> bool:
    return str((env or {}).get(KEY_CHECKED) or "").strip() == KEY_CHECKED_VALUE


def refuse_unless_allowed(mode: str, client, db: Optional[str] = None) -> None:
    """Mainnet only, the client must be the Flipster client pointing at the allowed host, and (the executor: ``db``)
    its client-id ledger must live in the executor's own database."""
    if mode != MODE_MAINNET:
        raise Refused(f"플립스터에는 테스트넷이 없습니다: mode={mode!r}로는 시작하지 않습니다(\"mainnet\"만)")
    host = urllib.parse.urlparse(getattr(client, "base", "") or "").hostname or ""
    if host not in FLIPSTER_HOSTS or type(client) is not FlipsterClient or tuple(type(client).HOSTS) != FLIPSTER_HOSTS:
        raise Refused(f"주소 {host!r}: 플립스터 실행기는 {'·'.join(FLIPSTER_HOSTS)} 외에는 연결하지 않습니다")
    if db is not None:
        path = getattr(getattr(client, "ledger", None), "path", None)
        if not path or os.path.abspath(path) != os.path.abspath(db):
            raise Refused(f"플립스터 주문 장부(client id)가 실행기 DB({db})에 있지 않아 시작하지 않습니다(지금 {path!r})")


def check_executor_keys(mode: str, client, keycheck, env, paper_env) -> None:
    """The executor's key gates for Flipster (Executor.__init__): the keys, the key check, the owners' statement."""
    key, secret = trading_keys(mode, env, paper_env)
    if (client.key, client.secret) != (key, secret):
        raise Refused("플립스터 실거래 실행기의 키가 FLIPSTER_LIVE_KEY/SECRET와 다릅니다")
    if not isinstance(keycheck, FlipsterKeyCheckClient) or (keycheck.key, keycheck.secret) != (key, secret):
        raise Refused("플립스터 실거래는 키 확인(계정 읽기)을 거쳐야 시작합니다")
    if not attested(env) or not keycheck.attested:
        raise Refused(f"플립스터는 키 권한을 API로 알려 주지 않습니다. 키를 '읽기 + 거래만, 출금 없음, 서버 IP만'으로 만든 것을 "
                      f"확인한 뒤 /etc/paperbot/executor.env에 {KEY_CHECKED}={KEY_CHECKED_VALUE} 를 넣으세요")


def clients(mode: str, env, paper_env=None, db: Optional[str] = None):
    """(order client, key-check client) for the mode, keys from the environment. ``db``: the executor's database (the
    client-id ledger lives there); None: a ledger in memory (the drill and check)."""
    key, secret = trading_keys(mode, env, paper_env)
    return (FlipsterClient(key, secret, ledger=IdLedger(db)),
            FlipsterKeyCheckClient(key, secret, attested=attested(env)))


# ---------------------------------------------------------------- drill (mainnet, tiny)
def reconcile(c: FlipsterClient, symbol: str, stop_price: Optional[float] = None) -> dict:
    """After a restart: a position without a protective stop is the one state that must never last."""
    amt = float(c.position(symbol)["positionAmt"])
    stops = live_stops(c, symbol)
    covering = [o for o in stops if covers(o, amt)]
    out = {"position": amt, "stops": len(stops), "repaired": False, "problem": None}
    if amt != 0 and not covering:
        out["problem"] = "position without a protective stop" if not stops else "stop smaller than the position"
        if stop_price is not None:
            place_stop(c, symbol, "SELL" if amt > 0 else "BUY", stop_price, abs(amt))
            out["repaired"] = True
    elif amt == 0 and stops:
        out["problem"] = "stop orders without a position"
    return out


def pace(c: FlipsterClient, gap_s: float = DRILL_MIN_GAP_S, sleep=time.sleep, clock=time.monotonic) -> None:
    """The drill's requests: at least ``gap_s`` apart (the client's own budget keeps the windows)."""
    orig, last = c.req, [None]

    def paced(*a, **k):
        if last[0] is not None:
            wait = gap_s - (clock() - last[0])
            if wait > 0:
                sleep(wait)
        try:
            return orig(*a, **k)
        finally:
            last[0] = clock()
    c.req = paced


@dataclass
class FlipsterDrill:
    """The Flipster micro drill on the REAL account. ``check()`` reads (time, contracts, account, fee rate, open orders
    and stops, funding rows), sets one-way mode and the isolated leverage (BTC 40x, the others 30x): no order.
    ``order_cycle()`` (only behind the explicit confirmation) runs one smallest-size cycle on one coin: a plain market
    entry (no maxSlippagePrice), found by its client id through the ledger and again through the order history search
    (its answer treated as lost), a reduce-only STOP_MARKET, the stop moved (new first, then the old one cancelled: two
    must rest at once), then the trigger test (the stop moved to 0.1 % from the last price and left to fire for real; at
    most 20 minutes; which price fired it and whose orderId its fills carry) or a reduce-only close, flat with no order
    and no stop left, and the P&L replayed from the fills checked against the fill prices and the wallet change, with
    the fee rate measured on the fills."""
    client: FlipsterClient
    symbols: tuple = COINS
    symbol: Optional[str] = None
    side: int = 1
    keycheck: Optional[FlipsterKeyCheckClient] = None
    stop_frac: float = 0.01
    trigger_test: bool = True
    trigger_wait_s: float = TRIGGER_WAIT_S
    wait: Callable[[float], None] = time.sleep
    elapsed: Callable[[], float] = time.monotonic          # seconds, for the drill's waits (tests pass their clock)
    say: Optional[Callable[[str], None]] = None            # each step printed as it happens (the CLI prints)
    log: list = field(default_factory=list)
    fee_api: Optional[float] = None

    def add(self, name: str, ok: bool, detail) -> None:
        row = {"step": name, "ok": bool(ok), "detail": detail}
        self.log.append(row)
        if self.say:
            self.say(row_text(row))

    def _step(self, name: str, ok: bool, detail, fatal: bool = True) -> None:
        self.add(name, ok, detail)
        if not ok and fatal:
            raise AssertionError(f"{name}: {detail}")

    def _note(self, text: str) -> None:
        if self.say:
            self.say(f"  ... {text}")

    def _waiting(self, start: float, last: list, what: str) -> None:
        mins = int((self.elapsed() - start) // 300) * 5
        if mins and mins != last[0]:
            last[0] = mins
            self._note(f"{what}: {mins}분째 기다리는 중")

    def _until(self, check, tries: int = 10, pause: float = 0.4):
        for _ in range(tries):
            got = check()
            if got:
                return got
            self.wait(pause)
        return check()

    def smallest(self) -> str:
        """The coin whose smallest order is the cheapest."""
        c = self.client
        return min(self.symbols, key=lambda s: self.drill_qty(c.spec(s), c.price(s)) * c.price(s))

    @staticmethod
    def drill_qty(spec: dict, price: float) -> float:
        """The smallest quantity on the step worth at least DRILL_ORDER_USDT (and 20 % above the contract's minimum)."""
        step = spec["qty_step"]
        usd = max(DRILL_ORDER_USDT, 1.2 * float(spec.get("min_notional") or 0))
        need = math.ceil(usd / (price * step) - 1e-9) * step if price > 0 else 0.0
        return round(max(spec["min_qty"], need), 12)

    def check(self) -> list:
        c = self.client
        off = c.sync_time()
        self._step("서버 시간", abs(off) < 1000 and c.time_source != "local", {"offset_ms": off, "source": c.time_source})
        rows = {}
        for s in self.symbols:
            sp, px = c.spec(s), c.price(s)
            rows[s] = {"tradable": sp["tradable"], "qty_step": sp["qty_step_str"], "tick": sp["tick_str"],
                       "min_notional": sp["min_notional"], "max_leverage": sp["max_leverage"],
                       "min_order_usd": round(max(sp["min_qty"] * px, sp["min_notional"]), 4)}
        self._step("계약 정보(6개 코인, API 거래 가능)", all(r["tradable"] and (r["max_leverage"] or 0) >= (
            40 if s == "BTCUSDT" else 30) for s, r in rows.items()), rows)
        a = c.account()
        pos = c.positions()
        self._step("선물 계정 읽기", True, {"equity": a["totalMarginBalance"], "wallet": a["totalWalletBalance"],
                                         "unrealized": a["totalUnrealizedProfit"], "available": a["availableBalance"],
                                         "assets": a["assets"], "positions": [(p["symbol"], p["positionAmt"])
                                                                              for p in pos]})
        try:
            fee = c.fee_rate()
            self.fee_api = fee["taker"]
            self._step("수수료율(API로 읽음; 단위·내 등급 표시는 문서에 없음)", True,
                       {"lowest_level_feeRate": fee["taker"], "levels": fee["levels"]}, fatal=False)
        except TestnetError as e:
            self._step("수수료율(API로 읽음)", False, str(e), fatal=False)
        left = {s: (len(c.open_orders(s)), len(c.open_algo_orders(s))) for s in self.symbols}
        self._step("열린 주문·조건 주문(목록 읽기)", True, left)
        now = c.clock_ms() + c.offset_ms
        try:
            inc = c.income(None, None, now - 7 * 86_400_000, now)
            self._step("펀딩 기록 읽기(지난 7일; + 받음 / - 냄, 앱과 부호 비교)", True,
                       {"rows": len(inc), "last": [(r["symbol"], r["income"], r["time"]) for r in inc[-3:]]},
                       fatal=False)
        except TestnetError as e:
            self._step("펀딩 기록 읽기(지난 7일)", False, str(e), fatal=False)
        c.one_way()
        self._step("거래 모드 단방향(ONE_WAY, 답으로 확인)", c.trade_mode == ONE_WAY,
                   {"trade_mode": c.trade_mode, "source": c.trade_mode_source})
        levs = {}
        for s in self.symbols:
            want = int(min(FIXED_LEVERAGE.get(s, DEFAULT_LEVERAGE), c.spec(s)["max_leverage"] or 10 ** 6))
            levs[s] = c.leverage(s, want)["leverage"] if not any(p["symbol"] == s for p in pos) else "포지션 있음"
        self._step("격리 레버리지 BTC 40배, 나머지 30배" + (" (읽어서 확인)" if not c.lev_unverified else
                                                      f" (목록에 줄이 없어 확인 못 한 코인 {sorted(c.lev_unverified)}: "
                                                      "주문 시험의 포지션에서 확인)"),
                   all(v == (40 if s == "BTCUSDT" else 30) for s, v in levs.items()), levs)
        if self.keycheck is not None:
            self.keycheck.offset_ms = c.offset_ms
            perm = self.keycheck.api_restrictions()
            probs = check_permissions(perm) if isinstance(perm, dict) else ["키 확인 응답이 이상합니다"]
            self._step("키 확인(계정 읽기, 두 분 확인 문구)", not probs, probs or (perm or {}).get("warnings"), fatal=False)
        return self.log

    def _settle(self, s: str, x: dict) -> dict:
        c = self.client
        for _ in range(20):
            if x.get("status") in ORDER_FINAL and "readBack" not in x:
                break
            self.wait(0.5)
            x = c.order(s, order_id=x["orderId"])
        return x

    def _lost_answer(self, s: str, cid: str, oid: str) -> None:
        """The entry's answer treated as lost: the ledger row without its orderId must find the same order in the order
        history (side, type, quantity, time), within the settle window."""
        c = self.client
        c.ledger.forget_order(cid)
        start = self.elapsed()
        got, err = None, None
        while self.elapsed() - start < SETTLE_MS / 1000 + 10:
            try:
                got = c.order(s, client_id=cid)
                break
            except TransientError as e:
                err = e
                self.wait(2.0)
            except TestnetError as e:
                err = e
                break
        if got is None:
            c.ledger.bind(cid, oid, how="drill")           # the rest of the drill must still know its entry
        self._step("답을 잃은 주문 찾기(장부의 주문 번호를 지우고 주문 기록 검색으로 같은 주문)", got is not None
                   and got.get("orderId") == oid, {"orderId": (got or {}).get("orderId"), "want": oid,
                                                    "error": None if got else str(err)})

    def order_cycle(self) -> list:
        c = self.client
        s = self.symbol = self.symbol or self.smallest()
        buy, sell = ("BUY", "SELL") if self.side > 0 else ("SELL", "BUY")
        spec = c.spec(s)
        t0 = c.clock_ms() + c.offset_ms
        self._step(f"{s} 시작 전 포지션·주문·조건 주문 없음", float(c.position(s)["positionAmt"]) == 0
                   and not c.open_orders(s) and not c.open_algo_orders(s), "포지션이 없고 주문이 없어야 합니다")
        w0 = float(c.account()["totalWalletBalance"])
        qty = self.drill_qty(spec, c.price(s))
        cid = new_cid()
        o = self._settle(s, c.market(s, buy, qty, client_id=cid))
        self._step(f"시장가 진입 체결(maxSlippagePrice 없이, 가장 작은 주문 약 ${DRILL_ORDER_USDT:.0f})",
                   o.get("status") == "FILLED" and abs(float(o.get("executedQty") or 0) - qty) < spec["qty_step"] / 2,
                   {"status": o.get("status"), "flipster": o.get("flipsterStatus"), "avg": o.get("avgPrice"),
                    "qty": o.get("executedQty"), "fills": o.get("fills"), "fee": o.get("commission"),
                    "orderId": o.get("orderId")})
        found = c.order(s, client_id=cid)
        self._step("진입 주문을 우리 번호(장부 → orderId)로 찾음", found.get("orderId") == o["orderId"],
                   {"client_id": cid, "orderId": found.get("orderId")})
        self._lost_answer(s, cid, o["orderId"])
        entry = float(o["avgPrice"])
        p = (self._until(lambda: (lambda x: x if float(x["positionAmt"]) else None)(c.position(s))) or c.position(s))
        amt = float(p["positionAmt"])
        want_lev = int(min(FIXED_LEVERAGE.get(s, DEFAULT_LEVERAGE), spec["max_leverage"] or 10 ** 6))
        self._step("포지션 크기·레버리지·격리(포지션 줄에서 읽음)", abs(amt - self.side * qty) < spec["qty_step"] / 2
                   and _int(p.get("leverage")) == c.lev.get(s, want_lev) and p.get("marginType") == "isolated",
                   {"positionAmt": amt, "qty": qty, "leverage": p.get("leverage"), "marginType": p.get("marginType"),
                    "entryPrice": p.get("entryPrice")})
        a1 = c.account()
        lev = _int(p.get("leverage")) or 1
        margin = abs(amt) * entry / lev
        eq1 = float(a1["totalMarginBalance"])
        self._step("평가액(equity)에 포지션 증거금이 들어 있음(진입해도 증거금만큼 줄지 않음)", abs(eq1 - w0) < 0.5 * margin,
                   {"equity_before": w0, "equity_open": eq1, "margin": round(margin, 6),
                    "reserved": a1["positionMargin"], "available": a1["availableBalance"],
                    "unrealized": a1["totalUnrealizedProfit"], "leverage": lev})
        stop1 = round_stop(entry * (1 - self.side * self.stop_frac), spec["tick"], self.side)
        st1 = place_stop(c, s, sell, stop1, abs(amt), client_id=new_cid())
        stops = live_stops(c, s)
        self._step("손절이 플립스터에 걸림(청산 방향 STOP_MARKET, reduceOnly, price = 발동 가격)",
                   len(stops) == 1 and float(stops[0]["triggerPrice"]) == stop1 and covers(stops[0], amt)
                   and stops[0]["reduceOnly"] is True,
                   [(x["algoId"], x["triggerPrice"], x["quantity"], x["side"]) for x in stops])
        stop2 = round_stop(entry * (1 - self.side * self.stop_frac / 2), spec["tick"], self.side)
        seen = {}
        orig = c.cancel_algo

        def watch_cancel(algo_id=None, client_id=None):
            seen.setdefault("during", len(live_stops(c, s)))
            return orig(algo_id=algo_id, client_id=client_id)
        c.cancel_algo = watch_cancel
        try:
            mv = move_stop(c, s, sell, stop2, abs(amt), [st1["algoId"]], client_id=new_cid())
        finally:
            c.cancel_algo = orig
        after = self._until(lambda: (lambda x: x if len(x) == 1 else None)(live_stops(c, s))) or live_stops(c, s)
        self._step("손절 옮기기(새 손절 → 확인 → 옛 손절 취소, 빈틈 없음: 두 개가 같이 걸려야 함)",
                   mv["result"] == "moved" and seen.get("during") == 2 and len(after) == 1
                   and after[0]["algoId"] == mv["stop"]["algoId"] and float(after[0]["triggerPrice"]) == stop2,
                   {"during": seen.get("during"), "after": [(x["algoId"], x["triggerPrice"]) for x in after]})
        mine = {str(o["orderId"])}
        fired = None
        if self.trigger_test:
            fired = self._trigger_test(s, sell, amt, mv["stop"]["algoId"], spec)
            if fired and fired.get("actualOrderId"):
                mine.add(str(fired["actualOrderId"]))
        if float(c.position(s)["positionAmt"]) != 0:
            x = self._settle(s, c.market(s, sell, abs(amt), reduce_only=True, client_id=new_cid()))
            self._step("줄이기 전용 시장가로 청산(maxSlippagePrice 없이)", x.get("status") == "FILLED",
                       {"status": x.get("status"), "avg": x.get("avgPrice"), "qty": x.get("executedQty")})
            mine.add(str(x["orderId"]))
        cancel_everything(c, s)
        clean = self._until(lambda: float(c.position(s)["positionAmt"]) == 0 and not c.open_orders(s)
                            and not c.open_algo_orders(s))
        self._step("포지션 없음, 주문·조건 주문 없음", clean,
                   {"positionAmt": c.position(s)["positionAmt"], "orders": len(c.open_orders(s)),
                    "stops": len(c.open_algo_orders(s))})
        t1 = c.clock_ms() + c.offset_ms

        def pnl():
            fills = [f for f in c.user_trades(s, t0 - 5_000, t1 + 5_000) if str(f["orderId"]) in mine]
            return fills if balanced(self.side, fills, spec["qty_step"]) else None
        fills = self._until(pnl, tries=8, pause=1.5)
        if not fills and fired:
            # the stop's own orderId carries no fills: every fill of the drill's minutes on this coin
            def pnl_all():
                fs = c.user_trades(s, t0 - 5_000, t1 + 5_000)
                return fs if balanced(self.side, fs, spec["qty_step"]) else None
            fills = self._until(pnl_all, tries=4, pause=1.5)
        detail: dict = {"fills": None}
        ok = False
        if fills:
            w1 = float(c.account()["totalWalletBalance"])
            realized = sum(float(f["realizedPnl"]) for f in fills)
            fees = sum(float(f["commission"]) for f in fills)
            ins = [f for f in fills if f["side"] == buy]
            outs = [f for f in fills if f["side"] != buy]
            by_fills = self.side * (sum(float(f["qty"]) * float(f["price"]) for f in outs)
                                    - sum(float(f["qty"]) * float(f["price"]) for f in ins))
            notional = sum(float(f["qty"]) * float(f["price"]) for f in fills)
            funding = sum(float(r["income"]) for r in c.income(s, None, t0 - 5_000, t1 + 5_000))
            tol = max(0.02, 2e-4 * notional)
            ok = (abs(realized - by_fills) <= max(1e-6, 1e-7 * notional) and fees >= 0
                  and all(f.get("realizedSource") == "replay" for f in outs)
                  and abs((w1 - w0) - (realized - fees + funding)) <= tol)
            detail = {"fills": len(fills), "orders": sorted({str(f["orderId"]) for f in fills}),
                      "realized": round(realized, 6), "by_fill_prices": round(by_fills, 6), "fees": round(fees, 6),
                      "funding": round(funding, 6), "net": round(realized - fees + funding, 6),
                      # paid fee per side, % of notional (the brief's guess: about 0.06 %)
                      "fee_rate_pct": round(100 * fees / notional, 4) if notional else None,
                      "fee_api": self.fee_api, "wallet_change": round(w1 - w0, 6)}
        self._step("체결로 계산한 손익 = 체결 가격 = 지갑 변화(수수료·펀딩 포함)", ok, detail)
        if fills:
            self._step("체결 기록에 수수료가 들어 있음(0이나 음수면 수수료를 못 읽는 것; fee_rate_pct가 실제 수수료율)",
                       detail.get("fees", 0) > 0, {"fee_rate_pct": detail.get("fee_rate_pct"),
                                                   "fee_api": self.fee_api}, fatal=False)
        self._step("요청 한도(429) 답", True, {"429_answers": c.rate_answers}, fatal=False)
        return self.log

    def _trigger_test(self, s: str, sell: str, amt: float, stop_id: str, spec: dict) -> Optional[dict]:
        """The stop moved to TRIGGER_GAP from the last price (on the losing side) and left to fire for real: the
        position must close by itself, and the stop must read as fired. The last and the mark price are watched while
        waiting: which one crossed the level says which price fires a Flipster stop. Not reached in time: noted (not a
        failure), and the cycle closes the position itself."""
        c = self.client
        entry = float(c.position(s)["entryPrice"] or 0)
        start = self.elapsed()
        last = c.price(s)
        shown = [0]
        if entry and self.side * (last - entry * (1 + self.side * PROFIT_GAP)) < 0:
            self._note(f"이익 쪽 손절 시험: 가격이 진입가보다 {PROFIT_GAP * 100:g}% 유리해지기를 기다립니다"
                       f"(최대 {min(PROFIT_WAIT_S, self.trigger_wait_s) / 60:.0f}분). 기다리는 것이 정상입니다: 창을 닫거나 "
                       "Ctrl+C를 누르지 마세요")
        while entry and self.side * (last - entry * (1 + self.side * PROFIT_GAP)) < 0 \
                and self.elapsed() - start < min(PROFIT_WAIT_S, self.trigger_wait_s):
            self.wait(5.0)
            self._waiting(start, shown, "이익 쪽 손절 시험")
            if float(c.position(s)["positionAmt"]) == 0:    # the earlier stop fired while waiting: that is the test
                got = self._fired(stop_id)
                self._step("손절 발동 시험: 가격이 닿자 플립스터가 포지션을 스스로 닫음", got.get("algoStatus") == "TRIGGERED",
                           {"status": got.get("algoStatus"), "actualOrderId": got.get("actualOrderId")}, fatal=False)
                self._fills_of_stop(s, stop_id, got)
                return got
            last = c.price(s)
        level = round_stop(last * (1 - self.side * TRIGGER_GAP), spec["tick"], self.side)
        mv = move_stop(c, s, sell, level, abs(amt), [stop_id], client_id=new_cid())
        profit_side = bool(entry) and self.side * (level - entry) > 0
        if mv["result"] != "moved":
            self._step("손절 발동 시험(진짜로 발동시키기)", True, f"건너뜀: 가격이 이미 손절을 지나 바로 닫혔습니다({mv['result']})",
                       fatal=False)
            return None
        if profit_side:
            rest = [x for x in live_stops(c, s) if x["algoId"] == mv["stop"]["algoId"]]
            self._step("이익 쪽 손절(계단 잠금 자리, 진입가보다 유리한 곳)이 걸림", bool(rest),
                       {"entry": entry, "stop": level}, fatal=False)
        else:
            self._step("이익 쪽 손절(계단 잠금 자리)", True,
                       f"확인 못 함: {min(PROFIT_WAIT_S, self.trigger_wait_s) / 60:.0f}분 안에 가격이 진입가보다 "
                       f"{PROFIT_GAP * 100:g}% 유리하게 가지 않았습니다. 반대 방향(--side short 또는 long)으로 한 번 더 하세요",
                       fatal=False)
        sid = mv["stop"]["algoId"]
        start = self.elapsed()
        shown = [0]
        seen = {"last": [], "mark": []}
        self._note(f"손절 발동 시험: 시험 손절 {level:g}(지금 가격 {last:g})에 가격이 닿기를 기다립니다"
                   f"(최대 {self.trigger_wait_s / 60:.0f}분). 기다리는 것이 정상입니다: 창을 닫거나 Ctrl+C를 누르지 마세요")
        while self.elapsed() - start < self.trigger_wait_s:
            try:
                tk = c.ticker(s)
                seen["last"].append(float(_dec(tk.get("lastPrice"), "lastPrice")))
                seen["mark"].append(float(_dec(tk.get("markPrice"), "markPrice")))
            except TransientError:
                pass
            if float(c.position(s)["positionAmt"]) == 0:
                break
            self.wait(5.0)
            self._waiting(start, shown, "손절 발동 시험")
        flat = float(c.position(s)["positionAmt"]) == 0
        if not flat:
            self._step("손절 발동 시험(진짜로 발동시키기)", True,
                       f"{self.trigger_wait_s / 60:.0f}분 안에 가격이 손절({level:g})에 닿지 않아 발동을 못 봤습니다. "
                       "이 시험만 다시 하려면 drill을 한 번 더 하세요", fatal=False)
            return None
        got = self._fired(sid)
        self._step("손절 발동 시험: 가격이 닿자 플립스터가 포지션을 스스로 닫음", got.get("algoStatus") == "TRIGGERED",
                   {"stop": level, "status": got.get("algoStatus"), "actualOrderId": got.get("actualOrderId")},
                   fatal=False)
        self._step("손절을 발동시킨 가격(마지막 가격 / 마크 가격)", True, trigger_source(self.side, level, seen),
                   fatal=False)
        self._fills_of_stop(s, sid, got)
        return got

    def _fired(self, sid: str) -> dict:
        return self._until(lambda: (lambda o: o if o.get("algoStatus") in ("TRIGGERED", "CANCELED") else None)(
            self._algo_or_empty(sid)), tries=10, pause=1.5) or self._algo_or_empty(sid)

    def _fills_of_stop(self, s: str, sid: str, got: dict) -> None:
        """Whose orderId the fired stop's fills carry: its own (found by orderId), or another one (listed)."""
        c = self.client
        now = c.clock_ms() + c.offset_ms
        try:
            own = c._execs(s, now - 3_600_000, now + 5_000, order_id=sid, exec_type="TRADE")
            other = sorted({str(r.get("orderId")) for r in c._execs(s, now - 1_800_000, now + 5_000, exec_type="TRADE")
                            if c.ledger.by_order(r.get("orderId")) is None})
        except TestnetError as e:
            self._step("발동한 손절의 체결 찾기", False, str(e), fatal=False)
            return
        self._step("발동한 손절의 체결이 손절 자신의 orderId로 기록됨", bool(own),
                   {"own_fills": len(own), "stop": sid, "unknown_orders_with_fills": other[:5],
                    "actualOrderId": got.get("actualOrderId")}, fatal=False)

    def _algo_or_empty(self, sid: str) -> dict:
        try:
            return self.client.algo_order(algo_id=sid)
        except TestnetError:
            return {}


def trigger_source(side: int, level: float, seen: dict) -> dict:
    """Which watched price crossed the stop level (a long's stop: at or below it; a short's: at or above)."""
    crossed = {}
    for k in ("last", "mark"):
        xs = seen.get(k) or []
        crossed[k] = bool(xs) and (min(xs) <= level if side > 0 else max(xs) >= level)
    verdict = {(True, False): "마지막 가격", (False, True): "마크 가격", (True, True): "둘 다 지남(구분 못 함)",
               (False, False): "확인 못 함(5초 사이에 지나감)"}[(crossed["last"], crossed["mark"])]
    return {"verdict": verdict, "level": level,
            "last_extreme": (min if side > 0 else max)(seen["last"]) if seen.get("last") else None,
            "mark_extreme": (min if side > 0 else max)(seen["mark"]) if seen.get("mark") else None}


def row_text(row: dict) -> str:
    return ("[OK]  " if row["ok"] else "[FAIL]") + f" {row['step']}: {row['detail']}"


def leave_flat(c: FlipsterClient, sym: str, add) -> None:
    """After a drill stopped part-way: close the drill coin's position (reduce-only) and cancel its orders and
    stops, each on its own so one failure does not skip the other. ``add(step, ok, detail)`` records the result."""
    try:
        amt = float(c.position(sym)["positionAmt"])
        if amt:
            c.market(sym, "SELL" if amt > 0 else "BUY", abs(amt), reduce_only=True)
    except Exception as e:                     # noqa: BLE001 - the cancel below must still run
        add("정리: 포지션 닫기 실패(앱에서 직접 확인하세요)", False, f"{type(e).__name__}: {e}")
    try:
        cancel_everything(c, sym)
    except Exception as e:                     # noqa: BLE001
        add("정리: 주문·손절 취소 실패(앱에서 직접 확인하세요)", False, f"{type(e).__name__}: {e}")
    try:
        amt = float(c.position(sym)["positionAmt"])
        left = (len(c.open_orders(sym)), len(c.open_algo_orders(sym)))
        add("정리 후 상태", amt == 0 and left == (0, 0), {"positionAmt": amt, "orders": left[0], "stops": left[1]})
    except Exception as e:                     # noqa: BLE001
        add("정리 후 상태(앱에서 직접 확인하세요)", False, f"{type(e).__name__}: {e}")


def _interrupt(signum, frame):
    raise KeyboardInterrupt(signal.Signals(signum).name)


def say(text: str) -> None:
    """Print one drill line now; a closed terminal (after SIGHUP) must not stop the clean-up."""
    try:
        print(text, flush=True)
    except OSError:
        pass


def specs_text(c: FlipsterClient, symbols=COINS) -> str:
    lines = []
    for s in symbols:
        sp = c.spec(s)
        px = c.price(s)
        lines.append(f"{s}: {'API 거래 가능' if sp['tradable'] else 'API 거래 불가'}, 수량 단위 {sp['qty_step_str']} "
                     f"(지금 약 ${sp['qty_step'] * px:,.4f}), 최소 주문 ${sp['min_notional']:g}, 가격 단위 {sp['tick_str']}, "
                     f"최대 {sp['max_leverage']:g}배, 펀딩 {sp.get('funding_interval_hours')}시간마다")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "drill", "reconcile", "specs"])
    ap.add_argument("--symbol", default=None, help="drill order coin (default: the cheapest smallest order)")
    ap.add_argument("--side", choices=["long", "short"], default="long")
    ap.add_argument("--confirm-order", default="", help=f"{DRILL_CONFIRM}: run the one real order cycle")
    ap.add_argument("--no-trigger-test", action="store_true", help="close by hand instead of letting the stop fire")
    args = ap.parse_args(argv)
    try:      # mainnet keys only (specs too: Flipster's contract info is a private endpoint)
        c, kc = clients(MODE_MAINNET, os.environ, read_env_file(PAPER_ENV_FILE))
    except Refused as e:
        print(f"시작하지 않습니다: {e}", file=sys.stderr)
        return 2
    c.sync_time()
    if args.cmd == "specs":
        print(f"서버 시간 차이 {c.offset_ms} ms ({c.time_source})")
        print(specs_text(c))
        return 0
    if args.cmd == "reconcile":
        print(json.dumps(reconcile(c, args.symbol or "BTCUSDT"), indent=1))
        return 0
    pace(c)
    d = FlipsterDrill(c, symbol=args.symbol, side=1 if args.side == "long" else -1, keycheck=kc,
                      trigger_test=not args.no_trigger_test, say=say)
    # a closed terminal (SIGHUP) or a stop (SIGTERM) mid-drill: leave the account flat before exiting
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _interrupt)
    return 0 if run_drill(c, d, args.cmd, args.confirm_order == DRILL_CONFIRM, signals=True) else 1


def run_drill(c: FlipsterClient, d: FlipsterDrill, cmd: str, confirmed: bool, pause=time.sleep,
              signals: bool = False) -> bool:
    """check, then (drill + the confirmation only) the order cycle. Any stop part-way (a failed step, an error, Ctrl+C,
    a closed terminal) leaves the drill coin flat with no order or stop left. True when every step is [OK]."""
    orders = cmd == "drill" and confirmed
    ok = True
    try:
        d.check()
        if orders:
            d._note(f"진짜 주문 시험을 시작합니다(최대 약 {(TRIGGER_WAIT_S + PROFIT_WAIT_S) / 60 + 5:.0f}분). "
                    "'끝:' 줄이 나올 때까지 이 창을 닫지 마세요")
            pause(DRILL_PAUSE_S)
            d.order_cycle()
        elif cmd == "drill":
            d.add("주문 단계", True, f"건너뜀: 진짜 주문 한 번은 --confirm-order {DRILL_CONFIRM} 를 붙일 때만 합니다")
    except (Exception, KeyboardInterrupt) as e:  # noqa: BLE001 - any stop part-way leaves the account flat
        if signals:
            for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                signal.signal(sig, signal.SIG_IGN)   # the clean-up itself runs to its end
        d.add("멈춤", False, f"{type(e).__name__}: {e}")
        ok = False
        if orders and d.symbol:
            leave_flat(c, d.symbol, d.add)
    ok = ok and all(r["ok"] for r in d.log)
    bad = [r["step"] for r in d.log if not r["ok"]]
    if d.say:
        d.say(f"끝: {cmd} " + ("모두 [OK]" if ok else f"[FAIL] {len(bad)}개 — {', '.join(bad)}"))
    return ok


if __name__ == "__main__":
    hide_process_memory()
    sys.exit(main())
