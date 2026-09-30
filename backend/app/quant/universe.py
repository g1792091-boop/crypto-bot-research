"""여러 코인 종가를 BTC 시간축에 맞춰 불러오는 공통 도구 (리스크 · 포트폴리오에서 사용)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ..data import market

TIER_NAME = {"btc": "비트코인", "eth": "이더리움", "large": "대형 알트", "mid": "중소형 알트", "meme": "밈코인"}
TIER_ORDER = ["btc", "eth", "large", "mid", "meme"]
LARGE = {"SOL", "BNB", "XRP", "ADA", "DOGE", "TRX", "AVAX", "LINK", "TON", "DOT", "LTC", "BCH", "SUI", "XLM", "HBAR"}
MEME = {"1000PEPE", "1000SHIB", "1000BONK", "1000FLOKI", "WIF", "PEPE", "SHIB", "BONK", "FLOKI", "1000SATS", "MEME", "BOME", "POPCAT"}
DEFAULT_UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT",
                    "SUIUSDT", "TRXUSDT", "DOTUSDT", "LTCUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
                    "1000PEPEUSDT", "WIFUSDT", "1000BONKUSDT"]


def tier(symbol: str) -> str:
    b = symbol.upper().removesuffix("USDT")
    if b == "BTC":
        return "btc"
    if b == "ETH":
        return "eth"
    if b in MEME:
        return "meme"
    return "large" if b in LARGE else "mid"


def load(symbols: list[str], interval: str, bars: int) -> tuple[list[int], dict[str, list[float | None]], str]:
    """BTC 시간축에 맞춘 종가표. 상장 전·빈 구간은 None (중간 빈칸은 직전 값으로 채움)."""
    syms = list(dict.fromkeys(["BTCUSDT", *symbols]))

    def get(s):
        try:
            return s, market.candles(s, interval, bars)
        except Exception:
            return s, None
    with ThreadPoolExecutor(max_workers=8) as ex:
        got = dict(ex.map(get, syms))
    if not got.get("BTCUSDT"):
        raise ValueError("기준(BTC) 데이터를 불러오지 못했습니다")
    btc, src = got["BTCUSDT"]
    times = [b["time"] for b in btc]
    closes: dict[str, list[float | None]] = {}
    for s in syms:
        if not got.get(s):
            continue
        m = {b["time"]: b["close"] for b in got[s][0]}
        row, last, started = [], None, False
        for t in times:
            v = m.get(t)
            if v is not None:
                started, last = True, v
            row.append(v if v is not None else (last if started else None))
        closes[s] = row
    return times, closes, src
