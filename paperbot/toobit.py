"""Toobit USDT-M perpetual futures (api.toobit.com) for the executor: client, host allowlist, keys, key check, drill.
``"exchange": "toobit"`` in the executor config uses it (mainnet only: Toobit has no futures testnet); the Binance,
Bybit, MEXC, WOO X Pro, Flipster and DeepCoin paths are unchanged. Owners 10-25: a new $50 live bot on Toobit that will
follow the rule bot's V3.9 1-hour paper account. Its exits and leverage are decided elsewhere: this module is the
exchange connection, its checks and its drill only (docs/toobit-ko.md).

    python -m paperbot.toobit specs                      # the 6 coins' live contract specs (public, no key needed)
    python -m paperbot.toobit check                      # read-only checks + isolated leverage 40/30 (no order)
    python -m paperbot.toobit drill --confirm-order REAL_ORDER [--symbol DOGEUSDT] [--side short]   # + one small
                                                         # order cycle on one side and the stop-trigger test
                                                         # (--no-trigger-test skips it); run once per side

Sources (read as data, 10-25): Toobit's own USDT-M swap API docs, the last full version (January 2026) of the
toobit-docs/apidocs repository (api-docs.toobit.com was not reachable from here): base URL https://api.toobit.com;
header X-BB-APIKEY; a SIGNED request carries timestamp (ms) and recvWindow, and signature = hex HMAC-SHA256(secret, the
query string followed by the form body) (both of the docs' examples are reproduced in tests/test_toobit.py); a request
older than recvWindow (5 s) or more than 1 s ahead of the server is refused (-1021); errors {"code": -XXXX, "msg"} as
on the Error Codes page (Binance-like); 429 for a rate limit, whose numbers GET /api/v1/exchangeInfo ``rateLimits``
gives (REQUEST_WEIGHT per minute, ORDERS per window; each endpoint has a weight). Contracts "BTC-SWAP-USDT" in
exchangeInfo ``contracts``: contractMultiplier (base units per contract), filters PRICE_FILTER tickSize, LOT_SIZE minQty
/ maxQty / stepSize, MIN_NOTIONAL minNotional, riskLimits (initialMargin). Sizes are CONTRACTS (``quantity`` is a LONG;
positions are "pieces"). Sides BUY_OPEN / SELL_OPEN / BUY_CLOSE / SELL_CLOSE; a market order is type LIMIT with
priceType MARKET (matched at the latest price x (1 +- 5 %)); a stop is type STOP with stopPrice; every order carries a
newClientOrderId ("a unique id among open orders"). Also read, as data and not as authority: ccxt's toobit.js (the
market-order shape, the signing, the answers' field shapes: the fills' own realizedPnl and commission, the positions,
a cancel answered with the order's status; ccxt maps a reduce-only buy to SELL_CLOSE, the other way round from the docs'
words: see "What only a live run can confirm").

The client answers in the SAME shapes the executor reads from the Binance client (paperbot/testnet.py), like
paperbot/deepcoin.py, so the executor, the stop protocol (place_stop / move_stop / live_stops / covers) and livepnl run
unchanged.

  Binance client call          Toobit (api.toobit.com)
  spec(symbol)                 GET  /api/v1/exchangeInfo ``contracts`` (public, all, cached 5 s); its rateLimits too
  price / mark                 GET  /quote/v1/contract/ticker/price ``p`` (last) / GET /quote/v1/markPrice ``price``
  klines (1m)                  GET  /quote/v1/klines interval 1m (last price), startTime / endTime, <= 1000 rows a page
  sync_time                    GET  /api/v1/time {serverTime}; ``timestamp`` is counted on the server clock
  account()                    GET  /api/v1/futures/balance USDT ``balance`` (the wallet, unrealized P&L not in it) +
                               crossUnRealizedPnl + the isolated positions' unrealizedPnL (GET positions) = equity
  one_way()                    Toobit's sides open and close each side of a two-way account: every executor order names
                               its side (BUY_OPEN / SELL_OPEN to open, SELL_CLOSE / BUY_CLOSE to close), and the
                               executor sees ONE net position per coin. one_way() checks the positions: a coin holding a
                               long and a short at once is Refused
  isolated(symbol)             POST /api/v1/futures/marginType ISOLATED, POST /api/v1/futures/leverage (BTC 40x, others
                               30x), both read back with GET /api/v1/futures/accountLeverage (again after a pause while
                               it lags); a coin it cannot set never stops the start (leverage() sets it before an entry)
  market(...)                  POST /api/v1/futures/order type LIMIT + priceType MARKET, quantity in contracts,
                               newClientOrderId: open = BUY_OPEN / SELL_OPEN; close = SELL_CLOSE (a long) / BUY_CLOSE
                               (a short), which can never open or flip a position; read back with GET order?orderId= ;
                               a remainder still resting after the read-back is cancelled (a market order is matched
                               only within 5 % of the last price)
  order(symbol, id / cid)      GET  /api/v1/futures/order (orderId, or origClientOrderId), then openOrders and
                               historyOrders of the coin (their clientOrderId is a second try only: DeepCoin's first
                               live drill, 10-25, read it empty in a list; the drill checks both and notes the lists)
  stop_close(...)              POST /api/v1/futures/order type STOP, priceType MARKET, the closing side (SELL_CLOSE /
                               BUY_CLOSE), quantity = the position's contracts, stopPrice, newClientOrderId; then
                               waited for in GET /api/v1/futures/openOrders?type=STOP (about 5 s)
  algo_order / open_algo_orders GET order?type=STOP (orderId or origClientOrderId) and openOrders?type=STOP; an ended
                               stop by its own record (GET order, else historyOrders?type=STOP): see "Stops"
  cancel_algo / cancel_all_algo DELETE /api/v1/futures/order?type=STOP&orderId= (each resting stop of the coin)
  cancel / cancel_all          DELETE /api/v1/futures/order?orderId= (each open order of the coin)
  open_orders                  GET  /api/v1/futures/openOrders (type LIMIT, the default)
  position / positions         GET  /api/v1/futures/positions  ``position`` (contracts) x contractMultiplier, ``side``
  user_trades                  GET  /api/v1/futures/userTrades (startTime / endTime, <= 1000 rows: a full page is read
                               again in halves) -> fills; realized P&L = Toobit's own ``realizedPnl`` of each closing
                               fill, checked against the P&L replayed from the fills' own prices (paperbot/mexc.py
                               fills_from_deals)
  income                       GET  /api/v1/futures/balanceFlow flowType 32 (Fund Fee: FUNDING_FEE) and 51 (transfer:
                               TRANSFER), ``change`` (+ received / in)
  fee_rate                     GET  /api/v1/futures/commissionRate (open / close, maker / taker)

Client ids. ``ext_id`` maps each executor id to a deterministic newClientOrderId of 1-32 letters and digits (an id that
already fits is kept, any other becomes "pbh" + 29 hex of its SHA-1), so a look-up after a restart finds the same id
without a ledger. The docs promise uniqueness only "among open orders": a filled market order's id may be taken again,
so the client never relies on a refusal. An opening order is looked up by its id before it is sent (an id Toobit
already has is never sent twice, also after a restart), an opening id this process sent is never sent again at all, and
a close is sent again under the same id only once it is known to be absent (then sized from the position); the
executor makes its stop and close ids unique (UNIQUE_CLIENT_IDS). Not found: "not found" only SETTLE_MS (25 s) after
this process's last send of it (the docs warn that REST reads lag in a fast market), an unknown outcome
(TransientError) before. Stops carry a newClientOrderId too: a stop whose answer was lost is looked up by its id (GET
order type=STOP, then the stop list and the stop history of the coin).

Answers to an order or a stop (POST order). Refused (nothing ran) only on a code of the docs' Error Codes page that
refuses the request (the key, the signature, the timestamp, a parameter, the size, the margin; the timestamp code -1021
is a clock refusal, re-synced and sent again by the executor). The docs' "execution status unknown" codes (-1000,
-1001, -1006, -1007, -1146), the rate codes (-1003, -1015), the duplicate id (-1141: an order with that id exists), any
code the docs do not list, 403 / 418, 5xx, a body that is not JSON and a timeout may come from an order that ran: an
unknown outcome (TransientError or RateLimited), looked up by the id, an opening order never sent again. The checks
before an opening order goes out (the contract read, the look-up of its id) are tried again for a few seconds while
they fail; still failing: NotSent, a refusal (nothing was sent: the executor drops that entry as refused). Words in a
message are read on reads only (a rate word: 429; "not exist" / "not found": not found). A setting keeps its code as it
came; marginType / leverage are refused only on a documented code; anything else, and a read-back that still shows
another value after a pause, is TransientError (tried again), never a refusal.

Rate limits and 429. Each request waits for the weight budget (80 % of exchangeInfo's REQUEST_WEIGHT per minute; a new
order also for 80 % of its ORDERS window) BEFORE its timestamp and signature are made: never sent stale. Protective work
never waits for this self-imposed budget (its 20 % headroom is there for it); a 429 the exchange answers is handled
where it comes. A read answered 429 is read again after its Retry-After (at most 3 times); so are the setting and
cancel writes. An order never is: an opening order's 429 is an unknown outcome (looked up by its id, never sent twice);
a close's is looked up by its id (after the Retry-After, then every 2 s) and never sent again inside this client; a
stop's is looked up by its id, and a stop the first look-up does not find is sent ONCE more under the same id (either
one may then be it; a surplus reduce-only stop is cancelled by the executor). Protective work (a stop, a reduce-only
close, the look-up of one) has a budget: every wait inside one call shares PROTECT_WAIT_S (10 s); a wait that does not
fit raises RateLimited at once, before anything more is sent, and the executor's own handling takes over.

Stops. A stop is confirmed only from the stop list (openOrders type=STOP; stop_close waits about 5 s for it). Its own
record (GET order type=STOP) decides when it says the stop ended, also while a lagging list still shows it: FILLED
(ORDER_FILLED or FILLED: it fired: TRIGGERED, the order it placed found by its fills: under the stop's own orderId, else
the one order of the coin on the stop's side made right after it fired and not one of ours), CANCELED (ORDER_CANCELED
or CANCELED), REJECTED / FAILED (it ended without closing: REJECTED, never "fired"). A stop the list does not show and
whose record does not say it ended is UNCONFIRMED (place_stop raises ProtectionError, a move keeps the old stop); with
no record anywhere, someone else's is "not found". A status the client does not know (PENDING_CANCEL among them) is an
error, never "cancelled". A cancel is answered with the order: a resting status means this cancel ended it; an ended
status means it had already ended (NOT_FOUND[1]: the caller reads what happened). Only a STOP on a closing side counts
as a stop; one on an opening side, and a position TP/SL (STOP_LONG_LOSS ...), is listed as CONDITIONAL and never
counted. A row that may be ours but cannot be read (its side missing or not a documented value; its level or size
missing) is an error wherever it may protect something (the coin holds a position, or it is a stop this process placed);
on a flat coin open_algo_orders lists it as not a stop (``tbUnreadable``).
Why the stops are meant to fire on the last price: the paper engine judges its stops on the last price, the other
exchanges' stops trigger on it, and the executor's own ladder reads the last price's 1m candles. Toobit's STOP order
takes no price-type field (only the position TP/SL has slTriggerBy, default CONTRACT_PRICE = the last price): the drill
watches the last and the mark price while its test stop fires and says which crossed.

A coin whose LOT_SIZE lacks minQty or maxQty is never read as 0: it refuses new entries with that reason (leverage()
and an opening order; specs, check and the preflight show it) while the executor starts and its open position is still
protected and closed. A missing contractMultiplier, tickSize or stepSize is a BAD_SPEC error for that coin (a stop and a
close need them). Sizes: contracts x contractMultiplier = base units; LOT_SIZE is read in contracts when its stepSize is
a whole number, else in base units (stepSize / contractMultiplier contracts, which must be a whole number); specs prints
the raw values and the drill compares the position's own value (positionValue, USDT) with contracts x multiplier x
price. A coin whose cached status is not TRADING is read again in leverage() before an entry.

What only a live run can confirm (docs/toobit-ko.md "drill이 확인할 것"; the drill checks each): the side words (the
docs: SELL_CLOSE sells to close a long, BUY_CLOSE buys to close a short; ccxt maps them the other way round; a CLOSE
side can never open, so a wrong reading is refused, never a flip: every run closes half of its position with one, on
each side); the size units (the position's value against contracts x multiplier x price); a plain market order (LIMIT +
MARKET) filling fully; two reduce-only STOP orders resting at once (the stop protocol needs it for a moment: new stop ->
confirmed -> old one cancelled) and a reduce-only market close while a full-size stop rests (a close order may lock the
position's ``available`` quantity); a stop actually firing and closing the position, which price fired it, and whose
orderId its fills carry; how a resting, a cancelled and a fired stop read (the status words, the level's field name);
the look-ups the executor relies on: a just-sent order and a stop found by their client ids with GET order (also with
the answer treated as lost); whether the lists carry clientOrderId (a note); the leverage and isolated margin on the
drill's position; the balance and equity reading (the wallet does not drop by the margin; equity = wallet + the
position's unrealized P&L); the real taker fee against commissionRate (base taker 0.06 %; the TetherDrop payback is paid
later, outside the bot); whether a fill's realizedPnl is before fees (against the fill prices and the wallet change);
the funding sign; the server time offset; how long a new stop takes to be listed; the 32-character client id.

Safety:
- ``ToobitClient`` talks to api.toobit.com only (class-level allowlist, https only, checked at construction; the
  executor checks again). Mainnet only.
- Keys: TOOBIT_LIVE_KEY / TOOBIT_LIVE_SECRET behind PAPERBOT_LIVE_MAINNET=I_UNDERSTAND, from its own key file
  /etc/paperbot/executor-toobit.env; never the paper runner's key or another exchange's.
- Key gate: the futures API does not report a key's permissions. The gate proves the key reads the futures account;
  "futures trade only, no withdrawal, server IP bound" is the owners' statement
  TOOBIT_LIVE_KEY_CHECKED=FUTURES_ONLY_NO_WITHDRAW_IP_BOUND (refused without it), shown as a warning at every start.
- An order that was accepted (it has an orderId) is never reported as not executed, and an order or a stop is reported
  refused only on a documented refusal code; a lost or undocumented answer is looked up by its client id; an opening
  order is never sent twice; after a 429 a close is never sent again by the client and a stop at most once more, each
  looked up first. A stop is reported cancelled only on an explicit record, and confirmed live only from the stop list.
- The drill closes and cancels only what it made, only after its own entry was sent, and cancels a stop only once
  the position reads flat.
- The rate budget is waited out before a request is signed: ``timestamp`` is never stale.
- A position's size, the account equity and the stop list are never read as 0 / flat / empty from a missing or garbled
  field: such an answer is an error. A coin holding a long and a short at once is an error, never netted.
- AI agents never import this module (tests/test_toobit.py checks it).
"""

from __future__ import annotations

import argparse
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
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Callable, Optional

from . import bybit as BY
from . import deepcoin as DC
from . import flipster as FL
from . import mexc as MX
from . import wooxpro as WX
from .livepnl import balanced
from .mainnet import (FLAG, FLAG_VALUE, LIVE_KEY_NAMES as BINANCE_LIVE_KEY_NAMES, MODE_MAINNET, PAPER_ENV_FILE,
                      PAPER_KEY_NAMES, TESTNET_KEY_NAMES as BINANCE_TESTNET_KEY_NAMES, Refused, check_permissions,
                      read_env_file)
from .testnet import (BAD_TIMESTAMP, NOT_FOUND, WOULD_TRIGGER, RateLimited, TestnetError, TransientError, covers,
                      hide_process_memory, live_stops, move_stop, place_stop, round_stop, urllib_send)

SETTLE = "USDT"
SWAP = "-SWAP-"
TOOBIT_BASE = "https://api.toobit.com"
TOOBIT_HOSTS = ("api.toobit.com",)
FUT = "/api/v1/futures"
ORDER = FUT + "/order"
QUOTE = "/quote/v1"
LIVE_KEY_NAMES = ("TOOBIT_LIVE_KEY", "TOOBIT_LIVE_SECRET")
KEY_CHECKED = "TOOBIT_LIVE_KEY_CHECKED"               # the owners' statement: what the API cannot report
KEY_CHECKED_VALUE = "FUTURES_ONLY_NO_WITHDRAW_IP_BOUND"
KEY_FILE = "/etc/paperbot/executor-toobit.env"        # its own key file (deploy/executor-toobit.env.example)
DRILL_CONFIRM = "REAL_ORDER"
DRILL_ORDER_USDT = 6.0                                # the drill's order: $6 or more, two halves of the minimum or more
DRILL_UNIT_MAX_USDT = 40.0                            # the drill prefers a coin whose contract is not 1 coin (it tells
                                                      # the size units apart) while its order costs at most this
DRILL_MIN_GAP_S = 0.5                                 # the drill's requests at least this far apart
DRILL_PAUSE_S = 3.0
TRIGGER_GAP = 0.001                                   # the trigger test's stop: 0.1 % from the last price
TRIGGER_WAIT_S = 1200                                 # ... waited for at most 20 minutes
PROFIT_GAP = 0.0015                                   # first the price is waited for 0.15 % past the entry, so the test
PROFIT_WAIT_S = 600                                   # stop rests on the profit side (a lock's place); at most 10 min
FIXED_LEVERAGE = MX.FIXED_LEVERAGE                    # owners 2026-10-17: BTC 40x, the other coins 30x (the start's
DEFAULT_LEVERAGE = MX.DEFAULT_LEVERAGE                # setting; every entry sets the paper's own leverage first)
COINS = MX.COINS
PREFIX = {MODE_MAINNET: "[투비트 실거래 실행기]"}
RECV_WINDOW = 5000                                    # the docs: 5 s or less recommended

