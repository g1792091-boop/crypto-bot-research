"""WOO X Pro USDT perpetual futures (cloud-api.wooxpro.com) for the executor: client, host allowlist, keys, key check,
drill. ``"exchange": "wooxpro"`` in the executor config uses it (mainnet only: WOO X Pro has no futures testnet); the
Binance, Bybit and MEXC paths are unchanged. Owners 10-20: "바이비트 + WOO X Pro" (docs/wooxpro-ko.md).

    python -m paperbot.wooxpro specs                       # the 6 coins' live contract specs (public, no key needed)
    python -m paperbot.wooxpro check                       # read-only checks + one-way mode + leverage 40/30 (no order)
    python -m paperbot.wooxpro check --leverage 35         # ... every coin at 35x, and the largest position 35x allows
    python -m paperbot.wooxpro check --leverage 35 --stop-net-roe 0.5   # ... and the liquidation against the stop
    python -m paperbot.wooxpro drill --confirm-order REAL_ORDER [--symbol DOGEUSDT]   # + one smallest-size order cycle
                                                           # and the stop-trigger test (--no-trigger-test skips it)

WOO X Pro (formerly NovaEx) runs the BitMart futures API family. Sources (read as data, 2026-10-20):
- WOO X Pro's own API docs, developer.wooxpro.com (llms-full.txt): base URL https://cloud-api.wooxpro.com, the
  headers X-API-KEY / X-API-TIMESTAMP (ms) / X-API-SIGN = hex HMAC-SHA256(secret, timestamp + '#' + memo + '#' + the
  query string (GET) or the JSON body (POST)), a timestamp within one minute, answers {code: 1000, message, data,
  trace}, the error code table, the rate limits (per endpoint and 2 s), contract details (contract_size,
  vol_precision, min_volume, price_precision, max_leverage, status), K-line (step 1 = 1 minute, times in seconds, at
  most 500 rows), submit-order (side 1 buy open long, 2 buy close short, 3 sell close long, 4 sell open short; type
  market; size = contracts, an integer; leverage; open_type isolated; client_order_id letters and digits only, at most
  32), order detail (state 1 approval / 2 check = open, 4 finish), TP/SL orders (submit-tp-sl-order type stop_loss,
  price_type 1 = last price, plan_category 1, category market), current-plan-order, cancel-plan-order, position
  (current_amount contracts, position_type 1 long / 2 short), position-v2 (leverage and open_type even without a
  position), position mode, submit-leverage, assets-detail (equity, unrealized), trades (realised_profit, paid_fees,
  start / end in seconds, at most 200 rows), transaction-history (Funding Fee, Transfer; times in ms).
- ccxt 4.4.50 (pypi) ccxt/bitmart.py, the same API family: the signature string timestamp#memo#payload with the GET
  query as sent (sign, bitmart.py:5036-5066), the one-way meaning of the side codes (2 and 3 reduce only:
  create_swap_order_request, 2785-2803), the order state 1 / 2 open, 4 completed (parse_order_status_by_type,
  2509-2531), a position's contracts = current_amount and side = position_type (parse_position, 4579-4606), the error
  codes (330-509) and the server time at /system/time ({server_time} in ms, 856-873).
What only a live run can confirm is listed in docs/wooxpro-ko.md (the drill checks each, and its trigger test lets one
stop fire for real).

The client answers in the SAME shapes the executor reads from the Binance client (paperbot/testnet.py), like
paperbot/mexc.py, so the executor, the stop protocol (place_stop / move_stop / live_stops / covers) and livepnl run
unchanged. Quantities: WOO X Pro counts contracts (``size``, an integer); base quantity = contracts x contract_size
from the live contract details, never a hard-coded size.

  Binance client call          WOO X Pro (cloud-api.wooxpro.com)
  spec(symbol)                 GET  /contract/public/details (all contracts, cached 5 s)
  price / mark                 GET  /contract/public/details?symbol= last_price / markprice-kline (step 1) last close
  klines (1m)                  GET  /contract/public/kline step 1 (last price; seconds; <= 500 rows a request)
  sync_time                    GET  /system/time (else the funding-rate answer's timestamp)
  account()                    GET  /contract/private/assets-detail  USDT equity; wallet = equity - unrealized
  one_way()                    GET  get-position-mode; hedge_mode -> POST set-position-mode one_way_mode
  isolated(symbol)             POST submit-leverage open_type isolated (BTC 40x, others 30x), read back with
                               position-v2?symbol (it answers leverage and open_type without a position too)
  market(...)                  POST submit-order type market, side 1 / 4 open, 3 / 2 close (reduce only), size,
                               client_order_id, then read back by id (GET /contract/private/order)
  order(symbol, id / cid)      GET  /contract/private/order, or order-history?client_order_id= (and the open list)
  stop_close(...)              POST submit-tp-sl-order type stop_loss, side 3 (closes a long) / 2 (a short), size =
                               the position's contracts, trigger_price, executive_price = trigger, price_type 1 (last
                               price), plan_category 1, category market, client_order_id
  algo_order / open_algo_orders GET current-plan-order (resting); a stop no longer resting: order-history (by its id,
                               or the market order it placed: client_order_id "PLAN_<id>")
  cancel_algo / cancel_all_algo POST cancel-plan-order {symbol, order_id} (each resting one for cancel_all_algo)
  cancel_all / open_orders     POST cancel-orders / GET get-open-orders
  position / positions         GET  /contract/private/position   current_amount x contract_size, position_type 1 / 2
  user_trades                  GET  /contract/private/trades -> fills; realized P&L replayed from the fills' prices and
                               cross-checked against each fill's realised_profit (paperbot/mexc.py fills_from_deals)
  income                       GET  transaction-history flow_type 3 (FUNDING_FEE) and 1 (TRANSFER)

Why the stop is a TP/SL order (type stop_loss), not a plan order: a stop_loss on the close side says what it is (it
fires when the last price falls to the trigger for a long, rises for a short); a plan order's direction rests on
``price_way``, whose meaning the docs leave to one word. Its side (3 / 2) closes only, so it can never open or flip a
position. A moved stop is a new order first, confirmed in the list, then the old one cancelled (the executor's
protocol); it is never amended in place. The drill checks that two can rest at once and lets one fire for real.

Safety:
- ``WooXProClient`` talks to cloud-api.wooxpro.com only (class-level allowlist, https only, checked at construction;
  the executor checks again). Mainnet only.
- Keys: WOOXPRO_LIVE_KEY / WOOXPRO_LIVE_SECRET / WOOXPRO_LIVE_MEMO behind PAPERBOT_LIVE_MAINNET=I_UNDERSTAND; never the
  paper runner's key, a Binance, Bybit or MEXC key.
- Key gate: the API does not report a key's permissions. The gate proves the key reads the futures account and the
  position mode; "futures trade only, server IP bound" is the owners' statement
  WOOXPRO_LIVE_KEY_CHECKED=FUTURES_ONLY_NO_WITHDRAW_IP_BOUND (refused without it), shown as a warning at every start
  (the key page offers no withdrawal permission at all).
- An order that was accepted (it has an id) is never reported as not executed; a lost answer is looked up by its
  client_order_id; an opening order is never sent twice.
- A position's size, the account equity and the stop list are never read as 0 / flat / empty from a missing or garbled
  field: such an answer is an error.
- AI agents never import this module (tests/test_wooxpro.py checks it).
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
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Callable, Optional

from . import bybit as BY
from . import mexc as MX
from .livepnl import balanced
from .mainnet import (FLAG, FLAG_VALUE, LIVE_KEY_NAMES as BINANCE_LIVE_KEY_NAMES, MODE_MAINNET, PAPER_ENV_FILE,
                      PAPER_KEY_NAMES, TESTNET_KEY_NAMES as BINANCE_TESTNET_KEY_NAMES, Refused, check_permissions,
                      read_env_file)
from .testnet import (BAD_TIMESTAMP, NOT_FOUND, WOULD_TRIGGER, RateLimited, TestnetError,
                      TransientError, cancel_everything, covers, hide_process_memory, live_stops, move_stop,
                      place_stop, round_stop, urllib_send)

SETTLE = "USDT"
WOOX_BASE = "https://cloud-api.wooxpro.com"
WOOX_HOSTS = ("cloud-api.wooxpro.com",)
PUBLIC = "/contract/public"
PRIVATE = "/contract/private"
LIVE_KEY_NAMES = ("WOOXPRO_LIVE_KEY", "WOOXPRO_LIVE_SECRET")
MEMO_NAME = "WOOXPRO_LIVE_MEMO"                       # the API key's memo: part of every signature
KEY_CHECKED = "WOOXPRO_LIVE_KEY_CHECKED"              # the owners' statement: what the API cannot report
KEY_CHECKED_VALUE = "FUTURES_ONLY_NO_WITHDRAW_IP_BOUND"
DRILL_CONFIRM = "REAL_ORDER"
# the docs name no minimum order value: the executor's spec carries 5 USDT (MEXC's) as a floor that never binds the
# bot's ~$1,000 orders; the drill orders a bit above it
MIN_ORDER_USDT = 5.0
DRILL_ORDER_USDT = 6.0
DRILL_MIN_GAP_S = 1.0                                 # the first live check (10-20) hit the account rate limit at 0.35 s
DRILL_PAUSE_S = 3.0
TRIGGER_GAP = 0.001                                   # the trigger test's stop: 0.1 % from the last price
TRIGGER_WAIT_S = 1200                                 # ... waited for at most 20 minutes
PROFIT_GAP = 0.0015                                   # first the price is waited for 0.15 % past the entry, so the test
PROFIT_WAIT_S = 600                                   # stop rests on the profit side (a lock's place); at most 10 min
# (0.3 % was not reached in the owners' first drill, 10-20: 0.15 % still puts the stop 0.05 % past the entry)
FIXED_LEVERAGE = MX.FIXED_LEVERAGE                    # owners 2026-10-17: BTC 40x, the other coins 30x
DEFAULT_LEVERAGE = MX.DEFAULT_LEVERAGE
COINS = MX.COINS
PREFIX = {MODE_MAINNET: "[WOO X Pro 실거래 실행기]"}
# the liquidation before a stop (owners 10-24, WOO X Pro 2: 35x, a stop 1.30 % away): the stop must sit at least this
# much of the price nearer than the estimated liquidation (room for the mark-last gap, the fees and the stop's market
# fill in a fast move), else the executor does not enter (``check --leverage --stop-net-roe`` shows it per coin)
LIQ_ROOM = 0.002
WOO_COST = {"taker_fee": 0.00042, "slippage": 0.0002}   # the executors' net_costs for WOO X Pro (one side)


def liq_distance(lev: float, mmr: float) -> float:
    """How far (a fraction of the entry price) an isolated position at ``lev`` is from its liquidation: its margin
    1 / ``lev`` less the maintenance margin ratio of its size's bracket (the bracket's maintenance amount ``cum`` is
    left out: a little nearer than the exchange's own; the fees are what LIQ_ROOM is for)."""
    return 1.0 / float(lev) - float(mmr)

BUY_OPEN, BUY_CLOSE, SELL_CLOSE, SELL_OPEN = 1, 2, 3, 4   # buy open long / buy close short / sell close long / ...
CLOSE_CODES = (BUY_CLOSE, SELL_CLOSE)
ONE_WAY, HEDGE = "one_way_mode", "hedge_mode"
ISOLATED = "isolated"
PRICE_LAST = 1                                       # trigger price type: 1 last price, 2 fair (mark) price
WORKING_TYPE = {1: "CONTRACT_PRICE", 2: "MARK_PRICE"}
OK_CODE = 1000
OPEN_STATES = (1, 2)                                 # order state 1 approval, 2 check (open); 4 finish
FINISHED = 4
ORDER_FINAL = ("FILLED", "CANCELED", "REJECTED", "EXPIRED")
ORDER_WAITS = (0.05, 0.1, 0.2, 0.4)                  # a market order is read back after these
KLINE_ROWS = 500
TRADES_CAP = 200                                     # trades / order-history: at most 200 rows a request
INCOME_CAP = 1000                                    # transaction-history page_size max
FLOW_NAMES = {1: "transfer", 3: "funding fee"}       # transaction-history ``type`` of the rows income() books
SPAN_MS = 89 * 86_400_000                            # trades / order-history: start and end at most 90 days apart

