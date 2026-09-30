"""시장 상태 판단 (롱 우위 / 숏 우위 / 횡보) 과 매매 시나리오.

점수 (-100 ~ +100)
  EMA 배열 30% · EMA50 기울기(ATR 대비) 25% · 슈퍼트렌드 20% · 고점/저점 구조 15% · MACD 모멘텀 10%
판정
  추세성 = ADX ≥ 20 이고 효율비(ER, 40봉 순이동 ÷ 총이동) ≥ 0.3
  추세성이 없고 |점수| < 70 → 횡보, 점수 ≥ 30 → 롱 우위, 점수 ≤ -30 → 숏 우위, 그 외 횡보
시나리오
  스윙 고점/저점, 박스 상·하단, EMA, 청산 구간을 레벨로 쓰고 ATR 로 손절 폭을 잡는다.
"""
from __future__ import annotations

import time

from . import config, indicators as ind, liquidation, llm
from .data import market

MTF = ("15m", "1h", "4h", "1d")
LABEL = {"long": "롱 우위", "short": "숏 우위", "range": "횡보"}


def _last(x, k: int = 1):
    vals = [v for v in x if v is not None]
    return vals[-k] if len(vals) >= k else None


def _clamp(v: float, a: float = -1.0, b: float = 1.0) -> float:
    return max(a, min(b, v))


def pivots(c: list[dict], left: int = 3, right: int = 3) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs, lows = [], []
    for i in range(left, len(c) - right):
        h, l = c[i]["high"], c[i]["low"]
        if all(h >= c[j]["high"] for j in range(i - left, i + right + 1)):
            highs.append((i, h))
        if all(l <= c[j]["low"] for j in range(i - left, i + right + 1)):
            lows.append((i, l))
    return highs, lows


def regime(c: list[dict]) -> dict:
    close = [b["close"] for b in c]
    px = close[-1]
    e20, e50, e200 = ind.ema(close, 20), ind.ema(close, 50), ind.ema(close, 200)
    atr = _last(ind.atr(c)) or px * 0.01
    reasons: list[str] = []

    a20, a50, a200 = _last(e20), _last(e50), _last(e200)
    if a20 and a50:
        if px > a20 > a50:
            align = 1.0 if (a200 is None or a50 > a200) else 0.6
            reasons.append("가격 > EMA20 > EMA50 정배열" + (" (EMA200 위)" if a200 and a50 > a200 else ""))
        elif px < a20 < a50:
            align = -1.0 if (a200 is None or a50 < a200) else -0.6
            reasons.append("가격 < EMA20 < EMA50 역배열" + (" (EMA200 아래)" if a200 and a50 < a200 else ""))
        else:
            align = 0.3 if px > a50 else -0.3
            reasons.append(f"이평선 혼조 (가격 EMA50 {'위' if px > a50 else '아래'})")
    else:
        align = 0.0

    e50v = [v for v in e50 if v is not None]
    slope = _clamp((e50v[-1] - e50v[-11]) / (10 * atr) * 4) if len(e50v) > 11 else 0.0
    st_trend = _last(ind.supertrend(c)["trend"]) or 0
    reasons.append(f"슈퍼트렌드 {'상승' if st_trend > 0 else '하락'}")

    ph, pl = pivots(c[-150:])
    structure = 0.0
    if len(ph) >= 2 and len(pl) >= 2:
        hh, hl = ph[-1][1] > ph[-2][1], pl[-1][1] > pl[-2][1]
        if hh and hl:
            structure = 1.0; reasons.append("고점·저점 모두 높아지는 상승 구조")
        elif not hh and not hl:
            structure = -1.0; reasons.append("고점·저점 모두 낮아지는 하락 구조")
        else:
            reasons.append("고점/저점 방향이 엇갈림 (수렴·박스)")

    m = ind.macd(close)
    h1, h2 = _last(m["hist"]), _last(m["hist"], 2)
    mom = 0.0
    if h1 is not None and h2 is not None:
        mom = (0.5 if h1 > 0 else -0.5) + (0.5 if h1 > h2 else -0.5)

    score = round(100 * (0.30 * align + 0.25 * slope + 0.20 * st_trend + 0.15 * structure + 0.10 * mom))
    adx = _last(ind.adx(c)["adx"]) or 0.0
    rsi = _last(ind.rsi(close)) or 50.0
    width = [v for v in ind.bbands(close)["width"] if v is not None][-120:]
    squeeze_rank = (sum(w <= width[-1] for w in width) / len(width) * 100) if width else 50.0

    n_er = min(40, len(close) - 1)
    path = sum(abs(close[i] - close[i - 1]) for i in range(len(close) - n_er, len(close)))
    er = abs(close[-1] - close[-1 - n_er]) / path if path else 0.0
    trending = adx >= 20 and er >= 0.3
    if not trending and abs(score) < 70:
        state = "range"
    elif score >= 30:
        state = "long"
    elif score <= -30:
        state = "short"
    else:
        state = "range"
    reasons.append(f"ADX {adx:.0f} · 효율비 {er:.2f} → "
                   f"{'한 방향으로 꾸준히 움직임' if trending else '오르내림 반복 (방향성 약함)'}")
    if squeeze_rank <= 20:
        reasons.append("볼린저 밴드 폭이 최근 하위 20% — 변동성 수축, 큰 움직임 전조")
    if rsi >= 70:
        reasons.append(f"RSI {rsi:.0f} 과매수")
    elif rsi <= 30:
        reasons.append(f"RSI {rsi:.0f} 과매도")

    strength = abs(score) if state != "range" else max(0, 50 - abs(score)) + (20 - min(adx, 20))
    confidence = "높음" if strength >= 60 and (state == "range" or trending) else "보통" if strength >= 35 else "낮음"
    look = c[-31:-1] if len(c) > 31 else c[:-1]
    return {
        "state": state, "label": LABEL[state], "score": score, "confidence": confidence,
        "adx": round(adx, 1), "er": round(er, 2), "rsi": round(rsi, 1), "squeeze_rank": round(squeeze_rank),
        "atr": atr, "price": px,
        "ema20": a20, "ema50": a50, "ema200": a200,
        "range_high": max(b["high"] for b in look), "range_low": min(b["low"] for b in look),
        "reasons": reasons,
    }


