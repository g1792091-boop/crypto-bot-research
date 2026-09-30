"""네트워크가 막혀 있을 때 쓰는 결정론적 합성 캔들 (데모/테스트 전용).

각 봉의 가격은 심볼과 타임스탬프만의 함수라서, 요청 개수·호출 시점·봉 간격이 달라도
같은 시각의 가격은 항상 같다 (백테스트·페이퍼 봇·차트·에이전트가 서로 일치).
여러 주기의 사인파(추세/사이클) + 봉별 노이즈로 추세장과 횡보장이 섞이게 만든다.
"""
import math
import random
import time
import zlib

INTERVAL_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
    "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800,
    "1M": 2592000, "1y": 31536000,
}

BASE_PRICE = {"BTC": 65000.0, "ETH": 3200.0, "SOL": 150.0, "XRP": 0.6, "BNB": 580.0, "DOGE": 0.15}

# (주기[시간], 진폭[로그가격]) — 절대 시간 기준이라 모든 봉 간격이 같은 가격 경로를 공유한다
_WAVES = ((2400, 0.22), (700, 0.10), (160, 0.04), (45, 0.015), (13, 0.006))


def _base(symbol: str) -> float:
    for k, v in BASE_PRICE.items():
        if symbol.upper().startswith(k):
            return v
    return 100.0


def _close(t: int, base: float, phases: list[float], seed: int) -> float:
    h = t / 3600
    lp = sum(a * math.sin(2 * math.pi * h / p + ph) for (p, a), ph in zip(_WAVES, phases))
    lp += random.Random(seed * 1_000_003 + t).gauss(0, 0.002)
    return base * math.exp(lp)


def candles(symbol: str, interval: str, limit: int = 500, seed: int | None = None) -> list[dict]:
    step = INTERVAL_SECONDS.get(interval, 3600)
    end = int(time.time()) // step * step
    seed = seed if seed is not None else zlib.crc32(symbol.upper().encode())
    phase_rng = random.Random(seed)
    phases = [phase_rng.uniform(0, 2 * math.pi) for _ in _WAVES]
    base = _base(symbol)
    wick = 0.0015 * min(4.0, math.sqrt(step / 3600))
    out = []
    prev = _close(end - limit * step, base, phases, seed)
    for i in range(limit):
        t = end - (limit - 1 - i) * step
        c = _close(t, base, phases, seed)
        r = random.Random(seed * 7_919 + t + step)
        hi = max(prev, c) * (1 + abs(r.gauss(0, wick)))
        lo = min(prev, c) * (1 - abs(r.gauss(0, wick)))
        vol = abs(r.gauss(1000, 300)) * (step / 3600) * (1 + abs(c / prev - 1) * 80)
        out.append({"time": t, "open": prev, "high": hi, "low": lo, "close": c, "volume": vol})
        prev = c
    return out
