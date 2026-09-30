"""CoinGlass Open API v4 어댑터.

CoinGlass는 차트 임베드(iframe) 위젯을 공식 제공하지 않으므로, API로 데이터를 받아
우리 차트(lightweight-charts)에 직접 그린다. 유료 플랜(Hobbyist $29/월~) API 키 필요.

엔드포인트 경로는 CoinGlass 문서 개편 시 바뀔 수 있어 ENDPOINTS 한 곳에 모아 두었다.
https://docs.coinglass.com/reference/endpoint-overview
"""
import httpx

from .. import config

BASE = "https://open-api-v4.coinglass.com"

ENDPOINTS = {
    # 전체 거래소 합산 OI OHLC
    "oi_aggregated": "/api/futures/open-interest/aggregated-history",
    # OI 가중 펀딩비 OHLC
    "funding_oi_weighted": "/api/futures/funding-rate/oi-weight-history",
    # 거래소별 페어 전체 계정 롱/숏 비율
    "long_short_global": "/api/futures/global-long-short-account-ratio/history",
    # 합산 청산 히스토리
    "liquidation_aggregated": "/api/futures/liquidation/aggregated-history",
    # 청산 히트맵 (코인 합산)
    "liquidation_heatmap": "/api/futures/liquidation/aggregated-heatmap/model3",
}


class CoinGlassError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(config.COINGLASS_API_KEY)


def _get(key: str, params: dict):
    return get_path(ENDPOINTS[key], params)


def get_path(path: str, params: dict):
    r = httpx.get(BASE + path, params=params,
                  headers={"CG-API-KEY": config.COINGLASS_API_KEY, "accept": "application/json"},
                  timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    body = r.json()
    if str(body.get("code")) != "0":
        raise CoinGlassError(body.get("msg") or f"CoinGlass error code {body.get('code')}")
    return body.get("data")


def _ts(v) -> int:
    v = int(v)
    return v // 1000 if v > 10**11 else v


def _num(row: dict, *names: str) -> float:
    for n in names:
        if n in row and row[n] is not None:
            return float(row[n])
    raise KeyError(names)


def base_coin(symbol: str) -> str:
    s = symbol.upper()
    for q in ("USDT", "USDC", "USD"):
        if s.endswith(q):
            return s[: -len(q)]
    return s


def open_interest(symbol: str, interval: str, limit: int = 200) -> list[dict]:
    rows = _get("oi_aggregated", {"symbol": base_coin(symbol), "interval": interval, "limit": limit})
    return [{"time": _ts(r["time"]), "value": _num(r, "close", "c")} for r in rows]


def funding(symbol: str, interval: str, limit: int = 200) -> list[dict]:
    rows = _get("funding_oi_weighted", {"symbol": base_coin(symbol), "interval": interval, "limit": limit})
    return [{"time": _ts(r["time"]), "value": _num(r, "close", "c")} for r in rows]


def long_short(symbol: str, interval: str, limit: int = 200, exchange: str = "Binance") -> list[dict]:
    rows = _get("long_short_global",
                {"exchange": exchange, "symbol": symbol.upper(), "interval": interval, "limit": limit})
    return [{"time": _ts(r["time"]),
             "value": _num(r, "global_account_long_short_ratio", "longShortRatio")} for r in rows]


def liquidations(symbol: str, interval: str, limit: int = 200) -> list[dict]:
    rows = _get("liquidation_aggregated", {"symbol": base_coin(symbol), "interval": interval, "limit": limit,
                                           "exchange_list": "Binance,OKX,Bybit,Bitget"})
    return [{
        "time": _ts(r["time"]),
        "long_usd": _num(r, "aggregated_long_liquidation_usd", "longLiquidationUsd"),
        "short_usd": _num(r, "aggregated_short_liquidation_usd", "shortLiquidationUsd"),
    } for r in rows]


def liquidation_heatmap(symbol: str, range_: str = "3d"):
    return _get("liquidation_heatmap", {"symbol": base_coin(symbol), "range": range_})