BUY_OPEN, SELL_OPEN, BUY_CLOSE, SELL_CLOSE = "BUY_OPEN", "SELL_OPEN", "BUY_CLOSE", "SELL_CLOSE"
SIDES = (BUY_OPEN, SELL_OPEN, BUY_CLOSE, SELL_CLOSE)
OPEN_SIDE = {"BUY": BUY_OPEN, "SELL": SELL_OPEN}
CLOSE_SIDE = {"SELL": SELL_CLOSE, "BUY": BUY_CLOSE}   # the docs: SELL_CLOSE sells to close a long, BUY_CLOSE buys to
CLOSES = (SELL_CLOSE, BUY_CLOSE)                      # close a short (the drill confirms, see the docstring)
CLOSED_SIDE = {SELL_CLOSE: "LONG", BUY_CLOSE: "SHORT"}
LONG, SHORT = "LONG", "SHORT"
ISOLATED, CROSS = "ISOLATED", "CROSS"
STOP = "STOP"
STOP_KINDS = (STOP, "STOP_LIMIT", "STOP_MARKET")         # a plan order's type (the docs' order stream: STOP_LIMIT)
TPSL_TYPES = ("STOP_LONG_PROFIT", "STOP_LONG_LOSS", "STOP_SHORT_PROFIT", "STOP_SHORT_LOSS", "STOP_PROFIT_LOSS")
# a regular order's statuses (the docs' ENUM) and a stop's ("Plan order or stop loss order status"); both families are
# read for a stop, since the docs do not say which a STOP order's row carries (the drill shows it)
ORDER_FINAL = ("FILLED", "CANCELED", "REJECTED", "EXPIRED")    # the Binance-shaped statuses this client answers
STOP_RESTING = ("ORDER_NEW", "NEW", "PENDING_NEW")
STOP_FIRED = ("ORDER_FILLED", "FILLED", "PARTIALLY_FILLED")
STOP_CANCELED = ("ORDER_CANCELED", "CANCELED")
STOP_FAILED = ("ORDER_REJECTED", "ORDER_FAILED", "REJECTED", "EXPIRED")
STOP_ENDED = STOP_FIRED + STOP_CANCELED + STOP_FAILED
LEVEL_FIELDS = ("stopPrice", "triggerPrice")          # where a STOP row may carry its level (the drill says which)
FLOW_FUNDING, FLOW_TRANSFER = 32, 51                  # balanceFlow flowType: "Fund Fee", transfer
FLOW_NAMES = {10: "수수료", 28: "실현 손익", 32: "펀딩비", 51: "이체", 700: "강제 청산", 701: "ADL"}
ORDER_WAITS = (0.1, 0.2, 0.4, 0.8)                    # a market order is read back again after these (s)
KLINE_ROWS = 1000                                     # GET klines: at most 1000 rows
KLINE_PAGES = 50
PAGE_ROWS = 1000                                      # openOrders, historyOrders, userTrades, balanceFlow: <= 1000 rows
HISTORY_DEPTH = 24                                    # a full page is read again in halves, at most this deep
HISTORY_REQUESTS = 64                                 # ... and with at most this many requests
SETTLE_MS = 25_000                                    # an order sent this long ago is surely in the records
CHILD_AFTER_MS = 60_000                               # a fired stop's order: from 2 s before it fired to 60 s after
SPEC_CACHE_MS = 5_000
# the docs' Error Codes page. Each refuses the request (nothing ran) except the ones named below it
DOCUMENTED_CODES = frozenset((
    -1000, -1001, -1002, -1003, -1006, -1007, -1014, -1015, -1016, -1020, -1021, -1022, -1100, -1101, -1102, -1103,
    -1104, -1105, -1106, -1111, -1112, -1114, -1115, -1116, -1117, -1118, -1119, -1120, -1121, -1125, -1127, -1128,
    -1130, -1132, -1133, -1134, -1135, -1136, -1137, -1138, -1139, -1140, -1141, -1142, -1143, -1144, -1145, -1146,
    -1147, -1193, -1194, -1195, -1196, -1197, -1198, -1199, -1200, -1201, -1202, -1203, -2010, -2011, -2013, -2014,
    -2015, -2016, -3050, -3101, -3102, -3103, -3105, -3107, -3108, -3109, -3110, -3116, -3117, -3120, -3124, -3125,
    -3126, -3127, -3128, -3129, -3130, -3131))
TIME_CODES = (-1021,)                                 # timestamp outside recvWindow: refused, re-synced, sent again
AUTH_CODES = (-1002, -1022, -2014, -2015)             # the key, the signature, the IP, the permissions
RATE_CODES = (-1003, -1015)                           # too many requests / new orders
UNKNOWN_CODES = (-1000, -1001, -1006, -1007, -1146, -1147, -3127)   # "execution status unknown", timeouts
DUPLICATE_CODES = (-1141,)                            # "Duplicate clientOrderId": an order with that id exists
NOT_FOUND_CODES = (-2013,)                            # "Order does not exist."
ENDED_CODES = (-1139, -1142, -1143, -2011)            # a cancel of an order that is no longer open
LOOKUP_TOO_LONG = -1127                               # "Lookup interval is too big": the window is split
KEY_REFUSED = ("AUTH",)                               # the key itself refused: nothing on the account would work
# words read in the message of an undocumented code: on a read only (a write's answer is never guessed from words)
NOT_FOUND_WORDS = ("notfound", "not found", "notexist", "not exist", "does not exist")
RATE_WORDS = ("too many", "frequen", "rate limit", "ratelimit", "limit exceeded")
PLACE_KEYS = frozenset({"order"})                     # POST order: an order or a stop
# request weight per endpoint (the docs' "Weight"; markPrice and accountLeverage name none: 1)
DOC_WEIGHT = {"time": 1, "exchange_info": 1, "klines": 1, "ticker": 1, "mark": 1, "balance": 5, "positions": 5,
              "account_leverage": 1, "margin_type": 1, "leverage": 1, "order": 1, "query": 1, "cancel": 1,
              "open_orders": 1, "history": 5, "trades": 5, "flow": 5, "commission": 5}
DEFAULT_WEIGHT = 5
# the docs' example rateLimits (REQUEST_WEIGHT 3000 a minute, ORDERS 60 a 60 s): exchangeInfo's own numbers replace them
DEFAULT_LIMITS = {"weight": ((60_000, 3000),), "orders": ((60_000, 60),)}
RATE_SHARE = 0.8
READ_RETRIES = 3                                      # a read refused for the rate (429): read again after a pause
READ_PAUSE_S = 1.0
RETRY_AFTER_MAX_S = 60.0                              # a longer Retry-After is not waited inside a request
# writes sent again after a 429 without a look-up: the ones that change nothing when they run twice. An order never is
RETRY_WRITES = frozenset({"margin_type", "leverage", "cancel"})
PROTECT_WAIT_S = 10.0                                 # protective work: every wait inside one call shares this budget
BUDGET_CODE = "PROTECT_BUDGET"
LOOKUP_PAUSE_S = 2.0                                  # after a 429 on a stop or a close: looked up this often
LIST_WAITS = (0.3, 0.7, 1.0, 1.5, 1.5)               # a new stop must show in the stop list within these (5 s)
LEV_WAITS = (0.5, 1.0, 1.5)                           # a setting just made, not read back yet: read again after these
NOT_SENT_WAITS = (0.5, 1.0, 2.0)                      # the checks before an entry failed: tried again after these
UNCONFIRMED = "UNCONFIRMED"                           # a stop of ours the list does not show, no record that it ended
MISMATCH = "LEVERAGE_MISMATCH"                        # the leverage / margin type read back is not the one set (yet)
NOT_SENT = "NOT_SENT"                                 # an opening order not sent: a check before it failed


class RateLimitedUnknown(RateLimited):
    """A stop or a close answered 429 that may still have run, not found by the look-ups the protective budget allowed:
    its outcome stays unknown (looked up again, never "refused")."""


class NotSent(TestnetError):
    """The checks before an opening order is sent (the contract read, the look-up of its client id) failed on every
    try (NOT_SENT_WAITS): nothing went out. A refusal, neither a TransientError nor a RateLimited: the executor drops
    that entry as refused (entry_refused), never holds it as the unknown outcome of an order that was never sent.
    Never raised once the order may have gone out."""


def definite(e: Exception) -> bool:
    """A refusal that says nothing ran: a code of the docs' Error Codes page that refuses the request."""
    return not isinstance(e, (TransientError, RateLimited)) and getattr(e, "tb_code", None) in DOCUMENTED_CODES


def hosts_for(mode: str) -> tuple:
    return TOOBIT_HOSTS                    # one host list: mainnet only


# ---------------------------------------------------------------- numbers and names
def _dec(v, what: str = "value") -> Decimal:
    """A number the decision depends on (a size, a price, the equity): missing or garbled is an error, never 0."""
    if v is None or v == "" or isinstance(v, bool):
        raise TransientError(200, None, f"투비트 응답에 {what} 값이 없습니다")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError) as e:
        raise TransientError(200, None, f"투비트 응답의 {what} 값이 이상합니다: {v!r}") from e
    if not d.is_finite():
        raise TransientError(200, None, f"투비트 응답의 {what} 값이 이상합니다: {v!r}")
    return d


def _soft(v) -> Decimal:
    """A number shown only (a row that is not ours): unreadable -> 0, never an error."""
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return Decimal(0)
    return d if d.is_finite() else Decimal(0)


_f, _num, _int, _price_str, _id60 = MX._f, MX._num, MX._int, MX._price_str, MX._id60

_CID_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
CID_MAX = 32


def ext_id(client_id: Optional[str]) -> str:
    """The newClientOrderId for an executor client id: 1-32 letters and digits (the docs name no length or characters:
    the drill sends 32). An id that fits is kept; any other becomes "pbh" + 29 hex of its SHA-1: deterministic, so a
    look-up after a lost answer or a restart finds the order. None: a fresh id of 32 characters (the drill's)."""
    if client_id is None:
        return "pb" + hashlib.sha1(f"{time.time_ns()}|{os.getpid()}".encode()).hexdigest()[:CID_MAX - 2]
    if 0 < len(client_id) <= CID_MAX and set(client_id) <= _CID_OK:
        return client_id
    return "pbh" + hashlib.sha1(client_id.encode()).hexdigest()[:CID_MAX - 3]


def tb(symbol: str) -> str:
    """BTCUSDT -> BTC-SWAP-USDT."""
    if not symbol.endswith(SETTLE) or len(symbol) <= len(SETTLE):
        raise TestnetError(400, "NO_SYMBOL", f"{symbol}: USDT 무기한 이름이 아닙니다")
    return f"{symbol[:-len(SETTLE)]}{SWAP}{SETTLE}"


def bn(symbol_id) -> str:
    """BTC-SWAP-USDT -> BTCUSDT; anything that is not a USDT-M perpetual (BTC-SWAP, a spot pair) -> ""."""
    s = str(symbol_id or "")
    tail = f"{SWAP}{SETTLE}"
    return s[:-len(tail)] + SETTLE if s.endswith(tail) and len(s) > len(tail) else ""


def to_ms(v, what: str = "time") -> int:
    """A Toobit time (ms per the docs, often a string; one in seconds is read as such) -> ms. 0 stays 0."""
    n = int(_dec(v, what))
    if n > 10 ** 14:
        return n // 1_000
    if n > 10 ** 11 or n == 0:
        return n
    return n * 1000


def query_string(params: dict) -> str:
    """The parameters exactly as sent and signed (in the given order, URL-encoded; booleans as true/false)."""
    items = []
    for k, v in params.items():
        if v is None:
            continue
        if v is True or v is False:
            v = "true" if v else "false"
        items.append((k, str(v)))
    return urllib.parse.urlencode(items, quote_via=urllib.parse.quote)


def signature(secret: str, payload: str) -> str:
    """hex HMAC-SHA256(secret, the query string followed by the request body) (the docs' SIGNED endpoint security)."""
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def side_of(row: dict) -> str:
    """A Toobit order or fill side (BUY_OPEN, SELL_OPEN, BUY_CLOSE, SELL_CLOSE); anything else is an error."""
    side = str(row.get("side") or "").upper()
    if side not in SIDES:
        raise TransientError(200, None, f"주문 방향이 이상합니다(side {row.get('side')!r})")
    return side


def bin_side(side: str) -> str:
    return "BUY" if side.startswith("BUY") else "SELL"


def mx_code(side: str) -> int:
    """Toobit side -> paperbot/mexc.py's side code (1 open long, 2 close short, 3 open short, 4 close long)."""
    return {BUY_OPEN: MX.OPEN_LONG, BUY_CLOSE: MX.CLOSE_SHORT, SELL_OPEN: MX.OPEN_SHORT,
            SELL_CLOSE: MX.CLOSE_LONG}[side]


TB_SIDE = {MX.OPEN_LONG: BUY_OPEN, MX.CLOSE_SHORT: BUY_CLOSE, MX.OPEN_SHORT: SELL_OPEN, MX.CLOSE_LONG: SELL_CLOSE}


def margin_word(v) -> str:
    """ISOLATED / CROSS (the docs also write CROSSED); anything else ""."""
    s = str(v or "").upper()
    return ISOLATED if s == ISOLATED else CROSS if s in ("CROSS", "CROSSED") else ""


def fills_from_rows(rows: list, ct_val, symbol: str) -> list:
    """Toobit fills (GET /api/v1/futures/userTrades) -> Binance userTrades-like fills. Each closing fill carries
    Toobit's own ``realizedPnl`` (realizedSource "pnl"). It is checked against the P&L replayed from the fills' own
    prices (paperbot/mexc.py fills_from_deals) per closing order when the list holds its opening fills too: more apart
    than 0.01 + 0.02 % of the closed notional marks the order's fills ``realizedCheck`` "mismatch" (a sign, a size, or a
    P&L net of fees: the executor keeps the wallet estimate and alerts). Without a realizedPnl the replay stands when it
    knows the entry ("unchecked"), else the fill is "unknown" and "mismatch": never a final 0."""
    deals = []
    for r in rows:
        side = side_of(r)
        oid = str(r.get("orderId") or "")
        if not oid or r.get("id") in (None, ""):
            raise TransientError(200, None, f"{symbol}: 체결에 주문 번호나 체결 번호가 없습니다")
        code = mx_code(side)
        pnl = r.get("realizedPnl") if side in CLOSES else None
        deals.append({"id": str(r.get("id")), "orderId": oid, "vol": r.get("qty"), "price": r.get("price"),
                      "side": code, "timestamp": to_ms(r.get("time"), "time"),
                      "profit": None if pnl in (None, "") else _num(_dec(pnl, "realizedPnl")),
                      "fee": _dec(r.get("commission"), "commission"),
                      "feeCurrency": r.get("commissionAsset") or SETTLE, "isTaker": r.get("isMaker") is False})
    out = MX.fills_from_deals(deals, ct_val, symbol)
    by: dict = {}
    for f in out:
        f["tbSide"] = TB_SIDE.get(f.pop("mexcSide"))
        f["tbPnl"] = f.pop("mexcProfit")
        f.pop("vol", None)
        if f["realizedSource"] != "open":
            by.setdefault(str(f["orderId"]), []).append(f)
    for fs in by.values():
        theirs = None if any(f["tbPnl"] is None for f in fs) else sum(Decimal(f["tbPnl"]) for f in fs)
        known = all(f["realizedSource"] == "replay" for f in fs)
        ours = sum(Decimal(f["realizedPnl"]) for f in fs)
        notional = sum(Decimal(f["closedSize"]) * Decimal(f["price"]) for f in fs)
        if theirs is not None:
            bad = known and abs(ours - theirs) > Decimal("0.01") + Decimal("0.0002") * notional
        for f in fs:
            if theirs is not None:
                f["replayPnl"] = f["realizedPnl"] if known else None
                f["realizedPnl"], f["realizedSource"] = f["tbPnl"], "pnl"
                f["realizedCheck"] = ("mismatch" if bad else "ok") if known else "pnl"
            elif known:
                f["realizedCheck"] = "unchecked"
            else:
                f["realizedPnl"], f["realizedSource"], f["realizedCheck"] = "0", "unknown", "mismatch"
    return out


def lot_unit(step: Decimal, ct: Decimal) -> tuple:
    """How LOT_SIZE reads: ("contracts", step) when stepSize is a whole number, else ("base", stepSize / multiplier)
    which must be a whole number of contracts (``quantity`` is a LONG). Anything else: BAD_SPEC."""
    if step >= 1 and step == step.to_integral_value():
        return "contracts", step
    n = step / ct
    if n >= 1 and n == n.to_integral_value():
        return "base", n
    raise TestnetError(400, "BAD_SPEC", f"수량 단위(stepSize {step}, contractMultiplier {ct})가 계약으로도 코인으로도 "
                                        "맞지 않습니다")


def min_order_text(sp: dict) -> str:
    """The smallest order in words; missing: said plainly (that coin takes no new entry)."""
    if sp.get("problem"):
        return f"없음 → 새 진입 안 함({sp.get('problem')})"
    return f"{sp['min_sz']}계약 = {sp['min_qty']:g}"


def permission_record(attested: bool, account_read: bool) -> dict:
    """The Binance apiRestrictions fields mainnet.check_permissions reads. Toobit's futures API reports no key
    permissions: reading the futures account is what this key was seen to do; "futures trade only, no withdrawal, server
    IP bound" is the owners' statement (``attested``), never assumed."""
    extra = []
    if not attested:
        extra.append(f"투비트는 키 권한을 API로 알려 주지 않습니다. 키를 '선물 거래만, 출금 없음, 서버 IP만'으로 만든 것을 "
                     f"확인한 뒤 {KEY_FILE}에 {KEY_CHECKED}={KEY_CHECKED_VALUE} 를 넣으세요")
    return {
        "enableReading": bool(account_read),
        "enableWithdrawals": False if attested else None,
        "enableFutures": bool(account_read and attested),
        "ipRestrict": True if attested else None,
        "extraProblems": extra,
        "warnings": [f"투비트는 키 권한을 API로 알려 주지 않습니다. 확인한 것: 선물 계정 읽기. 선물 거래 권한·출금 없음·서버 "
                     f"IP 제한은 두 분이 확인한 내용({KEY_CHECKED})입니다"] if attested else [],
        "attested": attested,
    }


