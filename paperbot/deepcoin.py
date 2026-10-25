"""DeepCoin USDT perpetual futures (api.deepcoin.com) for the executor: client, host allowlist, keys, key check, drill.
``"exchange": "deepcoin"`` in the executor config uses it (mainnet only: DeepCoin has no testnet); the Binance, Bybit,
MEXC, WOO X Pro and Flipster paths are unchanged. Owners 10-24: "그냥 다른거래소 쓸래" (Flipster's API needs an
application): the third executor, following the paper bot "VWAP 개선판" (docs/deepcoin-ko.md).

    python -m paperbot.deepcoin specs                      # the 6 coins' live contract specs (public, no key needed)
    python -m paperbot.deepcoin check                      # read-only checks + leverage 40/30 isolated (no order)
    python -m paperbot.deepcoin drill --confirm-order REAL_ORDER [--symbol DOGEUSDT] [--side short]   # + one
                                                           # small order cycle on one side and the stop-trigger test
                                                           # (--no-trigger-test skips it); run once per side

Sources (read as data, 2026-10-24): DeepCoin's own API docs, www.deepcoin.com/docs (Access Guide / authentication,
Error Codes, Rate Limit Rules, Changelog, DeepCoinMarket_*, DeepCoinAccount_*, DeepCoinTrade_*): base URL
https://api.deepcoin.com; headers DC-ACCESS-KEY / DC-ACCESS-SIGN = Base64(HMAC-SHA256(secret, timestamp + METHOD +
requestPath (the GET query is part of it) + body)) / DC-ACCESS-TIMESTAMP (ISO UTC with milliseconds,
"2020-12-08T09:08:57.715Z") / DC-ACCESS-PASSPHRASE (chosen by the owners when the key was made); JSON bodies; answers
{code: "0", msg, data}, an order refusal as code "0" with data.sCode / sMsg, auth errors 5010x with HTTP 401; rate
limits per UID (private) and per IP (public), per endpoint, per second and per minute (the numbers below); a key with
trade permission not bound to an IP is deleted after 30 days of inactivity (ours is bound to the server). SWAP
instruments "BTC-USDT-SWAP": ``ctVal`` base units per contract, ``lotSz`` / ``minSz`` in contracts, ``tickSz``,
``lever`` (the maximum), ``state`` live. Sizes are CONTRACTS (base quantity = contracts x ctVal), like WOO X Pro, but not
always whole ones: the live instruments list (10-24) gives ETH and SOL a lotSz of 0.1. Also read: ccxt's deepcoin.py (as
data, not authority: the signature string, productGroup "Swap" on trigger orders, the order refusal codes 24 / 31 /
36 / 44 / 194 / 195 / 199), and unauthenticated GETs of the public market endpoints (10-24, the field shapes the test
fake answers with). There is no testnet.

The client answers in the SAME shapes the executor reads from the Binance client (paperbot/testnet.py), like
paperbot/wooxpro.py, so the executor, the stop protocol (place_stop / move_stop / live_stops / covers) and livepnl run
unchanged.

  Binance client call          DeepCoin (api.deepcoin.com)
  spec(symbol)                 GET  /deepcoin/market/instruments?instType=SWAP (public, all, cached 5 s)
  price / mark                 GET  /deepcoin/market/tickers?instType=SWAP&uly= ``last`` / /deepcoin/market/mark-price
  klines (1m)                  GET  /deepcoin/market/candles bar 1m (the last price's; newest first, ``after`` pages
                               back, <= 1000 rows a request)
  sync_time                    GET  /deepcoin/market/time {ts: ms}; DC-ACCESS-TIMESTAMP is counted on the server clock
  account()                    GET  /deepcoin/account/balances?instType=SWAP  USDT bal (wallet), unrealizedProfit,
                               equity, availBal (the other currencies: the assets list the start gate reads)
  one_way()                    DeepCoin has no account-wide position mode: every order carries posSide long/short and
                               mrgPosition merge, and the executor sees ONE net position per coin. one_way() checks the
                               positions: a coin holding a long and a short at once, or a split position: Refused
  isolated(symbol)             POST /deepcoin/account/set-leverage mgnMode isolated, mrgPosition merge (BTC 40x, others
                               30x), read back with GET /deepcoin/account/leverage-info (again after a pause while it
                               lags); a coin it cannot set never stops the start (leverage() sets it before an entry)
  market(...)                  POST /deepcoin/trade/order ordType market, tdMode isolated, mrgPosition merge, sz in
                               contracts, clOrdId: open = buy/long or sell/short; close (reduce only) = sell/long or
                               buy/short with reduceOnly true; read back with GET /deepcoin/trade/order?ordId=
  order(symbol, id / cid)      GET  /deepcoin/trade/order (ordId, or clOrdId: history first, then pending), then
                               /deepcoin/trade/v2/orders-pending and /deepcoin/trade/orders-history (both carry
                               clOrdId per the docs; the first live drill (10-25) read it EMPTY in the order history:
                               GET order is the look-up that works, the drill notes the lists)
  stop_close(...)              POST /deepcoin/trade/trigger-order productGroup Swap, orderType market, the closing side
                               and posSide (sell/long closes a long, buy/short a short), sz = the position's contracts,
                               triggerPrice, triggerPxType last, mrgPosition merge, tdMode / isCrossMargin of the
                               position; then waited for in the trigger pending list (about 5 s)
  algo_order / open_algo_orders GET /deepcoin/trade/trigger-orders-pending (resting); a stop the list does not show: its
                               row in /deepcoin/trade/trigger-orders-history decides (see "Stops" below)
  cancel_algo / cancel_all_algo POST /deepcoin/trade/cancel-trigger-order {instId, ordId} (each resting one)
  cancel / cancel_all          POST /deepcoin/trade/cancel-order {instId, ordId} (each pending order of the coin)
  open_orders                  GET  /deepcoin/trade/v2/orders-pending
  position / positions         GET  /deepcoin/account/positions?instType=SWAP  pos (contracts) x ctVal, posSide
  user_trades                  GET  /deepcoin/trade/fills (begin / end ms, <= 100 rows: a full page is read again in
                               halves) -> fills; realized P&L = DeepCoin's own ``pnl`` of each closing order (GET
                               /deepcoin/trade/order), shared over its fills by size, checked against the P&L replayed
                               from the fills' own prices (paperbot/mexc.py fills_from_deals)
  income                       GET  /deepcoin/account/bills type 7 (Funding Fee; balChg + received). Bills carry no
                               instrument and the bill types for transfers are not clearly named: no TRANSFER rows
  fee_rate                     GET  /deepcoin/account/trade-fee?instType=SWAP  takerU / makerU (USDT-margined)

Client ids. The executor's ids can be longer than DeepCoin's clOrdId (1-20 letters and digits): ``ext_id`` maps each to
a deterministic clOrdId (an id that already fits is kept, any other becomes "pbh" + 17 hex of its SHA-1), so a look-up
after a restart finds the same id without a local ledger. DeepCoin does not say it refuses a clOrdId used before (Get
Order Info: "only the most recent matched order is returned"), so the client never relies on that: an opening order is
looked up by its clOrdId before it is sent (an id DeepCoin already has is never sent twice, also after a restart), an
opening id this process sent is never sent again at all, and a close is sent again under the same id only once it is
known to be absent (then sized from the position); the executor makes its stop and close ids unique
(UNIQUE_CLIENT_IDS). A look-up by clOrdId reads GET /deepcoin/trade/order, then the pending
list and the order history of that instId. Not found: "not found" only SETTLE_MS (25 s) after this process's last send
of it (the docs warn that REST reads lag a fill), an unknown outcome (TransientError) before.

Trigger orders take NO client id (the Trigger Order request has no clOrdId; cancel-trigger-order: "currently not
supported"). A stop whose answer was lost is found by what was sent: before the send, the trigger orders already
pending on the coin are noted; a look-up then takes the trigger orders in the pending list and the trigger history of
that instId with the same side, posSide, size and trigger price (within half a tick), created from 3 s before the send,
that were not pending before it and that no other id of ours holds. Exactly one (two after a stop sent twice, below):
that stop. More: an unknown outcome, never "not found". None: "not found" only 25 s after the last send. This record
lives in the process; after a restart no stop is looked up by its id: the executor reads the resting stops from the
list (a surplus one is cancelled, Executor._cover); a stop id the process has not seen is looked for on every coin, and
a coin that cannot be read makes the answer unknown, never "not found".

Answers to an order or a stop (POST trade/order, trade/trigger-order). Refused (nothing ran) only on a code of the docs'
Error Codes page (the key, the signature, the timestamp, the IP: answered before anything runs; only the two timestamp
codes 50102 / 50112 are a clock refusal, re-synced and sent again by the executor) or on the request's own sCode. Any
other answer after the send (an undocumented code such as 50013 "System is busy", whatever its message says; 403 / 418;
5xx; a body that is not DeepCoin's shape; a timeout) may come from an order that ran: an unknown outcome
(TransientError), looked up by the clOrdId (a stop: by what was sent), an opening order never sent again. The checks
before an opening order goes out (the instrument read, the look-up of its clOrdId) are tried again for a few seconds
while they fail; still failing: NotSent, a refusal (nothing was sent: the executor drops that entry as refused, never
holds it as an unknown outcome). Words in a message are read on reads only (a rate
word: 429; "order not found": not found); a setting or a cancel keeps its code as it came. set-leverage: refused only on
its sCode or a documented code; an undocumented answer and a read-back that still shows another value after a pause are
TransientError (tried again), never a refusal.

Rate limits and 429. Each request waits for its endpoint's own budget (80 % of the docs' numbers, per second and per
minute) BEFORE its timestamp and signature are made: never sent stale. A read answered 429 is read again after its
Retry-After (at most 3 times); so are the setting and cancel writes. An order never is: an opening order's 429 is an
unknown outcome (looked up by its clOrdId, never sent twice); a close's is looked up by its clOrdId (after the
Retry-After, then every 2 s) and never sent again inside this client; a stop's is looked up by what was sent, and a
stop the first look-up finds in neither list is sent ONCE more (either one may then be it; a surplus reduce-only stop is
cancelled by the executor). Protective work (a stop, a reduce-only close, the look-up of one) has a budget: every wait
inside one call (a Retry-After, the look-ups, the wait for a new stop to be listed, the read-back) shares
PROTECT_WAIT_S (10 s); a wait that does not fit raises RateLimited at once, before anything more is sent, and the
executor's own handling takes over (Executor._protect closes a new position whose stop cannot be placed, a failed move
keeps the old stop, a failed close is tried again).

Stops. A stop is confirmed only from the trigger pending list (stop_close waits about 5 s for it). One that the list
does not show is decided by its trigger-history row only, and only an explicit row decides: triggerTime set and
errorCode 0: fired (TRIGGERED; the order it placed is found by its fills: under the stop's own ordId, else the one
order of the coin with the stop's side and posSide created right after the trigger and no clOrdId of ours); errorCode
not 0: it fired but its order failed (REJECTED: not fired, gone); triggerTime 0 and errorCode 0: ended without firing
(CANCELED. The history page says it holds triggered orders, but also "triggerTime of 0 indicates the order has not been
triggered yet": whether a resting order shows there is not settled, and the drill checks that a resting stop is not in
it). No row anywhere: a stop of ours is UNCONFIRMED (neither live nor fired nor cancelled: place_stop raises
ProtectionError, a move keeps the old stop); someone else's: not found. A missing errorCode or triggerTime is an error,
never "cancelled". A trigger order's kind is its triggerOrderType in the pending list and its ordType in the history.
A readable row that cannot be ours (another coin's, a documented kind we never send such as TPSL, posSide net, an
opening side) is simply not ours. A row that may be ours (its kind, side or posSide missing or not a documented value)
is an error, never "not a stop", wherever it may protect something: the coin holds a position or the row is a stop this
process placed; on a flat coin open_algo_orders lists it as not a stop (``dcUnreadable``), so one garbled row on a coin
without a position never stops the executor's loop; a lost answer's search raises on it only when it was made inside
the send's window.
Why "last" (triggerPxType): the paper engine judges its stops on the last price, the other exchanges' stops trigger on
it (Binance CONTRACT_PRICE, Bybit LastPrice, WOO X Pro price_type 1) and the executor's own ladder reads the last
price's 1m candles; the drill watches the last and the mark price while its test stop fires and says which crossed.

A coin whose instrument row lacks minSz (the smallest order), lever (the maximum leverage) or maxMktSz is never read as
0: it refuses new entries with that reason (leverage() and an opening order; specs, check and the preflight show it)
while the executor starts and its open position is still protected and closed. A missing ctVal, lotSz or tickSz is a
BAD_SPEC error for that coin (a stop and a close need them). DeepCoin states its minimum in contracts (minSz): the spec's
min_notional is 0 (no minimum value is published), its min_qty is minSz x ctVal. A coin whose cached state is not live
(suspend, preopen, settlement: the funding settlement passes in moments) is read again in leverage() before an entry.

What only a live run can confirm (docs/deepcoin-ko.md; the drill checks each): two reduce-only trigger orders resting at
once (the stop protocol needs it for a moment: new stop -> confirmed -> old one cancelled); a stop actually firing and
closing the position (the trigger test lets one fire for real), which price fired it, and whose ordId its fills carry;
that a resting stop is not in the trigger history and how a cancelled one reads there; that productGroup "Swap" is taken
for a USDT perpetual (the instruments list says "SwapU"; the Trigger Order page and ccxt say "Swap"); that a plain market
order fills fully; the real taker fee against the fee endpoint (DeepCoin charges its full fee; the payback app pays back
outside the bot); the fee sign (+ paid) and whether an order's ``pnl`` is before fees (the P&L from the fills against
the fill prices and the wallet change); the server time offset; a just-sent order found by its clOrdId (GET order and
the lists); the leverage and isolated margin on the drill's position; how long a new stop takes to be listed; a
reduce-only market close (every run closes half of its position with one) on each side (one run per side: long, then
--side short).

Safety:
- ``DeepCoinClient`` talks to api.deepcoin.com only (class-level allowlist, https only, checked at construction; the
  executor checks again). Mainnet only.
- Keys: DEEPCOIN_LIVE_KEY / DEEPCOIN_LIVE_SECRET / DEEPCOIN_LIVE_PASSPHRASE behind PAPERBOT_LIVE_MAINNET=I_UNDERSTAND;
  never the paper runner's key, a Binance, Bybit, MEXC, WOO X Pro or Flipster key.
- Key gate: the API does not report a key's permissions. The gate proves the key reads the account; "trade only, no
  withdrawal, server IP bound" is the owners' statement DEEPCOIN_LIVE_KEY_CHECKED=TRADE_ONLY_NO_WITHDRAW_IP_BOUND
  (refused without it), shown as a warning at every start.
- An order that was accepted (it has an ordId) is never reported as not executed, and an order or a stop is reported
  refused only on a documented code or its own sCode; a lost or undocumented answer is looked up by its clOrdId (a
  stop: by what was sent); an opening order is never sent twice; after a 429 a close is never sent again by the client
  and a stop at most once more, each looked up first. A stop is reported cancelled only on an explicit record, and
  confirmed live only from the pending list.
- The drill closes and cancels only what it made, only after its own entry was sent, and cancels a stop only once
  the position reads flat.
- The rate budget is waited out before a request is signed: DC-ACCESS-TIMESTAMP is never stale.
- A position's size, the account equity and the stop list are never read as 0 / flat / empty from a missing or garbled
  field: such an answer is an error. A coin holding a long and a short at once is an error, never netted.
- AI agents never import this module (tests/test_deepcoin.py checks it).
"""

from __future__ import annotations

import argparse
import base64
import contextlib
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
from . import flipster as FL
from . import mexc as MX
from . import wooxpro as WX
from .livepnl import balanced
from .mainnet import (FLAG, FLAG_VALUE, LIVE_KEY_NAMES as BINANCE_LIVE_KEY_NAMES, MODE_MAINNET, PAPER_ENV_FILE,
                      PAPER_KEY_NAMES, TESTNET_KEY_NAMES as BINANCE_TESTNET_KEY_NAMES, Refused, check_permissions,
                      read_env_file)
from .testnet import (BAD_TIMESTAMP, NOT_FOUND, WOULD_TRIGGER, RateLimited, TestnetError, TransientError,
                      UnknownOutcome, covers, hide_process_memory, live_stops, move_stop,
                      place_stop, round_stop, urllib_send)

SETTLE = "USDT"
SWAP = "-SWAP"
DEEPCOIN_BASE = "https://api.deepcoin.com"
DEEPCOIN_HOSTS = ("api.deepcoin.com",)
MKT = "/deepcoin/market"
ACC = "/deepcoin/account"
TRD = "/deepcoin/trade"
ORDER = TRD + "/order"
TRIGGER = TRD + "/trigger-order"
LIVE_KEY_NAMES = ("DEEPCOIN_LIVE_KEY", "DEEPCOIN_LIVE_SECRET")
PASSPHRASE_NAME = "DEEPCOIN_LIVE_PASSPHRASE"          # chosen by the owners when the key was made: sent with every call
KEY_CHECKED = "DEEPCOIN_LIVE_KEY_CHECKED"             # the owners' statement: what the API cannot report
KEY_CHECKED_VALUE = "TRADE_ONLY_NO_WITHDRAW_IP_BOUND"
DRILL_CONFIRM = "REAL_ORDER"
DRILL_ORDER_USDT = 6.0                                # the drill's order: $6 or more, two halves of minSz or more
DRILL_MIN_GAP_S = 0.5                                 # the drill's requests at least this far apart
DRILL_PAUSE_S = 3.0
TRIGGER_GAP = 0.001                                   # the trigger test's stop: 0.1 % from the last price
TRIGGER_WAIT_S = 1200                                 # ... waited for at most 20 minutes
PROFIT_GAP = 0.0015                                   # first the price is waited for 0.15 % past the entry, so the test
PROFIT_WAIT_S = 600                                   # stop rests on the profit side (a lock's place); at most 10 min
FIXED_LEVERAGE = MX.FIXED_LEVERAGE                    # owners 2026-10-17: BTC 40x, the other coins 30x
DEFAULT_LEVERAGE = MX.DEFAULT_LEVERAGE
COINS = MX.COINS
PREFIX = {MODE_MAINNET: "[딥코인 실거래 실행기]"}

