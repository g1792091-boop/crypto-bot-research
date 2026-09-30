"""FastAPI 서버: REST API + 프론트엔드 정적 파일."""
from __future__ import annotations

import time
from dataclasses import asdict
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agents, analysis, backtest, config, improve, indicators, liquidation, llm, nl_strategy, orderflow
from .data import coinglass, exchanges, market, news, sentiment, symbols
from .llm import LLMUnavailable
from .paper import PaperManager
from .quant import entry, footprint, forecast, portfolio, risk, toptraders
from .quant.scanner import scanner
from .strategy import StrategySpec, validate

paper = PaperManager()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    paper.start()
    orderflow.tracker.start()
    scanner.start()
    yield


app = FastAPI(title="GH Quant", lifespan=lifespan)


def _bad(e: Exception):
    raise HTTPException(status_code=400, detail=str(e))


# ------------------------------------------------------------------ 상태
@app.get("/api/status")
def status():
    return {
        "llm": config.llm_enabled(), "llm_provider": llm.provider(), "llm_label": llm.label(), "model": llm.model_name(),
        "intervals": market.INTERVALS,
        "coinglass": coinglass.enabled(), "data_source_mode": config.DATA_SOURCE,
        "indicators": {k: {"outputs": v["outputs"], "defaults": v["defaults"], "desc": v["desc"], "tv": v["tv"]}
                       for k, v in indicators.REGISTRY.items()},
    }


# ------------------------------------------------------------------ 시장 데이터
@app.get("/api/candles")
def candles(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 500):
    try:
        rows, src = market.candles(symbol.upper(), interval, min(limit, 3000))
    except ValueError as e:
        _bad(e)
    return {"source": src, "candles": rows}


@app.get("/api/resolve")
def resolve_symbol(q: str):
    """검색어(한글 이름·티커) → 바이낸스 선물 심볼."""
    return {"symbol": symbols.resolve(q)}


@app.get("/api/tickers")
def tickers(symbols: str = "BTCUSDT,ETHUSDT"):
    rows, src = market.tickers([s.strip().upper() for s in symbols.split(",") if s.strip()])
    return {"source": src, "items": rows}


@app.get("/api/orderbook")
def get_orderbook(symbol: str = "BTCUSDT", step: Optional[float] = None, rows: int = 20):
    try:
        return orderflow.orderbook(symbol.upper(), step, min(rows, 100))
    except Exception as e:
        raise HTTPException(502, f"호가창 요청 실패: {e}")


@app.get("/api/whales")
def get_whales(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 500, min_usd: Optional[float] = None):
    try:
        return orderflow.whales(symbol.upper(), interval, min(limit, 1500), min_usd)
    except ValueError as e:
        _bad(e)


@app.get("/api/exchanges")
def get_exchanges(symbol: str = "BTCUSDT"):
    return exchanges.compare(symbol.upper())


@app.get("/api/fear-greed")
def get_fear_greed(days: int = 90):
    try:
        return sentiment.fear_greed(min(days, 365))
    except Exception as e:
        raise HTTPException(502, f"공포·탐욕 지수 요청 실패: {e}")


@app.get("/api/coinbase-premium")
def get_coinbase_premium(symbol: str = "BTCUSDT", interval: str = "1h"):
    try:
        return sentiment.coinbase_premium(symbol.upper(), interval)
    except Exception as e:
        raise HTTPException(502, f"코인베이스 프리미엄 계산 실패: {e}")


@app.get("/api/cg-index")
def list_cg_index():
    return {"enabled": coinglass.enabled(), "items": [{"name": k, "title": v[0]} for k, v in sentiment.CG_INDEX.items()]}


@app.get("/api/cg-index/{name}")
def get_cg_index(name: str):
    try:
        return sentiment.coinglass_index(name)
    except ValueError as e:
        _bad(e)
    except Exception as e:
        raise HTTPException(502, f"CoinGlass 요청 실패: {e}")


