"""AI 에이전트 팀 (TradingAgents 스타일 멀티 에이전트).

  [기술적 분석가] ─┐
  [파생상품 분석가] ─┼─▶ [리스크 매니저] ─▶ [헤드 트레이더] ─▶ 결정(JSON) ─▶ (선택) 페이퍼 주문
  [뉴스·매크로 분석가]┘

세 분석가는 병렬 실행. API 키가 없으면 같은 스키마의 규칙 기반 점수로 대체한다.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import config, indicators as ind, llm
from .data import market, news


class AnalystReport(BaseModel):
    stance: Literal["bullish", "bearish", "neutral"]
    confidence: int = Field(description="0~100")
    key_points: list[str]
    summary: str


class RiskReview(BaseModel):
    max_leverage: float
    position_pct: float = Field(description="권장 증거금 비중 % (자본 대비)")
    warnings: list[str]
    event_risk: bool = Field(description="24시간 내 고영향 이벤트(FOMC/CPI 등) 여부")
    summary: str


class TradeDecision(BaseModel):
    action: Literal["long", "short", "stay_flat"]
    confidence: int = Field(description="0~100")
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profits: list[float] = []
    leverage: float = 1
    position_pct: float = 0
    invalidation: str = ""
    rationale: str


AGENTS = {
    "technical": ("기술적 분석가",
                  "너는 코인 선물 기술적 분석가다. 멀티 타임프레임 추세(EMA 정배열/역배열), 모멘텀(RSI, MACD), "
                  "변동성(ATR, 볼린저), 추세강도(ADX), 주요 지지/저항만 근거로 방향성을 판단한다. "
                  "데이터에 없는 사실을 지어내지 말고, 근거 수치를 key_points 에 적어라. 한국어로 답한다."),
    "derivatives": ("파생상품 분석가",
                    "너는 선물 시장 포지셔닝 분석가다. 펀딩비, 미결제약정(OI) 변화, 롱숏 비율, 청산 데이터를 해석한다. "
                    "과열된 한쪽 포지셔닝은 역방향 스퀴즈 위험으로 본다 (예: 펀딩비 급등+OI 급증+가격 정체 = 롱 과밀). "
                    "가격 방향과 OI 방향의 조합(신규 유입/청산)을 반드시 언급한다. 한국어로 답한다."),
    "news": ("뉴스·매크로 분석가",
             "너는 크립토 뉴스와 거시 이벤트 분석가다. 헤드라인의 호재/악재, 규제/ETF/해킹 이슈, 도미넌스 흐름, "
             "이번 주 미국 고영향 경제지표(FOMC, CPI, 고용) 일정이 단기 변동성에 주는 영향을 평가한다. "
             "헤드라인에 없는 뉴스를 지어내지 마라. 한국어로 답한다."),
}

RISK_PROMPT = ("너는 선물 트레이딩 데스크의 리스크 매니저다. 분석가 보고서와 변동성(ATR%), 이벤트 일정을 보고 "
               "허용 레버리지와 증거금 비중 상한, 경고사항을 정한다. 보수적으로 판단하고 한국어로 답한다.")
TRADER_PROMPT = ("너는 헤드 트레이더다. 세 분석가 보고서와 리스크 매니저 한도를 종합해 최종 결정을 내린다. "
                 "근거가 엇갈리거나 확신이 낮으면 stay_flat. 진입 시 entry/stop_loss/take_profits 는 현재가와 ATR 을 "
                 "기준으로 현실적인 가격을 쓰고, 레버리지와 비중은 리스크 한도를 넘지 않는다. "
                 "rationale 에 어떤 보고서의 어떤 근거가 결정적이었는지 한국어로 적는다.")


# ---------------------------------------------------------------------------
# 시장 스냅샷
# ---------------------------------------------------------------------------

def _last(x):
    for v in reversed(x):
        if v is not None:
            return v
    return None


def _tf_summary(c: list[dict]) -> dict:
    close = [b["close"] for b in c]
    e20, e50, e200 = (_last(ind.ema(close, n)) for n in (20, 50, 200))
    m = ind.macd(close)
    bb = ind.bbands(close)
    a = _last(ind.atr(c))
    st = ind.supertrend(c)
    dmi = ind.adx(c)
    px = close[-1]
    lookback = c[-50:]
    return {
        "price": px,
        "ema20": e20, "ema50": e50, "ema200": e200,
        "rsi14": _last(ind.rsi(close)),
        "macd_hist": _last(m["hist"]), "macd_hist_prev": m["hist"][-2],
        "bb_upper": _last(bb["upper"]), "bb_lower": _last(bb["lower"]), "bb_width_pct": _last(bb["width"]),
        "atr14": a, "atr_pct": a / px * 100 if a else None,
        "supertrend_trend": _last(st["trend"]),
        "adx": _last(dmi["adx"]),
        "swing_high_50": max(b["high"] for b in lookback),
        "swing_low_50": min(b["low"] for b in lookback),
        "change_pct_20bars": (px / close[-21] - 1) * 100 if len(close) > 21 else None,
    }


def snapshot(symbol: str) -> dict:
    snap: dict = {"symbol": symbol, "time": int(time.time()), "timeframes": {}}
    for tf in ("15m", "1h", "4h", "1d"):
        c, src = market.candles(symbol, tf, 300)
        snap["timeframes"][tf] = _tf_summary(c)
        snap["data_source"] = src
    d = market.derivatives(symbol, "1h", 48)
    def chg(series, n):
        if len(series) > n and series[-n - 1]["value"]:
            return (series[-1]["value"] / series[-n - 1]["value"] - 1) * 100
        return None
    snap["derivatives"] = {
        "source": d.get("source"),
        "funding_latest_pct": d["funding"][-1]["value"] if d["funding"] else None,
        "funding_avg_last8_pct": (sum(p["value"] for p in d["funding"][-8:]) / len(d["funding"][-8:])
                                  if d["funding"] else None),
        "oi_latest_usd": d["open_interest"][-1]["value"] if d["open_interest"] else None,
        "oi_change_24h_pct": chg(d["open_interest"], 24),
        "long_short_ratio": d["long_short"][-1]["value"] if d["long_short"] else None,
        "liquidations_24h": ({"long_usd": sum(x["long_usd"] for x in d["liquidations"][-24:]),
                              "short_usd": sum(x["short_usd"] for x in d["liquidations"][-24:])}
                             if d["liquidations"] else None),
    }
    try:
        snap["dominance"] = market.global_dominance()
    except Exception:
        snap["dominance"] = None
    snap["headlines"] = [f"[{h['source']}] {h['title']}" for h in news.headlines(20)["items"]]
    snap["calendar"] = news.economic_calendar()["items"][:15]
    return snap


def _fmt(d) -> str:
    import json
    return json.dumps(d, ensure_ascii=False, default=str, indent=1)


def _agent_input(key: str, snap: dict) -> str:
    base = f"심볼: {snap['symbol']} (데이터: {snap.get('data_source')})\n"
    if key == "technical":
        return base + "타임프레임별 지표:\n" + _fmt(snap["timeframes"])
    if key == "derivatives":
        return base + f"현재가: {snap['timeframes']['1h']['price']}\n1h 가격변화(20봉): " \
               f"{snap['timeframes']['1h']['change_pct_20bars']}\n파생 데이터:\n" + _fmt(snap["derivatives"])
    return base + "헤드라인:\n" + "\n".join(snap["headlines"]) + "\n\n도미넌스:\n" + _fmt(snap["dominance"]) + \
        "\n\n이번 주 미국 고영향 지표:\n" + _fmt(snap["calendar"])


# ---------------------------------------------------------------------------
# 규칙 기반 대체 에이전트 (API 키 없을 때)
# ---------------------------------------------------------------------------

def _stance(score: float) -> tuple[str, int]:
    if score > 0.2:
        return "bullish", min(90, int(50 + score * 40))
    if score < -0.2:
        return "bearish", min(90, int(50 - score * 40))
    return "neutral", 40


def _rule_technical(snap) -> AnalystReport:
    pts, score = [], 0.0
    for tf, w in (("1h", 0.3), ("4h", 0.4), ("1d", 0.3)):
        s = snap["timeframes"][tf]
        if None in (s["ema20"], s["ema50"]):
            continue
        up = s["price"] > s["ema20"] > s["ema50"]
        dn = s["price"] < s["ema20"] < s["ema50"]
        score += w * (1 if up else -1 if dn else 0)
        pts.append(f"{tf}: EMA {'정배열' if up else '역배열' if dn else '혼조'}, RSI {s['rsi14']:.1f}, "
                   f"MACD hist {s['macd_hist']:+.2f}, 슈퍼트렌드 {'상승' if s['supertrend_trend'] == 1 else '하락'}")
        if s["rsi14"] and s["rsi14"] > 75:
            score -= 0.1 * w * 3
        if s["rsi14"] and s["rsi14"] < 25:
            score += 0.1 * w * 3
    st, conf = _stance(score)
    return AnalystReport(stance=st, confidence=conf, key_points=pts, summary=f"추세 점수 {score:+.2f}")


def _rule_derivatives(snap) -> AnalystReport:
    d, pts, score = snap["derivatives"], [], 0.0
    f = d.get("funding_latest_pct")
    if f is not None:
        pts.append(f"펀딩비 {f:.4f}%")
        score += -0.4 if f > 0.05 else 0.3 if f < 0 else 0
    oi = d.get("oi_change_24h_pct")
    px = snap["timeframes"]["1h"]["change_pct_20bars"] or 0
    if oi is not None:
        pts.append(f"OI 24h {oi:+.2f}%, 가격 20봉 {px:+.2f}%")
        if oi > 3 and px > 0:
            score += 0.3; pts.append("가격↑ OI↑: 신규 롱 유입")
        elif oi > 3 and px < 0:
            score -= 0.3; pts.append("가격↓ OI↑: 신규 숏 유입")
        elif oi < -3:
            pts.append("OI 감소: 포지션 정리 국면")
    ls = d.get("long_short_ratio")
    if ls is not None:
        pts.append(f"롱숏비율 {ls:.2f}")
        score += -0.2 if ls > 2.5 else 0.2 if ls < 0.8 else 0
    if not pts:
        pts.append("파생 데이터 없음 (네트워크 또는 API 키 확인)")
    st, conf = _stance(score)
    return AnalystReport(stance=st, confidence=conf, key_points=pts, summary=f"포지셔닝 점수 {score:+.2f}")


_POS = ("approve", "approval", "inflow", "surge", "rally", "record", "adopt", "bull", "etf", "buy", "high")
_NEG = ("hack", "exploit", "ban", "lawsuit", "sec sues", "outflow", "crash", "plunge", "bear", "liquidat", "sell-off")


def _rule_news(snap) -> AnalystReport:
    pos = sum(any(k in h.lower() for k in _POS) for h in snap["headlines"])
    neg = sum(any(k in h.lower() for k in _NEG) for h in snap["headlines"])
    score = (pos - neg) / max(1, len(snap["headlines"])) * 2
    pts = [f"헤드라인 {len(snap['headlines'])}건: 긍정 키워드 {pos}, 부정 키워드 {neg}"]
    if snap["calendar"]:
        pts.append("이번 주 고영향 지표: " + ", ".join(e["title"] for e in snap["calendar"][:5]))
    if snap.get("dominance"):
        pts.append(f"BTC 도미넌스 {snap['dominance']['btc_dominance']:.1f}%")
    st, conf = _stance(score)
    return AnalystReport(stance=st, confidence=min(conf, 60), key_points=pts, summary="키워드 감성 점수")


def _rule_risk(snap, reports) -> RiskReview:
    atr_pct = snap["timeframes"]["1h"]["atr_pct"] or 1
    max_lev = max(1.0, min(10.0, round(2.0 / atr_pct, 1)))
    warn = []
    if atr_pct > 1.5:
        warn.append(f"1h ATR {atr_pct:.2f}% 로 변동성 높음")
    event = bool(snap["calendar"])
    if event:
        warn.append("이번 주 고영향 지표 발표 예정 — 발표 전후 포지션 축소 권장")
    stances = {r.stance for r in reports.values()}
    if {"bullish", "bearish"} <= stances:
        warn.append("분석가 의견 충돌")
    return RiskReview(max_leverage=max_lev, position_pct=10 if event else 20, warnings=warn,
                      event_risk=event, summary=f"최대 레버리지 {max_lev}배 (ATR 기준)")


def _rule_trader(snap, reports, risk: RiskReview) -> TradeDecision:
    w = {"technical": 0.5, "derivatives": 0.3, "news": 0.2}
    sgn = {"bullish": 1, "bearish": -1, "neutral": 0}
    score = sum(w[k] * sgn[r.stance] * r.confidence / 100 for k, r in reports.items())
    tf = snap["timeframes"]["1h"]
    px, a = tf["price"], tf["atr14"] or tf["price"] * 0.01
    if abs(score) < 0.25:
        return TradeDecision(action="stay_flat", confidence=int(50 - abs(score) * 100),
                             rationale=f"종합 점수 {score:+.2f} — 방향성 불충분")
    side = 1 if score > 0 else -1
    return TradeDecision(
        action="long" if side == 1 else "short", confidence=int(min(90, 50 + abs(score) * 60)),
        entry=px, stop_loss=px - side * 1.5 * a, take_profits=[px + side * 2 * a, px + side * 3.5 * a],
        leverage=min(risk.max_leverage, 5), position_pct=risk.position_pct,
        invalidation=f"1h 종가가 {px - side * 1.5 * a:.2f} {'하회' if side == 1 else '상회'}",
        rationale=f"종합 점수 {score:+.2f} (기술 50% / 파생 30% / 뉴스 20%)")


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def run_team(symbol: str) -> dict:
    t0 = time.time()
    snap = snapshot(symbol)
    use_llm = config.llm_enabled()
    reports: dict[str, AnalystReport] = {}
    errors: dict[str, str] = {}

    def run_one(key):
        if use_llm:
            try:
                return llm.parse(AGENTS[key][1], _agent_input(key, snap), AnalystReport)
            except llm.LLMUnavailable as e:   # 무료 한도 초과 등 → 이 분석가만 기본 분석으로
                errors[key] = f"AI 실패 → 기본 분석으로 대체: {e}"
        return {"technical": _rule_technical, "derivatives": _rule_derivatives, "news": _rule_news}[key](snap)

    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {k: ex.submit(run_one, k) for k in AGENTS}
        for k, f in futs.items():
            try:
                reports[k] = f.result()
            except Exception as e:
                errors[k] = str(e)
                reports[k] = AnalystReport(stance="neutral", confidence=0, key_points=[f"오류: {e}"], summary="실패")

    board = "\n\n".join(f"## {AGENTS[k][0]}\n{r.model_dump_json()}" for k, r in reports.items())
    vol = {tf: snap["timeframes"][tf]["atr_pct"] for tf in snap["timeframes"]}
    risk = decision = None
    if use_llm:
        try:
            risk = llm.parse(RISK_PROMPT, f"{board}\n\nATR%: {_fmt(vol)}\n이벤트: {_fmt(snap['calendar'])}", RiskReview)
            decision = llm.parse(TRADER_PROMPT,
                                 f"심볼 {symbol}, 현재가 {snap['timeframes']['1h']['price']}, "
                                 f"1h ATR {snap['timeframes']['1h']['atr14']}\n\n{board}\n\n## 리스크 매니저\n"
                                 f"{risk.model_dump_json()}", TradeDecision, effort="high")
        except llm.LLMUnavailable as e:
            errors["trader"] = f"AI 실패 → 기본 리스크·결정 규칙으로 대체: {e}"
            risk = decision = None
    if risk is None or decision is None:
        risk = _rule_risk(snap, reports)
        decision = _rule_trader(snap, reports, risk)

    return {
        "symbol": symbol,
        "engine": (llm.provider() or "claude") if use_llm else "rules",
        "model": llm.model_name() if use_llm else None,
        "elapsed_sec": round(time.time() - t0, 1),
        "reports": {k: {"name": AGENTS[k][0], **r.model_dump()} for k, r in reports.items()},
        "risk": risk.model_dump(),
        "decision": decision.model_dump(),
        "snapshot": snap,
        "errors": errors,
    }