# error codes (WOO X Pro docs "Restful Error Code"; ccxt bitmart.py 330-509)
TIME_CODES = (30007, 30008, 40013)                   # the request time is off: refused, not executed
RATE_CODES = (30013,)
BAN_CODES = (30017,)
TRANSIENT_CODES = (30014, 30016, 40012)              # unavailable / maintenance / system error
NOT_FOUND_CODES = (40035, 40037, 40002)              # order not exist / order id not exist / out_trade_no not found
GONE_CODES = (40036,)                                # the order status is invalid (already finished)
DUPLICATE_CID = 40050                                # client_order_id used before: the order exists
REGION_CODES = (40047, 53008)                        # not available in this country / area
# requests per 2 s (WOO X Pro docs "Rate Limit"); private ones count per key, public ones per IP
RATE_WINDOW_MS = 2000
RATE = {"details": 12, "kline": 12, "markprice_kline": 12, "funding_rate": 12, "time": 12,
        "submit_order": 24, "cancel_order": 40, "cancel_orders": 2, "open_orders": 50, "order": 50,
        "order_history": 6, "plan_list": 50, "tpsl_submit": 24, "plan_cancel": 40, "trades": 6, "transactions": 6,
        "fee_rate": 2, "position": 6, "position_v2": 6, "position_mode": 2, "position_mode_set": 2,
        "leverage_set": 24, "assets": 12, "leverage_bracket": 12}
DEFAULT_RATE = 6
READ_RETRIES = 3                                     # a read refused for the rate (429): read again after a pause
READ_PAUSE_S = 1.0                                   # ... of 1 s, 2 s, 3 s
# writes that may be sent again after a 429 (refused, nothing ran): settings, cancels, and a stop (its client_order_id
# makes a second copy impossible: 40050). Never an opening market order (market(): an unknown outcome, looked up)
RETRY_POSTS = frozenset({"position_mode_set", "leverage_set", "cancel_order", "cancel_orders", "plan_cancel",
                         "tpsl_submit"})


def hosts_for(mode: str) -> tuple:
    return WOOX_HOSTS                      # one host list: mainnet only


# ---------------------------------------------------------------- numbers and names
def _dec(v, what: str = "value") -> Decimal:
    """A number the decision depends on (a size, a price, the equity): missing or garbled is an error, never 0."""
    if v is None or v == "" or isinstance(v, bool):
        raise TransientError(200, None, f"WOO X Pro 응답에 {what} 값이 없습니다")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError) as e:
        raise TransientError(200, None, f"WOO X Pro 응답의 {what} 값이 이상합니다: {v!r}") from e
    if not d.is_finite():
        raise TransientError(200, None, f"WOO X Pro 응답의 {what} 값이 이상합니다: {v!r}")
    return d


_f, _num, _int, _price_str, _id60 = MX._f, MX._num, MX._int, MX._price_str, MX._id60

_CID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def ext_id(client_id: Optional[str]) -> str:
    """The client_order_id for an executor client id: letters and digits only, at most 32 (errors 40048 / 40049).
    Deterministic, so a look-up after a lost answer finds the order."""
    if client_id is None:
        return "pb" + hashlib.sha1(f"{time.time_ns()}|{os.getpid()}".encode()).hexdigest()[:24]
    if 0 < len(client_id) <= 32 and set(client_id) <= _CID_OK:
        return client_id
    return "pbh" + hashlib.sha1(client_id.encode()).hexdigest()[:29]


def query_string(params: dict) -> str:
    """The GET query, exactly as sent and signed: sorted by name, URL-encoded, booleans as true/false."""
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
    """The POST body exactly as sent and signed (compact JSON)."""
    return json.dumps(body, separators=(",", ":"))


def signature(secret: str, ts: str, memo: str, payload: str) -> str:
    return hmac.new(secret.encode(), f"{ts}#{memo}#{payload}".encode(), hashlib.sha256).hexdigest()


def mx_side(code: int) -> int:
    """WOO X Pro side code -> paperbot/mexc.py's (1 open long, 2 close short, 3 open short, 4 close long)."""
    return {BUY_OPEN: MX.OPEN_LONG, BUY_CLOSE: MX.CLOSE_SHORT, SELL_CLOSE: MX.CLOSE_LONG,
            SELL_OPEN: MX.OPEN_SHORT}.get(code, 0)


def fills_from_trades(rows: list, contract_size, symbol: str) -> list:
    """WOO X Pro trades -> Binance userTrades-like fills (paperbot/mexc.py fills_from_deals: realized P&L replayed from
    the fills' own prices, cross-checked against each fill's ``realised_profit``)."""
    deals = []
    for r in rows:
        code = _int(r.get("side"))
        if code not in (BUY_OPEN, BUY_CLOSE, SELL_CLOSE, SELL_OPEN):
            raise TransientError(200, None, f"{symbol}: 체결 방향이 이상합니다({r.get('side')!r})")
        fee = r.get("paid_fees")
        deals.append({"id": r.get("trade_id"), "orderId": r.get("order_id"), "vol": r.get("vol"),
                      "price": r.get("price"), "side": mx_side(code), "timestamp": r.get("create_time"),
                      "profit": r.get("realised_profit"), "fee": fee, "feeCurrency": SETTLE,
                      "isTaker": str(r.get("exec_type") or "").lower() == "taker"})
    out = MX.fills_from_deals(deals, contract_size, symbol)
    for f in out:
        f["wooSide"] = {v: k for k, v in ((c, mx_side(c)) for c in (1, 2, 3, 4))}.get(f.pop("mexcSide"))
        f["wooProfit"] = f.get("mexcProfit")
    return out


def permission_record(attested: bool, position_mode) -> dict:
    """The Binance apiRestrictions fields mainnet.check_permissions reads. WOO X Pro reports no key permissions: reading
    the futures account and the position mode is what this key was seen to do; "futures trade only, server IP bound"
    is the owners' statement (``attested``), never assumed."""
    extra = []
    if not attested:
        extra.append(f"WOO X Pro는 키 권한을 API로 알려 주지 않습니다. 키를 '읽기 전용, 선물 거래 + 서버 IP'로 만든 것을 "
                     f"확인한 뒤 /etc/paperbot/executor.env에 {KEY_CHECKED}={KEY_CHECKED_VALUE} 를 넣으세요")
    return {
        "enableReading": True,
        "enableWithdrawals": False if attested else None,
        "enableFutures": position_mode in (ONE_WAY, HEDGE),
        "ipRestrict": True if attested else None,
        "extraProblems": extra,
        "warnings": [f"WOO X Pro는 키 권한을 API로 알려 주지 않습니다. 확인한 것: 선물 계정 읽기, 포지션 모드 읽기. "
                     f"선물 거래 권한·서버 IP 제한은 두 분이 확인한 내용({KEY_CHECKED})입니다"] if attested else [],
        "attested": attested, "positionMode": position_mode,
    }