@app.get("/api/analysis")
def get_analysis(symbol: str = "BTCUSDT", interval: str = "1h", ai: bool = False):
    try:
        return analysis.analyze(symbol.upper(), interval, with_ai=ai)
    except (ValueError, LLMUnavailable) as e:
        _bad(e)


@app.get("/api/derivatives")
def derivatives(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 200):
    return {**market.derivatives(symbol, interval, limit), "premium": market.funding_now(symbol)}


@app.get("/api/liq-heatmap")
def liq_heatmap(symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 400):
    try:
        return liquidation.heatmap(symbol.upper(), interval, min(limit, 1000))
    except ValueError as e:
        _bad(e)


@app.get("/api/market/dominance")
def dominance():
    try:
        return market.global_dominance()
    except Exception as e:
        raise HTTPException(502, f"CoinGecko 요청 실패: {e}")


@app.get("/api/market/heatmap")
def heatmap(limit: int = 60):
    try:
        return {"items": market.heatmap(limit)}
    except Exception as e:
        raise HTTPException(502, f"바이낸스 요청 실패: {e}")


@app.get("/api/news")
def get_news(limit: int = 40):
    return news.headlines(limit)


class NewsBriefItem(BaseModel):
    id: str
    ko_title: str
    sentiment: Literal["bullish", "bearish", "neutral"]
    impact: int


class NewsBrief(BaseModel):
    items: list[NewsBriefItem]


_brief_cache: dict[tuple, dict] = {}


@app.get("/api/news/brief")
def news_brief(limit: int = 15):
    """AI(Claude/Gemini)가 헤드라인을 한국어로 옮기고 호재/악재·영향도(1~3)를 붙인다."""
    if not config.llm_enabled():
        raise HTTPException(400, "AI 키(ANTHROPIC_API_KEY 또는 무료 GEMINI_API_KEY)가 필요합니다.")
    items = news.headlines(limit)["items"]
    key = tuple(i["id"] for i in items)
    if key not in _brief_cache:
        lines = "\n".join(f"{i['id']}\t{i['title']}" for i in items)
        try:
            brief = llm.parse("너는 코인 선물 트레이더를 위한 뉴스 에디터다. 각 헤드라인을 자연스러운 한국어 한 줄로 옮기고 "
                              "(이미 한국어면 다듬기만), 비트코인·코인 선물 가격에 호재/악재/중립인지와 영향도(1 낮음~3 높음)를 "
                              "매긴다. id 는 입력 그대로 돌려준다.", lines, NewsBrief, effort="low")
        except LLMUnavailable as e:
            _bad(e)
        _brief_cache.clear()
        _brief_cache[key] = {b.id: b.model_dump() for b in brief.items}
    return {"items": _brief_cache[key]}


@app.get("/api/calendar")
def calendar(impact: str = "High"):
    return news.economic_calendar(min_impact=impact)


# ------------------------------------------------------------------ 전략 / 백테스트
class TextStrategyReq(BaseModel):
    text: str
    symbol: Optional[str] = None
    interval: Optional[str] = None


class BacktestReq(BaseModel):
    spec: StrategySpec
    bars: int = 1500
    initial_equity: float = 10_000


class AutoReq(TextStrategyReq):
    bars: int = 1500
    initial_equity: float = 10_000
    start_paper: bool = False


def _from_text(text: str, symbol: str | None, interval: str | None) -> tuple[StrategySpec, str, str | None]:
    """AI 로 변환. AI 가 실패하면(무료 한도 초과·키 오류 등) 기본 변환기로 대신하고 이유를 함께 돌려준다."""
    try:
        spec, engine = nl_strategy.from_text(text, symbol, interval)
        return spec, engine, None
    except LLMUnavailable as e:
        try:
            return nl_strategy.rule_parse(text, symbol, interval), "rules", str(e)
        except ValueError as e2:
            raise ValueError(f"AI 를 쓸 수 없어({e}) 기본 변환기로 시도했지만 이해하지 못했습니다. {e2}") from e2