OK_CODE = "0"
ISOLATED, CROSS = "isolated", "cross"
MERGE = "merge"
LONG, SHORT = "long", "short"
NET = "net"                                           # a posSide of the docs' trigger history; never one we send
CLOSING = (("sell", LONG), ("buy", SHORT))            # side + posSide that close a position
TRIGGER_PX_TYPE = "last"                              # which price fires our stops (module docstring: why)
WORKING_TYPE = {"last": "CONTRACT_PRICE", "mark": "MARK_PRICE", "index": "INDEX_PRICE"}
PRODUCT_GROUP = "Swap"                                # trigger-order productGroup (Trigger Order page; ccxt): the drill
OUR_KIND = "Conditional"                              # the kind of the trigger orders this client sends
OTHER_TRIGGERS = ("TPSL", "Serial", "Indicator", "Complex", "Tracking", "Line")   # kinds that are never our stop
ORDER_FINAL = ("FILLED", "CANCELED", "REJECTED", "EXPIRED")      # the Binance-shaped statuses this client answers
ORDER_WAITS = (0.1, 0.2, 0.4, 0.8)                    # a market order is read back again after these (s)
KLINE_ROWS = 1000                                     # GET candles: at most 1000 rows for SWAP
KLINE_PAGES = 50
PAGE_ROWS = 100                                       # fills, orders-history, bills, the trigger lists: 100 a page
HISTORY_DEPTH = 24                                    # a full fills page is read again in halves, at most this deep
HISTORY_REQUESTS = 64                                 # ... and with at most this many requests
BILL_PAGES = 40
SETTLE_MS = 25_000                                    # an order sent this long ago is surely in the records
MATCH_BEFORE_MS = 3_000                               # ... and was created at most this long before it was sent
FIND_WINDOW_MS = 7 * 86_400_000                       # a fired stop's order: looked for in the fills of the last week
CHILD_AFTER_MS = 60_000                               # ... created from 2 s before its trigger time to 60 s after
SPEC_CACHE_MS = 5_000
# the Error Codes page: every code there is answered before anything runs (the key, the signature, the timestamp)
TIME_CODES = ("50102", "50112")                       # the request timestamp expired / invalid: refused, not executed
IP_CODES = ("50110",)                                 # "Invalid IP": the key is bound to another IP
AUTH_CODES = ("50101", "50103", "50104", "50105", "50106", "50107", "50108", "50109", "50111", "50113", "50114")
FROZEN_CODES = ("50100",)
REQUEST_CODES = ("50115",)                            # "Invalid request type" (HTTP 405)
DOCUMENTED_CODES = TIME_CODES + IP_CODES + AUTH_CODES + FROZEN_CODES + REQUEST_CODES
KEY_REFUSED = ("AUTH", "IP", "FROZEN")                # the key itself refused: nothing on the account would work
NOT_FOUND_SCODES = ("24", "1033201232")               # OrderNotFound (ccxt), "Order not found" (Cancel Trigger Order)
NO_POSITION_SCODES = ("31",)                          # NotEnoughPositionToClose (ccxt): a close with nothing to close
# words read in the message of an undocumented code: on a read only (a write's answer is never guessed from words)
NOT_FOUND_WORDS = ("notfound", "not found", "notexist", "not exist", "does not exist")
RATE_WORDS = ("too many", "frequen", "rate limit", "ratelimit", "limit exceeded")
PLACE_KEYS = frozenset({"order", "trigger"})          # the POSTs that place an order or a stop
# requests per (second, minute) for each endpoint (the docs' Rate Limit Rules: private per UID, public per IP; GET and
# POST of one path share one budget); the client keeps to RATE_SHARE of each and handles a 429 where it comes
DOC_RATE = {
    "time": (10, 600), "instruments": (10, 600), "tickers": (10, 600), "candles": (50, 600), "mark_price": (10, 600),
    "balances": (10, 300), "positions": (10, 300), "bills": (5, 150), "set_leverage": (5, 150),
    "leverage_info": (10, 300), "trade_fee": (10, 300), "pending": (10, 300), "order": (15, 450), "history": (5, 150),
    "fills": (5, 150), "trigger_pending": (5, 150), "trigger_history": (5, 150), "cancel": (15, 450),
    "trigger": (15, 450), "trigger_cancel": (15, 450)}
DEFAULT_RATE = (5, 150)
RATE_SHARE = 0.8
READ_RETRIES = 3                                      # a read refused for the rate (429): read again after a pause
READ_PAUSE_S = 1.0
RETRY_AFTER_MAX_S = 60.0                              # a longer Retry-After is not waited inside a request
# writes sent again after a 429 without a look-up: the ones that change nothing when they run twice. An order never is
RETRY_WRITES = frozenset({"set_leverage", "cancel", "trigger_cancel"})
PROTECT_WAIT_S = 10.0                                 # protective work: every wait inside one call shares this budget
BUDGET_CODE = "PROTECT_BUDGET"
LOOKUP_PAUSE_S = 2.0                                  # after a 429 on a stop or a close: looked up this often
LIST_WAITS = (0.3, 0.7, 1.0, 1.5, 1.5)               # a new stop must show in the pending list within these (5 s)
LEV_WAITS = (0.5, 1.0, 1.5)                           # a leverage just set, not read back yet: read again after these
NOT_SENT_WAITS = (0.5, 1.0, 2.0)                      # the checks before an entry failed: tried again after these
UNCONFIRMED = "UNCONFIRMED"                           # a stop of ours in neither the list nor the history: not settled
AMBIGUOUS = "AMBIGUOUS_ORDER"                         # several stops fit a lost answer (never "not found")
MISMATCH = "LEVERAGE_MISMATCH"                        # the leverage read back is not the one set (yet)
NOT_SENT = "NOT_SENT"                                 # an opening order not sent: a check before it failed


class RateLimitedUnknown(RateLimited):
    """A stop or a close answered 429 that may still have run, not found by the look-ups the protective budget allowed:
    its outcome stays unknown (looked up again, never "refused")."""


class NotSent(TestnetError):
    """The checks before an opening order is sent (the instrument read, the look-up of its clOrdId) failed on every
    try (NOT_SENT_WAITS): nothing went out. A refusal, neither a TransientError nor a RateLimited: the executor drops
    that entry as refused (entry_refused), never holds it as the unknown outcome of an order that was never sent.
    Never raised once the order may have gone out."""


def definite(e: Exception) -> bool:
    """A refusal that says nothing ran: the request's own sCode, or a code of the docs' Error Codes page."""
    return getattr(e, "dc_scode", None) is not None or getattr(e, "dc_code", None) in DOCUMENTED_CODES


def hosts_for(mode: str) -> tuple:
    return DEEPCOIN_HOSTS                  # one host list: mainnet only


# ---------------------------------------------------------------- numbers and names
def _dec(v, what: str = "value") -> Decimal:
    """A number the decision depends on (a size, a price, the equity): missing or garbled is an error, never 0."""
    if v is None or v == "" or isinstance(v, bool):
        raise TransientError(200, None, f"딥코인 응답에 {what} 값이 없습니다")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError) as e:
        raise TransientError(200, None, f"딥코인 응답의 {what} 값이 이상합니다: {v!r}") from e
    if not d.is_finite():
        raise TransientError(200, None, f"딥코인 응답의 {what} 값이 이상합니다: {v!r}")
    return d


def _soft(v) -> Decimal:
    """A number shown only (a trigger order that is not ours): unreadable -> 0, never an error."""
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return Decimal(0)
    return d if d.is_finite() else Decimal(0)


_f, _num, _int, _price_str, _id60 = MX._f, MX._num, MX._int, MX._price_str, MX._id60

_CID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def ext_id(client_id: Optional[str]) -> str:
    """The clOrdId for an executor client id: 1-20 letters and digits (Place Order). An id that fits is kept; any other
    becomes "pbh" + 17 hex of its SHA-1: deterministic, so a look-up after a lost answer or a restart finds the order.
    None: a fresh id (the drill's)."""
    if client_id is None:
        return "pb" + hashlib.sha1(f"{time.time_ns()}|{os.getpid()}".encode()).hexdigest()[:18]
    if 0 < len(client_id) <= 20 and set(client_id) <= _CID_OK:
        return client_id
    return "pbh" + hashlib.sha1(client_id.encode()).hexdigest()[:17]


def fx(symbol: str) -> str:
    """BTCUSDT -> BTC-USDT-SWAP."""
    if not symbol.endswith(SETTLE) or len(symbol) <= len(SETTLE):
        raise TestnetError(400, "NO_SYMBOL", f"{symbol}: USDT 무기한 이름이 아닙니다")
    return f"{symbol[:-len(SETTLE)]}-{SETTLE}{SWAP}"


def uly(symbol: str) -> str:
    """BTCUSDT -> BTC-USDT (the tickers' index symbol)."""
    return fx(symbol)[:-len(SWAP)]


def bn(inst_id) -> str:
    """BTC-USDT-SWAP -> BTCUSDT; anything that is not a USDT perpetual -> "" (never traded here)."""
    s = str(inst_id or "")
    tail = f"-{SETTLE}{SWAP}"
    return s[:-len(tail)] + SETTLE if s.endswith(tail) and len(s) > len(tail) else ""


def to_ms(v, what: str = "time") -> int:
    """A DeepCoin time (ms as a string; the trigger history's cTime / triggerTime come in seconds in the docs' own
    example) -> ms. 0 stays 0."""
    n = int(_dec(v, what))
    if n > 10 ** 14:
        return n // 1_000
    if n > 10 ** 11 or n == 0:
        return n
    return n * 1000


def iso_ms(ms: int) -> str:
    """DC-ACCESS-TIMESTAMP: ISO 8601 UTC with milliseconds, e.g. 2020-12-08T09:08:57.715Z."""
    ms = int(ms)
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ms // 1000)) + f".{ms % 1000:03d}Z"


def query_string(params: dict) -> str:
    """The GET query exactly as sent and signed (part of requestPath): sorted by name, URL-encoded."""
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


def signature(secret: str, ts: str, method: str, request_path: str, body: str = "") -> str:
    """Base64(HMAC-SHA256(secret, timestamp + METHOD + requestPath + body)) (Access Guide, Signature)."""
    msg = f"{ts}{method.upper()}{request_path}{body or ''}"
    return base64.b64encode(hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()).decode()


def side_of(row: dict) -> tuple:
    """(side, posSide) of an order, a fill or a trigger order, lower case; anything else is an error."""
    side, ps = str(row.get("side") or "").lower(), str(row.get("posSide") or "").lower()
    if side not in ("buy", "sell") or ps not in (LONG, SHORT):
        raise TransientError(200, None, f"주문 방향이 이상합니다(side {row.get('side')!r}, posSide {row.get('posSide')!r})")
    return side, ps


def mx_code(side: str, pos_side: str) -> int:
    """DeepCoin side + posSide -> paperbot/mexc.py's side code (1 open long, 2 close short, 3 open short, 4 close
    long)."""
    return {("buy", LONG): MX.OPEN_LONG, ("buy", SHORT): MX.CLOSE_SHORT, ("sell", SHORT): MX.OPEN_SHORT,
            ("sell", LONG): MX.CLOSE_LONG}[(side, pos_side)]


DC_SIDE = {MX.OPEN_LONG: "buy/long", MX.CLOSE_SHORT: "buy/short", MX.OPEN_SHORT: "sell/short",
           MX.CLOSE_LONG: "sell/long"}


def fills_from_rows(rows: list, ct_val, symbol: str, pnl: dict) -> list:
    """DeepCoin fills (GET /deepcoin/trade/fills) -> Binance userTrades-like fills. The fills say open or close
    themselves (side + posSide) but carry no P&L: a closing fill's realized P&L is DeepCoin's own ``pnl`` of its order
    (``pnl``: ordId -> (the order's pnl, its filled contracts)), shared over the order's fills by size (realizedSource
    "pnl"). It is checked against the P&L replayed from the fills' own prices (paperbot/mexc.py fills_from_deals) when
    the list holds the opening fills too: more apart than 0.01 + 0.02 % of the closed notional marks the order's fills
    ``realizedCheck`` "mismatch" (a sign, a size, or a pnl net of fees: the executor keeps the wallet estimate and
    alerts). Without a pnl (its record not readable yet) the replay stands when it knows the entry ("unchecked"), else
    the fill is "unknown" and "mismatch": never a final 0."""
    deals = []
    for r in rows:
        side, ps = side_of(r)
        oid = str(r.get("ordId") or "")
        if not oid or (r.get("tradeId") in (None, "") and r.get("billId") in (None, "")):
            raise TransientError(200, None, f"{symbol}: 체결에 주문 번호나 체결 번호가 없습니다")
        code = mx_code(side, ps)
        share = None
        if code in (MX.CLOSE_LONG, MX.CLOSE_SHORT) and oid in pnl:
            total, filled = pnl[oid]
            sz = _dec(r.get("fillSz"), "fillSz")
            share = total * sz / filled if filled > 0 else None
        fee = r.get("fee")
        deals.append({"id": f"{r.get('tradeId')}/{r.get('billId')}", "orderId": oid, "vol": r.get("fillSz"),
                      "price": r.get("fillPx"), "side": code, "timestamp": to_ms(r.get("ts"), "ts"),
                      "profit": None if share is None else _num(share), "fee": _dec(fee, "fee"),
                      "feeCurrency": r.get("feeCcy") or SETTLE, "isTaker": str(r.get("execType") or "") == "T"})
    out = MX.fills_from_deals(deals, ct_val, symbol)
    by: dict = {}
    for f in out:
        f["dcSide"] = DC_SIDE.get(f.pop("mexcSide"))
        f["dcPnl"] = f.pop("mexcProfit")
        f.pop("vol", None)
        if f["realizedSource"] != "open":
            by.setdefault(str(f["orderId"]), []).append(f)
    for fs in by.values():
        theirs = None if any(f["dcPnl"] is None for f in fs) else sum(Decimal(f["dcPnl"]) for f in fs)
        known = all(f["realizedSource"] == "replay" for f in fs)
        ours = sum(Decimal(f["realizedPnl"]) for f in fs)
        notional = sum(Decimal(f["closedSize"]) * Decimal(f["price"]) for f in fs)
        for f in fs:
            if theirs is not None:
                f["replayPnl"] = f["realizedPnl"] if known else None
                f["realizedPnl"], f["realizedSource"] = f["dcPnl"], "pnl"
                if known:
                    f["realizedCheck"] = "mismatch" if abs(ours - theirs) > Decimal("0.01") + Decimal("0.0002") * \
                        notional else "ok"
                else:
                    f["realizedCheck"] = "pnl"
            elif known:
                f["realizedCheck"] = "unchecked"
            else:
                f["realizedPnl"], f["realizedSource"], f["realizedCheck"] = "0", "unknown", "mismatch"
    return out


def min_order_text(sp: dict) -> str:
    """The smallest order in words; missing: said plainly (that coin takes no new entry)."""
    if sp.get("problem"):
        return f"없음 → 새 진입 안 함({sp.get('problem')})"
    return f"{sp['min_sz']}계약 = {sp['min_qty']:g}"


def permission_record(attested: bool, account_read: bool) -> dict:
    """The Binance apiRestrictions fields mainnet.check_permissions reads. DeepCoin reports no key permissions: reading
    the account is what this key was seen to do; "trade only, no withdrawal, server IP bound" is the owners'
    statement (``attested``), never assumed."""
    extra = []
    if not attested:
        extra.append(f"딥코인은 키 권한을 API로 알려 주지 않습니다. 키를 '거래(Trade)만, 출금 없음, 서버 IP만'으로 만든 것을 "
                     f"확인한 뒤 /etc/paperbot/executor.env에 {KEY_CHECKED}={KEY_CHECKED_VALUE} 를 넣으세요")
    return {
        "enableReading": bool(account_read),
        "enableWithdrawals": False if attested else None,
        "enableFutures": bool(account_read and attested),
        "ipRestrict": True if attested else None,
        "extraProblems": extra,
        "warnings": [f"딥코인은 키 권한을 API로 알려 주지 않습니다. 확인한 것: 계정 읽기. 거래 권한·출금 없음·서버 IP "
                     f"제한은 두 분이 확인한 내용({KEY_CHECKED})입니다"] if attested else [],
        "attested": attested,
    }