# ---------------------------------------------------------------- client
class WooXProClient:
    """Signed REST client for WOO X Pro USDT perpetuals, real money only. Answers are translated into the Binance
    client's shapes (see the module docstring)."""
    __test__ = False
    HOSTS: tuple = WOOX_HOSTS
    DEFAULT_BASE = WOOX_BASE
    KEY_NAMES = LIVE_KEY_NAMES
    AGENT = "paperbot-wooxpro-live/0.1"
    EXCHANGE = "wooxpro"
    PNL_RECORD = "WOO X Pro 체결 realised_profit"
    # a stop bigger than the position is replaced by one of the position's size (the executor's _cover)
    EXACT_STOP_SIZE = True
    # the executor adds a random part to its stop and close ids: a client_order_id used before is refused (40050)
    UNIQUE_CLIENT_IDS = True

    def __init__(self, api_key: str, api_secret: str, memo: str, base: Optional[str] = None, send=None,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                 on_request: Optional[Callable[[dict], None]] = None, sleep: Callable[[float], None] = time.sleep,
                 public_only: bool = False):
        base = (base or self.DEFAULT_BASE).rstrip("/")
        u = urllib.parse.urlparse(base)
        host = u.hostname or ""
        if host not in type(self).HOSTS or u.scheme != "https" or u.path not in ("",) or u.port not in (None, 443):
            raise ValueError(f"refusing {base!r}: {type(self).__name__} only talks to https://{type(self).HOSTS}")
        if not public_only and not (api_key and api_secret and memo):
            raise ValueError(f"{self.KEY_NAMES[0]}, {self.KEY_NAMES[1]} and {MEMO_NAME} are required")
        self.base, self.host, self.key, self.secret, self.memo = base, host, api_key, api_secret, memo
        self.public_only = public_only
        self.send = send or urllib_send
        self.clock_ms = clock_ms
        self.sleep = sleep
        self.offset_ms = 0
        self.time_source = "local"
        self.on_request = on_request
        self.specs: dict = {}            # BTCUSDT -> spec (live contract details, cached for the process)
        self.detail_ms: Optional[int] = None
        self.hits: dict = {}             # rate-limit key -> request times (ms) in the last window
        self.order_symbol: dict = {}     # order / stop id -> symbol (a cancel or a history read needs the symbol)
        self.stop_by_cid: dict = {}      # client_order_id -> stop id (answers we got)
        self.cid_by_stop: dict = {}      # stop id -> client_order_id
        self.pending_stops: dict = {}    # client_order_id -> (symbol, side code, trigger, size, sent ms)
        self.pos_rows: dict = {}         # symbol -> the last position row (open type, leverage for a close order)
        self.lev: dict = {}              # symbol -> leverage set by leverage()
        self.kline_source = ""           # klines(): "last" (the last price's candles) or "mark" (those were empty)

    # ------------------------------------------------------------ transport
    def _now(self) -> int:
        return int(self.clock_ms() + self.offset_ms)

    def _recent(self, key: str) -> list:
        now = self.clock_ms()
        return [t for t in self.hits.get(key, []) if now - t < RATE_WINDOW_MS]

    def _pace(self, key: str) -> None:
        """Never past an endpoint's own limit: wait until its oldest request in the window leaves it (at most 2 s)."""
        lst = self._recent(key)
        limit = RATE.get(key, DEFAULT_RATE)
        if len(lst) >= limit:
            wait = (min(lst) + RATE_WINDOW_MS - self.clock_ms()) / 1000.0
            if wait > 0:
                self.sleep(min(wait, RATE_WINDOW_MS / 1000.0))
        lst = self._recent(key)
        lst.append(self.clock_ms())
        self.hits[key] = lst

    def throttle_s(self, share: float = 0.8) -> float:
        """Seconds to wait before the next loop: an endpoint that used ``share`` of its limit waits until the oldest
        request leaves the 2 s window."""
        now = self.clock_ms()
        wait = 0.0
        for key in list(self.hits):
            recent = self._recent(key)
            if len(recent) >= share * RATE.get(key, DEFAULT_RATE):
                wait = max(wait, (min(recent) + RATE_WINDOW_MS - now) / 1000.0)
        return max(0.0, min(wait, RATE_WINDOW_MS / 1000.0))

    def req(self, method: str, path: str, params=None, signed: bool = True, limit_key: Optional[str] = None):
        """One request. ``params``: the GET query or the POST body (a dict). Returns the answer's ``data``. A read (GET)
        refused for the request rate (429, code 30013; the owners' first live check 10-20 got "(U)Request too many
        requests", a per-account limit the docs do not size) is read again after a pause, at most READ_RETRIES times;
        so is a RETRY_POSTS write. Any other POST is never sent again here (the executor decides)."""
        for attempt in range(READ_RETRIES + 1):
            try:
                return self._req_once(method, path, params, signed, limit_key)
            except RateLimited as e:
                again = method == "GET" or (limit_key or path) in RETRY_POSTS
                if not again or e.status != 429 or attempt == READ_RETRIES:
                    raise
                self.sleep(min(max(float(getattr(e, "retry_after", 0) or 0), READ_PAUSE_S * (attempt + 1)), 5.0))
        raise AssertionError("unreachable")

    def _req_once(self, method: str, path: str, params=None, signed: bool = True, limit_key: Optional[str] = None):
        if signed and self.public_only:
            raise TestnetError(400, "NO_KEY", "키 없이 만든 클라이언트라 개인 API를 부르지 않습니다")
        audit = {"method": method, "path": path, "params": dict(params or {})}
        headers = {"User-Agent": self.AGENT, "Accept": "application/json"}
        if method in ("GET", "DELETE"):
            payload = query_string(params or {})
            body = None
            url = f"{self.base}{path}" + (f"?{payload}" if payload else "")
        else:
            body_obj = {k: v for k, v in (params or {}).items() if v is not None}
            audit["params"] = dict(body_obj)
            payload = body_string(body_obj)
            body = payload.encode()
            url = f"{self.base}{path}"
            headers["Content-Type"] = "application/json"
        if signed:
            ts = str(self._now())
            headers.update({"X-API-KEY": self.key, "X-API-TIMESTAMP": ts, "Content-Type": "application/json",
                            "X-API-SIGN": signature(self.secret, ts, self.memo, payload)})
        self._pace(limit_key or path)
        try:
            res = self.send(method, url, headers, body)
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
        code = data.get("code") if isinstance(data, dict) else None
        if isinstance(code, str) and code.lstrip("-").isdigit():
            code = int(code)
        msg = (data.get("message") if isinstance(data, dict) else None) or str((raw or b"")[:200])
        err: Optional[TestnetError] = None
        if status >= 500 or status in (0, 408):
            # a server error first, whatever code it carries: the request may have run (looked up, never resent)
            err = TransientError(status, code, msg or "server error")
        elif status == 429:
            try:
                after = float(hdr.get("retry-after") or 2.0)
            except ValueError:
                after = 2.0
            err = RateLimited(429, code, msg or "rate limited", after)
        elif status in (403, 418) and code not in REGION_CODES:
            # an IP block or a ban: never retried in the request, the loop waits (the executor's 418 ban handling)
            err = RateLimited(418, code, f"HTTP {status} (IP 차단·허용 안 된 IP·막힌 지역): {msg}"[:300], 300.0)
        elif isinstance(code, int) and code != OK_CODE:
            err = self._error(code, msg, status)
        elif status != 200:
            err = TestnetError(status, code, msg)
        elif not isinstance(data, dict) or code != OK_CODE:
            err = TransientError(status, None, f"응답이 WOO X Pro 형식(code 1000)이 아닙니다: {msg}"[:200])
        self._audit(audit, status=status, data=data, err=err)
        if err is not None:
            raise err
        return data.get("data")

    def _error(self, code: int, msg: str, status: int = 400) -> TestnetError:
        text = f"{msg} (WOO X Pro code {code})"
        if code in TIME_CODES:
            err = TestnetError(400, BAD_TIMESTAMP, text)
        elif code in RATE_CODES:
            err = RateLimited(429, code, text, 2.0)
        elif code in BAN_CODES:
            err = RateLimited(418, code, text, 300.0)
        elif code in TRANSIENT_CODES:
            err = TransientError(status or 400, code, text)
        elif code in NOT_FOUND_CODES:
            err = TestnetError(400, NOT_FOUND[0], text)
        elif code in GONE_CODES:
            err = TestnetError(400, NOT_FOUND[1], text)
        elif code in REGION_CODES:
            err = TestnetError(403, code, f"이 지역에서는 WOO X Pro API를 쓸 수 없다는 답입니다: {text}")
        else:
            err = TestnetError(status if status and status != 200 else 400, code, text)
        err.ret_code = code
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
        """The server clock: /system/time (BitMart's), else the funding-rate answer's timestamp. Neither: the local
        clock (the signature's one-minute window still refuses a clock that is far off, code 30007)."""
        for path, key, field_ in (("/system/time", "time", "server_time"),
                                  (PUBLIC + "/funding-rate", "funding_rate", "timestamp")):
            t0 = self.clock_ms()
            try:
                data = self.req("GET", path, {"symbol": "BTCUSDT"} if key == "funding_rate" else None, signed=False,
                                limit_key=key)
            except (TransientError, RateLimited):
                raise
            except TestnetError:
                continue
            t1 = self.clock_ms()
            server = _int((data or {}).get(field_) if isinstance(data, dict) else None, 0)
            if server > 10 ** 12:
                self.offset_ms = server - (t0 + t1) // 2
                self.time_source = path
                return self.offset_ms
        self.offset_ms, self.time_source = 0, "local"
        return 0

    def _load_detail(self) -> None:
        now = self.clock_ms()
        if self.detail_ms is not None and now - self.detail_ms < 5_000:
            return
        data = self.req("GET", PUBLIC + "/details", signed=False, limit_key="details")
        self.detail_ms = now
        rows = (data or {}).get("symbols") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise TransientError(200, None, f"계약 정보 응답이 이상합니다: {str(data)[:80]!r}")
        for row in rows:
            if not isinstance(row, dict) or row.get("quote_currency") != SETTLE or _int(row.get("product_type")) != 1:
                continue
            try:
                self.specs[str(row.get("symbol"))] = self._spec_row(row)
            except TestnetError:
                continue                                   # a contract with garbled units is never traded

    @staticmethod
    def _spec_row(row: dict) -> dict:
        cs, vp = _dec(row.get("contract_size"), "contract_size"), _dec(row.get("vol_precision"), "vol_precision")
        mv, pp = _dec(row.get("min_volume"), "min_volume"), _dec(row.get("price_precision"), "price_precision")
        if cs <= 0 or vp <= 0 or mv <= 0 or pp <= 0:
            raise TestnetError(400, "BAD_SPEC", f"{row.get('symbol')}: 계약 단위 정보가 이상합니다")
        unit = max(vp, Decimal(1))                         # size is an integer number of contracts
        if unit != unit.to_integral_value():
            unit = unit.to_integral_value(rounding=ROUND_FLOOR) + 1
        mv = max(mv, unit)
        maxv = row.get("market_max_volume") or row.get("max_volume")
        return {"qty_step": float(cs * unit), "min_qty": float(cs * mv), "tick": float(pp),
                "min_notional": MIN_ORDER_USDT, "max_leverage": _f(row.get("max_leverage")),
                "status": row.get("status"), "contract_size": _num(cs), "vol_unit": _num(unit), "min_vol": _num(mv),
                "price_unit": _num(pp), "max_vol": _num(_dec(maxv, "max_volume")) if maxv not in (None, "") else None,
                "tick_str": _num(pp), "qty_step_str": _num(cs * unit), "base_coin": row.get("base_currency"),
                "last_price": row.get("last_price"), "funding_interval_hours": row.get("funding_interval_hours"),
                "delist_time": row.get("delist_time")}

    def spec(self, symbol: str) -> dict:
        """The contract's live spec (cached): sizes in base units for the executor (qty_step = contract_size x one
        contract, min_qty = contract_size x min_volume, tick = price_precision), the raw contract units."""
        if symbol not in self.specs:
            self._load_detail()
        if symbol not in self.specs:
            raise TestnetError(400, "NO_SYMBOL", f"{symbol}: WOO X Pro USDT 무기한 계약에 없습니다")
        return dict(self.specs[symbol])

    def _spec(self, symbol: str) -> dict:
        return self.specs.get(symbol) or self.spec(symbol)

    def _contracts(self, symbol: str, qty: float) -> int:
        """A base quantity -> whole contracts (a multiple of the unit), floored (never more than asked)."""
        sp = self._spec(symbol)
        step = Decimal(sp["contract_size"]) * Decimal(sp["vol_unit"])
        n = (Decimal(repr(float(qty))) / step + Decimal("1e-9")).to_integral_value(rounding=ROUND_FLOOR)
        return int(n * Decimal(sp["vol_unit"]))

    def _qty(self, symbol: str, size) -> Decimal:
        return _dec(size, "size") * Decimal(self._spec(symbol)["contract_size"])

    def _check_size(self, symbol: str, size: int, qty: float, what: str) -> None:
        sp = self._spec(symbol)
        if size <= 0 or size < int(Decimal(sp["min_vol"])):
            raise TestnetError(400, "QTY_ZERO", f"{symbol}: {what} 수량 {qty}이 최소({sp['min_vol']}계약 = "
                                                f"{sp['min_qty']:g})보다 작습니다")
        if sp.get("max_vol") and size > Decimal(sp["max_vol"]):
            raise TestnetError(400, "QTY_MAX", f"{symbol}: {what} {size}계약이 최대 {sp['max_vol']}계약을 넘습니다")

    def _detail(self, symbol: str) -> dict:
        data = self.req("GET", PUBLIC + "/details", {"symbol": symbol}, signed=False, limit_key="details")
        rows = (data or {}).get("symbols") if isinstance(data, dict) else None
        row = next((r for r in rows or [] if isinstance(r, dict) and r.get("symbol") == symbol), None)
        if row is None:
            raise TransientError(200, None, f"{symbol}: 시세가 비어 있습니다")
        return row

    def price(self, symbol: str) -> float:
        """Last traded price: what the stops trigger on (price_type 1)."""
        return float(_dec(self._detail(symbol).get("last_price"), "last_price"))

    def mark(self, symbol: str) -> float:
        now = self._now()
        data = self.req("GET", PUBLIC + "/markprice-kline", {"symbol": symbol, "step": 1,
                                                              "start_time": now // 1000 - 300, "end_time": now // 1000},
                        signed=False, limit_key="markprice_kline")
        rows = [r for r in data or [] if isinstance(r, dict)] if isinstance(data, list) else []
        if not rows:
            raise TransientError(200, None, f"{symbol}: 마크 가격이 비어 있습니다")
        last = max(rows, key=lambda r: _int(r.get("timestamp")))
        return float(_dec(last.get("close_price"), "mark close"))

    def klines(self, symbol: str, start_ms: int, end_ms: int) -> list:
        """1m candles opened in [start_ms, end_ms], the one still forming included: [(open ms, high, low, close)], oldest
        first. The last price's candles first (what the stops trigger on, price_type 1): GET /contract/public/kline step
        1, start and end in SECONDS, at most 500 rows a request (read in pieces of 480 minutes). That endpoint answered
        an empty list for every coin and range on the owners' server (10-20) while the mark price's candles
        (/contract/public/markprice-kline, the same shape) came back: an empty answer is read again from those
        (``kline_source`` says which one answered). Neither has a row: []."""
        rows = self._kline_rows("/kline", symbol, start_ms, end_ms)
        self.kline_source = "last"
        if not rows:
            rows = self._kline_rows("/markprice-kline", symbol, start_ms, end_ms)
            self.kline_source = "mark"
        return rows

    def _kline_rows(self, path: str, symbol: str, start_ms: int, end_ms: int) -> list:
        lo = int(start_ms) - int(start_ms) % 60_000
        out = {}
        a = lo
        while a <= int(end_ms):
            b = min(int(end_ms), a + 480 * 60_000)
            data = self.req("GET", PUBLIC + path, {"symbol": symbol, "step": 1, "start_time": a // 1000,
                                                   "end_time": max(b // 1000, a // 1000 + 1)},
                            signed=False, limit_key="kline")
            if not isinstance(data, list):
                raise TransientError(200, None, f"{symbol}: 1분봉 응답이 목록이 아닙니다 {str(data)[:80]!r}")
            for r in data:
                if not isinstance(r, dict):
                    raise TransientError(200, None, f"{symbol}: 1분봉 응답의 모양이 다릅니다")
                ms = int(_dec(r.get("timestamp"), "timestamp"))
                ms = ms * 1000 if ms < 10 ** 11 else ms
                if lo <= ms <= int(end_ms):
                    out[ms] = (ms, float(_dec(r.get("high_price"), "high")), float(_dec(r.get("low_price"), "low")),
                               float(_dec(r.get("close_price"), "close")))
            a = b + 60_000
        return [out[k] for k in sorted(out)]

    def leverage_cap(self, symbol: str, lev: int) -> Optional[float]:
        """The largest position value (USDT) WOO X Pro lets a ``symbol`` position have at ``lev``: its public leverage
        risk limit (GET /contract/public/leverage-bracket), the brackets from the smallest up while their maximum
        leverage is at least ``lev``; None when not even the first allows ``lev``. Public, no key (``check
        --leverage``: owners 10-24, WOO X Pro 2 trades 35x on every coin)."""
        cap = None
        for blev, _lo, hi, _mmr in self.risk_brackets(symbol):
            if blev < int(lev):
                break
            cap = hi
        return cap

    def risk_brackets(self, symbol: str) -> list:
        """WOO X Pro's public leverage risk limit of ``symbol`` (GET /contract/public/leverage-bracket, no key): its
        brackets from the smallest up as (max leverage, notional floor, notional cap, maintenance margin ratio)."""
        data = self.req("GET", PUBLIC + "/leverage-bracket", {"symbol": symbol}, signed=False, limit_key="leverage_bracket")
        rules = data.get("rules") if isinstance(data, dict) else None
        row = next((r for r in rules or [] if isinstance(r, dict) and r.get("symbol") == symbol), None)
        rows = row.get("brackets") if isinstance(row, dict) else None
        if not isinstance(rows, list) or not rows or not all(isinstance(b, dict) for b in rows):
            raise TransientError(200, None, f"{symbol}: 레버리지 위험 한도 응답이 이상합니다")
        out = [(_int(b.get("initial_leverage")), float(_dec(b.get("notional_floor"), "notional_floor")),
                float(_dec(b.get("notional_cap"), "notional_cap")),
                float(_dec(b.get("maint_margin_ratio"), "maint_margin_ratio"))) for b in rows]
        return sorted(out, key=lambda r: r[1])

    def maint_margin_ratio(self, symbol: str, notional: float) -> Optional[float]:
        """The maintenance margin ratio of the bracket a ``notional`` (USDT) position of ``symbol`` falls in; None
        past the last bracket (the executor's liquidation check before a "roe" entry, owners 10-24)."""
        for _lev, _lo, hi, mmr in self.risk_brackets(symbol):
            if notional <= hi:
                return mmr
        return None

    def leverage_brackets(self) -> list:
        """Signal mode needs Binance-like notional brackets: not offered (the executor follows the paper position)."""
        raise TestnetError(400, "NO_BRACKETS", "WOO X Pro는 빠른 진입(signal) 크기 계산용 레버리지 구간을 주지 않습니다")

    # ------------------------------------------------------------ account
    def account(self) -> dict:
        data = self.req("GET", PRIVATE + "/assets-detail", limit_key="assets")
        if not isinstance(data, list):
            raise TransientError(200, None, f"자산 응답이 목록이 아닙니다: {str(data)[:80]!r}")
        usdt = next((r for r in data if isinstance(r, dict) and r.get("currency") == SETTLE), None)
        if usdt is None:          # never read as $0 (a daily-loss halt would close everything)
            raise TransientError(200, None, "자산 응답에 USDT 줄이 없습니다")
        equity, unreal = _dec(usdt.get("equity"), "equity"), _dec(usdt.get("unrealized"), "unrealized")
        wallet = equity - unreal
        assets = [{"asset": SETTLE, "walletBalance": _num(wallet)}]
        for r in data:
            if isinstance(r, dict) and r.get("currency") != SETTLE and _f(r.get("equity")) > 0:
                assets.append({"asset": r.get("currency"), "walletBalance": str(r.get("equity"))})
        return {"totalWalletBalance": _num(wallet), "totalUnrealizedProfit": _num(unreal),
                "totalMarginBalance": _num(equity), "assets": assets,
                "positionMargin": str(usdt.get("position_deposit")),
                "availableBalance": str(usdt.get("available_balance")),
                "frozenBalance": str(usdt.get("frozen_balance"))}

    def fee_rate(self, symbol: str) -> dict:
        data = self.req("GET", PRIVATE + "/trade-fee-rate", {"symbol": symbol}, limit_key="fee_rate")
        if not isinstance(data, dict):
            raise TransientError(200, None, f"{symbol}: 수수료율 응답이 이상합니다")
        return {"taker": float(_dec(data.get("taker_fee_rate"), "taker_fee_rate")),
                "maker": float(_dec(data.get("maker_fee_rate"), "maker_fee_rate"))}

    def position_mode(self) -> str:
        data = self.req("GET", PRIVATE + "/get-position-mode", limit_key="position_mode")
        mode = (data or {}).get("position_mode") if isinstance(data, dict) else None
        if mode not in (ONE_WAY, HEDGE):
            raise TransientError(200, None, f"포지션 모드 응답이 이상합니다({mode!r})")
        return mode

    def _busy(self) -> bool:
        """Any position, open order or resting stop (every USDT contract)?"""
        if self.positions():
            return True
        rows = self.req("GET", PRIVATE + "/get-open-orders", {"limit": 100}, limit_key="open_orders")
        if not isinstance(rows, list):
            raise TransientError(200, None, "열린 주문 응답이 목록이 아닙니다")
        if rows:
            return True
        return bool(self._resting(None))

    def one_way(self) -> None:
        """One-way position mode (the executor's Binance assumption). Switched only with nothing open; not possible:
        Refused (the executor does not start)."""
        if self.position_mode() == ONE_WAY:
            return
        if self._busy():
            raise Refused("WOO X Pro 포지션 모드가 양방향(hedge)이고 포지션·주문이 있어 단방향으로 못 바꿉니다. 정리한 뒤 "
                          "앱에서 단방향(One-way)으로 바꾸고 다시 켜세요")
        why = ""
        try:
            self.req("POST", PRIVATE + "/set-position-mode", {"position_mode": ONE_WAY},
                     limit_key="position_mode_set")
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            why = e.msg
        if self.position_mode() != ONE_WAY:
            raise Refused(f"WOO X Pro 포지션 모드를 단방향(One-way)으로 바꿀 수 없어 거래하지 않습니다. {why}".strip())

    def _lev_rows(self, symbol: str) -> list:
        """position-v2?symbol: the symbol's leverage and margin type, with or without a position."""
        data = self.req("GET", PRIVATE + "/position-v2", {"symbol": symbol}, limit_key="position_v2")
        if not isinstance(data, list):
            raise TransientError(200, None, f"{symbol}: 레버리지 응답이 목록이 아닙니다")
        rows = [r for r in data if isinstance(r, dict) and r.get("symbol") == symbol]
        if not rows:
            raise TransientError(200, None, f"{symbol}: 레버리지 응답에 이 코인 줄이 없습니다")
        return rows

    @staticmethod
    def _lev_ok(rows: list, lev: int) -> bool:
        return all(_int(r.get("leverage")) == lev and str(r.get("open_type") or "").lower() == ISOLATED for r in rows)

    def _set_leverage(self, symbol: str, lev: int) -> None:
        """Isolated ``lev``, then read back: every row must show it. Already so: nothing is sent."""
        if self._lev_ok(self._lev_rows(symbol), lev):
            return
        self.req("POST", PRIVATE + "/submit-leverage", {"symbol": symbol, "leverage": str(lev),
                                                        "open_type": ISOLATED}, limit_key="leverage_set")
        rows = self._lev_rows(symbol)
        if not self._lev_ok(rows, lev):
            seen = [(r.get("position_side"), r.get("open_type"), r.get("leverage")) for r in rows]
            raise TestnetError(400, "LEVERAGE_MISMATCH", f"{symbol}: 격리 {lev}배로 맞추지 못했습니다(읽은 값 {seen})")

    def isolated(self, symbol: str) -> None:
        """Isolated margin with the owners' leverage (BTC 40x, others 30x), read back. A position open on the symbol:
        TestnetError -4048 unless it is isolated already (the executor warns and keeps protecting it). Not possible
        otherwise: Refused (the executor does not start)."""
        sp = self._spec(symbol)
        rows = self._position_rows(symbol)
        if rows:
            if str(rows[0].get("margin_type") or "").lower() == ISOLATED:
                return None
            raise TestnetError(400, -4048, f"{symbol}: 교차(cross) 포지션이 열려 있어 격리로 맞추지 못했습니다")
        lev = int(min(FIXED_LEVERAGE.get(symbol, DEFAULT_LEVERAGE), sp.get("max_leverage") or 10 ** 6))
        try:
            self._set_leverage(symbol, lev)
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            if self._busy():
                raise TestnetError(e.status, -4048, f"{symbol}: 포지션·주문이 있어 격리 레버리지를 못 맞췄습니다: {e.msg}")
            raise Refused(f"WOO X Pro {symbol}을 격리 {lev}배로 맞출 수 없어 거래하지 않습니다: {e.msg}") from e
        self.lev[symbol] = lev

    def leverage(self, symbol: str, lev: int) -> dict:
        """Set the symbol's isolated leverage and read it back. Refused (TestnetError) unless the account is in one-way
        mode and the contract is trading: the executor never opens a position otherwise."""
        lev = int(lev)
        sp = self._spec(symbol)
        if sp.get("max_leverage") and lev > sp["max_leverage"]:
            raise TestnetError(400, "LEVERAGE_MAX", f"{symbol}: 레버리지 {lev}배가 최대 {sp['max_leverage']:g}배를 넘습니다")
        if str(sp.get("status") or "Trading") != "Trading":
            raise TestnetError(400, "NOT_TRADING", f"{symbol}: 계약 상태 {sp.get('status')} (Trading이 아니면 거래 안 함)")
        if self.position_mode() != ONE_WAY:
            raise TestnetError(400, "NOT_ONE_WAY", "WOO X Pro 포지션 모드가 단방향(One-way)이 아니라 진입하지 않습니다")
        rows = self._position_rows(symbol)
        if rows:
            r = rows[0]
            if _int(r.get("leverage")) == lev and str(r.get("margin_type") or "").lower() == ISOLATED:
                self.lev[symbol] = lev
                return {"symbol": symbol, "leverage": lev, "marginType": "isolated"}
            raise TestnetError(400, "POSITION_OPEN", f"{symbol}: 포지션이 있어 레버리지를 바꾸지 않습니다")
        self._set_leverage(symbol, lev)
        self.lev[symbol] = lev
        return {"symbol": symbol, "leverage": lev, "marginType": "isolated"}

    def account_setup(self, symbols) -> list:
        """(ok, Korean text) lines for preflight, reads only: position mode, each coin's contract state and leverage."""
        out = []
        mode = self.position_mode()
        if mode == ONE_WAY:
            out.append((True, "포지션 모드: 단방향(one-way)"))
        else:
            busy = self._busy()
            out.append((not busy, "포지션 모드: 양방향(hedge). " + ("포지션·주문이 있어 못 바꿉니다: 정리한 뒤 다시 하세요"
                                                                if busy else "실행기가 켤 때 단방향으로 바꿉니다")))
        for s in symbols:
            sp = self._spec(s)
            rows = self._lev_rows(s)
            levs = "/".join(f"{r.get('open_type')} {r.get('leverage')}" for r in rows)
            good = str(sp.get("status") or "") == "Trading"
            out.append((good, f"{s}: 계약 상태 {sp.get('status')}, 1계약 {sp['contract_size']} {sp.get('base_coin') or ''}, "
                              f"최소 {sp['min_vol']}계약, 가격 단위 {sp['price_unit']}, 지금 레버리지 {levs or '?'}"))
        return out

    # ------------------------------------------------------------ orders
    def _order_dict(self, row: dict) -> dict:
        sym = str(row.get("symbol") or "")
        size = _dec(row.get("size"), "size")
        deal = _dec(row.get("deal_size") if row.get("deal_size") not in (None, "") else 0, "deal_size")
        state = _int(row.get("state"))
        code = _int(row.get("side"))
        if state in OPEN_STATES:
            status = "PARTIALLY_FILLED" if deal > 0 else "NEW"
        elif state == FINISHED:
            status = "FILLED" if deal >= size else "CANCELED"
        else:
            raise TransientError(200, None, f"주문 상태가 이상합니다({row.get('state')!r})")
        cs = Decimal(self._spec(sym)["contract_size"])
        avg = row.get("deal_avg_price")
        return {"orderId": str(row.get("order_id")), "clientOrderId": row.get("client_order_id") or "", "symbol": sym,
                "side": "BUY" if code in (BUY_OPEN, BUY_CLOSE) else "SELL",
                "type": "MARKET" if str(row.get("type") or "") == "market" else str(row.get("type") or "").upper(),
                "origQty": _num(size * cs), "executedQty": _num(deal * cs),
                "avgPrice": str(avg) if deal > 0 and avg not in (None, "") else "0", "status": status,
                "reduceOnly": code in CLOSE_CODES, "time": _int(row.get("create_time")),
                "updateTime": _int(row.get("update_time")), "wooState": state, "wooSide": code,
                "leverage": row.get("leverage"), "openType": row.get("open_type")}

    def _history(self, symbol: str, **params) -> list:
        data = self.req("GET", PRIVATE + "/order-history", {"symbol": symbol, **params}, limit_key="order_history")
        if not isinstance(data, list):
            raise TransientError(200, None, f"{symbol}: 주문 기록 응답이 목록이 아닙니다")
        return [r for r in data if isinstance(r, dict)]

    def _find(self, symbol: str, order_id=None, ext: Optional[str] = None) -> dict:
        """The order (any state) by its id or client_order_id. TestnetError -2013 when WOO X Pro does not have it."""
        if order_id is not None:
            data = self.req("GET", PRIVATE + "/order", {"symbol": symbol, "order_id": str(order_id)},
                            limit_key="order")
            if isinstance(data, list):
                data = next((r for r in data if isinstance(r, dict)), None)
            if not data:
                raise TestnetError(404, NOT_FOUND[0], "Order does not exist.")
            if not isinstance(data, dict) or data.get("order_id") in (None, ""):
                raise TransientError(200, None, f"주문 응답이 이상합니다: {str(data)[:80]!r}")
            if str(data.get("order_id")) != str(order_id):
                raise TransientError(200, None, f"다른 주문({data.get('order_id')})이 왔습니다")
        else:
            data = next((r for r in self._history(symbol, client_order_id=ext)
                         if r.get("client_order_id") == ext and str(r.get("type") or "") != "planorder"), None)
            if data is None:
                rows = self.req("GET", PRIVATE + "/get-open-orders", {"symbol": symbol, "limit": 100},
                                limit_key="open_orders")
                data = next((r for r in rows or [] if isinstance(r, dict) and r.get("client_order_id") == ext), None)
            if data is None:
                raise TestnetError(404, NOT_FOUND[0], "Order does not exist.")
        self.order_symbol[str(data["order_id"])] = str(data.get("symbol") or symbol)
        return data

    def _pos_for_close(self, symbol: str) -> dict:
        """Margin type and leverage of the position a close order acts on (the last read, else read now)."""
        row = self.pos_rows.get(symbol)
        if row is None:
            rows = self._position_rows(symbol)
            row = rows[0] if rows else {}
        lev = _int(row.get("leverage")) or self.lev.get(symbol)
        return {"open_type": str(row.get("margin_type") or ISOLATED).lower(), "leverage": lev}

    def _open_leverage(self, symbol: str) -> int:
        lev = self.lev.get(symbol)
        if lev:
            return int(lev)
        lev = _int(self._lev_rows(symbol)[0].get("leverage"))
        if lev <= 0:
            raise TestnetError(400, "NO_LEVERAGE", f"{symbol}: 레버리지를 읽지 못해 주문하지 않습니다")
        return lev

    def market(self, symbol: str, side: str, qty: float, reduce_only: bool = False,
               client_id: Optional[str] = None) -> dict:
        """Market order, then read back until it is final. Opening: side 1 (buy) / 4 (sell), isolated with the
        symbol's leverage. reduce_only: a CLOSE side, 3 (sell: closes a long) / 2 (buy: closes a short), which can
        never open a position. An opening order's rate-limit answer counts as an unknown outcome (looked up by its
        client_order_id, never sent again)."""
        size = self._contracts(symbol, qty)
        self._check_size(symbol, size, qty, "주문")
        ext = ext_id(client_id)
        if reduce_only:
            code = SELL_CLOSE if side == "SELL" else BUY_CLOSE
            p = self._pos_for_close(symbol)
            body = {"symbol": symbol, "client_order_id": ext, "side": code, "type": "market", "size": size,
                    "open_type": p["open_type"]}
            if p["leverage"]:
                body["leverage"] = str(p["leverage"])
        else:
            code = BUY_OPEN if side == "BUY" else SELL_OPEN
            body = {"symbol": symbol, "client_order_id": ext, "side": code, "type": "market", "size": size,
                    "open_type": ISOLATED, "leverage": str(self._open_leverage(symbol))}
        placeholder = {"orderId": None, "clientOrderId": ext, "symbol": symbol, "side": side, "type": "MARKET",
                       "origQty": _num(self._qty(symbol, size)), "executedQty": "0", "avgPrice": "0", "status": "NEW",
                       "reduceOnly": reduce_only}
        try:
            data = self.req("POST", PRIVATE + "/submit-order", body, limit_key="submit_order")
        except RateLimited as e:
            if reduce_only or e.status == 418:
                raise
            raise TransientError(e.status, e.code, f"진입 주문에 요청 한도 답(결과 모름, 다시 보내지 않음): {e.msg}") from e
        except TestnetError as e:
            if getattr(e, "ret_code", None) != DUPLICATE_CID:
                raise
            o = self._order_dict(self._find(symbol, ext=ext))      # the id was used: that order is this one
            return self._read_back(symbol, o["orderId"], {**placeholder, "orderId": o["orderId"]})
        oid = data.get("order_id") if isinstance(data, dict) else data
        if oid in (None, "", 0, "0") or isinstance(oid, (dict, list, bool)):
            raise TransientError(200, None, "주문 번호가 없는 응답(결과 모름)")
        oid = str(oid)
        self.order_symbol[oid] = symbol
        return self._read_back(symbol, oid, {**placeholder, "orderId": oid})

    def _read_back(self, symbol: str, oid: str, placeholder: dict) -> dict:
        """The accepted order, read until final. It WAS accepted (it has an id): a failed read never escapes as if it
        had not run; the last state seen (or NEW) is returned and the executor settles it from the position."""
        o = None
        for w in (0.0,) + ORDER_WAITS:
            if w:
                self.sleep(w)
            try:
                o = self._order_dict(self._find(symbol, order_id=oid))
            except TestnetError as e:
                if e.code in NOT_FOUND and not isinstance(e, TransientError):
                    continue                               # not visible yet
                return {**(o or placeholder), "readBack": f"읽기 실패: {e}"}
            if o["status"] in ORDER_FINAL:
                break
        return o or placeholder

    def order(self, symbol: str, order_id=None, client_id: Optional[str] = None) -> dict:
        return self._order_dict(self._find(symbol, order_id=order_id,
                                           ext=None if order_id is not None else ext_id(client_id)))

    def cancel(self, symbol: str, order_id) -> dict:
        self.req("POST", PRIVATE + "/cancel-order", {"symbol": symbol, "order_id": str(order_id)},
                 limit_key="cancel_order")
        return {"orderId": str(order_id), "status": "CANCELED"}

    def cancel_all(self, symbol: str) -> dict:
        self.req("POST", PRIVATE + "/cancel-orders", {"symbol": symbol}, limit_key="cancel_orders")
        return {"code": 200, "msg": "ok"}

    def open_orders(self, symbol: str) -> list:
        rows = self.req("GET", PRIVATE + "/get-open-orders", {"symbol": symbol, "limit": 100}, limit_key="open_orders")
        if not isinstance(rows, list):
            raise TransientError(200, None, f"{symbol}: 열린 주문 응답이 목록이 아닙니다")
        return [self._order_dict(r) for r in rows if isinstance(r, dict) and r.get("symbol") == symbol]

    # ------------------------------------------------------------ TP/SL orders: the exchange-side stops
    def _plans(self, symbol: Optional[str]) -> list:
        """Every resting plan / TP/SL order (one symbol or all). The answer must be a list: never "none" from a missing
        or garbled one."""
        p = {"limit": 100}
        if symbol:
            p["symbol"] = symbol
        data = self.req("GET", PRIVATE + "/current-plan-order", p, limit_key="plan_list")
        if not isinstance(data, list):
            raise TransientError(200, None, f"조건 주문 응답이 목록이 아닙니다: {str(data)[:80]!r}")
        return [r for r in data if isinstance(r, dict) and (not symbol or r.get("symbol") == symbol)]

    def _resting(self, symbol: Optional[str]) -> list:
        """The plan / TP/SL orders that still rest: state 1 (approval) or 2 (check). A row in another state (the docs'
        own example shows a 4 in this list) is finished: never counted as a stop that covers a position."""
        return [r for r in self._plans(symbol) if _int(r.get("state"), 0) in OPEN_STATES]

    def _algo_dict(self, row: dict, status: str = "NEW", actual: str = "") -> dict:
        sym = str(row.get("symbol") or "")
        sid = str(row.get("order_id"))
        code = _int(row.get("side"))
        kind = str(row.get("type") or "")
        closing = code in CLOSE_CODES
        if closing and kind == "stop_loss":
            otype = "STOP_MARKET"
        elif closing and kind == "take_profit":
            otype = "TAKE_PROFIT_MARKET"
        else:
            otype = "CONDITIONAL"                           # a plan order or an opening one: never counted as a stop
        trig = row.get("trigger_price")
        if status == "NEW":                                 # a resting stop's level is never read as 0 from a gap
            trig = _num(_dec(trig, "trigger_price"))
        cid = row.get("client_order_id") or self.cid_by_stop.get(sid, "")
        self.order_symbol[sid] = sym
        return {"algoId": sid, "clientAlgoId": cid, "symbol": sym,
                "side": "BUY" if code in (BUY_OPEN, BUY_CLOSE) else "SELL", "orderType": otype,
                "algoType": "CONDITIONAL",
                "triggerPrice": _num(_dec(trig, "trigger_price")) if trig not in (None, "") else "0",
                "quantity": _num(self._qty(sym, row.get("size"))), "closePosition": False, "reduceOnly": closing,
                "workingType": WORKING_TYPE.get(_int(row.get("price_type")), str(row.get("price_type"))),
                "priceProtect": False, "algoStatus": status, "wooState": row.get("state"), "wooSide": code,
                "wooType": kind, "planCategory": row.get("plan_category"), "actualOrderId": actual,
                "createTime": _int(row.get("create_time"))}

    def stop_close(self, symbol: str, side: str, trigger: float, qty: Optional[float] = None,
                   client_id: Optional[str] = None) -> dict:
        """Protective stop resting on WOO X Pro: a close-side stop_loss TP/SL order (market on trigger, last price).
        ``qty`` the position's size (two can coexist while a stop is moved); None: the position's size now."""
        sp = self._spec(symbol)
        trig = _price_str(trigger, sp["tick_str"])
        if qty is None:
            qty = abs(float(self.position(symbol)["positionAmt"]))
        size = self._contracts(symbol, qty)
        self._check_size(symbol, size, qty, "손절")
        code = SELL_CLOSE if side == "SELL" else BUY_CLOSE
        ext = ext_id(client_id)
        body = {"symbol": symbol, "type": "stop_loss", "side": code, "size": size, "trigger_price": trig,
                "executive_price": trig, "price_type": PRICE_LAST, "plan_category": 1, "client_order_id": ext,
                "category": "market"}
        self.pending_stops[ext] = (symbol, code, Decimal(trig), size, self._now())
        self._trim()
        try:
            data = self.req("POST", PRIVATE + "/submit-tp-sl-order", body, limit_key="tpsl_submit")
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            if getattr(e, "ret_code", None) == DUPLICATE_CID:
                # sent before and the first one landed (its answer was lost): look it up, never a refusal
                raise TransientError(e.status, e.code, f"같은 번호의 손절이 이미 있습니다(결과 확인 필요): {e.msg}") from e
            raise self._would_trigger(e, symbol, side, float(trig)) from e
        sid = data.get("order_id") if isinstance(data, dict) else data
        if sid in (None, "", 0, "0") or isinstance(sid, (dict, list, bool)):
            raise TransientError(200, None, "손절 주문 번호가 없는 응답(결과 모름)")
        sid = str(sid)
        self.order_symbol[sid] = symbol
        self.stop_by_cid[ext], self.cid_by_stop[sid] = sid, ext
        return {"algoId": sid, "clientAlgoId": ext, "symbol": symbol, "side": side, "orderType": "STOP_MARKET",
                "algoType": "CONDITIONAL", "triggerPrice": _num(Decimal(trig)),
                "quantity": _num(self._qty(symbol, size)), "closePosition": False, "reduceOnly": True,
                "workingType": WORKING_TYPE[PRICE_LAST], "algoStatus": "NEW"}

    def _trim(self, keep: int = 2000) -> None:
        """The id maps of a process that runs for weeks stay small (the oldest go first)."""
        for d in (self.pending_stops, self.stop_by_cid, self.cid_by_stop, self.order_symbol):
            while len(d) > keep:
                d.pop(next(iter(d)))

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
            return TestnetError(e.status, WOULD_TRIGGER, f"Order would immediately trigger (WOO X Pro: {e.msg}; 마지막 "
                                                         f"가격 {last:g}, 손절 {trig:g})")
        return e

    def _stop_by_cid(self, ext: str) -> str:
        """A stop's id from its client_order_id: the answer we got, else the resting list (client_order_id, else the
        fingerprint of what we sent: symbol, side, trigger, contracts, created after we sent it)."""
        sid = self.stop_by_cid.get(ext)
        if sid is not None:
            return sid
        fp = self.pending_stops.get(ext)
        rows = self._resting(fp[0] if fp else None)
        hit = next((r for r in rows if r.get("client_order_id") == ext), None)
        if hit is None and fp is not None:
            _, code, trig, size, sent = fp
            cands = [r for r in rows if _int(r.get("side")) == code and str(r.get("type")) == "stop_loss"
                     and _dec(r.get("trigger_price"), "trigger_price") == trig and _int(r.get("size")) == size
                     and _int(r.get("create_time")) >= sent - 10_000 and str(r.get("order_id")) not in self.cid_by_stop]
            hit = min(cands, key=lambda r: _int(r.get("create_time")), default=None)
        if hit is None:
            raise TestnetError(404, NOT_FOUND[0], f"조건 주문 {ext}이 없습니다")
        sid = str(hit.get("order_id"))
        self.stop_by_cid[ext], self.cid_by_stop[sid] = sid, ext
        self.order_symbol[sid] = str(hit.get("symbol") or "")
        return sid

    def _finished_stop(self, sid: str, symbols) -> Optional[dict]:
        """A stop that no longer rests: its own history row (TRIGGERED when it names the order it placed, else
        CANCELED), or the market order it placed (client_order_id "PLAN_<id>", seen in the docs' history example)."""
        now_s = self._now() // 1000
        span = {"start_time": now_s - SPAN_MS // 1000, "end_time": now_s + 60}
        for s in symbols:
            rows = self._history(s, order_id=sid, **span)
            row = next((r for r in rows if str(r.get("order_id")) == sid), None)
            placed = next((r for r in self._history(s, client_order_id=f"PLAN_{sid}", **span)
                           if r.get("client_order_id") == f"PLAN_{sid}"), None)
            if row is None and placed is None:
                continue
            base = row or {"order_id": sid, "symbol": s, "side": (placed or {}).get("side"), "type": "stop_loss",
                           "size": (placed or {}).get("size"), "trigger_price": (placed or {}).get("trigger_price"),
                           "price_type": PRICE_LAST}
            ex = (row or {}).get("executive_order_id")
            actual = str(ex) if ex not in (None, "", 0, "0") else (str(placed.get("order_id")) if placed else "")
            if not base.get("trigger_price"):
                base = {**base, "trigger_price": None}
            return self._algo_dict(base, "TRIGGERED" if actual else "CANCELED", actual)
        return None

    def algo_order(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        if algo_id is None:
            algo_id = self._stop_by_cid(ext_id(client_id))
        algo_id = str(algo_id)
        sym = self.order_symbol.get(algo_id) or None
        row = next((r for r in self._plans(sym) if str(r.get("order_id")) == algo_id), None)
        if row is None and sym is not None:
            row = next((r for r in self._plans(None) if str(r.get("order_id")) == algo_id), None)
        if row is not None and _int(row.get("state"), 0) in OPEN_STATES:
            return self._algo_dict(row)
        if row is not None:
            sym = str(row.get("symbol") or "") or sym
        done = self._finished_stop(algo_id, [sym] if sym else COINS)
        if done is None and row is not None:
            return self._algo_dict({**row, "trigger_price": row.get("trigger_price") or None}, "CANCELED")
        if done is None:
            raise TestnetError(404, NOT_FOUND[0], f"조건 주문 {algo_id}이 없습니다")
        return done

    def cancel_algo(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        if algo_id is None:
            algo_id = self._stop_by_cid(ext_id(client_id))
        algo_id = str(algo_id)
        sym = self.order_symbol.get(algo_id) or self.algo_order(algo_id=algo_id)["symbol"]
        try:
            self.req("POST", PRIVATE + "/cancel-plan-order", {"symbol": sym, "order_id": algo_id},
                     limit_key="plan_cancel")
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
        return {"algoId": algo_id, "clientAlgoId": self.cid_by_stop.get(algo_id, ""), "code": "200", "msg": "success"}

    def open_algo_orders(self, symbol: str) -> list:
        return [self._algo_dict(r) for r in self._resting(symbol)]

    def cancel_all_algo(self, symbol: str) -> dict:
        """No documented "cancel every plan order" call: each resting one is cancelled by its id."""
        for r in self._resting(symbol):
            try:
                self.req("POST", PRIVATE + "/cancel-plan-order", {"symbol": symbol, "order_id": str(r.get("order_id"))},
                         limit_key="plan_cancel")
            except TestnetError as e:
                if e.code not in NOT_FOUND or isinstance(e, TransientError):
                    raise
        return {"code": 200, "msg": "ok"}

    # ------------------------------------------------------------ positions
    def _position_rows(self, symbol: Optional[str] = None) -> list:
        """Open position rows (current_amount > 0). The answer must be a list: never "flat" from a missing or garbled
        one."""
        data = self.req("GET", PRIVATE + "/position", {"symbol": symbol} if symbol else None, limit_key="position")
        if not isinstance(data, list):
            raise TransientError(200, None, f"포지션 응답이 목록이 아닙니다: {str(data)[:80]!r}")
        out = []
        for r in data:
            if not isinstance(r, dict):
                raise TransientError(200, None, "포지션 응답이 이상합니다")
            if symbol and r.get("symbol") != symbol:
                continue
            if not str(r.get("symbol") or "").endswith(SETTLE):
                continue            # not a USDT contract: never traded here
            if str(r.get("account") or "futures") != "futures":
                continue            # copy trading: not this bot's
            amt = _dec(r.get("current_amount"), "current_amount")
            if amt == 0:
                continue
            pt = _int(r.get("position_type"))
            if pt not in (1, 2) or (amt < 0 and pt == 1):
                raise TransientError(200, None, f"{r.get('symbol')}: 포지션 방향이 이상합니다(position_type "
                                                f"{r.get('position_type')!r}, 수량 {r.get('current_amount')!r})")
            out.append(r)
        return out

    def _position_dict(self, symbol: str, rows: list) -> dict:
        amt = Decimal(0)
        for r in rows:
            q = abs(self._qty(symbol, r.get("current_amount")))     # the side comes from position_type only
            amt += q if _int(r.get("position_type")) == 1 else -q
        main = rows[0] if rows else {}
        if rows:
            self.pos_rows[symbol] = main
        else:
            self.pos_rows.pop(symbol, None)
        mt = str(main.get("margin_type") or "").lower()
        return {"symbol": symbol, "positionAmt": _num(amt),
                "entryPrice": str(main.get("entry_price") or main.get("open_avg_price") or "0"),
                "markPrice": str(main.get("mark_price") or "0"), "liquidationPrice": "0",
                "unRealizedProfit": str(main.get("unrealized_value") or "0"),
                "leverage": str(main.get("leverage") or ""), "marginType": mt if mt in ("isolated", "cross") else "",
                "hedge": len({_int(r.get("position_type")) for r in rows}) > 1,
                "updateTime": _int(main.get("timestamp"))}

    def position(self, symbol: str) -> dict:
        return self._position_dict(symbol, self._position_rows(symbol))

    def positions(self) -> list:
        by: dict = {}
        for r in self._position_rows(None):
            by.setdefault(str(r.get("symbol")), []).append(r)
        out = [self._position_dict(s, rs) for s, rs in by.items() if s]
        for s in [s for s in self.pos_rows if s not in by]:
            self.pos_rows.pop(s, None)
        return [p for p in out if float(p["positionAmt"]) != 0]

    # ------------------------------------------------------------ fills, P&L, funding, transfers
    def _trade_rows(self, symbol: str, lo_s: int, hi_s: int, depth: int = 0) -> list:
        """trades in [lo_s, hi_s] seconds: a full answer (200 rows, the cap) is read again in two halves."""
        data = self.req("GET", PRIVATE + "/trades", {"symbol": symbol, "start_time": lo_s, "end_time": hi_s},
                        limit_key="trades")
        if not isinstance(data, list):
            raise TransientError(200, None, f"{symbol}: 체결 응답이 목록이 아닙니다")
        if len(data) >= TRADES_CAP and hi_s - lo_s > 1:
            if depth > 20:
                raise TransientError(0, None, f"{symbol}: 체결이 너무 많아 나눠 읽지 못했습니다")
            mid = (lo_s + hi_s) // 2             # the halves share ``mid`` (user_trades drops repeats by trade_id)
            return self._trade_rows(symbol, lo_s, mid, depth + 1) + self._trade_rows(symbol, mid, hi_s, depth + 1)
        return [r for r in data if isinstance(r, dict)]

    def user_trades(self, symbol: str, start_ms: int, end_ms: int, limit: int = 1000) -> list:
        """Account fills (Binance userTrades shape): price, qty (base units), realizedPnl (see fills_from_trades),
        commission (fee: + paid), commissionAsset, orderId, side, time."""
        rows, seen = [], set()
        lo = int(start_ms) // 1000
        end = -(-int(end_ms) // 1000)
        while lo <= end:
            hi = max(min(end, lo + SPAN_MS // 1000), lo + 1)
            for r in self._trade_rows(symbol, lo, hi):
                if r.get("symbol") not in (None, symbol) or str(r.get("trade_id")) in seen:
                    continue
                if str(r.get("account") or "futures") != "futures":
                    continue
                seen.add(str(r.get("trade_id")))
                rows.append(r)
            lo = hi + 1
        return fills_from_trades(rows, self._spec(symbol)["contract_size"], symbol)

    def _flows(self, flow_type: int, symbol: Optional[str], lo: int, hi: int, depth: int = 0) -> list:
        p = {"flow_type": flow_type, "start_time": lo, "end_time": hi, "page_size": INCOME_CAP}
        if symbol:
            p["symbol"] = symbol
        data = self.req("GET", PRIVATE + "/transaction-history", p, limit_key="transactions")
        if not isinstance(data, list):
            raise TransientError(200, None, "자금 기록 응답이 목록이 아닙니다")
        if len(data) >= INCOME_CAP and hi - lo > 1000:
            if depth > 20:
                raise TransientError(0, None, "자금 기록이 너무 많아 나눠 읽지 못했습니다")
            mid = (lo + hi) // 2                 # the halves share ``mid`` (income drops repeats)
            return self._flows(flow_type, symbol, lo, mid, depth + 1) + self._flows(flow_type, symbol, mid, hi,
                                                                                    depth + 1)
        return [r for r in data if isinstance(r, dict)]

    def income(self, symbol: Optional[str], income_type: Optional[str], start_ms: int, end_ms: int,
               limit: int = 1000) -> list:
        """Wallet changes in the Binance income shape (``income``: + received): funding (FUNDING_FEE) and transfers in and
        out of the futures account (TRANSFER; not trading P&L). With a symbol: its funding only."""
        out = []
        lo, hi = int(start_ms), int(end_ms)
        kinds = []
        if income_type in (None, "FUNDING_FEE"):
            kinds.append((3, "FUNDING_FEE", symbol, FLOW_NAMES[3]))
        if symbol is None and income_type in (None, "TRANSFER"):
            kinds.append((1, "TRANSFER", None, FLOW_NAMES[1]))
        seen = set()
        for flow, kind, sym, name in kinds:
            for r in self._flows(flow, sym, lo, hi):
                t = _int(r.get("time"))
                if not (lo <= t <= hi) or (sym and r.get("symbol") != sym):
                    continue
                if str(r.get("account") or "futures") != "futures":
                    continue
                # a server that ignores flow_type answers every kind: a realized P&L or a fee is never booked as a
                # transfer (it would move the daily-loss and drawdown baselines) nor as funding
                if str(r.get("type") or "").strip().lower() != name:
                    continue
                k = (kind, str(r.get("tran_id")), t, str(r.get("amount")), str(r.get("symbol")))
                if k in seen:
                    continue
                seen.add(k)
                out.append({"symbol": str(r.get("symbol") or ""), "incomeType": kind,
                            "income": _num(_dec(r.get("amount"), "amount")), "asset": r.get("asset") or SETTLE,
                            "time": t, "tranId": _id60(kind, r.get("tran_id"), r.get("symbol"), t, r.get("amount")),
                            "info": r.get("type")})
        return sorted(out, key=lambda r: int(r["time"]))


class WooXProKeyCheckClient(WooXProClient):
    """The key check (reads only): the futures account and the position mode. The API reports no key permissions:
    "futures trade only, server IP bound" comes from the owners' statement ``attested`` (WOOXPRO_LIVE_KEY_CHECKED)."""
    __test__ = False

    def __init__(self, *a, attested: bool = False, **k):
        super().__init__(*a, **k)
        self.attested = attested

    def api_restrictions(self):
        data = self.req("GET", PRIVATE + "/assets-detail", limit_key="assets")
        if not isinstance(data, list):
            return None                                     # nothing verified
        return permission_record(self.attested, self.position_mode())


# ---------------------------------------------------------------- keys, allowlist, the executor's clients
def _values(env, names) -> set:
    return {str((env or {}).get(n) or "").strip() for n in names} - {""}


def trading_keys(mode: str, env, paper_env=None) -> tuple[str, str, str]:
    """The WOO X Pro key, secret and memo, or Refused. Mainnet only, behind PAPERBOT_LIVE_MAINNET=I_UNDERSTAND. Never
    the paper runner's key, a Binance, Bybit or MEXC key."""
    if mode != MODE_MAINNET:
        raise Refused(f"WOO X Pro에는 선물 테스트넷이 없습니다: \"exchange\": \"wooxpro\"는 \"mode\": \"mainnet\"만 됩니다"
                      f"(지금 {mode!r})")
    if (env.get(FLAG) or "") != FLAG_VALUE:
        raise Refused(f"실거래 스위치가 꺼져 있습니다: 환경 변수 {FLAG}={FLAG_VALUE} 가 필요합니다")
    key, secret = (str(env.get(n) or "").strip() for n in LIVE_KEY_NAMES)
    memo = str(env.get(MEMO_NAME) or "").strip()
    if not (key and secret):
        raise Refused(f"{LIVE_KEY_NAMES[0]} / {LIVE_KEY_NAMES[1]} 가 비어 있습니다")
    if not memo:
        raise Refused(f"{MEMO_NAME} 가 비어 있습니다 (API 키를 만들 때 적은 메모: 서명에 들어갑니다)")
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
    return key, secret, memo


def refuse_unless_allowed(mode: str, client) -> None:
    """Mainnet only, and the client must be the WOO X Pro client pointing at the allowed host."""
    if mode != MODE_MAINNET:
        raise Refused(f"WOO X Pro에는 선물 테스트넷이 없습니다: mode={mode!r}로는 시작하지 않습니다(\"mainnet\"만)")
    host = urllib.parse.urlparse(getattr(client, "base", "") or "").hostname or ""
    if host not in WOOX_HOSTS or type(client) is not WooXProClient or tuple(type(client).HOSTS) != WOOX_HOSTS:
        raise Refused(f"주소 {host!r}: WOO X Pro 실행기는 {'·'.join(WOOX_HOSTS)} 외에는 연결하지 않습니다")
    if getattr(client, "public_only", False):
        raise Refused("키 없이 만든 WOO X Pro 클라이언트로는 실행기를 켜지 않습니다")


def check_executor_keys(mode: str, client, keycheck, env, paper_env) -> None:
    """The executor's key gates for WOO X Pro (Executor.__init__)."""
    key, secret, memo = trading_keys(mode, env, paper_env)
    if (client.key, client.secret, client.memo) != (key, secret, memo):
        raise Refused("WOO X Pro 실거래 실행기의 키가 WOOXPRO_LIVE_KEY/SECRET/MEMO와 다릅니다")
    if not isinstance(keycheck, WooXProKeyCheckClient) or (keycheck.key, keycheck.secret) != (key, secret):
        raise Refused("WOO X Pro 실거래는 키 확인(선물 계정 읽기)을 거쳐야 시작합니다")


def clients(mode: str, env, paper_env=None):
    """(order client, key-check client) for the mode, keys from the environment."""
    key, secret, memo = trading_keys(mode, env, paper_env)
    attested = str(env.get(KEY_CHECKED) or "").strip() == KEY_CHECKED_VALUE
    return (WooXProClient(key, secret, memo), WooXProKeyCheckClient(key, secret, memo, attested=attested))


def public_client() -> WooXProClient:
    """Market data only (specs): no key, no private call."""
    return WooXProClient("", "", "", public_only=True)


# ---------------------------------------------------------------- drill (mainnet, tiny)
def reconcile(c: WooXProClient, symbol: str, stop_price: Optional[float] = None) -> dict:
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


def pace(c: WooXProClient, gap_s: float = DRILL_MIN_GAP_S, sleep=time.sleep, clock=time.monotonic) -> None:
    """The drill's requests: at least ``gap_s`` apart (the client's own limiter keeps each endpoint under its limit)."""
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
class WooXProDrill:
    """The WOO X Pro micro drill on the REAL account. ``check()`` reads (time, contracts, account, fee rate, open
    orders and stops), switches to one-way mode when nothing is open and sets the isolated leverage (BTC 40x, the
    others 30x): no order. ``order_cycle()`` (only behind the explicit confirmation) runs one smallest-size cycle on one
    coin: market entry, found by its client_order_id, a stop_loss TP/SL order on WOO X Pro, the stop moved (new first,
    then the old one cancelled: two must rest at once), then the trigger test (the stop moved to 0.1 % from the last
    price and left to fire for real; at most 20 minutes) or a reduce-only close, flat with no order and no stop left,
    and the P&L from the fills checked three ways (fill prices, WOO X Pro's realised_profit, the wallet change)."""
    client: WooXProClient
    symbols: tuple = COINS
    symbol: Optional[str] = None
    side: int = 1
    keycheck: Optional[WooXProKeyCheckClient] = None
    stop_frac: float = 0.01
    trigger_test: bool = True
    trigger_wait_s: float = TRIGGER_WAIT_S
    wait: Callable[[float], None] = time.sleep
    elapsed: Callable[[], float] = time.monotonic          # seconds, for the drill's waits (tests pass their clock)
    say: Optional[Callable[[str], None]] = None            # each step printed as it happens (the CLI prints)
    log: list = field(default_factory=list)
    leverage: Optional[int] = None    # check --leverage N (owners 10-24, WOO X Pro 2: 35): every coin isolated at N
                                      # instead of BTC 40x / the others 30x, and the largest position N allows
    stop_net_roe: Optional[float] = None   # with leverage: the stop's net ROE (0.5) -> liquidation vs stop per coin
    margin: float = 0.4                    # ... for the position margin x N x the balance (the paper's margin 40 %)

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
        """A progress line during the long waits (printed, not a step)."""
        if self.say:
            self.say(f"  ... {text}")

    def _waiting(self, start: float, last: list, what: str) -> None:
        """Every 5 minutes of a long wait: one line that the drill is still waiting."""
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
        """The fewest contracts worth at least DRILL_ORDER_USDT."""
        step = spec["qty_step"]
        need = math.ceil(DRILL_ORDER_USDT / (price * step) - 1e-9) * step if price > 0 else 0.0
        return round(max(spec["min_qty"], need), 12)

    def check(self) -> list:
        c = self.client
        off = c.sync_time()
        self._step("서버 시간", abs(off) < 1000, {"offset_ms": off, "source": c.time_source})
        rows = {}
        for s in self.symbols:
            sp, px = c.spec(s), c.price(s)
            rows[s] = {"contract_size": sp["contract_size"], "min_volume": sp["min_vol"], "unit": sp["vol_unit"],
                       "price_precision": sp["price_unit"], "max_volume": sp["max_vol"],
                       "max_leverage": sp["max_leverage"], "status": sp["status"],
                       "min_order_usd": round(max(sp["min_qty"] * px, MIN_ORDER_USDT), 4)}
        need = (lambda s: self.leverage) if self.leverage else (lambda s: 40 if s == "BTCUSDT" else 30)
        self._step("계약 정보(6개 코인)" + (f", 최대 배수 {self.leverage}배 이상" if self.leverage else ""),
                   all(r["status"] == "Trading" and (r["max_leverage"] or 0) >= need(s) for s, r in rows.items()), rows)
        a = c.account()
        pos = c.positions()
        self._step("선물 계정 읽기", True, {"equity": a["totalMarginBalance"], "wallet": a["totalWalletBalance"],
                                         "unrealized": a["totalUnrealizedProfit"], "available": a["availableBalance"],
                                         "positionMargin": a["positionMargin"], "assets": a["assets"],
                                         "positions": [(p["symbol"], p["positionAmt"]) for p in pos]})
        taker = None
        try:
            fee = c.fee_rate(self.symbol or "DOGEUSDT")
            taker = fee["taker"]
            self._step("수수료율(API로 읽음, 편도)", True, {"taker_pct": round(fee["taker"] * 100, 4),
                                                       "maker_pct": round(fee["maker"] * 100, 4)}, fatal=False)
        except TestnetError as e:
            self._step("수수료율(API로 읽음, 편도)", False, str(e), fatal=False)
        left = {s: (len(c.open_orders(s)), len(c.open_algo_orders(s))) for s in self.symbols}
        self._step("열린 주문·조건 주문(목록 읽기)", True, left)
        now = c.clock_ms() + c.offset_ms
        try:
            inc = c.income(None, None, now - 7 * 86_400_000, now)
            kinds: dict = {}
            for r in inc:
                kinds[r["incomeType"]] = kinds.get(r["incomeType"], 0) + 1
            self._step("펀딩·입출금 기록 읽기(지난 7일)", True, {"rows": kinds}, fatal=False)
        except TestnetError as e:
            self._step("펀딩·입출금 기록 읽기(지난 7일)", False, str(e), fatal=False)
        c.one_way()
        self._step("포지션 모드 단방향", c.position_mode() == ONE_WAY, {"position_mode": c.position_mode()})
        levs = {}
        if self.leverage:                                  # every coin at N, read back; a refusal is said, never another N
            for s in self.symbols:
                try:
                    levs[s] = c.leverage(s, self.leverage)["leverage"] if not any(p["symbol"] == s for p in pos) \
                        else "포지션 있음"
                except TestnetError as e:
                    levs[s] = f"거절: {e}"
            self._step(f"격리 레버리지 모든 코인 {self.leverage}배(다시 읽어 확인)",
                       all(v == self.leverage for v in levs.values()), levs)
            caps = {}
            for s in self.symbols:
                try:
                    cap = c.leverage_cap(s, self.leverage)
                    caps[s] = f"${cap:,.0f}까지" if cap is not None else f"{self.leverage}배 안 됨"
                except TestnetError as e:
                    caps[s] = f"못 읽음: {e}"
            self._step(f"{self.leverage}배로 열 수 있는 포지션 크기(거래소 위험 한도)",
                       all(str(v).endswith("까지") for v in caps.values()), caps, fatal=False)
            if self.stop_net_roe is not None:
                self._liq_step(float(a["totalMarginBalance"] or 0), taker)
        else:
            for s in self.symbols:
                want = int(min(FIXED_LEVERAGE.get(s, DEFAULT_LEVERAGE), c.spec(s)["max_leverage"] or 10 ** 6))
                levs[s] = c.leverage(s, want)["leverage"] if not any(p["symbol"] == s for p in pos) else "포지션 있음"
            self._step("격리 레버리지 BTC 40배, 나머지 30배(다시 읽어 확인)",
                       all(v == (40 if s == "BTCUSDT" else 30) for s, v in levs.items()), levs)
        if self.keycheck is not None:
            self.keycheck.offset_ms = c.offset_ms
            perm = self.keycheck.api_restrictions()
            probs = check_permissions(perm) if isinstance(perm, dict) else ["키 확인 응답이 이상합니다"]
            self._step("키 확인(선물 계정·포지션 모드 읽기, 두 분 확인 문구)", not probs,
                       probs or (perm or {}).get("warnings"), fatal=False)
        return self.log

    def _liq_step(self, equity: float, taker: Optional[float]) -> None:
        """check --leverage N --stop-net-roe R: per coin, the position margin x N x the balance opens, its bracket's
        maintenance margin ratio, the estimated liquidation (liq_distance) against the stop (R / N less the round
        trip: the fee rate read above, else WOO_COST, and WOO_COST's slippage), and up to which balance that holds."""
        L, c = self.leverage, self.client
        fee = taker if taker is not None else WOO_COST["taker_fee"]
        stop = self.stop_net_roe / L - 2 * (fee + WOO_COST["slippage"])
        notional = equity * self.margin * L
        out, ok = {}, True
        for s in self.symbols:
            try:
                rows = c.risk_brackets(s)
            except TestnetError as e:
                out[s], ok = f"못 읽음: {e}", False
                continue
            here = next((r for r in rows if notional <= r[2]), None)
            safe = 0.0                                       # the largest position N opens with the stop first
            for blev, _lo, hi, mmr in rows:
                if blev < L or liq_distance(L, mmr) <= stop + LIQ_ROOM:
                    break
                safe = hi
            upto = f" · 잔고 ${safe / (self.margin * L):,.0f}까지 같음" if safe else ""
            if here is None or here[0] < L:
                out[s], ok = f"포지션 ${notional:,.0f}는 {L}배로 못 엶(거래소가 거절, 실행기는 진입 안 함){upto}", False
                continue
            d = liq_distance(L, here[3])
            if d > stop + LIQ_ROOM:
                out[s] = f"청산 약 {d:.2%}(유지증거금률 {here[3]:.2%}) · 손절 {stop:.2%} → 손절이 먼저{upto}"
            else:
                out[s], ok = (f"청산 약 {d:.2%}(유지증거금률 {here[3]:.2%}) · 손절 {stop:.2%} → 청산이 먼저이거나 너무 붙음: "
                              f"실행기가 진입하지 않음{upto}"), False
        self._step(f"{L}배 청산가와 손절(잔고 ${equity:,.0f} × {self.margin:.0%} × {L}배 = 포지션 ${notional:,.0f}, 손절 = 순ROE "
                   f"-{self.stop_net_roe:.0%} = 가격 {stop:.2%}, 테이커 {fee:.3%} + 슬리피지 {WOO_COST['slippage']:.2%})",
                   ok, out, fatal=False)

    def _settle(self, s: str, x: dict) -> dict:
        c = self.client
        for _ in range(20):
            if x.get("status") in ORDER_FINAL:
                break
            self.wait(0.5)
            x = c.order(s, order_id=x["orderId"])
        return x

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
        cid = ext_id(None)
        o = self._settle(s, c.market(s, buy, qty, client_id=cid))
        self._step(f"시장가 진입 체결(가장 작은 주문, 약 ${DRILL_ORDER_USDT:.0f})", o.get("status") == "FILLED",
                   {"status": o.get("status"), "avg": o.get("avgPrice"), "qty": o.get("executedQty"),
                    "contracts": round(qty / spec["qty_step"]) * int(Decimal(spec["vol_unit"])),
                    "orderId": o.get("orderId")})
        found = c.order(s, client_id=cid)
        self._step("진입 주문을 우리 번호(client_order_id)로 찾음", found.get("orderId") == o["orderId"],
                   {"client_order_id": cid, "orderId": found.get("orderId")})
        entry = float(o["avgPrice"])
        amt = float((self._until(lambda: (lambda p: p if float(p["positionAmt"]) else None)(c.position(s)))
                     or c.position(s))["positionAmt"])
        self._step("포지션 크기(계약 x 계약 크기)", abs(amt - self.side * qty) < spec["qty_step"] / 2,
                   {"positionAmt": amt, "qty": qty})
        a1 = c.account()
        lev = _int(c.position(s).get("leverage")) or 1
        margin = abs(amt) * entry / lev
        eq1 = float(a1["totalMarginBalance"])
        self._step("평가액(equity)에 포지션 증거금이 들어 있음(진입해도 증거금만큼 줄지 않음)",
                   abs(eq1 - w0) < 0.5 * margin,
                   {"equity_before": w0, "equity_open": eq1, "margin": round(margin, 6),
                    "positionMargin": a1["positionMargin"], "available": a1["availableBalance"],
                    "unrealized": a1["totalUnrealizedProfit"], "leverage": lev})
        stop1 = round_stop(entry * (1 - self.side * self.stop_frac), spec["tick"], self.side)
        st1 = place_stop(c, s, sell, stop1, abs(amt), client_id=ext_id(None))
        stops = live_stops(c, s)
        self._step("손절이 WOO X Pro에 걸림(청산 방향 stop_loss, 마지막 가격, 시장가)",
                   len(stops) == 1 and float(stops[0]["triggerPrice"]) == stop1
                   and stops[0].get("workingType") == "CONTRACT_PRICE" and covers(stops[0], amt),
                   [(x["algoId"], x["triggerPrice"], x["workingType"], x["quantity"], x.get("planCategory"))
                    for x in stops])
        stop2 = round_stop(entry * (1 - self.side * self.stop_frac / 2), spec["tick"], self.side)
        seen = {}
        orig = c.cancel_algo

        def watch_cancel(algo_id=None, client_id=None):
            seen.setdefault("during", len(live_stops(c, s)))
            return orig(algo_id=algo_id, client_id=client_id)
        c.cancel_algo = watch_cancel
        try:
            mv = move_stop(c, s, sell, stop2, abs(amt), [st1["algoId"]], client_id=ext_id(None))
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
            close_cid = ext_id(None)
            x = self._settle(s, c.market(s, sell, abs(amt), reduce_only=True, client_id=close_cid))
            self._step("줄이기 전용 시장가로 청산", x.get("status") == "FILLED", {"status": x.get("status"),
                                                                          "avg": x.get("avgPrice")})
            mine.add(str(x["orderId"]))
        cancel_everything(c, s)
        clean = self._until(lambda: float(c.position(s)["positionAmt"]) == 0 and not c.open_orders(s)
                            and not c.open_algo_orders(s))
        self._step("포지션 없음, 주문·조건 주문 없음", clean,
                   {"positionAmt": c.position(s)["positionAmt"], "orders": len(c.open_orders(s)),
                    "plan_orders": len(c.open_algo_orders(s))})
        t1 = c.clock_ms() + c.offset_ms

        def pnl():
            fills = [f for f in c.user_trades(s, t0 - 5_000, t1 + 5_000) if str(f["orderId"]) in mine]
            return fills if balanced(self.side, fills, spec["qty_step"]) else None
        fills = self._until(pnl, tries=8, pause=1.5)
        if not fills and fired and not fired.get("actualOrderId"):
            # the stop's own market order id was not found: every fill of the drill's minutes on this coin
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
            tol = max(0.02, 2e-4 * notional)
            ok = (abs(realized - by_fills) <= max(1e-6, 1e-7 * notional) and fees >= 0
                  and all(f.get("realizedCheck") == "ok" for f in outs)
                  and abs((w1 - w0) - (realized - fees)) <= tol)
            detail = {"fills": len(fills), "realized": round(realized, 6), "by_fill_prices": round(by_fills, 6),
                      "fees": round(fees, 6), "net": round(realized - fees, 6),
                      # paid fee per side, % of notional (expected about 0.042% after the TetherMax discount)
                      "fee_rate_pct": round(100 * fees / notional, 4) if notional else None,
                      "woo_profit": [f.get("wooProfit") for f in outs], "check": sorted({str(f.get("realizedCheck"))
                                                                                       for f in outs}),
                      "wallet_change": round(w1 - w0, 6)}
        self._step("체결로 계산한 손익 = 체결 가격 = WOO X Pro realised_profit = 지갑 변화(수수료 포함)", ok, detail)
        if fills:
            self._step("체결 기록에 수수료가 들어 있음(0이면 수수료를 못 읽는 것)", detail.get("fees", 0) > 0,
                       {"fee_rate_pct": detail.get("fee_rate_pct")}, fatal=False)
        return self.log

    def _trigger_test(self, s: str, sell: str, amt: float, stop_id: str, spec: dict) -> Optional[dict]:
        """The stop moved to TRIGGER_GAP from the last price (on the losing side) and left to fire for real: the
        position must close by itself, and the stop must read as fired (its market order's id when WOO X Pro names it).
        Not reached in time: noted (not a failure), and the cycle closes the position itself."""
        c = self.client
        entry = float(c.position(s)["entryPrice"] or 0)
        start = self.elapsed()
        last = c.price(s)
        shown = [0]
        if entry and self.side * (last - entry * (1 + self.side * PROFIT_GAP)) < 0:
            self._note(f"이익 쪽 손절 시험: 가격이 진입가보다 {PROFIT_GAP * 100:g}% 유리해지기를 기다립니다"
                       f"(최대 {min(PROFIT_WAIT_S, self.trigger_wait_s) / 60:.0f}분). 기다리는 것이 정상입니다: 창을 닫거나 Ctrl+C를 "
                       "누르지 마세요")
        while entry and self.side * (last - entry * (1 + self.side * PROFIT_GAP)) < 0 \
                and self.elapsed() - start < min(PROFIT_WAIT_S, self.trigger_wait_s):
            self.wait(5.0)
            self._waiting(start, shown, "이익 쪽 손절 시험")
            if float(c.position(s)["positionAmt"]) == 0:          # the earlier stop fired while waiting: that is the test
                got = self._until(lambda: (lambda o: o if o.get("algoStatus") in ("TRIGGERED", "CANCELED") else None)(
                    self._algo_or_empty(stop_id)), tries=10, pause=1.5) or self._algo_or_empty(stop_id)
                self._step("손절 발동 시험: 가격이 닿자 WOO X Pro가 포지션을 스스로 닫음", got.get("algoStatus") == "TRIGGERED",
                           {"status": got.get("algoStatus"), "actualOrderId": got.get("actualOrderId")}, fatal=False)
                return got
            last = c.price(s)
        level = round_stop(last * (1 - self.side * TRIGGER_GAP), spec["tick"], self.side)
        mv = move_stop(c, s, sell, level, abs(amt), [stop_id], client_id=ext_id(None))
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
        self._note(f"손절 발동 시험: 시험 손절 {level:g}(지금 가격 {last:g})에 가격이 닿기를 기다립니다"
                   f"(최대 {self.trigger_wait_s / 60:.0f}분). 기다리는 것이 정상입니다: 창을 닫거나 Ctrl+C를 누르지 마세요")
        while self.elapsed() - start < self.trigger_wait_s:
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
        got = self._until(lambda: (lambda o: o if o.get("algoStatus") in ("TRIGGERED", "CANCELED") else None)(
            self._algo_or_empty(sid)), tries=10, pause=1.5) or self._algo_or_empty(sid)
        self._step("손절 발동 시험: 가격이 닿자 WOO X Pro가 포지션을 스스로 닫음",
                   got.get("algoStatus") == "TRIGGERED",
                   {"stop": level, "status": got.get("algoStatus"), "actualOrderId": got.get("actualOrderId")},
                   fatal=False)
        return got

    def _algo_or_empty(self, sid: str) -> dict:
        try:
            return self.client.algo_order(algo_id=sid)
        except TestnetError:
            return {}


def row_text(row: dict) -> str:
    return ("[OK]  " if row["ok"] else "[FAIL]") + f" {row['step']}: {row['detail']}"


def leave_flat(c: WooXProClient, sym: str, add) -> None:
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
        add("정리 후 상태", amt == 0 and left == (0, 0),
            {"positionAmt": amt, "orders": left[0], "plan_orders": left[1]})
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


def specs_text(c: WooXProClient, symbols=COINS) -> str:
    lines = []
    for s in symbols:
        sp = c.spec(s)
        px = c.price(s)
        lines.append(f"{s}: 1계약 {sp['contract_size']} {sp.get('base_coin') or ''}, 최소 {sp['min_vol']}계약"
                     f"(지금 약 ${sp['min_qty'] * px:,.4f}), 가격 단위 {sp['price_unit']}, 최대 {sp['max_leverage']:g}배, "
                     f"상태 {sp['status']}, 펀딩 {sp.get('funding_interval_hours')}시간마다")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "drill", "reconcile", "specs"])
    ap.add_argument("--symbol", default=None, help="drill order coin (default: the cheapest smallest order)")
    ap.add_argument("--side", choices=["long", "short"], default="long")
    ap.add_argument("--confirm-order", default="", help=f"{DRILL_CONFIRM}: run the one real order cycle")
    ap.add_argument("--no-trigger-test", action="store_true", help="close by hand instead of letting the stop fire")
    ap.add_argument("--leverage", type=int, default=None,
                    help="every coin isolated at this leverage instead of BTC 40x / the others 30x, and the largest "
                         "position it allows (WOO X Pro 2, docs/friend-bot-ko.md: 35)")
    ap.add_argument("--stop-net-roe", type=float, default=None,
                    help="with --leverage: the stop's net ROE (0.5 = -50 %%): per coin, the liquidation at that "
                         "leverage for margin 40 %% of the balance against the stop")
    args = ap.parse_args(argv)
    if args.cmd == "specs":                 # public data only: no key needed
        c = public_client()
        c.sync_time()
        print(f"서버 시간 차이 {c.offset_ms} ms ({c.time_source})")
        print(specs_text(c))
        return 0
    try:      # mainnet keys only: never the paper runner's key, a Binance, Bybit or MEXC key
        c, kc = clients(MODE_MAINNET, os.environ, read_env_file(PAPER_ENV_FILE))
    except Refused as e:
        print(f"시작하지 않습니다: {e}", file=sys.stderr)
        return 2
    c.sync_time()
    if args.cmd == "reconcile":
        print(json.dumps(reconcile(c, args.symbol or "BTCUSDT"), indent=1))
        return 0
    pace(c)
    d = WooXProDrill(c, symbol=args.symbol, side=1 if args.side == "long" else -1, keycheck=kc,
                     trigger_test=not args.no_trigger_test, say=say, leverage=args.leverage,
                     stop_net_roe=args.stop_net_roe if args.leverage else None)
    # a closed terminal (SIGHUP) or a stop (SIGTERM) mid-drill: leave the account flat before exiting
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _interrupt)
    return 0 if run_drill(c, d, args.cmd, args.confirm_order == DRILL_CONFIRM, signals=True) else 1


def run_drill(c: WooXProClient, d: WooXProDrill, cmd: str, confirmed: bool, pause=time.sleep,
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
