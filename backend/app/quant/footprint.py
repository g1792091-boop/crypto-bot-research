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


# ---------------------------------------------------------------- 풋프린트 분석: 진입 신호 · 지지·저항 판정 · 다음 봉
def _zone_vol(b: dict, lo: float, hi: float) -> tuple[float, float]:
    """봉 안에서 [lo, hi) 가격 칸들의 (매도, 매수) 합."""
    s = sum(x[1] for x in b["levels"] if lo <= x[0] < hi)
    by = sum(x[2] for x in b["levels"] if lo <= x[0] < hi)
    return s, by


def bar_signals(bars: list[dict], atr: list, tick: float) -> list[dict]:
    """확정 봉마다 풋프린트 진입 신호. 같은 봉·같은 방향 이유는 하나로 묶는다."""
    out = []
    for i in range(10, len(bars) - 1):                     # 마지막(진행 중) 봉 제외
        b = bars[i]
        a = atr[i] or (b["high"] - b["low"]) or tick
        rng = (b["high"] - b["low"]) or tick
        vol = b["volume"] or 1e-12
        dr, clv = b["delta"] / vol, (b["close"] - b["low"]) / rng
        prev = bars[i - 10:i]
        plo, phi = min(x["low"] for x in prev), max(x["high"] for x in prev)
        s_bot, b_bot = _zone_vol(b, b["low"], b["low"] + rng * 0.25 + tick)
        s_top, b_top = _zone_vol(b, b["high"] - rng * 0.25, b["high"] + tick)
        why = {"long": [], "short": []}
        if b["low"] <= plo * 1.0005 and s_bot > b_bot * 1.5 and clv >= 0.55:
            why["long"].append("바닥에서 매도가 쏟아졌는데 가격이 버팀 — 매도 흡수")
        if b["high"] >= phi * 0.9995 and b_top > s_top * 1.5 and clv <= 0.45:
            why["short"].append("고점에서 매수가 몰렸는데 못 올라감 — 매수 흡수")
        d3 = [x["delta"] for x in bars[i - 3:i]]
        if sum(1 for d in d3 if d < 0) >= 2 and sum(d3) < 0 and dr >= 0.15 and b["close"] > bars[i - 1]["high"]:
            why["long"].append("매도 델타 뒤 강한 매수 델타로 반전, 직전 봉 고점 돌파")
        if sum(1 for d in d3 if d > 0) >= 2 and sum(d3) > 0 and dr <= -0.15 and b["close"] < bars[i - 1]["low"]:
            why["short"].append("매수 델타 뒤 강한 매도 델타로 반전, 직전 봉 저점 이탈")
        for j in range(max(0, i - 40), i - 1):
            for z in bars[j]["stacked"]:
                if z["side"] == "buy" and z["low"] - tick <= b["low"] <= z["high"] and b["close"] > z["high"] and dr > 0:
                    why["long"].append(f"이전 연속 매수 불균형 구간 {z['low']:.6g}~{z['high']:.6g} 다시 지지")
                if z["side"] == "sell" and z["low"] <= b["high"] <= z["high"] + tick and b["close"] < z["low"] and dr < 0:
                    why["short"].append(f"이전 연속 매도 불균형 구간 {z['low']:.6g}~{z['high']:.6g} 다시 저항")
        if b["low"] < plo and b["close"] > plo and dr > 0:
            why["long"].append(f"직전 10봉 저점 {plo:.6g} 아래를 쓸고 올라와 매수 델타로 마감 (스윕)")
        if b["high"] > phi and b["close"] < phi and dr < 0:
            why["short"].append(f"직전 10봉 고점 {phi:.6g} 위를 쓸고 내려와 매도 델타로 마감 (스윕)")
        if b["high"] > phi and dr < -0.1 and not why["short"]:
            why["short"].append("신고가인데 매도 델타 — 상승 힘 약함 (다이버전스)")
        if b["low"] < plo and dr > 0.1 and not why["long"]:
            why["long"].append("신저가인데 매수 델타 — 하락 힘 약함 (다이버전스)")
        for d, rs in why.items():
            rs = list(dict.fromkeys(rs))
            if not rs:
                continue
            if why["long"] and why["short"]:                # 같은 봉에서 양쪽이면 신호 약함 → 건너뜀
                continue
            e = b["close"]
            stop = (b["low"] - 0.2 * a) if d == "long" else (b["high"] + 0.2 * a)
            take = e + 2 * (e - stop)
            out.append({"i": i, "time": b["time"], "dir": d, "reasons": rs, "strength": min(3, len(rs)),
                        "entry": e, "stop": stop, "take": take})
    # 지난 신호 성적: 다음 20봉 안에 익절(2R)과 손절 중 무엇이 먼저 닿았나
    for s in out:
        res = None
        for b in bars[s["i"] + 1:s["i"] + 21]:
            if b is bars[-1]:
                break
            hit_s = b["low"] <= s["stop"] if s["dir"] == "long" else b["high"] >= s["stop"]
            hit_t = b["high"] >= s["take"] if s["dir"] == "long" else b["low"] <= s["take"]
            if hit_s:
                res = "stop"
                break
            if hit_t:
                res = "take"
                break
        s["outcome"] = res
    return out


