"""거래소별 시세 비교 (김치 프리미엄 포함). 모두 키 없는 공개 API.

선물: 바이낸스 · 바이비트 · OKX · 비트겟 / 현물: 바이낸스 · 코인베이스 · 업비트 · 빗썸
원화 거래소는 환율(USD/KRW)로 달러 환산해 김치 프리미엄을 계산하고, 업비트 USDT 원화 가격도 같이 보여준다.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from .. import config
from . import synthetic

_cache: dict[str, tuple[float, object]] = {}


def _get(url: str, params: dict | None = None):
    r = httpx.get(url, params=params, timeout=config.HTTP_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()


def _base(symbol: str) -> str:
    return symbol.upper().removesuffix("USDT")


def binance_perp(b):
    t = _get("https://fapi.binance.com/fapi/v1/ticker/24hr", {"symbol": f"{b}USDT"})
    f = _get("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": f"{b}USDT"})
    return {"price": float(t["lastPrice"]), "change_pct": float(t["priceChangePercent"]),
            "volume_usd": float(t["quoteVolume"]), "funding_pct": float(f["lastFundingRate"]) * 100}


def binance_spot(b):
    t = _get("https://api.binance.com/api/v3/ticker/24hr", {"symbol": f"{b}USDT"})
    return {"price": float(t["lastPrice"]), "change_pct": float(t["priceChangePercent"]), "volume_usd": float(t["quoteVolume"])}


def bybit_perp(b):
    t = _get("https://api.bybit.com/v5/market/tickers", {"category": "linear", "symbol": f"{b}USDT"})["result"]["list"][0]
    return {"price": float(t["lastPrice"]), "change_pct": float(t["price24hPcnt"]) * 100,
            "volume_usd": float(t["turnover24h"]), "funding_pct": float(t["fundingRate"]) * 100}


def okx_perp(b):
    t = _get("https://www.okx.com/api/v5/market/ticker", {"instId": f"{b}-USDT-SWAP"})["data"][0]
    f = _get("https://www.okx.com/api/v5/public/funding-rate", {"instId": f"{b}-USDT-SWAP"})["data"][0]
    last, open_ = float(t["last"]), float(t["open24h"])
    return {"price": last, "change_pct": (last / open_ - 1) * 100 if open_ else None,
            "volume_usd": float(t["volCcy24h"]) * last, "funding_pct": float(f["fundingRate"]) * 100}


def bitget_perp(b):
    t = _get("https://api.bitget.com/api/v2/mix/market/ticker", {"symbol": f"{b}USDT", "productType": "USDT-FUTURES"})["data"][0]
    return {"price": float(t["lastPr"]), "change_pct": float(t["change24h"]) * 100,
            "volume_usd": float(t.get("usdtVolume") or t.get("quoteVolume") or 0), "funding_pct": float(t["fundingRate"]) * 100}


def coinbase_spot(b):
    t = _get(f"https://api.exchange.coinbase.com/products/{b}-USD/ticker")
    s = _get(f"https://api.exchange.coinbase.com/products/{b}-USD/stats")
    last, open_ = float(t["price"]), float(s["open"])
    return {"price": last, "change_pct": (last / open_ - 1) * 100 if open_ else None, "volume_usd": float(s["volume"]) * last}


def upbit_krw(b):
    t = _get("https://api.upbit.com/v1/ticker", {"markets": f"KRW-{b}"})[0]
    return {"price_krw": float(t["trade_price"]), "change_pct": float(t["signed_change_rate"]) * 100,
            "volume_krw": float(t["acc_trade_price_24h"])}


def bithumb_krw(b):
    t = _get(f"https://api.bithumb.com/public/ticker/{b}_KRW")["data"]
    return {"price_krw": float(t["closing_price"]), "change_pct": float(t["fluctate_rate_24H"]),
            "volume_krw": float(t["acc_trade_value_24H"])}


def fx_usdkrw() -> dict:
    out = {}
    try:
        out["fx"] = float(_get("https://open.er-api.com/v6/latest/USD")["rates"]["KRW"])
    except Exception:
        pass
    try:
        out["usdt_krw"] = float(_get("https://api.upbit.com/v1/ticker", {"markets": "KRW-USDT"})[0]["trade_price"])
    except Exception:
        pass
    return out


SOURCES = [
    ("바이낸스", "선물", binance_perp), ("바이비트", "선물", bybit_perp), ("OKX", "선물", okx_perp),
    ("비트겟", "선물", bitget_perp), ("바이낸스", "현물", binance_spot), ("코인베이스", "현물", coinbase_spot),
    ("업비트", "원화", upbit_krw), ("빗썸", "원화", bithumb_krw),
]


def compare(symbol: str) -> dict:
    key = symbol.upper()
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 8:
        return hit[1]
    b = _base(symbol)
    if config.DATA_SOURCE == "synthetic":
        res = _synthetic(symbol)
    else:
        with ThreadPoolExecutor(max_workers=len(SOURCES) + 1) as ex:
            fx_f = ex.submit(fx_usdkrw)
            futs = [(name, kind, ex.submit(fn, b)) for name, kind, fn in SOURCES]
            fx = fx_f.result()
            rows = []
            for name, kind, f in futs:
                try:
                    rows.append({"exchange": name, "market": kind, **f.result()})
                except Exception as e:
                    rows.append({"exchange": name, "market": kind, "error": str(e)[:120]})
        res = _finish(rows, fx, "live")
    _cache[key] = (time.time(), res)
    return res


def _finish(rows: list[dict], fx: dict, source: str) -> dict:
    rate = fx.get("fx")
    for r in rows:
        if "price_krw" in r and rate:
            r["price"] = r["price_krw"] / rate
            r["volume_usd"] = r["volume_krw"] / rate
    ref = next((r["price"] for r in rows if r["exchange"] == "바이낸스" and r["market"] == "선물" and "price" in r), None)
    spot = next((r["price"] for r in rows if r["exchange"] == "바이낸스" and r["market"] == "현물" and "price" in r), ref)
    for r in rows:
        if "price" in r and ref:
            r["diff_pct"] = (r["price"] / ref - 1) * 100
        if "price_krw" in r and rate and spot:
            r["kimchi_pct"] = (r["price_krw"] / rate / spot - 1) * 100
    kimchi = next((r.get("kimchi_pct") for r in rows if r["exchange"] == "업비트" and "kimchi_pct" in r), None)
    tether = (fx["usdt_krw"] / rate - 1) * 100 if fx.get("usdt_krw") and rate else None
    return {"rows": rows, "fx_usdkrw": rate, "usdt_krw": fx.get("usdt_krw"), "kimchi_pct": kimchi,
            "tether_premium_pct": tether, "source": source, "time": int(time.time())}


def _synthetic(symbol: str) -> dict:
    c = synthetic.candles(symbol, "1h", 25)
    p, chg = c[-1]["close"], (c[-1]["close"] / c[0]["close"] - 1) * 100
    offs = {"바이낸스선물": 0, "바이비트선물": 0.0004, "OKX선물": -0.0003, "비트겟선물": 0.0006,
            "바이낸스현물": 0.0002, "코인베이스현물": 0.0009}
    rows = []
    for name, kind, _ in SOURCES:
        if kind == "원화":
            rows.append({"exchange": name, "market": kind, "price_krw": p * (1.021 if name == "업비트" else 1.0235) * 1380,
                         "change_pct": chg, "volume_krw": 3e11})
        else:
            rows.append({"exchange": name, "market": kind, "price": p * (1 + offs[name + kind]), "change_pct": chg,
                         "volume_usd": 2e9, **({"funding_pct": 0.01} if kind == "선물" else {})})
    return _finish(rows, {"fx": 1380.0, "usdt_krw": 1392.0}, "synthetic")
