"""Gate (api.gateio.ws) USDT perpetual futures: the client of the 게이트 봇 (owners 10-31, docs/gate-bot-ko.md).

The 게이트 봇 has no trading rule: a friend enters by hand on their own Gate account, and the bot only puts the stop
and the take-profit ladder on each position (paperbot/gateguard.py). This module is the exchange connection only:
the signed requests, the reads it needs and three writes (a stop, its cancel, a market close).

Sources (read as data, 10-31; Gate's web docs were not reachable from here): Gate's own Python SDK gate-api 7.2.172
(PyPI), its api_client.gen_sign and the futures models' field descriptions. Base https://api.gateio.ws/api/v4. A signed
request carries the headers KEY, Timestamp (Unix seconds) and SIGN = hex HMAC-SHA512(secret, METHOD "\\n" path
(with /api/v4) "\\n" query string "\\n" hex SHA-512 of the body ("" without one) "\\n" Timestamp). An error answers a
4xx with {"label": ..., "message": ...}.

  call                 Gate
  server_time          GET  /spot/time {server_time: ms} (public)
  contract(c)          GET  /futures/usdt/contracts/{c}: quanto_multiplier, order_price_round (the tick), status,
                       taker_fee_rate (public)
  candles(c, ...)      GET  /futures/usdt/candlesticks: interval, ``limit`` OR ``from`` / ``to`` (seconds, never
                       both), <= 2000 rows; each {t (open, s), o, h, l, c}; the newest row is the forming one; the last
                       price's candles (a "mark_" prefix would give the mark price's)
  last_price(c)        GET  /futures/usdt/tickers?contract= ``last``
  account()            GET  /futures/usdt/accounts: in_dual_mode, position_mode (single / dual / dual_plus)
  detail()             GET  /account/detail: ip_whitelist (the key's IP binding)
  positions()          GET  /futures/usdt/positions?holding=true: size (a string: decimal sizes; < 0 = short),
                       entry_price, leverage ("0" = cross: cross_leverage_limit), liq_price ("for reference only"),
                       mode (single / dual_long / dual_short), pos_margin_mode, open_time (s)
  taker_fee(c)         GET  /futures/usdt/fee?contract= {c: {taker_fee, maker_fee}}
  price_orders(...)    GET  /futures/usdt/price_orders?status=open[&contract=]; price_order(id) GET .../{id}:
                       status open / finished / inactive / invalid, finish_as cancelled / succeeded / failed / expired
  place_stop(...)      POST /futures/usdt/price_orders: initial {contract, size 0, price "0", tif "ioc", close true}
                       (the whole position at the moment it fires, at market: "When fully closing a position in
                       single-position mode, close must be set to true"), trigger {strategy_type 0, price_type 0 (the
                       last price), price, rule 2 (<=, a long's stop: "Trigger.Price must < last_price") or 1 (>=, a
                       short's: "must > last_price"), expiration 0}; answered {id}. No order_type: a plain price order,
                       not the position TP/SL the friend sets on the app (one of each per position there).
  cancel_stop(id)      DELETE /futures/usdt/price_orders/{id}
  close_market(c)      POST /futures/usdt/orders {contract, size 0, price "0", tif "ioc", close true, text "t-..."}:
                       the whole position at market ("a price of 0 with tif ioc represents a market order")
  closes(c, since)     GET  /futures/usdt/position_close: pnl (fees and funding in it), pnl_fee, side, time,
                       first_open_time

What only the first live position can confirm (docs/gate-bot-ko.md): that Gate takes the stop exactly as above (the
SDK's descriptions, not a live answer) and shows it in the app's 조건부 주문 list, that two such stops can rest at once
for a moment (a moved stop: the new one first, then the old one cancelled), and the text Gate fills in a price order
(read here only as data: our orders are known by the ids Gate answered).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Optional

BASE = "https://api.gateio.ws"
PREFIX = "/api/v4"
HOSTS = ("api.gateio.ws", "fx-api.gateio.ws")
SETTLE = "usdt"
KEY_NAMES = ("GATE_LIVE_KEY", "GATE_LIVE_SECRET")
KEY_CHECKED = "GATE_LIVE_KEY_CHECKED"
KEY_CHECKED_VALUE = "FUTURES_ONLY_NO_WITHDRAW_IP_BOUND"
AGENT = "paperbot-gate/0.1"
RULE_GE, RULE_LE = 1, 2            # trigger when the price is >= / <= the trigger price
PRICE_LAST = 0                     # price_type 0: the last trade price
CONTRACT_TTL_S = 300.0


class GateError(Exception):
    """A request that did not give a usable answer."""

    def __init__(self, msg: str, status: Optional[int] = None, label: Optional[str] = None) -> None:
        super().__init__(msg)
        self.status, self.label = status, label


class GateRefused(GateError):
    """Gate answered with an error label (a 4xx other than 429): the request did not run."""


class GateUnknown(GateError):
    """No readable answer (a timeout, a 5xx, a 429, a body that is not JSON): a write may or may not have run."""


def sign(secret: str, method: str, path: str, query: str, body: str, ts: str) -> str:
    """Gate APIv4's SIGN header (the SDK's gen_sign)."""
    payload = hashlib.sha512(body.encode("utf-8")).hexdigest()
    text = f"{method}\n{path}\n{query}\n{payload}\n{ts}"
    return hmac.new(secret.encode("utf-8"), text.encode("utf-8"), hashlib.sha512).hexdigest()


def fnum(x: Any) -> Optional[float]:
    """A Gate number (they come as strings) or None."""
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def price_text(price: float, tick: str) -> str:
    """``price`` written with the tick's decimals (the tick as Gate wrote it, e.g. "0.01")."""
    try:
        q = Decimal(str(tick)).normalize()
        places = max(0, -q.as_tuple().exponent)
        return f"{Decimal(repr(float(price))).quantize(Decimal(1).scaleb(-places)):f}"
    except (InvalidOperation, ValueError):
        return repr(float(price))