def level_tests(bars: list[dict], levels: list[dict], atr: float, tick: float) -> list[dict]:
    """가격대마다 최근 40봉에서 닿은 봉들의 체결로 '지지·저항을 하는지' 판정."""
    price = bars[-1]["close"]
    done = bars[-41:-1] if len(bars) > 41 else bars[:-1]
    out = []
    for lv in levels:
        L = lv["price"]
        role = "support" if L < price else "resistance"
        def covers(b):   # 풋프린트 가격 칸 범위 기준 (체결이 실제로 있었던 가격)
            lo = b["levels"][0][0] if b["levels"] else b["low"]
            hi = b["levels"][-1][0] + tick if b["levels"] else b["high"]
            return lo - tick * 0.5 <= L <= hi + tick * 0.5
        touch = [b for b in done if covers(b)]
        s_at = b_at = dl = 0.0
        closes_ok = 0
        for b in touch:
            s, by = _zone_vol(b, L - tick * 1.01, L + tick * 1.01)
            s_at += s
            b_at += by
            dl += b["delta"]
            closes_ok += (b["close"] >= L) if role == "support" else (b["close"] <= L)
        last_bad = (price < L - 0.15 * atr) if role == "support" else (price > L + 0.15 * atr)
        n = len(touch)
        if not n:
            status, text = "untested", "최근 40봉 동안 닿지 않음 — 첫 테스트 때 반응을 보세요"
        elif closes_ok == n:
            if role == "support":
                status = "holding"
                text = (f"{n}번 닿았고 모두 위에서 마감 · " +
                        ("매도가 쏟아졌는데도 버팀 (매도 흡수) — 강한 지지" if s_at > b_at * 1.2 else
                         "매수가 받쳐 줌 (매수 방어)" if b_at > s_at * 1.2 else "매수·매도 비슷 — 지지는 되지만 힘은 보통"))
            else:
                status = "holding"
                text = (f"{n}번 닿았고 모두 아래에서 마감 · " +
                        ("매수가 몰렸는데도 못 뚫음 (매수 흡수) — 강한 저항" if b_at > s_at * 1.2 else
                         "매도가 눌러 줌 (매도 방어)" if s_at > b_at * 1.2 else "매수·매도 비슷 — 저항은 되지만 힘은 보통"))
        elif closes_ok >= n / 2:
            status, text = "weakening", f"{n}번 중 {n - closes_ok}번은 넘어가서 마감 — 흔들리는 중, 다음 테스트에 깨질 수 있음"
        else:
            status, text = "broken", f"{n}번 중 {n - closes_ok}번 넘어가서 마감 — 역할이 바뀌었을 가능성 (지지 → 저항 / 저항 → 지지)"
        out.append({**lv, "role": role, "status": status, "touches": n, "sell_at": round(s_at, 4), "buy_at": round(b_at, 4),
                    "delta_on_touch": round(dl, 4), "text": text, "distance_atr": round((L - price) / atr, 2) if atr else None})
    return sorted(out, key=lambda x: abs(x["price"] - price))


