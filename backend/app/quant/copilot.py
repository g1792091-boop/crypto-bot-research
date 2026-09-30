"""실시간 AI 상황 분석 (코파일럿) — 지금 시장 상황과 내 포지션을 계속 지켜보며 분석한다.

- 상황 수집: 가격·ATR · 시장 판단(여러 봉) · 지지저항 · 시나리오 · 종합 진입 판단(다음 봉·유사 패턴·풋프린트·호가) ·
  풋프린트 지지저항 판정 · 호가 벽 · 펀딩/OI/롱숏 · 고수 포지션 · 스캐너 신호 · 경제지표 · **내 포지션과 봇 포지션**
- 즉시 경고(규칙, 매번 계산): 손절·청산가 근접, 손절 미설정, 시장 판단과 반대 포지션, 반대 신호, 이익 보호 등
- AI 분석(Claude/Gemini, 키가 없으면 같은 형식의 규칙 분석): 새 봉이 나오거나, 가격이 ATR 절반 이상 움직이거나,
  포지션이 바뀌거나, 경고가 새로 생기거나, 일정 시간이 지나면 다시 분석한다. 그 사이에는 저장된 분석을 돌려준다.
- 포지션 감시(백그라운드): 열린 포지션마다 30초마다 경고를 계산해 새 경고를 알림 목록에 쌓는다(화면이 읽어 알림).
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .. import analysis, config, llm, orderflow
from ..data import market
from . import entry as entry_mod
from . import footprint, toptraders


# ---------------------------------------------------------------- 출력 형식 (AI 와 규칙 분석이 같은 모양)
class PositionAdvice(BaseModel):
    target: str = Field(description="어떤 포지션인지: '내 포지션 BTCUSDT' 또는 '봇 <이름>'")
    symbol: str
    action: Literal["hold", "add", "reduce", "close", "move_stop", "take_profit"]
    urgency: Literal["low", "medium", "high"]
    new_stop: Optional[float] = Field(default=None, description="손절을 옮길 가격 (move_stop 일 때)")
    new_take: Optional[float] = Field(default=None, description="익절가 (바꿀 때)")
    fraction: Optional[float] = Field(default=None, description="reduce/take_profit 일 때 줄일 비율 0~1")
    reason: str


class EntryIdea(BaseModel):
    action: Literal["long", "short", "wait"]
    entry: Optional[float] = None
    stop: Optional[float] = None
    take: Optional[float] = None
    trigger: str = Field(description="어떤 조건이 되면 진입하는지")
    reason: str


class KeyLevel(BaseModel):
    price: float
    label: str


class LiveAnalysis(BaseModel):
    headline: str = Field(description="지금 상황 한 줄 요약")
    situation: str = Field(description="시장 상황 2~4문장")
    bias: Literal["long", "short", "neutral"]
    confidence: int = Field(description="0~100")
    changes: str = Field(description="직전 분석 이후 달라진 점 (처음이면 빈 문자열)")
    position_advice: list[PositionAdvice]
    entry_idea: Optional[EntryIdea] = None
    key_levels: list[KeyLevel]
    risks: list[str]
    watch: list[str] = Field(description="다음 봉 마감 전까지 지켜볼 것")


SYSTEM = (
    "너는 코인 무기한 선물 트레이딩 데스크의 실시간 코파일럿이다. 주어진 JSON(시장 데이터·지표·호가·체결·포지션)만 근거로 "
    "지금 상황을 분석한다. 데이터에 없는 뉴스나 수치를 지어내지 마라.\n"
    "규칙:\n"
    "1) 포지션이 있으면 포지션 관리가 최우선이다. 포지션마다 position_advice 를 하나씩 쓴다(유지·추가·일부 청산·전량 청산·손절 이동·익절).\n"
    "   - 손절이 없으면 반드시 move_stop 과 구체적인 new_stop 을 제시한다.\n"
    "   - 강제청산가가 가까우면(1.5 ATR 이내) urgency=high.\n"
    "   - 롱의 new_stop 은 현재가보다 낮고 강제청산가보다 높아야 한다(숏은 반대). 지지·저항과 ATR 을 기준으로 현실적인 가격을 쓴다.\n"
    "   - 봇 포지션은 봇이 자동으로 관리하므로 참고 의견으로 쓴다.\n"
    "2) 이 코인에 내 포지션이 없으면 entry_idea 를 쓴다. 근거가 엇갈리면 action=wait 과 어떤 조건에서 들어갈지(trigger).\n"
    "3) 근거들이 엇갈리거나 다음 봉 예측 적중률이 찍기 수준이면 확신(confidence)을 낮춘다.\n"
    "4) previous 가 있으면 changes 에 무엇이 바뀌었는지(가격·판단·신호) 한두 문장으로 쓴다.\n"
    "5) alerts 에 있는 경고는 risks 나 position_advice 에 반영한다.\n"
    "6) 한국어로, 짧고 구체적으로(가격 숫자 포함). 초보도 이해할 수 있게 쓴다."
)
ASK_SYSTEM = (
    "너는 코인 선물 트레이딩 코파일럿이다. 사용자의 질문에 아래 실시간 데이터(JSON)와 최근 분석만 근거로 한국어로 답한다. "
    "포지션 질문이면 손절·청산가·ATR·지지저항 수치를 들어 구체적으로 답하고, 모르는 것은 모른다고 한다. "
    "5~8문장 이내. 확정적인 수익 약속은 하지 않는다."
)

_state: dict[tuple[str, str], dict] = {}
_locks: dict[tuple[str, str], threading.Lock] = {}
_paper = None                      # main 에서 bind() 로 PaperManager 를 넘겨준다
alerts_feed: deque[dict] = deque(maxlen=300)
_alert_seen: dict[str, float] = {}
SETTINGS = {"watch": True, "auto_ai": False, "interval": "15m", "every_sec": 30}


def bind(paper_manager) -> None:
    global _paper
    _paper = paper_manager
    try:
        SETTINGS.update(json.loads((config.STATE_DIR / "copilot.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def set_settings(**kw) -> dict:
    for k in ("watch", "auto_ai"):
        if kw.get(k) is not None:
            SETTINGS[k] = bool(kw[k])
    if kw.get("interval"):
        SETTINGS["interval"] = kw["interval"]
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        (config.STATE_DIR / "copilot.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
    except OSError:
        pass
    return dict(SETTINGS)


def _r(x, n=6):
    return None if x is None else float(f"{x:.{n}g}")


# ---------------------------------------------------------------- 포지션
def positions(symbol: str | None = None, price: dict[str, float] | None = None, atr: dict[str, float] | None = None) -> list[dict]:
    """내 모의 포지션 + 봇 포지션 (symbol 을 주면 그 코인만)."""
    out = []
    if _paper is None:
        return out
    price, atr = price or {}, atr or {}
    acct = _paper.manual
    eq = acct.snapshot()["equity"] if acct.positions else None
    items = [("manual", "내 포지션", sym, p, None) for sym, p in acct.positions.items()]
    for b in _paper.bots.values():
        p = b.sim.position
        if p:
            items.append(("bot", f"봇 {b.spec.name}", b.spec.symbol, p, b))
    for kind, name, sym, p, bot in items:
        if symbol and sym != symbol:
            continue
        px = price.get(sym)
        if px is None:
            try:
                px = market.candles(sym, "1m", 2)[0][-1]["close"]
            except Exception:
                px = bot.last_price if bot else p.entry_price
            price[sym] = px
        a = atr.get(sym)
        u = p.unrealized(px)
        side = "long" if p.side == 1 else "short"
        d = lambda lvl: None if not lvl else (px - lvl) / px * 100 * p.side   # 양수 = 아직 여유
        row = {"kind": kind, "target": f"{name} {sym}" if kind == "manual" else name, "bot_id": bot.id if bot else None,
               "symbol": sym, "side": side, "leverage": p.leverage, "entry": _r(p.entry_price), "mark": _r(px),
               "qty": p.qty, "margin": round(p.margin, 2), "upnl": round(u, 2), "roe_pct": round(u / p.margin * 100, 2) if p.margin else None,
               "move_pct": round((px / p.entry_price - 1) * 100 * p.side, 3),
               "stop": _r(p.stop), "take": _r(p.take), "liq": _r(p.liq_price),
               "to_stop_pct": _r(d(p.stop), 3), "to_take_pct": _r(-d(p.take) if p.take else None, 3), "to_liq_pct": _r(d(p.liq_price), 3),
               "held_min": round((time.time() - p.entry_time) / 60), "equity_pct": round(p.margin / eq * 100, 1) if eq and kind == "manual" else None}
        if a:
            row["atr"] = _r(a)
            row["to_stop_atr"] = round(abs(px - p.stop) / a * (1 if (d(p.stop) or 0) > 0 else -1), 2) if p.stop else None
            row["to_liq_atr"] = round(abs(px - p.liq_price) / a, 2) if p.liq_price else None
            row["profit_atr"] = round((px - p.entry_price) * p.side / a, 2)
        out.append(row)
    return out


# ---------------------------------------------------------------- 즉시 경고 (규칙)
def alerts_for(pos: list[dict], reg: dict | None = None, verdict: dict | None = None, deriv: dict | None = None,
               sigs: list[dict] | None = None) -> list[dict]:
    out = []

    def add(level, key, text, sym=None):
        out.append({"level": level, "key": key, "symbol": sym, "text": text})

    for p in pos:
        tag, sym = f"{'내 ' if p['kind'] == 'manual' else p['target'] + ' '}{p['symbol'].replace('USDT', '')} {'롱' if p['side'] == 'long' else '숏'}", p["symbol"]
        if p.get("to_liq_atr") is not None and (p["to_liq_atr"] < 1.5 or (p["to_liq_pct"] or 99) < 2):
            add("high", f"liq:{p['target']}", f"{tag}: 강제청산가 {p['liq']:,}까지 {p['to_liq_pct']:.2f}% ({p['to_liq_atr']} ATR) — 매우 가까움", sym)
        if p["stop"] and p.get("to_stop_atr") is not None and 0 <= p["to_stop_atr"] < 0.5:
            add("high", f"stop:{p['target']}", f"{tag}: 손절가 {p['stop']:,}까지 {p['to_stop_pct']:.2f}% — 곧 닿을 수 있음", sym)
        if not p["stop"] and p["kind"] == "manual":
            add("medium", f"nostop:{p['target']}", f"{tag}: 손절이 없습니다 — 강제청산 전에 손실을 끊을 가격을 정하세요", sym)
        if p["take"] and p.get("to_take_pct") is not None and 0 <= p["to_take_pct"] < 0.3:
            add("info", f"take:{p['target']}", f"{tag}: 익절가 {p['take']:,} 근처 ({p['to_take_pct']:.2f}% 남음)", sym)
        if p.get("profit_atr") is not None and p["profit_atr"] >= 1.5 and (not p["stop"] or (p["stop"] - p["entry"]) * (1 if p["side"] == "long" else -1) < 0):
            add("medium", f"protect:{p['target']}", f"{tag}: 이익이 {p['profit_atr']} ATR — 손절을 본전({p['entry']:,}) 위로 올려 이익 보호를 고려", sym)
        if p["leverage"] >= 20:
            add("info", f"lev:{p['target']}", f"{tag}: 레버리지 {p['leverage']:g}배 — 작은 흔들림에도 청산 위험", sym)
        if reg and reg.get("symbol") == sym:
            if (p["side"] == "long" and reg["score"] <= -40) or (p["side"] == "short" and reg["score"] >= 40):
                add("medium", f"regime:{p['target']}:{reg['state']}", f"{tag}: 시장 판단이 반대 방향 ({reg['label']}, 점수 {reg['score']:+d})", sym)
        if verdict and verdict.get("symbol") == sym and verdict["verdict"] in ("long", "short") and verdict["verdict"] != p["side"]:
            add("medium", f"verdict:{p['target']}:{verdict['verdict']}", f"{tag}: 종합 진입 판단은 {verdict['label']} (점수 {verdict['score']:+d})", sym)
        for s in sigs or []:
            if s["symbol"] == sym and s.get("dir") in ("long", "short") and s["dir"] != p["side"] and (s.get("strength") or 1) >= 2:
                add("medium", f"sig:{s['id']}", f"{tag}: 반대 방향 신호 — {s['interval']} {s['label']} ({s['text'][:60]})", sym)
    if deriv and deriv.get("funding_pct") is not None and abs(deriv["funding_pct"]) >= 0.05:
        crowd = "롱" if deriv["funding_pct"] > 0 else "숏"
        add("info", "funding", f"펀딩비 {deriv['funding_pct']:+.3f}% — {crowd} 쏠림(과열). 반대쪽 급변(스퀴즈) 주의", deriv.get("symbol"))
    order = {"high": 0, "medium": 1, "info": 2}
    return sorted(out, key=lambda a: order[a["level"]])


# ---------------------------------------------------------------- 상황 수집
def _deriv(symbol: str) -> dict:
    try:
        d = market.derivatives(symbol, "1h", 48)
    except Exception:
        return {}
    oi = d.get("open_interest") or []
    return {"symbol": symbol, "source": d.get("source"),
            "funding_pct": d["funding"][-1]["value"] if d.get("funding") else None,
            "oi_change_24h_pct": round((oi[-1]["value"] / oi[-25]["value"] - 1) * 100, 2) if len(oi) > 25 and oi[-25]["value"] else None,
            "long_short_ratio": d["long_short"][-1]["value"] if d.get("long_short") else None}


def _events() -> list[dict]:
    if config.DATA_SOURCE == "synthetic":
        return []
    try:
        from ..data import news
        now = time.time()
        out = []
        for e in news.economic_calendar()["items"]:
            try:
                t = datetime.fromisoformat(e["date"]).timestamp()
            except (TypeError, ValueError):
                continue
            if -3600 <= t - now <= 86400:
                out.append({"title": e["title"], "in_hours": round((t - now) / 3600, 1), "forecast": e.get("forecast"), "previous": e.get("previous")})
        return out[:6]
    except Exception:
        return []


def light(symbol: str, interval: str) -> dict:
    """매번 계산하는 가벼운 상황 (가격 · ATR · 시장 판단 · 포지션 · 경고)."""
    c, src = market.candles(symbol, interval, 400)
    reg = analysis.regime(c)
    a = reg["atr"]
    last = c[-1]
    iv_sec = c[-1]["time"] - c[-2]["time"] if len(c) > 1 else 3600
    try:                                                   # 모의 계좌와 같은 가격(1분봉 현재가)으로 포지션·경고를 계산
        mark = market.candles(symbol, "1m", 2)[0][-1]["close"]
    except Exception:
        mark = last["close"]
    pos = positions(None, {symbol: mark}, {symbol: a})
    try:
        from .scanner import scanner
        sigs = [s for s in scanner.recent(int(time.time()) - 6 * 3600, 60) if s["symbol"] == symbol]
    except Exception:
        sigs = []
    return {"symbol": symbol, "interval": interval, "source": src, "price": mark, "bar_time": last["time"],
            "bar_left_sec": max(0, int(last["time"] + iv_sec - time.time())), "atr": a, "atr_pct": a / last["close"] * 100,
            "regime": {**{k: reg[k] for k in ("state", "label", "score", "confidence", "rsi", "adx", "reasons")}, "symbol": symbol},
            "positions": pos, "signals": sigs, "candles": c}


def full(lt: dict) -> dict:
    """AI 에 넘길 전체 상황 (새로 분석할 때만)."""
    symbol, interval, c, a = lt["symbol"], lt["interval"], lt["candles"], lt["atr"]
    ctx: dict = {"symbol": symbol, "interval": interval, "data_source": lt["source"], "now_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
                 "price": _r(lt["price"]), "atr": _r(a), "atr_pct": round(lt["atr_pct"], 3), "bar_left_sec": lt["bar_left_sec"],
                 "last_bars": [{"o": _r(b["open"]), "h": _r(b["high"]), "l": _r(b["low"]), "c": _r(b["close"]), "v": _r(b["volume"], 4)} for b in c[-6:]],
                 "change_pct": {"1bar": round((c[-1]["close"] / c[-2]["close"] - 1) * 100, 2), "20bars": round((c[-1]["close"] / c[-21]["close"] - 1) * 100, 2)},
                 "regime": {k: v for k, v in lt["regime"].items() if k != "symbol"}}
    try:
        an = analysis.analyze(symbol, interval)
        ctx["multi_timeframe"] = [{k: m[k] for k in ("interval", "label", "score")} for m in an["mtf"]]
        ctx["resistance"] = [{"price": _r(x["price"]), "kind": x["kind"]} for x in an["resistance"][:4]]
        ctx["support"] = [{"price": _r(x["price"]), "kind": x["kind"]} for x in an["support"][:4]]
        ctx["scenarios"] = [{k: s.get(k) for k in ("title", "bias", "trigger", "entry", "stop", "targets", "rr", "probability", "invalidation")} for s in an["scenarios"][:3]]
    except Exception:
        pass
    try:
        e = entry_mod.entry(symbol, interval)
        ctx["entry_verdict"] = {"label": e["label"], "score": e["score"], "agree": f"{e['agree']}/{e['total']}",
                                "parts": [f"{p['name']}: {p['text']} (기여 {p['contrib']:+d})" for p in e["parts"]], "plan": e["plan"]}
        ctx["_verdict"] = {"symbol": symbol, "verdict": e["verdict"], "label": e["label"], "score": e["score"]}
    except Exception:
        pass
    try:
        fp = footprint.analyze(symbol, interval, 60)["analysis"]
        ctx["footprint"] = {"next_bar": fp["next"].get("last_closed"),
                            "level_tests": [{"price": _r(x["price"]), "source": x["source"], "role": x["role"], "status": x["status"], "text": x["text"]} for x in fp["levels"][:5]],
                            "recent_signals": [{"dir": s["dir"], "reasons": s["reasons"], "entry": _r(s["entry"]), "stop": _r(s["stop"]), "outcome": s["outcome"]} for s in fp["signals"][-3:]]}
    except Exception:
        pass
    try:
        ob = orderflow.orderbook(symbol)
        ctx["orderbook"] = {"imbalance_0.5pct": round(ob["depth"][1]["imbalance"], 3), "imbalance_1pct": round(ob["depth"][2]["imbalance"], 3),
                            "walls": [{"price": _r(w["price"]), "side": "매수벽" if w["side"] == "bid" else "매도벽", "usd_m": round(w["usd"] / 1e6, 2)}
                                      for w in ob["walls"] if abs(w["price"] / lt["price"] - 1) < 0.03][:6],
                            "note": ob["plan"]["note"]}
    except Exception:
        pass
    ctx["derivatives"] = _deriv(symbol)
    tt = toptraders.last_result
    if tt and time.time() - tt["time"] < 3600:
        row = next((x for x in tt["by_coin"] if x["symbol"] == symbol), None)
        if row:
            ctx["top_traders_hyperliquid"] = {"long_traders": row["long"]["traders"], "short_traders": row["short"]["traders"],
                                              "long_share_pct": row["long_share"], "avg_lev_long": row["long"]["avg_leverage"],
                                              "avg_lev_short": row["short"]["avg_leverage"], "avg_entry_long": _r(row["long"]["avg_entry"]),
                                              "avg_entry_short": _r(row["short"]["avg_entry"])}
    try:
        br = toptraders.binance_ratios(symbol, "1h")
        ctx["binance_top_trader_long_pct"] = {"by_position": round(br["position"][-1]["long"] * 100, 1), "by_account": round(br["account"][-1]["long"] * 100, 1)}
    except Exception:
        pass
    ctx["scanner_signals_6h"] = [{"interval": s["interval"], "dir": s["dir"], "label": s["label"], "text": s["text"][:100],
                                  "minutes_ago": round((time.time() - s["created"]) / 60)} for s in lt["signals"][:8]]
    ctx["events_24h"] = _events()
    ctx["positions"] = lt["positions"]
    if _paper is not None:
        snap = _paper.manual.snapshot()
        ctx["account"] = {"equity": round(snap["equity"], 2), "free_margin": round(snap["free_margin"], 2)}
    return ctx


# ---------------------------------------------------------------- 규칙 분석 (AI 키가 없을 때 · AI 실패 시)
def _near(levels: list[dict], price: float, below: bool) -> float | None:
    xs = [x["price"] for x in levels or [] if (x["price"] < price if below else x["price"] > price)]
    return (max(xs) if below else min(xs)) if xs else None


def rules(ctx: dict, alerts: list[dict], prev: dict | None) -> LiveAnalysis:
    price, a, sym = ctx["price"], ctx["atr"], ctx["symbol"]
    reg, ev = ctx["regime"], ctx.get("entry_verdict")
    score = ev["score"] if ev else reg["score"]
    bias = "long" if score >= 25 else "short" if score <= -25 else "neutral"
    conf = min(85, 30 + abs(score) // 2)
    sup, res = _near(ctx.get("support"), price, True), _near(ctx.get("resistance"), price, False)
    advice = []
    for p in ctx["positions"]:
        long_ = p["side"] == "long"
        sgn = 1 if long_ else -1
        base = f"{'롱' if long_ else '숏'} {p['leverage']:g}배 · 수익 {p['roe_pct']:+.1f}%"
        if p.get("to_liq_atr") is not None and p["to_liq_atr"] < 1.5:
            advice.append(PositionAdvice(target=p["target"], symbol=p["symbol"], action="reduce", urgency="high", fraction=0.5,
                                         reason=f"{base}. 강제청산가까지 {p['to_liq_atr']} ATR — 비중을 줄여 청산 위험을 낮추세요"))
            continue
        if not p["stop"]:
            lvl = sup if long_ else res
            st = (lvl - 0.2 * a) if lvl and abs(price - lvl) < 3 * a else price - sgn * 1.5 * a
            if (st - p["mark"]) * sgn >= -0.2 * a:           # 현재가에 너무 붙거나 반대편이면 ATR 1.5배 거리로
                st = p["mark"] - sgn * 1.5 * a
            if (long_ and st <= p["liq"]) or (not long_ and st >= p["liq"]):
                st = p["liq"] + sgn * 0.3 * abs(price - p["liq"])
            advice.append(PositionAdvice(target=p["target"], symbol=p["symbol"], action="move_stop", urgency="medium", new_stop=_r(st),
                                         reason=f"{base}. 손절이 없어 {'가까운 지지' if long_ else '가까운 저항'}·ATR 기준 {_r(st):,}에 손절을 두는 것을 권장"
                                                + (f" (종합 판단도 반대 {score:+d} — 비중 축소도 고려)" if (long_ and score <= -40) or (not long_ and score >= 40) else "")))
            continue
        against = (long_ and score <= -40) or (not long_ and score >= 40)
        if against:
            advice.append(PositionAdvice(target=p["target"], symbol=p["symbol"], action="reduce", urgency="medium", fraction=0.5,
                                         reason=f"{base}. 종합 판단이 반대({ev['label'] if ev else reg['label']}, {score:+d}) — 절반 줄이거나 손절을 좁히세요"))
        elif (p.get("profit_atr") or 0) >= 1.5 and (p["stop"] - p["entry"]) * sgn < 0:
            advice.append(PositionAdvice(target=p["target"], symbol=p["symbol"], action="move_stop", urgency="medium", new_stop=p["entry"],
                                         reason=f"{base}. 이익이 {p['profit_atr']} ATR — 손절을 본전으로 올려 손실 없는 포지션으로"))
        elif p["take"] and (p.get("to_take_pct") or 99) < 0.3:
            advice.append(PositionAdvice(target=p["target"], symbol=p["symbol"], action="take_profit", urgency="low", fraction=0.5,
                                         reason=f"{base}. 익절가 근처 — 절반 익절 후 나머지는 추적"))
        else:
            advice.append(PositionAdvice(target=p["target"], symbol=p["symbol"], action="hold", urgency="low",
                                         reason=f"{base}. 손절 {p['stop']:,}까지 {p['to_stop_pct']:.2f}% 여유, 판단 {ev['label'] if ev else reg['label']} — 계획대로 유지"))
    idea = None
    if not any(p["symbol"] == sym and p["kind"] == "manual" for p in ctx["positions"]):
        plan = (ev or {}).get("plan")
        if bias != "neutral" and plan:
            idea = EntryIdea(action=bias, entry=_r(plan["entry"]), stop=_r(plan["stop"]), take=_r(plan["take"]),
                             trigger=plan.get("why") or "", reason=f"종합 판단 {ev['label']} ({score:+d}, {ev['agree']} 근거 일치) · 계획 출처 {plan.get('source')}")
        else:
            trig = f"{_r(res):,} 위 마감 시 롱 / {_r(sup):,} 아래 마감 시 숏" if sup and res else "방향이 정해질 때까지 대기"
            idea = EntryIdea(action="wait", trigger=trig, reason=f"근거가 엇갈림 (점수 {score:+d}) — 무리한 진입보다 돌파·이탈 확인")
    levels = []
    for x in (ctx.get("resistance") or [])[:2]:
        levels.append(KeyLevel(price=x["price"], label=f"저항 · {x['kind']}"))
    for x in (ctx.get("support") or [])[:2]:
        levels.append(KeyLevel(price=x["price"], label=f"지지 · {x['kind']}"))
    for w in (ctx.get("orderbook") or {}).get("walls", [])[:2]:
        levels.append(KeyLevel(price=w["price"], label=f"{w['side']} ${w['usd_m']}M"))
    risks = [x["text"] for x in alerts if x["level"] in ("high", "medium")][:5]
    d = ctx.get("derivatives") or {}
    if d.get("funding_pct") is not None and abs(d["funding_pct"]) >= 0.03:
        risks.append(f"펀딩비 {d['funding_pct']:+.3f}% — {'롱' if d['funding_pct'] > 0 else '숏'} 쏠림")
    for e in ctx.get("events_24h", [])[:2]:
        risks.append(f"{e['in_hours']}시간 뒤 {e['title']} 발표 — 변동성 확대")
    if not risks:
        risks.append(f"ATR {ctx['atr_pct']:.2f}% — 손절은 최소 ATR 1배 이상 거리 권장")
    fp = (ctx.get("footprint") or {}).get("next_bar") or {}
    nb = f" · 체결 기준 다음 봉 상승 {fp['p_up']}%" if fp.get("p_up") is not None else ""
    watch = [f"{_r(res):,} 저항 돌파 여부" if res else "", f"{_r(sup):,} 지지 이탈 여부" if sup else "",
             f"봉 마감까지 {ctx['bar_left_sec'] // 60}분 {ctx['bar_left_sec'] % 60}초 — 마감 모양(꼬리·거래량) 확인"]
    mtf = " · ".join(f"{m['interval']} {m['label']}" for m in ctx.get("multi_timeframe", []))
    changes = ""
    if prev:
        pp = prev.get("price")
        changes = f"직전 분석({prev.get('bias_label', '')}) 이후 가격 {((price / pp - 1) * 100 if pp else 0):+.2f}%"
    return LiveAnalysis(
        headline=f"{sym.replace('USDT', '')} {ctx['interval']} — {ev['label'] if ev else reg['label']} (점수 {score:+d}){nb}",
        situation=" ".join([f"시장 판단 {reg['label']}(점수 {reg['score']:+d}, 신뢰도 {reg['confidence']}).", *[r + "." for r in reg["reasons"][:2]],
                            f"여러 봉: {mtf}." if mtf else "", f"종합 진입 판단 {ev['label']} ({ev['agree']} 근거 일치)." if ev else ""]).strip(),
        bias=bias, confidence=conf, changes=changes, position_advice=advice, entry_idea=idea, key_levels=levels,
        risks=risks, watch=[w for w in watch if w])


# ---------------------------------------------------------------- AI 결과 검증
def _sanitize(res: LiveAnalysis, ctx: dict) -> LiveAnalysis:
    """AI 가 낸 가격이 말이 안 되면(롱 손절이 현재가 위 · 청산가 아래 등) 숫자를 지우고 표시."""
    pos = {p["target"]: p for p in ctx["positions"]}
    for adv in res.position_advice:
        p = pos.get(adv.target) or next((x for x in ctx["positions"] if x["symbol"] == adv.symbol), None)
        if not p:
            continue
        adv.target, adv.symbol = p["target"], p["symbol"]
        long_, px = p["side"] == "long", p["mark"]
        if adv.new_stop is not None and ((long_ and not (p["liq"] < adv.new_stop < px)) or (not long_ and not (px < adv.new_stop < p["liq"]))):
            adv.reason += f" (제안 손절 {adv.new_stop:,}은 현재가·청산가 기준으로 맞지 않아 제외)"
            adv.new_stop = None
        if adv.new_take is not None and ((long_ and adv.new_take <= px) or (not long_ and adv.new_take >= px)):
            adv.new_take = None
        if adv.fraction is not None:
            adv.fraction = max(0.1, min(1.0, adv.fraction))
    e = res.entry_idea
    if e and e.action in ("long", "short") and e.entry and e.stop and ((e.action == "long" and e.stop >= e.entry) or (e.action == "short" and e.stop <= e.entry)):
        e.stop = None
    res.confidence = max(0, min(100, res.confidence))
    return res


# ---------------------------------------------------------------- 분석 (저장 · 다시 분석 조건)
def _pos_sig(pos: list[dict], symbol: str) -> str:
    return "|".join(f"{p['target']}:{p['side']}:{p['entry']}:{p['stop']}:{p['take']}:{p['qty']:.6g}" for p in pos if p["symbol"] == symbol)


def _why_refresh(st: dict | None, lt: dict, alerts: list[dict], force: bool, max_age: int) -> str | None:
    if force:
        return "직접 요청"
    if not st:
        return "처음 분석"
    if st["bar_time"] != lt["bar_time"]:
        return "새 봉 시작"
    if _pos_sig(lt["positions"], lt["symbol"]) != st["pos_sig"]:
        return "포지션 변경"
    if abs(lt["price"] - st["price"]) >= 0.5 * lt["atr"]:
        return f"가격 급변 ({(lt['price'] / st['price'] - 1) * 100:+.2f}%)"
    hi = {a["key"] for a in alerts if a["level"] == "high"} - st["alert_keys"]
    if hi:
        return "새 위험 경고"
    if time.time() - st["time"] >= max_age:
        return f"{max_age // 60}분 경과"
    return None


def live(symbol: str, interval: str, force: bool = False, max_age: int = 300, use_ai: bool = True) -> dict:
    lt = light(symbol, interval)
    alerts = alerts_for(lt["positions"], lt["regime"], None, None, lt["signals"])
    key = (symbol, interval)
    st = _state.get(key)
    why = _why_refresh(st, lt, alerts, force, max(60, max_age))
    updating = False
    if why:
        lock = _locks.setdefault(key, threading.Lock())
        if lock.acquire(blocking=st is None or force):
            try:
                st = _run(key, lt, alerts, st, why, use_ai)
            finally:
                lock.release()
        else:
            updating = True                                    # 다른 요청이 이미 분석 중 → 저장본을 먼저 돌려준다
    ctx_alerts = alerts_for(lt["positions"], lt["regime"], (st or {}).get("verdict"), (st or {}).get("deriv"), lt["signals"])
    return {"symbol": symbol, "interval": interval, "price": lt["price"], "atr": lt["atr"], "bar_left_sec": lt["bar_left_sec"],
            "data_source": lt["source"], "positions": lt["positions"], "alerts": ctx_alerts, "updating": updating,
            "engine": st["engine"], "model": st.get("model"), "analyzed_at": int(st["time"]), "age_sec": int(time.time() - st["time"]),
            "price_at_analysis": st["price"], "refresh_reason": st["why"], "error": st.get("error"),
            "analysis": st["result"], "history": st["history"][-8:], "llm_available": config.llm_enabled()}


def _run(key, lt, alerts, prev_st, why, use_ai) -> dict:
    ctx = full(lt)
    verdict = ctx.pop("_verdict", None)
    alerts = alerts_for(lt["positions"], lt["regime"], verdict, ctx.get("derivatives"), lt["signals"])
    prev = None
    if prev_st:
        r = prev_st["result"]
        prev = {"minutes_ago": round((time.time() - prev_st["time"]) / 60, 1), "price": prev_st["price"], "headline": r["headline"],
                "bias": r["bias"], "bias_label": {"long": "롱 우위", "short": "숏 우위", "neutral": "중립"}[r["bias"]]}
    engine, model, err = "rules", None, None
    res = None
    if use_ai and config.llm_enabled():
        payload = {**ctx, "alerts": [a["text"] for a in alerts], "previous": prev}
        try:
            res = _sanitize(llm.parse(SYSTEM, json.dumps(payload, ensure_ascii=False, default=str), LiveAnalysis, effort="low", max_tokens=4000), ctx)
            engine, model = llm.provider(), llm.model_name()
        except Exception as e:                                # 무료 한도 초과 · 네트워크 → 규칙 분석으로
            err = f"AI 분석 실패 → 규칙 분석으로 대체: {str(e)[:160]}"
    if res is None:
        res = _sanitize(rules(ctx, alerts, prev), ctx)
    result = res.model_dump()
    hist = (prev_st or {}).get("history", [])
    hist = [*hist, {"time": int(time.time()), "price": lt["price"], "bias": result["bias"], "confidence": result["confidence"],
                    "headline": result["headline"], "why": why, "engine": engine}][-30:]
    st = {"time": time.time(), "bar_time": lt["bar_time"], "price": lt["price"], "pos_sig": _pos_sig(lt["positions"], lt["symbol"]),
          "alert_keys": {a["key"] for a in alerts if a["level"] == "high"}, "result": result, "engine": engine, "model": model,
          "error": err, "why": why, "verdict": verdict, "deriv": ctx.get("derivatives"), "ctx": ctx, "history": hist}
    _state[key] = st
    return st


def ask(symbol: str, interval: str, question: str, history: list[dict] | None = None) -> dict:
    if not config.llm_enabled():
        return {"answer": "AI 키가 없어 질문에 답할 수 없습니다. settings.txt 에 NVIDIA·Gemini(무료) 또는 Claude 키를 넣으면 "
                          "지금 차트·포지션을 보고 답합니다. 대신 위의 규칙 분석과 경고를 참고하세요.", "engine": "rules"}
    st = _state.get((symbol, interval))
    if not st or time.time() - st["time"] > 120:
        live(symbol, interval, force=not st, use_ai=False)
        st = _state[(symbol, interval)]
    lt = light(symbol, interval)
    ctx = {**st["ctx"], "price": _r(lt["price"]), "positions": lt["positions"], "bar_left_sec": lt["bar_left_sec"]}
    convo = "\n".join(f"{'사용자' if h.get('role') == 'user' else 'AI'}: {h.get('text', '')[:600]}" for h in (history or [])[-6:])
    user = (f"실시간 데이터:\n{json.dumps(ctx, ensure_ascii=False, default=str)}\n\n최근 분석:\n{json.dumps(st['result'], ensure_ascii=False)}\n\n"
            + (f"이전 대화:\n{convo}\n\n" if convo else "") + f"질문: {question}")
    try:
        ans = llm.text(ASK_SYSTEM, user, effort="low", max_tokens=1500)
    except Exception as e:
        return {"answer": f"AI 응답 실패: {str(e)[:200]}", "engine": llm.provider(), "error": True}
    return {"answer": ans.strip(), "engine": llm.provider(), "model": llm.model_name()}


# ---------------------------------------------------------------- 포지션 감시 (백그라운드)
def watch_once() -> int:
    """열린 포지션들의 경고를 계산해 새 것만 알림 목록에 쌓는다. (같은 경고는 30분에 한 번)"""
    if _paper is None:
        return 0
    syms = {p["symbol"] for p in positions()}
    n, now = 0, time.time()
    for sym in syms:
        try:
            lt = light(sym, SETTINGS.get("interval", "15m"))
        except Exception:
            continue
        for a in alerts_for([p for p in lt["positions"] if p["symbol"] == sym], lt["regime"], None, None, lt["signals"]):
            if a["level"] == "info" or now - _alert_seen.get(a["key"], 0) < 1800:
                continue
            _alert_seen[a["key"]] = now
            item = {**a, "id": f"{a['key']}:{int(now)}", "created": int(now), "price": lt["price"], "ai": None}
            if SETTINGS.get("auto_ai") and config.llm_enabled() and a["level"] == "high":
                try:
                    r = live(sym, SETTINGS.get("interval", "15m"), force=True)
                    adv = next((x for x in r["analysis"]["position_advice"] if x["symbol"] == sym), None)
                    item["ai"] = r["analysis"]["headline"] + (f" → {adv['reason']}" if adv else "")
                except Exception:
                    pass
            alerts_feed.append(item)
            n += 1
    for k in [k for k, t in _alert_seen.items() if now - t > 7200]:
        _alert_seen.pop(k, None)
    return n


def recent_alerts(since: int = 0) -> list[dict]:
    return [a for a in reversed(alerts_feed) if a["created"] > since]


async def run_forever():
    while True:
        if SETTINGS.get("watch", True):
            try:
                await asyncio.to_thread(watch_once)
            except Exception:
                pass
        await asyncio.sleep(max(10, int(SETTINGS.get("every_sec", 30))))


_task: asyncio.Task | None = None


def start():
    global _task
    if _task is None:
        _task = asyncio.create_task(run_forever())
