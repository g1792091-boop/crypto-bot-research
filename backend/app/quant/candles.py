"""캔들·차트 패턴 — 찾기 + 이 코인 과거에서 그 패턴 뒤 N봉 결과 통계 (패턴이 실제로 통했는지 검증).

캔들: 상승/하락 장악형, 망치형, 역망치형, 유성형, 교수형, 도지, 샛별, 저녁별, 적삼병, 흑삼병, 상승/하락 잉태형.
차트: 쌍바닥, 쌍봉, 헤드앤숄더(역), 삼각수렴 (스윙 고저점으로 판정).
"""
from __future__ import annotations

from .. import indicators as ind
from ..analysis import pivots

KO = {"bull_engulf": "상승 장악형", "bear_engulf": "하락 장악형", "hammer": "망치형", "inv_hammer": "역망치형", "shooting_star": "유성형",
      "hanging_man": "교수형", "doji": "도지", "morning_star": "샛별형", "evening_star": "저녁별형", "three_white": "적삼병",
      "three_black": "흑삼병", "bull_harami": "상승 잉태형", "bear_harami": "하락 잉태형"}
BIAS = {"bull_engulf": 1, "bear_engulf": -1, "hammer": 1, "inv_hammer": 1, "shooting_star": -1, "hanging_man": -1, "doji": 0,
        "morning_star": 1, "evening_star": -1, "three_white": 1, "three_black": -1, "bull_harami": 1, "bear_harami": -1}


def _body(b):
    return abs(b["close"] - b["open"])


def _rng(b):
    return max(1e-12, b["high"] - b["low"])


def detect_at(c: list[dict], i: int, trend: float) -> list[str]:
    """i 번째 봉에서 끝나는 캔들 패턴. trend: 직전 추세(+ 상승, - 하락)."""
    if i < 3:
        return []
    b, p, q = c[i], c[i - 1], c[i - 2]
    out = []
    up = b["close"] > b["open"]
    pup = p["close"] > p["open"]
    body, rng = _body(b), _rng(b)
    upper = b["high"] - max(b["open"], b["close"])
    lower = min(b["open"], b["close"]) - b["low"]
    if up and not pup and b["close"] >= p["open"] and b["open"] <= p["close"] and body > _body(p):
        out.append("bull_engulf")
    if not up and pup and b["open"] >= p["close"] and b["close"] <= p["open"] and body > _body(p):
        out.append("bear_engulf")
    if body / rng < 0.1:
        out.append("doji")
    if lower >= 2 * body and upper <= body * 0.5 and body / rng > 0.05:
        out.append("hammer" if trend < 0 else "hanging_man" if trend > 0 else "hammer")
    if upper >= 2 * body and lower <= body * 0.5 and body / rng > 0.05:
        out.append("inv_hammer" if trend < 0 else "shooting_star" if trend > 0 else "shooting_star")
    if q["close"] < q["open"] and _body(p) < _body(q) * 0.4 and up and b["close"] > (q["open"] + q["close"]) / 2:
        out.append("morning_star")
    if q["close"] > q["open"] and _body(p) < _body(q) * 0.4 and not up and b["close"] < (q["open"] + q["close"]) / 2:
        out.append("evening_star")
    if all(x["close"] > x["open"] for x in (q, p, b)) and q["close"] < p["close"] < b["close"] and all(_body(x) / _rng(x) > 0.5 for x in (q, p, b)):
        out.append("three_white")
    if all(x["close"] < x["open"] for x in (q, p, b)) and q["close"] > p["close"] > b["close"] and all(_body(x) / _rng(x) > 0.5 for x in (q, p, b)):
        out.append("three_black")
    if not pup and up and b["high"] < p["open"] and b["low"] > p["close"]:
        out.append("bull_harami")
    if pup and not up and b["high"] < p["close"] and b["low"] > p["open"]:
        out.append("bear_harami")
    return out


def candle_stats(c: list[dict], horizon: int = 5) -> dict:
    """과거 전체에서 패턴별: 횟수, horizon 봉 뒤 평균 수익률, 패턴 방향대로 간 비율."""
    cl = [b["close"] for b in c]
    ema = ind.ema(cl, 20)
    stats: dict = {}
    for i in range(25, len(c) - horizon):
        tr = (cl[i - 1] - ema[i - 1]) if ema[i - 1] else 0
        for k in detect_at(c, i, tr):
            r = (cl[i + horizon] / cl[i] - 1) * 100
            s = stats.setdefault(k, {"n": 0, "sum": 0.0, "hit": 0})
            s["n"] += 1
            s["sum"] += r
            s["hit"] += (r > 0) if BIAS[k] > 0 else (r < 0) if BIAS[k] < 0 else (abs(r) < 1)
    return {k: {"ko": KO[k], "n": v["n"], "avg_ret": round(v["sum"] / v["n"], 3), "hit_pct": round(v["hit"] / v["n"] * 100, 1),
                "reliable": v["n"] >= 30} for k, v in stats.items()}