@app.post("/api/strategy/parse")
def parse_strategy(req: TextStrategyReq):
    try:
        spec, engine, ai_error = _from_text(req.text, req.symbol, req.interval)
    except ValueError as e:
        _bad(e)
    return {"spec": spec.model_dump(), "engine": engine, "ai_error": ai_error, "problems": validate(spec)}


class RefineReq(BaseModel):
    spec: StrategySpec
    message: str
    history: list[dict] = []
    metrics: Optional[dict] = None
    bars: int = 1500


@app.post("/api/strategy/refine")
def refine_strategy(req: RefineReq):
    """대화로 전략 수정 → 바로 백테스트. '알아서 개선' 류 요청은 자동 개선을 돌린다."""
    try:
        if nl_strategy.wants_improve(req.message):
            rep = improve.run_for(req.spec, min(req.bars, 5000), with_ai=config.llm_enabled())
            spec = StrategySpec(**rep["spec"])
            reply = ("검증을 통과한 개선을 적용했습니다: " + " / ".join(rep["changes"])) if rep["applied"] else \
                "여러 개선안을 시험했지만 검증 구간(최근 30%)에서 나아지는 것이 없어 전략을 그대로 두었습니다."
            result = backtest.run_live_data(spec, min(req.bars, 5000))
            return {"spec": spec.model_dump(), "changes": rep["changes"], "reply": rep.get("ai_summary") or reply,
                    "engine": "improve", "improve": rep, "backtest": result}
        ai_error = None
        try:
            spec, changes, reply, engine = nl_strategy.refine(req.spec, req.message, req.history, req.metrics)
        except LLMUnavailable as e:   # AI 실패 → 기본 편집기로
            ai_error = str(e)
            spec, changes, reply, engine = nl_strategy.refine(req.spec, req.message, req.history, req.metrics, use_ai=False)
        result = backtest.run_live_data(spec, min(req.bars, 5000)) if changes or engine in ("claude", "gemini") else None
    except (ValueError, LLMUnavailable) as e:
        _bad(e)
    return {"spec": spec.model_dump(), "changes": changes, "reply": reply, "engine": engine, "ai_error": ai_error, "backtest": result}


class ImproveReq(BaseModel):
    spec: StrategySpec
    bars: int = 1500
    ai: bool = False


def _norm(spec: StrategySpec) -> StrategySpec:
    """'eth', '이더', 'PEPE' 처럼 들어온 심볼을 바이낸스 선물 심볼로."""
    sym = symbols.resolve(spec.symbol or "BTCUSDT")
    return spec if sym == spec.symbol else spec.model_copy(update={"symbol": sym})


@app.post("/api/strategy/improve")
def improve_strategy(req: ImproveReq):
    try:
        return improve.run_for(_norm(req.spec), min(req.bars, 5000), with_ai=req.ai)
    except (ValueError, LLMUnavailable) as e:
        _bad(e)


@app.post("/api/backtest")
def run_backtest(req: BacktestReq):
    try:
        return backtest.run_live_data(_norm(req.spec), min(req.bars, 5000), req.initial_equity)
    except ValueError as e:
        _bad(e)


class ScanReq(BaseModel):
    spec: StrategySpec
    symbols: list[str]
    intervals: list[str]
    bars: int = 1500
    initial_equity: float = 10_000


