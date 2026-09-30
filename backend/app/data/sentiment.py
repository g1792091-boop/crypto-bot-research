"""공포·탐욕 지수, 코인베이스 프리미엄, CoinGlass 지수 지표."""
from __future__ import annotations

import time

import httpx

from .. import config
from . import binance, coinglass

_cache: dict[tuple, tuple[float, object]] = {}


def _ttl(key: tuple, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    _cache[key] = (time.time(), v)
    return v


def _label(v: int) -> str:
    return "극단적 공포" if v < 25 else "공포" if v < 45 else "중립" if v <= 55 else "탐욕" if v <= 75 else "극단적 탐욕"


def fear_greed(days: int = 90) -> dict:
    """alternative.me 크립토 공포·탐욕 지수 (0 극단적 공포 ~ 100 극단적 탐욕)."""
    def fetch():
        r = httpx.get("https://api.alternative.me/fng/", params={"limit": days, "format": "json"}, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        rows = [{"time": int(d["timestamp"]), "value": int(d["value"])} for d in r.json()["data"]]
        rows.sort(key=lambda x: x["time"])
        return rows
    if config.DATA_SOURCE == "synthetic":
        import math
        now = int(time.time()) // 86400 * 86400
        rows = [{"time": now - (days - 1 - i) * 86400, "value": int(50 + 30 * math.sin((now // 86400 - days + i) / 9))} for i in range(days)]
        src = "synthetic"
    else:
        rows, src = _ttl(("fng", days), 600, fetch), "alternative.me"
    cur = rows[-1]["value"]
    prev = {k: rows[-1 - n]["value"] for k, n in (("yesterday", 1), ("week", 7), ("month", 30)) if len(rows) > n}
    return {"value": cur, "label": _label(cur), "history": rows, "previous": prev, "source": src}


def coinbase_premium(symbol: str = "BTCUSDT", interval: str = "1h") -> dict:
    """코인베이스(미국 기관·개인 현물) 가격이 바이낸스보다 얼마나 비싼지 (%). 양수면 미국 쪽 매수세 우위."""
    gran = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "6h": 21600, "1d": 86400}.get(interval, 3600)
    base = symbol.upper().removesuffix("USDT")

    def fetch():
        r = httpx.get(f"https://api.exchange.coinbase.com/products/{base}-USD/candles", params={"granularity": gran},
                      timeout=config.HTTP_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        cb = {int(row[0]): float(row[4]) for row in r.json()}
        b = httpx.get("https://api.binance.com/api/v3/klines",
                      params={"symbol": f"{base}USDT", "interval": interval, "limit": 300}, timeout=config.HTTP_TIMEOUT)
        b.raise_for_status()
        out = []
        for k in b.json():
            t = int(k[0]) // 1000
            if t in cb:
                bn = float(k[4])
                out.append({"time": t, "value": (cb[t] / bn - 1) * 100})
        return out
    return {"series": _ttl(("cbp", base, interval), 60, fetch), "source": "coinbase-binance"}


# CoinGlass 지수 (키 필요). 경로는 CoinGlass 문서 개편 시 바뀔 수 있어 한 곳에 모아 둔다.
CG_INDEX = {
    "fear_greed": ("공포·탐욕 (CoinGlass)", "/api/index/fear-greed-history", {}),
    "coinbase_premium": ("코인베이스 프리미엄 지수", "/api/coinbase-premium-index", {"interval": "1h"}),
    "ahr999": ("AHR999 (적립식 매수 지표)", "/api/index/ahr999", {}),
    "bull_peak": ("강세장 고점 지표", "/api/bull-market-peak-indicator", {}),
    "puell": ("퓨엘 멀티플", "/api/index/puell-multiple", {}),
    "pi_cycle": ("파이 사이클 고점 지표", "/api/index/pi-cycle-indicator", {}),
    "stock_flow": ("S2F 모델", "/api/index/stock-flow", {}),
    "btc_etf_flow": ("비트코인 현물 ETF 순유입", "/api/etf/bitcoin/flow-history", {}),
}


def coinglass_index(name: str) -> dict:
    if name not in CG_INDEX:
        raise ValueError(f"알 수 없는 지표: {name}")
    if not coinglass.enabled():
        raise ValueError("COINGLASS_API_KEY 가 필요합니다.")
    title, path, params = CG_INDEX[name]
    data = _ttl(("cg", name), 300, lambda: coinglass.get_path(path, params))
    return {"name": name, "title": title, "data": data}


def taker_ratio(symbol: str, interval: str, limit: int = 200) -> list[dict]:
    return binance.taker_buy_sell_ratio(symbol, interval, limit)