def next_bar_odds(c: list[dict]) -> dict:
    """봉의 델타(시장가 매수−매도)와 마감 위치(고가~저가 중 어디서 끝났나)가 비슷했던 과거 봉의 다음 봉 결과."""
    def bucket(b):
        v = b["volume"] or 1e-12
        tb = b.get("taker_buy")
        dr = (2 * tb - v) / v if tb is not None else 0.0
        rng = (b["high"] - b["low"]) or 1e-12
        clv = (b["close"] - b["low"]) / rng
        d = 0 if dr < -0.15 else 1 if dr < -0.05 else 2 if dr <= 0.05 else 3 if dr <= 0.15 else 4
        p = 0 if clv < 0.33 else 1 if clv <= 0.67 else 2
        return d, p, dr, clv
    stats: dict[tuple, list] = {}
    ups = tot = 0
    for i in range(len(c) - 2):                             # 마지막 두 봉(진행 중과 그 앞)은 결과를 모름
        d, p, _, _ = bucket(c[i])
        r = c[i + 1]["close"] / c[i]["close"] - 1
        stats.setdefault((d, p), []).append(r)
        tot += 1
        ups += r > 0
    D = ["강한 매도", "매도 우위", "균형", "매수 우위", "강한 매수"]
    P = ["저가 부근", "중간", "고가 부근"]

    def one(b, label):
        d, p, dr, clv = bucket(b)
        rs = stats.get((d, p), [])
        n = len(rs)
        pu = round(100 * sum(1 for r in rs if r > 0) / n) if n else None
        return {"label": label, "delta_ratio": round(dr, 3), "close_loc": round(clv, 2), "bucket": f"델타 {D[d]} · {P[p]} 마감",
                "n": n, "p_up": pu, "mean_ret_pct": round(sum(rs) / n * 100, 3) if n else None}
    base = round(100 * ups / tot) if tot else 50
    last_closed, forming = one(c[-2], "직전 확정 봉 → 지금 봉"), one(c[-1], "지금 봉이 이대로 끝나면 → 다음 봉")
    return {"baseline_up": base, "last_closed": last_closed, "forming": forming, "history": tot,
            "note": "같은 모양의 봉이 과거에 몇 번 있었고, 그다음 봉이 몇 % 올랐는지입니다. 표본(n)이 30개 미만이면 믿기 어렵습니다."}


def analyze(symbol: str, interval: str, bars: int = 80) -> dict:
    """풋프린트 + 진입 신호 + 지지·저항 판정 + 다음 봉."""
    from .. import analysis
    from .. import indicators as ind
    from . import forecast
    fp = footprint(symbol, interval, bars)
    fb = fp["bars"]
    atr_s = ind.atr(fb, 14)
    a = next((x for x in reversed(atr_s) if x), None) or (fb[-1]["high"] - fb[-1]["low"]) or fp["tick"]
    sigs = bar_signals(fb, atr_s, fp["tick"])
    done = [s for s in sigs if s["outcome"]]
    wins = sum(1 for s in done if s["outcome"] == "take")
    # 지지·저항 후보: 연속 불균형 구간 · 세션 POC/VAH/VAL · 자동 지지저항 구간
    c, _ = market.candles(symbol, interval, 1500)
    levels = []
    for b in fb[-60:-1]:
        for z in b["stacked"]:
            levels.append({"price": (z["low"] + z["high"]) / 2, "source": "연속 매수 불균형" if z["side"] == "buy" else "연속 매도 불균형"})
    prof = forecast.session_profiles(c[-400:], ind.atr(c[-400:], 14))
    if prof[-1][1]:
        p = prof[-1][1]
        levels += [{"price": p["poc"], "source": "직전 세션 POC"}, {"price": p["vah"], "source": "직전 세션 VAH"}, {"price": p["val"], "source": "직전 세션 VAL"}]
    levels.append({"price": prof[-1][0], "source": "현재 세션 POC"})
    for z in analysis.sr_levels(c)["zones"]:
        levels.append({"price": z["price"], "source": f"지지·저항 구간 ({z['touches']}회)"})
    price = fb[-1]["close"]
    near = sorted([lv for lv in levels if abs(lv["price"] - price) <= 2.5 * a], key=lambda lv: abs(lv["price"] - price))
    merged: list[dict] = []
    for lv in near:                                        # 0.3 ATR 안쪽은 하나로 (근거 합침)
        m = next((x for x in merged if abs(x["price"] - lv["price"]) <= 0.3 * a), None)
        if m:
            if lv["source"] not in m["source"]:
                m["source"] += " · " + lv["source"]
        else:
            merged.append(dict(lv))
    tests = level_tests(fb, merged[:8], a, fp["tick"])
    odds = next_bar_odds(c)
    return {**fp, "analysis": {
        "signals": [{k: v for k, v in s.items() if k != "i"} for s in sigs[-25:]],
        "signal_stats": {"n": len(done), "wins": wins, "win_rate": round(100 * wins / len(done)) if done else None,
                         "note": "지난 신호를 '진입가에서 2배 거리 익절 vs 봉 끝 너머 손절' 중 무엇이 먼저 닿았는지로 채점"},
        "levels": tests, "next": odds, "atr": a,
    }}
