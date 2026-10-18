"""Bybit USDT perpetual futures (API v5, category "linear") for the executor: client, host allowlists, keys, key check,
drill. ``"exchange": "bybit"`` in the executor config uses it; the Binance path (paperbot/testnet.py, mainnet.py) is
unchanged.

    BYBIT_TESTNET_API_KEY=... BYBIT_TESTNET_API_SECRET=... python -m paperbot.bybit drill --symbol BTCUSDT --side long
    python -m paperbot.bybit reconcile --symbol BTCUSDT
    python -m paperbot.bybit specs                     # the 6 coins' live specs and risk limits (no order)

Sources (read as data, 2026-10-18): Bybit's v5 API docs (github.com/bybit-exchange/docs, commit 2bad003 of
2026-10-14: guide, order/*, position/*, account/*, market/*, user/apikey-info, enum, error, rate-limit) and the
official Python SDK pybit 5.17.0 (_http_manager.py: signing, query building). What only a live testnet run can
confirm is listed in docs/bybit-ko.md.

The client answers in the SAME shapes the executor reads from the Binance client (paperbot/testnet.py), so the
executor, the stop protocol (place_stop / move_stop / live_stops / covers) and livepnl run unchanged:

  Binance client call          Bybit v5
  spec(symbol)                 GET  /v5/market/instruments-info   lotSizeFilter.qtyStep/minOrderQty/minNotionalValue,
                                                                   priceFilter.tickSize, leverageFilter.maxLeverage
  leverage_brackets()          GET  /v5/market/risk-limit         (signal mode only)
  mark / price                 GET  /v5/market/tickers            markPrice / lastPrice
  sync_time                    GET  /v5/market/time               timeNano
  account()                    GET  /v5/account/wallet-balance    USDT walletBalance / unrealisedPnl (+ other coins)
  one_way()                    POST /v5/position/switch-mode      coin=USDT mode=0 (110025 "not modified" is fine)
  isolated(symbol)             GET  /v5/account/info; UTA: POST /v5/account/set-margin-mode ISOLATED_MARGIN (account
                               level); classic: POST /v5/position/switch-isolated tradeMode=1 (per symbol)
  leverage(symbol, n)          POST /v5/position/set-leverage     (110043 "not modified" is fine), then read back;
                               refused unless the margin is isolated
  market(...)                  POST /v5/order/create Market + orderLinkId (the client id), then the order is read
                               back (creation is asynchronous) by its id: /v5/order/realtime, else /v5/order/history
  order(symbol, id / cid)      GET  /v5/order/realtime, then /v5/order/history (orderId or orderLinkId)
  stop_close(...)              POST /v5/order/create Market, triggerPrice, triggerDirection (2 falls: a long's stop;
                               1 rises: a short's), triggerBy=LastPrice (= Binance workingType CONTRACT_PRICE),
                               reduceOnly=true, closeOnTrigger=true, its own orderLinkId
  algo_order / open_algo_orders GET /v5/order/realtime (orderFilter=StopOrder for the list)
  cancel_algo / cancel_all_algo POST /v5/order/cancel / cancel-all orderFilter=StopOrder
  cancel_all                   POST /v5/order/cancel-all orderFilter=Order
  position / positions         GET  /v5/position/list             size (always >= 0) and side Buy/Sell -> signed amount
  user_trades                  GET  /v5/execution/list (fills) + GET /v5/position/closed-pnl (avgEntryPrice of each
                               closing order) -> realizedPnl per fill; replayed from the fills when a record is missing
  income                       GET  /v5/account/transaction-log (UTA; classic: contract-transaction-log): SETTLEMENT ->
                               FUNDING_FEE, TRANSFER_IN/OUT -> TRANSFER, with the wallet ``change`` as income

Signing (guide.mdx, pybit): X-BAPI-SIGN = hex HMAC-SHA256(timestamp + api key + recv window + payload), payload = the
query string for GET (sent exactly as signed) and the raw JSON body for POST; headers X-BAPI-API-KEY,
X-BAPI-TIMESTAMP (ms), X-BAPI-RECV-WINDOW, X-BAPI-SIGN-TYPE=2. Answers are {retCode, retMsg, result, time}; retCode != 0
is an error even with HTTP 200. Errors map to the Binance client's classes: 10006/10018 and HTTP 429 -> RateLimited
(X-Bapi-Limit-Reset-Timestamp), HTTP 403 (IP banned >= 10 minutes) -> RateLimited with the 418 ban status, timeouts,
5xx, 10000/10016/10019 and retCode 429 -> TransientError (an order's outcome is then unknown and looked up by its
orderLinkId), 10002 -> the clock refusal (-1021), 110001 -> order not found (-2013), 110008/110010 -> already done
(-2011), 110092/110093 -> "would immediately trigger" (-2021).

Safety:
- ``BybitClient`` talks to api-testnet.bybit.com only, ``BybitMainnetClient`` to api.bybit.com / api.bytick.com only
  (class-level allowlists, https only, checked at construction; the executor checks again).
- Keys: BYBIT_TESTNET_API_KEY/SECRET (testnet), BYBIT_LIVE_API_KEY/SECRET (mainnet, behind the same switch
  PAPERBOT_LIVE_MAINNET=I_UNDERSTAND); never the paper runner's key nor any Binance key nor the other mode's key.
- Mainnet start gate: GET /v5/user/query-api (any key may read it) must show withdrawals off, contract trading on,
  an IP whitelist, nothing else (transfers, spot, options, earn, convert).
- A position's size is never read as 0 from a missing or garbled field (that would close the trade's record and
  cancel its stop): such an answer is an error.
- AI agents never import this module (tests/test_bybit.py checks it).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import json
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Callable, Optional

from .livepnl import balanced
from .mainnet import (FLAG, FLAG_VALUE, LIVE_KEY_NAMES as BINANCE_LIVE_KEY_NAMES, MODE_MAINNET, MODE_TESTNET,
                      PAPER_ENV_FILE, PAPER_KEY_NAMES, TESTNET_KEY_NAMES as BINANCE_TESTNET_KEY_NAMES, Refused,
                      read_env_file)
from .testnet import (BAD_TIMESTAMP, FIRED_ALGO, NOT_FOUND, WOULD_TRIGGER, ProtectionError, RateLimited, TestnetError,
                      TransientError, _round_down, cancel_everything, covers, hide_process_memory, live_stops,
                      move_stop, place_stop, round_stop, urllib_send)

CATEGORY = "linear"
SETTLE = "USDT"
BYBIT_TESTNET = "https://api-testnet.bybit.com"
BYBIT_TESTNET_HOSTS = ("api-testnet.bybit.com",)
BYBIT_MAINNET = "https://api.bybit.com"
BYBIT_MAINNET_HOSTS = ("api.bybit.com", "api.bytick.com")        # guide.mdx: both mainnet endpoints are available
TESTNET_KEY_NAMES = ("BYBIT_TESTNET_API_KEY", "BYBIT_TESTNET_API_SECRET")
LIVE_KEY_NAMES = ("BYBIT_LIVE_API_KEY", "BYBIT_LIVE_API_SECRET")
RECV_WINDOW = 5000
TRIGGER_BY = "LastPrice"            # the Binance path's stop triggers on the last price (workingType CONTRACT_PRICE)
WORKING_TYPE = {"LastPrice": "CONTRACT_PRICE", "MarkPrice": "MARK_PRICE", "IndexPrice": "INDEX_PRICE"}
# owners 2026-10-17: BTC 40x, the other coins 30x. Used only to switch a classic account's symbol to isolated before
# the first entry (the entry itself sets the paper account's leverage).
FIXED_LEVERAGE = {"BTCUSDT": 40}
DEFAULT_LEVERAGE = 30
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
PREFIX = {MODE_TESTNET: "[바이비트 테스트넷 실행기]", MODE_MAINNET: "[바이비트 실거래 실행기]"}

# retCodes (docs v5/error.mdx)
RATE_CODES = (10006, 10018)                    # too many visits / IP rate limit
TRANSIENT_CODES = (10000, 10016, 10019, 429)   # server timeout / server error / restarting / high load, retry
TIME_CODES = (10002,)                          # request time outside the recv window
NOT_FOUND_CODES = (110001,)                    # order does not exist
GONE_CODES = (110008, 110010)                  # order completed or cancelled / order cancelled
TRIGGER_CODES = (110092, 110093)               # expect Rising/Falling, but trigger_price <=/>= current
LEVERAGE_NOT_MODIFIED = 110043
MODE_NOT_MODIFIED = 110025
MARGIN_NOT_MODIFIED = 110026
UNIFIED = (3, 4, 5, 6)                         # unifiedMarginStatus: UTA 1.0 / 1.0 pro / 2.0 / 2.0 pro; 1 = classic

ORDER_STATUS = {"New": "NEW", "PartiallyFilled": "PARTIALLY_FILLED", "Untriggered": "NEW", "Triggered": "NEW",
                "Filled": "FILLED", "Cancelled": "CANCELED", "PartiallyFilledCanceled": "CANCELED",
                "Rejected": "REJECTED", "Deactivated": "EXPIRED"}
ORDER_FINAL = ("FILLED", "CANCELED", "REJECTED", "EXPIRED")
ORDER_WAITS = (0.05, 0.1, 0.2, 0.4)       # a market order is read back after these (creation is asynchronous)
SPAN_MS = 7 * 86_400_000                  # execution/closed-pnl/transaction-log: endTime - startTime <= 7 days
MAX_PAGES = 50
INCOME_TYPE = {"TRANSFER_IN": "TRANSFER", "TRANSFER_OUT": "TRANSFER", "SETTLEMENT": "FUNDING_FEE"}
FILL_TYPES_SKIPPED = ("Funding",)         # funding comes from the transaction log (income), never as a fill


def hosts_for(mode: str) -> tuple:
    return BYBIT_MAINNET_HOSTS if mode == MODE_MAINNET else BYBIT_TESTNET_HOSTS


# ---------------------------------------------------------------- numbers
def _dec(v, what: str = "value") -> Decimal:
    """A number the decision depends on (a size, a price): missing or garbled is an error, never 0."""
    if v is None or v == "":
        raise TransientError(200, None, f"Bybit 응답에 {what} 값이 없습니다")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError) as e:
        raise TransientError(200, None, f"Bybit 응답의 {what} 값이 이상합니다: {v!r}") from e
    if not d.is_finite():
        raise TransientError(200, None, f"Bybit 응답의 {what} 값이 이상합니다: {v!r}")
    return d


def _f(v, default: float = 0.0) -> float:
    """An informational number ("" or missing -> default)."""
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _num(d) -> str:
    """Decimal -> a plain number string like the Binance answers ("0.05", "-3", "0")."""
    d = Decimal(d)
    if d == 0:
        return "0"
    s = format(d.normalize(), "f")
    return s


def _floor_to(x: float, step: str) -> str:
    """``x`` floored to a multiple of ``step`` (a decimal string), formatted with the step's decimals: never more."""
    st = Decimal(step)
    n = (Decimal(repr(float(x))) / st + Decimal("1e-9")).to_integral_value(rounding=ROUND_FLOOR)
    return format((n * st).quantize(st), "f")


