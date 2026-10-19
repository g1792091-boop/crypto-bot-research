"""MEXC USDT-M perpetual futures (contract API v1) for the executor: client, host allowlist, keys, key check, drill.
``"exchange": "mexc"`` in the executor config uses it (mainnet only: MEXC has no futures testnet); the Binance and Bybit
paths are unchanged.

    python -m paperbot.mexc check                          # read-only checks + one-way mode + leverage 40/30 (no order)
    python -m paperbot.mexc drill                          # the same checks; the order cycle needs --confirm-order
    python -m paperbot.mexc drill --symbol DOGEUSDT --confirm-order REAL_ORDER   # + one smallest-size order cycle
    python -m paperbot.mexc specs                          # the 6 coins' live contract specs (no order)

Sources (read as data, 2026-10-18; mexc.com is not reachable from where this was written):
- ccxt 4.5.88 (pypi), ccxt/mexc.py and ccxt/abstract/mexc.py: hosts (mexc.py:168-171: contract API on
  https://api.mexc.com/api/v1/contract and /api/v1/private), the contract endpoint list (mexc.py:303-410), signing
  (mexc.py:6035-6062), the response envelope (mexc.py:6065-6087), order create (mexc.py:2436-2560: side 1 open long,
  2 close short, 3 open short, 4 close long; openType 1 isolated / 2 cross; leverage required for isolated;
  externalOid; trigger orders on planorder/place with triggerType / executeCycle / trend / orderType), order by id
  (2711), plan list with states=1 (3076), plan cancel as a JSON list (3219), cancel-all (3336-3338), positions (5071),
  position mode (5567, 5588), leverage (5804, 4242, 5979), deals (4063), funding (4270), transfers (5316), assets
  (3660), contract detail (1388), ticker (1983), server time (1123).
- MEXC's own contract v1 docs (github.com/mexcdevelop/apidocs, branch gh-pages, contract_v1_en/index.html): the
  signature rules (accessKey + Request-Time + parameter string; GET/DELETE: parameters sorted, '&'-joined, URL-encoded;
  POST: the JSON body as sent; hex HMAC-SHA256), the 10 s request-time window, the error code table, the field
  meanings (order state 1-5, plan state 1-5, plan ``orderId`` = the order it placed when executed, executeCycle in
  hours, deal ``profit``, funding ``funding`` + received, transfer IN/OUT), the rate limits (20 per 2 s; contract detail
  1 per 5 s) and External order ID <= 32 characters (error 2030).
What only a live run can confirm is listed in docs/mexc-ko.md (the drill checks each).

The client answers in the SAME shapes the executor reads from the Binance client (paperbot/testnet.py), like
paperbot/bybit.py, so the executor, the stop protocol (place_stop / move_stop / live_stops / covers) and livepnl run
unchanged. Quantities: MEXC counts contracts (``vol``); the client converts with the live contract detail
(contractSize, volUnit, minVol, priceUnit): base quantity = vol x contractSize, never a hard-coded size.

  Binance client call          MEXC contract v1
  spec(symbol)                 GET  /api/v1/contract/detail (all contracts, once: 1 request / 5 s)
  mark / price                 GET  /api/v1/contract/ticker   fairPrice / lastPrice
  sync_time                    GET  /api/v1/contract/ping
  account()                    GET  /api/v1/private/account/assets   USDT equity; wallet = equity - unrealized
  one_way()                    GET  /position/position_mode; 1 (hedge) -> POST /position/change_position_mode 2
  isolated(symbol)             POST /position/change_leverage openType 1 for both position types (BTC 40x, others 30x),
                               read back with GET /position/leverage (MEXC's margin mode is per order: openType 1 on
                               every order)
  leverage(symbol, n)          the same with n, after checking one-way mode; refused unless both sides read back n
  market(...)                  POST /order/create type 5 (market), side 1/3 open, 2/4 close, openType, leverage,
                               externalOid (the client id), then read back by id (GET /order/get/{id})
  order(symbol, id / cid)      GET  /order/get/{id} or /order/external/{symbol}/{externalOid}
  stop_close(...)              POST /planorder/place: a CLOSE-side trigger order (side 4 closes a long, 2 a short: can
                               never open or flip a position), triggerType 2 (<=, a long's stop) / 1 (>=, a short's),
                               trend 1 (last price = Binance CONTRACT_PRICE), orderType 5 (market), executeCycle 2 (7
                               days: refreshed after 6 days, see ``refreshAt``), vol = the position's contracts
  algo_order / open_algo_orders GET /planorder/list/orders (states=1 for the open list)
  cancel_algo / cancel_all_algo POST /planorder/cancel [{symbol, orderId}] / /planorder/cancel_all
  cancel_all / open_orders     POST /order/cancel_all / GET /order/list/open_orders/{symbol}
  position / positions         GET  /position/open_positions   holdVol x contractSize, positionType 1 long / 2 short
  user_trades                  GET  /order/list/order_deals -> fills; realized P&L replayed from the fills' own prices
                               and cross-checked against each deal's ``profit``
  income                       GET  /position/funding_records (FUNDING_FEE) + /account/transfer_record (TRANSFER, IN +
                               / OUT -) + changes of the ``bonus`` balance (TRANSFER, not trading P&L)

Why the stop is a plan (trigger) order, not the position stop-loss (stoporder/*): ccxt places MEXC stop orders through
planorder/place (mexc.py:2538-2548) and documents its whole request; the position stop-loss endpoints have no request
shape in ccxt (stopLossPrice: "todo") and are tied to a positionId. A plan order with a CLOSE side is reduce-only by
its side, triggers on the last price like the Binance path, and fits the executor's protocol unchanged: a moved stop is
a new plan order first, confirmed in the list, then the old one cancelled (no gap; two close-side orders can never open
anything, the second simply fails once the first closed the position). It is never amended in place (an amend whose
answer is lost would leave the live level unknown).

Signing (MEXC docs, ccxt mexc.py:6035-6062): Signature = hex HMAC-SHA256(secret, apiKey + Request-Time + parameter
string); parameter string = the GET query sorted by name, '&'-joined, URL-encoded (sent exactly as signed), or the JSON
body of a POST as sent. Headers ApiKey, Request-Time (ms), Signature, Content-Type: application/json. Answers are
{success, code, data} (or {success: false, code, message}); success false is an error even with HTTP 200.
Errors map to the Binance client's classes: 510 / 2037 / HTTP 429 -> RateLimited (an OPENING order's rate-limit answer
is "outcome unknown" instead: it is looked up, never sent again), HTTP 403 -> the 418 ban handling, timeouts, 5xx, 9999,
500, 501, 504 -> TransientError, 513 (request time outside the window) -> the clock refusal (-1021: re-sync and resend),
603 (repeated request) -> re-sync, then TransientError (looked up by the client id before any resend), 2040 / 5002 ->
order not found (-2013), 2041 -> already done (-2011).

Safety:
- ``MexcClient`` talks to api.mexc.com / contract.mexc.com only (class-level allowlist, https only, checked at
  construction; the executor checks again). Mainnet only: there is no MEXC futures testnet.
- Keys: MEXC_LIVE_KEY / MEXC_LIVE_SECRET behind PAPERBOT_LIVE_MAINNET=I_UNDERSTAND; never the paper runner's key, a
  Binance key or a Bybit key.
- Key gate: MEXC does not report a key's permissions through the API. The gate proves the key reads the futures account
  (account/assets) and position mode (a trading-permission read in the docs); withdrawals off and the IP binding are the
  owners' statement MEXC_LIVE_KEY_CHECKED=FUTURES_ONLY_NO_WITHDRAW_IP_BOUND (refused without it), shown as a warning at
  every start.
- An order that was accepted (it has an id) is never reported as not executed; an answer that was lost is looked up by
  its externalOid; an opening order is never sent twice (the executor's rule, kept by this client for MEXC's rate-limit
  answers too).
- One executor database, one exchange (executor.py refuses a database of another exchange).
- A position's size, the account equity and the stop list are never read as 0 / flat / empty from a missing or garbled
  field: such an answer is an error.
- AI agents never import this module (tests/test_mexc.py checks it).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import json
import math
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Callable, Optional

from . import bybit as BY
from .livepnl import balanced
from .mainnet import (FLAG, FLAG_VALUE, LIVE_KEY_NAMES as BINANCE_LIVE_KEY_NAMES, MODE_MAINNET, MODE_TESTNET,
                      PAPER_ENV_FILE, PAPER_KEY_NAMES, TESTNET_KEY_NAMES as BINANCE_TESTNET_KEY_NAMES, Refused,
                      check_permissions, read_env_file)
from .testnet import (BAD_TIMESTAMP, NOT_FOUND, WOULD_TRIGGER, ProtectionError, RateLimited, TestnetError,
                      TransientError, cancel_everything, covers, hide_process_memory, live_stops, move_stop,
                      place_stop, round_stop, urllib_send)

SETTLE = "USDT"
MEXC_BASE = "https://api.mexc.com"
MEXC_HOSTS = ("api.mexc.com", "contract.mexc.com")   # ccxt 4.5.88 (api.mexc.com); MEXC's v1 docs (contract.mexc.com)
PUBLIC = "/api/v1/contract"
PRIVATE = "/api/v1/private"
LIVE_KEY_NAMES = ("MEXC_LIVE_KEY", "MEXC_LIVE_SECRET")
KEY_CHECKED = "MEXC_LIVE_KEY_CHECKED"                 # the owners' statement: what the API cannot report
KEY_CHECKED_VALUE = "FUTURES_ONLY_NO_WITHDRAW_IP_BOUND"
DRILL_CONFIRM = "REAL_ORDER"
# MEXC refuses an order under 5 USDT (code 7008 "Cannot be less than the minimum order amount 5 USDT", seen on the
# owners' first live drill 2026-10-19): the executor's spec carries it as min_notional, the drill orders a bit above it
MIN_ORDER_USDT = 5.0
DRILL_ORDER_USDT = 6.0
# the drill reads six coins at once: MEXC answered "Requests are too frequent" (code 510) on the owners' live drill
# 2026-10-19, so the drill spaces its requests (the executor's loop has its own retries and waits)
DRILL_MIN_GAP_S = 0.25
DRILL_PAUSE_S = 3.0
# owners 2026-10-17: BTC 40x, the other coins 30x (set at the start; the entry itself sets the paper account's leverage)
FIXED_LEVERAGE = {"BTCUSDT": 40}
DEFAULT_LEVERAGE = 30
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
PREFIX = {MODE_MAINNET: "[MEXC 실거래 실행기]", MODE_TESTNET: "[MEXC 실행기]"}

OPEN_LONG, CLOSE_SHORT, OPEN_SHORT, CLOSE_LONG = 1, 2, 3, 4
ISOLATED, CROSS = 1, 2
HEDGE, ONE_WAY = 1, 2
TRIGGER_GE, TRIGGER_LE = 1, 2              # trigger when the price is >= / <= the trigger price
TREND_LAST = 1                             # trigger price type: 1 latest price, 2 fair price, 3 index price
WORKING_TYPE = {1: "CONTRACT_PRICE", 2: "MARK_PRICE", 3: "INDEX_PRICE"}
PLAN_MARKET = 5                            # a plan order's orderType: 5 market
CYCLE_7D = 2                               # executeCycle 1: 24 hours, 2: 7 days (the list answers it in hours)
CYCLE_HOURS = {1: 24, 2: 168}
REFRESH_BEFORE_MS = 86_400_000             # a stop is placed again (new first, old one cancelled) a day before expiry
REFRESH_MAX_AGE_MS = 6 * 86_400_000
MARKET_TYPES = (5, 6)                      # order type 5 market; 6 "convert market price to current price" (ccxt's)

# error codes (MEXC contract v1 docs "Error code")
TIME_CODES = (513,)                        # request time outside the window: refused, not executed
REPLAY_CODES = (603,)                      # "Repeated requests": re-sync the clock; the outcome is looked up
RATE_CODES = (510, 2037)                   # too frequent
TRANSIENT_CODES = (9999, 500, 501, 504)    # public abnormal / internal error / busy / gateway timeout
NOT_FOUND_CODES = (2040, 5002)             # order not exist / stop-limit order not exist
GONE_CODES = (2041,)                       # order state cannot be cancelled (done or cancelled)
ORDER_FINAL = ("FILLED", "CANCELED", "REJECTED", "EXPIRED")
PLAN_STATUS = {1: "NEW", 2: "CANCELED", 3: "TRIGGERED", 4: "EXPIRED", 5: "REJECTED"}
ORDER_WAITS = (0.05, 0.1, 0.2, 0.4)        # a market order is read back after these
RATE_WINDOW_MS, RATE_LIMIT = 2000, 20      # 20 requests / 2 s per endpoint
PAGE_SIZE = 100
MAX_PAGES = 50
LIST_SPAN_MS = 89 * 86_400_000             # plan / deal lists: start and end at most 90 days apart
MATCH_SLACK_MS = 10_000                    # a plan order found by its fingerprint was created after we sent it
RECENT_MS = 2 * 86_400_000                 # a plan order looked up by id: the open list, then 2 days, then 89 days


def hosts_for(mode: str) -> tuple:
    return MEXC_HOSTS                      # one host list: mainnet only


# ---------------------------------------------------------------- numbers and names
def _dec(v, what: str = "value") -> Decimal:
    """A number the decision depends on (a size, a price, the equity): missing or garbled is an error, never 0."""
    if v is None or v == "" or isinstance(v, bool):
        raise TransientError(200, None, f"MEXC 응답에 {what} 값이 없습니다")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError) as e:
        raise TransientError(200, None, f"MEXC 응답의 {what} 값이 이상합니다: {v!r}") from e
    if not d.is_finite():
        raise TransientError(200, None, f"MEXC 응답의 {what} 값이 이상합니다: {v!r}")
    return d


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _num(d) -> str:
    """Decimal -> a plain number string like the Binance answers ("0.05", "-3", "0")."""
    d = Decimal(str(d))
    if d == 0:
        return "0"
    return format(d.normalize(), "f")


def _int(v, default: int = 0) -> int:
    try:
        return int(Decimal(str(v)))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _price_str(x: float, tick: str) -> str:
    """A price (already on the tick: round_stop) as a plain string on the tick."""
    t = Decimal(tick)
    n = (Decimal(repr(float(x))) / t).to_integral_value()
    return _num(n * t)


def _id60(*parts) -> int:
    return int(hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:15], 16)


def mx(symbol: str) -> str:
    """BTCUSDT -> BTC_USDT."""
    if not symbol.endswith(SETTLE) or len(symbol) <= len(SETTLE):
        raise TestnetError(400, "NO_SYMBOL", f"{symbol}: USDT 무기한 이름이 아닙니다")
    return f"{symbol[:-len(SETTLE)]}_{SETTLE}"


def bn(mexc_symbol: Optional[str]) -> str:
    """BTC_USDT -> BTCUSDT."""
    return str(mexc_symbol or "").replace("_", "")


_EXT_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def ext_id(client_id: Optional[str]) -> str:
    """The externalOid for an executor client id: <= 32 characters (error 2030), letters, digits, '-' and '_' (it is
    also a URL path part of the look-up). Deterministic, so a look-up after a lost answer finds the order."""
    if client_id is None:
        return "pb" + hashlib.sha1(f"{time.time_ns()}|{os.getpid()}".encode()).hexdigest()[:24]
    if 0 < len(client_id) <= 32 and set(client_id) <= _EXT_OK:
        return client_id
    return "pbh" + hashlib.sha1(client_id.encode()).hexdigest()[:29]


def query_string(params: dict) -> str:
    """The signed GET parameter string: sorted by name, URL-encoded (spaces as %20), booleans as true/false."""
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
    """The POST body exactly as sent and signed (compact JSON, like ccxt)."""
    return json.dumps(body, separators=(",", ":"))


def signature(secret: str, api_key: str, req_time: str, param_string: str) -> str:
    return hmac.new(secret.encode(), (api_key + req_time + param_string).encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- fills and realized P&L (pure)
def fills_from_deals(deals: list, contract_size, symbol: str) -> list:
    """MEXC deals (/order/list/order_deals) -> Binance userTrades-like fills with ``realizedPnl``.

    Quantities are converted from contracts (vol x contractSize). Sides: 1 open long and 2 close short are buys, 3 open
    short and 4 close long are sells; 2 and 4 close. The realized P&L of a closing fill is replayed from the fills'
    own prices in time order (closed quantity x (fill price - average entry) x side of the position it closes), never
    from a field whose meaning could be misread. A closing fill whose position opened before the first fill of the list
    takes MEXC's ``profit`` (``realizedSource`` "profit"), else 0 ("unknown").

    Cross-check: per closing order, the replayed realized P&L must equal MEXC's own ``profit`` of its deals within
    0.01 + 0.02 % of the notional + twice the order's fees (the docs do not say whether ``profit`` is before or after
    fees). A difference beyond that (a sign or a size) marks the order's fills ``realizedCheck`` "mismatch": the
    executor then keeps the wallet estimate for the trade and alerts."""
    cs = Decimal(str(contract_size))
    rows = sorted(deals, key=lambda d: (_int(d.get("timestamp")), str(d.get("id"))))
    out = []
    pos, avg = Decimal(0), Decimal(0)
    for d in rows:
        vol = _dec(d.get("vol"), "vol")
        qty = vol * cs
        px = _dec(d.get("price"), "price")
        code = _int(d.get("side"))
        if code not in (OPEN_LONG, CLOSE_SHORT, OPEN_SHORT, CLOSE_LONG):
            raise TransientError(200, None, f"{symbol}: 체결 방향이 이상합니다({d.get('side')!r})")
        sgn = 1 if code in (OPEN_LONG, CLOSE_SHORT) else -1
        closing_side = code in (CLOSE_SHORT, CLOSE_LONG)
        opposite = pos != 0 and (pos > 0) != (sgn > 0)
        closed, replay, known = Decimal(0), Decimal(0), True
        if opposite:
            k = min(qty, abs(pos))
            replay = k * (px - avg) * (1 if pos > 0 else -1)
            pos += sgn * k
            if pos == 0:
                avg = Decimal(0)
            closed = qty if closing_side else k
            known = k == closed
        elif closing_side:
            closed, known = qty, False                       # the position opened before the list
        opened = Decimal(0) if closing_side else qty - closed
        if opened > 0:
            if pos == 0 or (pos > 0) == (sgn > 0):
                avg = (abs(pos) * avg + opened * px) / (abs(pos) + opened)
            pos += sgn * opened
        profit = d.get("profit")
        profit = None if profit in (None, "") else _dec(profit, "profit")
        if closed > 0 and known:
            realized, source = replay, "replay"
        elif closed > 0 and profit is not None:
            realized, source = profit, "profit"
        elif closed > 0:
            realized, source = Decimal(0), "unknown"
        else:
            realized, source = Decimal(0), "open"
        fee = d.get("fee")
        taker = d.get("isTaker", d.get("taker"))
        out.append({"symbol": symbol, "id": _id60("deal", d.get("id")), "dealId": str(d.get("id")),
                    "orderId": str(d.get("orderId")), "side": "BUY" if sgn > 0 else "SELL", "price": _num(px),
                    "qty": _num(qty), "vol": _num(vol), "quoteQty": _num(px * qty), "realizedPnl": _num(realized),
                    "realizedSource": source, "commission": _num(_dec(fee, "fee")) if fee not in (None, "") else "0",
                    "commissionAsset": d.get("feeCurrency") or SETTLE, "time": _int(d.get("timestamp")),
                    "maker": taker is False, "closedSize": _num(closed), "mexcSide": code,
                    "mexcProfit": None if profit is None else _num(profit), "positionSide": "BOTH",
                    "marginAsset": SETTLE, "realizedCheck": None})
    _check_against_profit(out)
    return out


def _check_against_profit(fills: list) -> None:
    by: dict = {}
    for f in fills:
        if f["realizedSource"] == "replay":
            by.setdefault(str(f["orderId"]), []).append(f)
    for fs in by.values():
        if any(f.get("mexcProfit") is None for f in fs):
            for f in fs:
                f["realizedCheck"] = "unchecked"
            continue
        ours = sum(Decimal(f["realizedPnl"]) for f in fs)
        theirs = sum(Decimal(f["mexcProfit"]) for f in fs)
        fees = sum(abs(Decimal(f["commission"])) for f in fs)
        notional = sum(Decimal(f["closedSize"]) * Decimal(f["price"]) for f in fs)
        bad = abs(ours - theirs) > Decimal("0.01") + Decimal("0.0002") * notional + 2 * fees
        for f in fs:
            f["realizedCheck"] = "mismatch" if bad else "ok"


def permission_record(attested: bool, position_mode) -> dict:
    """The Binance apiRestrictions fields mainnet.check_permissions reads. MEXC reports no key permissions: reading the
    futures account and the position mode (a trading-permission read in MEXC's docs) is what this key was seen to do;
    withdrawals off and the IP binding are the owners' statement (``attested``), never assumed."""
    extra = []
    if not attested:
        extra.append(f"MEXC는 키 권한을 API로 알려 주지 않습니다. 키를 '선물 거래만, 출금 없음, 서버 IP만'으로 만든 것을 "
                     f"확인한 뒤 /etc/paperbot/executor.env에 {KEY_CHECKED}={KEY_CHECKED_VALUE} 를 넣으세요")
    return {
        "enableReading": True,
        "enableWithdrawals": False if attested else None,
        "enableFutures": _int(position_mode, 0) in (HEDGE, ONE_WAY),
        "ipRestrict": True if attested else None,
        "extraProblems": extra,
        "warnings": [f"MEXC는 키 권한을 API로 알려 주지 않습니다. 확인한 것: 선물 계정 읽기, 포지션 모드 읽기(거래 권한). "
                     f"출금 꺼짐·서버 IP 제한은 두 분이 확인한 내용({KEY_CHECKED})입니다"] if attested else [],
        "attested": attested, "positionMode": position_mode,
    }


# ---------------------------------------------------------------- client
class MexcClient:
    """Signed REST client for MEXC USDT-M perpetuals (contract API v1), real money only. Answers are translated into the
    Binance client's shapes (see the module docstring)."""
    __test__ = False
    HOSTS: tuple = MEXC_HOSTS
    DEFAULT_BASE = MEXC_BASE
    KEY_NAMES = LIVE_KEY_NAMES
    AGENT = "paperbot-mexc-live/0.1"
    EXCHANGE = "mexc"
    PNL_RECORD = "MEXC 체결 profit"
    # a stop bigger than the position is replaced by one of the position's size (the executor's _cover): what MEXC does
    # with a triggered close order larger than the position is not documented
    EXACT_STOP_SIZE = True
    # the executor adds a random part to its stop and close ids: MEXC may answer an externalOid used before with that
    # old order (its batch endpoint is documented to), so a repeated id must never happen
    UNIQUE_CLIENT_IDS = True

    def __init__(self, api_key: str, api_secret: str, base: Optional[str] = None, send=None,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                 on_request: Optional[Callable[[dict], None]] = None, sleep: Callable[[float], None] = time.sleep,
                 market_type: int = 5):
        base = (base or self.DEFAULT_BASE).rstrip("/")
        u = urllib.parse.urlparse(base)
        host = u.hostname or ""
        if host not in type(self).HOSTS or u.scheme != "https" or u.path not in ("",) or u.port not in (None, 443):
            raise ValueError(f"refusing {base!r}: {type(self).__name__} only talks to https://{type(self).HOSTS}")
        if not (api_key and api_secret):
            raise ValueError(f"{self.KEY_NAMES[0]} and {self.KEY_NAMES[1]} are required")
        if market_type not in MARKET_TYPES:
            raise ValueError(f"market_type {market_type!r}: 5 or 6")
        self.base, self.host, self.key, self.secret = base, host, api_key, api_secret
        self.send = send or urllib_send
        self.clock_ms = clock_ms
        self.sleep = sleep
        self.offset_ms = 0
        self.on_request = on_request
        self.market_type = market_type
        self.create_path = "/order/create"   # or "/order/submit" once order/create answered HTTP 404 (_create)
        self.specs: dict = {}            # BTCUSDT -> spec (live contract detail, cached for the process)
        self.detail_ms: Optional[int] = None
        self.hits: dict = {}             # rate-limit key -> request times (ms) in the last window
        self.order_symbol: dict = {}     # order / plan id -> symbol (a plan cancel needs the symbol)
        self.plan_by_cid: dict = {}      # externalOid -> plan id (answers we got)
        self.cid_by_plan: dict = {}      # plan id -> externalOid
        self.pending_plans: dict = {}    # externalOid -> (symbol, side code, trigger, vol, sent ms): found by these
        self.pos_rows: dict = {}         # symbol -> the last position row (openType, leverage for a close order)
        self.lev: dict = {}              # symbol -> leverage set by leverage()
        self.bonus_seen: Optional[Decimal] = None
        self.bonus_rows: list = []       # bonus balance changes as TRANSFER income rows

    # ------------------------------------------------------------ transport
    def _now(self) -> int:
        return int(self.clock_ms() + self.offset_ms)

    def _hit(self, key: str) -> None:
        now = self.clock_ms()
        lst = [t for t in self.hits.get(key, []) if now - t < RATE_WINDOW_MS]
        lst.append(now)
        self.hits[key] = lst

    def throttle_s(self, share: float = 0.8) -> float:
        """Seconds to wait before the next request: an endpoint that used ``share`` of its 20 requests per 2 s waits
        until the oldest one leaves the window."""
        now = self.clock_ms()
        wait = 0.0
        for lst in self.hits.values():
            recent = [t for t in lst if now - t < RATE_WINDOW_MS]
            if len(recent) >= share * RATE_LIMIT:
                wait = max(wait, (min(recent) + RATE_WINDOW_MS - now) / 1000.0)
        return max(0.0, min(wait, RATE_WINDOW_MS / 1000.0))

    def req(self, method: str, path: str, params=None, signed: bool = True, limit_key: Optional[str] = None):
        """One request. ``params``: a dict (GET query or POST body) or a list (a POST body that is a JSON list).
        Returns the answer's ``data``."""
        audit = {"method": method, "path": path,
                 "params": dict(params) if isinstance(params, dict) else list(params or [])}
        headers = {"User-Agent": self.AGENT, "Accept": "application/json"}
        if method in ("GET", "DELETE"):
            payload = query_string(params or {})
            body = None
            url = f"{self.base}{path}" + (f"?{payload}" if payload else "")
        else:
            body_obj = params if params is not None else {}
            if isinstance(body_obj, dict):
                body_obj = {k: v for k, v in body_obj.items() if v is not None}
                audit["params"] = dict(body_obj)
            payload = body_string(body_obj)
            body = payload.encode()
            url = f"{self.base}{path}"
        if signed:
            ts = str(self._now())
            headers.update({"ApiKey": self.key, "Request-Time": ts, "Content-Type": "application/json",
                            "Signature": signature(self.secret, self.key, ts, payload)})
        elif body is not None:
            headers["Content-Type"] = "application/json"
        self._hit(limit_key or path)
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
        msg = (data.get("message") or data.get("msg") if isinstance(data, dict) else None) or str((raw or b"")[:200])
        err: Optional[TestnetError] = None
        if status == 403:
            # a WAF / IP block: never retried in the request, the loop waits (the executor's 418 ban handling)
            err = RateLimited(418, code, f"HTTP 403 (IP 차단 또는 막힌 지역): {msg}"[:300], 300.0)
        elif status == 429:
            try:
                after = float(hdr.get("retry-after") or 2.0)
            except ValueError:
                after = 2.0
            err = RateLimited(429, code, msg or "rate limited", after)
        elif status >= 500 or status in (0, 408):
            err = TransientError(status, code, msg or "server error")
        elif status != 200:
            err = TestnetError(status, code, msg)
        elif not isinstance(data, dict) or ("success" not in data and "code" not in data):
            err = TransientError(status, None, f"응답이 MEXC 형식(success/code)이 아닙니다: {msg}"[:200])
        else:
            ok = data.get("success") is True or ("success" not in data and code in (0, 200))
            if not ok:
                err = self._error(code, msg)
        self._audit(audit, status=status, data=data, err=err)
        if err is not None:
            raise err
        return data.get("data")

    def _error(self, code, msg: str) -> TestnetError:
        text = f"{msg} (MEXC code {code})"
        if not isinstance(code, int) or code in (0, 200):
            return TransientError(200, None, f"MEXC가 실패(success=false)라고만 답했습니다: {text}")
        if code in TIME_CODES:
            err = TestnetError(400, BAD_TIMESTAMP, text)
        elif code in REPLAY_CODES:
            try:                                   # a replayed / repeated request: the clock first, then look it up
                self.sync_time()
            except TestnetError:
                pass
            err = TransientError(400, code, f"반복 요청으로 거절(결과 모름, 주문 번호로 확인): {text}")
        elif code in RATE_CODES:
            err = RateLimited(429, code, text, 2.0)
        elif code in TRANSIENT_CODES:
            err = TransientError(400, code, text)
        elif code in NOT_FOUND_CODES:
            err = TestnetError(400, NOT_FOUND[0], text)
        elif code in GONE_CODES:
            err = TestnetError(400, NOT_FOUND[1], text)
        else:
            err = TestnetError(400, code, text)
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

    def _pages(self, path: str, params: dict, time_key: Optional[str] = None, since: Optional[int] = None,
               limit_key: Optional[str] = None) -> list:
        """Every page of a paged list (page_num / page_size; ``data`` a list or {resultList, totalPage}). A page that
        is not a list is an error (never "empty"); too many pages raise (never a partial list as complete). With
        ``since``: stops once a newest-first page reaches rows older than it."""
        out, size = [], None
        for page in range(1, MAX_PAGES + 1):
            data = self.req("GET", path, {**params, "page_num": page, "page_size": PAGE_SIZE}, limit_key=limit_key)
            total = None
            if isinstance(data, dict) and isinstance(data.get("resultList"), list):
                rows, total = data["resultList"], data.get("totalPage")
            elif isinstance(data, list):
                rows = data
            else:
                raise TransientError(200, None, f"{path}: 목록이 아닌 응답 {str(data)[:80]!r}")
            out += rows
            # the end: an empty page, the last page by totalPage, or a page shorter than an earlier one (a first page
            # shorter than asked may be MEXC's own page cap: the next page is read to be sure)
            if not rows or (total is not None and page >= _int(total)) or (size is not None and len(rows) < size):
                return out
            size = max(size or 0, len(rows))
            if since is not None and time_key:
                ts = [_int(r.get(time_key)) for r in rows]
                if ts == sorted(ts, reverse=True) and ts[-1] < since:
                    return out
        raise TransientError(0, None, f"{path}: 쪽이 {MAX_PAGES}개를 넘습니다")

    # ------------------------------------------------------------ market data
    def sync_time(self) -> int:
        t0 = self.clock_ms()
        data = self.req("GET", PUBLIC + "/ping", signed=False)
        t1 = self.clock_ms()
        server = int(_dec(data, "server time"))
        self.offset_ms = server - (t0 + t1) // 2
        return self.offset_ms

    def _load_detail(self) -> None:
        now = self.clock_ms()
        if self.detail_ms is not None and now - self.detail_ms < 5_000:
            return                                         # 1 request / 5 s: the cache stands
        data = self.req("GET", PUBLIC + "/detail", signed=False, limit_key="detail")
        self.detail_ms = now
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else None
        if rows is None:
            raise TransientError(200, None, f"계약 정보 응답이 이상합니다: {str(data)[:80]!r}")
        for row in rows:
            if not isinstance(row, dict) or row.get("settleCoin") != SETTLE or row.get("quoteCoin") != SETTLE:
                continue
            try:
                self.specs[bn(row.get("symbol"))] = self._spec_row(row)
            except TestnetError:
                continue                                   # a contract with garbled units is never traded

    @staticmethod
    def _spec_row(row: dict) -> dict:
        cs, vu = _dec(row.get("contractSize"), "contractSize"), _dec(row.get("volUnit"), "volUnit")
        mv, pu = _dec(row.get("minVol"), "minVol"), _dec(row.get("priceUnit"), "priceUnit")
        if cs <= 0 or vu <= 0 or mv <= 0 or pu <= 0:
            raise TestnetError(400, "BAD_SPEC", f"{row.get('symbol')}: 계약 단위 정보가 이상합니다")
        maxv = row.get("maxVol")
        return {"qty_step": float(cs * vu), "min_qty": float(cs * mv), "tick": float(pu), "min_notional": MIN_ORDER_USDT,
                "max_leverage": _f(row.get("maxLeverage")), "status": row.get("state"),
                "api_allowed": row.get("apiAllowed"), "position_open_type": row.get("positionOpenType"),
                "contract_size": _num(cs), "vol_unit": _num(vu), "min_vol": _num(mv), "price_unit": _num(pu),
                "max_vol": _num(_dec(maxv, "maxVol")) if maxv not in (None, "") else None, "tick_str": _num(pu),
                "qty_step_str": _num(cs * vu), "mexc_symbol": row.get("symbol"), "base_coin": row.get("baseCoin"),
                "taker_fee": _f(row.get("takerFeeRate")), "maker_fee": _f(row.get("makerFeeRate"))}

    def spec(self, symbol: str) -> dict:
        """The contract's live spec (cached): sizes in base units for the executor (qty_step = contractSize x volUnit,
        min_qty = contractSize x minVol, tick = priceUnit), the raw contract units for the conversion."""
        if symbol not in self.specs:
            self._load_detail()
        if symbol not in self.specs:
            raise TestnetError(400, "NO_SYMBOL", f"{symbol}: MEXC USDT 무기한 계약에 없습니다")
        return dict(self.specs[symbol])

    def _spec(self, symbol: str) -> dict:
        return self.specs.get(symbol) or self.spec(symbol)

    def _contracts(self, symbol: str, qty: float) -> Decimal:
        """A base quantity -> contracts, floored to volUnit (never more than asked)."""
        sp = self._spec(symbol)
        step = Decimal(sp["contract_size"]) * Decimal(sp["vol_unit"])
        n = (Decimal(repr(float(qty))) / step + Decimal("1e-9")).to_integral_value(rounding=ROUND_FLOOR)
        return n * Decimal(sp["vol_unit"])

    def _qty(self, symbol: str, vol) -> Decimal:
        return _dec(vol, "vol") * Decimal(self._spec(symbol)["contract_size"])

    @staticmethod
    def _vol_json(v: Decimal):
        return int(v) if v == v.to_integral_value() else float(v)

    def _check_vol(self, symbol: str, vol: Decimal, qty: float, what: str) -> None:
        sp = self._spec(symbol)
        if vol <= 0 or vol < Decimal(sp["min_vol"]):
            raise TestnetError(400, "QTY_ZERO", f"{symbol}: {what} 수량 {qty}이 최소({sp['min_vol']}계약 = "
                                                f"{sp['min_qty']:g})보다 작습니다")
        if sp.get("max_vol") and vol > Decimal(sp["max_vol"]):
            raise TestnetError(400, "QTY_MAX", f"{symbol}: {what} {vol}계약이 최대 {sp['max_vol']}계약을 넘습니다")

    def _ticker(self, symbol: str) -> dict:
        data = self.req("GET", PUBLIC + "/ticker", {"symbol": mx(symbol)}, signed=False, limit_key="ticker")
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        row = next((x for x in rows if isinstance(x, dict) and x.get("symbol") == mx(symbol)), None)
        if row is None:
            raise TransientError(200, None, f"{symbol}: 시세가 비어 있습니다")
        return row

    def mark(self, symbol: str) -> float:
        return float(_dec(self._ticker(symbol).get("fairPrice"), "fairPrice"))

    def price(self, symbol: str) -> float:
        """Last traded price: what the stops trigger on (trend 1)."""
        return float(_dec(self._ticker(symbol).get("lastPrice"), "lastPrice"))

    def leverage_brackets(self) -> list:
        """Signal mode needs Binance-like notional brackets; MEXC's risk tiers count contracts. Not offered: the
        executor falls back to following the paper position (it warns once)."""
        raise TestnetError(400, "NO_BRACKETS", "MEXC는 빠른 진입(signal) 크기 계산용 레버리지 구간을 주지 않습니다")

    # ------------------------------------------------------------ account
    def account(self) -> dict:
        data = self.req("GET", PRIVATE + "/account/assets", limit_key="assets")
        if not isinstance(data, list):
            raise TransientError(200, None, f"자산 응답이 목록이 아닙니다: {str(data)[:80]!r}")
        usdt = next((r for r in data if isinstance(r, dict) and r.get("currency") == SETTLE), None)
        if usdt is None:          # never read as $0 (a daily-loss halt would close everything)
            raise TransientError(200, None, "자산 응답에 USDT 줄이 없습니다")
        equity, unreal = _dec(usdt.get("equity"), "equity"), _dec(usdt.get("unrealized"), "unrealized")
        bonus = _dec(usdt.get("bonus") if usdt.get("bonus") not in (None, "") else 0, "bonus")
        wallet = equity - unreal
        assets = [{"asset": SETTLE, "walletBalance": _num(wallet)}]
        for r in data:
            if isinstance(r, dict) and r.get("currency") != SETTLE and _f(r.get("equity")) > 0:
                assets.append({"asset": r.get("currency"), "walletBalance": str(r.get("equity"))})
        if bonus > 0:                                       # a bonus is not the budget's money
            assets.append({"asset": "BONUS", "walletBalance": _num(bonus)})
        self._note_bonus(bonus)
        return {"totalWalletBalance": _num(wallet), "totalUnrealizedProfit": _num(unreal),
                "totalMarginBalance": _num(equity), "assets": assets, "bonus": _num(bonus),
                "positionMargin": str(usdt.get("positionMargin")),
                "availableBalance": str(usdt.get("availableBalance")),
                "cashBalance": str(usdt.get("cashBalance")), "frozenBalance": str(usdt.get("frozenBalance"))}

    def _note_bonus(self, bonus: Decimal) -> None:
        """A change of the bonus balance is money that is not trading P&L: recorded as a TRANSFER income row (the
        executor moves its daily-loss and drawdown baselines by it)."""
        if self.bonus_seen is not None and bonus != self.bonus_seen:
            t = self._now()
            self.bonus_rows.append({"symbol": "", "incomeType": "TRANSFER", "income": _num(bonus - self.bonus_seen),
                                    "asset": SETTLE, "time": t, "tranId": _id60("bonus", t, bonus), "info": "BONUS"})
            self.bonus_rows = self.bonus_rows[-200:]
        self.bonus_seen = bonus

    def position_mode(self) -> int:
        mode = _int(self.req("GET", PRIVATE + "/position/position_mode", limit_key="position_mode"), 0)
        if mode not in (HEDGE, ONE_WAY):
            raise TransientError(200, None, f"포지션 모드 응답이 이상합니다({mode!r})")
        return mode

    def _busy(self) -> bool:
        """Any position, open order or untriggered plan order (every USDT contract)?"""
        if self.positions():
            return True
        if self._pages(PRIVATE + "/order/list/open_orders", {}, limit_key="open_orders"):
            return True
        return any(_int(r.get("state")) == 1 for r in self._plans(None, states="1"))

    def one_way(self) -> None:
        """One-way position mode (the executor's Binance assumption). Switched only with nothing open; not possible:
        Refused (the executor does not start)."""
        if self.position_mode() == ONE_WAY:
            return
        if self._busy():
            raise Refused("MEXC 포지션 모드가 양방향(hedge)이고 포지션·주문이 있어 단방향으로 못 바꿉니다. 정리한 뒤 앱에서 "
                          "단방향(One-way)으로 바꾸고 다시 켜세요")
        why = ""
        try:
            self.req("POST", PRIVATE + "/position/change_position_mode", {"positionMode": ONE_WAY},
                     limit_key="position_mode_set")
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            why = e.msg
        if self.position_mode() != ONE_WAY:
            raise Refused(f"MEXC 포지션 모드를 단방향(One-way)으로 바꿀 수 없어 거래하지 않습니다. {why}".strip())

    def _leverage_rows(self, symbol: str) -> list:
        data = self.req("GET", PRIVATE + "/position/leverage", {"symbol": mx(symbol)}, limit_key="leverage")
        if not isinstance(data, list):
            raise TransientError(200, None, f"{symbol}: 레버리지 응답이 목록이 아닙니다")
        return data

    @staticmethod
    def _isolated_rows(rows: list) -> dict:
        """position type -> its isolated leverage row (a row without openType counts as isolated; a cross row next to
        it is not the one the orders use)."""
        out = {}
        for r in rows:
            if isinstance(r, dict) and _int(r.get("openType"), ISOLATED) == ISOLATED:
                out.setdefault(_int(r.get("positionType")), r)
        return out

    def _leverage_ok(self, rows: list, lev: int) -> bool:
        got = self._isolated_rows(rows)
        return all(pt in got and _int(got[pt].get("leverage")) == lev for pt in (1, 2))

    def _set_leverage(self, symbol: str, lev: int) -> None:
        """Both position types, isolated (openType 1), then read back: both must show ``lev`` (and isolated where the
        answer says). Already so: nothing is sent."""
        if self._leverage_ok(self._leverage_rows(symbol), lev):
            return
        for pt in (1, 2):
            self.req("POST", PRIVATE + "/position/change_leverage", {"openType": ISOLATED, "leverage": lev,
                                                                     "symbol": mx(symbol), "positionType": pt},
                     limit_key="leverage_set")
        rows = self._leverage_rows(symbol)
        if not self._leverage_ok(rows, lev):
            seen = [(r.get("positionType"), r.get("openType"), r.get("leverage")) for r in rows if isinstance(r, dict)]
            raise TestnetError(400, "LEVERAGE_MISMATCH", f"{symbol}: 격리 {lev}배로 맞추지 못했습니다(읽은 값 {seen})")

    def isolated(self, symbol: str) -> None:
        """MEXC's margin mode is per order (openType 1 on every order); this sets the symbol's isolated leverage for
        both sides (BTC 40x, others 30x) and reads it back. A position open on the symbol: TestnetError -4048 (the
        executor warns and keeps protecting it). Not possible otherwise: Refused (the executor does not start)."""
        sp = self._spec(symbol)
        if _int(sp.get("position_open_type"), 3) not in (1, 3):
            raise Refused(f"MEXC {symbol}은 격리 마진을 받지 않아 거래하지 않습니다(positionOpenType "
                          f"{sp.get('position_open_type')})")
        rows = self._position_rows(symbol)
        if rows:
            ot = _int(rows[0].get("openType"))
            if ot == ISOLATED:
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
            raise Refused(f"MEXC {symbol}을 격리 {lev}배로 맞출 수 없어 거래하지 않습니다: {e.msg}") from e
        self.lev[symbol] = lev

    def leverage(self, symbol: str, lev: int) -> dict:
        """Set the symbol's isolated leverage (both sides) and read it back. Refused (TestnetError) unless the account
        is in one-way mode and the contract is trading: the executor never opens a position otherwise."""
        lev = int(lev)
        sp = self._spec(symbol)
        if sp.get("max_leverage") and lev > sp["max_leverage"]:
            raise TestnetError(400, "LEVERAGE_MAX", f"{symbol}: 레버리지 {lev}배가 최대 {sp['max_leverage']:g}배를 넘습니다")
        if sp.get("status") not in (None, 0, "0"):
            raise TestnetError(400, "NOT_TRADING", f"{symbol}: 계약 상태 {sp.get('status')} (0이 아니면 거래 안 함)")
        if self.position_mode() != ONE_WAY:
            raise TestnetError(400, "NOT_ONE_WAY", "MEXC 포지션 모드가 단방향(One-way)이 아니라 진입하지 않습니다")
        rows = self._position_rows(symbol)
        if rows:
            r = rows[0]
            if _int(r.get("leverage")) == lev and _int(r.get("openType")) == ISOLATED:
                self.lev[symbol] = lev
                return {"symbol": symbol, "leverage": lev, "marginType": "isolated"}
            raise TestnetError(400, "POSITION_OPEN", f"{symbol}: 포지션이 있어 레버리지를 바꾸지 않습니다")
        self._set_leverage(symbol, lev)
        self.lev[symbol] = lev
        return {"symbol": symbol, "leverage": lev, "marginType": "isolated"}

    def account_setup(self, symbols) -> list:
        """(ok, Korean text) lines for preflight, reads only: position mode, each coin's contract state and isolated
        leverage, a bonus balance."""
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
            rows = self._isolated_rows(self._leverage_rows(s))
            levs = "/".join(f"{rows[pt].get('leverage')}" for pt in (1, 2) if pt in rows)
            good = sp.get("status") in (0, "0") and sp.get("api_allowed") is not False
            out.append((good, f"{s}: 계약 상태 {sp.get('status')}, API 허용 {sp.get('api_allowed')}, 1계약 "
                              f"{sp['contract_size']} {sp.get('base_coin') or ''}, 최소 {sp['min_vol']}계약, 가격 단위 "
                              f"{sp['price_unit']}, 지금 레버리지(롱/숏) {levs or '?'}"))
        if self.bonus_seen:
            out.append((False, f"보너스 잔고 {self.bonus_seen}: 실행기 전용 계정에는 보너스가 없어야 합니다"))
        return out

    # ------------------------------------------------------------ orders
    def _order_dict(self, row: dict) -> dict:
        sym = bn(row.get("symbol"))
        vol = _dec(row.get("vol"), "vol")
        deal = _dec(row.get("dealVol") if row.get("dealVol") not in (None, "") else 0, "dealVol")
        state = _int(row.get("state"))
        code = _int(row.get("side"))
        if state == 1:
            status = "NEW"
        elif state == 2:
            status = "PARTIALLY_FILLED" if deal > 0 else "NEW"
        elif state == 3:
            status = "FILLED" if deal >= vol else "CANCELED"
        elif state == 4:
            status = "CANCELED"
        elif state == 5:
            status = "REJECTED"
        else:
            raise TransientError(200, None, f"주문 상태가 이상합니다({row.get('state')!r})")
        cs = Decimal(self._spec(sym)["contract_size"])
        avg = row.get("dealAvgPrice")
        return {"orderId": str(row.get("orderId")), "clientOrderId": row.get("externalOid") or "", "symbol": sym,
                "side": "BUY" if code in (OPEN_LONG, CLOSE_SHORT) else "SELL",
                "type": "MARKET" if _int(row.get("orderType")) in MARKET_TYPES else "LIMIT",
                "origQty": _num(vol * cs), "executedQty": _num(deal * cs),
                "avgPrice": str(avg) if deal > 0 and avg not in (None, "") else "0", "status": status,
                "reduceOnly": code in (CLOSE_SHORT, CLOSE_LONG), "time": _int(row.get("createTime")),
                "updateTime": _int(row.get("updateTime")), "mexcState": state, "mexcSide": code,
                "errorCode": row.get("errorCode"), "positionId": row.get("positionId"), "profit": row.get("profit")}

    def _find(self, symbol: str, order_id=None, ext: Optional[str] = None) -> dict:
        """The order (any state) by its id or externalOid. TestnetError -2013 when MEXC does not have it."""
        if order_id is not None:
            data = self.req("GET", f"{PRIVATE}/order/get/{urllib.parse.quote(str(order_id), safe='')}",
                            limit_key="order_get")
        else:
            data = self.req("GET", f"{PRIVATE}/order/external/{mx(symbol)}/{urllib.parse.quote(str(ext), safe='')}",
                            limit_key="order_external")
        if isinstance(data, list):
            data = next((r for r in data if isinstance(r, dict)), None)
        if not data:
            raise TestnetError(404, NOT_FOUND[0], "Order does not exist.")
        if not isinstance(data, dict) or data.get("orderId") in (None, ""):
            raise TransientError(200, None, f"주문 응답이 이상합니다: {str(data)[:80]!r}")
        if order_id is not None and str(data.get("orderId")) != str(order_id):
            raise TransientError(200, None, f"다른 주문({data.get('orderId')})이 왔습니다")
        if ext is not None and data.get("externalOid") not in (None, "", ext):
            raise TransientError(200, None, f"다른 externalOid({data.get('externalOid')})의 주문이 왔습니다")
        self.order_symbol[str(data["orderId"])] = bn(data.get("symbol")) or symbol
        return data

    def _pos_for_close(self, symbol: str) -> dict:
        """openType and leverage of the position a close order acts on (the last read, else read now)."""
        row = self.pos_rows.get(symbol)
        if row is None:
            rows = self._position_rows(symbol)
            row = rows[0] if rows else {}
        return {"openType": _int(row.get("openType"), ISOLATED) or ISOLATED,
                "leverage": _int(row.get("leverage")) or self.lev.get(symbol)}

    def _open_leverage(self, symbol: str, code: int) -> int:
        lev = self.lev.get(symbol)
        if lev:
            return int(lev)
        rows = self._isolated_rows(self._leverage_rows(symbol))
        lev = _int((rows.get(1 if code == OPEN_LONG else 2) or {}).get("leverage"))
        if lev <= 0:
            raise TestnetError(400, "NO_LEVERAGE", f"{symbol}: 레버리지를 읽지 못해 주문하지 않습니다")
        return lev

    def market(self, symbol: str, side: str, qty: float, reduce_only: bool = False,
               client_id: Optional[str] = None) -> dict:
        """Market order (type 5), then read back until it is final. Opening: side 1 (buy) / 3 (sell), isolated with
        the symbol's leverage. reduce_only: a CLOSE side, 4 (sell: closes a long) / 2 (buy: closes a short), which can
        never open a position. An opening order's rate-limit answer counts as an unknown outcome (looked up by its
        externalOid, never sent again: MEXC is not documented to refuse a repeated externalOid on this endpoint)."""
        vol = self._contracts(symbol, qty)
        self._check_vol(symbol, vol, qty, "주문")
        ext = ext_id(client_id)
        if reduce_only:
            code = CLOSE_LONG if side == "SELL" else CLOSE_SHORT
            p = self._pos_for_close(symbol)
            body = {"symbol": mx(symbol), "vol": self._vol_json(vol), "side": code, "type": self.market_type,
                    "openType": p["openType"], "leverage": p["leverage"], "externalOid": ext}
        else:
            code = OPEN_LONG if side == "BUY" else OPEN_SHORT
            body = {"symbol": mx(symbol), "vol": self._vol_json(vol), "side": code, "type": self.market_type,
                    "openType": ISOLATED, "leverage": self._open_leverage(symbol, code), "externalOid": ext}
        placeholder = {"orderId": None, "clientOrderId": ext, "symbol": symbol, "side": side, "type": "MARKET",
                       "origQty": _num(self._qty(symbol, vol)), "executedQty": "0", "avgPrice": "0", "status": "NEW",
                       "reduceOnly": reduce_only}
        try:
            data = self._create(body)
        except RateLimited as e:
            if reduce_only or e.status == 418:
                raise
            raise TransientError(e.status, e.code, f"진입 주문에 요청 한도 답(결과 모름, 다시 보내지 않음): {e.msg}") from e
        oid = data.get("orderId") if isinstance(data, dict) else data
        if oid in (None, "", 0, "0") or isinstance(oid, (dict, list, bool)):
            raise TransientError(200, None, "주문 번호가 없는 응답(결과 모름)")
        oid = str(oid)
        self.order_symbol[oid] = symbol
        return self._read_back(symbol, oid, {**placeholder, "orderId": oid})

    def _create(self, body: dict):
        """POST the order to order/create (ccxt 4.5.88); MEXC's v1 docs name it order/submit. An HTTP 404 means the
        path does not exist on this host (nothing was routed, so nothing ran): the same body goes once to the other
        path, and the path that answered is kept for later orders."""
        try:
            return self.req("POST", PRIVATE + self.create_path, body, limit_key="order_create")
        except TestnetError as e:
            if e.status != 404 or isinstance(e, TransientError):
                raise
            other = "/order/submit" if self.create_path == "/order/create" else "/order/create"
            data = self.req("POST", PRIVATE + other, body, limit_key="order_create")
            self.create_path = other
            return data

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
        data = self.req("POST", PRIVATE + "/order/cancel", [str(order_id)], limit_key="order_cancel")
        row = next((r for r in (data or []) if isinstance(r, dict)), None) if isinstance(data, list) else None
        ec = _int((row or {}).get("errorCode"), 0)
        if ec:
            raise self._error(ec, str((row or {}).get("errorMsg") or "cancel failed"))
        return {"orderId": str(order_id), "status": "CANCELED"}

    def cancel_all(self, symbol: str) -> dict:
        self.req("POST", PRIVATE + "/order/cancel_all", {"symbol": mx(symbol)}, limit_key="order_cancel_all")
        return {"code": 200, "msg": "ok"}

    def open_orders(self, symbol: str) -> list:
        rows = self._pages(f"{PRIVATE}/order/list/open_orders/{mx(symbol)}", {}, limit_key="open_orders")
        return [self._order_dict(r) for r in rows if bn(r.get("symbol")) == symbol]

    # ------------------------------------------------------------ plan (trigger) orders: the exchange-side stops
    def _plans(self, symbol: Optional[str], states: Optional[str] = None, since_ms: Optional[int] = None) -> list:
        now = self._now()
        p = {"start_time": max(int(since_ms), now - LIST_SPAN_MS) if since_ms is not None else now - LIST_SPAN_MS,
             "end_time": now + 60_000}
        if symbol:
            p["symbol"] = mx(symbol)
        if states:
            p["states"] = states
        rows = self._pages(PRIVATE + "/planorder/list/orders", p, limit_key="plan_list")
        return [r for r in rows if isinstance(r, dict) and (not symbol or r.get("symbol") == mx(symbol))]

    def _algo_dict(self, row: dict) -> dict:
        sym = bn(row.get("symbol"))
        pid = str(row.get("id") if row.get("id") not in (None, "") else row.get("planId"))
        code, tt, state = _int(row.get("side")), _int(row.get("triggerType")), _int(row.get("state"))
        if state not in PLAN_STATUS:
            raise TransientError(200, None, f"조건 주문 상태가 이상합니다({row.get('state')!r})")
        closing = code in (CLOSE_SHORT, CLOSE_LONG)
        protective = (code == CLOSE_LONG and tt == TRIGGER_LE) or (code == CLOSE_SHORT and tt == TRIGGER_GE)
        market = _int(row.get("orderType")) == PLAN_MARKET
        if closing and protective:
            kind = "STOP_MARKET" if market else "STOP"
        elif closing:
            kind = "TAKE_PROFIT_MARKET" if market else "TAKE_PROFIT"
        else:
            kind = "CONDITIONAL"                            # an opening trigger order: never a stop
        status = PLAN_STATUS[state]
        created = _int(row.get("createTime"))
        hours = _int(row.get("executeCycle")) or CYCLE_HOURS[CYCLE_7D]
        refresh = None
        if created:
            refresh = created + min(hours * 3_600_000 - REFRESH_BEFORE_MS, REFRESH_MAX_AGE_MS)
        placed = row.get("orderId")
        cid = row.get("externalOid") or self.cid_by_plan.get(pid, "")
        self.order_symbol[pid] = sym
        return {"algoId": pid, "clientAlgoId": cid, "symbol": sym,
                "side": "BUY" if code in (OPEN_LONG, CLOSE_SHORT) else "SELL", "orderType": kind,
                "algoType": "CONDITIONAL", "triggerPrice": _num(_dec(row.get("triggerPrice"), "triggerPrice")),
                "quantity": _num(self._qty(sym, row.get("vol"))), "closePosition": False, "reduceOnly": closing,
                "workingType": WORKING_TYPE.get(_int(row.get("trend")), str(row.get("trend"))), "priceProtect": False,
                "algoStatus": status, "mexcState": state, "mexcSide": code, "triggerType": tt,
                "actualOrderId": str(placed) if state == 3 and placed not in (None, "", 0, "0") else "",
                "createTime": created, "executeCycle": hours, "refreshAt": refresh, "errorCode": row.get("errorCode")}

    def stop_close(self, symbol: str, side: str, trigger: float, qty: Optional[float] = None,
                   client_id: Optional[str] = None) -> dict:
        """Protective stop resting on MEXC: a close-side plan order (market on trigger, last price). ``qty`` the
        position's size (two can coexist while a stop is moved); None: the position's size now."""
        sp = self._spec(symbol)
        trig = _price_str(trigger, sp["tick_str"])
        if qty is None:
            qty = abs(float(self.position(symbol)["positionAmt"]))
        vol = self._contracts(symbol, qty)
        self._check_vol(symbol, vol, qty, "손절")
        code = CLOSE_LONG if side == "SELL" else CLOSE_SHORT
        p = self._pos_for_close(symbol)
        ext = ext_id(client_id)
        body = {"symbol": mx(symbol), "side": code, "openType": p["openType"], "leverage": p["leverage"],
                "vol": self._vol_json(vol), "triggerPrice": trig,
                "triggerType": TRIGGER_LE if code == CLOSE_LONG else TRIGGER_GE, "executeCycle": CYCLE_7D,
                "orderType": PLAN_MARKET, "trend": TREND_LAST, "externalOid": ext}
        self.pending_plans[ext] = (symbol, code, Decimal(trig), vol, self._now())
        self._trim()
        try:
            data = self.req("POST", PRIVATE + "/planorder/place", body, limit_key="plan_place")
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            raise self._would_trigger(e, symbol, side, float(trig)) from e
        pid = data.get("orderId", data.get("id")) if isinstance(data, dict) else data
        if pid in (None, "", 0, "0") or isinstance(pid, (dict, list, bool)):
            raise TransientError(200, None, "손절 주문 번호가 없는 응답(결과 모름)")
        pid = str(pid)
        self.order_symbol[pid] = symbol
        self.plan_by_cid[ext], self.cid_by_plan[pid] = pid, ext
        return {"algoId": pid, "clientAlgoId": ext, "symbol": symbol, "side": side, "orderType": "STOP_MARKET",
                "algoType": "CONDITIONAL", "triggerPrice": _num(Decimal(trig)),
                "quantity": _num(self._qty(symbol, vol)), "closePosition": False, "reduceOnly": True,
                "workingType": WORKING_TYPE[TREND_LAST], "algoStatus": "NEW"}

    def _trim(self, keep: int = 2000) -> None:
        """The id maps of a process that runs for weeks stay small (the oldest go first)."""
        for d in (self.pending_plans, self.plan_by_cid, self.cid_by_plan, self.order_symbol):
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
            return TestnetError(e.status, WOULD_TRIGGER, f"Order would immediately trigger (MEXC: {e.msg}; 마지막 가격 "
                                                         f"{last:g}, 손절 {trig:g})")
        return e

    def _plan_by_cid(self, ext: str) -> str:
        """A plan order's id from its externalOid: the answer we got, else the list (externalOid when MEXC echoes it,
        else the fingerprint of what we sent: symbol, side, trigger, contracts, created after we sent it)."""
        pid = self.plan_by_cid.get(ext)
        if pid is not None:
            return pid
        fp = self.pending_plans.get(ext)
        rows = self._plans(fp[0] if fp else None, since_ms=(fp[4] - 60_000) if fp else self._now() - RECENT_MS)
        hit = next((r for r in rows if r.get("externalOid") == ext), None)
        if hit is None and fp is not None:
            _, code, trig, vol, sent = fp
            cands = [r for r in rows if _int(r.get("side")) == code
                     and _dec(r.get("triggerPrice"), "triggerPrice") == trig and _dec(r.get("vol"), "vol") == vol
                     and _int(r.get("createTime")) >= sent - MATCH_SLACK_MS
                     and str(r.get("id")) not in self.cid_by_plan]
            hit = min(cands, key=lambda r: _int(r.get("createTime")), default=None)
        if hit is None:
            raise TestnetError(404, NOT_FOUND[0], f"조건 주문 {ext}이 없습니다")
        pid = str(hit.get("id"))
        self.plan_by_cid[ext], self.cid_by_plan[pid] = pid, ext
        self.order_symbol[pid] = bn(hit.get("symbol"))
        return pid

    def algo_order(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        if algo_id is None:
            algo_id = self._plan_by_cid(ext_id(client_id))
        algo_id = str(algo_id)
        sym = self.order_symbol.get(algo_id)
        row = None
        tries = [(sym, "1", None), (sym, None, self._now() - RECENT_MS), (sym, None, None)]
        if sym is not None:
            tries.append((None, None, None))                # a wrong symbol on record: every contract
        for symbol, states, since in tries:                 # the open list first: one small page in the usual case
            row = next((r for r in self._plans(symbol, states=states, since_ms=since) if str(r.get("id")) == algo_id),
                       None)
            if row is not None:
                break
        if row is None:
            raise TestnetError(404, NOT_FOUND[0], f"조건 주문 {algo_id}이 없습니다")
        return self._algo_dict(row)

    def cancel_algo(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        if algo_id is None:
            algo_id = self._plan_by_cid(ext_id(client_id))
        algo_id = str(algo_id)
        sym = self.order_symbol.get(algo_id) or self.algo_order(algo_id=algo_id)["symbol"]
        try:
            self.req("POST", PRIVATE + "/planorder/cancel", [{"symbol": mx(sym), "orderId": algo_id}],
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
        return {"algoId": algo_id, "clientAlgoId": self.cid_by_plan.get(algo_id, ""), "code": "200", "msg": "success"}

    def open_algo_orders(self, symbol: str) -> list:
        return [self._algo_dict(r) for r in self._plans(symbol, states="1") if _int(r.get("state")) == 1]

    def cancel_all_algo(self, symbol: str) -> dict:
        self.req("POST", PRIVATE + "/planorder/cancel_all", {"symbol": mx(symbol)}, limit_key="plan_cancel_all")
        return {"code": 200, "msg": "ok"}

    # ------------------------------------------------------------ positions
    def _position_rows(self, symbol: Optional[str] = None) -> list:
        """Open position rows (holdVol > 0). The answer must be a list: never "flat" from a missing or garbled one."""
        data = self.req("GET", PRIVATE + "/position/open_positions", {"symbol": mx(symbol)} if symbol else None,
                        limit_key="positions")
        if not isinstance(data, list):
            raise TransientError(200, None, f"포지션 응답이 목록이 아닙니다: {str(data)[:80]!r}")
        out = []
        for r in data:
            if not isinstance(r, dict):
                raise TransientError(200, None, "포지션 응답이 이상합니다")
            if symbol and r.get("symbol") != mx(symbol):
                continue
            if not str(r.get("symbol") or "").endswith("_" + SETTLE):
                continue            # not a USDT contract: never traded here (the start gate refuses other assets)
            vol = _dec(r.get("holdVol"), "holdVol")
            if vol == 0 or _int(r.get("state")) == 3:
                continue
            if _int(r.get("positionType")) not in (1, 2):
                raise TransientError(200, None, f"{r.get('symbol')}: 포지션 방향이 이상합니다({r.get('positionType')!r})")
            out.append(r)
        return out

    def _position_dict(self, symbol: str, rows: list) -> dict:
        amt = Decimal(0)
        for r in rows:
            q = self._qty(symbol, r.get("holdVol"))
            amt += q if _int(r.get("positionType")) == 1 else -q
        main = rows[0] if rows else {}
        if rows:
            self.pos_rows[symbol] = main
        else:
            self.pos_rows.pop(symbol, None)
        ot = _int(main.get("openType"))
        return {"symbol": symbol, "positionAmt": _num(amt), "entryPrice": str(main.get("openAvgPrice") or "0"),
                "markPrice": "0", "liquidationPrice": str(main.get("liquidatePrice") or "0"), "unRealizedProfit": "0",
                "leverage": str(main.get("leverage") or ""),
                "marginType": "isolated" if ot == ISOLATED else ("cross" if ot == CROSS else ""),
                "positionId": main.get("positionId"), "hedge": len({_int(r.get("positionType")) for r in rows}) > 1,
                "updateTime": _int(main.get("updateTime"))}

    def position(self, symbol: str) -> dict:
        return self._position_dict(symbol, self._position_rows(symbol))

    def positions(self) -> list:
        by: dict = {}
        for r in self._position_rows(None):
            by.setdefault(bn(r.get("symbol")), []).append(r)
        out = [self._position_dict(s, rs) for s, rs in by.items() if s]
        for s in [s for s in self.pos_rows if s not in by]:
            self.pos_rows.pop(s, None)
        return [p for p in out if float(p["positionAmt"]) != 0]

    # ------------------------------------------------------------ fills, P&L, funding, transfers
    def user_trades(self, symbol: str, start_ms: int, end_ms: int, limit: int = 1000) -> list:
        """Account fills (Binance userTrades shape): price, qty (base units), realizedPnl (see fills_from_deals),
        commission (fee: + paid), commissionAsset, orderId, side, time."""
        deals, seen = [], set()
        lo = int(start_ms)
        while lo <= int(end_ms):
            hi = min(int(end_ms), lo + LIST_SPAN_MS)
            for d in self._pages(PRIVATE + "/order/list/order_deals", {"symbol": mx(symbol), "start_time": lo,
                                                                      "end_time": hi}, limit_key="deals"):
                if not isinstance(d, dict) or d.get("symbol") != mx(symbol) or str(d.get("id")) in seen:
                    continue
                seen.add(str(d.get("id")))
                deals.append(d)
            lo = hi + 1
        return fills_from_deals(deals, self._spec(symbol)["contract_size"], symbol)

    def income(self, symbol: Optional[str], income_type: Optional[str], start_ms: int, end_ms: int,
               limit: int = 1000) -> list:
        """Wallet changes in the Binance income shape (``income``: + received): funding (FUNDING_FEE), transfers in and
        out of the futures account and bonus balance changes (TRANSFER; not trading P&L). With a symbol: its funding
        only."""
        out = []
        lo, hi = int(start_ms), int(end_ms)
        if income_type in (None, "FUNDING_FEE"):
            for r in self._pages(PRIVATE + "/position/funding_records", {"symbol": mx(symbol)} if symbol else {},
                                 time_key="settleTime", since=lo, limit_key="funding"):
                t = _int(r.get("settleTime"))
                if not (lo <= t <= hi) or (symbol and r.get("symbol") != mx(symbol)):
                    continue
                out.append({"symbol": bn(r.get("symbol")), "incomeType": "FUNDING_FEE",
                            "income": _num(_dec(r.get("funding"), "funding")), "asset": SETTLE, "time": t,
                            "tranId": _id60("funding", r.get("id"), r.get("symbol"), t), "info": "FUNDING",
                            "positionId": r.get("positionId")})
        if symbol is None and income_type in (None, "TRANSFER"):
            for r in self._pages(PRIVATE + "/account/transfer_record", {}, time_key="createTime", since=lo,
                                 limit_key="transfers"):
                t = _int(r.get("createTime"))
                if not (lo <= t <= hi) or r.get("state") != "SUCCESS" or r.get("type") not in ("IN", "OUT"):
                    continue
                amount = abs(_dec(r.get("amount"), "amount"))
                out.append({"symbol": "", "incomeType": "TRANSFER",
                            "income": _num(amount if r.get("type") == "IN" else -amount),
                            "asset": r.get("currency") or SETTLE, "time": t,
                            "tranId": _id60("transfer", r.get("id"), r.get("txid")), "info": r.get("type")})
            out += [dict(r) for r in self.bonus_rows if lo <= int(r["time"]) <= hi]
        return sorted(out, key=lambda r: int(r["time"]))


class MexcKeyCheckClient(MexcClient):
    """The key check (reads only): the futures account and the position mode. MEXC reports no key permissions:
    withdrawals off and the IP binding come from the owners' statement ``attested`` (MEXC_LIVE_KEY_CHECKED)."""
    __test__ = False

    def __init__(self, *a, attested: bool = False, **k):
        super().__init__(*a, **k)
        self.attested = attested

    def api_restrictions(self):
        data = self.req("GET", PRIVATE + "/account/assets", limit_key="assets")
        if not isinstance(data, list):
            return None                                     # nothing verified
        return permission_record(self.attested, self.position_mode())


# ---------------------------------------------------------------- keys, allowlist, the executor's clients
def _values(env, names) -> set:
    return {str((env or {}).get(n) or "").strip() for n in names} - {""}


def trading_keys(mode: str, env, paper_env=None) -> tuple[str, str]:
    """The MEXC key pair, or Refused. Mainnet only (no MEXC futures testnet), behind PAPERBOT_LIVE_MAINNET=I_UNDERSTAND.
    Never the paper runner's key, a Binance key or a Bybit key."""
    if mode != MODE_MAINNET:
        raise Refused(f"MEXC에는 선물 테스트넷이 없습니다: \"exchange\": \"mexc\"는 \"mode\": \"mainnet\"만 됩니다(지금 {mode!r})")
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
    return key, secret


def refuse_unless_allowed(mode: str, client) -> None:
    """Mainnet only, and the client must be the MEXC client pointing at an allowed MEXC host."""
    if mode != MODE_MAINNET:
        raise Refused(f"MEXC에는 선물 테스트넷이 없습니다: mode={mode!r}로는 시작하지 않습니다(\"mainnet\"만)")
    host = urllib.parse.urlparse(getattr(client, "base", "") or "").hostname or ""
    if host not in MEXC_HOSTS or type(client) is not MexcClient or tuple(type(client).HOSTS) != MEXC_HOSTS:
        raise Refused(f"주소 {host!r}: MEXC 실행기는 {'·'.join(MEXC_HOSTS)} 외에는 연결하지 않습니다")


def check_executor_keys(mode: str, client, keycheck, env, paper_env) -> None:
    """The executor's key gates for MEXC (Executor.__init__)."""
    key, secret = trading_keys(mode, env, paper_env)
    if (client.key, client.secret) != (key, secret):
        raise Refused("MEXC 실거래 실행기의 키가 MEXC_LIVE_KEY/MEXC_LIVE_SECRET와 다릅니다")
    if not isinstance(keycheck, MexcKeyCheckClient) or (keycheck.key, keycheck.secret) != (key, secret):
        raise Refused("MEXC 실거래는 키 확인(선물 계정 읽기)을 거쳐야 시작합니다")


def clients(mode: str, env, paper_env=None, host: Optional[str] = None, market_type: int = 5):
    """(order client, key-check client) for the mode, keys from the environment."""
    key, secret = trading_keys(mode, env, paper_env)
    base = f"https://{host}" if host else None
    attested = str(env.get(KEY_CHECKED) or "").strip() == KEY_CHECKED_VALUE
    return (MexcClient(key, secret, base=base, market_type=market_type),
            MexcKeyCheckClient(key, secret, base=base, market_type=market_type, attested=attested))


# ---------------------------------------------------------------- drill (mainnet, tiny)
def reconcile(c: MexcClient, symbol: str, stop_price: Optional[float] = None) -> dict:
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


def pace(c: "MexcClient", gap_s: float = DRILL_MIN_GAP_S, sleep=time.sleep, clock=time.monotonic) -> None:
    """The drill's requests: at least ``gap_s`` apart, and no endpoint past half its rate window (MEXC code 510)."""
    orig, last = c.req, [None]

    def paced(*a, **k):
        if last[0] is not None:
            wait = max(gap_s - (clock() - last[0]), c.throttle_s(share=0.5))
            if wait > 0:
                sleep(wait)
        try:
            return orig(*a, **k)
        finally:
            last[0] = clock()
    c.req = paced


@dataclass
class MexcDrill:
    """The MEXC micro drill on the REAL account. ``check()`` reads (time, contracts, account, open orders and stops),
    switches to one-way mode when nothing is open and sets the isolated leverage (BTC 40x, the others 30x): no order.
    ``order_cycle()`` (only behind the explicit confirmation) runs one smallest-size cycle on one coin: market entry,
    found by its externalOid, a close-side stop on MEXC, the stop moved (new first, then the old one cancelled), a
    reduce-only close, flat with no order and no stop left, and the P&L from the fills checked three ways (fill prices,
    MEXC's ``profit``, the wallet change)."""
    client: MexcClient
    symbols: tuple = COINS
    symbol: Optional[str] = None
    side: int = 1
    keycheck: Optional[MexcKeyCheckClient] = None
    stop_frac: float = 0.01
    wait: Callable[[float], None] = time.sleep
    log: list = field(default_factory=list)

    def _step(self, name: str, ok: bool, detail, fatal: bool = True) -> None:
        self.log.append({"step": name, "ok": bool(ok), "detail": detail})
        if not ok and fatal:
            raise AssertionError(f"{name}: {detail}")

    def _until(self, check, tries: int = 10, pause: float = 0.3):
        for _ in range(tries):
            got = check()
            if got:
                return got
            self.wait(pause)
        return check()

    def smallest(self) -> str:
        """The coin whose smallest order MEXC accepts is the cheapest."""
        c = self.client
        return min(self.symbols, key=lambda s: self.drill_qty(c.spec(s), c.price(s)) * c.price(s))

    @staticmethod
    def drill_qty(spec: dict, price: float) -> float:
        """The fewest contracts worth at least DRILL_ORDER_USDT (MEXC refuses orders under MIN_ORDER_USDT)."""
        step = spec["qty_step"]
        need = math.ceil(DRILL_ORDER_USDT / (price * step) - 1e-9) * step if price > 0 else 0.0
        return round(max(spec["min_qty"], need), 12)

    def check(self) -> list:
        c = self.client
        off = c.sync_time()
        self._step("서버 시간", abs(off) < 1000, {"offset_ms": off})
        rows = {}
        for s in self.symbols:
            sp, px = c.spec(s), c.price(s)
            rows[s] = {"contractSize": sp["contract_size"], "minVol": sp["min_vol"], "volUnit": sp["vol_unit"],
                       "priceUnit": sp["price_unit"], "maxVol": sp["max_vol"], "maxLeverage": sp["max_leverage"],
                       "state": sp["status"], "apiAllowed": sp["api_allowed"],
                       "positionOpenType": sp["position_open_type"], "min_order_usd": round(max(sp["min_qty"] * px, MIN_ORDER_USDT), 4)}
        self._step("계약 정보(6개 코인)", all(r["state"] in (0, "0") and _int(r["positionOpenType"], 3) in (1, 3)
                                          for r in rows.values()), rows)
        a = c.account()
        pos = c.positions()
        self._step("선물 계정 읽기", True, {"equity": a["totalMarginBalance"], "wallet": a["totalWalletBalance"],
                                         "unrealized": a["totalUnrealizedProfit"], "bonus": a["bonus"],
                                         "cash": a["cashBalance"], "available": a["availableBalance"],
                                         "positionMargin": a["positionMargin"], "assets": a["assets"],
                                         "positions": [(p["symbol"], p["positionAmt"]) for p in pos]})
        left = {s: (len(c.open_orders(s)), len(c.open_algo_orders(s))) for s in self.symbols}
        self._step("열린 주문·조건 주문(목록 읽기)", True, left)
        c.one_way()
        self._step("포지션 모드 단방향", c.position_mode() == ONE_WAY, {"positionMode": c.position_mode()})
        levs = {}
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
        o = c.market(s, buy, qty, client_id=cid)
        for _ in range(20):
            if o.get("status") in ORDER_FINAL:
                break
            self.wait(0.5)
            o = c.order(s, order_id=o["orderId"])
        self._step(f"시장가 진입 체결(가장 작은 주문, 약 ${DRILL_ORDER_USDT:.0f})", o.get("status") == "FILLED",
                   {"status": o.get("status"), "avg": o.get("avgPrice"), "qty": o.get("executedQty"),
                    "contracts": round(qty / spec["qty_step"]), "orderId": o.get("orderId")})
        found = c.order(s, client_id=cid)
        self._step("진입 주문을 우리 번호(externalOid)로 찾음", found.get("orderId") == o["orderId"],
                   {"externalOid": cid, "orderId": found.get("orderId")})
        entry = float(o["avgPrice"])
        amt = float((self._until(lambda: (lambda p: p if float(p["positionAmt"]) else None)(c.position(s)))
                     or c.position(s))["positionAmt"])
        self._step("포지션 크기(계약 x 계약 크기)", abs(amt - self.side * qty) < spec["qty_step"] / 2,
                   {"positionAmt": amt, "qty": qty})
        a1 = c.account()
        lev = _int(c.position(s).get("leverage")) or 1
        margin = abs(amt) * entry / lev
        eq1 = float(a1["totalMarginBalance"])
        # the daily-loss and drawdown limits read this equity: it must not fall by the position's margin on an entry
        self._step("평가액(equity)에 포지션 증거금이 들어 있음(진입해도 증거금만큼 줄지 않음)",
                   abs(eq1 - w0) < 0.5 * margin,
                   {"equity_before": w0, "equity_open": eq1, "margin": round(margin, 6),
                    "positionMargin": a1["positionMargin"], "available": a1["availableBalance"],
                    "cash": a1["cashBalance"], "unrealized": a1["totalUnrealizedProfit"]})
        stop1 = round_stop(entry * (1 - self.side * self.stop_frac), spec["tick"], self.side)
        st1 = place_stop(c, s, sell, stop1, abs(amt), client_id=ext_id(None))
        stops = live_stops(c, s)
        self._step("손절이 MEXC에 걸림(청산 방향 조건 주문, 마지막 가격, 시장가)",
                   len(stops) == 1 and float(stops[0]["triggerPrice"]) == stop1
                   and stops[0].get("workingType") == "CONTRACT_PRICE" and covers(stops[0], amt),
                   [(x["algoId"], x["triggerPrice"], x["workingType"], x["quantity"], x["executeCycle"])
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
        self._step("손절 옮기기(새 손절 → 확인 → 옛 손절 취소, 빈틈 없음)",
                   mv["result"] == "moved" and seen.get("during") == 2 and len(after) == 1
                   and after[0]["algoId"] == mv["stop"]["algoId"] and float(after[0]["triggerPrice"]) == stop2,
                   {"during": seen.get("during"), "after": [(x["algoId"], x["triggerPrice"]) for x in after]})
        close_cid = ext_id(None)
        x = c.market(s, sell, abs(amt), reduce_only=True, client_id=close_cid)
        for _ in range(20):
            if x.get("status") in ORDER_FINAL:
                break
            self.wait(0.5)
            x = c.order(s, order_id=x["orderId"])
        self._step("줄이기 전용 시장가로 청산", x.get("status") == "FILLED", {"status": x.get("status"),
                                                                      "avg": x.get("avgPrice")})
        cancel_everything(c, s)
        clean = self._until(lambda: float(c.position(s)["positionAmt"]) == 0 and not c.open_orders(s)
                            and not c.open_algo_orders(s))
        self._step("포지션 없음, 주문·조건 주문 없음", clean,
                   {"positionAmt": c.position(s)["positionAmt"], "orders": len(c.open_orders(s)),
                    "plan_orders": len(c.open_algo_orders(s))})
        mine = {str(o["orderId"]), str(x["orderId"])}
        t1 = c.clock_ms() + c.offset_ms

        def pnl():
            fills = [f for f in c.user_trades(s, t0 - 5_000, t1 + 5_000) if str(f["orderId"]) in mine]
            return fills if balanced(self.side, fills, spec["qty_step"]) else None
        fills = self._until(pnl, tries=8, pause=1.0)
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
                      # paid fee per side, % of notional (MEXC API futures notice 2026-06-01: taker 0.08%)
                      "fee_rate_pct": round(100 * fees / notional, 4) if notional else None,
                      "mexc_profit": [f.get("mexcProfit") for f in outs], "check": sorted({str(f.get("realizedCheck"))
                                                                                          for f in outs}),
                      "wallet_change": round(w1 - w0, 6)}
        self._step("체결로 계산한 손익 = 체결 가격 = MEXC profit = 지갑 변화(수수료 포함)", ok, detail)
        return self.log


def specs_text(c: MexcClient, symbols=COINS) -> str:
    lines = []
    for s in symbols:
        sp = c.spec(s)
        px = c.price(s)
        lines.append(f"{s}: 1계약 {sp['contract_size']} {sp.get('base_coin') or ''}, 최소 {sp['min_vol']}계약"
                     f"(지금 약 ${sp['min_qty'] * px:,.4f}), 단위 {sp['vol_unit']}계약, 가격 단위 {sp['price_unit']}, "
                     f"최대 {sp['max_leverage']:g}배, 상태 {sp['status']}, API 허용 {sp['api_allowed']}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "drill", "reconcile", "specs"])
    ap.add_argument("--symbol", default=None, help="drill order coin (default: the cheapest smallest order)")
    ap.add_argument("--side", choices=["long", "short"], default="long")
    ap.add_argument("--host", choices=list(MEXC_HOSTS), default=None)
    ap.add_argument("--market-type", type=int, choices=list(MARKET_TYPES), default=5)
    ap.add_argument("--confirm-order", default="", help=f"{DRILL_CONFIRM}: run the one real order cycle")
    args = ap.parse_args(argv)
    try:      # mainnet keys only: never the paper runner's key, a Binance key or a Bybit key
        c, kc = clients(MODE_MAINNET, os.environ, read_env_file(PAPER_ENV_FILE), host=args.host,
                        market_type=args.market_type)
    except Refused as e:
        print(f"시작하지 않습니다: {e}", file=sys.stderr)
        return 2
    c.sync_time()
    if args.cmd == "specs":
        print(specs_text(c))
        return 0
    if args.cmd == "reconcile":
        print(json.dumps(reconcile(c, args.symbol or "BTCUSDT"), indent=1))
        return 0
    pace(c)
    d = MexcDrill(c, symbol=args.symbol, side=1 if args.side == "long" else -1, keycheck=kc)
    orders = args.cmd == "drill" and args.confirm_order == DRILL_CONFIRM
    ok = True
    try:
        d.check()
        if orders:
            time.sleep(DRILL_PAUSE_S)             # let the reads' rate window empty before the order cycle
            d.order_cycle()
        elif args.cmd == "drill":
            d.log.append({"step": "주문 단계", "ok": True,
                          "detail": f"건너뜀: 진짜 주문 한 번은 --confirm-order {DRILL_CONFIRM} 를 붙일 때만 합니다"})
    except (AssertionError, TestnetError, ProtectionError, Refused) as e:
        d.log.append({"step": "멈춤", "ok": False, "detail": str(e)})
        ok = False
        sym = d.symbol
        if orders and sym:
            try:                              # leave the account flat
                amt = float(c.position(sym)["positionAmt"])
                if amt:
                    c.market(sym, "SELL" if amt > 0 else "BUY", abs(amt), reduce_only=True)
                cancel_everything(c, sym)
            except TestnetError as e2:
                d.log.append({"step": "정리 실패(앱에서 직접 확인하세요)", "ok": False, "detail": str(e2)})
    ok = ok and all(r["ok"] for r in d.log)
    for row in d.log:
        print(("[OK]  " if row["ok"] else "[FAIL]") + f" {row['step']}: {row['detail']}")
    return 0 if ok else 1


if __name__ == "__main__":
    hide_process_memory()
    sys.exit(main())