@app.post("/api/strategy/scan")
def scan_strategy(req: ScanReq):
    """같은 전략을 여러 코인 × 여러 봉으로 한꺼번에 백테스트해서 성적순으로."""
    from concurrent.futures import ThreadPoolExecutor

    from .strategy import INTERVALS as OK_IV
    syms = list(dict.fromkeys(symbols.resolve(s) for s in req.symbols if s.strip()))
    ivs = [iv for iv in dict.fromkeys(req.intervals) if iv in OK_IV]
    combos = [(s, iv) for s in syms for iv in ivs]
    if not combos:
        _bad(ValueError("코인과 봉을 하나 이상 고르세요."))
    if len(combos) > 80:
        _bad(ValueError(f"조합이 너무 많습니다 ({len(combos)}개). 80개 이하로 줄여 주세요."))

    def one(combo):
        s, iv = combo
        spec = req.spec.model_copy(update={"symbol": s, "interval": iv})
        try:
            r = backtest.run_live_data(spec, min(req.bars, 5000), req.initial_equity)
            return {"symbol": s, "interval": iv, "metrics": r["metrics"], "data_source": r["data_source"], "bars": len(r["candles"])}
        except Exception as e:   # 없는 종목·상장 기간 부족 등은 그 줄만 오류로
            return {"symbol": s, "interval": iv, "error": str(e)}

    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(one, combos))
    rows.sort(key=lambda r: (r.get("error") is not None, -(r.get("metrics", {}).get("total_return_pct") or -1e9)))
    return {"rows": rows}


@app.post("/api/strategy/auto")
def auto(req: AutoReq):
    """자연어 → 전략 변환 → 백테스트 → (선택) 페이퍼 봇 가동까지 한 번에."""
    try:
        spec, engine, ai_error = _from_text(req.text, req.symbol, req.interval)
        result = backtest.run_live_data(spec, min(req.bars, 5000), req.initial_equity)
    except (ValueError, LLMUnavailable) as e:
        _bad(e)
    result["engine"] = engine
    result["ai_error"] = ai_error
    if req.start_paper:
        result["paper_bot"] = paper.add_bot(spec, req.initial_equity).to_dict()
    return result


# ------------------------------------------------------------------ 페이퍼 트레이딩
class BotReq(BaseModel):
    spec: StrategySpec
    initial_equity: float = 10_000


class ManualOrder(BaseModel):
    symbol: str = "BTCUSDT"
    side: Literal["long", "short"]
    margin: float
    leverage: float = 5
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None


class ResetReq(BaseModel):
    initial_equity: float = 10_000
    fee_pct: float = 0.04


@app.get("/api/paper/bots")
def list_bots():
    return [b.to_dict() for b in paper.bots.values()]


@app.post("/api/paper/bots")
def create_bot(req: BotReq):
    try:
        spec = _norm(req.spec)
        market.candles(spec.symbol, spec.interval, 2)   # 없는 종목이면 여기서 오류 → 봇을 만들지 않는다
        return paper.add_bot(spec, req.initial_equity).to_dict()
    except ValueError as e:
        _bad(e)


class BotConfig(BaseModel):
    auto_improve: Optional[bool] = None
    improve_every: Optional[int] = None


@app.post("/api/paper/bots/{bot_id}/config")
def bot_config(bot_id: str, cfg: BotConfig):
    bot = paper.bots.get(bot_id)
    if not bot:
        raise HTTPException(404, "봇이 없습니다.")
    if cfg.auto_improve is not None:
        bot.auto_improve = cfg.auto_improve
    if cfg.improve_every:
        bot.improve_every = max(3, cfg.improve_every)
    paper.save()
    return bot.to_dict()


@app.post("/api/paper/bots/{bot_id}/improve")
def bot_improve(bot_id: str):
    bot = paper.bots.get(bot_id)
    if not bot:
        raise HTTPException(404, "봇이 없습니다.")
    rep = bot.maybe_improve(force=True)
    paper.save()
    return rep


@app.post("/api/paper/bots/{bot_id}/{action}")
def bot_action(bot_id: str, action: Literal["pause", "resume", "close", "delete"]):
    bot = paper.bots.get(bot_id)
    if not bot:
        raise HTTPException(404, "봇이 없습니다.")
    if action == "pause":
        bot.running = False
    elif action == "resume":
        bot.running = True
    elif action == "close" and bot.sim.position:
        bot.sim.close_position(bot.last_price or bot.sim.position.entry_price, int(time.time()),
                               "manual_close")
    elif action == "delete":
        paper.bots.pop(bot_id)
    paper.save()
    return {"ok": True}