def http_send(method: str, url: str, headers: dict, body: Optional[str], timeout: float) -> tuple[int, str]:
    """One HTTPS request: (status, body text). Network failures raise OSError."""
    data = body.encode("utf-8") if body else None
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:                 # noqa: S310 (host allowlisted)
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


class GateClient:
    """Gate USDT perpetual futures. ``send`` (tests) replaces the HTTPS call: send(method, url, headers, body, timeout)
    -> (status, text)."""
    __test__ = False

    def __init__(self, key: str = "", secret: str = "", base: str = BASE,
                 send: Optional[Callable[..., tuple[int, str]]] = None,
                 clock: Optional[Callable[[], float]] = None, timeout: float = 10.0) -> None:
        host = urllib.parse.urlparse(base).hostname or ""
        if host not in HOSTS:
            raise ValueError(f"주소 {host!r}: 게이트 봇은 {'·'.join(HOSTS)} 외에는 연결하지 않습니다")
        self.key, self.secret, self.base = key, secret, base.rstrip("/")
        self.send = send or http_send
        self.clock = clock or time.time
        self.timeout = float(timeout)
        self.offset_s = 0.0
        self._contracts: dict = {}

    # ------------------------------------------------------------------ transport
    def req(self, method: str, path: str, query: Optional[dict] = None, body: Any = None, signed: bool = True) -> Any:
        q = urllib.parse.urlencode([(k, v) for k, v in (query or {}).items() if v is not None])
        full = PREFIX + path
        data = "" if body is None else json.dumps(body, separators=(",", ":"))
        headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": AGENT}
        if signed:
            if not (self.key and self.secret):
                raise GateRefused("게이트 키가 없습니다", None, "NO_KEY")
            ts = str(int(self.clock() + self.offset_s))
            headers.update({"KEY": self.key, "Timestamp": ts,
                            "SIGN": sign(self.secret, method, full, urllib.parse.unquote_plus(q), data, ts)})
        url = self.base + full + ("?" + q if q else "")
        try:
            status, text = self.send(method, url, headers, data or None, self.timeout)
        except (OSError, TimeoutError, ValueError) as e:
            raise GateUnknown(f"{method} {path}: 응답 없음 ({type(e).__name__}: {e})") from None
        try:
            js = json.loads(text) if text and text.strip() else None
        except ValueError:
            js, bad = None, True
        else:
            bad = False
        if 200 <= int(status) < 300:
            if bad:
                raise GateUnknown(f"{method} {path}: JSON이 아닌 응답 ({text[:120]!r})", int(status))
            return js
        label = js.get("label") if isinstance(js, dict) else None
        msg = (js.get("message") if isinstance(js, dict) else None) or (text or "")[:200]
        if int(status) == 429 or int(status) >= 500 or not label:
            raise GateUnknown(f"{method} {path}: HTTP {status} {label or ''} {msg}".strip(), int(status), label)
        raise GateRefused(f"{method} {path}: {label}: {msg}", int(status), str(label))

    # ------------------------------------------------------------------ public
    def server_time(self) -> float:
        js = self.req("GET", "/spot/time", signed=False)
        t = fnum((js or {}).get("server_time")) if isinstance(js, dict) else None
        if not t:
            raise GateUnknown(f"/spot/time: 서버 시각을 못 읽음 ({js!r})")
        return t / 1000.0

    def sync_time(self) -> float:
        t0 = self.clock()
        st = self.server_time()
        t1 = self.clock()
        self.offset_s = st - (t0 + t1) / 2.0
        return self.offset_s

    def now(self) -> float:
        return self.clock() + self.offset_s

    def contract(self, c: str) -> dict:
        hit = self._contracts.get(c)
        if hit and self.clock() - hit["read"] < CONTRACT_TTL_S:
            return hit
        js = self.req("GET", f"/futures/{SETTLE}/contracts/{c}", signed=False)
        if not isinstance(js, dict):
            raise GateUnknown(f"{c} 계약 정보를 못 읽음 ({js!r})")
        tick_s = str(js.get("order_price_round") or "")
        tick = fnum(tick_s)
        if not tick or tick <= 0:
            raise GateError(f"{c} 계약의 가격 단위(order_price_round)를 못 읽음 ({tick_s!r})")
        out = {"name": c, "tick": tick, "tick_s": tick_s, "mult": fnum(js.get("quanto_multiplier")),
               "status": js.get("status") or "", "taker": fnum(js.get("taker_fee_rate")), "read": self.clock()}
        self._contracts[c] = out
        return out

    def candles(self, c: str, interval: str, start_s: Optional[int] = None, end_s: Optional[int] = None,
                limit: Optional[int] = None) -> list[tuple[int, float, float, float, float]]:
        """[(open ms, open, high, low, close)] oldest first, each minute once. ``limit`` or ``start_s``/``end_s``."""
        q: dict = {"contract": c, "interval": interval}
        if limit is not None:
            q["limit"] = int(limit)
        else:
            q["from"] = int(start_s) if start_s is not None else None
            q["to"] = int(end_s) if end_s is not None else None
        js = self.req("GET", f"/futures/{SETTLE}/candlesticks", q, signed=False)
        if not isinstance(js, list):
            raise GateUnknown(f"{c} {interval} 캔들 응답이 목록이 아닙니다 ({str(js)[:120]})")
        rows = {}
        for r in js:
            if not isinstance(r, dict):
                raise GateError(f"{c} 캔들 한 줄을 못 읽음 ({r!r})")
            t, o, h, l, cl = (fnum(r.get(k)) for k in ("t", "o", "h", "l", "c"))
            if t is None or None in (o, h, l, cl) or not (h >= l > 0):
                raise GateError(f"{c} 캔들 한 줄을 못 읽음 ({r!r})")
            rows[int(t) * 1000] = (int(t) * 1000, o, h, l, cl)
        return [rows[k] for k in sorted(rows)]

    def last_price(self, c: str) -> float:
        js = self.req("GET", f"/futures/{SETTLE}/tickers", {"contract": c}, signed=False)
        row = js[0] if isinstance(js, list) and js and isinstance(js[0], dict) else {}
        px = fnum(row.get("last"))
        if not px or px <= 0:
            raise GateUnknown(f"{c} 현재가를 못 읽음 ({str(js)[:120]})")
        return px

    # ------------------------------------------------------------------ private reads
    def account(self) -> dict:
        js = self.req("GET", f"/futures/{SETTLE}/accounts")
        if not isinstance(js, dict):
            raise GateUnknown(f"선물 계정을 못 읽음 ({str(js)[:120]})")
        return js

    def detail(self) -> dict:
        js = self.req("GET", "/account/detail")
        return js if isinstance(js, dict) else {}

    def positions(self) -> list[dict]:
        """The open positions: {contract, side (+1 / -1), size (abs), entry, lev, liq, mode, margin_mode, open_s}."""
        js = self.req("GET", f"/futures/{SETTLE}/positions", {"holding": "true"})
        if not isinstance(js, list):
            raise GateUnknown(f"포지션 목록을 못 읽음 ({str(js)[:120]})")
        out = []
        for p in js:
            if not isinstance(p, dict) or not p.get("contract"):
                raise GateError(f"포지션 한 줄을 못 읽음 ({p!r})")
            size = fnum(p.get("size"))
            if size is None:
                raise GateError(f"{p.get('contract')} 포지션 수량을 못 읽음 ({p.get('size')!r})")
            if size == 0:
                continue
            lev = fnum(p.get("leverage")) or 0.0
            cross = lev <= 0 or str(p.get("pos_margin_mode") or "") == "cross"
            if lev <= 0:
                lev = fnum(p.get("cross_leverage_limit")) or fnum(p.get("lever")) or 0.0
            out.append({"contract": str(p["contract"]), "side": 1 if size > 0 else -1, "size": abs(size),
                        "entry": fnum(p.get("entry_price")) or 0.0, "lev": lev, "cross": cross,
                        "liq": fnum(p.get("liq_price")) or 0.0, "mode": str(p.get("mode") or "single"),
                        "open_s": int(fnum(p.get("open_time")) or 0), "margin": fnum(p.get("margin")),
                        "upnl": fnum(p.get("unrealised_pnl"))})
        return out

    def taker_fee(self, c: str) -> Optional[float]:
        js = self.req("GET", f"/futures/{SETTLE}/fee", {"contract": c})
        row = js.get(c) if isinstance(js, dict) else None
        return fnum(row.get("taker_fee")) if isinstance(row, dict) else None

    @staticmethod
    def _order(o: dict) -> dict:
        ini = o.get("initial") if isinstance(o.get("initial"), dict) else {}
        trg = o.get("trigger") if isinstance(o.get("trigger"), dict) else {}
        oid = o.get("id")
        return {"id": int(oid) if str(oid or "").isdigit() else oid, "contract": ini.get("contract"),
                "price": fnum(trg.get("price")), "rule": trg.get("rule"), "price_type": trg.get("price_type"),
                "close": bool(ini.get("close") or ini.get("is_close")), "size": fnum(ini.get("size")),
                "text": ini.get("text") or "", "status": o.get("status") or "", "finish_as": o.get("finish_as") or "",
                "reason": o.get("reason") or "", "create_s": fnum(o.get("create_time")) or 0.0,
                "order_type": o.get("order_type") or ""}

    def price_orders(self, contract: Optional[str] = None, status: str = "open") -> list[dict]:
        js = self.req("GET", f"/futures/{SETTLE}/price_orders", {"status": status, "contract": contract})
        if not isinstance(js, list):
            raise GateUnknown(f"조건부 주문 목록을 못 읽음 ({str(js)[:120]})")
        return [self._order(o) for o in js if isinstance(o, dict)]

    def price_order(self, oid: int) -> dict:
        js = self.req("GET", f"/futures/{SETTLE}/price_orders/{int(oid)}")
        if not isinstance(js, dict):
            raise GateUnknown(f"조건부 주문 {oid}을 못 읽음 ({str(js)[:120]})")
        return self._order(js)

    def closes(self, c: str, since_s: int, limit: int = 10) -> list[dict]:
        js = self.req("GET", f"/futures/{SETTLE}/position_close", {"contract": c, "from": int(since_s), "limit": limit})
        if not isinstance(js, list):
            raise GateUnknown(f"{c} 종료 기록을 못 읽음 ({str(js)[:120]})")
        return [r for r in js if isinstance(r, dict)]

    # ------------------------------------------------------------------ writes
    def place_stop(self, c: str, side: int, price: float) -> int:
        """A resting stop that closes the WHOLE position at market when the last price reaches ``price``."""
        tick_s = self.contract(c)["tick_s"]
        body = {"initial": {"contract": c, "size": 0, "price": "0", "tif": "ioc", "close": True},
                "trigger": {"strategy_type": 0, "price_type": PRICE_LAST, "price": price_text(price, tick_s),
                            "rule": RULE_LE if side > 0 else RULE_GE, "expiration": 0}}
        js = self.req("POST", f"/futures/{SETTLE}/price_orders", body=body)
        oid = js.get("id") if isinstance(js, dict) else None
        if not str(oid or "").isdigit():
            raise GateUnknown(f"{c} 손절 주문의 번호가 응답에 없습니다 ({str(js)[:120]})")
        return int(oid)

    def cancel_stop(self, oid: int) -> dict:
        js = self.req("DELETE", f"/futures/{SETTLE}/price_orders/{int(oid)}")
        return self._order(js) if isinstance(js, dict) else {}

    def close_market(self, c: str, tag: str) -> dict:
        """The whole position closed at market now (reduce only: close true, size 0)."""
        text = "t-" + "".join(ch for ch in tag if ch.isalnum() or ch in "_-.")[:28]
        js = self.req("POST", f"/futures/{SETTLE}/orders",
                      body={"contract": c, "size": 0, "price": "0", "tif": "ioc", "close": True, "text": text})
        return js if isinstance(js, dict) else {}
