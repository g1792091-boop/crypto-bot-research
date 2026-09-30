"""데이터 소스 통합 레이어.

- 캔들: 바이낸스 선물 (실패 시 합성 데이터, DATA_SOURCE=auto)
- 파생 지표: CoinGlass 키가 있으면 CoinGlass, 없으면 바이낸스 공개 API
- 도미넌스/시총: CoinGecko 공개 API
"""
import time
from datetime import datetime, timezone

import httpx

from .. import config
from . import binance, coinglass, synthetic

_cache: dict[tuple, tuple[float, object]] = {}


def _cached(key: tuple, ttl: float, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h",
             "1d", "3d", "1w", "1M", "1y"]


def _yearly(monthly: list[dict]) -> list[dict]:
    """월봉 → 연봉 (UTC 달력 연도 기준)."""
    out: list[dict] = []
    for b in monthly:
        year = datetime.fromtimestamp(b["time"], tz=timezone.utc).year
        if out and out[-1]["_y"] == year:
            y = out[-1]
            y["high"] = max(y["high"], b["high"]); y["low"] = min(y["low"], b["low"])
            y["close"] = b["close"]; y["volume"] += b["volume"]
        else:
            out.append({**b, "time": int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp()), "_y": year})
    for y in out:
        y.pop("_y")
    return out


def _binance_candles(symbol: str, interval: str, limit: int) -> list[dict]:
    if interval == "1y":
        return _yearly(binance.klines(symbol, "1M", min(limit * 12, 1500)))[-limit:]
    return binance.klines(symbol, interval, limit)


def candles(symbol: str, interval: str, limit: int = 500) -> tuple[list[dict], str]:
    """(캔들, 소스명) 반환."""
    if interval not in INTERVALS:
        raise ValueError(f"지원하지 않는 봉 간격: {interval}")
    src = config.DATA_SOURCE
    if src == "synthetic":
        return synthetic.candles(symbol, interval, limit), "synthetic"
    try:
        rows = _cached(("klines", symbol, interval, limit), 5,
                       lambda: _binance_candles(symbol, interval, limit))
        return rows, "binance"
    except httpx.HTTPStatusError as e:
        # 네트워크 문제가 아니라 바이낸스가 "없는 심볼"이라고 답한 경우: 가짜 차트를 보여주지 않는다
        if e.response.status_code == 400:
            raise ValueError(f"{symbol} 은(는) 바이낸스 선물에 없는 종목입니다.") from e
        if src == "binance":
            raise
        return synthetic.candles(symbol, interval, limit), "synthetic"
    except Exception:
        if src == "binance":
            raise
        return synthetic.candles(symbol, interval, limit), "synthetic"