def chart_patterns(c: list[dict]) -> list[dict]:
    """최근 스윙으로 판정한 차트 패턴 (가장 최근 것 위주)."""
    ph, pl = pivots(c, 5, 5)
    atr = next((v for v in reversed(ind.atr(c, 14)) if v), c[-1]["close"] * 0.01)
    out = []
    if len(pl) >= 2:
        (i1, a), (i2, b) = pl[-2], pl[-1]
        if abs(a - b) <= atr * 0.8 and i2 - i1 >= 5:
            neck = max(x["high"] for x in c[i1:i2 + 1])
            out.append({"name": "쌍바닥", "bias": 1, "level": neck, "text": f"저점 {a:,.4g}·{b:,.4g} 두 번 지지 · 넥라인 {neck:,.4g} 돌파 시 확인"})
    if len(ph) >= 2:
        (i1, a), (i2, b) = ph[-2], ph[-1]
        if abs(a - b) <= atr * 0.8 and i2 - i1 >= 5:
            neck = min(x["low"] for x in c[i1:i2 + 1])
            out.append({"name": "쌍봉", "bias": -1, "level": neck, "text": f"고점 {a:,.4g}·{b:,.4g} 두 번 저항 · 넥라인 {neck:,.4g} 이탈 시 확인"})
    if len(ph) >= 3:
        (_, l), (_, h), (_, r) = ph[-3:]
        if h > l + atr and h > r + atr and abs(l - r) <= atr * 1.2:
            out.append({"name": "헤드앤숄더", "bias": -1, "level": min(l, r), "text": f"머리 {h:,.4g} · 양 어깨 {l:,.4g}/{r:,.4g}"})
    if len(pl) >= 3:
        (_, l), (_, h), (_, r) = pl[-3:]
        if h < l - atr and h < r - atr and abs(l - r) <= atr * 1.2:
            out.append({"name": "역헤드앤숄더", "bias": 1, "level": max(l, r), "text": f"머리 {h:,.4g} · 양 어깨 {l:,.4g}/{r:,.4g}"})
    if len(ph) >= 2 and len(pl) >= 2 and ph[-1][1] < ph[-2][1] and pl[-1][1] > pl[-2][1]:
        out.append({"name": "삼각수렴", "bias": 0, "level": None, "text": f"고점 낮아짐({ph[-2][1]:,.4g}→{ph[-1][1]:,.4g}) · 저점 높아짐({pl[-2][1]:,.4g}→{pl[-1][1]:,.4g}) — 돌파 방향 대기"})
    return out


def analyze(c: list[dict], recent: int = 5, horizon: int = 5) -> dict:
    cl = [b["close"] for b in c]
    ema = ind.ema(cl, 20)
    found = []
    for i in range(max(25, len(c) - recent), len(c)):
        tr = (cl[i - 1] - ema[i - 1]) if ema[i - 1] else 0
        for k in detect_at(c, i, tr):
            found.append({"time": c[i]["time"], "key": k, "ko": KO[k], "bias": BIAS[k], "bars_ago": len(c) - 1 - i})
    st = candle_stats(c, horizon)
    lines = [f"최근 {recent}봉 캔들 패턴: " + (", ".join(f"{f['ko']}({f['bars_ago']}봉 전)" for f in found) or "없음")]
    for f in found:
        s = st.get(f["key"])
        if s:
            lines.append(f"- {f['ko']}: 이 코인 과거 {s['n']}번 · {horizon}봉 뒤 평균 {s['avg_ret']:+.2f}% · 패턴 방향대로 {s['hit_pct']}%"
                         + ("" if s["reliable"] else " (30번 미만 — 패턴이라 부르기 어려움)"))
    cp = chart_patterns(c)
    lines.append("차트 패턴: " + (" / ".join(f"{p['name']} — {p['text']}" for p in cp) or "뚜렷한 것 없음"))
    best = sorted((v for v in st.values() if v["reliable"]), key=lambda v: -abs(v["hit_pct"] - 50))[:4]
    if best:
        lines.append("이 코인에서 통계가 쌓인 패턴: " + ", ".join(f"{v['ko']} {v['hit_pct']}%({v['n']})" for v in best))
    return {"candles": found, "chart": cp, "stats": st, "text": "\n".join(lines)}
