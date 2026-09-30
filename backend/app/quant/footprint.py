"""봉 볼륨 풋프린트 — 봉 하나 안에서 가격대별 시장가 매수·매도 체결량.

진짜 풋프린트는 모든 체결 내역이 필요한데, 바이낸스는 과거 체결을 한 번에 많이 주지 않는다.
그래서 봉을 작은 봉(예: 1시간봉 → 1분봉 60개)으로 쪼개고, 작은 봉마다 거래량과 '테이커 매수량'을
그 봉의 고가~저가 가격 칸에 고르게 나눠 담아 근사한다. 1분봉 단위까지는 실제 체결 방향이 반영된다.

- 델타 = 매수 − 매도 (봉 전체), POC = 가장 많이 거래된 가격 칸
- 대각 불균형: 한 칸의 매수량이 한 칸 아래 매도량의 3배 이상(매수 불균형) / 반대(매도 불균형)
- 연속 불균형(3칸 이상) = 공격적인 매수·매도가 몰린 구간 → 이후 지지·저항으로 자주 작동
"""
from __future__ import annotations

import bisect
import math

from ..data import market
from ..data.synthetic import INTERVAL_SECONDS
from ..orderflow import nice_step

SUB = {"3m": "1m", "5m": "1m", "15m": "1m", "30m": "1m", "1h": "1m", "2h": "5m", "4h": "5m", "6h": "15m",
       "12h": "15m", "1d": "1h", "3d": "1h", "1w": "4h", "1M": "1d"}
RATIO = 3.0            # 불균형 배수
MAX_SUB = 6000


def _sec(iv: str) -> int:
    return INTERVAL_SECONDS.get(iv, 3600)