def _price_str(x: float, tick: str) -> str:
    """A price (already on the tick: round_stop) formatted with the tick's decimals."""
    t = Decimal(tick)
    n = (Decimal(repr(float(x))) / t).to_integral_value()
    return format((n * t).quantize(t), "f")


def _id60(*parts) -> int:
    """A stable integer id (60 bits: fits SQLite) for Bybit's string ids (execId, transaction-log id)."""
    return int(hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:15], 16)


_LINK_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def link_id(client_id: Optional[str]) -> str:
    """The orderLinkId for an executor client id: <= 36 characters of letters, digits, '-' and '_' (create-order.mdx).
    Deterministic, so a look-up after a lost answer finds the order by the same id."""
    if client_id is None:
        return "pb" + hashlib.sha1(f"{time.time_ns()}|{os.getpid()}".encode()).hexdigest()[:24]
    if 0 < len(client_id) <= 36 and set(client_id) <= _LINK_OK:
        return client_id
    return "pbh" + hashlib.sha1(client_id.encode()).hexdigest()[:30]


def _qv(v) -> str:
    if v is True or v is False:
        return "true" if v else "false"
    # cursors come back already URL-encoded ("page_args%3D...%26"): sent as they are (pybit does the same)
    return urllib.parse.quote(str(v), safe="%,:-._~*")


def _chunks(start_ms: int, end_ms: int, span: int = SPAN_MS - 1):
    lo = int(start_ms)
    end_ms = int(end_ms)
    while lo <= end_ms:
        hi = min(end_ms, lo + span)
        yield lo, hi
        lo = hi + 1


# ---------------------------------------------------------------- fills and realized P&L (pure)
def fills_from_executions(execs: list, closed: Optional[dict] = None) -> list:
    """Bybit executions (/v5/execution/list) -> Binance userTrades-like fills with ``realizedPnl``.

    Bybit's fills carry no realized P&L. Each fill that closes part of a position (``closedSize`` > 0) gets
    closedSize x (fill price - entry price) x position side, with the entry price of its order's record in
    /v5/position/closed-pnl (``closed``: orderId -> record; the exchange's own average entry). Without a record (it
    can lag the fill) the entry price is replayed from the fills before it, in time order; a fill that closes a
    position opened before the first fill of the list keeps realizedPnl 0 and ``realizedSource`` "unknown" (the
    executor only books its own orders, whose opening fills are in its window)."""
    closed = closed or {}
    out = []
    pos, avg = Decimal(0), Decimal(0)
    rows = sorted(execs, key=lambda e: (int(e.get("execTime") or 0), int(e.get("seq") or 0), str(e.get("execId"))))
    for e in rows:
        qty = _dec(e.get("execQty"), "execQty")
        px = _dec(e.get("execPrice"), "execPrice")
        sgn = 1 if e.get("side") == "Buy" else -1
        opposite = pos != 0 and (pos > 0) != (sgn > 0)
        cs = e.get("closedSize")
        cs = _dec(cs, "closedSize") if cs not in (None, "") else (min(qty, abs(pos)) if opposite else Decimal(0))
        cs = min(max(cs, Decimal(0)), qty)
        replay, known = Decimal(0), True
        if cs > 0:
            if opposite:
                k = min(cs, abs(pos))
                replay = k * (px - avg) * (1 if pos > 0 else -1)
                pos += sgn * k
                if pos == 0:
                    avg = Decimal(0)
                known = k == cs
            else:
                known = False
        opened = qty - cs
        if opened > 0:
            if pos == 0 or (pos > 0) == (sgn > 0):
                avg = (abs(pos) * avg + opened * px) / (abs(pos) + opened)
            pos += sgn * opened
        rec = closed.get(str(e.get("orderId")))
        entry = rec and rec.get("avgEntryPrice")
        if cs > 0 and entry not in (None, "", "0"):
            pside = 1 if rec.get("side") == "Sell" else -1          # the closing order's side: Sell closes a long
            realized, source = cs * (px - Decimal(str(entry))) * pside, "closed-pnl"
        elif cs > 0 and known:
            realized, source = replay, "replay"
        elif cs > 0:
            realized, source = Decimal(0), "unknown"
        else:
            realized, source = Decimal(0), "open"
        fee_cur = e.get("feeCurrency") or SETTLE
        out.append({"symbol": e.get("symbol"), "id": _id60("exec", e.get("execId")), "execId": e.get("execId"),
                    "orderId": e.get("orderId"), "orderLinkId": e.get("orderLinkId") or "",
                    "side": "BUY" if sgn > 0 else "SELL", "price": _num(px), "qty": _num(qty),
                    "quoteQty": str(e.get("execValue") or _num(px * qty)), "realizedPnl": _num(realized),
                    "realizedSource": source, "commission": str(e.get("execFee") or "0"),
                    "commissionAsset": fee_cur, "time": int(e.get("execTime") or 0), "maker": bool(e.get("isMaker")),
                    "closedSize": _num(cs), "execType": e.get("execType"), "positionSide": "BOTH",
                    "marginAsset": SETTLE})
    return out


def permission_record(r) -> Optional[dict]:
    """/v5/user/query-api -> the Binance apiRestrictions fields mainnet.check_permissions reads. None when the answer
    is not a key record (nothing verified)."""
    if not isinstance(r, dict) or not isinstance(r.get("permissions"), dict) or "readOnly" not in r:
        return None
    perms = r["permissions"]

    def has(group: str, name: Optional[str] = None) -> bool:
        v = perms.get(group) or []
        return bool(v) if name is None else name in v
    ips = [str(x).strip() for x in (r.get("ips") or []) if str(x).strip() and str(x).strip() != "*"]
    try:
        writable = int(r.get("readOnly")) == 0
    except (TypeError, ValueError):
        writable = False
    return {
        "enableReading": True,
        "enableWithdrawals": has("Wallet", "Withdraw"),
        "enableFutures": writable and ((has("ContractTrade", "Order") and has("ContractTrade", "Position"))
                                       or has("Derivatives", "DerivativesTrade")),
        "ipRestrict": bool(ips),
        "enableInternalTransfer": any(has("Wallet", x) for x in ("AccountTransfer", "SubMemberTransfer",
                                                                  "SubMemberTransferList")),
        "enableSpotAndMarginTrading": has("Spot"),
        "enableVanillaOptions": has("Options"),
        "otherPermissions": has("Earn") or has("Exchange"),
        "ips": ips, "uta": r.get("uta"), "isMaster": r.get("isMaster"), "readOnly": r.get("readOnly"),
    }