def candles_range(symbol: str, interval: str, start: int, end: int) -> tuple[list[dict], str]:
    """start~end(유닉스 초) 사이 봉 — 과거 특정 시기(위기 구간 등) 조회용."""
    step = synthetic.INTERVAL_SECONDS.get(interval, 86400)
    n = max(2, (end - start) // step + 2)
    if config.DATA_SOURCE != "synthetic":
        try:
            rows = _cached(("range", symbol, interval, start, end), 3600,
                           lambda: binance.klines(symbol, interval, min(n, 1500), end_time=end))
            return [b for b in rows if start <= b["time"] <= end], "binance"
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                return [], "binance"              # 그 시기에 상장 전
            if config.DATA_SOURCE == "binance":
                raise
        except Exception:
            if config.DATA_SOURCE == "binance":
                raise
    rows = synthetic.candles(symbol, interval, n, end_time=end)
    return [b for b in rows if start <= b["time"] <= end], "synthetic"


def tickers(symbols: list[str]) -> tuple[list[dict], str]:
    """관심 종목 시세 (24h 등락, 고가/저가)."""
    if config.DATA_SOURCE != "synthetic":
        try:
            rows = _cached(("tickers",), 5, binance.tickers_24h)
            by = {r["symbol"]: r for r in rows}
            return [by[s] for s in symbols if s in by], "binance"
        except Exception:
            if config.DATA_SOURCE == "binance":
                raise
    out = []
    for s in symbols:
        c = synthetic.candles(s, "1h", 25)
        last, prev = c[-1]["close"], c[0]["close"]
        out.append({"symbol": s, "price": last, "change_pct": (last / prev - 1) * 100,
                    "high": max(b["high"] for b in c[1:]), "low": min(b["low"] for b in c[1:]),
                    "quote_volume": sum(b["volume"] * b["close"] for b in c[1:])})
    return out, "synthetic"


def derivatives(symbol: str, interval: str, limit: int = 200) -> dict:
    """OI / 펀딩비 / 롱숏비율 / 청산. 가능한 소스에서 최대한 채워서 반환."""
    out: dict = {"source": None, "open_interest": [], "funding": [], "long_short": [],
                 "liquidations": [], "errors": {}}

    if coinglass.enabled():
        out["source"] = "coinglass"
        for name, fn in (("open_interest", coinglass.open_interest), ("funding", coinglass.funding),
                         ("long_short", coinglass.long_short), ("liquidations", coinglass.liquidations)):
            try:
                out[name] = _cached(("cg", name, symbol, interval, limit), 30,
                                    lambda fn=fn: fn(symbol, interval, limit))
            except Exception as e:  # 하나가 실패해도 나머지는 표시
                out["errors"][name] = str(e)

    out["taker"] = []
    missing = [k for k in ("open_interest", "funding", "long_short", "taker") if not out[k]]
    if missing and config.DATA_SOURCE != "synthetic":
        fallback = {
            "open_interest": lambda: binance.open_interest_history(symbol, interval, limit),
            "funding": lambda: binance.funding_history(symbol, min(limit, 1000)),
            "long_short": lambda: binance.long_short_ratio(symbol, interval, limit),
            "taker": lambda: binance.taker_buy_sell_ratio(symbol, interval, limit),
        }
        for name in missing:
            try:
                out[name] = _cached(("bn", name, symbol, interval, limit), 30, fallback[name])
                out["source"] = out["source"] or "binance"
            except Exception as e:
                out["errors"][name] = str(e)
    if not any(out[k] for k in ("open_interest", "funding", "long_short")):
        c, src = candles(symbol, interval, limit)
        if src == "synthetic":
            out.update(synthetic.derivatives(c), source="synthetic", errors={})
    return out


def funding_now(symbol: str) -> dict | None:
    try:
        return _cached(("premium", symbol), 15, lambda: binance.premium_index(symbol))
    except Exception:
        return None


def global_dominance() -> dict:
    """BTC/ETH/스테이블 도미넌스 (CoinGecko /global)."""
    def fetch():
        r = httpx.get("https://api.coingecko.com/api/v3/global", timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        d = r.json()["data"]
        pct = d["market_cap_percentage"]
        stable = sum(pct.get(k, 0) for k in ("usdt", "usdc", "dai", "fdusd", "usde"))
        return {
            "total_market_cap_usd": d["total_market_cap"]["usd"],
            "market_cap_change_24h_pct": d["market_cap_change_percentage_24h_usd"],
            "btc_dominance": pct.get("btc"),
            "eth_dominance": pct.get("eth"),
            "stablecoin_dominance": stable,
            "others_dominance": 100 - (pct.get("btc", 0) + pct.get("eth", 0) + stable),
            "top": dict(sorted(pct.items(), key=lambda kv: -kv[1])[:10]),
        }
    return _cached(("dominance",), 120, fetch)


def heatmap(limit: int = 60) -> list[dict]:
    """선물 거래대금 상위 코인의 24h 등락률 (히트맵용)."""
    def fetch():
        rows = binance.tickers_24h()
        rows.sort(key=lambda r: -r["quote_volume"])
        return rows[:limit]
    return _cached(("heatmap", limit), 30, fetch)