@app.get("/api/paper/markers")
def paper_markers(symbol: str = "BTCUSDT"):
    """차트에 표시할 페이퍼 봇·수동 계좌의 진입/청산 기록."""
    sym = symbol.upper()
    manual = paper.manual
    pos = manual.positions.get(sym)
    return {
        "bots": [b.markers() for b in paper.bots.values() if b.spec.symbol == sym],
        "manual": {"trades": [asdict(t) for t in manual.trades if getattr(t, "symbol", None) == sym][-300:],
                   "position": None if not pos else {"side": "long" if pos.side == 1 else "short", "leverage": pos.leverage,
                                                     "entry_price": pos.entry_price, "entry_time": pos.entry_time,
                                                     "stop": pos.stop, "take": pos.take, "liq_price": pos.liq_price}},
    }


@app.get("/api/paper/account")
def manual_account():
    return paper.manual.snapshot()


@app.post("/api/paper/order")
def manual_order(o: ManualOrder):
    try:
        res = paper.manual.open(o.symbol, o.side, o.margin, o.leverage, o.stop_loss_pct, o.take_profit_pct)
    except Exception as e:
        _bad(e)
    paper.save()
    return res


class ModifyReq(BaseModel):
    stop: Optional[float] = None
    take: Optional[float] = None


@app.post("/api/paper/position/{symbol}")
def modify_position(symbol: str, req: ModifyReq):
    """진입 후 손절·익절 가격 수정. 값을 비우면(null) 해제."""
    try:
        res = paper.manual.modify(symbol.upper(), req.stop, req.take)
    except ValueError as e:
        _bad(e)
    paper.save()
    return res


@app.get("/api/levels")
def get_levels(symbol: str = "BTCUSDT", interval: str = "1h"):
    """자동 지지·저항 구간과 추세선."""
    try:
        c, _ = market.candles(symbol.upper(), interval, 500)
    except ValueError as e:
        _bad(e)
    return analysis.sr_levels(c)


@app.post("/api/paper/close/{symbol}")
def manual_close(symbol: str):
    try:
        res = paper.manual.close(symbol)
    except Exception as e:
        _bad(e)
    paper.save()
    return res


@app.post("/api/paper/reset")
def manual_reset(req: ResetReq):
    paper.reset_manual(req.initial_equity, req.fee_pct)
    return paper.manual.snapshot()


# ------------------------------------------------------------------ AI 에이전트 팀
class AgentReq(BaseModel):
    symbol: str = "BTCUSDT"


class ExecuteDecisionReq(BaseModel):
    symbol: str
    decision: agents.TradeDecision
    equity_pct_cap: float = 20


@app.post("/api/agents/run")
def run_agents(req: AgentReq):
    try:
        return agents.run_team(req.symbol)
    except LLMUnavailable as e:
        _bad(e)


@app.post("/api/agents/execute")
def execute_decision(req: ExecuteDecisionReq):
    """에이전트 결정을 페이퍼 계좌에 주문으로 넣는다 (실거래 아님)."""
    d = req.decision
    if d.action == "stay_flat":
        raise HTTPException(400, "관망 결정은 주문할 수 없습니다.")
    acct = paper.manual
    pct = min(d.position_pct or 10, req.equity_pct_cap)
    margin = acct.free_margin() * pct / 100
    price = d.entry or 0
    sl = abs(price - d.stop_loss) / price * 100 if d.stop_loss and price else None
    tp = abs(d.take_profits[0] - price) / price * 100 if d.take_profits and price else None
    try:
        res = acct.open(req.symbol, d.action, margin, max(1.0, d.leverage), sl, tp)
    except Exception as e:
        _bad(e)
    paper.save()
    return res