# ---------------------------------------------------------------- client
class BybitClient:
    """Signed REST client for Bybit v5 USDT perpetuals. This class talks to the TESTNET only (api-testnet.bybit.com);
    BybitMainnetClient to api.bybit.com / api.bytick.com. Answers are translated into the Binance client's shapes."""
    __test__ = False
    HOSTS: tuple = BYBIT_TESTNET_HOSTS
    DEFAULT_BASE = BYBIT_TESTNET
    KEY_NAMES = TESTNET_KEY_NAMES
    AGENT = "paperbot-bybit-testnet/0.1"
    EXCHANGE = "bybit"
    # a stop bigger than the position is replaced by one of the position's size (the executor's _cover): what Bybit
    # does with a triggered reduce-only order larger than the position is not documented
    EXACT_STOP_SIZE = True

    def __init__(self, api_key: str, api_secret: str, base: Optional[str] = None, send=None,
                 clock_ms: Callable[[], int] = lambda: int(time.time() * 1000),
                 on_request: Optional[Callable[[dict], None]] = None, sleep: Callable[[float], None] = time.sleep):
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
        self.on_request = on_request
        self.specs: dict = {}          # symbol -> instrument (live, cached for the process)
        self.tiers: dict = {}          # symbol -> risk limit tiers (live, cached)
        self.acct: Optional[dict] = None   # /v5/account/info (refreshed by one_way / isolated / leverage)
        self.order_symbol: dict = {}   # orderId -> symbol (a cancel needs the symbol)
        self.rl: dict = {}             # path -> (remaining, limit, reset ms) from the X-Bapi-Limit-* headers

    # ------------------------------------------------------------ transport
    def _note(self, path: str, hdr: dict) -> None:
        try:
            if "x-bapi-limit" in hdr and "x-bapi-limit-status" in hdr:
                self.rl[path] = (int(hdr["x-bapi-limit-status"]), int(hdr["x-bapi-limit"]),
                                 int(hdr.get("x-bapi-limit-reset-timestamp") or 0))
        except ValueError:
            pass

    def throttle_s(self, share: float = 0.8) -> float:
        """Seconds to wait before the next request: an endpoint with less than (1 - share) of its per-second limit left
        waits for its reset (at most 1 s: Bybit's windows are per second)."""
        now = self.clock_ms() + self.offset_ms
        wait = 0.0
        for remain, limit, reset in self.rl.values():
            if limit > 0 and remain <= (1 - share) * limit and reset > now:
                wait = max(wait, min(1.0, (reset - now) / 1000.0))
        return wait

    def _reset_wait(self, hdr: dict) -> float:
        try:
            reset = int(hdr.get("x-bapi-limit-reset-timestamp") or 0)
        except ValueError:
            reset = 0
        now = self.clock_ms() + self.offset_ms
        return max(1.0, min(10.0, (reset - now) / 1000.0)) if reset > now else 1.0

    def req(self, method: str, path: str, params: Optional[dict] = None, signed: bool = True):
        p = {k: v for k, v in (params or {}).items() if v is not None}
        audit = {"method": method, "path": path, "params": dict(p)}
        headers = {"User-Agent": self.AGENT, "Accept": "application/json"}
        if method == "GET":
            payload = "&".join(f"{k}={_qv(v)}" for k, v in sorted(p.items()))
            body = None
            url = f"{self.base}{path}" + (f"?{payload}" if payload else "")
        else:
            payload = json.dumps(p)
            body = payload.encode()
            url = f"{self.base}{path}"
            headers["Content-Type"] = "application/json"
        if signed:
            ts = str(int(self.clock_ms() + self.offset_ms))
            sign = hmac.new(self.secret.encode(), (ts + self.key + str(RECV_WINDOW) + payload).encode(),
                            hashlib.sha256).hexdigest()
            headers.update({"X-BAPI-API-KEY": self.key, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": str(RECV_WINDOW),
                            "X-BAPI-SIGN": sign, "X-BAPI-SIGN-TYPE": "2"})
        try:
            res = self.send(method, url, headers, body)
        except (OSError, http.client.HTTPException) as e:
            err = TransientError(0, None, f"network: {type(e).__name__}: {e}")
            self._audit(audit, err=err)
            raise err from e
        status, raw = res[0], res[1]
        hdr = {k.lower(): v for k, v in (res[2] if len(res) > 2 else {}).items()}
        self._note(path, hdr)
        try:
            data = json.loads(raw) if raw else None
        except ValueError:
            data = None
        rc = data.get("retCode") if isinstance(data, dict) else None
        msg = (data.get("retMsg") if isinstance(data, dict) else None) or str((raw or b"")[:200])
        if isinstance(rc, str) and rc.lstrip("-").isdigit():
            rc = int(rc)
        err: Optional[TestnetError] = None
        if status == 403:
            # rate-limit.mdx: "403, access too frequent": the IP is banned for at least 10 minutes (or a U.S. IP).
            # The executor's ban handling (status 418): never retried in the request, the loop waits.
            err = RateLimited(418, rc, f"HTTP 403 (IP 요청 과다로 10분 이상 차단, 또는 막힌 지역): {msg}", 600.0)
        elif status == 429 or rc in RATE_CODES:
            err = RateLimited(429, rc, msg or "rate limited", self._reset_wait(hdr))
        elif status >= 500 or status in (0, 408) or rc in TRANSIENT_CODES:
            err = TransientError(status, rc, msg or "server error")
        elif status != 200:
            err = TestnetError(status, rc, msg)
        elif not isinstance(data, dict) or not isinstance(rc, int):
            err = TransientError(status, None, f"응답이 Bybit 형식(retCode)이 아닙니다: {msg}"[:200])
        elif rc != 0:
            res_ = data.get("result")
            reasons = res_.get("reasons") if isinstance(res_, dict) else None
            text = f"{msg} (retCode {rc})" + (f" {json.dumps(reasons, ensure_ascii=False)}" if reasons else "")
            code = (BAD_TIMESTAMP if rc in TIME_CODES else NOT_FOUND[0] if rc in NOT_FOUND_CODES
                    else NOT_FOUND[1] if rc in GONE_CODES else WOULD_TRIGGER if rc in TRIGGER_CODES else rc)
            err = TestnetError(400, code, text)
            err.ret_code = rc
        self._audit(audit, status=status, data=data, err=err)
        if err is not None:
            raise err
        result = data.get("result")
        return result if isinstance(result, dict) else {}

    def _audit(self, audit: dict, status: int = 0, data=None, err: Optional[Exception] = None) -> None:
        if self.on_request is None:
            return
        audit.update(status=getattr(err, "status", status), error=None if err is None else str(err),
                     code=getattr(err, "code", None), data=data)
        try:
            self.on_request(audit)
        except Exception:  # noqa: BLE001  (an audit failure must not change order handling)
            pass

    def _pages(self, path: str, params: dict, signed: bool = True) -> list:
        """Every page of a cursor list. Too many pages raises: a partial list is never returned as complete."""
        out, cursor = [], None
        for _ in range(MAX_PAGES):
            p = dict(params)
            if cursor:
                p["cursor"] = cursor
            r = self.req("GET", path, p, signed=signed)
            rows = r.get("list") or []
            out += rows
            cursor = r.get("nextPageCursor")
            if not cursor or not rows:
                return out
        raise TransientError(0, None, f"{path}: 쪽이 {MAX_PAGES}개를 넘습니다")

    # ------------------------------------------------------------ market data
    def sync_time(self) -> int:
        t0 = self.clock_ms()
        r = self.req("GET", "/v5/market/time", signed=False)
        t1 = self.clock_ms()
        server = int(r["timeNano"]) // 1_000_000 if r.get("timeNano") else int(r["timeSecond"]) * 1000
        self.offset_ms = server - (t0 + t1) // 2
        return self.offset_ms

    def spec(self, symbol: str) -> dict:
        """The instrument's live spec (cached): the executor rounds sizes to qty_step and prices to tick."""
        r = self.req("GET", "/v5/market/instruments-info", {"category": CATEGORY, "symbol": symbol}, signed=False)
        row = next((x for x in r.get("list") or [] if x.get("symbol") == symbol), None)
        if row is None:
            raise TestnetError(400, "NO_SYMBOL", f"{symbol}: Bybit linear 종목에 없습니다")
        lot, pf, lf = row.get("lotSizeFilter") or {}, row.get("priceFilter") or {}, row.get("leverageFilter") or {}
        if (row.get("settleCoin") or SETTLE) != SETTLE:
            raise TestnetError(400, "NOT_USDT", f"{symbol}: USDT 정산 무기한 계약이 아닙니다({row.get('settleCoin')})")
        step, mn, tick = _dec(lot.get("qtyStep"), "qtyStep"), _dec(lot.get("minOrderQty"), "minOrderQty"), \
            _dec(pf.get("tickSize"), "tickSize")
        if step <= 0 or tick <= 0 or mn <= 0:
            raise TestnetError(400, "BAD_SPEC", f"{symbol}: 주문 단위 정보가 이상합니다 {lot} {pf}")
        info = {"qty_step": float(step), "min_qty": float(mn), "tick": float(tick),
                "min_notional": _f(lot.get("minNotionalValue")), "max_leverage": _f(lf.get("maxLeverage")),
                "leverage_step": _f(lf.get("leverageStep")), "max_market_qty": _f(lot.get("maxMktOrderQty")),
                "status": row.get("status"), "contract_type": row.get("contractType"), "base_coin": row.get("baseCoin"),
                "settle_coin": row.get("settleCoin") or SETTLE, "qty_step_str": str(lot["qtyStep"]),
                "tick_str": str(pf["tickSize"])}
        self.specs[symbol] = info
        return dict(info)

    def _spec(self, symbol: str) -> dict:
        return self.specs.get(symbol) or self.spec(symbol)

    def _ticker(self, symbol: str) -> dict:
        r = self.req("GET", "/v5/market/tickers", {"category": CATEGORY, "symbol": symbol}, signed=False)
        row = next((x for x in r.get("list") or [] if x.get("symbol") == symbol), None)
        if row is None:
            raise TransientError(200, None, f"{symbol}: 시세가 비어 있습니다")
        return row

    def mark(self, symbol: str) -> float:
        return float(_dec(self._ticker(symbol).get("markPrice"), "markPrice"))

    def price(self, symbol: str) -> float:
        """Last traded price: what the stops trigger on (triggerBy LastPrice)."""
        return float(_dec(self._ticker(symbol).get("lastPrice"), "lastPrice"))

    def risk_limits(self, symbol: str) -> list:
        """Risk limit tiers (/v5/market/risk-limit), cached. maintenanceMargin / initialMargin are read as ratios;
        when initialMargin x maxLeverage is about 100 they are percentages (the docs' example) and divided by 100."""
        if symbol in self.tiers:
            return self.tiers[symbol]
        rows = [x for x in self._pages("/v5/market/risk-limit", {"category": CATEGORY, "symbol": symbol},
                                       signed=False) if x.get("symbol") == symbol]
        rows.sort(key=lambda x: _f(x.get("riskLimitValue")))
        tiers = []
        for x in rows:
            im, mm, lev = _f(x.get("initialMargin")), _f(x.get("maintenanceMargin")), _f(x.get("maxLeverage"))
            scale = 100.0 if im * lev > 10 else 1.0
            tiers.append({"cap": _f(x.get("riskLimitValue")), "mmr": mm / scale, "imr": im / scale,
                          "max_leverage": lev, "deduction": x.get("mmDeduction")})
        if not tiers:
            raise TestnetError(400, "NO_RISK_LIMIT", f"{symbol}: 위험 한도 단계가 없습니다")
        self.tiers[symbol] = tiers
        return tiers

    def leverage_brackets(self) -> list:
        """Binance leverageBracket shape for paperbot/margin.Brackets (signal mode only)."""
        out = []
        for sym in sorted(self.specs) or COINS:
            floor, cum, prev_mmr, brackets = 0.0, 0.0, None, []
            for i, t in enumerate(self.risk_limits(sym), 1):
                if t["deduction"] not in (None, ""):
                    cum = _f(t["deduction"])
                elif prev_mmr is not None:
                    cum += floor * (t["mmr"] - prev_mmr)
                brackets.append({"bracket": i, "initialLeverage": int(t["max_leverage"]), "notionalCap": t["cap"],
                                 "notionalFloor": floor, "maintMarginRatio": t["mmr"], "cum": cum})
                floor, prev_mmr = t["cap"], t["mmr"]
            out.append({"symbol": sym, "brackets": brackets})
        return out

    # ------------------------------------------------------------ account
    def account_info(self) -> dict:
        self.acct = self.req("GET", "/v5/account/info")
        return self.acct

    def _uta(self) -> bool:
        info = self.acct if self.acct is not None else self.account_info()
        try:
            status = int(info.get("unifiedMarginStatus"))
        except (TypeError, ValueError):
            status = None
        if status == 1:
            return False
        if status in UNIFIED:
            return True
        raise TestnetError(400, "ACCOUNT_KIND", f"Bybit 계정 종류를 알 수 없습니다(unifiedMarginStatus={status!r})")

    def margin_mode(self) -> str:
        info = self.acct if self.acct is not None else self.account_info()
        return str(info.get("marginMode") or "")

    def account(self) -> dict:
        r = self.req("GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED" if self._uta() else "CONTRACT"})
        lst = r.get("list")
        if not isinstance(lst, list):
            raise TransientError(200, None, "지갑 응답에 list가 없습니다")
        coins = (lst[0].get("coin") if lst else None) or []
        usdt = next((c for c in coins if c.get("coin") == SETTLE), {})
        wallet, upl = _f(usdt.get("walletBalance")), _f(usdt.get("unrealisedPnl"))
        assets = [{"asset": c.get("coin"), "walletBalance": str(c.get("walletBalance") or "0")} for c in coins]
        if not usdt:
            assets.insert(0, {"asset": SETTLE, "walletBalance": "0"})
        if _f(usdt.get("bonus")) > 0:                       # a bonus is not the budget's money
            assets.append({"asset": "BONUS", "walletBalance": str(usdt.get("bonus"))})
        return {"totalWalletBalance": str(wallet), "totalUnrealizedProfit": str(upl),
                "totalMarginBalance": str(wallet + upl), "assets": assets,
                "accountType": (lst[0].get("accountType") if lst else None)}

    def one_way(self) -> None:
        """One-way position mode (positionIdx 0) for every USDT perpetual without a position or order."""
        try:
            self.req("POST", "/v5/position/switch-mode", {"category": CATEGORY, "coin": SETTLE, "mode": 0})
        except TestnetError as e:
            if getattr(e, "ret_code", None) != MODE_NOT_MODIFIED:
                raise

    def _busy(self) -> bool:
        """Any position or open order (USDT perpetuals)?"""
        if self.positions():
            return True
        r = self.req("GET", "/v5/order/realtime", {"category": CATEGORY, "settleCoin": SETTLE, "limit": 1})
        return bool(r.get("list"))

    def isolated(self, symbol: str) -> None:
        """Isolated margin. Unified account (UTA): account-wide, POST /v5/account/set-margin-mode ISOLATED_MARGIN;
        classic account: per symbol, POST /v5/position/switch-isolated. Not possible while positions or orders exist:
        TestnetError -4048 (the executor warns, keeps protecting, and leverage() refuses every new entry until it is
        isolated). Not possible for any other reason: Refused (the executor does not start)."""
        info = self.account_info()
        if not self._uta():
            lev = str(FIXED_LEVERAGE.get(symbol, DEFAULT_LEVERAGE))
            try:
                self.req("POST", "/v5/position/switch-isolated", {"category": CATEGORY, "symbol": symbol,
                                                                  "tradeMode": 1, "buyLeverage": lev,
                                                                  "sellLeverage": lev})
            except (TransientError, RateLimited):
                raise
            except TestnetError as e:
                if getattr(e, "ret_code", None) == MARGIN_NOT_MODIFIED:
                    return None
                if self._busy():
                    raise TestnetError(e.status, -4048, f"{symbol}: 포지션·주문이 있어 격리 마진으로 못 바꿨습니다: {e.msg}")
                raise Refused(f"Bybit {symbol}을 격리 마진으로 바꿀 수 없어 거래하지 않습니다: {e.msg}") from e
            return None
        if info.get("marginMode") == "ISOLATED_MARGIN":
            return None
        why = ""
        try:
            self.req("POST", "/v5/account/set-margin-mode", {"setMarginMode": "ISOLATED_MARGIN"})
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            if getattr(e, "ret_code", None) != MARGIN_NOT_MODIFIED:
                why = e.msg
        if self.account_info().get("marginMode") == "ISOLATED_MARGIN":
            return None
        if self._busy():
            raise TestnetError(400, -4048, f"포지션·주문이 있어 계정을 격리 마진으로 못 바꿨습니다(지금 "
                                           f"{self.margin_mode()}): {why}")
        raise Refused(f"Bybit 계정을 격리 마진(ISOLATED_MARGIN)으로 바꿀 수 없어 거래하지 않습니다(지금 {self.margin_mode()}). "
                      f"{why}".strip())

    def leverage(self, symbol: str, lev: int) -> dict:
        """Set the symbol's leverage and read it back. Refused (TestnetError) unless the margin is isolated: the
        executor never opens a position in cross margin. A unified account still in cross margin (it could not be
        switched at the start because something was open) is switched here when nothing is open any more."""
        lev = int(lev)
        spec = self._spec(symbol)
        if spec.get("max_leverage") and lev > spec["max_leverage"]:
            raise TestnetError(400, "LEVERAGE_MAX", f"{symbol}: 레버리지 {lev}배가 최대 {spec['max_leverage']:g}배를 넘습니다")
        info = self.account_info()
        if self._uta():
            if info.get("marginMode") != "ISOLATED_MARGIN":
                try:                       # not switched at the start (something was open then): once more now
                    self.isolated(symbol)
                except (TransientError, RateLimited):
                    raise
                except (TestnetError, Refused) as e:
                    raise TestnetError(400, "NOT_ISOLATED", f"계정이 격리 마진이 아닙니다(지금 {self.margin_mode()}): "
                                                            f"진입하지 않습니다. {e}") from e
                if self.margin_mode() != "ISOLATED_MARGIN":
                    raise TestnetError(400, "NOT_ISOLATED", f"계정이 격리 마진이 아닙니다(지금 {self.margin_mode()}): "
                                                            "진입하지 않습니다")
        else:
            try:
                self.req("POST", "/v5/position/switch-isolated", {"category": CATEGORY, "symbol": symbol,
                                                                  "tradeMode": 1, "buyLeverage": str(lev),
                                                                  "sellLeverage": str(lev)})
            except TestnetError as e:
                if getattr(e, "ret_code", None) != MARGIN_NOT_MODIFIED:
                    raise
        try:
            self.req("POST", "/v5/position/set-leverage", {"category": CATEGORY, "symbol": symbol,
                                                           "buyLeverage": str(lev), "sellLeverage": str(lev)})
        except TestnetError as e:
            if getattr(e, "ret_code", None) != LEVERAGE_NOT_MODIFIED:
                raise
        rows = self.req("GET", "/v5/position/list", {"category": CATEGORY, "symbol": symbol}).get("list") or []
        got = [_f(r.get("leverage")) for r in rows if int(r.get("positionIdx") or 0) == 0]
        if not got or abs(got[0] - lev) > 1e-9:
            raise TestnetError(400, "LEVERAGE_MISMATCH", f"{symbol}: 레버리지를 {lev}배로 맞추지 못했습니다(읽은 값 {got})")
        return {"symbol": symbol, "leverage": lev, "marginType": "isolated"}

    # ------------------------------------------------------------ orders
    def _order_dict(self, row: dict) -> dict:
        st = ORDER_STATUS.get(row.get("orderStatus"), row.get("orderStatus") or "")
        avg = row.get("avgPrice")
        return {"orderId": row.get("orderId"), "clientOrderId": row.get("orderLinkId") or "",
                "symbol": row.get("symbol"), "side": str(row.get("side") or "").upper(),
                "type": str(row.get("orderType") or "").upper(), "origQty": str(row.get("qty") or "0"),
                "executedQty": str(row.get("cumExecQty") or "0"), "avgPrice": str(avg) if avg not in (None, "") else "0",
                "status": st, "reduceOnly": bool(row.get("reduceOnly")), "time": int(row.get("createdTime") or 0),
                "updateTime": int(row.get("updatedTime") or 0), "bybitStatus": row.get("orderStatus"),
                "cancelType": row.get("cancelType"), "rejectReason": row.get("rejectReason")}

    def _find(self, symbol: Optional[str], order_id=None, link: Optional[str] = None) -> dict:
        """The order (any status) by orderId or orderLinkId: /v5/order/realtime, else /v5/order/history.
        TestnetError -2013 when neither knows it."""
        p = {"category": CATEGORY}
        p.update({"symbol": symbol} if symbol else {"settleCoin": SETTLE})
        if order_id is not None:
            p["orderId"] = str(order_id)
        else:
            p["orderLinkId"] = link
        rows = self.req("GET", "/v5/order/realtime", p).get("list") or []
        row = self._match(rows, order_id, link)
        if row is None:
            row = self._match(self.req("GET", "/v5/order/history", p).get("list") or [], order_id, link)
        if row is None:
            raise TestnetError(404, NOT_FOUND[0], "Order does not exist.")
        if row.get("orderId") and row.get("symbol"):
            self.order_symbol[row["orderId"]] = row["symbol"]
        return row

    @staticmethod
    def _match(rows: list, order_id, link):
        for r in rows:
            if (order_id is not None and str(r.get("orderId")) == str(order_id)) or \
                    (order_id is None and link and r.get("orderLinkId") == link):
                return r
        return None

    def market(self, symbol: str, side: str, qty: float, reduce_only: bool = False,
               client_id: Optional[str] = None) -> dict:
        """Market order, then read back until it is final (creation is asynchronous). Not final after the reads:
        returned as it is (NEW), the executor settles it from the position."""
        spec = self._spec(symbol)
        q = _floor_to(qty, spec["qty_step_str"])
        if Decimal(q) <= 0:
            raise TestnetError(400, "QTY_ZERO", f"{symbol}: 수량 {qty}이 최소 단위보다 작습니다")
        link = link_id(client_id)
        body = {"category": CATEGORY, "symbol": symbol, "side": "Buy" if side == "BUY" else "Sell",
                "orderType": "Market", "qty": q, "positionIdx": 0, "orderLinkId": link}
        if reduce_only:
            body["reduceOnly"] = True
        r = self.req("POST", "/v5/order/create", body)
        oid = r.get("orderId")
        if not oid:
            raise TransientError(200, None, "주문 번호가 없는 응답(결과 모름)")
        self.order_symbol[oid] = symbol
        o = None
        for w in (0.0,) + ORDER_WAITS:
            if w:
                self.sleep(w)
            try:
                o = self._order_dict(self._find(symbol, order_id=oid))
            except TestnetError as e:
                if e.code not in NOT_FOUND or isinstance(e, TransientError):
                    raise
                o = None
            if o is not None and o["status"] in ORDER_FINAL:
                break
        if o is None:
            o = {"orderId": oid, "clientOrderId": link, "symbol": symbol, "side": side, "type": "MARKET",
                 "origQty": q, "executedQty": "0", "avgPrice": "0", "status": "NEW", "reduceOnly": reduce_only}
        return o

    def order(self, symbol: str, order_id=None, client_id: Optional[str] = None) -> dict:
        return self._order_dict(self._find(symbol, order_id=order_id,
                                           link=None if order_id is not None else link_id(client_id)))

    def cancel(self, symbol: str, order_id) -> dict:
        return self.req("POST", "/v5/order/cancel", {"category": CATEGORY, "symbol": symbol, "orderId": str(order_id)})

    def cancel_all(self, symbol: str) -> dict:
        r = self.req("POST", "/v5/order/cancel-all", {"category": CATEGORY, "symbol": symbol, "orderFilter": "Order"})
        return {"code": 200, "msg": "ok", "cancelled": len(r.get("list") or [])}

    def open_orders(self, symbol: str) -> list:
        rows = self._pages("/v5/order/realtime", {"category": CATEGORY, "symbol": symbol, "orderFilter": "Order",
                                                  "limit": 50})
        return [self._order_dict(r) for r in rows]

    # ------------------------------------------------------------ conditional (stop) orders
    def _algo_dict(self, row: dict) -> dict:
        side = str(row.get("side") or "").upper()
        st = row.get("orderStatus")
        sot = row.get("stopOrderType") or ""
        direction = int(row.get("triggerDirection") or 0)
        market = row.get("orderType") == "Market"
        closing = bool(row.get("reduceOnly")) or bool(row.get("closeOnTrigger"))
        protective = (side == "SELL" and direction == 2) or (side == "BUY" and direction == 1)
        if sot in ("StopLoss", "PartialStopLoss"):
            kind = "STOP_MARKET" if market else "STOP"
        elif sot in ("TakeProfit", "PartialTakeProfit"):
            kind = "TAKE_PROFIT_MARKET" if market else "TAKE_PROFIT"
        elif sot == "TrailingStop":
            kind = "TRAILING_STOP_MARKET"
        elif market and closing and protective:
            kind = "STOP_MARKET"
        elif market and closing:
            kind = "TAKE_PROFIT_MARKET"
        else:
            kind = "CONDITIONAL"
        executed = _f(row.get("cumExecQty"))
        if st == "Untriggered":
            status = "NEW"
        elif st in ("Triggered", "New", "PartiallyFilled"):
            status = "TRIGGERING"                        # triggered: the same order id is now an active order
        elif st == "Filled" or (st in ("Cancelled", "PartiallyFilledCanceled") and executed > 0):
            status = "FINISHED"
        elif st == "Rejected":
            status = "REJECTED"
        else:
            status = "CANCELED"                          # Cancelled, Deactivated
        qty = str(row.get("qty") or "0")
        close_all = _f(qty) == 0 or (sot in ("StopLoss", "TakeProfit") and row.get("tpslMode") == "Full")
        return {"algoId": row.get("orderId"), "clientAlgoId": row.get("orderLinkId") or "",
                "symbol": row.get("symbol"), "side": side, "orderType": kind, "algoType": "CONDITIONAL",
                "triggerPrice": str(row.get("triggerPrice") or "0"), "quantity": qty, "closePosition": close_all,
                "reduceOnly": bool(row.get("reduceOnly")), "closeOnTrigger": bool(row.get("closeOnTrigger")),
                "workingType": WORKING_TYPE.get(row.get("triggerBy"), row.get("triggerBy") or ""),
                "priceProtect": False, "algoStatus": status, "bybitStatus": st, "stopOrderType": sot,
                "triggerDirection": direction,
                "actualOrderId": row.get("orderId") if status in FIRED_ALGO else "",
                "actualQty": str(row.get("cumExecQty") or "0"), "actualPrice": str(row.get("avgPrice") or ""),
                "createTime": int(row.get("createdTime") or 0)}

    def stop_close(self, symbol: str, side: str, trigger: float, qty: Optional[float] = None,
                   client_id: Optional[str] = None) -> dict:
        """Protective stop resting on the exchange: a conditional reduce-only, close-on-trigger market order,
        triggered by the LAST price. With ``qty``: that quantity (two can coexist while a stop is moved); without:
        qty "0" = close the whole position (create-order.mdx)."""
        spec = self._spec(symbol)
        trig = _price_str(trigger, spec["tick_str"])
        if qty is None:
            q = "0"
        else:
            q = _floor_to(qty, spec["qty_step_str"])
            if Decimal(q) <= 0:                          # never "0": that would be close-all, not this size
                raise TestnetError(400, "QTY_ZERO", f"{symbol}: 손절 수량 {qty}이 최소 단위보다 작습니다")
        link = link_id(client_id)
        body = {"category": CATEGORY, "symbol": symbol, "side": "Sell" if side == "SELL" else "Buy",
                "orderType": "Market", "qty": q, "triggerPrice": trig, "triggerDirection": 2 if side == "SELL" else 1,
                "triggerBy": TRIGGER_BY, "reduceOnly": True, "closeOnTrigger": True, "positionIdx": 0,
                "orderLinkId": link}
        try:
            r = self.req("POST", "/v5/order/create", body)
        except (TransientError, RateLimited):
            raise
        except TestnetError as e:
            raise self._would_trigger(e, symbol, side, float(trig)) from e
        oid = r.get("orderId")
        if not oid:
            raise TransientError(200, None, "손절 주문 번호가 없는 응답(결과 모름)")
        self.order_symbol[oid] = symbol
        return {"algoId": oid, "clientAlgoId": link, "symbol": symbol, "side": side, "orderType": "STOP_MARKET",
                "algoType": "CONDITIONAL", "triggerPrice": trig, "quantity": q, "closePosition": qty is None,
                "reduceOnly": True, "closeOnTrigger": True, "workingType": WORKING_TYPE[TRIGGER_BY],
                "algoStatus": "NEW"}

    def _would_trigger(self, e: TestnetError, symbol: str, side: str, trig: float) -> TestnetError:
        """110092/110093, or any other refusal while the last price is already past the trigger: the executor's
        "would immediately trigger" (-2021: close at market). Anything else stays as it was."""
        if e.code == WOULD_TRIGGER:
            return e
        try:
            last = self.price(symbol)
        except TestnetError:
            return e
        if (side == "SELL" and last <= trig) or (side == "BUY" and last >= trig):
            return TestnetError(e.status, WOULD_TRIGGER, f"Order would immediately trigger (Bybit: {e.msg}; 마지막 "
                                                         f"가격 {last:g}, 손절 {trig:g})")
        return e

    def algo_order(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        sym = self.order_symbol.get(algo_id) if algo_id is not None else None
        return self._algo_dict(self._find(sym, order_id=algo_id,
                                          link=None if algo_id is not None else link_id(client_id)))

    def cancel_algo(self, algo_id=None, client_id: Optional[str] = None) -> dict:
        sym = self.order_symbol.get(algo_id) if algo_id is not None else None
        if sym is None:                                  # a cancel needs the symbol: look the order up first
            sym = self.algo_order(algo_id=algo_id, client_id=client_id)["symbol"]
        body = {"category": CATEGORY, "symbol": sym}
        if algo_id is not None:
            body["orderId"] = str(algo_id)
        else:
            body["orderLinkId"] = link_id(client_id)
        r = self.req("POST", "/v5/order/cancel", body)
        return {"algoId": r.get("orderId") or algo_id, "clientAlgoId": r.get("orderLinkId") or "", "code": "200",
                "msg": "success"}

    def open_algo_orders(self, symbol: str) -> list:
        rows = self._pages("/v5/order/realtime", {"category": CATEGORY, "symbol": symbol, "orderFilter": "StopOrder",
                                                  "limit": 50})
        out = []
        for r in rows:
            if r.get("orderId") and r.get("symbol"):
                self.order_symbol[r["orderId"]] = r["symbol"]
            out.append(self._algo_dict(r))
        return out

    def cancel_all_algo(self, symbol: str) -> dict:
        r = self.req("POST", "/v5/order/cancel-all", {"category": CATEGORY, "symbol": symbol,
                                                      "orderFilter": "StopOrder"})
        return {"code": 200, "msg": "ok", "cancelled": len(r.get("list") or [])}

    # ------------------------------------------------------------ positions
    def _position_dict(self, symbol: str, rows: list) -> dict:
        amt, main = Decimal(0), None
        for r in rows:
            size = _dec(r.get("size"), "size")
            if size == 0:
                continue
            side = r.get("side")
            if side not in ("Buy", "Sell"):
                raise TransientError(200, None, f"{symbol}: 포지션 방향이 이상합니다({side!r}, 크기 {size})")
            amt += size if side == "Buy" else -size
            main = main or r
        main = main or rows[0]
        mm = self.margin_mode() if self.acct is not None else ""
        return {"symbol": symbol, "positionAmt": _num(amt), "entryPrice": str(main.get("avgPrice") or "0"),
                "markPrice": str(main.get("markPrice") or "0"), "liquidationPrice": str(main.get("liqPrice") or "0"),
                "unRealizedProfit": str(main.get("unrealisedPnl") or "0"), "leverage": str(main.get("leverage") or ""),
                "marginType": "isolated" if mm == "ISOLATED_MARGIN" else ("cross" if mm else ""),
                "positionIdx": main.get("positionIdx"), "positionStatus": main.get("positionStatus"),
                "updateTime": int(main.get("updatedTime") or 0)}

    def position(self, symbol: str) -> dict:
        rows = [r for r in self.req("GET", "/v5/position/list", {"category": CATEGORY, "symbol": symbol}).get("list")
                or [] if r.get("symbol") == symbol]
        if not rows:   # position-list returns the symbol's row even when flat: an empty answer is not "flat"
            raise TransientError(200, None, f"{symbol}: 포지션 응답이 비어 있습니다")
        return self._position_dict(symbol, rows)

    def positions(self) -> list:
        """Every symbol with a non-zero position (settleCoin=USDT lists only those)."""
        rows = self._pages("/v5/position/list", {"category": CATEGORY, "settleCoin": SETTLE, "limit": 200})
        by: dict = {}
        for r in rows:
            by.setdefault(r.get("symbol"), []).append(r)
        out = [self._position_dict(s, rs) for s, rs in by.items() if s]
        return [p for p in out if float(p["positionAmt"]) != 0]

    # ------------------------------------------------------------ fills, P&L, funding, transfers
    def closed_pnl(self, symbol: str, start_ms: int, end_ms: int) -> list:
        out = []
        for lo, hi in _chunks(start_ms, end_ms):
            out += self._pages("/v5/position/closed-pnl", {"category": CATEGORY, "symbol": symbol, "startTime": lo,
                                                           "endTime": hi, "limit": 100})
        return out

    def user_trades(self, symbol: str, start_ms: int, end_ms: int, limit: int = 1000) -> list:
        """Account fills (Binance userTrades shape): price, qty, realizedPnl (see fills_from_executions), commission
        (execFee: + paid, - rebate), commissionAsset, orderId, side, time. Funding executions are left out."""
        execs, seen = [], set()
        for lo, hi in _chunks(start_ms, end_ms):
            for e in self._pages("/v5/execution/list", {"category": CATEGORY, "symbol": symbol, "startTime": lo,
                                                        "endTime": hi, "limit": 100}):
                if e.get("execType") in FILL_TYPES_SKIPPED or e.get("symbol") != symbol or e.get("execId") in seen:
                    continue
                seen.add(e.get("execId"))
                execs.append(e)
        closed = {}
        if any(_f(e.get("closedSize")) > 0 or e.get("closedSize") in (None, "") for e in execs):
            for rec in self.closed_pnl(symbol, start_ms, int(end_ms) + 60_000):
                closed[str(rec.get("orderId"))] = rec
        return fills_from_executions(execs, closed)

    def income(self, symbol: Optional[str], income_type: Optional[str], start_ms: int, end_ms: int,
               limit: int = 1000) -> list:
        """Wallet changes in the Binance income shape: SETTLEMENT -> FUNDING_FEE, TRANSFER_IN/OUT -> TRANSFER (other
        types keep their Bybit name). ``income`` is the transaction log's ``change`` (the wallet change: + received)."""
        uta = self._uta()
        path = "/v5/account/transaction-log" if uta else "/v5/account/contract-transaction-log"
        base = {"limit": 50}
        if uta:
            base["accountType"] = "UNIFIED"
        if symbol:
            base["baseCoin"] = self._spec(symbol).get("base_coin") or symbol[:-len(SETTLE)]
            if uta:
                base["category"] = CATEGORY
        if income_type == "FUNDING_FEE":
            base["type"] = "SETTLEMENT"
        rows = []
        for lo, hi in _chunks(start_ms, end_ms):
            rows += self._pages(path, {**base, "startTime": lo, "endTime": hi})
        out, seen = [], set()
        for r in rows:
            if symbol and r.get("symbol") != symbol:
                continue
            kind = r.get("type") or ""
            if r.get("change") not in (None, ""):
                change = _dec(r.get("change"), "change")
            else:                                         # change = cashFlow + funding - fee (UTA), - funding (classic)
                fund = Decimal(str(r.get("funding") or 0))
                change = (Decimal(str(r.get("cashFlow") or 0)) + (fund if uta else -fund)
                          - Decimal(str(r.get("fee") or 0)))
            tid = _id60("log", r.get("id"), kind, r.get("transactionTime"), r.get("tradeId"), r.get("symbol"),
                        r.get("change"))
            if tid in seen:
                continue
            seen.add(tid)
            row = {"symbol": r.get("symbol") or "", "incomeType": INCOME_TYPE.get(kind, kind), "income": _num(change),
                   "asset": r.get("currency") or SETTLE, "time": int(r.get("transactionTime") or 0), "tranId": tid,
                   "info": kind, "tradeId": r.get("tradeId") or ""}
            if income_type is None or row["incomeType"] == income_type:
                out.append(row)
        return out


class BybitMainnetClient(BybitClient):
    """The same client for real money: api.bybit.com (or api.bytick.com) only."""
    __test__ = False
    HOSTS = BYBIT_MAINNET_HOSTS
    DEFAULT_BASE = BYBIT_MAINNET
    KEY_NAMES = LIVE_KEY_NAMES
    AGENT = "paperbot-bybit-live/0.1"


class BybitKeyCheckClient(BybitClient):
    """Reads the key's own permissions (GET /v5/user/query-api, any key may). Places nothing."""
    __test__ = False
    HOSTS = BYBIT_MAINNET_HOSTS
    DEFAULT_BASE = BYBIT_MAINNET
    KEY_NAMES = LIVE_KEY_NAMES
    AGENT = "paperbot-bybit-live/0.1"

    def api_restrictions(self):
        return permission_record(self.req("GET", "/v5/user/query-api"))


# ---------------------------------------------------------------- keys, allowlists, the executor's clients
def _values(env, names) -> set:
    return {str((env or {}).get(n) or "").strip() for n in names} - {""}


def trading_keys(mode: str, env, paper_env=None) -> tuple[str, str]:
    """The Bybit key pair this mode may trade with, or Refused. Testnet: BYBIT_TESTNET_*; mainnet: BYBIT_LIVE_* behind
    PAPERBOT_LIVE_MAINNET=I_UNDERSTAND. Never the paper runner's key, a Binance key, or the other mode's key."""
    paper = _values(env, PAPER_KEY_NAMES) | _values(paper_env, PAPER_KEY_NAMES)
    binance = _values(env, BINANCE_LIVE_KEY_NAMES + BINANCE_TESTNET_KEY_NAMES)
    if mode == MODE_MAINNET:
        if (env.get(FLAG) or "") != FLAG_VALUE:
            raise Refused(f"실거래 스위치가 꺼져 있습니다: 환경 변수 {FLAG}={FLAG_VALUE} 가 필요합니다")
        names, other, other_text = LIVE_KEY_NAMES, _values(env, TESTNET_KEY_NAMES), "바이비트 테스트넷 키(BYBIT_TESTNET_*)"
    elif mode == MODE_TESTNET:
        names, other, other_text = TESTNET_KEY_NAMES, _values(env, LIVE_KEY_NAMES), "바이비트 실거래 키(BYBIT_LIVE_*)"
    else:
        raise Refused(f"mode={mode!r}: testnet 또는 mainnet만 있습니다")
    key, secret = (str(env.get(n) or "").strip() for n in names)
    if not (key and secret):
        raise Refused(f"{names[0]} / {names[1]} 가 비어 있습니다")
    if key == secret:
        raise Refused(f"{names[0]}와 {names[1]}가 같습니다")
    if {key, secret} & paper:
        raise Refused(f"{names[0]}/{names[1]}가 paper 실행기의 읽기 전용 키(BINANCE_API_KEY)와 같습니다")
    if {key, secret} & binance:
        raise Refused(f"{names[0]}/{names[1]}가 바이낸스 키(LIVE_*/TESTNET_*)와 같습니다. 거래소마다 다른 키를 씁니다")
    if {key, secret} & other:
        raise Refused(f"{names[0]}/{names[1]}가 {other_text}와 같습니다. 모드마다 다른 키를 씁니다")
    return key, secret


def refuse_unless_allowed(mode: str, client) -> None:
    """The client must be the Bybit client class of the mode and point at that mode's hosts."""
    host = urllib.parse.urlparse(getattr(client, "base", "") or "").hostname or ""
    if mode == MODE_TESTNET:
        if host not in BYBIT_TESTNET_HOSTS or type(client) is not BybitClient \
                or tuple(type(client).HOSTS) != BYBIT_TESTNET_HOSTS:
            raise Refused(f"주소 {host!r}: 바이비트 testnet 모드는 api-testnet.bybit.com 외에는 연결하지 않습니다")
    elif mode == MODE_MAINNET:
        if host not in BYBIT_MAINNET_HOSTS or not isinstance(client, BybitMainnetClient) \
                or tuple(type(client).HOSTS) != BYBIT_MAINNET_HOSTS:
            raise Refused(f"주소 {host!r}: 바이비트 mainnet 모드는 api.bybit.com·api.bytick.com 외에는 연결하지 않습니다")
    else:
        raise Refused(f"mode={mode!r}: testnet/mainnet 외의 모드는 시작하지 않습니다")


def check_executor_keys(mode: str, client, keycheck, env, paper_env) -> None:
    """The executor's key gates for Bybit (Executor.__init__)."""
    if mode == MODE_MAINNET:
        key, secret = trading_keys(MODE_MAINNET, env, paper_env)
        if (client.key, client.secret) != (key, secret):
            raise Refused("바이비트 실거래 실행기의 키가 BYBIT_LIVE_API_KEY/BYBIT_LIVE_API_SECRET와 다릅니다")
        if not isinstance(keycheck, BybitKeyCheckClient) or (keycheck.key, keycheck.secret) != (key, secret):
            raise Refused("바이비트 실거래는 키 권한 확인(/v5/user/query-api)을 거쳐야 시작합니다")
        return
    reused = _values(env, PAPER_KEY_NAMES + BINANCE_LIVE_KEY_NAMES + BINANCE_TESTNET_KEY_NAMES + LIVE_KEY_NAMES)
    reused |= _values(paper_env, PAPER_KEY_NAMES)
    if {client.key, client.secret} & reused:
        raise Refused("바이비트 테스트넷 키가 paper 키·바이낸스 키·바이비트 실거래 키와 같습니다. 테스트넷 전용 키를 쓰세요")


def clients(mode: str, env, paper_env=None, host: Optional[str] = None):
    """(order client, key-permission client or None) for the mode, keys from the environment."""
    key, secret = trading_keys(mode, env, paper_env)
    base = f"https://{host}" if host else None
    if mode == MODE_MAINNET:
        return BybitMainnetClient(key, secret, base=base), BybitKeyCheckClient(key, secret, base=base)
    return BybitClient(key, secret, base=base), None


# ---------------------------------------------------------------- drill (testnet)
def reconcile(c: BybitClient, symbol: str, stop_price: Optional[float] = None) -> dict:
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


@dataclass
class BybitDrill:
    """The testnet drill (paperbot/testnet.py Drill) on Bybit, plus: isolated margin and leverage read back, the entry
    found by its orderLinkId, and the fills' P&L checked against Bybit's own closed-pnl record."""
    client: BybitClient
    symbol: str
    side: int = 1
    notional: float = 200.0
    leverage: int = 40
    stop_frac: float = 0.01
    wait: Callable[[float], None] = time.sleep
    log: list = field(default_factory=list)

    def _step(self, name: str, ok: bool, detail) -> None:
        self.log.append({"step": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    def _stops(self) -> list:
        return live_stops(self.client, self.symbol)

    def _until(self, check, tries: int = 10, pause: float = 0.3):
        """Cancels and fills are asynchronous on Bybit: look again a few times."""
        for _ in range(tries):
            got = check()
            if got:
                return got
            self.wait(pause)
        return check()

    def run(self) -> list:
        c, s = self.client, self.symbol
        buy, sell = ("BUY", "SELL") if self.side > 0 else ("SELL", "BUY")
        t0 = c.clock_ms() + c.offset_ms
        spec = c.spec(s)
        self._step("clean start", float(c.position(s)["positionAmt"]) == 0 and not c.open_orders(s)
                   and not c.open_algo_orders(s), "position must be flat and no open (or conditional) orders")
        c.one_way()
        c.isolated(s)
        lev = c.leverage(s, self.leverage)
        mode = c.account_info().get("marginMode") if c._uta() else "classic"
        self._step("isolated margin and leverage", int(lev["leverage"]) == self.leverage
                   and mode in ("ISOLATED_MARGIN", "classic"), {"leverage": lev["leverage"], "marginMode": mode})
        mark = c.mark(s)
        qty = max(_round_down(self.notional / mark, spec["qty_step"]), spec["min_qty"])
        while spec["min_notional"] and qty * mark < spec["min_notional"]:
            qty = round(qty + spec["qty_step"], 12)
        cid = link_id(None)
        o = c.market(s, buy, qty, client_id=cid)
        for _ in range(20):
            if o.get("status") == "FILLED":
                break
            self.wait(0.5)
            o = c.order(s, order_id=o["orderId"])
        self._step("entry filled", o.get("status") == "FILLED", {"status": o.get("status"), "avg": o.get("avgPrice")})
        found = c.order(s, client_id=cid)
        self._step("entry found by its client id (orderLinkId)", found.get("orderId") == o["orderId"],
                   {"orderLinkId": cid, "orderId": found.get("orderId")})
        entry = float(o["avgPrice"])
        amt = float(c.position(s)["positionAmt"])
        self._step("position size", abs(amt - self.side * qty) < spec["qty_step"] / 2, {"positionAmt": amt, "qty": qty})
        stop1 = round_stop(entry * (1 - self.side * self.stop_frac), spec["tick"], self.side)
        st1 = place_stop(c, s, sell, stop1, abs(amt), client_id=link_id(None))
        stops = self._stops()
        self._step("stop rests on exchange (conditional, last price, reduce-only, close on trigger)",
                   len(stops) == 1 and float(stops[0]["triggerPrice"]) == stop1
                   and stops[0].get("workingType") == "CONTRACT_PRICE" and stops[0].get("reduceOnly")
                   and stops[0].get("closeOnTrigger") and covers(stops[0], amt),
                   [(x["algoId"], x["triggerPrice"], x.get("workingType"), x.get("quantity")) for x in stops])
        stop2 = round_stop(entry * (1 - self.side * self.stop_frac / 2), spec["tick"], self.side)
        seen = {}
        orig = c.cancel_algo

        def watch_cancel(algo_id=None, client_id=None):
            seen.setdefault("during", len(self._stops()))
            return orig(algo_id=algo_id, client_id=client_id)
        c.cancel_algo = watch_cancel
        try:
            mv = move_stop(c, s, sell, stop2, abs(amt), [st1["algoId"]], client_id=link_id(None))
        finally:
            c.cancel_algo = orig
        stops = self._until(lambda: (lambda x: x if len(x) == 1 else None)(self._stops())) or self._stops()
        self._step("stop moved without a gap", mv["result"] == "moved" and seen.get("during") == 2 and len(stops) == 1
                   and stops[0]["algoId"] == mv["stop"]["algoId"],
                   {"during": seen.get("during"), "after": [(x["algoId"], x["triggerPrice"]) for x in stops]})
        c.cancel_algo(algo_id=mv["stop"]["algoId"])
        self._until(lambda: not self._stops())
        rep = reconcile(c, s, stop_price=stop2)
        self._step("restart check restores a missing stop", rep["repaired"] and len(self._stops()) == 1, rep)
        last = c.price(s)
        bad = round_stop(last * (1 + self.side * 0.02), spec["tick"], self.side)
        mv = move_stop(c, s, sell, bad, abs(amt), [x["algoId"] for x in self._stops()], close_id=link_id(None))
        self._step("stop past the price is refused (110092/110093) and the position closed at market",
                   mv["result"] == "closed", {k: mv.get(k) for k in ("result", "error")})
        cancel_everything(c, s)
        clean = self._until(lambda: float(c.position(s)["positionAmt"]) == 0 and not c.open_orders(s)
                            and not c.open_algo_orders(s))
        self._step("flat and no orders left", clean,
                   {"positionAmt": c.position(s)["positionAmt"], "orders": len(c.open_orders(s)),
                    "conditional": len(c.open_algo_orders(s))})
        close_id = (mv.get("close") or {}).get("orderId")
        mine = {str(o["orderId"]), str(close_id)}
        t1 = c.clock_ms() + c.offset_ms

        def pnl():
            fills = [f for f in c.user_trades(s, t0 - 5_000, t1 + 5_000) if str(f["orderId"]) in mine]
            recs = [r for r in c.closed_pnl(s, t0 - 5_000, t1 + 60_000) if str(r.get("orderId")) == str(close_id)]
            if not (balanced(self.side, fills, spec["qty_step"]) and recs
                    and all(f["realizedSource"] == "closed-pnl" for f in fills if float(f["closedSize"]) > 0)):
                return None
            return fills, recs[0]
        got = self._until(pnl, tries=8, pause=1.0)
        detail: dict = {"fills": None, "closed_pnl": None}
        ok = False
        if got:
            fills, rec = got
            realized = sum(float(f["realizedPnl"]) for f in fills)
            fees = sum(float(f["commission"]) for f in fills)
            pside = 1 if rec.get("side") == "Sell" else -1
            gross = (_f(rec.get("avgExitPrice")) - _f(rec.get("avgEntryPrice"))) * _f(rec.get("closedSize")) * pside
            tol = max(0.02, 1e-4 * abs(qty) * entry)
            # the record's own numbers: gross = (exit - entry) x size; closedPnl = gross - open fee - close fee
            ok = abs(realized - gross) <= tol and abs((realized - fees) - _f(rec.get("closedPnl"))) <= tol
            detail = {"fills": len(fills), "realized": round(realized, 6), "fees": round(fees, 6),
                      "net": round(realized - fees, 6), "bybit_gross": round(gross, 6),
                      "bybit_closedPnl": rec.get("closedPnl"), "bybit_openFee": rec.get("openFee"),
                      "bybit_closeFee": rec.get("closeFee")}
        self._step("fills and P&L read back = Bybit closed-pnl (realized, fees, net)", ok, detail)
        return self.log


def specs_text(c: BybitClient, symbols=COINS) -> str:
    lines = []
    for s in symbols:
        sp = c.spec(s)
        tiers = c.risk_limits(s)
        lines.append(f"{s}: 수량 단위 {sp['qty_step_str']}, 최소 {sp['min_qty']:g}, 최소 금액 ${sp['min_notional']:g}, "
                     f"가격 단위 {sp['tick_str']}, 최대 {sp['max_leverage']:g}배, 상태 {sp['status']}; 위험 한도 1단계 "
                     f"${tiers[0]['cap']:,.0f}까지 최대 {tiers[0]['max_leverage']:g}배, 유지 증거금 {tiers[0]['mmr']:.2%}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["drill", "reconcile", "specs"])
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--side", choices=["long", "short"], default="long")
    ap.add_argument("--notional", type=float, default=200.0)
    ap.add_argument("--leverage", type=int, default=40)
    args = ap.parse_args(argv)
    try:      # testnet only: never the paper runner's key, a Binance key or the Bybit mainnet key
        key, secret = trading_keys(MODE_TESTNET, os.environ, read_env_file(PAPER_ENV_FILE))
    except Refused as e:
        print(f"시작하지 않습니다: {e}", file=sys.stderr)
        return 2
    c = BybitClient(key, secret)
    c.sync_time()
    if args.cmd == "specs":
        print(specs_text(c))
        return 0
    if args.cmd == "reconcile":
        print(json.dumps(reconcile(c, args.symbol), indent=1))
        return 0
    d = BybitDrill(c, args.symbol, 1 if args.side == "long" else -1, args.notional, args.leverage)
    try:
        d.run()
        ok = True
    except (AssertionError, TestnetError, ProtectionError, Refused) as e:
        d.log.append({"step": "stopped", "ok": False, "detail": str(e)})
        ok = False
        try:                              # leave the testnet account flat
            amt = float(c.position(args.symbol)["positionAmt"])
            if amt:
                c.market(args.symbol, "SELL" if amt > 0 else "BUY", abs(amt), reduce_only=True)
            cancel_everything(c, args.symbol)
        except TestnetError:
            pass
    for row in d.log:
        print(("[OK]  " if row["ok"] else "[FAIL]") + f" {row['step']}: {row['detail']}")
    return 0 if ok else 1


if __name__ == "__main__":
    hide_process_memory()
    sys.exit(main())
