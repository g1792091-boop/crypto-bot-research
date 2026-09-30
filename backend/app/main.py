"""FastAPI 서버: REST API + 프론트엔드 정적 파일."""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agents, analysis, backtest, config, indicators, liquidation, llm, nl_strategy
from .data import coinglass, market, news
from .llm import LLMUnavailable
from .paper import PaperManager
from .strategy import StrategySpec, validate

paper = PaperManager()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    paper.start()
    yield


app = FastAPI(title="Coin Futures Terminal", lifespan=lifespan)


def _bad(e: Exception):
    raise HTTPException(status_code=400, detail=str(e))


# ------------------------------------------------------------------ 상태
@app.get("/api/status")
def status():
    return {
        "llm": config.llm_enabled(), "model": config.CLAUDE_MODEL if config.llm_enabled() else None,
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


@app.get("/api/tickers")
def tickers(symbols: str = "BTCUSDT,ETHUSDT"):
    rows, src = market.tickers([s.strip().upper() for s in symbols.split(",") if s.strip()])
    return {"source": src, "items": rows}


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
    """Claude 가 헤드라인을 한국어로 옮기고 호재/악재·영향도(1~3)를 붙인다."""
    if not config.llm_enabled():
        raise HTTPException(400, "ANTHROPIC_API_KEY 가 필요합니다.")
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


@app.post("/api/strategy/parse")
def parse_strategy(req: TextStrategyReq):
    try:
        spec, engine = nl_strategy.from_text(req.text, req.symbol, req.interval)
    except (ValueError, LLMUnavailable) as e:
        _bad(e)
    return {"spec": spec.model_dump(), "engine": engine, "problems": validate(spec)}


@app.post("/api/backtest")
def run_backtest(req: BacktestReq):
    try:
        return backtest.run_live_data(req.spec, min(req.bars, 5000), req.initial_equity)
    except ValueError as e:
        _bad(e)


@app.post("/api/strategy/auto")
def auto(req: AutoReq):
    """자연어 → 전략 변환 → 백테스트 → (선택) 페이퍼 봇 가동까지 한 번에."""
    try:
        spec, engine = nl_strategy.from_text(req.text, req.symbol, req.interval)
        result = backtest.run_live_data(spec, min(req.bars, 5000), req.initial_equity)
    except (ValueError, LLMUnavailable) as e:
        _bad(e)
    result["engine"] = engine
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
        return paper.add_bot(req.spec, req.initial_equity).to_dict()
    except ValueError as e:
        _bad(e)


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


# ------------------------------------------------------------------ 프론트엔드
app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")