# ---------------------------------------------------------------- client
class DeepCoinClient:
    """Signed REST client for DeepCoin USDT perpetuals, real money only. Answers are translated into the Binance
    client's shapes (see the module docstring)."""
    __test__ = False
    HOSTS: tuple = DEEPCOIN_HOSTS
    DEFAULT_BASE = DEEPCOIN_BASE
    KEY_NAMES = LIVE_KEY_NAMES
    AGENT = "paperbot-deepcoin-live/0.1"
    EXCHANGE = "deepcoin"
    PNL_RECORD = "딥코인 주문 기록의 pnl"
    # a stop bigger than the position is replaced by one of the position's size (the executor's _cover)
    EXACT_STOP_SIZE = True
    # the executor adds a random part to its stop and close ids: DeepCoin may take a clOrdId twice
    UNIQUE_CLIENT_IDS = True

    def __init__(self, api_key: str, api_secret: str, passphrase: str, base: Optional[str] = None, send=None,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                 on_request: Optional[Callable[[dict], None]] = None, sleep: Callable[[float], None] = time.sleep,
                 public_only: bool = False):
        base = (base or self.DEFAULT_BASE).rstrip("/")
        u = urllib.parse.urlparse(base)
        host = u.hostname or ""
        if host not in type(self).HOSTS or u.scheme != "https" or u.path not in ("",) or u.port not in (None, 443):
            raise ValueError(f"refusing {base!r}: {type(self).__name__} only talks to https://{type(self).HOSTS}")
        if not public_only and not (api_key and api_secret and passphrase):
            raise ValueError(f"{self.KEY_NAMES[0]}, {self.KEY_NAMES[1]} and {PASSPHRASE_NAME} are required")
        self.base, self.host, self.key, self.secret, self.passphrase = base, host, api_key, api_secret, passphrase
        self.public_only = public_only
        self.send = send or urllib_send
        self.clock_ms = clock_ms
        self.sleep = sleep
        self.offset_ms = 0
        self.time_source = "local"
        self.on_request = on_request
        self.specs: dict = {}            # BTCUSDT -> spec (live instruments, cached)
        self.spec_problems: dict = {}    # BTCUSDT -> why its instrument row cannot be traded at all (BAD_SPEC)
        self.spec_ms: Optional[int] = None
        self.hits: dict = {}             # rate-limit key -> request times (ms) in the last minute
        self.rate_answers = 0            # 429 answers seen (the drill reports them)
        self.order_symbol: dict = {}     # ordId (orders and stops) -> symbol
        self.sent: dict = {}             # clOrdId -> {"symbol", "first", "last", "reduce_only"} sent by this process
        self.own_oids: dict = {}         # ordId -> symbol of each order this process placed (the order history shows
                                         # clOrdId empty: first live drill 10-25)
        self.stop_intents: dict = {}     # a stop's id key -> what was sent (side, posSide, sz, trigger, times, before)
        self.stop_by_cid: dict = {}      # id key -> stop ordId (answers we got, or found by a look-up)
        self.cid_by_stop: dict = {}
        self.list_delay_ms: dict = {}    # stop ordId -> ms until the pending list showed it (the drill reports it)
        self.pos_rows: dict = {}         # symbol -> the last position row (margin mode for a close or a stop)
        self.lev: dict = {}              # symbol -> leverage set by leverage() / isolated()
        self.lev_problems: dict = {}     # symbol -> why isolated() could not set it (leverage() tries before an entry)
        self.one_side = False            # one_way(): no coin holds a long and a short at once (checked this run)
        self.kline_source = "last"
        self.deadline: Optional[int] = None   # protective work: the clock (ms) every wait inside must end by

    # ------------------------------------------------------------ transport
    def _now(self) -> int:
        return int(self.clock_ms() + self.offset_ms)

    @contextlib.contextmanager
    def _protective(self):
        """A stop or a reduce-only close: every wait inside shares PROTECT_WAIT_S (nested calls share the outer one)."""
        outer = self.deadline is None
        if outer:
            self.deadline = int(self.clock_ms() + PROTECT_WAIT_S * 1000)
        try:
            yield
        finally:
            if outer:
                self.deadline = None

    def _left_s(self) -> float:
        return float("inf") if self.deadline is None else (self.deadline - self.clock_ms()) / 1000.0

    def _wait(self, s: float) -> None:
        """Sleep ``s`` seconds; in protective work only within its budget, else RateLimited (code PROTECT_BUDGET) at
        once, before anything more is sent."""
        if s > self._left_s():
            raise RateLimited(429, BUDGET_CODE, f"손절·청산 주문의 기다림이 {PROTECT_WAIT_S:g}초를 넘어 멈춥니다(요청 한도)",
                              1.0)
        if s > 0:
            self.sleep(s)

    @staticmethod
    def _limits(key: str) -> tuple:
        per_s, per_m = DOC_RATE.get(key, DEFAULT_RATE)
        return ((1_000, max(1, int(per_s * RATE_SHARE))), (60_000, max(1, int(per_m * RATE_SHARE))))

    def _recent(self, key: str, window_ms: int) -> list:
        now = self.clock_ms()
        return [t for t in self.hits.get(key, []) if now - t < window_ms]

    def _pace(self, key: str) -> None:
        """Never past the endpoint's own budget: wait until the oldest request of a full window leaves it. Protective
        work is never held back by this self-imposed budget beyond its one-second window (and only within its
        budget); a 429 the exchange answers is handled where it comes."""
        for window, limit in self._limits(key):
            lst = self._recent(key, window)
            if len(lst) >= limit:
                wait = min((min(lst) + window - self.clock_ms()) / 1000.0, window / 1000.0)
                if self.deadline is not None and (window > 1_000 or wait > self._left_s()):
                    continue
                if wait > 0:
                    self.sleep(wait)
        self.hits[key] = self._recent(key, 60_000) + [self.clock_ms()]

    def throttle_s(self, share: float = 0.8) -> float:
        """Seconds to wait before the next loop: an endpoint window that used ``share`` of its budget waits for its
        oldest request to leave it."""
        now = self.clock_ms()
        wait = 0.0
        for key in list(self.hits):
            for window, limit in self._limits(key):
                recent = self._recent(key, window)
                if len(recent) >= share * limit:
                    wait = max(wait, (min(recent) + window - now) / 1000.0)
        return max(0.0, min(wait, 60.0))

    def req(self, method: str, path: str, params=None, signed: bool = True, limit_key: Optional[str] = None):
        """One request; returns the answer's ``data``. A read (GET) refused for the rate (429) is read again after its
        Retry-After (at most READ_RETRIES times); so is a RETRY_WRITES write. A Retry-After longer than
        RETRY_AFTER_MAX_S (or, in protective work, than the budget left) is not waited here: the RateLimited goes up.
        Any other write is never sent again here."""
        for attempt in range(READ_RETRIES + 1):
            try:
                return self._req_once(method, path, params, signed, limit_key)
            except RateLimited as e:
                again = method == "GET" or (limit_key or "") in RETRY_WRITES
                if not again or e.status != 429 or e.code == BUDGET_CODE or attempt == READ_RETRIES \
                        or float(e.retry_after or 0) > RETRY_AFTER_MAX_S:
                    raise
                self._wait(max(float(e.retry_after or 0), READ_PAUSE_S * (attempt + 1)))
        raise AssertionError("unreachable")

    def _req_once(self, method: str, path: str, params=None, signed: bool = True, limit_key: Optional[str] = None):
        if signed and self.public_only:
            raise TestnetError(400, "NO_KEY", "키 없이 만든 클라이언트라 개인 API를 부르지 않습니다")
        audit = {"method": method, "path": path, "params": dict(params or {})}
        headers = {"User-Agent": self.AGENT, "Accept": "application/json"}
        target, body = path, ""
        if method == "GET":
            q = query_string(params or {})
            target = f"{path}?{q}" if q else path
        else:
            body_obj = {k: v for k, v in (params or {}).items() if v is not None}
            audit["params"] = dict(body_obj)
            body = body_string(body_obj)
            headers["Content-Type"] = "application/json"
        # the budget first (it can wait up to a minute), then the timestamp and the signature: never sent stale
        self._pace(limit_key or path)
        if signed:
            ts = iso_ms(self._now())
            headers.update({"DC-ACCESS-KEY": self.key, "DC-ACCESS-TIMESTAMP": ts,
                            "DC-ACCESS-PASSPHRASE": self.passphrase, "Content-Type": "application/json",
                            "DC-ACCESS-SIGN": signature(self.secret, ts, method, target, body)})
        try:
            res = self.send(method, f"{self.base}{target}", headers, body.encode() if method != "GET" else None)
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
        code = None if code is None else str(code)
        msg = str((data.get("msg") if isinstance(data, dict) else None) or (raw or b"")[:200])
        # an order or a stop: refused only on a documented code or its own sCode; any other answer may have run
        placing = method == "POST" and (limit_key or path) in PLACE_KEYS
        err: Optional[TestnetError] = None
        if status >= 500 or status in (0, 408):
            # a server error: the request may have run (an order is looked up, never resent)
            err = TransientError(status, code, f"server error {status}: {msg}"[:300])
        elif status == 429:
            self.rate_answers += 1
            try:
                after = float(hdr.get("retry-after") or 1.0)
            except ValueError:
                after = 1.0
            err = RateLimited(429, code, f"rate limited: {msg}"[:300], after)
        elif status in (403, 418) and placing:
            # whether a blocked order reached the exchange is not said: looked up, never "nothing ran"
            err = TransientError(status, code, f"HTTP {status} (차단·허용 안 된 IP), 주문 결과 모름: {msg}"[:300])
        elif status in (403, 418):
            # a firewall block or a ban: never retried in the request, the loop waits (the executor's 418 handling)
            err = RateLimited(418, code, f"HTTP {status} (차단·허용 안 된 IP): {msg}"[:300], 300.0)
        elif code is not None and code != OK_CODE:
            err = self._error(code, msg, status, read=method == "GET", placing=placing)
        elif status != 200:
            err = (TransientError if placing else TestnetError)(status, code, msg)
        elif not isinstance(data, dict) or code != OK_CODE:
            err = TransientError(status, None, f"응답이 딥코인 형식(code \"0\")이 아닙니다: {msg}"[:200])
        else:
            d = data.get("data")
            if isinstance(d, dict) and str(d.get("sCode") if d.get("sCode") is not None else "0") not in ("", "0"):
                err = self._s_error(str(d.get("sCode")), str(d.get("sMsg") or ""))
            elif isinstance(d, dict) and isinstance(d.get("errorList"), list) and d["errorList"]:
                e0 = d["errorList"][0] if isinstance(d["errorList"][0], dict) else {}
                err = self._s_error(str(e0.get("errorCode")), str(e0.get("errorMsg") or ""))
        self._audit(audit, status=status, data=data, err=err)
        if err is not None:
            raise err
        return data.get("data")

    def _error(self, code: str, msg: str, status: int, read: bool = True, placing: bool = False) -> TestnetError:
        """A top-level code that is not "0". The Error Codes page's codes (the key, the signature, the timestamp, the
        IP, a frozen key, the request type) are answered before anything runs: refused. Any other code is not
        documented: on an order or a stop (``placing``) it is an unknown outcome (TransientError: looked up by its
        clOrdId, a stop by what was sent; e.g. 50013 "System is busy" after the order ran), never a refusal and never a
        clock refusal sent again. Only a read (GET) reads words in the message (a rate word: 429; "order not found":
        not found); another write keeps the code as it came."""
        text = f"{msg} (딥코인 code {code})"
        low = msg.lower().replace("_", " ")
        if code in TIME_CODES:
            err = TestnetError(400, BAD_TIMESTAMP, text)        # refused, not executed: re-sync and send again
        elif code in IP_CODES:
            err = TestnetError(401, "IP", f"키에 묶인 IP가 이 서버가 아닙니다({text}). 키 설정에서 서버 IP를 확인하세요")
        elif code in AUTH_CODES:
            err = TestnetError(401, "AUTH", f"키·서명·패스프레이즈가 거절됐습니다: {text}")
        elif code in FROZEN_CODES:
            err = TestnetError(400, "FROZEN", f"API 키가 막혀 있습니다: {text}")
        elif code in REQUEST_CODES:
            err = TestnetError(405, code, text)
        elif placing:
            err = TransientError(status, code, f"주문에 문서에 없는 답이 왔습니다(들어갔는지 모름, 찾아봅니다): {text}"[:300])
        elif read and any(w in low for w in RATE_WORDS):
            self.rate_answers += 1
            err = RateLimited(429, code, text, 1.0)
        elif read and "order" in low and any(w.replace(" ", "") in low.replace(" ", "") for w in NOT_FOUND_WORDS):
            err = TestnetError(404, NOT_FOUND[0], text)
        else:
            err = TestnetError(status if status and status != 200 else 400, code, text)
        err.dc_code = code
        return err

    @staticmethod
    def _s_error(scode: str, smsg: str) -> TestnetError:
        """A refusal of the request itself (code "0", data.sCode not 0): nothing ran. Told apart by the code only."""
        text = f"{smsg} (딥코인 sCode {scode})"
        if scode in NOT_FOUND_SCODES:
            err = TestnetError(404, NOT_FOUND[0], text)
        elif scode in NO_POSITION_SCODES:
            err = TestnetError(400, -2022, f"ReduceOnly Order is rejected (딥코인: {text})")
        else:
            err = TestnetError(400, scode, text)
        err.dc_code = err.dc_scode = scode
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

    @staticmethod
    def _rows(data, what: str) -> list:
        """A list answer: it must be a list of objects (never "none" from a missing or garbled one)."""
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise TransientError(200, None, f"{what} 응답이 목록이 아닙니다: {str(data)[:80]!r}")
        return data

    # ------------------------------------------------------------ market data
    def sync_time(self) -> int:
        """The server clock (GET /deepcoin/market/time, ms): DC-ACCESS-TIMESTAMP is counted on it. A refused answer: the
        local clock (chrony); a garbled one is an error."""
        t0 = self.clock_ms()
        try:
            data = self.req("GET", MKT + "/time", signed=False, limit_key="time")
        except (TransientError, RateLimited):
            raise
        except TestnetError:
            self.offset_ms, self.time_source = 0, "local"
            return 0
        t1 = self.clock_ms()
        server = to_ms((data or {}).get("ts") if isinstance(data, dict) else None, "ts")
        self.offset_ms = server - (t0 + t1) // 2
        self.time_source = MKT + "/time"
        return self.offset_ms

    def _load_instruments(self) -> None:
        now = self.clock_ms()
        if self.spec_ms is not None and now - self.spec_ms < SPEC_CACHE_MS:
            return
        rows = self._rows(self.req("GET", MKT + "/instruments", {"instType": "SWAP"}, signed=False,
                                   limit_key="instruments"), "상품 정보")
        self.spec_ms = now
        for row in rows:
            sym = bn(row.get("instId"))
            if not sym or str(row.get("instType") or "SWAP") != "SWAP":
                continue
            if str(row.get("settleCcy") or row.get("quoteCcy") or SETTLE) != SETTLE \
                    or str(row.get("ctType") or "linear") != "linear":
                continue
            try:
                self.specs[sym] = self._spec_row(row)
                self.spec_problems.pop(sym, None)
            except TestnetError as e:                       # a contract with missing or garbled units: never traded
                self.specs.pop(sym, None)
                self.spec_problems[sym] = e.msg

    @staticmethod
    def _spec_row(row: dict) -> dict:
        """The units a stop and a close need (ctVal, lotSz, tickSz) must be there: missing or garbled, the coin cannot
        be used (BAD_SPEC). What only a NEW entry needs (minSz, lever, maxMktSz) is never read as 0: missing or
        garbled, the spec carries ``problem`` and the coin refuses new entries with that reason, while a position on
        it is still protected and closed (the executor starts and runs)."""
        ct, lot, tick = (_dec(row.get(k), k) for k in ("ctVal", "lotSz", "tickSz"))
        if ct <= 0 or lot <= 0 or tick <= 0:
            raise TestnetError(400, "BAD_SPEC", f"{row.get('instId')}: 계약 단위 정보가 이상합니다")
        problems, vals = [], {}
        for k in ("minSz", "lever", "maxMktSz"):
            try:
                v = _dec(row.get(k), k)
                if v <= 0:
                    raise TransientError(200, None, f"딥코인 응답의 {k} 값이 이상합니다: {v}")
                vals[k] = v
            except TestnetError as e:
                problems.append(e.msg)
        mn = vals.get("minSz")
        state = str(row.get("state") or "")
        return {"qty_step": float(ct * lot), "min_qty": float(ct * (mn if mn is not None else lot)), "tick": float(tick),
                "min_notional": 0.0, "problem": "; ".join(problems) or None,
                "max_leverage": float(vals["lever"]) if "lever" in vals else None,
                "status": "Trading" if state == "live" else (state or "?"), "tradable": state == "live",
                "ct_val": _num(ct), "lot_sz": _num(lot), "min_sz": _num(mn) if mn is not None else None,
                "max_mkt_sz": _num(vals["maxMktSz"]) if "maxMktSz" in vals else None, "tick_str": _num(tick),
                "qty_step_str": _num(ct * lot), "base_coin": row.get("baseCcy") or row.get("ctValCcy"),
                "inst_id": row.get("instId")}

    def _no_entries(self, symbol: str) -> None:
        """A coin whose instrument row lacks what a new entry needs takes no new entry (a clear reason, never a 0). The
        list is read again first (at most every 5 s): a value that came back lifts it."""
        if not self._spec(symbol).get("problem"):
            return
        self._load_instruments()
        problem = self._spec(symbol).get("problem")
        if problem:
            raise TestnetError(400, "BAD_SPEC", f"{symbol}: 딥코인 상품 정보에 새 진입에 필요한 값이 없어 새 진입을 하지 "
                                                f"않습니다({problem}). 열린 포지션의 손절·청산은 그대로 합니다")

    def spec(self, symbol: str) -> dict:
        """The contract's live spec (cached): sizes in base units for the executor (qty_step = ctVal x lotSz, min_qty =
        ctVal x minSz, tick = tickSz), the raw contract units. Missing units: TestnetError BAD_SPEC naming the field;
        a missing entry-only value: a spec with ``problem`` (no new entries; specs and check print it)."""
        if symbol not in self.specs:
            self._load_instruments()
        if symbol not in self.specs and symbol in self.spec_problems:
            raise TestnetError(400, "BAD_SPEC", f"{symbol}: 딥코인 상품 정보가 이상해 거래하지 않습니다: "
                                                f"{self.spec_problems[symbol]}")
        if symbol not in self.specs:
            raise TestnetError(400, "NO_SYMBOL", f"{symbol}: 딥코인 USDT 무기한 상품에 없습니다")
        return dict(self.specs[symbol])

    def _spec(self, symbol: str) -> dict:
        return self.specs.get(symbol) or self.spec(symbol)

    def _contracts(self, symbol: str, qty: float) -> Decimal:
        """A base quantity -> contracts on lotSz (whole contracts for most coins, 0.1 for ETH and SOL), floored."""
        sp = self._spec(symbol)
        step = Decimal(sp["ct_val"]) * Decimal(sp["lot_sz"])
        n = (Decimal(repr(float(qty))) / step + Decimal("1e-9")).to_integral_value(rounding=ROUND_FLOOR)
        return n * Decimal(sp["lot_sz"])

    def _base(self, symbol: str, contracts) -> Decimal:
        return _dec(contracts, "sz") * Decimal(self._spec(symbol)["ct_val"])

    def _check_size(self, symbol: str, sz: Decimal, qty: float, what: str, entry: bool) -> None:
        sp = self._spec(symbol)
        if sz <= 0:
            raise TestnetError(400, "QTY_ZERO", f"{symbol}: {what} 수량 {qty}이 최소 단위 {sp['qty_step_str']}보다 "
                                                "작습니다")
        if entry and sp.get("min_sz") and sz < Decimal(sp["min_sz"]):
            raise TestnetError(400, "QTY_MIN", f"{symbol}: {what} {_num(sz)}계약이 최소 {sp['min_sz']}계약보다 작습니다")
        if entry and sp.get("max_mkt_sz") and sz > Decimal(sp["max_mkt_sz"]):
            raise TestnetError(400, "QTY_MAX", f"{symbol}: {what} {_num(sz)}계약이 시장가 최대 {sp['max_mkt_sz']}계약을 "
                                               "넘습니다")

    def ticker(self, symbol: str) -> dict:
        rows = self._rows(self.req("GET", MKT + "/tickers", {"instType": "SWAP", "uly": uly(symbol)}, signed=False,
                                   limit_key="tickers"), "시세")
        row = next((r for r in rows if r.get("instId") == fx(symbol)), None)
        if row is None:
            raise TransientError(200, None, f"{symbol}: 시세가 비어 있습니다")
        return row

    def price(self, symbol: str) -> float:
        """Last traded price: what our stops trigger on (triggerPxType last)."""
        return float(_dec(self.ticker(symbol).get("last"), "last"))

    def mark(self, symbol: str) -> float:
        rows = self._rows(self.req("GET", MKT + "/mark-price", {"instType": "SWAP", "instId": fx(symbol)},
                                   signed=False, limit_key="mark_price"), "마크 가격")
        row = next((r for r in rows if r.get("instId") == fx(symbol)), None)
        if row is None:
            raise TransientError(200, None, f"{symbol}: 마크 가격이 비어 있습니다")
        return float(_dec(row.get("markPx"), "markPx"))

    def klines(self, symbol: str, start_ms: int, end_ms: int) -> list:
        """1m candles of the last price opened in [start_ms, end_ms], the one still forming included: [(open ms, high,
        low, close)], oldest first. GET /deepcoin/market/candles answers newest first, at most 1000 rows; ``after``
        reads back from a time (the live answer 10-24 included the candle AT it): pages go back until the start. A page
        that does not go further back stops the read (never an endless loop)."""
        lo = int(start_ms) - int(start_ms) % 60_000
        end = int(end_ms)
        out = {}
        cursor = end - end % 60_000 + 60_000
        for _ in range(KLINE_PAGES):
            n = int(min(KLINE_ROWS, max(2, (cursor - lo) // 60_000 + 2)))
            rows = self.req("GET", MKT + "/candles", {"instId": fx(symbol), "bar": "1m", "after": cursor, "limit": n},
                            signed=False, limit_key="candles")
            if not isinstance(rows, list):
                raise TransientError(200, None, f"{symbol}: 1분봉 응답이 목록이 아닙니다 {str(rows)[:80]!r}")
            oldest = None
            for r in rows:
                if not isinstance(r, (list, tuple)) or len(r) < 5:
                    raise TransientError(200, None, f"{symbol}: 1분봉 응답의 모양이 다릅니다")
                ms = to_ms(r[0], "candle ts")
                oldest = ms if oldest is None else min(oldest, ms)
                if lo <= ms <= end:
                    out[ms] = (ms, float(_dec(r[2], "high")), float(_dec(r[3], "low")), float(_dec(r[4], "close")))
            if oldest is None or oldest <= lo or len(rows) < n or oldest >= cursor:
                break
            cursor = oldest
        return [out[k] for k in sorted(out)]

    def leverage_brackets(self) -> list:
        """Signal mode needs Binance-like notional brackets: not offered (the executor follows the paper position)."""
        raise TestnetError(400, "NO_BRACKETS", "딥코인은 빠른 진입(signal) 크기 계산용 레버리지 구간을 주지 않습니다")

    # ------------------------------------------------------------ account
    def account(self) -> dict:
        """GET /deepcoin/account/balances?instType=SWAP: the USDT row's bal (wallet), unrealizedProfit, equity (= bal +
        unrealizedProfit), availBal; never $0 from a gap. Other currencies with a balance: the assets list."""
        rows = self._rows(self.req("GET", ACC + "/balances", {"instType": "SWAP"}, limit_key="balances"), "잔고")
        usdt = next((r for r in rows if r.get("ccy") == SETTLE), None)
        if usdt is None:          # never read as $0 (a daily-loss halt would close everything)
            raise TransientError(200, None, "잔고 응답에 USDT 줄이 없습니다")
        wallet, unreal = _dec(usdt.get("bal"), "bal"), _dec(usdt.get("unrealizedProfit"), "unrealizedProfit")
        equity, avail = _dec(usdt.get("equity"), "equity"), _dec(usdt.get("availBal"), "availBal")
        assets = [{"asset": SETTLE, "walletBalance": _num(wallet)}]
        for r in rows:
            if r.get("ccy") not in (None, "", SETTLE) and _f(r.get("bal")) > 0:
                assets.append({"asset": str(r.get("ccy")), "walletBalance": str(r.get("bal"))})
        return {"totalWalletBalance": _num(wallet), "totalUnrealizedProfit": _num(unreal),
                "totalMarginBalance": _num(equity), "availableBalance": _num(avail),
                "frozenBalance": str(usdt.get("frozenBal") or "0"), "assets": assets}

    def fee_rate(self, symbol: Optional[str] = None) -> dict:
        """GET /deepcoin/account/trade-fee?instType=SWAP: the account's rates (takerU / makerU for USDT-margined
        contracts, else taker / maker)."""
        p = {"instType": "SWAP"}
        if symbol:
            p["instId"] = fx(symbol)
        rows = self._rows(self.req("GET", ACC + "/trade-fee", p, limit_key="trade_fee"), "수수료율")
        if not rows:
            raise TransientError(200, None, "수수료율 응답이 비어 있습니다")
        r = rows[0]
        taker = r.get("takerU") if r.get("takerU") not in (None, "") else r.get("taker")
        maker = r.get("makerU") if r.get("makerU") not in (None, "") else r.get("maker")
        return {"taker": float(_dec(taker, "takerU")), "maker": float(_dec(maker, "makerU")), "level": r.get("level")}

    def one_way(self) -> None:
        """The executor's Binance assumption: one net position per coin. DeepCoin has no account-wide mode: each order
        carries posSide and mrgPosition merge (this client's always do). Checked here: no coin holds a long and a short
        at once, and no position is split; otherwise Refused (the executor does not start: clear it in the app)."""
        try:
            self._position_rows(None)
        except TransientError as e:
            if getattr(e, "dc_mixed", False):
                raise Refused(f"딥코인에 한 코인 롱·숏이 같이 있거나 분할(split) 포지션이 있어 거래하지 않습니다: {e.msg}. 앱에서 "
                              "정리한 뒤 다시 켜세요") from e
            raise
        self.one_side = True

    def _lev_info(self, symbol: str) -> Optional[int]:
        """GET /deepcoin/account/leverage-info (isolated, merge): the leverage set for the coin, with or without a
        position."""
        data = self.req("GET", ACC + "/leverage-info", {"instId": fx(symbol), "mgnMode": ISOLATED,
                                                        "mrgPosition": MERGE}, limit_key="leverage_info")
        row = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else data
        if not isinstance(row, dict):
            raise TransientError(200, None, f"{symbol}: 레버리지 응답이 이상합니다: {str(data)[:80]!r}")
        if row.get("instId") not in (None, "", fx(symbol)):
            raise TransientError(200, None, f"{symbol}: 다른 상품의 레버리지가 왔습니다({row.get('instId')})")
        if str(row.get("mgnMode") or ISOLATED) != ISOLATED:
            return None
        return int(_dec(row.get("lever"), "lever"))

    def _set_leverage(self, symbol: str, lev: int) -> None:
        """Isolated ``lev`` (merge), then read back; already so: nothing is sent. The read-back can lag the answer: it
        is read again after LEV_WAITS (3 s). Refused only on a definite answer (the request's own sCode, a documented
        code); an undocumented one may have set it, and the read-back decides. Still another value after the waits:
        TransientError LEVERAGE_MISMATCH (tried again later), never a refusal."""
        if self._lev_info(symbol) == lev:
            return
        answer = None
        try:
            self.req("POST", ACC + "/set-leverage", {"instId": fx(symbol), "lever": str(lev), "mgnMode": ISOLATED,
                                                     "mrgPosition": MERGE}, limit_key="set_leverage")
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            if definite(e):
                raise
            answer = e
        got = self._lev_info(symbol)
        for w in LEV_WAITS:
            if got == lev:
                return
            self._wait(w)
            got = self._lev_info(symbol)
        if got != lev:
            raise TransientError(200, MISMATCH, f"{symbol}: 격리 {lev}배로 맞춘 것을 확인하지 못했습니다(읽은 값 {got}"
                                                + (f", 답 {answer.msg}" if answer is not None else "") + ")")

    def isolated(self, symbol: str) -> None:
        """Isolated margin with the owners' leverage (BTC 40x, others 30x), read back. A position open on the symbol:
        TestnetError -4048 unless it is isolated already (the executor warns and keeps protecting it). The key refused
        (IP, signature, a frozen key): Refused (the executor does not start: nothing would work). Any other failure is
        this coin's only (a refusal of the value, an undocumented answer, a read-back that does not show it yet, the
        endpoint not answering): kept in ``lev_problems`` (check shows it) and never stops the start, so an open
        position elsewhere is still protected; leverage() sets and reads back the paper's leverage before every entry
        on the coin and refuses that entry when it cannot."""
        sp = self._spec(symbol)
        rows = self._position_rows(symbol)
        if rows:
            if str(rows[0].get("mgnMode") or "").lower() == ISOLATED:
                return None
            raise TestnetError(400, -4048, f"{symbol}: 교차(cross) 포지션이 열려 있어 격리로 맞추지 못했습니다")
        lev = int(min(FIXED_LEVERAGE.get(symbol, DEFAULT_LEVERAGE), sp.get("max_leverage") or 10 ** 6))
        try:
            self._set_leverage(symbol, lev)
        except TestnetError as e:
            if e.code in KEY_REFUSED:
                raise Refused(f"딥코인 {symbol}을 격리 {lev}배로 맞출 수 없어 거래하지 않습니다: {e.msg}") from e
            if e.code == BAD_TIMESTAMP:
                raise                                      # the clock: the executor re-syncs and calls again
            self.lev_problems[symbol] = f"격리 {lev}배를 못 맞춤: {e.msg}"
            return None
        self.lev_problems.pop(symbol, None)
        self.lev[symbol] = lev

    def leverage(self, symbol: str, lev: int) -> dict:
        """Set the symbol's isolated leverage and read it back. Refused (TestnetError) unless this process checked the
        positions (one_way) and the contract is live: the executor never opens a position otherwise. A coin that is
        not live in the cached instruments (e.g. "settlement", the funding settlement) is read again first."""
        lev = int(lev)
        sp = self._spec(symbol)
        if not sp.get("tradable"):
            self._load_instruments()                       # at most every SPEC_CACHE_MS
            sp = self._spec(symbol)
        if sp.get("max_leverage") and lev > sp["max_leverage"]:
            raise TestnetError(400, "LEVERAGE_MAX", f"{symbol}: 레버리지 {lev}배가 최대 {sp['max_leverage']:g}배를 넘습니다")
        if not sp.get("tradable"):
            raise TestnetError(400, "NOT_TRADING", f"{symbol}: 상품 상태 {sp.get('status')} (live가 아니면 거래 안 함)")
        self._no_entries(symbol)
        if not self.one_side:
            raise TestnetError(400, "NOT_ONE_WAY", "딥코인 포지션(한 코인 한쪽만)을 확인하지 않아 진입하지 않습니다")
        rows = self._position_rows(symbol)
        if rows:
            r = rows[0]
            if _int(r.get("lever")) == lev and str(r.get("mgnMode") or "").lower() == ISOLATED:
                self.lev[symbol] = lev
                return {"symbol": symbol, "leverage": lev, "marginType": "isolated"}
            raise TestnetError(400, "POSITION_OPEN", f"{symbol}: 포지션이 있어 레버리지를 바꾸지 않습니다")
        self._set_leverage(symbol, lev)
        self.lev_problems.pop(symbol, None)
        self.lev[symbol] = lev
        return {"symbol": symbol, "leverage": lev, "marginType": "isolated"}

    def account_setup(self, symbols) -> list:
        """(ok, Korean text) lines for preflight, reads only: the positions (one side per coin) and each coin's
        instrument row and leverage."""
        out = []
        try:
            self._position_rows(None)
            out.append((True, "포지션: 주문마다 합침(merge) + posSide, 한 코인에 한쪽만(롱·숏 동시 없음)"))
        except TransientError as e:
            out.append((False, f"포지션: {e.msg}"))
        for s in symbols:
            sp = self._spec(s)
            lev = self._lev_info(s)
            problem = self.lev_problems.get(s)
            out.append((bool(sp.get("tradable")) and not sp.get("problem") and not problem,
                        f"{s}: 상태 {sp.get('status')}, 1계약 {sp['ct_val']} {sp.get('base_coin') or ''}, 수량 단위 "
                        f"{sp['lot_sz']}계약, 최소 주문 {min_order_text(sp)}, 가격 단위 {sp['tick_str']}, 최대 "
                        f"{sp['max_leverage'] or 0:g}배, 지금 격리 레버리지 {lev if lev is not None else '?'}"
                        + (f" ({problem}: 진입 직전에 다시 맞추고, 안 되면 그 진입만 하지 않음)" if problem else "")))
        return out

    # ------------------------------------------------------------ order records
    def _order_rows(self, symbol: str, **by) -> list:
        """GET /deepcoin/trade/order by ordId or clOrdId (history first, then pending). Empty: [] (not there, or not
        visible yet: the docs warn of a short delay)."""
        try:
            data = self.req("GET", ORDER, {"instId": fx(symbol), **by}, limit_key="order")
        except TestnetError as e:
            if e.code in NOT_FOUND and not isinstance(e, TransientError):
                return []
            raise
        if data is None:
            return []
        rows = data if isinstance(data, list) else [data]
        return self._rows(rows, "주문")

    def _order_row(self, symbol: str, oid: str) -> Optional[dict]:
        return next((r for r in self._order_rows(symbol, ordId=oid) if str(r.get("ordId")) == oid), None)

    def _pending(self, symbol: Optional[str]) -> list:
        """GET /deepcoin/trade/v2/orders-pending (pages of 100)."""
        out = []
        for index in range(1, 11):
            p = {"index": index, "limit": PAGE_ROWS}
            if symbol:
                p["instId"] = fx(symbol)
            rows = self._rows(self.req("GET", TRD + "/v2/orders-pending", p, limit_key="pending"), "대기 주문")
            for r in rows:
                if r.get("ordId") in (None, ""):
                    raise TransientError(200, None, "대기 주문 응답의 모양이 다릅니다")
                if bn(r.get("instId")) and (not symbol or r.get("instId") == fx(symbol)):
                    self.order_symbol[str(r["ordId"])] = bn(r.get("instId"))
                    out.append(r)
            if len(rows) < PAGE_ROWS:
                break
        return out

    def _history(self, symbol: str, ord_id: Optional[str] = None) -> list:
        """GET /deepcoin/trade/orders-history: the newest 100 orders of the coin (``ord_id``: that order only)."""
        p = {"instType": "SWAP", "instId": fx(symbol), "limit": PAGE_ROWS}
        if ord_id is not None:
            p["ordId"] = str(ord_id)
        return self._rows(self.req("GET", TRD + "/orders-history", p, limit_key="history"), "주문 기록")

    def _find_cid(self, symbol: str, ext: str, lists: bool = True) -> Optional[dict]:
        """The order whose clOrdId is ``ext``: GET /deepcoin/trade/order?clOrdId=, then (``lists``) the pending list and
        the order history of the coin (the docs say both carry clOrdId; the live order history read it empty, 10-25:
        GET order is the look-up that finds it). None: in none of them."""
        row = next((r for r in self._order_rows(symbol, clOrdId=ext) if r.get("clOrdId") == ext), None)
        if row is None and lists:
            row = next((r for r in self._pending(symbol) + self._history(symbol) if r.get("clOrdId") == ext), None)
        if row is not None and row.get("ordId") not in (None, ""):
            self.order_symbol[str(row["ordId"])] = symbol
        return row

    def _order_dict(self, row: dict, symbol: Optional[str] = None) -> dict:
        sym = bn(row.get("instId")) or symbol or ""
        sz = _dec(row.get("sz"), "sz")
        acc = _dec(row.get("accFillSz"), "accFillSz")
        state = str(row.get("state") or "").lower().replace("cancelled", "canceled")
        side, ps = side_of(row)
        if state == "live":
            status = "PARTIALLY_FILLED" if acc > 0 else "NEW"
        elif state == "partially_filled":
            status = "PARTIALLY_FILLED"
        elif state == "filled":
            status = "FILLED"
        elif state == "canceled":
            status = "FILLED" if acc >= sz else "CANCELED"
        else:
            raise TransientError(200, None, f"주문 상태가 이상합니다({row.get('state')!r})")
        avg = row.get("avgPx")
        fee = row.get("fee")
        return {"orderId": str(self._need(row, "ordId", "주문")), "clientOrderId": row.get("clOrdId") or "",
                "symbol": sym, "side": side.upper(), "type": "MARKET" if row.get("ordType") == "market" else
                str(row.get("ordType") or "").upper(), "origQty": _num(self._base(sym, sz)),
                "executedQty": _num(self._base(sym, acc)),
                "avgPrice": _num(_dec(avg, "avgPx")) if acc > 0 and avg not in (None, "") else "0", "status": status,
                "reduceOnly": (side, ps) in CLOSING, "positionSide": ps, "dcState": state,
                "commission": _num(_dec(fee, "fee")) if fee not in (None, "") else "0", "pnl": row.get("pnl"),
                "time": to_ms(row["cTime"]) if row.get("cTime") not in (None, "") else None,
                "updateTime": to_ms(row["uTime"]) if row.get("uTime") not in (None, "") else None,
                "leverage": row.get("lever"), "tdMode": row.get("tdMode")}

    @staticmethod
    def _need(row: dict, key: str, what: str):
        v = row.get(key)
        if v in (None, ""):
            raise TransientError(200, None, f"{what}에 {key} 값이 없습니다")
        return v

    # ------------------------------------------------------------ orders
    def market(self, symbol: str, side: str, qty: float, reduce_only: bool = False,
               client_id: Optional[str] = None) -> dict:
        """Market order, then read back until it is final. Opening: buy/long or sell/short (isolated, merge).
        reduce_only: sell/long (closes a long) or buy/short (a short) with reduceOnly true, in the position's margin
        mode: it can never open or flip a position. An opening order is never sent twice (its clOrdId is looked up
        first; a 429 is an unknown outcome); a reduce-only order is protective work (its waits share
        PROTECT_WAIT_S). Answers (see _error): refused only on a documented code or the order's own sCode; anything
        else that came after the send (an undocumented code, 403, 5xx, a garbled answer, a timeout) is an unknown
        outcome looked up by the clOrdId. A failure before an opening order was sent: NotSent."""
        if side not in ("BUY", "SELL"):
            raise TestnetError(400, "BAD_SIDE", f"주문 방향 {side!r}")
        if not reduce_only:
            return self._market(symbol, side, qty, False, client_id)
        with self._protective():
            return self._market(symbol, side, qty, True, client_id)

    def _before_send(self, symbol: str, ext: str) -> Optional[dict]:
        """An opening id this process never sent: the checks before the send (the instrument read, the look-up of its
        clOrdId: an id DeepCoin already has is read, never sent again), tried again after NOT_SENT_WAITS while they
        fail. Still failing: NotSent, a refusal: nothing was sent (never the unknown outcome of a sent order)."""
        for w in NOT_SENT_WAITS + (None,):
            try:
                self._no_entries(symbol)
                return self._earlier(symbol, ext, False)
            except TransientError as e:
                if w is None:
                    raise NotSent(getattr(e, "status", 0), NOT_SENT, f"진입 주문 {ext}을 보내기 전 확인이 안 돼 보내지 "
                                                                     f"않았습니다: {e.msg}"[:300]) from e
            self._wait(w)
        raise AssertionError("unreachable")

    def _market(self, symbol: str, side: str, qty: float, reduce_only: bool, client_id: Optional[str]) -> dict:
        ext = ext_id(client_id)
        if not reduce_only and ext not in self.sent:       # an opening id this process never sent
            earlier = self._before_send(symbol, ext)
        else:
            if not reduce_only:
                self._no_entries(symbol)
            earlier = self._earlier(symbol, ext, reduce_only)
        if earlier is not None:                            # the same order: read it, never send it again
            return self._read_back(symbol, str(earlier["ordId"]), self._placeholder(symbol, side, qty, reduce_only,
                                                                                     ext), earlier)
        if ext in self.sent and reduce_only:
            # the same close once more (its earlier send found absent past SETTLE_MS): sized from the position now,
            # never past it (a throttled send that ran after all must not close twice)
            qty = self._reduce_left(symbol, side, qty)
        sz = self._contracts(symbol, qty)
        self._check_size(symbol, sz, qty, "주문", entry=not reduce_only)
        lside = side.lower()
        if reduce_only:
            ps = LONG if side == "SELL" else SHORT
            body = {"instId": fx(symbol), "tdMode": self._margin_of(symbol), "side": lside, "posSide": ps,
                    "mrgPosition": MERGE, "ordType": "market", "sz": _num(sz), "reduceOnly": True, "clOrdId": ext}
        else:
            ps = LONG if side == "BUY" else SHORT
            body = {"instId": fx(symbol), "tdMode": ISOLATED, "side": lside, "posSide": ps, "mrgPosition": MERGE,
                    "ordType": "market", "sz": _num(sz), "clOrdId": ext}
        placeholder = self._placeholder(symbol, side, float(self._base(symbol, sz)), reduce_only, ext)
        now = self._now()
        prev = self.sent.get(ext)
        self.sent[ext] = {"symbol": symbol, "first": (prev or {}).get("first", now), "last": now,
                          "reduce_only": reduce_only}
        self._trim()
        try:
            data, found = self._send_order(symbol, ext, body, reduce_only)
        except (TransientError, RateLimited):
            raise                                          # it may have run: looked up by its clOrdId, never refused
        except TestnetError:
            self._unsend(ext, prev)                         # refused (a documented code, its own sCode): nothing ran
            raise
        if found is not None:
            self.own_oids[str(found["ordId"])] = symbol
            return self._read_back(symbol, str(found["ordId"]), placeholder, found)
        oid = data.get("ordId") if isinstance(data, dict) else None
        if oid in (None, "") or isinstance(oid, (dict, list, bool)):
            raise TransientError(200, None, "주문 번호가 없는 응답(결과 모름)")
        oid = str(oid)
        self.order_symbol[oid] = symbol
        self.own_oids[oid] = symbol
        return self._read_back(symbol, oid, {**placeholder, "orderId": oid}, None)

    def _unsend(self, ext: str, prev: Optional[dict]) -> None:
        """A send that was refused before anything ran: the id's record goes back to what it was."""
        if prev is None:
            self.sent.pop(ext, None)
        else:
            self.sent[ext] = prev

    @staticmethod
    def _placeholder(symbol: str, side: str, qty: float, reduce_only: bool, ext: str) -> dict:
        return {"orderId": None, "clientOrderId": ext, "symbol": symbol, "side": side, "type": "MARKET",
                "origQty": _num(Decimal(repr(float(qty)))), "executedQty": "0", "avgPrice": "0", "status": "NEW",
                "reduceOnly": reduce_only}

    def _margin_of(self, symbol: str) -> str:
        """The margin mode of the coin's position (a close and a stop act on it): the last row read, else read now;
        none: isolated (what this executor opens)."""
        row = self.pos_rows.get(symbol)
        if row is None:
            rows = self._position_rows(symbol)
            row = rows[0] if rows else {}
        mode = str(row.get("mgnMode") or ISOLATED).lower()
        return mode if mode in (ISOLATED, CROSS) else ISOLATED

    def _reduce_left(self, symbol: str, side: str, qty: float) -> float:
        """A close sent once more: at most the position now; none to reduce on that side: refused before sending."""
        amt = float(self.position(symbol)["positionAmt"])
        if (side == "SELL" and amt <= 0) or (side == "BUY" and amt >= 0):
            raise TestnetError(400, -2022, f"ReduceOnly Order is rejected ({symbol}: 줄일 포지션이 없어 같은 번호의 "
                                           "청산을 다시 보내지 않습니다)")
        return min(float(qty), abs(amt))

    def _earlier(self, symbol: str, ext: str, reduce_only: bool) -> Optional[dict]:
        """The order an id already placed, or None (send it). An id this process sent is looked up; not found within
        SETTLE_MS of its last send: unknown (TransientError, never sent again now); past it: an opening order is still
        never sent again (unknown), a close may be (None). An opening id this process did not send is looked up on the
        exchange once (a deterministic id sent before a restart is found): found -> that order."""
        mine = self.sent.get(ext)
        if mine is None:
            return self._find_cid(symbol, ext, lists=False) if not reduce_only else None
        row = self._find_cid(symbol, ext)
        if row is not None:
            return row
        age = self._now() - int(mine["last"])
        if age < SETTLE_MS:
            raise TransientError(200, None, f"이 번호({ext})로 {age / 1000:.0f}초 전에 보낸 주문이 아직 안 보입니다. 다시 "
                                            f"보내지 않습니다({SETTLE_MS // 1000}초까지 확인)")
        if not reduce_only:
            raise TransientError(200, None, f"이 번호({ext})로 보낸 진입 주문의 결과를 모릅니다. 다시 보내지 않습니다")
        return None

    def _send_order(self, symbol: str, ext: str, body: dict, reduce_only: bool) -> tuple:
        """POST an order: (answer, None), or (None, row) when a close answered 429 was found by its clOrdId. The docs
        do not say whether an order answered 429 ran: it may have. An opening order's 429 is an unknown outcome
        (TransientError: looked up, never sent twice). A close's is looked up after its Retry-After, then every
        LOOKUP_PAUSE_S, while the protective budget lasts; never sent again here. Not found by then:
        RateLimitedUnknown."""
        try:
            return self.req("POST", ORDER, body, limit_key="order"), None
        except RateLimited as e:
            if e.status != 429 or e.code == BUDGET_CODE:
                raise
            if not reduce_only:
                raise TransientError(e.status, e.code, f"진입 주문에 요청 한도 답(결과 모름, 다시 보내지 않음): {e.msg}") from e
            first = e
        pause = max(float(first.retry_after or 0), READ_PAUSE_S)
        why = "찾는 동안 기다릴 시간이 다 됨"
        while True:
            try:
                self._wait(pause)
                row = self._find_cid(symbol, ext)
            except RateLimited as e:
                why = str(e)[:120]
                break
            except TestnetError as e:                      # a failed read: looked up again while the budget lasts
                why, row = str(e)[:120], None
            if row is not None:
                return None, row
            pause = LOOKUP_PAUSE_S
        raise RateLimitedUnknown(429, first.code, f"주문 {ext}에 요청 한도 답(429): 들어갔는지 아직 모릅니다. 번호로 "
                                                  f"찾습니다({why}): {first.msg}", 1.0)

    def _read_back(self, symbol: str, oid: str, placeholder: dict, row: Optional[dict]) -> dict:
        """The accepted order, read until final (a few short waits; inside a protective call, within its budget). It
        WAS accepted (it has an ordId): a failed or garbled read never escapes as if it had not run; the last state
        seen (or NEW) is returned and the executor settles it from the position."""
        best = {**placeholder, "orderId": oid}
        if row is not None:
            try:
                best = self._order_dict(row, symbol)
            except TestnetError as e:
                best = {**best, "readBack": f"기록을 읽지 못함: {e}"}
            if best.get("status") in ORDER_FINAL and "readBack" not in best:
                return best
        for w in (0.0,) + ORDER_WAITS:
            try:
                self._wait(w)
                got = self._order_row(symbol, oid)
                if got is None:
                    best = {**best, "readBack": "주문 기록이 아직 안 보입니다"}
                    continue
                best = self._order_dict(got, symbol)
            except TestnetError as e:
                return {**best, "readBack": f"읽기 실패: {e}"}
            if best["status"] in ORDER_FINAL:
                break
        return best

    def order(self, symbol: str, order_id=None, client_id: Optional[str] = None) -> dict:
        """An order by its ordId or clOrdId. Not anywhere: TestnetError -2013 (not found), unless this process sent it
        less than SETTLE_MS ago (TransientError: unknown; an accepted order is never reported as not executed)."""
        if order_id is not None:
            oid = str(order_id)
            row = self._order_row(symbol, oid)
            if row is None:
                raise TestnetError(404, NOT_FOUND[0], "Order does not exist.")
            return self._order_dict(row, symbol)
        ext = ext_id(client_id)
        mine = self.sent.get(ext)
        with self._protective() if (mine or {}).get("reduce_only") else contextlib.nullcontext():
            row = self._find_cid(symbol, ext)
        if row is not None:
            return self._order_dict(row, symbol)
        if mine is not None and self._now() - int(mine["last"]) < SETTLE_MS:
            raise TransientError(200, None, f"주문 {ext}이 아직 딥코인 기록에 안 보입니다(보낸 지 "
                                            f"{(self._now() - int(mine['last'])) / 1000:.0f}초)")
        raise TestnetError(404, NOT_FOUND[0], f"주문 {ext}이 딥코인에 없습니다")

    def forget_order(self, ext: str) -> None:
        """Drill only: the order's answer as if it had been lost (the look-up must find it by its clOrdId)."""
        self.sent.pop(ext, None)

    def cancel(self, symbol: str, order_id) -> dict:
        self.req("POST", TRD + "/cancel-order", {"instId": fx(symbol), "ordId": str(order_id)}, limit_key="cancel")
        return {"orderId": str(order_id), "status": "CANCELED"}

    def cancel_all(self, symbol: str) -> dict:
        """Each pending order of the coin cancelled by its ordId (the documented cancel-all takes one margin mode)."""
        for r in self._pending(symbol):
            try:
                self.cancel(symbol, r["ordId"])
            except TestnetError as e:
                if e.code not in NOT_FOUND or isinstance(e, TransientError):
                    raise
        return {"code": 200, "msg": "ok"}

    def open_orders(self, symbol: str) -> list:
        return [self._order_dict(r, symbol) for r in self._pending(symbol)]

    def _trim(self, keep: int = 2000) -> None:
        """The id maps of a process that runs for weeks stay small (the oldest go first)."""
        for d in (self.sent, self.stop_intents, self.stop_by_cid, self.cid_by_stop, self.order_symbol,
                  self.list_delay_ms, self.own_oids):
            while len(d) > keep:
                d.pop(next(iter(d)))

    # ------------------------------------------------------------ trigger orders: the exchange-side stops
    def _triggers(self, symbol: str) -> list:
        """GET /deepcoin/trade/trigger-orders-pending of the coin: every resting trigger order (ours and any other)."""
        rows = self._rows(self.req("GET", TRD + "/trigger-orders-pending", {"instType": "SWAP", "instId": fx(symbol),
                                                                            "limit": PAGE_ROWS},
                                   limit_key="trigger_pending"), "조건 주문")
        out = []
        for r in rows:
            if r.get("instId") not in (None, "", fx(symbol)):
                continue                                   # another coin's row: never part of this coin's answer
            if r.get("ordId") in (None, ""):
                if self._ours(r, True) is False:
                    continue                               # readable and not ours: its id is not needed
                raise TransientError(200, None, "조건 주문 응답에 ordId가 없습니다")
            self.order_symbol[str(r["ordId"])] = symbol
            out.append(r)
        return out

    def _trigger_history(self, symbol: str, oid: Optional[str] = None) -> list:
        p = {"instType": "SWAP", "instId": fx(symbol), "limit": PAGE_ROWS}
        if oid is not None:
            p["ordId"] = str(oid)
        try:
            data = self.req("GET", TRD + "/trigger-orders-history", p, limit_key="trigger_history")
        except TestnetError as e:
            if oid is not None and e.code in NOT_FOUND and not isinstance(e, TransientError):
                return []                                  # an id the history does not know, answered as an error
            raise
        rows = self._rows(data, "조건 주문 기록")
        return [r for r in rows if r.get("instId") in (None, "", fx(symbol))
                and (oid is None or str(r.get("ordId")) == str(oid))]

    @staticmethod
    def _kind(row: dict, pending: bool) -> str:
        """The trigger order's kind as the row says it: triggerOrderType in the pending list, ordType in the history
        (Get Pending Trigger Orders / Get Triggered Order History; the pending list's own ordType is the price type,
        market or limit); "" when missing."""
        k = row.get("triggerOrderType" if pending else "ordType")
        return k if isinstance(k, str) else ""

    @classmethod
    def _ours(cls, row: dict, pending: bool) -> Optional[bool]:
        """Can this trigger row be one of our stops? False: readable and not ours (a documented kind we never send, a
        posSide net, an opening side). True: a closing Conditional (long or short). None: a field it needs is missing
        or not a documented value (the kind, side, posSide), so it may be ours: the caller decides (never "not a
        stop" on a coin it may protect)."""
        kind = cls._kind(row, pending)
        if kind in OTHER_TRIGGERS:
            return False
        side, ps = str(row.get("side") or "").lower(), str(row.get("posSide") or "").lower()
        if kind != OUR_KIND or side not in ("buy", "sell") or ps not in (LONG, SHORT, NET):
            return None
        return ps != NET and (side, ps) in CLOSING

    def _is_stop(self, row: dict, pending: bool) -> bool:
        """A closing trigger order of the kind we send. A row that may be ours but cannot be read: TransientError, never
        "not a stop" (a resting stop read as none would make the executor place more stops or close a protected
        position)."""
        ours = self._ours(row, pending)
        if ours is None:
            raise TransientError(200, None, f"조건 주문 {row.get('ordId')}을 읽을 수 없습니다(종류 {self._kind(row, pending)!r}, "
                                            f"side {row.get('side')!r}, posSide {row.get('posSide')!r})")
        return ours

    def _algo_dict(self, row: dict, symbol: str, status: str = "NEW", actual: str = "") -> dict:
        sid = str(self._need(row, "ordId", "조건 주문"))
        pending = status == "NEW"                          # a pending-list row; the others are history rows
        stop = self._is_stop(row, pending)
        trig = row.get("triggerPx")
        if status == "NEW" and stop:                       # a resting stop's level and size are never 0 from a gap
            if _dec(trig, "triggerPx") <= 0 or _dec(row.get("sz"), "sz") <= 0:
                raise TransientError(200, None, f"조건 주문 {sid}의 발동 가격이나 수량이 이상합니다({trig!r}, "
                                                f"{row.get('sz')!r})")
            trig, qty = _num(_dec(trig, "triggerPx")), _num(self._base(symbol, row.get("sz")))
        elif stop:
            qty = _num(self._base(symbol, row.get("sz"))) if row.get("sz") not in (None, "") else "0"
            trig = _num(_dec(trig, "triggerPx")) if trig not in (None, "") else "0"
        else:                                              # not ours: shown as it reads, never an error
            qty, trig = _num(_soft(row.get("sz")) * Decimal(self._spec(symbol)["ct_val"])), _num(_soft(trig))
        side = str(row.get("side") or "").upper()
        self.order_symbol[sid] = symbol
        made = row.get("cTime")
        return {"algoId": sid, "clientAlgoId": self.cid_by_stop.get(sid, ""), "symbol": symbol, "side": side,
                "positionSide": str(row.get("posSide") or ""), "orderType": "STOP_MARKET" if stop else "CONDITIONAL",
                "algoType": "CONDITIONAL", "triggerPrice": trig, "quantity": qty,
                "closePosition": False, "reduceOnly": stop, "workingType": WORKING_TYPE.get(
                    str(row.get("triggerPxType") or ""), str(row.get("triggerPxType") or "")),
                "priceProtect": False, "algoStatus": status, "dcKind": self._kind(row, pending),
                "actualOrderId": actual,
                "createTime": to_ms(made) if made not in (None, "") and (stop or _soft(made) > 0) else None}

    def stop_close(self, symbol: str, side: str, trigger: float, qty: Optional[float] = None,
                   client_id: Optional[str] = None) -> dict:
        """Protective stop resting on DeepCoin: a trigger order on the closing side and posSide (sell/long closes a
        long, buy/short a short), market, triggerPxType last, ``sz`` the position's contracts (two can coexist while a
        stop is moved; None: the position's size now). A level the last price is already past is refused before
        anything is sent (the executor's -2021: close at market). Protective work: every wait inside shares
        PROTECT_WAIT_S (then RateLimited; RateLimitedUnknown when the stop may have gone in). After the send the stop is
        waited for in the pending list (LIST_WAITS, within the budget): place_stop confirms a stop from the list only.
        Refused only on a documented code or the stop's own sCode; any other answer after the send (an undocumented
        code, 403, 5xx, a timeout) is an unknown outcome, looked up by what was sent."""
        with self._protective():
            return self._stop_close(symbol, side, trigger, qty, client_id)

    def _stop_close(self, symbol: str, side: str, trigger: float, qty: Optional[float],
                    client_id: Optional[str]) -> dict:
        sp = self._spec(symbol)
        trig = _price_str(trigger, sp["tick_str"])
        if qty is None:
            qty = abs(float(self.position(symbol)["positionAmt"]))
        sz = self._contracts(symbol, qty)
        self._check_size(symbol, sz, qty, "손절", entry=False)
        key = ext_id(client_id)
        earlier = self._stop_earlier(key)
        if earlier is not None:                            # this id placed a stop: never a second copy
            return self.algo_order(algo_id=earlier)
        last = self.price(symbol)
        if (side == "SELL" and last <= float(trig)) or (side == "BUY" and last >= float(trig)):
            raise TestnetError(400, WOULD_TRIGGER, f"Order would immediately trigger (딥코인: 마지막 가격 {last:g}, "
                                                   f"손절 {trig})")
        mode = self._margin_of(symbol)
        ps = LONG if side == "SELL" else SHORT
        body = {"instId": fx(symbol), "productGroup": PRODUCT_GROUP, "sz": _num(sz), "side": side.lower(),
                "posSide": ps, "isCrossMargin": "1" if mode == CROSS else "0", "orderType": "market",
                "triggerPrice": trig, "triggerPxType": TRIGGER_PX_TYPE, "mrgPosition": MERGE, "tdMode": mode}
        # what rests before this send (a look-up never takes an older identical stop for this one), then the record
        before = sorted(str(r["ordId"]) for r in self._triggers(symbol))
        now = self._now()
        self.stop_intents[key] = {"symbol": symbol, "side": side.lower(), "posSide": ps, "sz": _num(sz), "trig": trig,
                                  "first": now, "last": now, "before": before, "sends": 1}
        self._trim()
        try:
            data, found = self._send_stop(key, body)
        except (TransientError, RateLimited):
            raise                                          # it may be in: looked up by what was sent
        except TestnetError as e:                          # refused (a documented code, its own sCode): nothing placed
            self.stop_intents.pop(key, None)
            raise self._would_trigger(e, symbol, side, float(trig)) from e
        if found is not None:                              # a 429 that still ran: that stop, never a second copy
            self._await_listed(symbol, found)
            return self.algo_order(algo_id=found)
        sid = data.get("ordId") if isinstance(data, dict) else None
        if sid in (None, "") or isinstance(sid, (dict, list, bool)):
            raise TransientError(200, None, "손절 주문 번호가 없는 응답(결과 모름)")
        sid = str(sid)
        self._bind_stop(key, sid, symbol)
        self._await_listed(symbol, sid)
        return {"algoId": sid, "clientAlgoId": key, "symbol": symbol, "side": side, "positionSide": ps,
                "orderType": "STOP_MARKET", "algoType": "CONDITIONAL", "triggerPrice": _num(Decimal(trig)),
                "quantity": _num(self._base(symbol, sz)), "closePosition": False, "reduceOnly": True,
                "workingType": WORKING_TYPE[TRIGGER_PX_TYPE], "algoStatus": "NEW"}

    def _bind_stop(self, key: str, sid: str, symbol: str) -> None:
        self.stop_by_cid[key], self.cid_by_stop[sid] = sid, key
        self.order_symbol[sid] = symbol

    def forget_stop(self, key: str) -> None:
        """Drill only: the stop's answer as if it had been lost (the look-up must find it by what was sent)."""
        sid = self.stop_by_cid.pop(key, None)
        if sid is not None:
            self.cid_by_stop.pop(sid, None)

    def _send_stop(self, key: str, body: dict) -> tuple:
        """POST a stop: (answer, None), or (None, ordId) when it was answered 429 and a look-up found it. The first
        look-up (after the Retry-After) that finds it in neither list sends it ONCE more (a second reduce-only stop
        cannot open anything and the executor cancels a surplus one, while a stop that never goes in would close a new
        position); then the look-ups go on (either send may be the one that rests) while the budget lasts. Not found
        by then: RateLimitedUnknown. Any other error: as it came (a 403 / 418 after the send is a TransientError)."""
        try:
            return self.req("POST", TRIGGER, body, limit_key="trigger"), None
        except RateLimited as e:
            if e.status != 429 or e.code == BUDGET_CODE:
                raise
            first = e
        pause = max(float(first.retry_after or 0), READ_PAUSE_S)
        why = "찾는 동안 기다릴 시간이 다 됨"
        again = True
        while True:
            hits = None
            try:
                self._wait(pause)
                hits = self._search_stop(key)
            except RateLimited as e:
                why = str(e)[:120]
                break
            except TestnetError as e:
                why = str(e)[:120]
            intent = self.stop_intents.get(key) or {}
            if hits and len(hits) > int(intent.get("sends", 1)):
                raise UnknownOutcome(409, AMBIGUOUS, f"손절 {key}: 요청 한도 답 뒤에 맞는 조건 주문이 {len(hits)}개라 어느 "
                                                     "것인지 모릅니다")
            if hits:
                sid = str(hits[0]["ordId"])
                self._bind_stop(key, sid, intent["symbol"])
                return None, sid
            pause = LOOKUP_PAUSE_S
            if not again or hits is None:
                continue
            again = False                                  # in neither list: sent once more (same intent)
            intent["sends"], intent["last"] = 2, self._now()
            try:
                return self.req("POST", TRIGGER, body, limit_key="trigger"), None
            except RateLimited as e:
                if e.status != 429 or e.code == BUDGET_CODE:
                    why = str(e)[:120]
                    break
                pause = max(float(e.retry_after or 0), READ_PAUSE_S)
            except TestnetError as e:                      # refused or unanswered: either send may be the one
                why = str(e)[:120]
        raise RateLimitedUnknown(429, first.code, f"손절 {key}에 요청 한도 답(429): 들어갔는지 아직 모릅니다. 보낸 내용으로 "
                                                  f"찾습니다({why}): {first.msg}", 1.0)

    def _search_stop(self, key: str) -> list:
        """Trigger orders that fit a stop whose answer was lost (module docstring): same side, posSide, size and
        trigger (half a tick), created from MATCH_BEFORE_MS before the send, not resting before it, held by no other id
        of ours; the pending list first, then the trigger history. A row that is readable and cannot be it (made outside
        the send's window, a kind we never send, a posSide net, another side) is simply not it; one that may be it but
        cannot be read (its kind, side or posSide missing or undocumented; its size or level garbled): TransientError,
        never skipped as "not it"."""
        intent = self.stop_intents.get(key)
        if intent is None:
            return []
        sym = intent["symbol"]
        half_tick = Decimal(self._spec(sym)["tick_str"]) / 2
        found: dict = {}
        rows = [(r, True) for r in self._triggers(sym)] + [(r, False) for r in self._trigger_history(sym)]
        for r, pending in rows:
            sid = str(r.get("ordId") or "")
            if not sid or sid in found or sid in intent["before"]:
                continue
            made = _soft(r.get("cTime"))
            if made > 0 and not intent["first"] - MATCH_BEFORE_MS <= to_ms(made) <= intent["last"] + SETTLE_MS:
                continue                                   # made outside the send's window: not it, whatever it says
            ours = self._ours(r, pending)
            if ours is False or (ours and side_of(r) != (intent["side"], intent["posSide"])):
                continue
            if ours is None:
                raise TransientError(200, None, f"손절 {key}: 조건 주문 {sid}이 이 손절일 수 있는데 읽을 수 없습니다(종류 "
                                                f"{self._kind(r, pending)!r}, side {r.get('side')!r}, posSide "
                                                f"{r.get('posSide')!r})")
            if _dec(r.get("sz"), "sz") != Decimal(intent["sz"]) or \
                    abs(_dec(r.get("triggerPx"), "triggerPx") - Decimal(intent["trig"])) > half_tick:
                continue
            other = self.cid_by_stop.get(sid)
            if other is not None and other != key:
                continue
            found[sid] = r
        return list(found.values())

    def _stop_earlier(self, key: str) -> Optional[str]:
        """The stop an id already placed (its ordId), or None (send it). A stop sent by this process whose answer was
        lost is searched for (_search_stop); not found within SETTLE_MS of its last send: unknown (TransientError,
        never a second copy now)."""
        sid = self.stop_by_cid.get(key)
        if sid is not None:
            return sid
        if key not in self.stop_intents:
            return None
        return self._resolve_stop(key, settled_none=True)

    def _resolve_stop(self, key: str, settled_none: bool = False) -> Optional[str]:
        sid = self.stop_by_cid.get(key)
        if sid is not None:
            return sid
        intent = self.stop_intents.get(key)
        if intent is None:
            raise TestnetError(404, NOT_FOUND[0], f"조건 주문 {key}이 없습니다")
        hits = self._search_stop(key)
        if hits and len(hits) <= int(intent.get("sends", 1)):
            sid = str(hits[0]["ordId"])
            self._bind_stop(key, sid, intent["symbol"])
            return sid
        if hits:
            raise TestnetError(409, AMBIGUOUS, f"손절 {key}: 답을 잃은 손절에 맞는 조건 주문이 {len(hits)}개라 어느 것인지 "
                                               "모릅니다")
        age = self._now() - int(intent["last"])
        if age < SETTLE_MS:
            raise TransientError(200, None, f"손절 {key}: 아직 조건 주문 목록·기록에 안 보입니다(보낸 지 {age / 1000:.0f}초, "
                                            f"{SETTLE_MS // 1000}초까지 기다림)")
        if settled_none:
            return None
        raise TestnetError(404, NOT_FOUND[0], f"손절 {key}이 딥코인에 없습니다({SETTLE_MS // 1000}초 지나도 없음)")

    def _await_listed(self, symbol: str, sid: str) -> None:
        """A stop just placed: waited for (LIST_WAITS, about 5 s, within the protective budget) until the pending list
        shows it, or its history row says it ended (fired at once). Best effort, never an error here: place_stop reads
        it next, and a stop the list does not show is not confirmed."""
        t0 = self.clock_ms()
        for w in (0.0,) + LIST_WAITS:
            try:
                self._wait(w)
                if any(str(r.get("ordId")) == sid for r in self._triggers(symbol)):
                    self.list_delay_ms[sid] = self.clock_ms() - t0
                    return
                if self._trigger_history(symbol, sid):
                    return
            except TestnetError:
                return

    def _would_trigger(self, e: TestnetError, symbol: str, side: str, trig: float) -> TestnetError:
        """A refused stop while the last price is already past it: the executor's "would immediately trigger" (-2021:
        close at market). Anything else stays as it was."""
        if e.code == WOULD_TRIGGER or isinstance(e, RateLimited):
            return e
        try:
            last = self.price(symbol)
        except TestnetError:
            return e
        if (side == "SELL" and last <= trig) or (side == "BUY" and last >= trig):
            return TestnetError(e.status, WOULD_TRIGGER, f"Order would immediately trigger (딥코인: {e.msg}; 마지막 "
                                                         f"가격 {last:g}, 손절 {trig:g})")
        return e

    def _finished_stop(self, sid: str, symbol: str) -> Optional[dict]:
        """A stop the pending list does not show: its trigger-history row decides, and only an explicit one (module
        docstring): fired (TRIGGERED), fired but its order failed (REJECTED), ended without firing (CANCELED). None: no
        row. A row without errorCode or triggerTime is an error, never "cancelled"."""
        row = next(iter(self._trigger_history(symbol, sid)), None)
        if row is None:
            return None
        err = row.get("errorCode")
        if err in (None, "") or row.get("triggerTime") in (None, ""):
            raise TransientError(200, None, f"손절 {sid}의 기록에 errorCode / triggerTime이 없습니다")
        fired_ms = to_ms(row.get("triggerTime"), "triggerTime")
        if str(err) not in ("0",):
            out = self._algo_dict(row, symbol, "REJECTED")
            out["dcError"] = f"{err} {row.get('errorMsg') or ''}".strip()
            return out
        if fired_ms > 0:
            return self._algo_dict(row, symbol, "TRIGGERED", self._child_order(symbol, sid, row, fired_ms))
        return self._algo_dict(row, symbol, "CANCELED")

    def _child_order(self, symbol: str, sid: str, row: dict, fired_ms: int) -> str:
        """The order a fired stop placed: fills under the stop's own ordId, else the one order of the coin with the
        stop's side and posSide, created from 2 s before its trigger time to CHILD_AFTER_MS after, not one of ours (no
        clOrdId of ours, and not an order this process placed: the history shows clOrdId empty, first live drill 10-25).
        Not found or not one: "" (the executor's P&L then reads every fill of the trade's window). A failed read of the
        fills under the stop's own ordId still leaves the order history to look in."""
        try:
            if self._fills(symbol, fired_ms - 60_000, fired_ms + CHILD_AFTER_MS, ord_id=sid):
                return sid
        except TestnetError:
            pass
        try:
            side, ps = side_of(row)
            cands = []
            for r in self._history(symbol):
                if str(r.get("side") or "").lower() != side or str(r.get("posSide") or "").lower() != ps:
                    continue
                if str(r.get("clOrdId") or "").startswith("pb") or str(r.get("ordId")) in self.own_oids:
                    continue                               # one of ours (every id this executor sends starts "pb")
                t = to_ms(r["cTime"]) if r.get("cTime") not in (None, "") else None
                if t is not None and fired_ms - 2_000 <= t <= fired_ms + CHILD_AFTER_MS:
                    cands.append(str(r.get("ordId")))
            return cands[0] if len(cands) == 1 else ""
        except TestnetError:
            return ""

    def algo_order(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        """A stop by its ordId (or the executor's id: _resolve_stop): the pending list, else its trigger-history row.
        Its reads share the protective budget (place_stop confirms a new stop with it). An ordId this process has not
        seen (after a restart) is looked for on every coin: a coin whose lists cannot be read is skipped, and then
        the answer is unknown (TransientError), never "not found"."""
        with self._protective():
            return self._algo_order(algo_id, client_id)

    def _algo_order(self, algo_id, client_id: Optional[str]) -> dict:
        if algo_id is None:
            algo_id = self._resolve_stop(ext_id(client_id))
        sid = str(algo_id)
        sym = self.order_symbol.get(sid)
        coins = [sym] if sym else list(COINS)
        unread: dict = {}                                  # coin -> the error that hid its lists (the scan only)
        for s in coins:
            try:
                row = next((r for r in self._triggers(s) if str(r.get("ordId")) == sid), None)
            except TestnetError as e:
                if sym:
                    raise
                unread[s] = e
                continue
            if row is not None:
                return self._algo_dict(row, s, "NEW")
        for s in [s for s in coins if s not in unread]:   # never a history row for a coin whose list was not read
            try:
                done = self._finished_stop(sid, s)
            except TestnetError as e:
                if sym:
                    raise
                unread[s] = e
                continue
            if done is not None:
                return done
        key = self.cid_by_stop.get(sid)
        if key is not None:                                # ours, accepted, in neither: not settled
            intent = self.stop_intents.get(key) or {}
            s = intent.get("symbol") or sym
            return {"algoId": sid, "clientAlgoId": key, "symbol": s, "side": str(intent.get("side") or "").upper(),
                    "orderType": "STOP_MARKET", "algoType": "CONDITIONAL",
                    "triggerPrice": str(intent.get("trig") or "0"),
                    "quantity": _num(self._base(s, intent["sz"])) if intent.get("sz") else "0",
                    "closePosition": False, "reduceOnly": True, "workingType": WORKING_TYPE[TRIGGER_PX_TYPE],
                    "algoStatus": UNCONFIRMED, "actualOrderId": ""}
        if unread:
            first = next(iter(unread.values()))
            raise TransientError(getattr(first, "status", 0), None, f"조건 주문 {sid}: {', '.join(unread)}의 목록을 읽지 "
                                                                    f"못해 있는지 모릅니다({first})"[:300])
        raise TestnetError(404, NOT_FOUND[0], f"조건 주문 {sid}이 없습니다")

    def cancel_algo(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        if algo_id is None:
            algo_id = self._resolve_stop(ext_id(client_id))
        sid = str(algo_id)
        sym = self.order_symbol.get(sid) or self.algo_order(algo_id=sid)["symbol"]
        try:
            self.req("POST", TRD + "/cancel-trigger-order", {"instId": fx(sym), "ordId": sid},
                     limit_key="trigger_cancel")
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            if e.code in NOT_FOUND:
                raise
            try:                                           # an undocumented refusal: did it end already?
                cur = self.algo_order(algo_id=sid)
            except TestnetError:
                raise e
            if cur["algoStatus"] in ("TRIGGERED", "CANCELED", "REJECTED"):    # only what the record says ended
                raise TestnetError(400, NOT_FOUND[1], f"이미 끝난 조건 주문({cur['algoStatus']}): {e.msg}") from e
            raise
        return {"algoId": sid, "clientAlgoId": self.cid_by_stop.get(sid, ""), "code": "200", "msg": "success"}

    def open_algo_orders(self, symbol: str) -> list:
        """Every resting trigger order of the coin: ours (closing, Conditional) as STOP_MARKET, any other kind as
        CONDITIONAL (never counted as a stop that covers a position). Rows of other coins never enter the answer. A row
        that may be one of our stops but cannot be read is an error (never "no stop") while it may protect something:
        the coin holds a position, or the row's ordId is a stop this process placed. On a coin without a position it
        protects nothing: it is listed as CONDITIONAL with ``dcUnreadable`` (the executor's sweep of the other coins
        goes on; it is never cancelled as a stray stop)."""
        out, unread = [], []
        for r in self._triggers(symbol):
            try:
                out.append(self._algo_dict(r, symbol))
            except TransientError as e:
                unread.append((r, e))
        if unread:
            if any(str(r.get("ordId")) in self.cid_by_stop for r, _ in unread) or self._position_rows(symbol):
                raise unread[0][1]
            out += [{"algoId": str(r.get("ordId")), "clientAlgoId": "", "symbol": symbol,
                     "side": str(r.get("side") or "").upper(), "positionSide": str(r.get("posSide") or ""),
                     "orderType": "CONDITIONAL", "algoType": "CONDITIONAL", "triggerPrice": "0", "quantity": "0",
                     "closePosition": False, "reduceOnly": False, "algoStatus": "NEW",
                     "dcKind": self._kind(r, True), "dcUnreadable": e.msg} for r, e in unread]
        return out

    def placed_stops(self, symbol: str) -> list:
        """The resting trigger orders of the coin that this client placed: an ordId it was answered, or a lost answer
        found by what was sent (the drill's clean-up cancels these and nothing else)."""
        mine = {sid for sid in self.stop_by_cid.values() if self.order_symbol.get(sid) == symbol}
        for key, intent in list(self.stop_intents.items()):
            if intent.get("symbol") == symbol and key not in self.stop_by_cid:
                mine |= {str(r["ordId"]) for r in self._search_stop(key)}
        return [o for o in self.open_algo_orders(symbol) if o["algoId"] in mine]

    def cancel_all_algo(self, symbol: str) -> dict:
        """Each resting conditional trigger order of the coin cancelled by its ordId (a position TP/SL set in the app,
        kind TPSL, belongs to its position and goes with it)."""
        for r in self._triggers(symbol):
            if self._kind(r, True) in OTHER_TRIGGERS:
                continue
            try:
                self.req("POST", TRD + "/cancel-trigger-order", {"instId": fx(symbol), "ordId": str(r["ordId"])},
                         limit_key="trigger_cancel")
            except TestnetError as e:
                if e.code not in NOT_FOUND or isinstance(e, TransientError):
                    raise
        return {"code": 200, "msg": "ok"}

    # ------------------------------------------------------------ positions
    def _position_rows(self, symbol: Optional[str] = None) -> list:
        """Open position rows (pos > 0). The answer must be a list and a row must be readable: never "flat" from a
        missing or garbled field. A coin with a long and a short at once, or a split position: TransientError
        (``dc_mixed``): never netted. Copy-trading rows (isLeading / isFollow) are not this bot's."""
        p = {"instType": "SWAP"}
        if symbol:
            p["instId"] = fx(symbol)
        rows = self._rows(self.req("GET", ACC + "/positions", p, limit_key="positions"), "포지션")
        out, per = [], {}
        for r in rows:
            sym = bn(r.get("instId"))
            if not sym or (symbol and sym != symbol):
                continue
            if r.get("isLeading") is True or r.get("isFollow") is True:
                continue
            amt = _dec(r.get("pos"), "pos")
            if amt == 0:
                continue
            ps = str(r.get("posSide") or "").lower()
            if amt < 0 or ps not in (LONG, SHORT):
                raise TransientError(200, None, f"{sym}: 포지션 방향이 이상합니다(posSide {r.get('posSide')!r}, 수량 "
                                                f"{r.get('pos')!r})")
            if str(r.get("mrgPosition") or MERGE).lower() != MERGE:
                err = TransientError(200, None, f"{sym}: 분할(split) 포지션이 있습니다(이 실행기는 합침만 다룹니다)")
                err.dc_mixed = True
                raise err
            per.setdefault(sym, []).append(ps)
            out.append(r)
        many = sorted(s for s, sides in per.items() if len(sides) > 1)
        if many:
            err = TransientError(200, None, f"{', '.join(many)}: 한 코인에 포지션이 둘 이상입니다(롱·숏 동시: 단방향이 아님)")
            err.dc_mixed = True
            raise err
        return out

    def _position_dict(self, symbol: str, rows: list) -> dict:
        main = rows[0] if rows else {}
        amt = Decimal(0)
        if rows:
            q = self._base(symbol, main.get("pos"))       # the side comes from posSide only
            amt = q if str(main.get("posSide")).lower() == LONG else -q
            self.pos_rows[symbol] = main
        else:
            self.pos_rows.pop(symbol, None)
        mt = str(main.get("mgnMode") or "").lower()
        return {"symbol": symbol, "positionAmt": _num(amt), "entryPrice": str(main.get("avgPx") or "0"),
                # the positions list carries the last price, not the mark price
                "markPrice": str(main.get("lastPx") or "0"), "liquidationPrice": str(main.get("liqPx") or "0"),
                "unRealizedProfit": str(main.get("unrealizedProfit") or "0"), "leverage": str(main.get("lever") or ""),
                "marginType": mt if mt in (ISOLATED, CROSS) else "", "hedge": False,
                "positionSide": main.get("posSide"), "mrgPosition": main.get("mrgPosition"),
                "posId": main.get("posId"), "updateTime": to_ms(main["uTime"]) if main.get("uTime") else None}

    def position(self, symbol: str) -> dict:
        return self._position_dict(symbol, self._position_rows(symbol))

    def positions(self) -> list:
        by: dict = {}
        for r in self._position_rows(None):
            by.setdefault(bn(r.get("instId")), []).append(r)
        out = [self._position_dict(s, rs) for s, rs in by.items() if s]
        for s in [s for s in self.pos_rows if s not in by]:
            self.pos_rows.pop(s, None)
        return [p for p in out if float(p["positionAmt"]) != 0]

    # ------------------------------------------------------------ fills, P&L, funding
    def _fills(self, symbol: str, lo_ms: int, hi_ms: int, ord_id: Optional[str] = None, depth: int = 0,
               budget: Optional[list] = None) -> list:
        """GET /deepcoin/trade/fills in [lo_ms, hi_ms]: begin / end one ms wider (whether they include their own
        millisecond is not said) and the rows kept by their ts; a full page (100) is read again in two halves, at most
        HISTORY_REQUESTS requests (a server that ignored the window would otherwise split forever: an error)."""
        budget = [HISTORY_REQUESTS] if budget is None else budget
        if budget[0] <= 0:
            raise TransientError(0, None, f"{symbol}: 체결이 너무 많아 나눠 읽지 못했습니다(요청 {HISTORY_REQUESTS}번)")
        budget[0] -= 1
        p = {"instType": "SWAP", "instId": fx(symbol), "begin": int(lo_ms) - 1, "end": int(hi_ms) + 1,
             "limit": PAGE_ROWS}
        if ord_id is not None:
            p["ordId"] = str(ord_id)
        try:
            data = self.req("GET", TRD + "/fills", p, limit_key="fills")
        except TestnetError as e:
            if ord_id is not None and e.code in NOT_FOUND and not isinstance(e, TransientError):
                return []                                  # an ordId with no fills, answered as an error
            raise
        rows = self._rows(data, "체결")
        if len(rows) >= PAGE_ROWS:
            if depth >= HISTORY_DEPTH or hi_ms - lo_ms < 2:
                raise TransientError(0, None, f"{symbol}: 체결이 너무 많아 나눠 읽지 못했습니다")
            mid = (int(lo_ms) + int(hi_ms)) // 2
            return self._fills(symbol, lo_ms, mid, ord_id, depth + 1, budget) + \
                self._fills(symbol, mid + 1, hi_ms, ord_id, depth + 1, budget)
        out = []
        for r in rows:
            if r.get("instId") not in (None, "", fx(symbol)):
                continue
            if ord_id is not None and str(r.get("ordId")) != str(ord_id):
                continue
            if int(lo_ms) <= to_ms(r.get("ts"), "ts") <= int(hi_ms):
                out.append(r)
        return out

    def user_trades(self, symbol: str, start_ms: int, end_ms: int, limit: int = 1000) -> list:
        """Account fills (Binance userTrades shape): price, qty (base units), realizedPnl (DeepCoin's own ``pnl`` of each
        closing order, checked against the replay: fills_from_rows), commission (fee: + paid), commissionAsset,
        orderId, side, time."""
        seen, rows = set(), []
        for r in self._fills(symbol, int(start_ms), int(end_ms)):
            k = (str(r.get("tradeId")), str(r.get("billId")))
            if k in seen:
                continue
            seen.add(k)
            rows.append(r)
        if not rows:
            return []
        pnl: dict = {}
        for oid in sorted({str(r.get("ordId")) for r in rows if side_of(r) in CLOSING}):
            try:
                rec = self._order_row(symbol, oid)
            except TestnetError:
                rec = None                                 # not readable now: the replay (or "unknown") stands
            if rec is not None and rec.get("pnl") not in (None, "") and rec.get("accFillSz") not in (None, ""):
                pnl[oid] = (_dec(rec.get("pnl"), "pnl"), _dec(rec.get("accFillSz"), "accFillSz"))
        return fills_from_rows(rows, self._spec(symbol)["ct_val"], symbol, pnl)

    def _bills(self, lo_ms: int, hi_ms: int) -> list:
        """GET /deepcoin/account/bills (USDT, swap), newest first, 100 a page. The cursor's direction is not settled
        by the docs: a page is asked with ``before`` = 1 ms past the oldest row seen and must only bring rows that old
        or older (a page that brings newer ones is an error, never a silent gap)."""
        out: dict = {}
        cursor = None
        for _ in range(BILL_PAGES):
            p = {"instType": "SWAP", "ccy": SETTLE, "limit": PAGE_ROWS}
            if cursor is not None:
                p["before"] = cursor
            rows = self._rows(self.req("GET", ACC + "/bills", p, limit_key="bills"), "자금 기록")
            new = 0
            oldest = None
            for r in rows:
                bid = str(self._need(r, "billId", "자금 기록"))
                t = to_ms(r.get("ts"), "ts")
                if cursor is not None and t >= cursor:
                    raise TransientError(200, None, "자금 기록을 앞으로 넘기는 방법이 문서와 달라 더 읽지 않습니다")
                oldest = t if oldest is None else min(oldest, t)
                if bid not in out:
                    out[bid] = r
                    new += 1
            if len(rows) < PAGE_ROWS or oldest is None or oldest < lo_ms or not new:
                break
            cursor = oldest + 1
        return [r for r in out.values() if lo_ms <= to_ms(r.get("ts"), "ts") <= hi_ms]

    def income(self, symbol: Optional[str], income_type: Optional[str], start_ms: int, end_ms: int,
               limit: int = 1000) -> list:
        """Funding in the Binance income shape (``income``: + received) from the bills of type 7 (Funding Fee, balChg).
        Bills carry no instrument: a funding bill in a trade's window is that trade's (one position at a time, the
        account is the executor's own). No TRANSFER rows (the transfer bill types are not clearly named; the live
        configs set no daily-loss or drawdown halt)."""
        if income_type not in (None, "FUNDING_FEE"):
            return []
        out = []
        for r in self._bills(int(start_ms), int(end_ms)):
            if str(r.get("type")) != "7":
                continue
            t = to_ms(r.get("ts"), "ts")
            out.append({"symbol": symbol or "", "incomeType": "FUNDING_FEE",
                        "income": _num(_dec(r.get("balChg"), "balChg")), "asset": r.get("ccy") or SETTLE, "time": t,
                        "tranId": _id60("funding", r.get("billId"), t), "info": "Funding Fee (bill type 7)"})
        return sorted(out, key=lambda r: int(r["time"]))

    def bill_types(self, start_ms: int, end_ms: int) -> dict:
        """Drill: how many bills of each type the window holds (compared with the app by the owners)."""
        kinds: dict = {}
        for r in self._bills(int(start_ms), int(end_ms)):
            kinds[str(r.get("type"))] = kinds.get(str(r.get("type")), 0) + 1
        return kinds


class DeepCoinKeyCheckClient(DeepCoinClient):
    """The key check (reads only): the account. The API reports no key permissions: "trade only, no withdrawal, server
    IP bound" comes from the owners' statement ``attested`` (DEEPCOIN_LIVE_KEY_CHECKED)."""
    __test__ = False

    def __init__(self, *a, attested: bool = False, **k):
        super().__init__(*a, **k)
        self.attested = attested

    def api_restrictions(self):
        data = self.req("GET", ACC + "/balances", {"instType": "SWAP"}, limit_key="balances")
        if not isinstance(data, list) or not any(isinstance(r, dict) and r.get("ccy") == SETTLE for r in data):
            return None                                     # nothing verified
        return permission_record(self.attested, True)


# ---------------------------------------------------------------- keys, allowlist, the executor's clients
def _values(env, names) -> set:
    return {str((env or {}).get(n) or "").strip() for n in names} - {""}


def trading_keys(mode: str, env, paper_env=None) -> tuple[str, str, str]:
    """The DeepCoin key, secret and passphrase, or Refused. Mainnet only, behind PAPERBOT_LIVE_MAINNET=I_UNDERSTAND.
    Never the paper runner's key, a Binance, Bybit, MEXC, WOO X Pro or Flipster key."""
    if mode != MODE_MAINNET:
        raise Refused(f"딥코인에는 테스트넷이 없습니다: \"exchange\": \"deepcoin\"는 \"mode\": \"mainnet\"만 됩니다"
                      f"(지금 {mode!r})")
    if (env.get(FLAG) or "") != FLAG_VALUE:
        raise Refused(f"실거래 스위치가 꺼져 있습니다: 환경 변수 {FLAG}={FLAG_VALUE} 가 필요합니다")
    key, secret = (str(env.get(n) or "").strip() for n in LIVE_KEY_NAMES)
    phrase = str(env.get(PASSPHRASE_NAME) or "").strip()
    if not (key and secret):
        raise Refused(f"{LIVE_KEY_NAMES[0]} / {LIVE_KEY_NAMES[1]} 가 비어 있습니다")
    if not phrase:
        raise Refused(f"{PASSPHRASE_NAME} 가 비어 있습니다 (API 키를 만들 때 두 분이 정한 패스프레이즈: 모든 요청에 들어갑니다)")
    if len({key, secret, phrase}) < 3:
        raise Refused(f"{LIVE_KEY_NAMES[0]} / {LIVE_KEY_NAMES[1]} / {PASSPHRASE_NAME} 중 같은 값이 있습니다")
    mine = {key, secret}
    if mine & (_values(env, PAPER_KEY_NAMES) | _values(paper_env, PAPER_KEY_NAMES)):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 paper 실행기의 읽기 전용 키(BINANCE_API_KEY)와 같습니다")
    if mine & _values(env, BINANCE_LIVE_KEY_NAMES + BINANCE_TESTNET_KEY_NAMES):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 바이낸스 키(LIVE_*/TESTNET_*)와 같습니다. 거래소마다 다른 키를 씁니다")
    if mine & _values(env, BY.LIVE_KEY_NAMES + BY.TESTNET_KEY_NAMES):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 바이비트 키(BYBIT_*)와 같습니다. 거래소마다 다른 키를 씁니다")
    if mine & _values(env, MX.LIVE_KEY_NAMES):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 MEXC 키(MEXC_*)와 같습니다. 거래소마다 다른 키를 씁니다")
    if mine & _values(env, WX.LIVE_KEY_NAMES + (WX.MEMO_NAME,)):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 WOO X Pro 키(WOOXPRO_*)와 같습니다. 거래소마다 다른 키를 "
                      "씁니다")
    if mine & _values(env, FL.LIVE_KEY_NAMES):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 플립스터 키(FLIPSTER_*)와 같습니다. 거래소마다 다른 키를 "
                      "씁니다")
    return key, secret, phrase


def attested(env) -> bool:
    return str((env or {}).get(KEY_CHECKED) or "").strip() == KEY_CHECKED_VALUE


def refuse_unless_allowed(mode: str, client) -> None:
    """Mainnet only, and the client must be the DeepCoin client pointing at the allowed host, with keys."""
    if mode != MODE_MAINNET:
        raise Refused(f"딥코인에는 테스트넷이 없습니다: mode={mode!r}로는 시작하지 않습니다(\"mainnet\"만)")
    host = urllib.parse.urlparse(getattr(client, "base", "") or "").hostname or ""
    if host not in DEEPCOIN_HOSTS or type(client) is not DeepCoinClient \
            or tuple(type(client).HOSTS) != DEEPCOIN_HOSTS:
        raise Refused(f"주소 {host!r}: 딥코인 실행기는 {'·'.join(DEEPCOIN_HOSTS)} 외에는 연결하지 않습니다")
    if getattr(client, "public_only", False):
        raise Refused("키 없이 만든 딥코인 클라이언트로는 실행기를 켜지 않습니다")


def check_executor_keys(mode: str, client, keycheck, env, paper_env) -> None:
    """The executor's key gates for DeepCoin (Executor.__init__): the keys, the key check, the owners' statement."""
    key, secret, phrase = trading_keys(mode, env, paper_env)
    if (client.key, client.secret, client.passphrase) != (key, secret, phrase):
        raise Refused("딥코인 실거래 실행기의 키가 DEEPCOIN_LIVE_KEY/SECRET/PASSPHRASE와 다릅니다")
    if not isinstance(keycheck, DeepCoinKeyCheckClient) or (keycheck.key, keycheck.secret, keycheck.passphrase) != (
            key, secret, phrase):
        raise Refused("딥코인 실거래는 키 확인(계정 읽기)을 거쳐야 시작합니다")
    if not attested(env) or not keycheck.attested:
        raise Refused(f"딥코인은 키 권한을 API로 알려 주지 않습니다. 키를 '거래(Trade)만, 출금 없음, 서버 IP만'으로 만든 것을 "
                      f"확인한 뒤 /etc/paperbot/executor.env에 {KEY_CHECKED}={KEY_CHECKED_VALUE} 를 넣으세요")


def clients(mode: str, env, paper_env=None):
    """(order client, key-check client) for the mode, keys from the environment."""
    key, secret, phrase = trading_keys(mode, env, paper_env)
    return (DeepCoinClient(key, secret, phrase),
            DeepCoinKeyCheckClient(key, secret, phrase, attested=attested(env)))


def public_client() -> DeepCoinClient:
    """Market data only (specs): no key, no private call."""
    return DeepCoinClient("", "", "", public_only=True)


# ---------------------------------------------------------------- drill (mainnet, tiny)
def reconcile(c: DeepCoinClient, symbol: str, stop_price: Optional[float] = None) -> dict:
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


def pace(c: DeepCoinClient, gap_s: float = DRILL_MIN_GAP_S, sleep=time.sleep, clock=time.monotonic) -> None:
    """The drill's requests: at least ``gap_s`` apart (the client's own budget keeps each endpoint's windows)."""
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
class DeepCoinDrill:
    """The DeepCoin micro drill on the REAL account. ``check()`` reads (time, instruments, account, fee rate, open
    orders and stops, funding bills, positions one side per coin) and sets the isolated leverage (BTC 40x, the others
    30x): no order. ``order_cycle()`` (only behind the explicit confirmation) runs one small-size cycle on one coin:
    a plain market entry, found by its clOrdId (GET order, and again with its answer treated as lost; whether the
    pending list / order history show it too is a note only), the leverage and margin read on the position, a reduce-only trigger stop (how long until it is listed; not
    in the trigger history while it rests; found again by what was sent), half of the position closed with a
    reduce-only market order (always, whatever the trigger test does), the stop moved to the half left (new first,
    then the old one cancelled: two must rest at once; how the cancelled one reads), then the trigger test (the stop
    moved to 0.1 % from the last price and left to fire for real; which price fired it and whose ordId its fills carry)
    or a reduce-only close of the rest, flat with no order and no stop left, and the P&L from the fills (DeepCoin's pnl)
    checked against the fill prices and the wallet change, with the fee rate measured on the fills against the fee
    endpoint. One run tests one side (``side``): the drill is done once a long and a short run are both [OK]."""
    client: DeepCoinClient
    symbols: tuple = COINS
    symbol: Optional[str] = None
    side: int = 1
    keycheck: Optional[DeepCoinKeyCheckClient] = None
    stop_frac: float = 0.01
    trigger_test: bool = True
    trigger_wait_s: float = TRIGGER_WAIT_S
    wait: Callable[[float], None] = time.sleep
    elapsed: Callable[[], float] = time.monotonic          # seconds, for the drill's waits (tests pass their clock)
    say: Optional[Callable[[str], None]] = None            # each step printed as it happens (the CLI prints)
    log: list = field(default_factory=list)
    fee_api: Optional[float] = None
    entry_sent: bool = False                               # set just before the cycle's entry goes out: from then on a
    entry_qty: float = 0.0                                 # stop part-way cleans up what the drill made (leave_flat)

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
        """The coin whose drill order (drill_qty) is the cheapest."""
        c = self.client
        return min(self.symbols, key=lambda s: self.drill_qty(c.spec(s), c.price(s)) * c.price(s))

    @staticmethod
    def drill_qty(spec: dict, price: float) -> float:
        """The fewest contracts (on lotSz) worth at least DRILL_ORDER_USDT that split into two equal halves of at
        least minSz each: the cycle closes one half with a reduce-only market order and the other later (whether
        DeepCoin takes a close, or leaves a position, under minSz is not said)."""
        step = spec["qty_step"]
        need = math.ceil(DRILL_ORDER_USDT / (price * step) - 1e-9) * step if price > 0 else 0.0
        half = max(spec["min_qty"], math.ceil(need / 2 / step - 1e-9) * step)
        return round(2 * half, 12)

    def check(self) -> list:
        c = self.client
        off = c.sync_time()
        self._step("서버 시간", abs(off) < 1000 and c.time_source != "local", {"offset_ms": off, "source": c.time_source})
        rows = {}
        for s in self.symbols:
            try:
                sp = c.spec(s)
            except TestnetError as e:                       # a missing unit: shown, never a 0
                rows[s] = {"error": e.msg}
                continue
            px = c.price(s)
            rows[s] = {"state": sp["status"], "ctVal": sp["ct_val"], "lotSz": sp["lot_sz"], "minSz": sp["min_sz"],
                       "tickSz": sp["tick_str"], "max_leverage": sp["max_leverage"], "maxMktSz": sp["max_mkt_sz"],
                       "min_order_usd": round(sp["min_qty"] * px, 4)}
            if sp.get("problem"):                           # e.g. no minSz: no new entry on it
                rows[s]["error"] = f"새 진입에 필요한 값 없음 → 새 진입 안 함: {sp['problem']}"
        self._step("상품 정보(6개 코인, live)", all("error" not in r and r["state"] == "Trading" and (
            r["max_leverage"] or 0) >= (40 if s == "BTCUSDT" else 30) for s, r in rows.items()), rows)
        a = c.account()
        pos = c.positions()
        self._step("선물 계정 읽기", True, {"equity": a["totalMarginBalance"], "wallet": a["totalWalletBalance"],
                                         "unrealized": a["totalUnrealizedProfit"], "available": a["availableBalance"],
                                         "assets": a["assets"], "positions": [(p["symbol"], p["positionAmt"])
                                                                              for p in pos]})
        try:
            fee = c.fee_rate(self.symbol or "DOGEUSDT")
            self.fee_api = fee["taker"]
            self._step("수수료율(API로 읽음, 편도)", True, {"taker_pct": round(fee["taker"] * 100, 4),
                                                       "maker_pct": round(fee["maker"] * 100, 4),
                                                       "level": fee.get("level")}, fatal=False)
        except TestnetError as e:
            self._step("수수료율(API로 읽음, 편도)", False, str(e), fatal=False)
        left = {s: (len(c.open_orders(s)), len(c.open_algo_orders(s))) for s in self.symbols}
        self._step("열린 주문·조건 주문(목록 읽기)", True, left)
        now = c.clock_ms() + c.offset_ms
        try:
            inc = c.income(None, None, now - 7 * 86_400_000, now)
            kinds = c.bill_types(now - 7 * 86_400_000, now)
            self._step("펀딩 기록 읽기(지난 7일, 자금 기록 type 7; + 받음 / - 냄, 앱과 비교)", True,
                       {"funding_rows": len(inc), "last": [(r["income"], r["time"]) for r in inc[-3:]],
                        "bill_types": kinds}, fatal=False)
        except TestnetError as e:
            self._step("펀딩 기록 읽기(지난 7일)", False, str(e), fatal=False)
        c.one_way()
        self._step("포지션: 한 코인에 한쪽만(롱·숏 동시 없음, 분할 없음)", c.one_side, {"positions": len(pos)})
        levs = {}
        for s in self.symbols:
            want = int(min(FIXED_LEVERAGE.get(s, DEFAULT_LEVERAGE), c.spec(s)["max_leverage"] or 10 ** 6))
            if any(p["symbol"] == s for p in pos):
                levs[s] = "포지션 있음"
                continue
            try:
                levs[s] = c.leverage(s, want)["leverage"]
            except TestnetError as e:                       # this coin only: shown with the others
                levs[s] = f"못 맞춤: {e.msg}"
        self._step("격리 레버리지 BTC 40배, 나머지 30배(다시 읽어 확인)",
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
            try:
                x = c.order(s, order_id=x["orderId"])
            except TestnetError:
                continue
        return x

    def _found_by_cid(self, s: str, ext: str, oid: str, sent_s: float) -> None:
        """The entry found by its clOrdId: GET order, and the pending list / order history (its answer treated as lost),
        with how long it took to show."""
        c = self.client
        got, err = None, None
        while self.elapsed() - sent_s < SETTLE_MS / 1000 + 10:
            try:
                got = c._find_cid(s, ext, lists=False)
            except TestnetError as e:
                err = e
            if got is not None:
                break
            self.wait(1.0)
        delay = round(self.elapsed() - sent_s, 1)
        self._step("진입 주문을 우리 번호(clOrdId)로 찾음(GET order)", got is not None and str(got.get("ordId")) == oid,
                   {"clOrdId": ext, "ordId": (got or {}).get("ordId"), "want": oid, "seconds": delay,
                    "error": None if got else str(err)})
        c.forget_order(ext)
        try:
            via, err = c.order(s, client_id=ext), None
        except TestnetError as e:
            via, err = None, e
        self._step("답을 잃은 주문 찾기(보낸 기록 없이 우리 번호로 다시 조회 - 실행기가 쓰는 길)", via is not None
                   and via.get("orderId") == oid, {"lookup": (via or {}).get("orderId"), "want": oid,
                                                   "status": (via or {}).get("status"),
                                                   "error": None if via else str(err)})
        self._lists_note(s, ext, oid)

    def _lists_note(self, s: str, ext: str, oid: str) -> None:
        """Only a note: does the pending list / order history show the entry's clOrdId too? The look-up by clOrdId
        (GET order, the step above) is what the executor relies on; the lists are its second try, and a real position
        is always read before anything is sent again. Not seen: what the order history shows of it, for the owners
        to pass on."""
        c = self.client
        start = self.elapsed()
        try:
            row = self._until(lambda: next((r for r in c._pending(s) + c._history(s) if r.get("clOrdId") == ext),
                                           None), tries=10, pause=2.0)
        except TestnetError as e:
            self._note(f"참고: 대기 목록·주문 기록을 읽지 못했습니다({e}). 위 [OK] 조회로 충분합니다")
            return
        waited = round(self.elapsed() - start, 1)
        if row is not None and str(row.get("ordId")) == oid:
            self._note(f"참고: 대기 목록·주문 기록에도 같은 clOrdId로 보입니다({waited}초)")
            return
        seen = {}
        try:
            hist = c._history(s)
            mine = next((r for r in hist if str(r.get("ordId")) == oid), None)
            by_id = next(iter(c._history(s, ord_id=oid)), None)
            seen = {"history_rows": len(hist), "in_newest": mine is not None,
                    "clOrdId_in_newest": None if mine is None else mine.get("clOrdId"),
                    "by_ordId": None if by_id is None else {"ordId": by_id.get("ordId"),
                                                            "clOrdId": by_id.get("clOrdId"),
                                                            "state": by_id.get("state")},
                    "first_last": [str(hist[0].get("ordId")), str(hist[-1].get("ordId"))] if hist else []}
        except TestnetError as e:
            seen = {"error": str(e)}
        self._note(f"참고: {waited}초 동안 대기 목록·주문 기록에서 clOrdId {ext}가 안 보였습니다. 위 [OK] 조회(GET order)로 "
                   f"찾으므로 실거래에는 문제없습니다. 이 줄을 그대로 전달해 주세요: {seen}")

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
        ext = ext_id(None)
        sent_s = self.elapsed()
        self.entry_sent, self.entry_qty = True, qty         # from here a stop part-way cleans up (only what it made)
        o = self._settle(s, c.market(s, buy, qty, client_id=ext))
        self._step(f"시장가 진입이 다 체결됨(작은 주문: 약 ${DRILL_ORDER_USDT:.0f} 이상, 절반이 최소 주문 이상)",
                   o.get("status") == "FILLED" and abs(float(o.get("executedQty") or 0) - qty) < spec["qty_step"] / 2,
                   {"status": o.get("status"), "avg": o.get("avgPrice"), "qty": o.get("executedQty"),
                    "contracts": _num(c._contracts(s, qty)), "fee": o.get("commission"), "orderId": o.get("orderId")})
        self._found_by_cid(s, ext, str(o["orderId"]), sent_s)
        entry = float(o["avgPrice"])
        p = (self._until(lambda: (lambda x: x if float(x["positionAmt"]) else None)(c.position(s))) or c.position(s))
        amt = float(p["positionAmt"])
        want_lev = int(min(FIXED_LEVERAGE.get(s, DEFAULT_LEVERAGE), spec["max_leverage"] or 10 ** 6))
        self._step("포지션 크기·레버리지·격리·합침(포지션 줄에서 읽음)", abs(amt - self.side * qty) < spec["qty_step"] / 2
                   and _int(p.get("leverage")) == c.lev.get(s, want_lev) and p.get("marginType") == ISOLATED
                   and p.get("mrgPosition") == MERGE,
                   {"positionAmt": amt, "qty": qty, "leverage": p.get("leverage"), "marginType": p.get("marginType"),
                    "mrgPosition": p.get("mrgPosition"), "entryPrice": p.get("entryPrice")})
        a1 = c.account()
        lev = _int(p.get("leverage")) or 1
        margin = abs(amt) * entry / lev
        eq1 = float(a1["totalMarginBalance"])
        self._step("평가액(equity)에 포지션 증거금이 들어 있음(진입해도 증거금만큼 줄지 않음)", abs(eq1 - w0) < 0.5 * margin,
                   {"equity_before": w0, "equity_open": eq1, "margin": round(margin, 6),
                    "available": a1["availableBalance"], "unrealized": a1["totalUnrealizedProfit"], "leverage": lev})
        stop1 = round_stop(entry * (1 - self.side * self.stop_frac), spec["tick"], self.side)
        key1 = ext_id(None)
        st1 = place_stop(c, s, sell, stop1, abs(amt), client_id=key1)
        stops = live_stops(c, s)
        self._step("손절이 딥코인에 걸림(청산 방향 조건 주문, 마지막 가격, 시장가; 대기 목록에 보임)",
                   len(stops) == 1 and float(stops[0]["triggerPrice"]) == stop1 and covers(stops[0], amt)
                   and stops[0].get("workingType") == "CONTRACT_PRICE",
                   {"stops": [(x["algoId"], x["triggerPrice"], x["quantity"], x["side"], x.get("positionSide"),
                               x.get("dcKind")) for x in stops],
                    "listed_after_ms": c.list_delay_ms.get(st1["algoId"])})
        hist = c._trigger_history(s, st1["algoId"])
        self._step("걸려 있는 손절은 발동 기록(trigger history)에 없음(있으면 '취소'로 잘못 읽을 수 있음)", not hist,
                   {"history_rows": hist[:1]})
        c.forget_stop(key1)
        again = c.algo_order(client_id=key1)
        self._step("답을 잃은 손절 찾기(보낸 내용: 방향·수량·발동 가격, 보내기 전 목록 제외)",
                   again.get("algoId") == st1["algoId"], {"found": again.get("algoId"), "want": st1["algoId"]})
        # one reduce-only market close in every run (the trigger test may close the rest by itself): half of it
        mine = {str(o["orderId"])}
        part = round(abs(amt) / 2, 12)
        rest = abs(amt) - part
        x1 = self._settle(s, c.market(s, sell, part, reduce_only=True, client_id=ext_id(None)))
        p2 = self._until(lambda: (lambda x: x if abs(abs(float(x["positionAmt"])) - rest) < spec["qty_step"] / 2
                                  else None)(c.position(s))) or c.position(s)
        self._step("줄이기 전용 시장가로 절반 청산(나머지는 손절 발동 시험이나 마지막 청산으로)",
                   x1.get("status") == "FILLED" and abs(float(x1.get("executedQty") or 0) - part) < spec["qty_step"] / 2
                   and abs(abs(float(p2["positionAmt"])) - rest) < spec["qty_step"] / 2,
                   {"status": x1.get("status"), "avg": x1.get("avgPrice"), "qty": x1.get("executedQty"),
                    "positionAmt": p2["positionAmt"], "orderId": x1.get("orderId")})
        mine.add(str(x1["orderId"]))
        amt = float(p2["positionAmt"])
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
        self._step("손절 옮기기(남은 크기로; 새 손절 → 확인 → 옛 손절 취소, 빈틈 없음: 두 개가 같이 걸려야 함)",
                   mv["result"] == "moved" and seen.get("during") == 2 and len(after) == 1
                   and after[0]["algoId"] == mv["stop"]["algoId"] and float(after[0]["triggerPrice"]) == stop2
                   and covers(after[0], amt) and abs(float(after[0]["quantity"]) - abs(amt)) < spec["qty_step"] / 2,
                   {"during": seen.get("during"),
                    "after": [(x["algoId"], x["triggerPrice"], x["quantity"]) for x in after], "positionAmt": amt})
        old = self._until(lambda: (lambda o: o if o.get("algoStatus") == "CANCELED" else None)(
            self._algo_or_empty(st1["algoId"])), tries=8, pause=1.0) or self._algo_or_empty(st1["algoId"])
        self._step("취소한 손절이 발동 기록에 '발동 안 함'으로 남음(CANCELED)", old.get("algoStatus") == "CANCELED",
                   {"status": old.get("algoStatus")}, fatal=False)
        fired = None
        if self.trigger_test:
            fired = self._trigger_test(s, sell, amt, mv["stop"]["algoId"], spec)
            if fired and fired.get("actualOrderId"):
                mine.add(str(fired["actualOrderId"]))
        if float(c.position(s)["positionAmt"]) != 0:
            x = self._settle(s, c.market(s, sell, abs(amt), reduce_only=True, client_id=ext_id(None)))
            self._step("줄이기 전용 시장가로 나머지 청산", x.get("status") == "FILLED",
                       {"status": x.get("status"), "avg": x.get("avgPrice"), "qty": x.get("executedQty")})
            mine.add(str(x["orderId"]))
        if self._until(lambda: float(c.position(s)["positionAmt"]) == 0):   # its stops go only once it reads flat
            cancel_own(c, s)
        clean = self._until(lambda: float(c.position(s)["positionAmt"]) == 0 and not c.open_orders(s)
                            and not c.open_algo_orders(s))
        self._step("포지션 없음, 주문·조건 주문 없음", clean,
                   {"positionAmt": c.position(s)["positionAmt"], "orders": len(c.open_orders(s)),
                    "stops": len(c.open_algo_orders(s))})
        t1 = c.clock_ms() + c.offset_ms

        def pnl(only_mine: bool = True, with_pnl: bool = True):
            fills = [f for f in c.user_trades(s, t0 - 5_000, t1 + 5_000) if not only_mine or str(f["orderId"]) in mine]
            if not balanced(self.side, fills, spec["qty_step"]):
                return None
            # the closing orders' records (their pnl) can show a moment after their fills: waited for
            if with_pnl and any(f["side"] != buy and f.get("realizedSource") != "pnl" for f in fills):
                return None
            return fills
        fills = self._until(pnl, tries=8, pause=1.5) or pnl(with_pnl=False)
        if not fills and fired:
            # the fired stop's order was not found: every fill of the drill's minutes on this coin
            fills = self._until(lambda: pnl(only_mine=False), tries=4, pause=1.5) or pnl(False, False)
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
            ok = (abs(realized - by_fills) <= max(1e-6, 1e-7 * notional) and fees > 0
                  and all(f.get("realizedSource") == "pnl" and f.get("realizedCheck") == "ok" for f in outs)
                  and abs((w1 - w0) - (realized - fees + funding)) <= tol)
            detail = {"fills": len(fills), "orders": sorted({str(f["orderId"]) for f in fills}),
                      "realized_dc_pnl": round(realized, 6), "by_fill_prices": round(by_fills, 6),
                      "fees": round(fees, 6), "funding": round(funding, 6), "net": round(realized - fees + funding, 6),
                      "check": sorted({str(f.get("realizedCheck")) for f in outs}),
                      # paid fee per side, % of notional
                      "fee_rate_pct": round(100 * fees / notional, 4) if notional else None,
                      "fee_api_pct": round(100 * self.fee_api, 4) if self.fee_api is not None else None,
                      "wallet_change": round(w1 - w0, 6)}
        self._step("체결로 계산한 손익: 딥코인 pnl = 체결 가격 = 지갑 변화(수수료·펀딩 포함)", ok, detail)
        if fills:
            measured = detail.get("fee_rate_pct")
            same = measured is not None and self.fee_api is not None and abs(measured / 100 - self.fee_api) <= 5e-5
            self._step("실제 수수료율 = 수수료율 API(편도; 다르면 실제 값을 쓰세요)", same,
                       {"fee_rate_pct": measured, "fee_api_pct": detail.get("fee_api_pct")}, fatal=False)
        self._step("요청 한도(429) 답", True, {"429_answers": c.rate_answers}, fatal=False)
        return self.log

    def _trigger_test(self, s: str, sell: str, amt: float, stop_id: str, spec: dict) -> Optional[dict]:
        """The stop moved to TRIGGER_GAP from the last price (on the losing side) and left to fire for real: the
        position must close by itself, and the stop must read as fired. The last and the mark price are watched while
        waiting: which one crossed the level says which price fired it. Not reached in time: noted (not a failure), and
        the cycle closes the position itself."""
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
                self._step("손절 발동 시험: 가격이 닿자 딥코인이 포지션을 스스로 닫음", got.get("algoStatus") == "TRIGGERED",
                           {"status": got.get("algoStatus"), "actualOrderId": got.get("actualOrderId")}, fatal=False)
                self._fills_of_stop(s, stop_id, got)
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
        seen = {"last": [], "mark": []}
        self._note(f"손절 발동 시험: 시험 손절 {level:g}(지금 가격 {last:g})에 가격이 닿기를 기다립니다"
                   f"(최대 {self.trigger_wait_s / 60:.0f}분). 기다리는 것이 정상입니다: 창을 닫거나 Ctrl+C를 누르지 마세요")
        while self.elapsed() - start < self.trigger_wait_s:
            try:
                seen["last"].append(c.price(s))
                seen["mark"].append(c.mark(s))
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
        self._step("손절 발동 시험: 가격이 닿자 딥코인이 포지션을 스스로 닫음", got.get("algoStatus") == "TRIGGERED",
                   {"stop": level, "status": got.get("algoStatus"), "actualOrderId": got.get("actualOrderId")},
                   fatal=False)
        self._step("손절을 발동시킨 가격(마지막 가격 / 마크 가격)", True, trigger_source(self.side, level, seen),
                   fatal=False)
        self._fills_of_stop(s, sid, got)
        return got

    def _fired(self, sid: str) -> dict:
        return self._until(lambda: (lambda o: o if o.get("algoStatus") in ("TRIGGERED", "CANCELED", "REJECTED")
                                    else None)(self._algo_or_empty(sid)), tries=10, pause=1.5) \
            or self._algo_or_empty(sid)

    def _fills_of_stop(self, s: str, sid: str, got: dict) -> None:
        """Whose ordId the fired stop's fills carry: its own, or the order it placed (found by side and time)."""
        c = self.client
        now = c.clock_ms() + c.offset_ms
        try:
            own = c._fills(s, now - 3_600_000, now + 5_000, ord_id=sid)
            child = got.get("actualOrderId") or ""
            theirs = c._fills(s, now - 3_600_000, now + 5_000, ord_id=child) if child and child != sid else []
        except TestnetError as e:
            self._step("발동한 손절의 체결 찾기", False, str(e), fatal=False)
            return
        self._step("발동한 손절의 체결을 찾음(손절 자신의 ordId, 또는 손절이 낸 주문)", bool(own or theirs),
                   {"own_fills": len(own), "stop": sid, "child_order": child if child != sid else "",
                    "child_fills": len(theirs)}, fatal=False)

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


def cancel_own(c: DeepCoinClient, sym: str) -> None:
    """The drill's clean-up: cancel the stops and the orders that this client placed on the coin (never another's)."""
    for o in c.placed_stops(sym):
        try:
            c.cancel_algo(algo_id=o["algoId"])
        except TestnetError as e:
            if e.code not in NOT_FOUND or isinstance(e, TransientError):
                raise
    for o in c.open_orders(sym):
        if o.get("clientOrderId") in c.sent:
            c.cancel(sym, o["orderId"])


def leave_flat(c: DeepCoinClient, sym: str, add, side: int, most: float) -> None:
    """After a drill stopped part-way, only once its own entry was sent: close what is left of the drill's position
    (reduce-only, at most ``most`` and only on the drill's ``side``), then, once the position reads flat, cancel the
    stops and orders the drill placed (cancel_own). A position that is still open keeps its stops. Each part on its
    own, so one failure does not skip the reading after it. ``add(step, ok, detail)`` records the result."""
    try:
        amt = float(c.position(sym)["positionAmt"])
        close = min(abs(amt), float(most)) if amt * side > 0 else 0.0
        if close:
            c.market(sym, "SELL" if amt > 0 else "BUY", close, reduce_only=True)
    except Exception as e:                     # noqa: BLE001 - the position is read again below
        add("정리: 포지션 닫기 실패(앱에서 직접 확인하세요)", False, f"{type(e).__name__}: {e}")
    try:
        amt = float(c.position(sym)["positionAmt"])
        if amt == 0:
            cancel_own(c, sym)
        else:                                  # never a position without its stop
            add("정리: 포지션이 남아 있어 손절을 그대로 둡니다(앱에서 직접 확인하세요)", False, {"positionAmt": amt})
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


def specs_text(c: DeepCoinClient, symbols=COINS) -> str:
    lines = []
    for s in symbols:
        try:
            sp = c.spec(s)
        except TestnetError as e:                           # a missing unit: said plainly, never a 0
            lines.append(f"{s}: 상품 정보를 쓸 수 없습니다(거래 안 함): {e.msg}")
            continue
        px = c.price(s)
        lines.append(f"{s}: 상태 {sp['status']}, 1계약 {sp['ct_val']} {sp.get('base_coin') or ''}, 수량 단위 "
                     f"{sp['lot_sz']}계약, 최소 주문 {min_order_text(sp)}(지금 약 ${sp['min_qty'] * px:,.4f}), 가격 단위 "
                     f"{sp['tick_str']}, 최대 {sp['max_leverage'] or 0:g}배, 시장가 최대 {sp['max_mkt_sz']}계약")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "drill", "reconcile", "specs"])
    ap.add_argument("--symbol", default=None, help="drill order coin (default: the cheapest drill order)")
    ap.add_argument("--side", choices=["long", "short"], default="long",
                    help="the cycle's side (the drill is done once a long and a short run both passed)")
    ap.add_argument("--confirm-order", default="", help=f"{DRILL_CONFIRM}: run the one real order cycle")
    ap.add_argument("--no-trigger-test", action="store_true", help="close by hand instead of letting the stop fire")
    args = ap.parse_args(argv)
    if args.cmd == "specs":                 # public data only: no key needed
        c = public_client()
        c.sync_time()
        print(f"서버 시간 차이 {c.offset_ms} ms ({c.time_source})")
        print(specs_text(c))
        return 0
    try:      # mainnet keys only: never the paper runner's key or another exchange's
        c, kc = clients(MODE_MAINNET, os.environ, read_env_file(PAPER_ENV_FILE))
    except Refused as e:
        print(f"시작하지 않습니다: {e}", file=sys.stderr)
        return 2
    c.sync_time()
    if args.cmd == "reconcile":
        print(json.dumps(reconcile(c, args.symbol or "BTCUSDT"), indent=1))
        return 0
    pace(c)
    d = DeepCoinDrill(c, symbol=args.symbol, side=1 if args.side == "long" else -1, keycheck=kc,
                      trigger_test=not args.no_trigger_test, say=say)
    # a closed terminal (SIGHUP) or a stop (SIGTERM) mid-drill: leave the account flat before exiting
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _interrupt)
    return 0 if run_drill(c, d, args.cmd, args.confirm_order == DRILL_CONFIRM, signals=True) else 1


def run_drill(c: DeepCoinClient, d: DeepCoinDrill, cmd: str, confirmed: bool, pause=time.sleep,
              signals: bool = False) -> bool:
    """check, then (drill + the confirmation only) the order cycle. A stop part-way (a failed step, an error, Ctrl+C,
    a closed terminal) after the cycle's entry was sent closes what the drill opened and cancels what it placed
    (leave_flat); before it nothing is touched (a coin that was not empty is never the drill's to close). True when
    every step is [OK]; the order cycle tests one side, so the last line asks for the other side's run too."""
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
        if orders and d.entry_sent:
            leave_flat(c, d.symbol, d.add, d.side, d.entry_qty)
        elif orders:
            d._note("진입 주문을 보내기 전에 멈췄습니다: 계정에는 손대지 않았습니다(정리할 것 없음)")
    ok = ok and all(r["ok"] for r in d.log)
    bad = [r["step"] for r in d.log if not r["ok"]]
    if d.say:
        text = "모두 [OK]" if ok else f"[FAIL] {len(bad)}개 — {', '.join(bad)}"
        if orders:
            this, other = ("롱", "숏(--side short)") if d.side > 0 else ("숏", "롱(--side long)")
            text += f" (이번은 {this} 쪽입니다. {other}도 모두 [OK]여야 drill이 끝납니다)"
        d.say(f"끝: {cmd} {text}")
    return ok


if __name__ == "__main__":
    hide_process_memory()
    sys.exit(main())
