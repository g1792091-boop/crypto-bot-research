"""실거래 — 데모거래를 통과하고 사람이 승인한 매매법의 신호를 바이낸스 USDT-M 선물 주문으로 그대로 따라 한다.

안전 장치 (모두 코드가 강제, AI 는 켜거나 승인할 수 없다)
- 기본 꺼짐. 켜려면 화면에서 직접 켜고, 매매법마다 '승인' 을 눌러야 한다.
- 기본은 테스트넷(가짜 돈, testnet.binancefuture.com). 실제 돈은 '테스트넷 끄기' 를 따로 해야 한다.
- 주문 한 번 최대 금액(USDT, 증거금×레버리지 기준) · 전체 노출 한도 · 최대 레버리지 · 하루 손실 한도 → 넘으면 모두 청산하고 꺼짐.
- 비상 정지: 모든 실거래 포지션 시장가 청산 + 꺼짐.
키: settings.txt 의 BINANCE_API_KEY / BINANCE_API_SECRET (선물 거래 권한만, 출금 권한은 절대 주지 말 것).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import threading
import time
from urllib.parse import urlencode

import httpx

from . import config

MAIN = "https://fapi.binance.com"
TEST = "https://testnet.binancefuture.com"
DEFAULT = {"enabled": False, "testnet": True, "max_order_usdt": 50.0, "max_total_usdt": 200.0, "max_leverage": 5,
           "daily_loss_usdt": 30.0, "approved": {}}
S: dict = {}
LOG: list[dict] = []
_lock = threading.RLock()
_info: dict = {}
_state = {"day": "", "realized": 0.0, "positions": {}, "last_sync": 0.0}


def _path():
    return config.STATE_DIR / "live.json"


def load() -> None:
    global S
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    S = {**DEFAULT, **(d.get("settings") or {})}
    LOG[:] = d.get("log") or []
    _state.update(d.get("state") or {})


def save() -> None:
    try:
        _path().write_text(json.dumps({"settings": S, "log": LOG[-500:], "state": _state}, ensure_ascii=False, default=str), encoding="utf-8")
    except OSError:
        pass


def log(text: str, **kw) -> None:
    with _lock:
        LOG.append({"t": time.time(), "text": text, **kw})
        del LOG[:-500]
    save()


def keys() -> tuple[str, str]:
    return os.getenv("BINANCE_API_KEY", ""), os.getenv("BINANCE_API_SECRET", "")


def base() -> str:
    return TEST if S.get("testnet", True) else MAIN


def sign(params: dict, secret: str) -> str:
    q = urlencode(params)
    return q + "&signature=" + hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()


def _req(method: str, path: str, params: dict | None = None, signed: bool = True):
    k, sec = keys()
    if signed and not (k and sec):
        raise RuntimeError("BINANCE_API_KEY / BINANCE_API_SECRET 가 없습니다 (settings.txt)")
    p = dict(params or {})
    if signed:
        p["timestamp"] = int(time.time() * 1000)
        p["recvWindow"] = 5000
        q = sign(p, sec)
    else:
        q = urlencode(p)
    r = httpx.request(method, f"{base()}{path}?{q}", headers={"X-MBX-APIKEY": k} if k else {}, timeout=config.HTTP_TIMEOUT)
    if r.status_code >= 400:
        raise RuntimeError(f"바이낸스 {r.status_code}: {r.text[:200]}")
    return r.json()


def symbol_info(symbol: str) -> dict:
    if not _info:
        d = _req("GET", "/fapi/v1/exchangeInfo", signed=False)
        for s in d.get("symbols", []):
            f = {x["filterType"]: x for x in s.get("filters", [])}
            _info[s["symbol"]] = {"step": float((f.get("MARKET_LOT_SIZE") or f.get("LOT_SIZE") or {}).get("stepSize", 0.001)),
                                  "min_qty": float((f.get("MARKET_LOT_SIZE") or f.get("LOT_SIZE") or {}).get("minQty", 0.001)),
                                  "min_notional": float((f.get("MIN_NOTIONAL") or {}).get("notional", 5))}
    if symbol not in _info:
        raise RuntimeError(f"{symbol} 은(는) 이 거래소 선물에 없습니다")
    return _info[symbol]


def round_qty(qty: float, step: float) -> float:
    n = math.floor(qty / step + 1e-9) * step
    dec = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    return round(n, dec)


def positions() -> dict:
    rows = _req("GET", "/fapi/v2/positionRisk")
    return {r["symbol"]: {"qty": float(r["positionAmt"]), "entry": float(r["entryPrice"]), "upnl": float(r["unRealizedProfit"]),
                          "lev": float(r.get("leverage", 1))} for r in rows if float(r["positionAmt"]) != 0}


def balance() -> float:
    rows = _req("GET", "/fapi/v2/balance")
    return next((float(r["balance"]) for r in rows if r["asset"] == "USDT"), 0.0)


def _today():
    return time.strftime("%Y-%m-%d")


def guard_ok(add_notional: float = 0.0) -> tuple[bool, str]:
    if not S.get("enabled"):
        return False, "실거래가 꺼져 있습니다"
    if _state.get("day") != _today():
        _state.update(day=_today(), realized=0.0)
    if -_state["realized"] >= S["daily_loss_usdt"]:
        return False, f"오늘 손실 한도({S['daily_loss_usdt']} USDT)에 닿았습니다"
    tot = sum(abs(p["qty"] * p["entry"]) for p in _state["positions"].values()) + add_notional
    if tot > S["max_total_usdt"] + 1e-6:
        return False, f"전체 노출 한도({S['max_total_usdt']} USDT)를 넘습니다"
    return True, ""


def open_position(pid: str, name: str, symbol: str, side: int, price: float, leverage: float) -> dict | None:
    """승인된 매매법이 진입하면 같은 방향으로 시장가 진입 (한도 안에서)."""
    lev = int(max(1, min(S["max_leverage"], leverage)))
    notional = S["max_order_usdt"]
    ok, why = guard_ok(notional)
    if not ok:
        log(f"⛔ {name} {symbol} 진입 안 함 — {why}", pid=pid)
        return None
    info = symbol_info(symbol)
    qty = round_qty(notional / price, info["step"])
    if qty < info["min_qty"] or qty * price < info["min_notional"]:
        log(f"⛔ {name} {symbol} 진입 안 함 — 최소 주문 수량 미달 (한 번 최대 {notional} USDT)", pid=pid)
        return None
    _req("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": lev})
    r = _req("POST", "/fapi/v1/order", {"symbol": symbol, "side": "BUY" if side > 0 else "SELL", "type": "MARKET", "quantity": qty,
                                         "newClientOrderId": f"ghq{pid[:10]}{int(time.time()) % 100000}"})
    _state["positions"][pid] = {"symbol": symbol, "qty": qty * side, "entry": price, "name": name, "t": time.time()}
    log(f"{'🟢 롱' if side > 0 else '🔴 숏'} 진입 {name} {symbol} {qty} @≈{price:.6g} (x{lev}{', 테스트넷' if S['testnet'] else ', 실제 돈'})", pid=pid, order=r.get("orderId"))
    save()
    return r


def close_position(pid: str, price: float, why: str = "신호 청산") -> dict | None:
    p = _state["positions"].get(pid)
    if not p:
        return None
    qty = abs(p["qty"])
    r = _req("POST", "/fapi/v1/order", {"symbol": p["symbol"], "side": "SELL" if p["qty"] > 0 else "BUY", "type": "MARKET",
                                         "quantity": qty, "reduceOnly": "true"})
    pnl = (price - p["entry"]) * p["qty"]
    _state["realized"] = _state.get("realized", 0.0) + pnl
    _state["positions"].pop(pid, None)
    log(f"⚪ 청산 {p['name']} {p['symbol']} {qty} @≈{price:.6g} · 추정 손익 {pnl:+.2f} USDT · {why}", pid=pid, order=r.get("orderId"))
    save()
    if -_state["realized"] >= S["daily_loss_usdt"]:
        kill(f"하루 손실 한도 {S['daily_loss_usdt']} USDT 도달")
    return r


def kill(why: str = "비상 정지") -> int:
    """모든 실거래 포지션을 시장가로 닫고 실거래를 끈다."""
    n = 0
    for pid, p in list(_state["positions"].items()):
        try:
            close_position(pid, p["entry"], why)
            n += 1
        except Exception as e:  # noqa: BLE001
            log(f"⚠ {p['name']} 청산 실패: {str(e)[:160]} — 거래소에서 직접 확인하세요", pid=pid)
    S["enabled"] = False
    log(f"🛑 실거래 정지: {why} (청산 {n}건)")
    save()
    return n


def approve(pid: str, ok: bool) -> None:
    if ok:
        S["approved"][pid] = time.time()
        log(f"✅ 승인: {pid}")
    else:
        S["approved"].pop(pid, None)
        log(f"↩ 승인 취소: {pid}")
    save()


def set_settings(body: dict) -> dict:
    for k in ("enabled", "testnet", "max_order_usdt", "max_total_usdt", "max_leverage", "daily_loss_usdt"):
        if k in body:
            S[k] = type(DEFAULT[k])(body[k])
    S["max_leverage"] = int(max(1, min(20, S["max_leverage"])))
    log(f"설정 변경: {', '.join(f'{k}={body[k]}' for k in body if k in DEFAULT)}")
    save()
    return view()


def sync(items: list[dict]) -> None:
    """승인된 파이프라인 항목(데모 봇)의 포지션 상태를 실거래 포지션에 맞춘다. items: {id, name, symbol, side(+1/-1/0), price, leverage}."""
    if not S.get("enabled"):
        return
    for it in items:
        pid = it["id"]
        if pid not in S["approved"]:
            continue
        cur = _state["positions"].get(pid)
        cur_side = 0 if not cur else (1 if cur["qty"] > 0 else -1)
        try:
            if cur_side and cur_side != it["side"]:
                close_position(pid, it["price"], "데모 신호 청산/반전")
                cur_side = 0
            if it["side"] and not cur_side:
                if it.get("blocked"):                       # 보호 장치: 새 진입만 막는다 (청산은 위에서 이미 허용)
                    if _state.setdefault("guard_note", {}).get(pid) != it["blocked"]:
                        _state["guard_note"][pid] = it["blocked"]
                        log(f"🛡 {it['name']} 새 진입 보류 — {it['blocked']}", pid=pid)
                    continue
                open_position(pid, it["name"], it["symbol"], it["side"], it["price"], it["leverage"])
        except Exception as e:  # noqa: BLE001
            log(f"⚠ {it['name']} 주문 실패: {str(e)[:200]}", pid=pid)
    _state["last_sync"] = time.time()


def view() -> dict:
    k, sec = keys()
    if _state.get("day") != _today():
        _state.update(day=_today(), realized=0.0)
    return {"settings": {kk: v for kk, v in S.items() if kk != "approved"}, "approved": S.get("approved", {}), "has_keys": bool(k and sec),
            "base": base(), "positions": _state["positions"], "realized_today": round(_state.get("realized", 0.0), 2),
            "log": LOG[-80:][::-1]}


load()