def _levels(c: list[dict], reg: dict, liq: dict | None) -> tuple[list[dict], list[dict]]:
    px = reg["price"]
    ph, pl = pivots(c[-300:], 5, 5)
    res = [{"price": p, "kind": "스윙 고점"} for _, p in ph if p > px]
    sup = [{"price": p, "kind": "스윙 저점"} for _, p in pl if p < px]
    for key, kind in (("ema50", "EMA50"), ("ema200", "EMA200")):
        v = reg.get(key)
        if v:
            (res if v > px else sup).append({"price": v, "kind": kind})
    res.append({"price": reg["range_high"], "kind": "박스 상단"}) if reg["range_high"] > px else None
    sup.append({"price": reg["range_low"], "kind": "박스 하단"}) if reg["range_low"] < px else None
    if liq:
        res += [{"price": z["price"], "kind": "숏 청산 구간"} for z in liq.get("clusters_above", [])[:3]]
        sup += [{"price": z["price"], "kind": "롱 청산 구간"} for z in liq.get("clusters_below", [])[:3]]
    # 너무 가까운 레벨(0.3 ATR 이내)은 하나로
    def dedupe(xs, reverse):
        out = []
        for x in sorted(xs, key=lambda x: x["price"], reverse=reverse):
            if not out or abs(x["price"] - out[-1]["price"]) > reg["atr"] * 0.75:
                out.append(x)
        return out
    return dedupe(res, False)[:5], dedupe(sup, True)[:5]


def _targets(entry: float, stop: float, levels: list[float], side: int) -> list[float]:
    """진입가 기준으로 최소 1R 이상 떨어진 레벨을 1차 목표로, 그 다음 레벨을 2차 목표로."""
    risk = abs(entry - stop)
    beyond = sorted((p for p in levels if side * (p - entry) >= risk), key=lambda p: side * p)
    t1 = beyond[0] if beyond else entry + side * 1.5 * risk
    rest = [p for p in beyond if side * (p - t1) >= 0.5 * risk]
    t2 = rest[0] if rest else t1 + side * 1.5 * risk
    return [t1, t2]


def _rr(entry: float, stop: float, target: float) -> float | None:
    risk = abs(entry - stop)
    return round(abs(target - entry) / risk, 2) if risk else None


