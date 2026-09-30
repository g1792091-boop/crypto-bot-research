"""청산 히트맵.

CoinGlass 키가 있으면 CoinGlass 모델 데이터를 쓰고, 없으면 공개 청산맵 모델들과 같은 방식으로 추정한다.

추정 방법
  1. 봉마다 미결제약정(OI)이 늘어난 만큼 "새 포지션"이 그 봉의 평균가(hlc3)에 진입했다고 본다.
     OI 데이터가 없으면 거래대금 일부를 신규 포지션으로 간주한다 (상대 강도만 의미 있음).
  2. 신규 포지션을 롱/숏 반씩, 레버리지 분포(10/25/50/100배)로 나눠 각 청산가에 쌓는다.
       롱 청산가 = 진입가 x (1 - 1/레버리지 + 유지증거금률), 숏은 반대
  3. OI가 줄면 쌓인 물량을 같은 비율로 줄인다 (포지션 정리). 시간이 지나며 자연 정리되는 포지션도
     있으므로 봉마다 조금씩 줄인다 (거래대금 기반 추정은 더 빠르게).
  4. 가격이 청산가를 지나가면 그 가격대 물량은 청산된 것으로 보고 지운다.
  5. 각 봉 시점의 남은 물량 분포가 히트맵의 한 열이 된다.
"""
from __future__ import annotations

from . import config
from .data import binance, coinglass, market

LEVERAGE_MIX = ((10, 0.30), (25, 0.30), (50, 0.25), (100, 0.15))
MMR = 0.005
BINS = 160


def _oi_series(symbol: str, interval: str, candles: list[dict]) -> list[float | None] | None:
    if config.DATA_SOURCE == "synthetic":
        return None
    try:
        pts = binance.open_interest_history(symbol, interval, 500)
    except Exception:
        return None
    if not pts:
        return None
    pts.sort(key=lambda p: p["time"])
    out, j, last = [], 0, None
    for b in candles:
        while j < len(pts) and pts[j]["time"] <= b["time"]:
            last = pts[j]["value"]; j += 1
        out.append(last)
    covered = sum(v is not None for v in out) / len(out)
    return out if covered >= 0.6 else None


def _zones(prices: list[float], values: list[float], step: float) -> list[dict]:
    """물량이 몰린 봉우리(peak)를 찾아 청산 구간으로 만든다.
    봉우리에서 양옆으로 물량이 봉우리의 절반 이상인 칸까지를 한 구간으로 본다."""
    n = len(values)
    sm = [sum(values[max(0, i - 1): i + 2]) / len(values[max(0, i - 1): i + 2]) for i in range(n)]
    top = max(sm, default=0)
    zones, used = [], [False] * n
    peaks = [i for i in range(n) if sm[i] >= 0.05 * top and sm[i] > 0
             and sm[i] >= (sm[i - 1] if i else 0) and sm[i] >= (sm[i + 1] if i < n - 1 else 0)]
    for i in sorted(peaks, key=lambda k: -sm[k]):
        if used[i]:
            continue
        a = b = i
        while a > 0 and not used[a - 1] and sm[a - 1] >= sm[i] * 0.5:
            a -= 1
        while b < n - 1 and not used[b + 1] and sm[b + 1] >= sm[i] * 0.5:
            b += 1
        for k in range(a, b + 1):
            used[k] = True
        val = sum(values[a: b + 1])
        if val <= 0:
            continue
        zones.append({"low": prices[a] - step / 2, "high": prices[b] + step / 2, "value": val,
                      "price": sum(prices[k] * values[k] for k in range(a, b + 1)) / val})
    return zones


