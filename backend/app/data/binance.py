"""바이낸스 USDⓈ-M 선물 공개 API (키 불필요).

CoinGlass 키가 없을 때 파생 데이터(OI, 펀딩비, 롱숏비율)의 무료 대체재로 사용한다.
"""
import httpx

from .. import config

FAPI = "https://fapi.binance.com"

# openInterestHist 등 /futures/data 엔드포인트가 받는 period 값
_PERIODS = {"5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}


def _get(path: str, params: dict) -> list | dict:
    r = httpx.get(FAPI + path, params=params, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def klines(symbol: str, interval: str, limit: int = 500, end_time: int | None = None) -> list[dict]:
    """최대 limit개. 1500개 초과 요청은 여러 번 나눠서 과거로 거슬러 올라가며 받는다."""
    out: list[dict] = []
    end_ms = end_time * 1000 if end_time else None
    remaining = limit
    while remaining > 0:
        params = {"symbol": symbol, "interval": interval, "limit": min(remaining, 1500)}
        if end_ms:
            params["endTime"] = end_ms
        rows = _get("/fapi/v1/klines", params)
        if not rows:
            break
        batch = [{
            "time": int(k[0]) // 1000,
            "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
            "close": float(k[4]), "volume": float(k[5]),
        } for k in rows]
        out = batch + out
        remaining -= len(batch)
        end_ms = rows[0][0] - 1
        if len(rows) < params["limit"]:
            break
    return out[-limit:]


def funding_history(symbol: str, limit: int = 200) -> list[dict]:
    rows = _get("/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit})
    return [{"time": int(r["fundingTime"]) // 1000, "value": float(r["fundingRate"]) * 100} for r in rows]


def premium_index(symbol: str) -> dict:
    r = _get("/fapi/v1/premiumIndex", {"symbol": symbol})
    return {
        "mark_price": float(r["markPrice"]),
        "index_price": float(r["indexPrice"]),
        "funding_rate_pct": float(r["lastFundingRate"]) * 100,
        "next_funding_time": int(r["nextFundingTime"]) // 1000,
    }


def _period(interval: str) -> str:
    if interval in _PERIODS:
        return interval
    # 1m/3m 은 5m, 일봉 이상은 1d 가 이 엔드포인트의 한계
    return "5m" if interval in ("1m", "3m") else "1d"


def open_interest_history(symbol: str, interval: str, limit: int = 200) -> list[dict]:
    rows = _get("/futures/data/openInterestHist",
                {"symbol": symbol, "period": _period(interval), "limit": min(limit, 500)})
    return [{"time": int(r["timestamp"]) // 1000, "value": float(r["sumOpenInterestValue"])} for r in rows]


def long_short_ratio(symbol: str, interval: str, limit: int = 200) -> list[dict]:
    rows = _get("/futures/data/globalLongShortAccountRatio",
                {"symbol": symbol, "period": _period(interval), "limit": min(limit, 500)})
    return [{"time": int(r["timestamp"]) // 1000, "value": float(r["longShortRatio"])} for r in rows]


def taker_buy_sell_ratio(symbol: str, interval: str, limit: int = 200) -> list[dict]:
    rows = _get("/futures/data/takerlongshortRatio",
                {"symbol": symbol, "period": _period(interval), "limit": min(limit, 500)})
    return [{"time": int(r["timestamp"]) // 1000, "value": float(r["buySellRatio"])} for r in rows]


def tickers_24h() -> list[dict]:
    rows = _get("/fapi/v1/ticker/24hr", {})
    return [{
        "symbol": r["symbol"],
        "price": float(r["lastPrice"]),
        "change_pct": float(r["priceChangePercent"]),
        "high": float(r["highPrice"]),
        "low": float(r["lowPrice"]),
        "quote_volume": float(r["quoteVolume"]),
    } for r in rows if r["symbol"].endswith("USDT")]