def footprint(symbol: str, interval: str, bars: int = 60, rows: int = 14) -> dict:
    if interval not in SUB:
        raise ValueError("1분봉은 쪼갤 작은 봉이 없어 풋프린트를 만들 수 없습니다. 3분봉 이상에서 보세요.")
    sub_iv = SUB[interval]
    per = max(1, round(_sec(interval) / _sec(sub_iv)))
    bars = max(5, min(bars, MAX_SUB // per))
    parents, src = market.candles(symbol, interval, bars)
    subs, _ = market.candles(symbol, sub_iv, min(MAX_SUB, bars * per + per))
    # 가격 칸 크기: 최근 봉들의 중간 크기 봉을 rows 칸 정도로
    rngs = sorted(b["high"] - b["low"] for b in parents if b["high"] > b["low"])
    med = rngs[len(rngs) // 2] if rngs else parents[-1]["close"] * 0.002
    tick = nice_step(max(med / rows, parents[-1]["close"] * 0.00001))
    ptimes = [b["time"] for b in parents]
    acc: list[dict[float, list[float]]] = [dict() for _ in parents]
    covered = [0] * len(parents)
    for s in subs:
        k = bisect.bisect_right(ptimes, s["time"]) - 1
        if k < 0:
            continue
        buy = s.get("taker_buy")
        buy = s["volume"] / 2 if buy is None else buy
        sell = s["volume"] - buy
        lo, hi = math.floor(s["low"] / tick), math.floor(s["high"] / tick)
        n = hi - lo + 1
        for lv in range(lo, hi + 1):
            cell = acc[k].setdefault(round(lv * tick, 10), [0.0, 0.0])
            cell[0] += sell / n
            cell[1] += buy / n
        covered[k] += 1
    out = []
    cvd = 0.0
    for k, b in enumerate(parents):
        lv = sorted(acc[k].items())
        if not lv:
            continue
        sells = {p: v[0] for p, v in lv}
        buys = {p: v[1] for p, v in lv}
        tot = [v[0] + v[1] for _, v in lv]
        poc = lv[max(range(len(lv)), key=lambda i: tot[i])][0]
        delta = sum(buys.values()) - sum(sells.values())
        cvd += delta
        avg = sum(tot) / len(tot)
        imb_b, imb_s = [], []
        for p, (s_, b_) in lv:
            below = sells.get(round(p - tick, 10), 0.0)
            above = buys.get(round(p + tick, 10), 0.0)
            if b_ > avg * 0.3 and b_ >= RATIO * max(below, 1e-12):
                imb_b.append(p)
            if s_ > avg * 0.3 and s_ >= RATIO * max(above, 1e-12):
                imb_s.append(p)
        stacked = []
        for side, ps in (("buy", imb_b), ("sell", imb_s)):
            run = [ps[0]] if ps else []
            for p in ps[1:] + [None]:
                if p is not None and abs(p - run[-1] - tick) < tick * 1e-6:
                    run.append(p)
                    continue
                if len(run) >= 3:
                    stacked.append({"side": side, "low": run[0], "high": run[-1] + tick})
                run = [p] if p is not None else []
        out.append({"time": b["time"], "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
                    "volume": sum(tot), "delta": delta, "cvd": cvd, "poc": poc, "complete": covered[k] >= per * 0.9,
                    "levels": [[p, round(v[0], 6), round(v[1], 6)] for p, v in lv], "imb_buy": imb_b, "imb_sell": imb_s,
                    "stacked": stacked})
    return {"symbol": symbol, "interval": interval, "sub_interval": sub_iv, "tick": tick, "data_source": src,
            "approx": True, "bars": out, "summary": summarize(out)}


def summarize(bars: list[dict]) -> dict:
    """마지막 확정 봉(진행 중인 봉 바로 앞)과 최근 흐름을 말로."""
    if len(bars) < 3:
        return {"notes": []}
    last, cur = bars[-2], bars[-1]
    notes, score = [], 0
    dr = last["delta"] / last["volume"] if last["volume"] else 0
    up = last["close"] >= last["open"]
    if abs(dr) >= 0.15:
        notes.append(f"직전 봉 델타 {'매수' if dr > 0 else '매도'} 우위 ({dr * 100:+.0f}%)")
        score += 1 if dr > 0 else -1
    if up and dr < -0.1:
        notes.append("양봉인데 매도 체결이 더 많음 — 위에서 매도 흡수, 상승 힘 약함")
        score -= 1
    if not up and dr > 0.1:
        notes.append("음봉인데 매수 체결이 더 많음 — 아래에서 매수 흡수, 하락 힘 약함")
        score += 1
    rng = (last["high"] - last["low"]) or 1e-12
    pos = (last["poc"] - last["low"]) / rng
    if pos >= 0.7:
        notes.append("직전 봉 거래가 윗부분(POC 상단)에 몰림 — 위쪽 가격 수용")
    elif pos <= 0.3:
        notes.append("직전 봉 거래가 아랫부분(POC 하단)에 몰림 — 아래쪽 가격 수용")
    recent = bars[-11:-1]
    cvd_chg = sum(b["delta"] for b in recent)
    vol = sum(b["volume"] for b in recent) or 1
    px_chg = recent[-1]["close"] - recent[0]["open"]
    if px_chg > 0 and cvd_chg < 0:
        notes.append("최근 10봉 가격은 올랐는데 누적 델타는 감소 — 약세 다이버전스")
        score -= 1
    elif px_chg < 0 and cvd_chg > 0:
        notes.append("최근 10봉 가격은 내렸는데 누적 델타는 증가 — 강세 다이버전스")
        score += 1
    zones = [dict(z, time=b["time"]) for b in bars[-30:-1] for z in b["stacked"]]
    price = cur["close"]
    sup = [z for z in zones if z["side"] == "buy" and z["high"] <= price]
    res = [z for z in zones if z["side"] == "sell" and z["low"] >= price]
    if sup:
        z = max(sup, key=lambda z: z["high"])
        notes.append(f"아래 연속 매수 불균형 구간 {z['low']:.6g}~{z['high']:.6g} — 지지 후보")
    if res:
        z = min(res, key=lambda z: z["low"])
        notes.append(f"위 연속 매도 불균형 구간 {z['low']:.6g}~{z['high']:.6g} — 저항 후보")
    return {"score": score, "delta_ratio": round(dr, 3), "cvd10_ratio": round(cvd_chg / vol, 3), "notes": notes,
            "support": [z for z in sup][-3:], "resistance": [z for z in res][:3]}