# ------------------------------------------------------------------ 퀀트: 패턴 예측 · 순환매 · 스캐너 · 리스크
@app.get("/api/footprint")
def get_footprint(symbol: str = "BTCUSDT", interval: str = "1h", bars: int = 60, analysis: bool = False):
    """봉 볼륨 풋프린트 (작은 봉의 테이커 매수·매도로 근사). analysis=true 면 진입 신호 · 지지저항 판정 · 다음 봉까지."""
    try:
        if analysis:
            return footprint.analyze(symbols.resolve(symbol), interval, max(20, min(bars, 300)))
        return footprint.footprint(symbols.resolve(symbol), interval, max(5, min(bars, 300)))
    except ValueError as e:
        _bad(e)


@app.get("/api/entry")
def get_entry(symbol: str = "BTCUSDT", interval: str = "1h"):
    """종합 진입 판단: 시장 판단 · 다음 봉 · 유사 패턴 · 풋프린트 · 호가."""
    try:
        return entry.entry(symbols.resolve(symbol), interval)
    except ValueError as e:
        _bad(e)


@app.get("/api/forecast")
def get_forecast(symbol: str = "BTCUSDT", interval: str = "1h", window: int = 48, horizon: int = 24):
    """과거 비슷한 차트의 이후 흐름(예상 시나리오 범위) + 다음 봉 예측."""
    try:
        return forecast.forecast(symbols.resolve(symbol), interval, max(16, min(window, 200)), max(4, min(horizon, 120)))
    except ValueError as e:
        _bad(e)


@app.get("/api/toptraders")
def get_top_traders(window: Literal["day", "week", "month", "allTime"] = "month", n: int = 30, sort: Literal["pnl", "roi"] = "pnl",
                    min_account: float = 100_000):
    """잘하는 트레이더(Hyperliquid 수익 상위)가 지금 들고 있는 포지션 · 레버리지 · 진입가, 코인별 집계."""
    return toptraders.top_traders(window, max(5, min(n, 60)), sort, max(0.0, min_account))


@app.get("/api/toptraders/binance")
def get_top_trader_ratios(symbol: str = "BTCUSDT", interval: str = "1h"):
    """바이낸스 상위 트레이더 롱/숏 비율."""
    try:
        return toptraders.binance_ratios(symbols.resolve(symbol), interval)
    except Exception as e:
        _bad(ValueError(f"바이낸스 상위 트레이더 비율을 불러오지 못했습니다: {e}"))


@app.get("/api/scanner")
def scanner_status():
    return scanner.status()


@app.get("/api/scanner/signals")
def scanner_signals(since: int = 0, limit: int = 100):
    return {"now": int(time.time()), "items": scanner.recent(since, min(limit, 400))}


class ScannerCfg(BaseModel):
    enabled: Optional[bool] = None
    symbols: Optional[list[str]] = None
    intervals: Optional[list[str]] = None
    signals: Optional[dict[str, bool]] = None


@app.post("/api/scanner/config")
def scanner_config(cfg: ScannerCfg):
    return scanner.set_config(**cfg.model_dump())


@app.post("/api/scanner/run")
def scanner_run():
    n = scanner.scan()
    return {"new": n, **scanner.status()}


class RiskMatrixReq(BaseModel):
    symbols: list[str]
    interval: str = "1d"
    bars: int = 120


@app.post("/api/risk/matrix")
def risk_matrix(req: RiskMatrixReq):
    try:
        return risk.matrix([symbols.resolve(s) for s in req.symbols][:30], req.interval, max(30, min(req.bars, 1500)))
    except ValueError as e:
        _bad(e)


def _paper_positions() -> list[dict]:
    pos = [{"symbol": p["symbol"], "side": p["side"], "notional": p["qty"] * p["mark_price"], "leverage": p["leverage"], "who": "수동"}
           for p in paper.manual.snapshot()["positions"]]
    for b in paper.bots.values():
        p = b.sim.position
        if p is not None:
            pos.append({"symbol": b.spec.symbol, "side": "long" if p.side == 1 else "short", "leverage": p.leverage,
                        "notional": p.qty * (b.last_price or p.entry_price), "who": f"봇 {b.spec.name}"})
    return pos