def scenarios(c: list[dict], reg: dict, liq: dict | None = None) -> dict:
    px, atr, score = reg["price"], reg["atr"], reg["score"]
    res, sup = _levels(c, reg, liq)
    r1 = res[0]["price"] if res else px + 2 * atr
    s1 = sup[0]["price"] if sup else px - 2 * atr
    up_levels = [x["price"] for x in res]
    dn_levels = [x["price"] for x in sup]

    p_up = _clamp(0.5 + score / 200, 0.1, 0.9)
    w_range = 0.5 if reg["state"] == "range" else (0.3 if reg["er"] < 0.4 else 0.15)
    probs = {"long": (1 - w_range) * p_up, "short": (1 - w_range) * (1 - p_up), "range": w_range}

    out = []
    if reg["state"] == "long":
        entry = max(s1, reg["ema20"] or s1)
        stop = min(s1, entry) - 0.5 * atr
        out.append({"key": "long", "title": "눌림목 롱", "bias": "long",
                    "trigger": f"{entry:,.2f} 부근까지 되돌림 후 지지 확인 (아래꼬리·거래량)",
                    "entry": entry, "stop": stop, "targets": _targets(entry, stop, up_levels, 1)})
    else:
        entry = r1 + 0.1 * atr
        stop = r1 - 1.2 * atr
        out.append({"key": "long", "title": "저항 돌파 롱", "bias": "long",
                    "trigger": f"{r1:,.2f} ({res[0]['kind'] if res else '저항'}) 위 종가 마감",
                    "entry": entry, "stop": stop, "targets": _targets(entry, stop, up_levels, 1)})
    if reg["state"] == "short":
        entry = min(r1, reg["ema20"] or r1)
        stop = max(r1, entry) + 0.5 * atr
        out.append({"key": "short", "title": "반등 숏", "bias": "short",
                    "trigger": f"{entry:,.2f} 부근까지 반등 후 저항 확인 (윗꼬리·거래량)",
                    "entry": entry, "stop": stop, "targets": _targets(entry, stop, dn_levels, -1)})
    else:
        entry = s1 - 0.1 * atr
        stop = s1 + 1.2 * atr
        out.append({"key": "short", "title": "지지 이탈 숏", "bias": "short",
                    "trigger": f"{s1:,.2f} ({sup[0]['kind'] if sup else '지지'}) 아래 종가 마감",
                    "entry": entry, "stop": stop, "targets": _targets(entry, stop, dn_levels, -1)})
    lo, hi = reg["range_low"], reg["range_high"]
    if hi - lo > 2 * atr:
        out.append({"key": "range", "title": "박스권 양방향", "bias": "range",
                    "trigger": f"{lo:,.2f} ~ {hi:,.2f} 박스 유지 시 하단 롱 / 상단 숏",
                    "entry": lo + 0.2 * atr, "stop": lo - 0.7 * atr,
                    "targets": [(lo + hi) / 2, hi - 0.2 * atr],
                    "alt": {"entry": hi - 0.2 * atr, "stop": hi + 0.7 * atr, "targets": [(lo + hi) / 2, lo + 0.2 * atr]}})
    for s in out:
        s["probability"] = round(probs[s["key"]] * 100)
        s["rr"] = _rr(s["entry"], s["stop"], s["targets"][0])
        s["invalidation"] = f"{s['stop']:,.2f} {'이탈' if s['bias'] != 'short' else '돌파'} 시 무효"
    total = sum(s["probability"] for s in out) or 1
    for s in out:
        s["probability"] = round(s["probability"] / total * 100)
    out.sort(key=lambda s: -s["probability"])
    return {"scenarios": out, "resistance": res, "support": sup}


def _mtf(symbol: str) -> list[dict]:
    rows = []
    for tf in MTF:
        try:
            c, _ = market.candles(symbol, tf, 300)
            r = regime(c)
            rows.append({"interval": tf, "state": r["state"], "label": r["label"], "score": r["score"]})
        except Exception:
            continue
    return rows


_ai_cache: dict[tuple, str] = {}

AI_PROMPT = ("너는 코인 선물 데스크의 시니어 트레이더다. 아래 JSON(현재 시장 판단, 멀티 타임프레임, 레벨, 청산 구간, "
             "시나리오)을 보고 한국어로 4~6문장 브리핑을 쓴다. 지금 어떤 장인지, 가장 가능성 높은 시나리오와 "
             "진입·손절 기준, 조심할 가격대(청산 구간)를 구체적 숫자로 말한다. 데이터에 없는 뉴스나 사실은 지어내지 않는다. "
             "제목, 목록, 이모지 없이 문단으로만 쓴다.")


def analyze(symbol: str, interval: str, with_ai: bool = False) -> dict:
    c, src = market.candles(symbol, interval, 400)
    reg = regime(c)
    try:
        liq = liquidation.heatmap(symbol, interval, 400)
        liq_brief = {k: liq[k] for k in ("clusters_above", "clusters_below", "model", "unit")}
    except Exception:
        liq, liq_brief = None, None
    sc = scenarios(c, reg, liq)
    out = {"symbol": symbol, "interval": interval, "data_source": src, "time": int(time.time()),
           "bar_time": c[-1]["time"], "regime": reg, "mtf": _mtf(symbol), "liquidation": liq_brief, **sc,
           "ai_comment": None}
    if with_ai and config.llm_enabled():
        key = (symbol, interval, c[-1]["time"])
        if key not in _ai_cache:
            import json
            payload = {k: out[k] for k in ("regime", "mtf", "resistance", "support", "scenarios", "liquidation")}
            _ai_cache[key] = llm.text(AI_PROMPT, json.dumps(payload, ensure_ascii=False, default=float), effort="low")
        out["ai_comment"] = _ai_cache[key]
    return out
