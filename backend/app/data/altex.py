"""바이낸스가 안 될 때(지역 차단 451 · 점검 · 네트워크) 쓰는 다른 거래소의 무기한 선물 공개 API — 키 불필요.

- 바이빗(Bybit) v5 linear: 캔들 · 24시간 시세 · 펀딩비 · 미결제약정 · 롱숏 비율
- OKX v5 SWAP: 캔들 · 24시간 시세
캔들 형식은 binance.klines 와 같다 ({time, open, high, low, close, volume}). 테이커 매수량(taker_buy)은 주지 않으므로
CVD 같은 계산은 각자 '없으면 대체' 경로를 탄다.
"""
from __future__ import annotations

import httpx

from .. import config

BYBIT = "https://api.bybit.com"
OKX = "https://www.okx.com"
_BYBIT_IV = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240", "6h": "360",
             "12h": "720", "1d": "D", "1w": "W", "1M": "M"}
_OKX_IV = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6Hutc",
           "12h": "12Hutc", "1d": "1Dutc", "3d": "3Dutc", "1w": "1Wutc", "1M": "1Mutc"}
_BYBIT_OI = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1d"}


class NoSymbol(ValueError):
    """그 거래소에 없는 종목."""


def _get(url: str, params: dict) -> dict:
    r = httpx.get(url, params=params, timeout=config.HTTP_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()


def _okx_inst(symbol: str) -> str:
    base = symbol[:-4] if symbol.endswith("USDT") else symbol
    return f"{base}-USDT-SWAP"


# ---------------------------------------------------------------- 바이빗
def bybit_klines(symbol: str, interval: str, limit: int = 500, end_time: int | None = None) -> list[dict]:
    iv = _BYBIT_IV.get(interval)
    if not iv:
        raise ValueError(f"바이빗은 {interval} 봉을 주지 않습니다")
    out: list[dict] = []
    end_ms = end_time * 1000 if end_time else None
    while len(out) < limit:
        params = {"category": "linear", "symbol": symbol, "interval": iv, "limit": min(1000, limit - len(out))}
        if end_ms:
            params["end"] = end_ms
        d = _get(BYBIT + "/v5/market/kline", params)
        if d.get("retCode") not in (0, None):
            if "symbol" in str(d.get("retMsg", "")).lower() or d.get("retCode") == 10001:
                raise NoSymbol(f"{symbol} 은(는) 바이빗 선물에 없는 종목입니다.")
            raise RuntimeError(f"바이빗 오류: {d.get('retMsg')}")
        rows = (d.get("result") or {}).get("list") or []
        if not rows:
            break
        batch = [{"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                  "close": float(k[4]), "volume": float(k[5])} for k in reversed(rows)]   # 바이빗은 최신이 먼저
        out = batch + out
        end_ms = int(rows[-1][0]) - 1
        if len(rows) < params["limit"]:
            break
    if not out:
        raise NoSymbol(f"{symbol} 은(는) 바이빗 선물에 없는 종목입니다.")
    return out[-limit:]


def bybit_tickers() -> list[dict]:
    rows = _get(BYBIT + "/v5/market/tickers", {"category": "linear"})["result"]["list"]
    out = []
    for r in rows:
        try:
            out.append({"symbol": r["symbol"], "price": float(r["lastPrice"]), "change_pct": float(r["price24hPcnt"]) * 100,
                        "high": float(r["highPrice24h"]), "low": float(r["lowPrice24h"]), "quote_volume": float(r["turnover24h"])})
        except (KeyError, ValueError, TypeError):
            continue
    return out


def bybit_funding(symbol: str, limit: int = 200) -> list[dict]:
    rows = _get(BYBIT + "/v5/market/funding/history", {"category": "linear", "symbol": symbol, "limit": min(limit, 200)})["result"]["list"]
    return [{"time": int(r["fundingRateTimestamp"]) // 1000, "value": float(r["fundingRate"]) * 100} for r in reversed(rows)]


def bybit_open_interest(symbol: str, interval: str, limit: int = 200) -> list[dict]:
    iv = _BYBIT_OI.get(interval, "1h")
    rows = _get(BYBIT + "/v5/market/open-interest", {"category": "linear", "symbol": symbol, "intervalTime": iv,
                                                     "limit": min(limit, 200)})["result"]["list"]
    return [{"time": int(r["timestamp"]) // 1000, "value": float(r["openInterest"])} for r in reversed(rows)]


def bybit_long_short(symbol: str, interval: str, limit: int = 200) -> list[dict]:
    iv = _BYBIT_OI.get(interval, "1h")
    rows = _get(BYBIT + "/v5/market/account-ratio", {"category": "linear", "symbol": symbol, "period": iv,
                                                     "limit": min(limit, 500)})["result"]["list"]
    out = []
    for r in reversed(rows):
        b, s = float(r["buyRatio"]), float(r["sellRatio"])
        out.append({"time": int(r["timestamp"]) // 1000, "value": b / s if s else None, "long": b, "short": s})
    return out


# ---------------------------------------------------------------- OKX
def okx_klines(symbol: str, interval: str, limit: int = 500, end_time: int | None = None) -> list[dict]:
    bar = _OKX_IV.get(interval)
    if not bar:
        raise ValueError(f"OKX 는 {interval} 봉을 주지 않습니다")
    inst = _okx_inst(symbol)
    out: list[dict] = []
    after = str(end_time * 1000 + 1) if end_time else None
    path = "/api/v5/market/candles"
    for _ in range(40):                                   # 최근 300개 → 그 이전은 history 100개씩
        params = {"instId": inst, "bar": bar, "limit": 300 if path.endswith("candles") else 100}
        if after:
            params["after"] = after
        d = _get(OKX + path, params)
        if d.get("code") not in ("0", 0):
            if d.get("code") in ("51001", "51000"):
                raise NoSymbol(f"{symbol} 은(는) OKX 선물에 없는 종목입니다.")
            raise RuntimeError(f"OKX 오류: {d.get('msg')}")
        rows = d.get("data") or []
        if not rows:
            break
        batch = [{"time": int(k[0]) // 1000, "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
                  "close": float(k[4]), "volume": float(k[6])} for k in reversed(rows)]   # k[6] = 기초자산 수량
        out = batch + out
        if len(out) >= limit:
            break
        after = rows[-1][0]
        path = "/api/v5/market/history-candles"
    if not out:
        raise NoSymbol(f"{symbol} 은(는) OKX 선물에 없는 종목입니다.")
    return out[-limit:]


def okx_tickers() -> list[dict]:
    rows = _get(OKX + "/api/v5/market/tickers", {"instType": "SWAP"})["data"]
    out = []
    for r in rows:
        if not r["instId"].endswith("-USDT-SWAP"):
            continue
        try:
            last = float(r["last"])
            out.append({"symbol": r["instId"].replace("-USDT-SWAP", "USDT"), "price": last,
                        "change_pct": (last / float(r["open24h"]) - 1) * 100 if float(r["open24h"]) else 0.0,
                        "high": float(r["high24h"]), "low": float(r["low24h"]),
                        "quote_volume": float(r["volCcy24h"]) * last})
        except (KeyError, ValueError, TypeError, ZeroDivisionError):
            continue
    return out