# ---------------------------------------------------------------- client
class ToobitClient:
    """Signed REST client for Toobit USDT-M perpetuals, real money only. Answers are translated into the Binance
    client's shapes (see the module docstring)."""
    __test__ = False
    HOSTS: tuple = TOOBIT_HOSTS
    DEFAULT_BASE = TOOBIT_BASE
    KEY_NAMES = LIVE_KEY_NAMES
    AGENT = "paperbot-toobit-live/0.1"
    EXCHANGE = "toobit"
    PNL_RECORD = "투비트 체결의 realizedPnl"
    # a stop bigger than the position is replaced by one of the position's size (the executor's _cover)
    EXACT_STOP_SIZE = True
    # the executor adds a random part to its stop and close ids: Toobit takes an id again once its order ended
    UNIQUE_CLIENT_IDS = True

    def __init__(self, api_key: str, api_secret: str, base: Optional[str] = None, send=None,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                 on_request: Optional[Callable[[dict], None]] = None, sleep: Callable[[float], None] = time.sleep,
                 public_only: bool = False):
        base = (base or self.DEFAULT_BASE).rstrip("/")
        u = urllib.parse.urlparse(base)
        host = u.hostname or ""
        if host not in type(self).HOSTS or u.scheme != "https" or u.path not in ("",) or u.port not in (None, 443):
            raise ValueError(f"refusing {base!r}: {type(self).__name__} only talks to https://{type(self).HOSTS}")
        if not public_only and not (api_key and api_secret):
            raise ValueError(f"{self.KEY_NAMES[0]} and {self.KEY_NAMES[1]} are required")
        self.base, self.host, self.key, self.secret = base, host, api_key, api_secret
        self.public_only = public_only
        self.send = send or urllib_send
        self.clock_ms = clock_ms
        self.sleep = sleep
        self.offset_ms = 0
        self.time_source = "local"
        self.on_request = on_request
        self.specs: dict = {}            # BTCUSDT -> spec (live contracts, cached)
        self.spec_problems: dict = {}    # BTCUSDT -> why its contract row cannot be traded at all (BAD_SPEC)
        self.spec_ms: Optional[int] = None
        self.limits: dict = {k: tuple(v) for k, v in DEFAULT_LIMITS.items()}   # bucket -> ((window ms, limit), ...)
        self.limits_source = "docs example"
        self.hits: dict = {}             # bucket -> [(ms, weight)] in its longest window
        self.rate_answers = 0            # 429 answers seen (the drill reports them)
        self.order_symbol: dict = {}     # orderId (orders and stops) -> symbol
        self.sent: dict = {}             # client id -> {"symbol", "first", "last", "reduce_only"} sent by this process
        self.own_oids: dict = {}         # orderId -> symbol of each order this process placed
        self.stop_intents: dict = {}     # a stop's client id -> what was sent (symbol, side, sz, trig, times, sends)
        self.stop_by_cid: dict = {}      # client id -> stop orderId (answers we got, or found by a look-up)
        self.cid_by_stop: dict = {}
        self.list_delay_ms: dict = {}    # stop orderId -> ms until the stop list showed it (the drill reports it)
        self.level_field: dict = {}      # stop orderId -> the field its level was read from (the drill reports it)
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

    def _buckets(self, key: str) -> list:
        """(bucket, window ms, budget, weight) for each limit a request counts against: the request weight; a new order
        (POST order) also the ORDERS limit."""
        w = DOC_WEIGHT.get(key, DEFAULT_WEIGHT)
        out = [("weight", win, max(1, int(lim * RATE_SHARE)), w) for win, lim in self.limits["weight"]]
        if key in PLACE_KEYS:
            out += [("orders", win, max(1, int(lim * RATE_SHARE)), 1) for win, lim in self.limits["orders"]]
        return out

    def _recent(self, bucket: str, window_ms: int) -> list:
        now = self.clock_ms()
        return [(t, w) for t, w in self.hits.get(bucket, []) if now - t < window_ms]

    def _pace(self, key: str) -> None:
        """Never past the budget: wait until enough of the window's weight leaves it. Protective work never waits for
        this self-imposed budget (the 20 % headroom is for it); a 429 the exchange answers is handled where it comes."""
        for bucket, window, budget, w in self._buckets(key):
            hits = sorted(self._recent(bucket, window))
            used = sum(x for _, x in hits)
            if used + w <= budget or self.deadline is not None:
                continue
            need, acc, until = used + w - budget, 0, None
            for t, x in hits:
                acc += x
                if acc >= need:
                    until = t + window
                    break
            wait = min(((until or self.clock_ms()) - self.clock_ms()) / 1000.0, window / 1000.0)
            if wait > 0:
                self.sleep(wait)
        longest = {}
        for bucket, window, _budget, w in self._buckets(key):
            longest[bucket] = (max(window, longest.get(bucket, (0, 0))[0]), w)
        for bucket, (window, w) in longest.items():
            self.hits[bucket] = self._recent(bucket, window) + [(self.clock_ms(), w)]

    def throttle_s(self, share: float = 0.8) -> float:
        """Seconds to wait before the next loop: a window that used ``share`` of its budget waits for its oldest
        request to leave it."""
        now = self.clock_ms()
        wait = 0.0
        for bucket, lims in self.limits.items():
            for window, lim in lims:
                budget = max(1, int(lim * RATE_SHARE))
                recent = self._recent(bucket, window)
                if recent and sum(w for _, w in recent) >= share * budget:
                    wait = max(wait, (min(t for t, _ in recent) + window - now) / 1000.0)
        return max(0.0, min(wait, 60.0))

    def req(self, method: str, path: str, params=None, signed: bool = True, limit_key: Optional[str] = None):
        """One request; returns the parsed answer. A read (GET) refused for the rate (429) is read again after its
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
        key = limit_key or path
        params = {k: v for k, v in (params or {}).items() if v is not None}
        audit = {"method": method, "path": path, "params": dict(params)}
        headers = {"User-Agent": self.AGENT, "Accept": "application/json"}
        # the budget first (it can wait up to a minute), then the timestamp and the signature: never sent stale
        self._pace(key)
        if signed:
            params.update(recvWindow=RECV_WINDOW, timestamp=self._now())
        q = query_string(params)
        if signed:
            q = (q + "&" if q else "") + "signature=" + signature(self.secret, q)
            headers["X-BB-APIKEY"] = self.key
        if method == "POST":
            target, body = path, q.encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            target, body = (f"{path}?{q}" if q else path), None
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
            parsed = True
        except ValueError:
            data, parsed = None, False
        code = data.get("code") if isinstance(data, dict) else None
        try:
            code = None if code is None else int(code)
        except (TypeError, ValueError):
            code = str(code)
        failed = code is not None and code not in (0, 200)
        msg = str((data.get("msg") if isinstance(data, dict) else None) or (raw or b"")[:200])
        # an order or a stop: refused only on a documented refusal code; any other answer may have run
        placing = method == "POST" and key in PLACE_KEYS
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
        elif failed:
            err = self._error(code, msg, status, read=method == "GET", placing=placing)
        elif status in (403, 418) and placing:
            # whether a blocked order reached the exchange is not said: looked up, never "nothing ran"
            err = TransientError(status, code, f"HTTP {status} (차단·허용 안 된 IP), 주문 결과 모름: {msg}"[:300])
        elif status in (403, 418):
            # a firewall block or a ban: never retried in the request, the loop waits (the executor's 418 handling)
            err = RateLimited(418, code, f"HTTP {status} (차단·허용 안 된 IP): {msg}"[:300], 300.0)
        elif status != 200:
            err = (TransientError if placing else TestnetError)(status, code, msg[:300])
        elif not parsed or data is None:
            err = TransientError(status, None, f"응답이 투비트 형식(JSON)이 아닙니다: {msg}"[:200])
        self._audit(audit, status=status, data=data, err=err)
        if err is not None:
            raise err
        return data

    def _error(self, code, msg: str, status: int, read: bool = True, placing: bool = False) -> TestnetError:
        """A ``code`` that is not 0 / 200. The Error Codes page's refusals refuse the request (nothing ran); its
        "status unknown" codes, its rate codes, a duplicate id on an order and any code it does not list are not a
        refusal of an order or a stop (``placing``): an unknown outcome (looked up by the client id), never a clock
        refusal sent again. Only a read (GET) reads words in the message (a rate word: 429; "not exist": not found)."""
        text = f"{msg} (투비트 code {code})"
        low = msg.lower().replace("_", " ")
        if code in TIME_CODES:
            err = TestnetError(400, BAD_TIMESTAMP, text)        # refused, not executed: re-sync and send again
        elif code in AUTH_CODES:
            err = TestnetError(401, "AUTH", f"키·서명·IP·권한이 거절됐습니다({text}). 키에 묶인 IP가 이 서버인지, 선물 거래 "
                                            "권한이 있는지 확인하세요")
        elif code in RATE_CODES:
            self.rate_answers += 1
            err = RateLimited(429, code, text, 1.0)
        elif code in UNKNOWN_CODES:
            err = TransientError(status if status and status != 200 else 0, code,
                                 f"처리 결과를 모른다는 답입니다(들어갔는지 모름, 찾아봅니다): {text}"[:300])
        elif code in DUPLICATE_CODES and placing:
            err = TransientError(status, code, f"같은 번호의 주문이 이미 있습니다(찾아봅니다): {text}"[:300])
        elif code in NOT_FOUND_CODES:
            err = TestnetError(404, NOT_FOUND[0], text)
        elif code in DOCUMENTED_CODES:
            err = TestnetError(status if status and status != 200 else 400, code, text)      # refused: nothing ran
        elif placing:
            err = TransientError(status, code, f"주문에 문서에 없는 답이 왔습니다(들어갔는지 모름, 찾아봅니다): {text}"[:300])
        elif read and any(w in low for w in RATE_WORDS):
            self.rate_answers += 1
            err = RateLimited(429, code, text, 1.0)
        elif read and any(w.replace(" ", "") in low.replace(" ", "") for w in NOT_FOUND_WORDS):
            err = TestnetError(404, NOT_FOUND[0], text)
        else:
            err = TestnetError(status if status and status != 200 else 400, code, text)
        err.tb_code = code
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

    @staticmethod
    def _need(row: dict, key: str, what: str):
        v = row.get(key)
        if v in (None, ""):
            raise TransientError(200, None, f"{what}에 {key} 값이 없습니다")
        return v

    # ------------------------------------------------------------ market data
    def sync_time(self) -> int:
        """The server clock (GET /api/v1/time, ms): ``timestamp`` is counted on it. A refused answer: the local clock
        (chrony); a garbled one is an error."""
        t0 = self.clock_ms()
        try:
            data = self.req("GET", "/api/v1/time", signed=False, limit_key="time")
        except (TransientError, RateLimited):
            raise
        except TestnetError:
            self.offset_ms, self.time_source = 0, "local"
            return 0
        t1 = self.clock_ms()
        server = to_ms((data or {}).get("serverTime") if isinstance(data, dict) else None, "serverTime")
        self.offset_ms = server - (t0 + t1) // 2
        self.time_source = "/api/v1/time"
        return self.offset_ms

    def _load_instruments(self) -> None:
        now = self.clock_ms()
        if self.spec_ms is not None and now - self.spec_ms < SPEC_CACHE_MS:
            return
        data = self.req("GET", "/api/v1/exchangeInfo", signed=False, limit_key="exchange_info")
        if not isinstance(data, dict):
            raise TransientError(200, None, f"상품 정보 응답이 이상합니다: {str(data)[:80]!r}")
        rows = self._rows(data.get("contracts"), "상품 정보(contracts)")
        self._read_limits(data.get("rateLimits"))
        self.spec_ms = now
        for row in rows:
            sym = bn(row.get("symbol"))
            if not sym or row.get("inverse") is True or str(row.get("marginToken") or SETTLE) != SETTLE:
                continue
            try:
                self.specs[sym] = self._spec_row(row)
                self.spec_problems.pop(sym, None)
            except TestnetError as e:                       # a contract with missing or garbled units: never traded
                self.specs.pop(sym, None)
                self.spec_problems[sym] = e.msg

    def _read_limits(self, rows) -> None:
        """exchangeInfo rateLimits: REQUEST_WEIGHT and ORDERS, each (interval x intervalUnit, limit). Unreadable: the
        docs' example numbers stay."""
        if not isinstance(rows, list):
            return
        got: dict = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            unit_ms = {"SECOND": 1_000, "MINUTE": 60_000, "HOUR": 3_600_000, "DAY": 86_400_000}.get(
                str(r.get("interval") or "").upper())
            try:
                window, lim = unit_ms * int(r.get("intervalUnit") or 1), int(r.get("limit"))
            except (TypeError, ValueError):
                continue
            if window <= 0 or lim <= 0:
                continue
            kind = str(r.get("rateLimitType") or "").upper()
            bucket = "weight" if kind in ("REQUEST_WEIGHT", "REQUESTS_WEIGHT") else "orders" if kind == "ORDERS" \
                else None
            if bucket:
                got.setdefault(bucket, []).append((window, lim))
        for bucket, lims in got.items():
            self.limits[bucket] = tuple(lims)
        if got:
            self.limits_source = "exchangeInfo"

    @staticmethod
    def _spec_row(row: dict) -> dict:
        """The units a stop and a close need (contractMultiplier, tickSize, stepSize) must be there: missing or garbled,
        the coin cannot be used (BAD_SPEC). What only a NEW entry needs (minQty, maxQty, a garbled minNotional) is never
        read as 0: missing, the spec carries ``problem`` and the coin refuses new entries with that reason, while a
        position on it is still protected and closed. No MIN_NOTIONAL filter: no minimum value (0). The maximum leverage
        is 1 / the first risk tier's initialMargin (None when the row has none: the leverage setting decides)."""
        filters = {f.get("filterType"): f for f in row.get("filters") or [] if isinstance(f, dict)}
        lot = filters.get("LOT_SIZE") or {}
        ct = _dec(row.get("contractMultiplier"), "contractMultiplier")
        tick = _dec((filters.get("PRICE_FILTER") or {}).get("tickSize"), "tickSize")
        step = _dec(lot.get("stepSize"), "stepSize")
        if ct <= 0 or tick <= 0 or step <= 0:
            raise TestnetError(400, "BAD_SPEC", f"{row.get('symbol')}: 계약 단위 정보가 이상합니다")
        unit, step_c = lot_unit(step, ct)
        problems, vals = [], {}
        for k, rounding in (("minQty", ROUND_CEILING), ("maxQty", ROUND_FLOOR)):
            try:
                v = _dec(lot.get(k), k)
                c = (v if unit == "contracts" else v / ct).to_integral_value(rounding=rounding)
                if c <= 0:
                    raise TransientError(200, None, f"투비트 응답의 {k} 값이 이상합니다: {v}")
                vals[k] = c
            except TestnetError as e:
                problems.append(e.msg)
        min_notional = Decimal(0)
        if "MIN_NOTIONAL" in filters:
            try:
                min_notional = _dec(filters["MIN_NOTIONAL"].get("minNotional"), "minNotional")
            except TestnetError as e:
                problems.append(e.msg)
        max_lev = None
        tiers = [t for t in row.get("riskLimits") or [] if isinstance(t, dict)]
        if tiers:
            im = _soft(tiers[0].get("initialMargin"))
            if im > 0:
                max_lev = float((1 / im).to_integral_value(rounding=ROUND_FLOOR))
        mn = vals.get("minQty")
        mn = max(mn, step_c) if mn is not None else None
        status = str(row.get("status") or "")
        return {"qty_step": float(ct * step_c), "min_qty": float(ct * (mn if mn is not None else step_c)),
                "tick": float(tick), "min_notional": float(min_notional), "problem": "; ".join(problems) or None,
                "max_leverage": max_lev, "status": "Trading" if status == "TRADING" else (status or "?"),
                "tradable": status == "TRADING", "ct_val": _num(ct), "lot_sz": _num(step_c),
                "min_sz": _num(mn) if mn is not None else None,
                "max_sz": _num(vals["maxQty"]) if "maxQty" in vals else None, "tick_str": _num(tick),
                "qty_step_str": _num(ct * step_c), "base_coin": row.get("underlying") or row.get("baseAssetName"),
                "inst_id": row.get("symbol"), "lot_unit": unit,
                "raw_lot": {k: lot.get(k) for k in ("stepSize", "minQty", "maxQty")}}

    def _no_entries(self, symbol: str) -> None:
        """A coin whose contract row lacks what a new entry needs takes no new entry (a clear reason, never a 0). The
        list is read again first (at most every 5 s): a value that came back lifts it."""
        if not self._spec(symbol).get("problem"):
            return
        self._load_instruments()
        problem = self._spec(symbol).get("problem")
        if problem:
            raise TestnetError(400, "BAD_SPEC", f"{symbol}: 투비트 상품 정보에 새 진입에 필요한 값이 없어 새 진입을 하지 "
                                                f"않습니다({problem}). 열린 포지션의 손절·청산은 그대로 합니다")

    def spec(self, symbol: str) -> dict:
        """The contract's live spec (cached): sizes in base units for the executor (qty_step = multiplier x step,
        min_qty = multiplier x the smallest order, tick), the raw contract units. Missing units: TestnetError BAD_SPEC
        naming the field; a missing entry-only value: a spec with ``problem`` (no new entries; specs and check print
        it)."""
        if symbol not in self.specs:
            self._load_instruments()
        if symbol not in self.specs and symbol in self.spec_problems:
            raise TestnetError(400, "BAD_SPEC", f"{symbol}: 투비트 상품 정보가 이상해 거래하지 않습니다: "
                                                f"{self.spec_problems[symbol]}")
        if symbol not in self.specs:
            raise TestnetError(400, "NO_SYMBOL", f"{symbol}: 투비트 USDT 무기한 상품에 없습니다")
        return dict(self.specs[symbol])

    def _spec(self, symbol: str) -> dict:
        return self.specs.get(symbol) or self.spec(symbol)

    def _contracts(self, symbol: str, qty: float) -> Decimal:
        """A base quantity -> whole contracts on the step, floored."""
        sp = self._spec(symbol)
        step = Decimal(sp["ct_val"]) * Decimal(sp["lot_sz"])
        n = (Decimal(repr(float(qty))) / step + Decimal("1e-9")).to_integral_value(rounding=ROUND_FLOOR)
        return n * Decimal(sp["lot_sz"])

    def _base(self, symbol: str, contracts) -> Decimal:
        return _dec(contracts, "quantity") * Decimal(self._spec(symbol)["ct_val"])

    def _check_size(self, symbol: str, sz: Decimal, qty: float, what: str, entry: bool) -> None:
        sp = self._spec(symbol)
        if sz <= 0:
            raise TestnetError(400, "QTY_ZERO", f"{symbol}: {what} 수량 {qty}이 최소 단위 {sp['qty_step_str']}보다 "
                                                "작습니다")
        if entry and sp.get("min_sz") and sz < Decimal(sp["min_sz"]):
            raise TestnetError(400, "QTY_MIN", f"{symbol}: {what} {_num(sz)}계약이 최소 {sp['min_sz']}계약보다 작습니다")
        if entry and sp.get("max_sz") and sz > Decimal(sp["max_sz"]):
            raise TestnetError(400, "QTY_MAX", f"{symbol}: {what} {_num(sz)}계약이 한 번 최대 {sp['max_sz']}계약을 넘습니다")

    @staticmethod
    def _one(data, symbol: str, keys: tuple, what: str) -> dict:
        """The row of ``symbol`` in a public answer (a list or one object): its symbol field (any of ``keys``) is the
        contract's name or the plain one (BTC-SWAP-USDT or BTCUSDT); a single row without one answers our query."""
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else None
        if rows is None or not all(isinstance(r, dict) for r in rows):
            raise TransientError(200, None, f"{symbol}: {what} 응답이 이상합니다: {str(data)[:80]!r}")
        named = [r for r in rows if any(r.get(k) in (tb(symbol), symbol) for k in keys)]
        if named:
            return named[0]
        if len(rows) == 1 and not any(rows[0].get(k) for k in keys):
            return rows[0]
        raise TransientError(200, None, f"{symbol}: {what}이(가) 비어 있습니다")

    def price(self, symbol: str) -> float:
        """Last traded price (GET /quote/v1/contract/ticker/price ``p``): what the paper judges stops on."""
        data = self.req("GET", QUOTE + "/contract/ticker/price", {"symbol": tb(symbol)}, signed=False,
                        limit_key="ticker")
        return float(_dec(self._one(data, symbol, ("s", "symbol"), "시세").get("p"), "p"))

    def mark(self, symbol: str) -> float:
        data = self.req("GET", QUOTE + "/markPrice", {"symbol": tb(symbol)}, signed=False, limit_key="mark")
        return float(_dec(self._one(data, symbol, ("symbolId", "symbol"), "마크 가격").get("price"), "price"))

    def klines(self, symbol: str, start_ms: int, end_ms: int) -> list:
        """1m candles of the last price opened in [start_ms, end_ms], the one still forming included: [(open ms, high,
        low, close)], oldest first. GET /quote/v1/klines reads forward from startTime, at most 1000 rows; a page that
        does not move forward stops the read (never an endless loop)."""
        lo = int(start_ms) - int(start_ms) % 60_000
        end = int(end_ms)
        out = {}
        cursor = lo
        for _ in range(KLINE_PAGES):
            n = int(min(KLINE_ROWS, max(2, (end - cursor) // 60_000 + 2)))
            rows = self.req("GET", QUOTE + "/klines", {"symbol": tb(symbol), "interval": "1m", "startTime": cursor,
                                                        "endTime": end, "limit": n}, signed=False, limit_key="klines")
            if not isinstance(rows, list):
                raise TransientError(200, None, f"{symbol}: 1분봉 응답이 목록이 아닙니다 {str(rows)[:80]!r}")
            newest = None
            for r in rows:
                if not isinstance(r, (list, tuple)) or len(r) < 5:
                    raise TransientError(200, None, f"{symbol}: 1분봉 응답의 모양이 다릅니다")
                ms = to_ms(r[0], "kline time")
                newest = ms if newest is None else max(newest, ms)
                if lo <= ms <= end:
                    out[ms] = (ms, float(_dec(r[2], "high")), float(_dec(r[3], "low")), float(_dec(r[4], "close")))
            if newest is None or len(rows) < n or newest + 60_000 > end or newest < cursor:
                break
            cursor = newest + 60_000
        return [out[k] for k in sorted(out)]

    def leverage_brackets(self) -> list:
        """Signal mode needs Binance-like notional brackets: not offered (the executor follows the paper position)."""
        raise TestnetError(400, "NO_BRACKETS", "투비트는 빠른 진입(signal) 크기 계산용 레버리지 구간을 주지 않습니다")

    # ------------------------------------------------------------ account
    def account(self) -> dict:
        """GET /api/v1/futures/balance: the USDT row's ``balance`` (the wallet: unrealized P&L is not in it),
        availableBalance, positionMargin; the unrealized P&L is crossUnRealizedPnl plus the isolated positions' own
        unrealizedPnL (GET positions), and equity = wallet + it. Never $0 from a gap. Other assets: the assets list."""
        rows = self._rows(self.req("GET", FUT + "/balance", limit_key="balance"), "잔고")
        usdt = next((r for r in rows if r.get("asset") == SETTLE), None)
        if usdt is None:          # never read as $0 (a daily-loss halt would close everything)
            raise TransientError(200, None, "잔고 응답에 USDT 줄이 없습니다")
        wallet = _dec(usdt.get("balance"), "balance")
        cross = _dec(usdt.get("crossUnRealizedPnl") if usdt.get("crossUnRealizedPnl") not in (None, "") else "0",
                     "crossUnRealizedPnl")
        iso = Decimal(0)
        for r in self._position_rows(None):
            if margin_word(r.get("marginType")) != CROSS:
                iso += _dec(r.get("unrealizedPnL"), "unrealizedPnL")
        unreal = cross + iso
        assets = [{"asset": SETTLE, "walletBalance": _num(wallet)}]
        for r in rows:
            if r.get("asset") not in (None, "", SETTLE) and _f(r.get("balance")) > 0:
                assets.append({"asset": str(r.get("asset")), "walletBalance": str(r.get("balance"))})
        return {"totalWalletBalance": _num(wallet), "totalUnrealizedProfit": _num(unreal),
                "totalMarginBalance": _num(wallet + unreal),
                "availableBalance": _num(_dec(usdt.get("availableBalance"), "availableBalance")),
                "positionMargin": str(usdt.get("positionMargin") or "0"), "orderMargin": str(usdt.get("orderMargin")
                                                                                             or "0"),
                "assets": assets}

    def fee_rate(self, symbol: Optional[str] = None) -> dict:
        """GET /api/v1/futures/commissionRate: opening and closing, maker and taker. ``taker`` / ``maker``: the larger
        of the two (what a round trip is charged at most per side)."""
        data = self.req("GET", FUT + "/commissionRate", {"symbol": tb(symbol or "BTCUSDT")}, limit_key="commission")
        if not isinstance(data, dict):
            raise TransientError(200, None, f"수수료율 응답이 이상합니다: {str(data)[:80]!r}")
        got = {k: float(_dec(data.get(k), k)) for k in ("openTakerFee", "closeTakerFee", "openMakerFee",
                                                         "closeMakerFee")}
        return {"taker": max(got["openTakerFee"], got["closeTakerFee"]),
                "maker": max(got["openMakerFee"], got["closeMakerFee"]), "open_taker": got["openTakerFee"],
                "close_taker": got["closeTakerFee"], "open_maker": got["openMakerFee"],
                "close_maker": got["closeMakerFee"]}

    def one_way(self) -> None:
        """The executor's Binance assumption: one net position per coin. Toobit's sides open and close each side of a
        two-way account; this client's orders always name the side. Checked here: no coin holds a long and a short at
        once; otherwise Refused (the executor does not start: clear it in the app)."""
        try:
            self._position_rows(None)
        except TransientError as e:
            if getattr(e, "tb_mixed", False):
                raise Refused(f"투비트에 한 코인 롱·숏이 같이 있어 거래하지 않습니다: {e.msg}. 앱에서 정리한 뒤 다시 켜세요") from e
            raise
        self.one_side = True

    def _lev_info(self, symbol: str) -> tuple:
        """GET /api/v1/futures/accountLeverage?symbol=: (leverage, margin type) of the coin, with or without a
        position."""
        data = self.req("GET", FUT + "/accountLeverage", {"symbol": tb(symbol)}, limit_key="account_leverage")
        if isinstance(data, dict) and "data" in data and not data.get("symbol"):
            data = data.get("data")
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else None
        if not rows or not all(isinstance(r, dict) for r in rows):
            raise TransientError(200, None, f"{symbol}: 레버리지 응답이 이상합니다: {str(data)[:80]!r}")
        row = next((r for r in rows if r.get("symbol") in (tb(symbol), symbol)), None)
        if row is None and len(rows) == 1 and not rows[0].get("symbol"):
            row = rows[0]
        if row is None:
            raise TransientError(200, None, f"{symbol}: 레버리지 응답에 이 코인이 없습니다")
        return int(_dec(row.get("leverage"), "leverage")), margin_word(row.get("marginType"))

    def _setting(self, path: str, body: dict, key: str) -> Optional[TestnetError]:
        """A setting (marginType / leverage). Refused only on a documented code (raised); an undocumented answer may
        have set it: returned, and the read-back decides."""
        try:
            self.req("POST", path, body, limit_key=key)
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            if definite(e) or e.code in ("AUTH", BAD_TIMESTAMP):
                raise
            return e
        return None

    def _read_back(self, symbol: str, ok: Callable[[tuple], bool], what: str, answer) -> None:
        got = self._lev_info(symbol)
        for w in LEV_WAITS:
            if ok(got):
                return
            self._wait(w)
            got = self._lev_info(symbol)
        if not ok(got):
            raise TransientError(200, MISMATCH, f"{symbol}: {what}로 맞춘 것을 확인하지 못했습니다(읽은 값 {got[0]}배 "
                                                f"{got[1] or '?'}" + (f", 답 {answer.msg}" if answer is not None else "")
                                 + ")")

    def _set_leverage(self, symbol: str, lev: int) -> None:
        """Isolated margin, then ``lev``, each read back; already so: nothing is sent. The read-back can lag the answer:
        it is read again after LEV_WAITS (3 s). Refused only on a documented code; still another value after the waits:
        TransientError LEVERAGE_MISMATCH (tried again later), never a refusal."""
        cur, mode = self._lev_info(symbol)
        if mode != ISOLATED:
            answer = self._setting(FUT + "/marginType", {"symbol": tb(symbol), "marginType": ISOLATED}, "margin_type")
            self._read_back(symbol, lambda g: g[1] == ISOLATED, "격리(ISOLATED)", answer)
            cur, mode = self._lev_info(symbol)
        if cur == lev:
            return
        answer = self._setting(FUT + "/leverage", {"symbol": tb(symbol), "leverage": int(lev)}, "leverage")
        self._read_back(symbol, lambda g: g == (lev, ISOLATED), f"격리 {lev}배", answer)

    def isolated(self, symbol: str) -> None:
        """Isolated margin with the owners' leverage (BTC 40x, others 30x), read back. A position open on the symbol:
        TestnetError -4048 unless it is isolated already (the executor warns and keeps protecting it). The key refused
        (IP, signature, permissions): Refused (the executor does not start: nothing would work). Any other failure is
        this coin's only (a refusal of the value, an undocumented answer, a read-back that does not show it yet, the
        endpoint not answering): kept in ``lev_problems`` (check shows it) and never stops the start, so an open
        position elsewhere is still protected; leverage() sets and reads back the paper's leverage before every entry
        on the coin and refuses that entry when it cannot."""
        sp = self._spec(symbol)
        rows = self._position_rows(symbol)
        if rows:
            if margin_word(rows[0].get("marginType")) == ISOLATED:
                return None
            raise TestnetError(400, -4048, f"{symbol}: 교차(cross) 포지션이 열려 있어 격리로 맞추지 못했습니다")
        lev = int(min(FIXED_LEVERAGE.get(symbol, DEFAULT_LEVERAGE), sp.get("max_leverage") or 10 ** 6))
        try:
            self._set_leverage(symbol, lev)
        except TestnetError as e:
            if e.code in KEY_REFUSED:
                raise Refused(f"투비트 {symbol}을 격리 {lev}배로 맞출 수 없어 거래하지 않습니다: {e.msg}") from e
            if e.code == BAD_TIMESTAMP:
                raise                                      # the clock: the executor re-syncs and calls again
            self.lev_problems[symbol] = f"격리 {lev}배를 못 맞춤: {e.msg}"
            return None
        self.lev_problems.pop(symbol, None)
        self.lev[symbol] = lev

    def leverage(self, symbol: str, lev: int) -> dict:
        """Set the symbol's isolated leverage and read it back. Refused (TestnetError) unless this process checked the
        positions (one_way) and the contract is TRADING: the executor never opens a position otherwise. A coin that is
        not TRADING in the cached contracts is read again first."""
        lev = int(lev)
        sp = self._spec(symbol)
        if not sp.get("tradable"):
            self._load_instruments()                       # at most every SPEC_CACHE_MS
            sp = self._spec(symbol)
        if sp.get("max_leverage") and lev > sp["max_leverage"]:
            raise TestnetError(400, "LEVERAGE_MAX", f"{symbol}: 레버리지 {lev}배가 최대 {sp['max_leverage']:g}배를 넘습니다")
        if not sp.get("tradable"):
            raise TestnetError(400, "NOT_TRADING", f"{symbol}: 상품 상태 {sp.get('status')} (TRADING이 아니면 거래 안 함)")
        self._no_entries(symbol)
        if not self.one_side:
            raise TestnetError(400, "NOT_ONE_WAY", "투비트 포지션(한 코인 한쪽만)을 확인하지 않아 진입하지 않습니다")
        rows = self._position_rows(symbol)
        if rows:
            r = rows[0]
            if _int(r.get("leverage")) == lev and margin_word(r.get("marginType")) == ISOLATED:
                self.lev[symbol] = lev
                return {"symbol": symbol, "leverage": lev, "marginType": "isolated"}
            raise TestnetError(400, "POSITION_OPEN", f"{symbol}: 포지션이 있어 레버리지를 바꾸지 않습니다")
        self._set_leverage(symbol, lev)
        self.lev_problems.pop(symbol, None)
        self.lev[symbol] = lev
        return {"symbol": symbol, "leverage": lev, "marginType": "isolated"}

    def account_setup(self, symbols) -> list:
        """(ok, Korean text) lines for preflight, reads only: the positions (one side per coin) and each coin's contract
        row and leverage."""
        out = []
        try:
            self._position_rows(None)
            out.append((True, "포지션: 주문마다 롱·숏 쪽을 붙여 보냄(BUY_OPEN·SELL_CLOSE 등), 한 코인에 한쪽만(롱·숏 동시 없음)"))
        except TransientError as e:
            out.append((False, f"포지션: {e.msg}"))
        for s in symbols:
            sp = self._spec(s)
            lev, mode = self._lev_info(s)
            problem = self.lev_problems.get(s)
            out.append((bool(sp.get("tradable")) and not sp.get("problem") and not problem,
                        f"{s}: 상태 {sp.get('status')}, 1계약 {sp['ct_val']} {sp.get('base_coin') or ''}, 수량 단위 "
                        f"{sp['lot_sz']}계약, 최소 주문 {min_order_text(sp)}, 가격 단위 {sp['tick_str']}, 최대 "
                        f"{sp['max_leverage'] or 0:g}배, 지금 {mode or '?'} {lev}배"
                        + (f" ({problem}: 진입 직전에 다시 맞추고, 안 되면 그 진입만 하지 않음)" if problem else "")))
        return out

    # ------------------------------------------------------------ order records
    def _query(self, symbol: Optional[str], stop: bool, **by) -> Optional[dict]:
        """GET /api/v1/futures/order by orderId or origClientOrderId (type STOP for a stop). Not there (-2013, or an
        empty answer): None. A row of another kind, another coin or another id than asked is not the answer (None)."""
        p = dict(by)
        if stop:
            p["type"] = STOP
        try:
            data = self.req("GET", ORDER, p, limit_key="query")
        except TestnetError as e:
            if e.code in NOT_FOUND and not isinstance(e, TransientError):
                return None
            raise
        if data in (None, {}, []):
            return None
        if isinstance(data, list):
            data = next((r for r in self._rows(data, "주문") if self._matches(r, by)), None)
            if data is None:
                return None
        if not isinstance(data, dict):
            raise TransientError(200, None, f"주문 응답이 이상합니다: {str(data)[:80]!r}")
        if not self._matches(data, by):
            return None
        kind = str(data.get("type") or "").upper()
        if kind and (kind in STOP_KINDS) != stop:
            return None
        sym = bn(data.get("symbol"))
        if (data.get("symbol") and not sym) or (symbol and sym and sym != symbol):
            return None
        if data.get("orderId") not in (None, ""):
            self.order_symbol[str(data["orderId"])] = sym or symbol or ""
        return data

    @staticmethod
    def _matches(row: dict, by: dict) -> bool:
        if "orderId" in by:
            return str(row.get("orderId")) == str(by["orderId"])
        return str(row.get("clientOrderId") or "") == str(by.get("origClientOrderId"))

    def _open_rows(self, symbol: str, stop: bool = False) -> list:
        """GET /api/v1/futures/openOrders of the coin (type STOP: the resting stops; else the open regular orders)."""
        p = {"symbol": tb(symbol), "limit": PAGE_ROWS}
        if stop:
            p["type"] = STOP
        rows = self._rows(self.req("GET", FUT + "/openOrders", p, limit_key="open_orders"),
                          "손절 대기 목록" if stop else "대기 주문")
        out = []
        for r in rows:
            if r.get("symbol") not in (None, "", tb(symbol)):
                continue                                   # another coin's row: never part of this coin's answer
            if r.get("orderId") in (None, ""):
                if stop and self._ours(r) is False:
                    continue                               # readable and not ours: its id is not needed
                raise TransientError(200, None, "대기 목록 응답에 orderId가 없습니다")
            self.order_symbol[str(r["orderId"])] = symbol
            out.append(r)
        return out

    def _history_rows(self, symbol: str, stop: bool = False, start_ms: Optional[int] = None) -> list:
        """GET /api/v1/futures/historyOrders of the coin, the newest 1000 (the docs' default window: three days)."""
        p = {"symbol": tb(symbol), "limit": PAGE_ROWS}
        if stop:
            p["type"] = STOP
        if start_ms is not None:
            p["startTime"] = int(start_ms)
        rows = self._rows(self.req("GET", FUT + "/historyOrders", p, limit_key="history"), "주문 기록")
        return [r for r in rows if r.get("symbol") in (None, "", tb(symbol))]

    def _find_cid(self, symbol: str, ext: str, lists: bool = True) -> Optional[dict]:
        """The regular order whose clientOrderId is ``ext``: GET order?origClientOrderId=, then (``lists``) the open
        orders and the order history of the coin (a second try only). None: in none of them."""
        row = self._query(symbol, False, origClientOrderId=ext)
        if row is None and lists:
            row = next((r for r in self._open_rows(symbol) + self._history_rows(symbol)
                        if r.get("clientOrderId") == ext and str(r.get("type") or "").upper() not in STOP_KINDS),
                       None)
        if row is not None and row.get("orderId") not in (None, ""):
            self.order_symbol[str(row["orderId"])] = symbol
        return row

    def _order_dict(self, row: dict, symbol: Optional[str] = None) -> dict:
        sym = bn(row.get("symbol")) or symbol or ""
        orig = _dec(row.get("origQty"), "origQty")
        done = row.get("executedQty") if row.get("executedQty") not in (None, "") else row.get("executeQty")
        exe = _dec(done, "executedQty")
        raw = str(row.get("status") or "").upper()
        side = side_of(row)
        if raw in ("NEW", "PENDING_NEW", "PENDING_CANCEL"):
            status = "PARTIALLY_FILLED" if exe > 0 else "NEW"
        elif raw == "PARTIALLY_FILLED":
            status = "PARTIALLY_FILLED"
        elif raw == "FILLED":
            status = "FILLED"
        elif raw in ("CANCELED", "REJECTED", "EXPIRED"):
            status = "FILLED" if orig > 0 and exe >= orig else raw
        else:
            raise TransientError(200, None, f"주문 상태가 이상합니다({row.get('status')!r})")
        avg = row.get("avgPrice")
        kind = "MARKET" if str(row.get("priceType") or "").upper() == "MARKET" else str(row.get("type") or "").upper()
        return {"orderId": str(self._need(row, "orderId", "주문")), "clientOrderId": row.get("clientOrderId") or "",
                "symbol": sym, "side": bin_side(side), "type": kind, "origQty": _num(self._base(sym, orig)),
                "executedQty": _num(self._base(sym, exe)),
                "avgPrice": _num(_dec(avg, "avgPrice")) if exe > 0 and avg not in (None, "") else "0",
                "status": status, "reduceOnly": side in CLOSES,
                "positionSide": CLOSED_SIDE.get(side) or (LONG if side == BUY_OPEN else SHORT), "tbStatus": raw,
                "tbSide": side, "time": to_ms(row["time"]) if row.get("time") not in (None, "") else None,
                "updateTime": to_ms(row["updateTime"]) if row.get("updateTime") not in (None, "") else None,
                "leverage": row.get("leverage"), "priceType": row.get("priceType")}

    # ------------------------------------------------------------ orders
    def market(self, symbol: str, side: str, qty: float, reduce_only: bool = False,
               client_id: Optional[str] = None) -> dict:
        """Market order (type LIMIT, priceType MARKET), then read back until it is final; a remainder still resting is
        cancelled. Opening: BUY_OPEN or SELL_OPEN. reduce_only: SELL_CLOSE (closes a long) or BUY_CLOSE (a short): it
        can never open or flip a position. An opening order is never sent twice (its client id is looked up first; a 429
        is an unknown outcome); a reduce-only order is protective work (its waits share PROTECT_WAIT_S). Answers (see
        _error): refused only on a documented refusal code; anything else that came after the send is an unknown outcome
        looked up by the client id. A failure before an opening order was sent: NotSent."""
        if side not in ("BUY", "SELL"):
            raise TestnetError(400, "BAD_SIDE", f"주문 방향 {side!r}")
        if not reduce_only:
            return self._market(symbol, side, qty, False, client_id)
        with self._protective():
            return self._market(symbol, side, qty, True, client_id)

    def _before_send(self, symbol: str, ext: str) -> Optional[dict]:
        """An opening id this process never sent: the checks before the send (the contract read, the look-up of its
        client id: an id Toobit already has is read, never sent again), tried again after NOT_SENT_WAITS while they
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
            return self._read_back_order(symbol, str(earlier["orderId"]),
                                         self._placeholder(symbol, side, qty, reduce_only, ext), earlier)
        if ext in self.sent and reduce_only:
            # the same close once more (its earlier send found absent past SETTLE_MS): sized from the position now,
            # never past it (a throttled send that ran after all must not close twice)
            qty = self._reduce_left(symbol, side, qty)
        sz = self._contracts(symbol, qty)
        self._check_size(symbol, sz, qty, "주문", entry=not reduce_only)
        body = {"symbol": tb(symbol), "side": CLOSE_SIDE[side] if reduce_only else OPEN_SIDE[side], "type": "LIMIT",
                "priceType": "MARKET", "quantity": _num(sz), "newClientOrderId": ext}
        placeholder = self._placeholder(symbol, side, float(self._base(symbol, sz)), reduce_only, ext)
        now = self._now()
        prev = self.sent.get(ext)
        self.sent[ext] = {"symbol": symbol, "first": (prev or {}).get("first", now), "last": now,
                          "reduce_only": reduce_only}
        self._trim()
        try:
            data, found = self._send_order(symbol, ext, body, reduce_only)
        except (TransientError, RateLimited):
            raise                                          # it may have run: looked up by its client id, never refused
        except TestnetError:
            self._unsend(ext, prev)                         # refused (a documented code): nothing ran
            raise
        if found is not None:
            self.own_oids[str(found["orderId"])] = symbol
            return self._read_back_order(symbol, str(found["orderId"]), placeholder, found)
        oid = data.get("orderId") if isinstance(data, dict) else None
        if oid in (None, "") or isinstance(oid, (dict, list, bool)):
            raise TransientError(200, None, "주문 번호가 없는 응답(결과 모름)")
        oid = str(oid)
        self.order_symbol[oid] = symbol
        self.own_oids[oid] = symbol
        return self._read_back_order(symbol, oid, {**placeholder, "orderId": oid}, data)

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
        """POST an order: (answer, None), or (None, row) when a close answered 429 was found by its client id. The docs
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

    def _read_back_order(self, symbol: str, oid: str, placeholder: dict, row: Optional[dict]) -> dict:
        """The accepted order, read until final (a few short waits; inside a protective call, within its budget). A
        market order still resting after them (matched only within 5 % of the last price) has its remainder cancelled
        and is read once more. It WAS accepted (it has an orderId): a failed or garbled read never escapes as if it had
        not run; the last state seen (or NEW) is returned and the executor settles it from the position."""
        best = {**placeholder, "orderId": oid}
        if row is not None and row.get("status") not in (None, ""):
            try:
                best = self._order_dict(row, symbol)
            except TestnetError as e:
                best = {**best, "readBack": f"기록을 읽지 못함: {e}"}
            if best.get("status") in ORDER_FINAL and "readBack" not in best:
                return best
        for w in (0.0,) + ORDER_WAITS:
            try:
                self._wait(w)
                got = self._query(symbol, False, orderId=oid)
                if got is None:
                    best = {**best, "readBack": "주문 기록이 아직 안 보입니다"}
                    continue
                best = self._order_dict(got, symbol)
            except TestnetError as e:
                return {**best, "readBack": f"읽기 실패: {e}"}
            if best["status"] in ORDER_FINAL:
                return best
        if best.get("status") in ("NEW", "PARTIALLY_FILLED") and "readBack" not in best:
            try:
                self.cancel(symbol, oid)
            except TestnetError as e:
                if e.code not in NOT_FOUND:
                    return {**best, "rest": f"남은 수량을 취소하지 못했습니다: {e}"}
            try:
                got = self._query(symbol, False, orderId=oid)
                if got is not None:
                    best = self._order_dict(got, symbol)
            except TestnetError as e:
                return {**best, "readBack": f"읽기 실패: {e}"}
            best["restCancelled"] = True
        return best

    def order(self, symbol: str, order_id=None, client_id: Optional[str] = None) -> dict:
        """An order by its orderId or client id. Not anywhere: TestnetError -2013 (not found), unless this process sent
        it less than SETTLE_MS ago (TransientError: unknown; an accepted order is never reported as not executed)."""
        if order_id is not None:
            row = self._query(symbol, False, orderId=str(order_id))
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
            raise TransientError(200, None, f"주문 {ext}이 아직 투비트 기록에 안 보입니다(보낸 지 "
                                            f"{(self._now() - int(mine['last'])) / 1000:.0f}초)")
        raise TestnetError(404, NOT_FOUND[0], f"주문 {ext}이 투비트에 없습니다")

    def forget_order(self, ext: str) -> None:
        """Drill only: the order's answer as if it had been lost (the look-up must find it by its client id)."""
        self.sent.pop(ext, None)

    @staticmethod
    def _cancel_answer(data, what: str) -> None:
        """A cancel is answered with the order (the docs; ccxt reads its status): an open status means this cancel ended
        it; an ended one means it had ended before (NOT_FOUND[1]: the caller reads what happened)."""
        status = str((data or {}).get("status") or "").upper() if isinstance(data, dict) else ""
        if status in STOP_ENDED or status in ORDER_FINAL:
            raise TestnetError(400, NOT_FOUND[1], f"{what}은 이미 끝났습니다({status})")

    def cancel(self, symbol: str, order_id) -> dict:
        """DELETE /api/v1/futures/order (a regular order). One that already ended: TestnetError NOT_FOUND."""
        try:
            data = self.req("DELETE", ORDER, {"orderId": str(order_id), "symbol": tb(symbol)}, limit_key="cancel")
        except TestnetError as e:
            if getattr(e, "tb_code", None) in ENDED_CODES and not isinstance(e, (TransientError, RateLimited)):
                raise TestnetError(400, NOT_FOUND[1], f"주문 {order_id}은 이미 끝났습니다({e.msg})") from e
            raise
        self._cancel_answer(data, f"주문 {order_id}")
        return {"orderId": str(order_id), "status": "CANCELED"}

    def cancel_all(self, symbol: str) -> dict:
        """Each open regular order of the coin cancelled by its orderId."""
        for r in self._open_rows(symbol):
            try:
                self.cancel(symbol, r["orderId"])
            except TestnetError as e:
                if e.code not in NOT_FOUND or isinstance(e, TransientError):
                    raise
        return {"code": 200, "msg": "ok"}

    def open_orders(self, symbol: str) -> list:
        return [self._order_dict(r, symbol) for r in self._open_rows(symbol)]

    def _trim(self, keep: int = 2000) -> None:
        """The id maps of a process that runs for weeks stay small (the oldest go first)."""
        for d in (self.sent, self.stop_intents, self.stop_by_cid, self.cid_by_stop, self.order_symbol,
                  self.list_delay_ms, self.own_oids, self.level_field):
            while len(d) > keep:
                d.pop(next(iter(d)))

    # ------------------------------------------------------------ STOP orders: the exchange-side stops
    def _open_stops(self, symbol: str) -> list:
        return self._open_rows(symbol, stop=True)

    @staticmethod
    def _ours(row: dict) -> Optional[bool]:
        """Can this STOP row be one of our stops? True: a STOP on a closing side. False: readable and not ours (an
        opening side, a position TP/SL type). None: its side (or type) missing or not a documented value, so it may be
        ours: the caller decides (never "not a stop" on a coin it may protect)."""
        kind = str(row.get("type") or STOP).upper()
        if kind in TPSL_TYPES:
            return False
        side = str(row.get("side") or "").upper()
        if kind not in STOP_KINDS or side not in SIDES:
            return None
        return side in CLOSES

    def _is_stop(self, row: dict) -> bool:
        ours = self._ours(row)
        if ours is None:
            raise TransientError(200, None, f"손절 주문 {row.get('orderId')}을 읽을 수 없습니다(type {row.get('type')!r}, "
                                            f"side {row.get('side')!r})")
        return ours

    @staticmethod
    def _stop_status(row: dict) -> str:
        """NEW / TRIGGERED / CANCELED / REJECTED from a STOP row's own status; anything else is an error (never
        "cancelled")."""
        s = str(row.get("status") or "").upper()
        if s in STOP_RESTING:
            return "NEW"
        if s in STOP_FIRED:
            return "TRIGGERED"
        if s in STOP_CANCELED:
            return "CANCELED"
        if s in STOP_FAILED:
            return "REJECTED"
        raise TransientError(200, None, f"손절 주문 {row.get('orderId')}의 상태를 모릅니다({row.get('status')!r})")

    def _level(self, row: dict) -> tuple:
        """(the level's field, its value) of a STOP row: stopPrice, else triggerPrice ("" / 0 / missing: none)."""
        for k in LEVEL_FIELDS:
            if _soft(row.get(k)) > 0:
                return k, _dec(row.get(k), k)
        return "", None

    def _algo_dict(self, row: dict, symbol: str, status: str = "NEW", actual: str = "") -> dict:
        sid = str(self._need(row, "orderId", "손절 주문"))
        stop = self._is_stop(row)
        fld, level = self._level(row)
        if status == "NEW" and stop:                       # a resting stop's level and size are never 0 from a gap
            if level is None or _dec(row.get("origQty"), "origQty") <= 0:
                raise TransientError(200, None, f"손절 주문 {sid}의 발동 가격이나 수량이 이상합니다({row.get('stopPrice')!r}, "
                                                f"{row.get('origQty')!r})")
            trig, qty = _num(level), _num(self._base(symbol, row.get("origQty")))
            self.level_field[sid] = fld
        elif stop:
            qty = _num(self._base(symbol, row.get("origQty"))) if row.get("origQty") not in (None, "") else "0"
            trig = _num(level) if level is not None else "0"
        else:                                              # not ours: shown as it reads, never an error
            qty = _num(_soft(row.get("origQty")) * Decimal(self._spec(symbol)["ct_val"]))
            trig = _num(level) if level is not None else "0"
        side = str(row.get("side") or "").upper()
        self.order_symbol[sid] = symbol
        made = row.get("time")
        return {"algoId": sid, "clientAlgoId": str(row.get("clientOrderId") or self.cid_by_stop.get(sid, "")),
                "symbol": symbol, "side": bin_side(side) if side in SIDES else side,
                "positionSide": CLOSED_SIDE.get(side, ""), "orderType": "STOP_MARKET" if stop else "CONDITIONAL",
                "algoType": "CONDITIONAL", "triggerPrice": trig, "quantity": qty, "closePosition": False,
                "reduceOnly": stop, "workingType": str(row.get("triggerBy") or row.get("workingType") or ""),
                "priceProtect": False, "algoStatus": status, "tbStatus": str(row.get("status") or ""),
                "tbType": str(row.get("type") or ""), "tbSide": side, "actualOrderId": actual,
                "createTime": to_ms(made) if made not in (None, "") and (stop or _soft(made) > 0) else None,
                "updateTime": to_ms(row["updateTime"]) if _soft(row.get("updateTime")) > 0 else None}

    def stop_close(self, symbol: str, side: str, trigger: float, qty: Optional[float] = None,
                   client_id: Optional[str] = None) -> dict:
        """Protective stop resting on Toobit: a STOP order on the closing side (SELL_CLOSE closes a long, BUY_CLOSE a
        short), priceType MARKET, ``quantity`` the position's contracts (two can coexist while a stop is moved; None:
        the position's size now). A level the last price is already past is refused before anything is sent (the
        executor's -2021: close at market). Protective work: every wait inside shares PROTECT_WAIT_S (then RateLimited;
        RateLimitedUnknown when the stop may have gone in). After the send the stop is waited for in the stop list
        (LIST_WAITS, within the budget): place_stop confirms a stop from the list only. Refused only on a documented
        refusal code; any other answer after the send is an unknown outcome, looked up by its client id."""
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
            raise TestnetError(400, WOULD_TRIGGER, f"Order would immediately trigger (투비트: 마지막 가격 {last:g}, "
                                                   f"손절 {trig})")
        tside = CLOSE_SIDE[side]
        body = {"symbol": tb(symbol), "side": tside, "type": STOP, "priceType": "MARKET", "stopPrice": trig,
                "quantity": _num(sz), "newClientOrderId": key}
        now = self._now()
        prev = self.stop_intents.get(key)
        self.stop_intents[key] = {"symbol": symbol, "side": tside, "sz": _num(sz), "trig": trig,
                                  "first": (prev or {}).get("first", now), "last": now, "sends": 1}
        self._trim()
        try:
            data, found = self._send_stop(key, body)
        except (TransientError, RateLimited):
            raise                                          # it may be in: looked up by its client id
        except TestnetError as e:                          # refused (a documented code): nothing placed
            if prev is None:
                self.stop_intents.pop(key, None)
            else:
                self.stop_intents[key] = prev
            raise self._would_trigger(e, symbol, side, float(trig)) from e
        if found is not None:                              # a 429 that still ran: that stop, never a second copy
            self._await_listed(symbol, found)
            return self.algo_order(algo_id=found)
        sid = data.get("orderId") if isinstance(data, dict) else None
        if sid in (None, "") or isinstance(sid, (dict, list, bool)):
            raise TransientError(200, None, "손절 주문 번호가 없는 응답(결과 모름)")
        sid = str(sid)
        self._bind_stop(key, sid, symbol)
        self._await_listed(symbol, sid)
        return {"algoId": sid, "clientAlgoId": key, "symbol": symbol, "side": side,
                "positionSide": CLOSED_SIDE[tside], "orderType": "STOP_MARKET", "algoType": "CONDITIONAL",
                "triggerPrice": _num(Decimal(trig)), "quantity": _num(self._base(symbol, sz)),
                "closePosition": False, "reduceOnly": True, "workingType": "", "algoStatus": "NEW"}

    def _bind_stop(self, key: str, sid: str, symbol: str) -> None:
        self.stop_by_cid[key], self.cid_by_stop[sid] = sid, key
        self.order_symbol[sid] = symbol
        self.own_oids[sid] = symbol

    def forget_stop(self, key: str) -> None:
        """Drill only: the stop's answer as if it had been lost (the look-up must find it by its client id)."""
        sid = self.stop_by_cid.pop(key, None)
        if sid is not None:
            self.cid_by_stop.pop(sid, None)

    def _send_stop(self, key: str, body: dict) -> tuple:
        """POST a stop: (answer, None), or (None, orderId) when it was answered 429 and a look-up by its client id found
        it. The first look-up (after the Retry-After) that finds it nowhere sends it ONCE more under the same id (a
        second reduce-only stop cannot open anything and the executor cancels a surplus one, while a stop that never
        goes in would close a new position); then the look-ups go on while the budget lasts. Not found by then:
        RateLimitedUnknown. Any other error: as it came (a 403 / 418 after the send is a TransientError)."""
        intent = self.stop_intents[key]
        try:
            return self.req("POST", ORDER, body, limit_key="order"), None
        except RateLimited as e:
            if e.status != 429 or e.code == BUDGET_CODE:
                raise
            first = e
        pause = max(float(first.retry_after or 0), READ_PAUSE_S)
        why = "찾는 동안 기다릴 시간이 다 됨"
        again = True
        while True:
            row, read = None, False
            try:
                self._wait(pause)
                row = self._find_stop_cid(intent["symbol"], key)
                read = True
            except RateLimited as e:
                why = str(e)[:120]
                break
            except TestnetError as e:
                why = str(e)[:120]
            if row is not None:
                sid = str(row["orderId"])
                self._bind_stop(key, sid, intent["symbol"])
                return None, sid
            pause = LOOKUP_PAUSE_S
            if not again or not read:
                continue
            again = False                                  # nowhere: sent once more (same id)
            intent["sends"], intent["last"] = 2, self._now()
            try:
                return self.req("POST", ORDER, body, limit_key="order"), None
            except RateLimited as e:
                if e.status != 429 or e.code == BUDGET_CODE:
                    why = str(e)[:120]
                    break
                pause = max(float(e.retry_after or 0), READ_PAUSE_S)
            except TestnetError as e:                      # refused, a duplicate id, unanswered: look again
                why = str(e)[:120]
        raise RateLimitedUnknown(429, first.code, f"손절 {key}에 요청 한도 답(429): 들어갔는지 아직 모릅니다. 번호로 "
                                                  f"찾습니다({why}): {first.msg}", 1.0)

    def _find_stop_cid(self, symbol: Optional[str], key: str, lists: bool = True) -> Optional[dict]:
        """The STOP order whose clientOrderId is ``key``: GET order?type=STOP&origClientOrderId=, then (``lists``, the
        coin known) its stop list and stop history (a second try only). None: in none of them."""
        row = self._query(symbol, True, origClientOrderId=key)
        if row is None and lists and symbol:
            row = next((r for r in self._open_stops(symbol) + self._history_rows(symbol, stop=True)
                        if r.get("clientOrderId") == key), None)
        if row is not None and row.get("orderId") not in (None, ""):
            self.order_symbol[str(row["orderId"])] = bn(row.get("symbol")) or symbol or ""
        return row

    def _stop_earlier(self, key: str) -> Optional[str]:
        """The stop an id already placed (its orderId), or None (send it). A stop sent by this process whose answer was
        lost is looked up by its id; not found within SETTLE_MS of its last send: unknown (TransientError, never a
        second copy now)."""
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
        row = self._find_stop_cid(intent["symbol"] if intent else None, key, lists=intent is not None)
        if row is not None and row.get("orderId") not in (None, ""):
            sid = str(row["orderId"])
            if intent is not None:
                self._bind_stop(key, sid, intent["symbol"])
            return sid
        if intent is None:
            raise TestnetError(404, NOT_FOUND[0], f"손절 {key}이 없습니다")
        age = self._now() - int(intent["last"])
        if age < SETTLE_MS:
            raise TransientError(200, None, f"손절 {key}: 아직 투비트 기록에 안 보입니다(보낸 지 {age / 1000:.0f}초, "
                                            f"{SETTLE_MS // 1000}초까지 기다림)")
        if settled_none:
            return None
        raise TestnetError(404, NOT_FOUND[0], f"손절 {key}이 투비트에 없습니다({SETTLE_MS // 1000}초 지나도 없음)")

    def _await_listed(self, symbol: str, sid: str) -> None:
        """A stop just placed: waited for (LIST_WAITS, about 5 s, within the protective budget) until the stop list
        shows it, or its own record says it ended (fired at once). Best effort, never an error here: place_stop reads it
        next, and a stop the list does not show is not confirmed."""
        t0 = self.clock_ms()
        for w in (0.0,) + LIST_WAITS:
            try:
                self._wait(w)
                if any(str(r.get("orderId")) == sid for r in self._open_stops(symbol)):
                    self.list_delay_ms[sid] = self.clock_ms() - t0
                    return
                row = self._query(symbol, True, orderId=sid)
                if row is not None and str(row.get("status") or "").upper() in STOP_ENDED:
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
            return TestnetError(e.status, WOULD_TRIGGER, f"Order would immediately trigger (투비트: {e.msg}; 마지막 "
                                                         f"가격 {last:g}, 손절 {trig:g})")
        return e

    def _ended(self, row: dict, symbol: str, status: str) -> dict:
        """A stop whose own record says it ended: fired (TRIGGERED, with the order it placed), CANCELED or REJECTED."""
        sid = str(row.get("orderId"))
        if status == "TRIGGERED":
            fired = to_ms(row["updateTime"]) if _soft(row.get("updateTime")) > 0 else self._now()
            return self._algo_dict(row, symbol, status, self._child_order(symbol, sid, row, fired))
        out = self._algo_dict(row, symbol, status)
        if status == "REJECTED":
            out["tbError"] = str(row.get("status") or "")
        return out

    def _child_order(self, symbol: str, sid: str, row: dict, fired_ms: int) -> str:
        """The order a fired stop placed: fills under the stop's own orderId, else the one regular order of the coin on
        the stop's side made from 2 s before it fired to CHILD_AFTER_MS after, not one of ours (no client id of ours,
        not an order this process placed). Not found or not one: "" (the executor's P&L then reads every fill of the
        trade's window). A failed read of the fills still leaves the order history to look in."""
        try:
            if any(str(f.get("orderId")) == sid for f in self._trades(symbol, fired_ms - 60_000,
                                                                       fired_ms + CHILD_AFTER_MS)):
                return sid
        except TestnetError:
            pass
        try:
            side = side_of(row)
            cands = []
            for r in self._history_rows(symbol, start_ms=fired_ms - 60_000):
                if str(r.get("side") or "").upper() != side or str(r.get("type") or "").upper() in STOP_KINDS:
                    continue
                cid = str(r.get("clientOrderId") or "")
                if cid.startswith("pb") or cid in self.sent or str(r.get("orderId")) in self.own_oids:
                    continue                               # one of ours (every id this executor sends starts "pb")
                t = to_ms(r["time"]) if r.get("time") not in (None, "") else None
                if t is not None and fired_ms - 2_000 <= t <= fired_ms + CHILD_AFTER_MS:
                    cands.append(str(r.get("orderId")))
            return cands[0] if len(cands) == 1 else ""
        except TestnetError:
            return ""

    def algo_order(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        """A stop by its orderId (or the executor's client id). Its own record (GET order type=STOP) decides when it
        says the stop ended; resting is confirmed only from the stop list. The reads share the protective budget
        (place_stop confirms a new stop with it). An orderId whose record is not there and whose coin this process has
        not seen (after a restart) is looked for in every coin's stop list: a coin whose list cannot be read makes the
        answer unknown (TransientError), never "not found"."""
        with self._protective():
            return self._algo_order(algo_id, client_id)

    def _algo_order(self, algo_id, client_id: Optional[str]) -> dict:
        if algo_id is None:
            algo_id = self._resolve_stop(ext_id(client_id))
        sid = str(algo_id)
        sym = self.order_symbol.get(sid) or None
        row = self._query(sym, True, orderId=sid)
        if row is not None:
            sym = bn(row.get("symbol")) or sym
            st = self._stop_status(row)
            if st != "NEW" and sym:
                return self._ended(row, sym, st)
        coins = [sym] if sym else list(COINS)
        unread: dict = {}
        for s in coins:
            try:
                listed = next((r for r in self._open_stops(s) if str(r.get("orderId")) == sid), None)
            except TestnetError as e:
                if sym:
                    raise
                unread[s] = e
                continue
            if listed is not None:
                return self._algo_dict(listed, s, "NEW")
        if row is None and sym:                            # no record by its id: the stop history may hold its end
            hist = next((r for r in self._history_rows(sym, stop=True) if str(r.get("orderId")) == sid), None)
            if hist is not None and self._stop_status(hist) != "NEW":
                return self._ended(hist, sym, self._stop_status(hist))
        key = self.cid_by_stop.get(sid)
        if key is not None or row is not None:             # ours, or its record says resting: not confirmed (no list)
            intent = self.stop_intents.get(key or "") or {}
            s = sym or intent.get("symbol") or ""
            return {"algoId": sid, "clientAlgoId": key or str((row or {}).get("clientOrderId") or ""), "symbol": s,
                    "side": bin_side(intent.get("side") or str((row or {}).get("side") or "SELL").upper()),
                    "orderType": "STOP_MARKET", "algoType": "CONDITIONAL",
                    "triggerPrice": str(intent.get("trig") or "0"),
                    "quantity": _num(self._base(s, intent["sz"])) if intent.get("sz") and s else "0",
                    "closePosition": False, "reduceOnly": True, "workingType": "", "algoStatus": UNCONFIRMED,
                    "actualOrderId": ""}
        if unread:
            first = next(iter(unread.values()))
            raise TransientError(getattr(first, "status", 0), None, f"손절 주문 {sid}: {', '.join(unread)}의 목록을 읽지 "
                                                                    f"못해 있는지 모릅니다({first})"[:300])
        raise TestnetError(404, NOT_FOUND[0], f"손절 주문 {sid}이 없습니다")

    def cancel_algo(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        """DELETE /api/v1/futures/order?type=STOP. Answered with a resting status: this cancel ended it. Answered with
        an ended status, or "not found / already ended": NOT_FOUND (the record is read: one that still rests is an
        error); without a status, the stop is read again: still resting is TransientError (the cancel is not
        confirmed)."""
        if algo_id is None:
            algo_id = self._resolve_stop(ext_id(client_id))
        sid = str(algo_id)
        sym = self.order_symbol.get(sid) or self.algo_order(algo_id=sid)["symbol"]
        try:
            data = self.req("DELETE", ORDER, {"orderId": sid, "type": STOP, "symbol": tb(sym)}, limit_key="cancel")
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            if e.code not in NOT_FOUND and getattr(e, "tb_code", None) not in ENDED_CODES:
                raise
            try:                                           # did it end already?
                cur = self.algo_order(algo_id=sid)
            except TestnetError as e2:
                if e2.code in NOT_FOUND:
                    raise e2 from e
                raise e
            if cur["algoStatus"] in ("TRIGGERED", "CANCELED", "REJECTED"):    # only what the record says ended
                raise TestnetError(400, NOT_FOUND[1], f"이미 끝난 손절({cur['algoStatus']}): {e.msg}") from e
            raise
        status = str(data.get("status") or "").upper() if isinstance(data, dict) else ""
        if status in STOP_ENDED:
            raise TestnetError(400, NOT_FOUND[1], f"손절 {sid}은 이미 끝났습니다({status})")
        if status not in STOP_RESTING:
            cur = self.algo_order(algo_id=sid)
            if cur["algoStatus"] in ("NEW", UNCONFIRMED):
                raise TransientError(200, None, f"손절 {sid} 취소 답에 상태가 없고, 아직 걸려 있는 것으로 읽힙니다")
        return {"algoId": sid, "clientAlgoId": self.cid_by_stop.get(sid, ""), "code": "200", "msg": "success"}

    def open_algo_orders(self, symbol: str) -> list:
        """Every resting STOP order of the coin: ours (a closing side) as STOP_MARKET, an opening one or a position
        TP/SL as CONDITIONAL (never counted as a stop that covers a position). Rows of other coins never enter the
        answer; a row whose own status says it ended is not resting. A row that may be one of our stops but cannot be
        read is an error (never "no stop") while it may protect something: the coin holds a position, or the row's
        orderId is a stop this process placed. On a coin without a position it protects nothing: it is listed as
        CONDITIONAL with ``tbUnreadable`` (the executor's sweep of the other coins goes on; never cancelled as a stray
        stop)."""
        out, unread = [], []
        for r in self._open_stops(symbol):
            try:
                if str(r.get("status") or "").upper() in STOP_ENDED:
                    continue
                out.append(self._algo_dict(r, symbol))
            except TransientError as e:
                unread.append((r, e))
        if unread:
            if any(str(r.get("orderId")) in self.cid_by_stop for r, _ in unread) or self._position_rows(symbol):
                raise unread[0][1]
            out += [{"algoId": str(r.get("orderId")), "clientAlgoId": str(r.get("clientOrderId") or ""),
                     "symbol": symbol, "side": str(r.get("side") or "").upper(), "positionSide": "",
                     "orderType": "CONDITIONAL", "algoType": "CONDITIONAL", "triggerPrice": "0", "quantity": "0",
                     "closePosition": False, "reduceOnly": False, "algoStatus": "NEW",
                     "tbType": str(r.get("type") or ""), "tbUnreadable": e.msg} for r, e in unread]
        return out

    def placed_stops(self, symbol: str) -> list:
        """The resting STOP orders of the coin that this client placed: an orderId it was answered, or a lost answer
        found by its client id (the drill's clean-up cancels these and nothing else)."""
        mine = {sid for sid in self.stop_by_cid.values() if self.order_symbol.get(sid) == symbol}
        rows = self.open_algo_orders(symbol)
        keys = {k for k, i in self.stop_intents.items() if i.get("symbol") == symbol and k not in self.stop_by_cid}
        mine |= {o["algoId"] for o in rows if o.get("clientAlgoId") in keys}
        return [o for o in rows if o["algoId"] in mine]

    def cancel_all_algo(self, symbol: str) -> dict:
        """Each resting STOP order of the coin cancelled by its orderId (a position TP/SL set in the app belongs to its
        position and goes with it)."""
        for r in self._open_stops(symbol):
            if str(r.get("type") or STOP).upper() in TPSL_TYPES or str(r.get("status") or "").upper() in STOP_ENDED:
                continue
            try:
                self.req("DELETE", ORDER, {"orderId": str(r["orderId"]), "type": STOP, "symbol": tb(symbol)},
                         limit_key="cancel")
            except TestnetError as e:
                if isinstance(e, (TransientError, RateLimited)) or (
                        e.code not in NOT_FOUND and getattr(e, "tb_code", None) not in ENDED_CODES):
                    raise
        return {"code": 200, "msg": "ok"}

    # ------------------------------------------------------------ positions
    def _position_rows(self, symbol: Optional[str] = None) -> list:
        """Open position rows (position != 0). The answer must be a list and a row must be readable: never "flat" from a
        missing or garbled field. A coin with a long and a short at once: TransientError (``tb_mixed``), never
        netted."""
        p = {"symbol": tb(symbol)} if symbol else {}
        rows = self._rows(self.req("GET", FUT + "/positions", p, limit_key="positions"), "포지션")
        out, per = [], {}
        for r in rows:
            sym = bn(r.get("symbol"))
            if not sym or (symbol and sym != symbol):
                continue
            amt = _dec(r.get("position"), "position")
            if amt == 0:
                continue
            side = str(r.get("side") or "").upper()
            if side not in (LONG, SHORT) or (amt < 0 and side == LONG):
                raise TransientError(200, None, f"{sym}: 포지션 방향이 이상합니다(side {r.get('side')!r}, 수량 "
                                                f"{r.get('position')!r})")
            per.setdefault(sym, []).append(side)
            out.append(r)
        many = sorted(s for s, sides in per.items() if len(sides) > 1)
        if many:
            err = TransientError(200, None, f"{', '.join(many)}: 한 코인에 포지션이 둘 이상입니다(롱·숏 동시: 단방향이 아님)")
            err.tb_mixed = True
            raise err
        return out

    def _position_dict(self, symbol: str, rows: list) -> dict:
        main = rows[0] if rows else {}
        amt = Decimal(0)
        if rows:
            q = abs(self._base(symbol, main.get("position")))     # the side comes from ``side`` only
            amt = q if str(main.get("side")).upper() == LONG else -q
        mt = margin_word(main.get("marginType"))
        avail = main.get("available")
        return {"symbol": symbol, "positionAmt": _num(amt), "entryPrice": str(main.get("avgPrice") or "0"),
                "markPrice": str(main.get("markPrice") or main.get("lastPrice") or "0"),
                "liquidationPrice": str(main.get("flp") or "0"),
                "unRealizedProfit": str(main.get("unrealizedPnL") or "0"), "leverage": str(main.get("leverage") or ""),
                "marginType": mt.lower(), "hedge": False, "positionSide": main.get("side"),
                "available": _num(abs(self._base(symbol, avail))) if _soft(avail) != 0 or avail == "0" else None,
                "positionValue": main.get("positionValue"), "margin": main.get("margin")}

    def position(self, symbol: str) -> dict:
        return self._position_dict(symbol, self._position_rows(symbol))

    def positions(self) -> list:
        by: dict = {}
        for r in self._position_rows(None):
            by.setdefault(bn(r.get("symbol")), []).append(r)
        out = [self._position_dict(s, rs) for s, rs in by.items() if s]
        return [p for p in out if float(p["positionAmt"]) != 0]

    # ------------------------------------------------------------ fills, P&L, funding
    def _split(self, fetch: Callable, lo: int, hi: int, depth: int, budget: list, what: str) -> list:
        """A window read in two halves (a full page, or the window refused as too long)."""
        if depth >= HISTORY_DEPTH or hi - lo < 2:
            raise TransientError(0, None, f"{what}이 너무 많아 나눠 읽지 못했습니다")
        mid = (int(lo) + int(hi)) // 2
        return fetch(lo, mid, depth + 1, budget) + fetch(mid + 1, hi, depth + 1, budget)

    def _trades(self, symbol: str, lo_ms: int, hi_ms: int, depth: int = 0, budget: Optional[list] = None) -> list:
        """GET /api/v1/futures/userTrades in [lo_ms, hi_ms]: startTime / endTime one ms wider (whether they include
        their own millisecond is not said) and the rows kept by their time; a full page (1000), or a window refused as
        too long (-1127), is read again in two halves, at most HISTORY_REQUESTS requests (a server that ignored the
        window would otherwise split forever: an error)."""
        budget = [HISTORY_REQUESTS] if budget is None else budget
        if budget[0] <= 0:
            raise TransientError(0, None, f"{symbol}: 체결이 너무 많아 나눠 읽지 못했습니다(요청 {HISTORY_REQUESTS}번)")
        budget[0] -= 1
        fetch = lambda a, b, d, bud: self._trades(symbol, a, b, d, bud)          # noqa: E731
        p = {"symbol": tb(symbol), "startTime": int(lo_ms) - 1, "endTime": int(hi_ms) + 1, "limit": PAGE_ROWS}
        try:
            data = self.req("GET", FUT + "/userTrades", p, limit_key="trades")
        except TestnetError as e:
            if getattr(e, "tb_code", None) == LOOKUP_TOO_LONG and not isinstance(e, (TransientError, RateLimited)):
                return self._split(fetch, lo_ms, hi_ms, depth, budget, f"{symbol}: 체결")
            raise
        rows = self._rows(data, "체결")
        if len(rows) >= PAGE_ROWS:
            return self._split(fetch, lo_ms, hi_ms, depth, budget, f"{symbol}: 체결")
        return [r for r in rows if r.get("symbol") in (None, "", tb(symbol))
                and int(lo_ms) <= to_ms(r.get("time"), "time") <= int(hi_ms)]

    def user_trades(self, symbol: str, start_ms: int, end_ms: int, limit: int = 1000) -> list:
        """Account fills (Binance userTrades shape): price, qty (base units), realizedPnl (Toobit's own of each closing
        fill, checked against the replay: fills_from_rows), commission (+ paid), commissionAsset, orderId, side,
        time."""
        seen, rows = set(), []
        for r in self._trades(symbol, int(start_ms), int(end_ms)):
            k = str(r.get("id"))
            if k in seen:
                continue
            seen.add(k)
            rows.append(r)
        if not rows:
            return []
        return fills_from_rows(rows, self._spec(symbol)["ct_val"], symbol)

    def _flows(self, lo_ms: int, hi_ms: int, flow_type: Optional[int], depth: int = 0,
               budget: Optional[list] = None) -> list:
        """GET /api/v1/futures/balanceFlow (USDT-M) of one flowType (None: every type) in [lo_ms, hi_ms], the window
        read again in halves when a page is full (1000) or the window is refused as too long. A row of another type than
        asked is left out (a server that ignored the filter)."""
        budget = [HISTORY_REQUESTS] if budget is None else budget
        if budget[0] <= 0:
            raise TransientError(0, None, f"자금 기록이 너무 많아 나눠 읽지 못했습니다(요청 {HISTORY_REQUESTS}번)")
        budget[0] -= 1
        fetch = lambda a, b, d, bud: self._flows(a, b, flow_type, d, bud)         # noqa: E731
        p = {"flowType": flow_type, "startTime": int(lo_ms) - 1, "endTime": int(hi_ms) + 1, "limit": PAGE_ROWS}
        try:
            data = self.req("GET", FUT + "/balanceFlow", p, limit_key="flow")
        except TestnetError as e:
            if getattr(e, "tb_code", None) == LOOKUP_TOO_LONG and not isinstance(e, (TransientError, RateLimited)):
                return self._split(fetch, lo_ms, hi_ms, depth, budget, "자금 기록")
            raise
        rows = self._rows(data, "자금 기록")
        if len(rows) >= PAGE_ROWS:
            return self._split(fetch, lo_ms, hi_ms, depth, budget, "자금 기록")
        out = []
        for r in rows:
            self._need(r, "id", "자금 기록")
            typ = r.get("flowTypeValue")
            if flow_type is not None and typ not in (None, "") and _int(typ) != flow_type:
                continue
            if int(lo_ms) <= to_ms(r.get("created"), "created") <= int(hi_ms):
                out.append(r)
        return out

    def income(self, symbol: Optional[str], income_type: Optional[str], start_ms: int, end_ms: int,
               limit: int = 1000) -> list:
        """Funding and transfers in the Binance income shape (``income``: + received / in) from balanceFlow: flowType 32
        (Fund Fee) as FUNDING_FEE (a row naming another coin is not ``symbol``'s; one naming none counts: one position
        at a time, the account is the executor's own) and flowType 51 (the transfer between the spot and the futures
        account) as TRANSFER."""
        out = []
        for flow, kind in ((FLOW_FUNDING, "FUNDING_FEE"), (FLOW_TRANSFER, "TRANSFER")):
            if income_type not in (None, kind):
                continue
            for r in self._flows(int(start_ms), int(end_ms), flow):
                plain = str(r.get("symbol") or "")
                sym = bn(r.get("symbolId")) or (plain if plain.endswith(SETTLE) and len(plain) > len(SETTLE)
                                                 and "-" not in plain else "")
                if kind == "FUNDING_FEE" and symbol and sym and sym != symbol:
                    continue
                t = to_ms(r.get("created"), "created")
                out.append({"symbol": sym or symbol or "", "incomeType": kind,
                            "income": _num(_dec(r.get("change"), "change")),
                            "asset": str(r.get("coin") or r.get("coinId") or SETTLE), "time": t,
                            "tranId": _id60("flow", r.get("id"), t),
                            "info": f"{r.get('flowType') or kind} (flowType {flow})"})
        return sorted(out, key=lambda r: int(r["time"]))

    def flow_types(self, start_ms: int, end_ms: int) -> dict:
        """Drill: how many rows of each flowType the window holds (compared with the app by the owners)."""
        kinds: dict = {}
        for r in self._flows(int(start_ms), int(end_ms), None):
            k = f"{r.get('flowTypeValue')} {FLOW_NAMES.get(_int(r.get('flowTypeValue')), r.get('flowType') or '')}"
            kinds[k.strip()] = kinds.get(k.strip(), 0) + 1
        return kinds


class ToobitKeyCheckClient(ToobitClient):
    """The key check (reads only): the futures account. The API reports no key permissions: "futures trade only, no
    withdrawal, server IP bound" comes from the owners' statement ``attested`` (TOOBIT_LIVE_KEY_CHECKED)."""
    __test__ = False

    def __init__(self, *a, attested: bool = False, **k):
        super().__init__(*a, **k)
        self.attested = attested

    def api_restrictions(self):
        data = self.req("GET", FUT + "/balance", limit_key="balance")
        if not isinstance(data, list) or not any(isinstance(r, dict) and r.get("asset") == SETTLE for r in data):
            return None                                     # nothing verified
        return permission_record(self.attested, True)


# ---------------------------------------------------------------- keys, allowlist, the executor's clients
def _values(env, names) -> set:
    return {str((env or {}).get(n) or "").strip() for n in names} - {""}


OTHER_KEYS = (("paper 실행기의 읽기 전용 키(BINANCE_API_KEY)", PAPER_KEY_NAMES),
              ("바이낸스 키(LIVE_*/TESTNET_*)", BINANCE_LIVE_KEY_NAMES + BINANCE_TESTNET_KEY_NAMES),
              ("바이비트 키(BYBIT_*)", BY.LIVE_KEY_NAMES + BY.TESTNET_KEY_NAMES),
              ("MEXC 키(MEXC_*)", MX.LIVE_KEY_NAMES), ("WOO X Pro 키(WOOXPRO_*)", WX.LIVE_KEY_NAMES + (WX.MEMO_NAME,)),
              ("플립스터 키(FLIPSTER_*)", FL.LIVE_KEY_NAMES),
              ("딥코인 키(DEEPCOIN_*)", DC.LIVE_KEY_NAMES + (DC.PASSPHRASE_NAME,)))


def trading_keys(mode: str, env, paper_env=None) -> tuple[str, str]:
    """The Toobit key and secret, or Refused. Mainnet only, behind PAPERBOT_LIVE_MAINNET=I_UNDERSTAND. Never the paper
    runner's key or another exchange's key."""
    if mode != MODE_MAINNET:
        raise Refused(f"투비트에는 테스트넷이 없습니다: \"exchange\": \"toobit\"는 \"mode\": \"mainnet\"만 됩니다"
                      f"(지금 {mode!r})")
    if (env.get(FLAG) or "") != FLAG_VALUE:
        raise Refused(f"실거래 스위치가 꺼져 있습니다: 환경 변수 {FLAG}={FLAG_VALUE} 가 필요합니다")
    key, secret = (str(env.get(n) or "").strip() for n in LIVE_KEY_NAMES)
    if not (key and secret):
        raise Refused(f"{LIVE_KEY_NAMES[0]} / {LIVE_KEY_NAMES[1]} 가 비어 있습니다")
    if key == secret:
        raise Refused(f"{LIVE_KEY_NAMES[0]}와 {LIVE_KEY_NAMES[1]}가 같습니다")
    mine = {key, secret}
    if mine & _values(paper_env, PAPER_KEY_NAMES):
        raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 paper 실행기의 읽기 전용 키(BINANCE_API_KEY)와 같습니다")
    for what, names in OTHER_KEYS:
        if mine & _values(env, names):
            raise Refused(f"{LIVE_KEY_NAMES[0]}/{LIVE_KEY_NAMES[1]}가 {what}와 같습니다. 거래소마다 다른 키를 씁니다")
    return key, secret


def attested(env) -> bool:
    return str((env or {}).get(KEY_CHECKED) or "").strip() == KEY_CHECKED_VALUE


def refuse_unless_allowed(mode: str, client) -> None:
    """Mainnet only, and the client must be the Toobit client pointing at the allowed host, with keys."""
    if mode != MODE_MAINNET:
        raise Refused(f"투비트에는 테스트넷이 없습니다: mode={mode!r}로는 시작하지 않습니다(\"mainnet\"만)")
    host = urllib.parse.urlparse(getattr(client, "base", "") or "").hostname or ""
    if host not in TOOBIT_HOSTS or type(client) is not ToobitClient or tuple(type(client).HOSTS) != TOOBIT_HOSTS:
        raise Refused(f"주소 {host!r}: 투비트 실행기는 {'·'.join(TOOBIT_HOSTS)} 외에는 연결하지 않습니다")
    if getattr(client, "public_only", False):
        raise Refused("키 없이 만든 투비트 클라이언트로는 실행기를 켜지 않습니다")


def check_executor_keys(mode: str, client, keycheck, env, paper_env) -> None:
    """The executor's key gates for Toobit (Executor.__init__): the keys, the key check, the owners' statement."""
    key, secret = trading_keys(mode, env, paper_env)
    if (client.key, client.secret) != (key, secret):
        raise Refused("투비트 실거래 실행기의 키가 TOOBIT_LIVE_KEY/SECRET와 다릅니다")
    if not isinstance(keycheck, ToobitKeyCheckClient) or (keycheck.key, keycheck.secret) != (key, secret):
        raise Refused("투비트 실거래는 키 확인(선물 계정 읽기)을 거쳐야 시작합니다")
    if not attested(env) or not keycheck.attested:
        raise Refused(f"투비트는 키 권한을 API로 알려 주지 않습니다. 키를 '선물 거래만, 출금 없음, 서버 IP만'으로 만든 것을 "
                      f"확인한 뒤 {KEY_FILE}에 {KEY_CHECKED}={KEY_CHECKED_VALUE} 를 넣으세요")


def clients(mode: str, env, paper_env=None):
    """(order client, key-check client) for the mode, keys from the environment."""
    key, secret = trading_keys(mode, env, paper_env)
    return ToobitClient(key, secret), ToobitKeyCheckClient(key, secret, attested=attested(env))


def public_client() -> ToobitClient:
    """Market data only (specs): no key, no private call."""
    return ToobitClient("", "", public_only=True)


# ---------------------------------------------------------------- drill (mainnet, tiny)
def reconcile(c: ToobitClient, symbol: str, stop_price: Optional[float] = None) -> dict:
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


pace = DC.pace                                             # the drill's requests at least DRILL_MIN_GAP_S apart
trigger_source = DC.trigger_source
row_text = DC.row_text
say = DC.say
_interrupt = DC._interrupt


@dataclass
class ToobitDrill:
    """The Toobit micro drill on the REAL account. ``check()`` reads (time, contracts and rate limits, account, fee
    rate, open orders and stops, funding and transfer flows, positions one side per coin) and sets the isolated leverage
    (BTC 40x, the others 30x): no order. ``order_cycle()`` (only behind the explicit confirmation) runs one small-size
    cycle on one coin: a plain market entry (LIMIT + MARKET), found by its client id (GET order, and again with its
    answer treated as lost; whether the open list / order history show it too is a note only), the leverage, margin and
    size units read on the position (its own value against contracts x multiplier x price), the balance and equity, a
    reduce-only STOP (how long until it is listed; found by its client id, also as a lost answer), half of the position
    closed with a reduce-only market order (SELL_CLOSE / BUY_CLOSE) while that stop rests (always, whatever the trigger
    test does), the stop moved to the half left (new first, then the old one cancelled: two must rest at once; how the
    cancelled one reads), then the trigger test (the stop moved to 0.1 % from the last price and left to fire for real;
    which price fired it and whose orderId its fills carry) or a reduce-only close of the rest, flat with no order and
    no stop left, and the P&L from the fills (Toobit's realizedPnl) checked against the fill prices and the wallet
    change, with the fee measured on the fills against commissionRate. One run tests one side (``side``): the drill is
    done once a long and a short run are both [OK]."""
    client: ToobitClient
    symbols: tuple = COINS
    symbol: Optional[str] = None
    side: int = 1
    keycheck: Optional[ToobitKeyCheckClient] = None
    stop_frac: float = 0.01
    trigger_test: bool = True
    trigger_wait_s: float = TRIGGER_WAIT_S
    wait: Callable[[float], None] = time.sleep
    elapsed: Callable[[], float] = time.monotonic          # seconds, for the drill's waits (tests pass their clock)
    say: Optional[Callable[[str], None]] = None            # each step printed as it happens (the CLI prints)
    log: list = field(default_factory=list)
    fee_api: Optional[dict] = None
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
        """The drill's coin: the cheapest drill order among the coins whose contract is not 1 coin (there the size
        units can be told apart) while it costs at most DRILL_UNIT_MAX_USDT, else the cheapest of all."""
        c = self.client
        cost = {}
        for s in self.symbols:
            try:
                sp, px = c.spec(s), c.price(s)
            except TestnetError:
                continue
            if sp.get("tradable") and not sp.get("problem"):
                cost[s] = (self.drill_qty(sp, px) * px, Decimal(sp["ct_val"]) != 1)
        if not cost:
            raise TestnetError(400, "NO_SYMBOL", "drill에 쓸 수 있는 코인이 없습니다")
        units = [s for s, (usd, ok) in cost.items() if ok and usd <= DRILL_UNIT_MAX_USDT]
        return min(units or cost, key=lambda s: cost[s][0])

    @staticmethod
    def drill_qty(spec: dict, price: float) -> float:
        """The fewest contracts worth at least DRILL_ORDER_USDT (and the minimum order value twice, with a margin) that
        split into two equal halves of at least the smallest order each: the cycle closes one half with a reduce-only
        market order and the other later."""
        step = spec["qty_step"]
        usd = max(DRILL_ORDER_USDT, 2.1 * float(spec.get("min_notional") or 0))
        need = math.ceil(usd / (price * step) - 1e-9) * step if price > 0 else 0.0
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
            except TestnetError as e:                       # a missing unit or coin: shown, never a 0
                rows[s] = {"error": e.msg}
                continue
            px = c.price(s)
            rows[s] = {"status": sp["status"], "contractMultiplier": sp["ct_val"], "LOT_SIZE": sp["raw_lot"],
                       "lot_read_as": sp["lot_unit"], "step_contracts": sp["lot_sz"], "min_contracts": sp["min_sz"],
                       "max_contracts": sp["max_sz"], "tickSize": sp["tick_str"], "minNotional": sp["min_notional"],
                       "max_leverage": sp["max_leverage"], "min_order_usd": round(sp["min_qty"] * px, 4)}
            want = FIXED_LEVERAGE.get(s, DEFAULT_LEVERAGE)
            if sp.get("problem"):                           # e.g. no minQty: no new entry on it
                rows[s]["error"] = f"새 진입에 필요한 값 없음 → 새 진입 안 함: {sp['problem']}"
            elif sp["max_leverage"] is not None and sp["max_leverage"] < want:
                rows[s]["error"] = f"최대 {sp['max_leverage']:g}배라 {want}배를 못 씁니다"
        self._step("상품 정보(6개 코인이 있는지, TRADING, 단위; 최대 배수는 위험 한도 첫 단계)",
                   all("error" not in r and r["status"] == "Trading" for r in rows.values()), rows)
        self._step("요청 한도(exchangeInfo rateLimits, 봇은 80%까지만)", True,
                   {"source": c.limits_source, "weight": c.limits["weight"], "orders": c.limits["orders"]}, fatal=False)
        a = c.account()
        pos = c.positions()
        self._step("선물 계정 읽기", True, {"equity": a["totalMarginBalance"], "wallet": a["totalWalletBalance"],
                                         "unrealized": a["totalUnrealizedProfit"], "available": a["availableBalance"],
                                         "assets": a["assets"], "positions": [(p["symbol"], p["positionAmt"])
                                                                              for p in pos]})
        try:
            fee = c.fee_rate(self.symbol or next(iter(c.specs), "BTCUSDT"))
            self.fee_api = fee
            self._step("수수료율(API로 읽음, 편도: 진입·청산 테이커)", True,
                       {"open_taker_pct": round(fee["open_taker"] * 100, 4),
                        "close_taker_pct": round(fee["close_taker"] * 100, 4),
                        "open_maker_pct": round(fee["open_maker"] * 100, 4),
                        "close_maker_pct": round(fee["close_maker"] * 100, 4)}, fatal=False)
        except TestnetError as e:
            self._step("수수료율(API로 읽음, 편도)", False, str(e), fatal=False)
        left = {s: (len(c.open_orders(s)), len(c.open_algo_orders(s))) for s in self.symbols if "error" not in rows[s]
                or s in c.specs}
        self._step("열린 주문·손절(목록 읽기)", True, left)
        now = c.clock_ms() + c.offset_ms
        try:
            inc = c.income(None, None, now - 7 * 86_400_000, now)
            kinds = c.flow_types(now - 7 * 86_400_000, now)
            self._step("자금 기록 읽기(지난 7일: 펀딩 flowType 32, 이체 51; + 받음·들어옴 / - 냄·나감, 앱과 비교)", True,
                       {"funding_rows": len([r for r in inc if r["incomeType"] == "FUNDING_FEE"]),
                        "transfer_rows": len([r for r in inc if r["incomeType"] == "TRANSFER"]),
                        "last": [(r["incomeType"], r["income"], r["time"]) for r in inc[-3:]], "flow_types": kinds},
                       fatal=False)
        except TestnetError as e:
            self._step("자금 기록 읽기(지난 7일)", False, str(e), fatal=False)
        c.one_way()
        self._step("포지션: 한 코인에 한쪽만(롱·숏 동시 없음)", c.one_side, {"positions": len(pos)})
        levs = {}
        for s in self.symbols:
            if s not in c.specs:
                levs[s] = "상품 없음"
                continue
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
            self._step("키 확인(선물 계정 읽기, 두 분 확인 문구)", not probs, probs or (perm or {}).get("warnings"),
                       fatal=False)
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
        """The entry found by its client id: GET order (the executor's look-up), and again with its answer treated as
        lost, with how long it took to show; the lists are a note."""
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
        self._step("진입 주문을 우리 번호(newClientOrderId)로 찾음(GET order)",
                   got is not None and str(got.get("orderId")) == oid,
                   {"clientOrderId": ext, "orderId": (got or {}).get("orderId"), "want": oid, "seconds": delay,
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
        self._lists_note(s, ext, oid, stop=False)

    def _lists_note(self, s: str, ext: str, oid: str, stop: bool) -> None:
        """Only a note: does the open list / order history show the client id too? The look-up by client id (GET
        order, the step above) is what the executor relies on; the lists are its second try, and a real position is
        always read before anything is sent again. Not seen: what the lists show of it, for the owners to pass on."""
        c = self.client
        what = "손절 목록·손절 기록" if stop else "대기 목록·주문 기록"
        start = self.elapsed()
        try:
            row = self._until(lambda: next((r for r in c._open_rows(s, stop) + c._history_rows(s, stop)
                                            if r.get("clientOrderId") == ext), None), tries=10, pause=2.0)
        except TestnetError as e:
            self._note(f"참고: {what}을 읽지 못했습니다({e}). 위 [OK] 조회로 충분합니다")
            return
        waited = round(self.elapsed() - start, 1)
        if row is not None and str(row.get("orderId")) == oid:
            self._note(f"참고: {what}에도 같은 clientOrderId로 보입니다({waited}초)")
            return
        try:
            rows = c._open_rows(s, stop) + c._history_rows(s, stop)
            mine = next((r for r in rows if str(r.get("orderId")) == oid), None)
            seen = {"rows": len(rows), "found_by_orderId": mine is not None,
                    "clientOrderId_there": None if mine is None else mine.get("clientOrderId")}
        except TestnetError as e:
            seen = {"error": str(e)}
        self._note(f"참고: {waited}초 동안 {what}에서 clientOrderId {ext}가 안 보였습니다. 위 [OK] 조회(GET order)로 "
                   f"찾으므로 실거래에는 문제없습니다. 이 줄을 그대로 전달해 주세요: {seen}")

    def order_cycle(self) -> list:
        c = self.client
        s = self.symbol = self.symbol or self.smallest()
        buy, sell = ("BUY", "SELL") if self.side > 0 else ("SELL", "BUY")
        spec = c.spec(s)
        t0 = c.clock_ms() + c.offset_ms
        self._step(f"{s} 시작 전 포지션·주문·손절 없음", float(c.position(s)["positionAmt"]) == 0
                   and not c.open_orders(s) and not c.open_algo_orders(s), "포지션이 없고 주문이 없어야 합니다")
        w0 = float(c.account()["totalWalletBalance"])
        qty = self.drill_qty(spec, c.price(s))
        ext = ext_id(None)
        sent_s = self.elapsed()
        self.entry_sent, self.entry_qty = True, qty         # from here a stop part-way cleans up (only what it made)
        o = self._settle(s, c.market(s, buy, qty, client_id=ext))
        self._step(f"시장가 진입(LIMIT + priceType MARKET)이 다 체결됨(작은 주문: 약 ${DRILL_ORDER_USDT:.0f} 이상, 절반이 "
                   "최소 주문 이상)",
                   o.get("status") == "FILLED" and abs(float(o.get("executedQty") or 0) - qty) < spec["qty_step"] / 2
                   and not o.get("restCancelled"),
                   {"status": o.get("status"), "avg": o.get("avgPrice"), "qty": o.get("executedQty"),
                    "contracts": _num(c._contracts(s, qty)), "orderId": o.get("orderId"),
                    "rest_cancelled": bool(o.get("restCancelled")), "clientOrderId_len": len(ext)})
        self._found_by_cid(s, ext, str(o["orderId"]), sent_s)
        entry = float(o["avgPrice"])
        p = (self._until(lambda: (lambda x: x if float(x["positionAmt"]) else None)(c.position(s))) or c.position(s))
        amt = float(p["positionAmt"])
        want_lev = int(min(FIXED_LEVERAGE.get(s, DEFAULT_LEVERAGE), spec["max_leverage"] or 10 ** 6))
        value = _f(p.get("positionValue"), None) if p.get("positionValue") not in (None, "") else None
        units_ok = value is not None and abs(value - abs(amt) * entry) <= 0.02 * abs(amt) * entry + 0.01
        self._step("포지션 크기·방향·레버리지·격리(포지션 줄에서 읽음)", abs(amt - self.side * qty) < spec["qty_step"] / 2
                   and _int(p.get("leverage")) == c.lev.get(s, want_lev) and p.get("marginType") == "isolated",
                   {"positionAmt": amt, "qty": qty, "side": p.get("positionSide"), "leverage": p.get("leverage"),
                    "marginType": p.get("marginType"), "entryPrice": p.get("entryPrice")})
        self._step("수량 단위: 포지션 가치(positionValue) = 계약 수 × 계약 크기 × 가격",
                   units_ok, {"positionValue": p.get("positionValue"), "by_contracts": round(abs(amt) * entry, 6),
                              "contractMultiplier": spec["ct_val"],
                              "note": "1계약 = 1코인이라 이 시험으로는 단위를 가리지 못합니다(다른 코인으로 한 번 더)"
                              if Decimal(spec["ct_val"]) == 1 else ""})
        a1 = c.account()
        lev = _int(p.get("leverage")) or 1
        margin = abs(amt) * entry / lev
        w1, eq1 = float(a1["totalWalletBalance"]), float(a1["totalMarginBalance"])
        up = _f(p.get("unRealizedProfit"))
        self._step("잔고(balance)는 진입해도 증거금만큼 줄지 않고, 평가액 = 잔고 + 미실현 손익",
                   abs(w1 - w0) < 0.25 * margin and abs(eq1 - (w1 + up)) <= max(0.02, 1e-4 * abs(amt) * entry),
                   {"wallet_before": w0, "wallet_open": w1, "equity_open": eq1, "unrealized": up,
                    "margin": round(margin, 6), "available": a1["availableBalance"], "leverage": lev})
        stop1 = round_stop(entry * (1 - self.side * self.stop_frac), spec["tick"], self.side)
        key1 = ext_id(None)
        st1 = place_stop(c, s, sell, stop1, abs(amt), client_id=key1)
        stops = live_stops(c, s)
        self._step("손절이 투비트에 걸림(STOP, 청산 방향, 발동하면 시장가; 손절 목록에 보임)",
                   len(stops) == 1 and float(stops[0]["triggerPrice"]) == stop1 and covers(stops[0], amt),
                   {"stops": [(x["algoId"], x["triggerPrice"], x["quantity"], x.get("tbSide"), x.get("tbStatus"),
                               x.get("tbType")) for x in stops],
                    "level_field": c.level_field.get(st1["algoId"]), "listed_after_ms": c.list_delay_ms.get(
                        st1["algoId"])})
        got = c._find_stop_cid(s, key1, lists=False)
        self._step("손절을 우리 번호로 찾음(GET order type=STOP)", got is not None and str(got.get("orderId")) ==
                   st1["algoId"], {"found": (got or {}).get("orderId"), "want": st1["algoId"],
                                   "status": (got or {}).get("status")})
        c.forget_stop(key1)
        again = c.algo_order(client_id=key1)
        self._step("답을 잃은 손절 찾기(보낸 기록 없이 우리 번호로 - 실행기가 쓰는 길)", again.get("algoId") == st1["algoId"]
                   and again.get("algoStatus") == "NEW", {"found": again.get("algoId"), "want": st1["algoId"]})
        self._lists_note(s, key1, st1["algoId"], stop=True)
        # one reduce-only market close in every run while the full-size stop rests (the trigger test may close the
        # rest by itself): half of it
        mine = {str(o["orderId"])}
        part = round(abs(amt) / 2, 12)
        rest = abs(amt) - part
        x1 = self._settle(s, c.market(s, sell, part, reduce_only=True, client_id=ext_id(None)))
        p2 = self._until(lambda: (lambda x: x if abs(abs(float(x["positionAmt"])) - rest) < spec["qty_step"] / 2
                                  else None)(c.position(s))) or c.position(s)
        self._step(f"손절이 걸린 채로 줄이기 전용 시장가({CLOSE_SIDE[sell]})로 절반 청산(나머지는 손절 발동 시험이나 마지막 청산으로)",
                   x1.get("status") == "FILLED" and abs(float(x1.get("executedQty") or 0) - part) < spec["qty_step"] / 2
                   and abs(abs(float(p2["positionAmt"])) - rest) < spec["qty_step"] / 2
                   and float(p2["positionAmt"]) * self.side > 0,
                   {"status": x1.get("status"), "avg": x1.get("avgPrice"), "qty": x1.get("executedQty"),
                    "positionAmt": p2["positionAmt"], "available": p2.get("available"), "orderId": x1.get("orderId")})
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
        self._step("취소한 손절이 기록에 '취소'로 남음(CANCELED)", old.get("algoStatus") == "CANCELED",
                   {"status": old.get("algoStatus"), "tbStatus": old.get("tbStatus")}, fatal=False)
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
        self._step("포지션 없음, 주문·손절 없음", clean,
                   {"positionAmt": c.position(s)["positionAmt"], "orders": len(c.open_orders(s)),
                    "stops": len(c.open_algo_orders(s))})
        t1 = c.clock_ms() + c.offset_ms

        def pnl(only_mine: bool = True, with_pnl: bool = True):
            fills = [f for f in c.user_trades(s, t0 - 5_000, t1 + 5_000) if not only_mine or str(f["orderId"]) in mine]
            if not balanced(self.side, fills, spec["qty_step"]):
                return None
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
            w2 = float(c.account()["totalWalletBalance"])
            realized = sum(float(f["realizedPnl"]) for f in fills)
            fees = sum(float(f["commission"]) for f in fills)
            ins = [f for f in fills if f["side"] == buy]
            outs = [f for f in fills if f["side"] != buy]
            by_fills = self.side * (sum(float(f["qty"]) * float(f["price"]) for f in outs)
                                    - sum(float(f["qty"]) * float(f["price"]) for f in ins))
            n_in = sum(float(f["qty"]) * float(f["price"]) for f in ins)
            n_out = sum(float(f["qty"]) * float(f["price"]) for f in outs)
            notional = n_in + n_out
            funding = sum(float(r["income"]) for r in c.income(s, "FUNDING_FEE", t0 - 5_000, t1 + 5_000))
            tol = max(0.02, 2e-4 * notional)
            ok = (abs(realized - by_fills) <= max(1e-6, 1e-7 * notional) and fees > 0
                  and all(f.get("realizedSource") == "pnl" and f.get("realizedCheck") == "ok" for f in outs)
                  and abs((w2 - w0) - (realized - fees + funding)) <= tol)
            fee_in = sum(float(f["commission"]) for f in ins)
            fee_out = sum(float(f["commission"]) for f in outs)
            detail = {"fills": len(fills), "orders": sorted({str(f["orderId"]) for f in fills}),
                      "realized_toobit_pnl": round(realized, 6), "by_fill_prices": round(by_fills, 6),
                      "fees": round(fees, 6), "funding": round(funding, 6), "net": round(realized - fees + funding, 6),
                      "check": sorted({str(f.get("realizedCheck")) for f in outs}),
                      # paid fee per side, % of notional
                      "fee_rate_pct": round(100 * fees / notional, 4) if notional else None,
                      "open_fee_pct": round(100 * fee_in / n_in, 4) if n_in else None,
                      "close_fee_pct": round(100 * fee_out / n_out, 4) if n_out else None,
                      "wallet_change": round(w2 - w0, 6)}
        self._step("체결로 계산한 손익: 투비트 realizedPnl = 체결 가격 = 지갑 변화(수수료·펀딩 포함)", ok, detail)
        if fills:
            api = self.fee_api or {}
            same = all(detail.get(k) is not None and api.get(a) is not None
                       and abs(detail[k] / 100 - api[a]) <= 5e-5
                       for k, a in (("open_fee_pct", "open_taker"), ("close_fee_pct", "close_taker")))
            self._step("실제 수수료율 = 수수료율 API(진입·청산 테이커; 다르면 실제 값을 쓰세요)", same,
                       {"open_fee_pct": detail.get("open_fee_pct"), "close_fee_pct": detail.get("close_fee_pct"),
                        "api_open_taker_pct": round(100 * api["open_taker"], 4) if api.get("open_taker") is not None
                        else None,
                        "api_close_taker_pct": round(100 * api["close_taker"], 4) if api.get("close_taker") is not None
                        else None}, fatal=False)
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
                self._step("손절 발동 시험: 가격이 닿자 투비트가 포지션을 스스로 닫음", got.get("algoStatus") == "TRIGGERED",
                           {"status": got.get("algoStatus"), "tbStatus": got.get("tbStatus"),
                            "actualOrderId": got.get("actualOrderId")}, fatal=False)
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
        self._step("손절 발동 시험: 가격이 닿자 투비트가 포지션을 스스로 닫음", got.get("algoStatus") == "TRIGGERED",
                   {"stop": level, "status": got.get("algoStatus"), "tbStatus": got.get("tbStatus"),
                    "actualOrderId": got.get("actualOrderId")}, fatal=False)
        self._step("손절을 발동시킨 가격(마지막 가격 / 마크 가격)", True, trigger_source(self.side, level, seen),
                   fatal=False)
        self._fills_of_stop(s, sid, got)
        return got

    def _fired(self, sid: str) -> dict:
        return self._until(lambda: (lambda o: o if o.get("algoStatus") in ("TRIGGERED", "CANCELED", "REJECTED")
                                    else None)(self._algo_or_empty(sid)), tries=10, pause=1.5) \
            or self._algo_or_empty(sid)

    def _fills_of_stop(self, s: str, sid: str, got: dict) -> None:
        """Whose orderId the fired stop's fills carry: its own, or the order it placed (found by side and time)."""
        c = self.client
        now = c.clock_ms() + c.offset_ms
        try:
            rows = c._trades(s, now - 3_600_000, now + 5_000)
        except TestnetError as e:
            self._step("발동한 손절의 체결 찾기", False, str(e), fatal=False)
            return
        child = got.get("actualOrderId") or ""
        own = [r for r in rows if str(r.get("orderId")) == sid]
        theirs = [r for r in rows if child and child != sid and str(r.get("orderId")) == child]
        self._step("발동한 손절의 체결을 찾음(손절 자신의 orderId, 또는 손절이 낸 주문)", bool(own or theirs),
                   {"own_fills": len(own), "stop": sid, "child_order": child if child != sid else "",
                    "child_fills": len(theirs)}, fatal=False)

    def _algo_or_empty(self, sid: str) -> dict:
        try:
            return self.client.algo_order(algo_id=sid)
        except TestnetError:
            return {}


def cancel_own(c: ToobitClient, sym: str) -> None:
    """The drill's clean-up: cancel the stops and the orders that this client placed on the coin (never another's)."""
    for o in c.placed_stops(sym):
        try:
            c.cancel_algo(algo_id=o["algoId"])
        except TestnetError as e:
            if e.code not in NOT_FOUND or isinstance(e, TransientError):
                raise
    for o in c.open_orders(sym):
        if o.get("clientOrderId") in c.sent:
            try:
                c.cancel(sym, o["orderId"])
            except TestnetError as e:
                if e.code not in NOT_FOUND or isinstance(e, TransientError):
                    raise


def leave_flat(c: ToobitClient, sym: str, add, side: int, most: float) -> None:
    """After a drill stopped part-way, only once its own entry was sent: close what is left of the drill's position
    (reduce-only, at most ``most`` and only on the drill's ``side``), then, once the position reads flat, cancel the
    stops and orders the drill placed (cancel_own). A position that is still open keeps its stops. Each part on its
    own, so one failure does not skip the reading after it. ``add(step, ok, detail)`` records the result.
    One case of its own: a close Toobit refuses (a documented refusal) while the drill's own stops rest, as when a
    resting stop locks the position's closable quantity (``available``): those stops are cancelled, the close is sent
    once more at once, and if it is refused again each cancelled stop is placed again (the drill's tiny position is
    without its stop only for that moment, never left so)."""
    try:
        amt = float(c.position(sym)["positionAmt"])
        close = min(abs(amt), float(most)) if amt * side > 0 else 0.0
        if close:
            try:
                c.market(sym, "SELL" if amt > 0 else "BUY", close, reduce_only=True)
            except TestnetError as e:
                if not definite(e) or not c.placed_stops(sym):
                    raise
                _close_unlocked(c, sym, add, amt, close, e)
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


def _close_unlocked(c: ToobitClient, sym: str, add, amt: float, close: float, refused: TestnetError) -> None:
    """leave_flat's case of a refused close while the drill's own stops rest: cancel them, close at once, and place
    them again when the close is refused once more."""
    held = [(o["side"], float(o["triggerPrice"]), float(o["quantity"])) for o in c.placed_stops(sym)]
    add("정리: 청산이 거절됨(걸린 손절이 청산 수량을 묶는 듯): drill이 건 손절을 먼저 취소하고 바로 청산합니다", False,
        str(refused))
    for o in c.placed_stops(sym):
        c.cancel_algo(algo_id=o["algoId"])
    try:
        c.market(sym, "SELL" if amt > 0 else "BUY", close, reduce_only=True)
    except Exception:
        for side, trig, qty in held:           # never left without its stop
            place_stop(c, sym, side, trig, qty)
        raise


def specs_text(c: ToobitClient, symbols=COINS) -> str:
    lines = []
    for s in symbols:
        try:
            sp = c.spec(s)
        except TestnetError as e:                           # a missing unit or coin: said plainly, never a 0
            lines.append(f"{s}: 상품 정보를 쓸 수 없습니다(거래 안 함): {e.msg}")
            continue
        px = c.price(s)
        lev = f"{sp['max_leverage']:g}배" if sp["max_leverage"] else "?(위험 한도에 없음)"
        lot = sp["raw_lot"]
        lines.append(f"{s}: 상태 {sp['status']}, 1계약 {sp['ct_val']} {sp.get('base_coin') or ''}, 수량 단위 "
                     f"{sp['lot_sz']}계약, 최소 주문 {min_order_text(sp)}(지금 약 ${sp['min_qty'] * px:,.4f}), 한 번 최대 "
                     f"{sp['max_sz']}계약, 최소 금액 ${sp['min_notional']:g}, 가격 단위 {sp['tick_str']}, 최대 {lev} "
                     f"[LOT_SIZE 원래 값 stepSize {lot.get('stepSize')}, minQty {lot.get('minQty')}, maxQty "
                     f"{lot.get('maxQty')} → {'계약' if sp['lot_unit'] == 'contracts' else '코인'} 단위로 읽음]")
    lines.append(f"요청 한도({c.limits_source}): 가중치 {c.limits['weight']}, 주문 {c.limits['orders']} "
                 "((기간 ms, 한도) - 봇은 80%까지만)")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "drill", "reconcile", "specs"])
    ap.add_argument("--symbol", default=None, help="drill order coin (default: see ToobitDrill.smallest)")
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
    d = ToobitDrill(c, symbol=args.symbol, side=1 if args.side == "long" else -1, keycheck=kc,
                    trigger_test=not args.no_trigger_test, say=say)
    # a closed terminal (SIGHUP) or a stop (SIGTERM) mid-drill: leave the account flat before exiting
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _interrupt)
    return 0 if run_drill(c, d, args.cmd, args.confirm_order == DRILL_CONFIRM, signals=True) else 1


def run_drill(c: ToobitClient, d: ToobitDrill, cmd: str, confirmed: bool, pause=time.sleep,
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