@app.get("/api/risk/portfolio")
def risk_portfolio(interval: str = "1d", shock_pct: float = -10.0):
    """모의 계좌 + 실행 중인 봇 포지션을 합친 위험 (VaR · BTC 급락 스트레스)."""
    pos = _paper_positions()
    if not pos:
        return {"positions": 0, "items": []}
    try:
        return {**risk.portfolio(pos, interval, shock_pct=shock_pct), "items": pos}
    except ValueError as e:
        _bad(e)


class MonteCarloReq(BaseModel):
    pnls: list[float]
    initial_equity: float = 10_000
    sims: int = 2000


@app.post("/api/risk/montecarlo")
def risk_montecarlo(req: MonteCarloReq):
    try:
        return risk.montecarlo(req.pnls, req.initial_equity, max(200, min(req.sims, 10000)))
    except ValueError as e:
        _bad(e)


class SweepReq(BaseModel):
    spec: StrategySpec
    p1: str
    v1: list[float]
    p2: Optional[str] = None
    v2: Optional[list[float]] = None
    bars: int = 1500


@app.post("/api/risk/params")
def risk_params(spec: StrategySpec):
    return risk.params_of(spec.model_dump())


@app.post("/api/risk/sweep")
def risk_sweep(req: SweepReq):
    try:
        return risk.sweep(_norm(req.spec).model_dump(), req.p1, req.v1, req.p2, req.v2, min(req.bars, 5000))
    except (ValueError, KeyError, IndexError) as e:
        _bad(ValueError(f"스윕 실패: {e}"))


# ------------------------------------------------------------------ 기관식 포트폴리오
class OptimizeReq(BaseModel):
    symbols: list[str]
    interval: str = "1d"
    bars: int = 365
    max_weight: float = 0.4


@app.post("/api/portfolio/optimize")
def portfolio_optimize(req: OptimizeReq):
    try:
        return portfolio.optimize([symbols.resolve(s) for s in req.symbols][:25], req.interval, max(60, min(req.bars, 1500)),
                                  max(0.05, min(req.max_weight, 1.0)))
    except ValueError as e:
        _bad(e)


class StressReq(BaseModel):
    weights: Optional[dict[str, float]] = None      # 없으면 지금 모의 포지션
    equity: float = 10_000


@app.post("/api/portfolio/stress")
def portfolio_stress(req: StressReq):
    pos = ([{"symbol": symbols.resolve(s), "side": "long" if w >= 0 else "short", "notional": abs(w) * req.equity, "leverage": 1}
            for s, w in req.weights.items() if w] if req.weights else _paper_positions())
    try:
        return portfolio.stress(pos)
    except ValueError as e:
        _bad(e)


@app.get("/api/portfolio/exposure")
def portfolio_exposure():
    try:
        return portfolio.exposures(_paper_positions())
    except ValueError as e:
        _bad(e)


class TearReq(BaseModel):
    source: Literal["paper", "custom"] = "paper"
    trades: Optional[list[dict]] = None
    equity_curve: Optional[list[dict]] = None
    initial: float = 10_000


@app.post("/api/portfolio/tearsheet")
def portfolio_tearsheet(req: TearReq):
    """성과 분석. paper = 모의 계좌 + 모든 봇 거래, custom = 넘겨준 거래(백테스트 등)."""
    if req.source == "paper":
        trades = [dict(t) for t in paper.manual.snapshot()["trades"]]
        initial = paper.manual.initial_equity if hasattr(paper.manual, "initial_equity") else 10_000
        for b in paper.bots.values():
            trades += [{**asdict(t), "symbol": b.spec.symbol} for t in b.sim.trades]
            initial += b.initial_equity
        curve = None
    else:
        trades, curve, initial = req.trades or [], req.equity_curve, req.initial
    try:
        return portfolio.tearsheet(trades, initial, curve)
    except ValueError as e:
        _bad(e)


# ------------------------------------------------------------------ 프론트엔드
app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")
