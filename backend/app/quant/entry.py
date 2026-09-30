"""종합 진입 판단 — 시장 판단 · 다음 봉 예측 · 유사 패턴 · 풋프린트 · 호가창을 한 점수로.

각 근거를 −1(숏)~+1(롱)로 바꾸고 가중 평균한다. 다음 봉 예측은 최근 적중률이 찍기보다 나을 때만
제대로 반영하고, 유사 패턴은 신뢰도에 따라 줄인다. 점수가 ±25 를 넘으면 그 방향이 유리, 아니면 관망.
"""
from __future__ import annotations

from .. import analysis, orderflow
from ..data import market
from . import footprint, forecast

W = {"regime": 0.25, "next_bar": 0.2, "analog": 0.2, "footprint": 0.15, "orderbook": 0.2}


def entry(symbol: str, interval: str) -> dict:
    parts: list[dict] = []
    c, src = market.candles(symbol, interval, 400)
    reg = analysis.regime(c)
    parts.append({"key": "regime", "name": "시장 판단", "value": max(-1, min(1, reg["score"] / 60)),
                  "text": f"{reg['label']} (점수 {reg['score']:+d}, 신뢰도 {reg['confidence']})"})
    try:
        fc = forecast.forecast(symbol, interval)
    except ValueError:
        fc = {}
    nb, an = fc.get("next_bar"), fc.get("analog")
    if nb:
        edge = (nb["backtest"]["accuracy_pct"] or 0) - nb["backtest"]["baseline_pct"]
        trust = 1.0 if edge >= 5 else 0.6 if edge >= 1.5 else 0.2
        parts.append({"key": "next_bar", "name": "다음 봉 예측", "value": (nb["p_up"] - 50) / 50 * trust,
                      "text": f"상승 {nb['p_up']}% · 최근 적중률 {nb['backtest']['accuracy_pct']}% (찍기 {nb['backtest']['baseline_pct']}%)"
                              + ("" if trust == 1 else " — 적중률이 낮아 약하게 반영")})
    if an:
        trust = {"높음": 1.0, "보통": 0.6, "낮음": 0.3}[an["reliability"]]
        parts.append({"key": "analog", "name": "과거 유사 패턴", "value": (an["prob_up"] - 50) / 50 * trust,
                      "text": f"{an['horizon']}봉 뒤 상승 {an['prob_up']}% · 중간값 {an['median_ret_pct']:+.2f}% · 신뢰도 {an['reliability']}"})
    fp_notes: list[str] = []
    try:
        fp = footprint.footprint(symbol, interval, 40)
        sm = fp["summary"]
        fp_notes = sm["notes"]
        parts.append({"key": "footprint", "name": "풋프린트 (체결)", "value": max(-1, min(1, sm.get("score", 0) / 2)),
                      "text": " · ".join(sm["notes"][:2]) or "특이 사항 없음"})
    except ValueError:
        fp = None
    ob = None
    try:
        ob = orderflow.orderbook(symbol)
        near = ob["depth"][1]["imbalance"]
        parts.append({"key": "orderbook", "name": "호가창", "value": max(-1, min(1, near * 2)),
                      "text": f"±0.5% 안 매수 {ob['depth'][1]['bid_usd'] / 1e6:.2f}M vs 매도 {ob['depth'][1]['ask_usd'] / 1e6:.2f}M (불균형 {near * 100:+.0f}%)"})
    except Exception:
        pass
    tw = sum(W[p["key"]] for p in parts) or 1
    score = round(sum(W[p["key"]] * p["value"] for p in parts) / tw * 100)
    for p in parts:
        p["contrib"] = round(W[p["key"]] * p["value"] / tw * 100)
        p["value"] = round(p["value"], 3)
    verdict = "long" if score >= 25 else "short" if score <= -25 else "wait"
    agree = sum(1 for p in parts if (p["value"] > 0.1 and score > 0) or (p["value"] < -0.1 and score < 0))
    plan = (ob or {}).get("plan", {}).get("plans", {}).get(verdict) if verdict != "wait" else None
    if plan:
        plan = {**plan, "source": "호가 벽"}
    elif verdict != "wait":   # 가까운 벽이 없으면 자동 시나리오 중 같은 방향 것
        sc = next((s for s in analysis.scenarios(c, reg)["scenarios"] if s["bias"] == verdict), None)
        if sc:
            plan = {"entry": sc["entry"], "stop": sc["stop"], "take": sc["targets"][0], "rr": sc["rr"], "why": sc["trigger"], "source": "시나리오"}
    return {"symbol": symbol, "interval": interval, "data_source": src, "score": score, "verdict": verdict,
            "label": {"long": "롱 유리", "short": "숏 유리", "wait": "관망"}[verdict],
            "agree": agree, "total": len(parts), "parts": parts, "plan": plan, "footprint_notes": fp_notes,
            "evidence": (nb or {}).get("evidence", []),
            "note": "여러 근거가 같은 방향을 가리킬수록 믿을 만합니다. 점수만 보고 진입하지 말고 손절 위치를 먼저 정하세요."}