def estimate(candles: list[dict], oi: list[float | None] | None = None, bins: int = BINS) -> dict:
    lo = min(b["low"] for b in candles) * 0.85
    hi = max(b["high"] for b in candles) * 1.15
    step = (hi - lo) / bins
    prices = [lo + (i + 0.5) * step for i in range(bins)]
    longs = [0.0] * bins    # 롱 청산 물량 (현재가 아래)
    shorts = [0.0] * bins   # 숏 청산 물량 (현재가 위)

    def idx(p: float) -> int | None:
        i = int((p - lo) / step)
        return i if 0 <= i < bins else None

    columns = []
    prev_oi = None
    decay = 0.997 if oi is not None else 0.975
    for k, b in enumerate(candles):
        if k:
            longs = [v * decay for v in longs]
            shorts = [v * decay for v in shorts]
        tp = (b["high"] + b["low"] + b["close"]) / 3
        if oi is not None:
            cur = oi[k]
            delta = (cur - prev_oi) if cur is not None and prev_oi is not None else 0.0
            if cur is not None:
                prev_oi = cur
        else:
            delta = b["volume"] * tp * 0.1  # 거래대금 기반 대체 지표
        total = sum(longs) + sum(shorts)
        if delta < 0 and total > 0:
            keep = max(0.0, 1 + delta / total)
            longs = [v * keep for v in longs]
            shorts = [v * keep for v in shorts]
        elif delta > 0:
            for lev, w in LEVERAGE_MIX:
                li = idx(tp * (1 - 1 / lev + MMR))
                si = idx(tp * (1 + 1 / lev - MMR))
                if li is not None:
                    longs[li] += delta * 0.5 * w
                if si is not None:
                    shorts[si] += delta * 0.5 * w
        # 이 봉의 저가~고가를 지나간 청산가는 청산 처리
        for i, p in enumerate(prices):
            if p >= b["low"] and longs[i]:
                longs[i] = 0.0
            if p <= b["high"] and shorts[i]:
                shorts[i] = 0.0
        col = [[i, int(longs[i] + shorts[i])] for i in range(bins) if longs[i] + shorts[i] >= 1]
        columns.append([b["time"], col])

    last_price = candles[-1]["close"]
    zones = _zones(prices, [longs[i] + shorts[i] for i in range(bins)], step)
    above = sorted((z for z in zones if z["price"] > last_price), key=lambda z: -z["value"])[:5]
    below = sorted((z for z in zones if z["price"] < last_price), key=lambda z: -z["value"])[:5]
    return {
        "price_min": lo, "price_step": step, "bins": bins,
        "columns": columns,
        "max_value": max((v for _, col in columns for _, v in col), default=0),
        "clusters_above": sorted(above, key=lambda c: c["price"]),
        "clusters_below": sorted(below, key=lambda c: -c["price"]),
        "unit": "usd" if oi is not None else "relative",
    }


def _from_coinglass(symbol: str, candles: list[dict]) -> dict | None:
    """CoinGlass model3 응답 → 같은 형식. 형식이 예상과 다르면 None (추정으로 대체)."""
    data = coinglass.liquidation_heatmap(symbol, "3d")
    y = data.get("y_axis") or data.get("y")
    cells = data.get("liquidation_leverage_data") or data.get("data")
    sticks = data.get("price_candlesticks") or []
    if not (y and cells and sticks):
        return None
    times = [int(s[0]) // (1000 if int(s[0]) > 10**11 else 1) for s in sticks]
    ys = [float(v) for v in y]
    step = (ys[-1] - ys[0]) / max(1, len(ys) - 1)
    cols: dict[int, list] = {}
    for x, yi, v in cells:
        cols.setdefault(int(x), []).append([int(yi), float(v)])
    columns = [[times[x], cols.get(x, [])] for x in range(len(times))]
    last = float(sticks[-1][4])
    tot: dict[int, float] = {}
    for x, col in cols.items():
        if x == len(times) - 1:
            for yi, v in col:
                tot[yi] = tot.get(yi, 0) + v
    clusters = sorted(({"price": ys[i], "value": v, "side": "long" if ys[i] < last else "short"}
                       for i, v in tot.items()), key=lambda c: -c["value"])
    return {
        "price_min": ys[0] - step / 2, "price_step": step, "bins": len(ys), "columns": columns,
        "max_value": max((v for _, col in columns for _, v in col), default=0),
        "clusters_above": sorted([c for c in clusters if c["price"] > last][:5], key=lambda c: c["price"]),
        "clusters_below": sorted([c for c in clusters if c["price"] < last][:5], key=lambda c: -c["price"]),
        "unit": "usd", "candles": [{"time": t, "open": float(s[1]), "high": float(s[2]), "low": float(s[3]),
                                    "close": float(s[4])} for t, s in zip(times, sticks)],
    }


def heatmap(symbol: str, interval: str, limit: int = 400) -> dict:
    candles, src = market.candles(symbol, interval, limit)
    if coinglass.enabled() and interval in ("15m", "30m", "1h"):
        try:
            cg = _from_coinglass(symbol, candles)
            if cg:
                return {**cg, "model": "coinglass", "data_source": "coinglass"}
        except Exception:
            pass
    oi = _oi_series(symbol, interval, candles)
    res = estimate(candles, oi)
    res.update(model="estimate_oi" if oi else "estimate_volume", data_source=src, candles=candles)
    return res
