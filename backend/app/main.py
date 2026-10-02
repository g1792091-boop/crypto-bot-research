"""FastAPI 서버: REST API + 프론트엔드 정적 파일."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agents, ai_auto, ai_routes, analysis, autopilot, backtest, config, improve, indicators, library, liquidation, llm, nl_strategy, orderflow
from .data import coinglass, exchanges, market, news, sentiment, symbols
from .llm import LLMUnavailable
from .paper import PaperManager
from .quant import copilot, entry, footprint, forecast, portfolio, risk, toptraders
from .quant.scanner import scanner
from .auth import PasswordMiddleware
from .team import engine as team
from .office import engine as office
from .strategy import StrategySpec, validate

paper = PaperManager()
copilot.bind(paper)
team.bind(paper)
autopilot.bind(paper)
ai_auto.bind(paper)
office.bind(paper)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    paper.start()
    orderflow.tracker.start()
    scanner.start()
    copilot.start()
    team.start()
    autopilot.start()
    ai_auto.start()
    office.start()
    if not os.environ.get("SCENBOT_OFF"):
        from . import scenbot
        scenbot.start()
    yield


app = FastAPI(title="GH Quant", lifespan=lifespan)
app.add_middleware(PasswordMiddleware)        # APP_PASSWORD 가 있으면 접속 비밀번호 (서버에서 24시간 돌릴 때)


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _bad(e: Exception):
    raise HTTPException(status_code=400, detail=str(e))


@app.exception_handler(RuntimeError)
async def _data_down(_req, e: RuntimeError):
    """거래소 시세를 못 받았을 때 (가상 데이터로 몰래 바꾸지 않고 이유를 그대로 보여준다)."""
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={"detail": str(e)[:400]})


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
        from . import scenbot
        return scenbot.annotate(analysis.analyze(symbol.upper(), interval, with_ai=ai))
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
        raise HTTPException(502, f"시세 요청 실패: {e}")


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
        raise HTTPException(400, "AI 키(ANTHROPIC_API_KEY, 무료 NVIDIA_API_KEY 또는 무료 GEMINI_API_KEY)가 필요합니다.")
    items = news.headlines(limit)["items"]
    key = tuple(i["id"] for i in items)
    if key not in _brief_cache:
        lines = "\n".join(f"{i['id']}\t{i['title']}" for i in items)
        try:
            brief = llm.parse("너는 코인 선물 트레이더를 위한 뉴스 에디터다. 각 헤드라인을 자연스러운 한국어 한 줄로 옮기고 "
                              "(이미 한국어면 다듬기만), 비트코인·코인 선물 가격에 호재/악재/중립인지와 영향도(1 낮음~3 높음)를 "
                              "매긴다. id 는 입력 그대로 돌려준다.", lines, NewsBrief, effort="low", feature="news")
        except LLMUnavailable as e:
            _bad(e)
        _brief_cache.clear()
        _brief_cache[key] = {b.id: b.model_dump() for b in brief.items}
    return {"items": _brief_cache[key]}


# ------------------------------------------------------------------ AI 사무실 (코인팀 · 퀀트 연구소 · 전략·리스크팀 · 데이터·미디어팀)
@app.get("/api/office/state")
def office_state(since: int = 0, visible: bool = True):
    if visible:
        office.RT["visible"] = time.time()
    return office.snapshot_state(since)


@app.get("/api/office/roster")
def office_roster():
    return office.roster_view()


class OfficeAsk(BaseModel):
    text: str
    room: str = "hq"


@app.post("/api/office/ask")
def office_ask(req: OfficeAsk):
    try:
        return office.ask(req.text, req.room)
    except ValueError as e:
        _bad(e)


@app.post("/api/office/agenda/{agenda_id}")
def office_agenda(agenda_id: str):
    try:
        return office.run_agenda(agenda_id)
    except ValueError as e:
        _bad(e)


@app.post("/api/office/job")
def office_job(job: Optional[str] = None):
    """지금 일 시키기 (job 을 비우면 다음 차례 업무)."""
    import threading
    if office.RT["job"]:
        _bad(ValueError(f"지금 '{office.JOB_KO.get(office.RT['job'])}' 중입니다. 끝나면 다시 눌러 주세요."))
    if job and job not in office.JOB_FN:
        _bad(ValueError("없는 업무입니다"))
    threading.Thread(target=(lambda: office._safe_job(job)) if job else office.cycle, daemon=True).start()
    return {"ok": True}


@app.post("/api/office/report")
def office_report():
    import threading
    threading.Thread(target=office.report, kwargs={"manual": True}, daemon=True).start()
    return {"ok": True}


@app.get("/api/office/reports")
def office_reports():
    return {"items": office.reports()}


@app.get("/api/office/backlog")
def office_backlog():
    return {"items": office.backlog()}


@app.get("/api/office/forecasts")
def office_forecasts():
    return {"items": [office._fc_view(f) for f in reversed(office.ST["forecasts"][-100:])], "score": office.forecast_score()}


@app.post("/api/office/cfg")
def office_cfg(body: dict):
    try:
        return office.set_cfg(body)
    except ValueError as e:
        _bad(e)


@app.post("/api/office/stop")
def office_stop():
    office.RT["stop_meeting"] = True
    return {"ok": True}


@app.post("/api/office/rate/{entry_id}")
def office_rate(entry_id: int, v: int = 1):
    office.rate(entry_id, v)
    return {"ok": True}


@app.post("/api/office/clear")
def office_clear():
    office.clear_log()
    return {"ok": True}


@app.get("/api/office/pipeline")
def office_pipeline():
    from .office import teamjobs
    return {"items": list(reversed(teamjobs.pipeline())), "live": teamjobs.live_items(),
            "rules": {"promote": teamjobs.PROMOTE, "retire": teamjobs.RETIRE, "demo_max": teamjobs.DEMO_MAX}}


@app.post("/api/office/team/{team_id}")
def office_team_run(team_id: str):
    """이 팀 업무를 지금 시킨다."""
    import threading
    from .office import roster as oro, teamjobs
    if team_id not in oro.TEAM_BY:
        _bad(ValueError("없는 팀입니다"))
    if team_id in teamjobs.ext_teams():
        threading.Thread(target=teamjobs.run_team, args=(team_id,), daemon=True).start()
    else:
        job = {"coin": "flowscan", "quant": "research", "strat": "forecast", "data": "sns"}[team_id]
        threading.Thread(target=office._safe_job, args=(job,), daemon=True).start()
    return {"ok": True}


@app.get("/api/office/termind")
def office_termind():
    """터미널 지표 추세·타점팀의 최근 판정 (코인별 · 봉별 147개 지표 합의 · 타점)."""
    from .office import teamjobs
    from .quant import termind
    ok, err = termind.available()
    return {"available": ok, "error": err, "coins": teamjobs.term_coins(), "items": list(teamjobs.TERM.values()),
            "interval_sec": office.CFG.get("termind_sec", 60)}


@app.get("/api/scenbot")
def scenbot_view():
    """시나리오 진입 봇: 정책 · 성적 · 주문 · 배운 적중률 · 메타 모델 · 개선 기록."""
    from . import scenbot
    return scenbot.view()


class ScenbotSettings(BaseModel):
    enabled: Optional[bool] = None
    symbols: Optional[list[str]] = None
    intervals: Optional[list[str]] = None
    leverage: Optional[float] = None
    margin_pct: Optional[float] = None
    follow_chart: Optional[bool] = None
    max_open: Optional[int] = None
    learn_hours: Optional[float] = None
    use_termind: Optional[bool] = None
    use_chart: Optional[bool] = None


@app.post("/api/scenbot/settings")
def scenbot_settings(body: ScenbotSettings):
    from . import scenbot
    b = body.model_dump(exclude_none=True)
    if "symbols" in b:
        try:
            b["symbols"] = [symbols.resolve(x) for x in b["symbols"]]
        except ValueError as e:
            _bad(e)
    return scenbot.set_settings(b)


@app.post("/api/scenbot/learn")
def scenbot_learn():
    """지금 학습(그림자 채점 추가 · 보정 · 메타 모델 · 정책 walk-forward 재선정) — 뒤에서 돈다."""
    from . import scenbot
    if scenbot._th["busy"]:
        return {"ok": False, "busy": True}
    return {"ok": scenbot.learn_bg()}


@app.get("/api/scenbot/chart")
def scenbot_chart(symbol: str = "BTCUSDT", interval: str = "1h"):
    """트레이드 차트 표시용: 이 코인의 시나리오 봇 주문·포지션(실시간 손익)과 지난 진입·청산."""
    from . import scenbot
    try:
        return scenbot.chart(symbols.resolve(symbol), interval)
    except ValueError as e:
        _bad(e)


@app.post("/api/scenbot/revert/{version}")
def scenbot_revert(version: int):
    from . import scenbot
    try:
        return scenbot.revert(version)
    except ValueError as e:
        _bad(e)


@app.get("/api/growth")
def growth_check(start: float = 100_000, target: float = 100_000_000, days: int = 30, lev: float = 3.0, fresh: bool = False):
    """목표 현실 점검 (1억 챌린지 검증팀) — 실제 성적으로 달성·파산 확률 · 켈리 · 현실 경로. 결과는 files/growth 에도 저장."""
    from .office import teamjobs
    last = teamjobs.GROWTH.get("last")
    same = last and (last["math"]["start"], last["math"]["target"], last["math"]["days"], last["base_leverage"]) == (start, target, days, lev)
    if same and not fresh and time.time() - last.get("t", 0) < 600:
        return last
    try:
        return teamjobs.growth_run(start, target, days, lev)
    except ValueError as e:
        _bad(e)


@app.get("/api/grid/scan")
def grid_scan(symbols_csv: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,BNBUSDT", interval: str = "1h", levels: int = 12, lev: float = 2.0):
    """박스권 그리드 백테스트 (앞 절반으로 박스, 뒤 절반으로 검증)."""
    from .quant import grid
    try:
        return {"items": grid.scan([symbols.resolve(x) for x in symbols_csv.split(",") if x.strip()][:10], interval, 720, levels, lev)}
    except ValueError as e:
        _bad(e)


@app.get("/api/carry/scan")
def carry_scan(symbols_csv: str = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,BNBUSDT"):
    """펀딩비 차익(현물 롱 + 선물 숏) 점검 — 분석 전용."""
    from .quant import carry
    return {"items": carry.scan([symbols.resolve(x) for x in symbols_csv.split(",") if x.strip()][:12])}


@app.get("/api/oss")
def oss_list():
    """오픈소스 연구팀이 조사한 깃허브 프로젝트와 이 앱에 옮긴 기법."""
    from .knowledge import oss
    return {"items": oss.PROJECTS}


@app.post("/api/office/termind/scan")
def office_termind_scan(symbol: str = "BTCUSDT"):
    from .office import teamjobs
    try:
        return teamjobs.termind_scan(symbols.resolve(symbol))
    except (ValueError, RuntimeError) as e:
        _bad(e)


@app.post("/api/office/models/even")
def office_models_even():
    try:
        return {"models": office.assign_keys_evenly()}
    except ValueError as e:
        _bad(e)


@app.get("/api/office/results")
def office_results():
    from .office import results
    return results.listing()


@app.get("/api/office/results/file")
def office_result_file(path: str):
    from .office import results
    try:
        p = results.safe_path(path)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return FileResponse(p, filename=p.name)


@app.get("/api/office/results/zip")
def office_results_zip():
    from .office import results
    p = results.zip_all()
    return FileResponse(p, filename=p.name, media_type="application/zip")


@app.post("/api/office/results/open")
def office_results_open():
    from .office import results
    try:
        return {"path": results.open_folder()}
    except (ValueError, OSError) as e:
        _bad(e)


# ------------------------------------------------------------------ 실거래 (기본 꺼짐 · 테스트넷 · 사람 승인)
@app.get("/api/live")
def live_view():
    from . import live
    from .office import teamjobs
    return {**live.view(), "items": teamjobs.live_items()}


class LiveSettings(BaseModel):
    enabled: Optional[bool] = None
    testnet: Optional[bool] = None
    max_order_usdt: Optional[float] = None
    max_total_usdt: Optional[float] = None
    max_leverage: Optional[int] = None
    daily_loss_usdt: Optional[float] = None
    confirm: str = ""


@app.post("/api/live/settings")
def live_settings(req: LiveSettings):
    from . import live
    body = {k: v for k, v in req.model_dump().items() if v is not None and k != "confirm"}
    if body.get("enabled") and req.confirm != "실거래 켜기":
        _bad(ValueError("실거래를 켜려면 확인 문구 '실거래 켜기' 를 입력해야 합니다"))
    if body.get("testnet") is False and req.confirm != "실제 돈":
        _bad(ValueError("테스트넷을 끄려면(실제 돈) 확인 문구 '실제 돈' 을 입력해야 합니다"))
    if body.get("enabled") and not all(live.keys()):
        _bad(ValueError("settings.txt 에 BINANCE_API_KEY / BINANCE_API_SECRET 를 넣어야 합니다 (선물 권한만, 출금 권한 금지)"))
    return live.set_settings(body)


@app.post("/api/live/approve/{pid}")
def live_approve(pid: str, ok: bool = True):
    from . import live
    from .office import teamjobs
    if pid.startswith("sb:"):                          # 시나리오 진입 봇 (코인마다) — 가상 성적 기준을 넘었을 때만
        from . import scenbot
        if ok and not scenbot.candidate()["ok"]:
            _bad(ValueError("시나리오 진입 봇이 아직 실거래 기준을 넘지 못했습니다: " + scenbot.candidate()["need"]))
        live.approve(pid, ok)
        if not ok and pid in live._state["positions"] and live.S.get("enabled"):
            try:
                live.close_position(pid, live._state["positions"][pid]["entry"], "승인 취소")
            except Exception as e:  # noqa: BLE001
                live.log(f"⚠ 승인 취소 청산 실패: {e}")
        return live.view()
    p = next((x for x in teamjobs.pipeline() if x["id"] == pid), None)
    if not p or p["stage"] not in ("candidate", "live"):
        _bad(ValueError("데모를 통과한(승인 대기) 매매법만 승인할 수 있습니다"))
    live.approve(pid, ok)
    if not ok and p["stage"] == "live":
        teamjobs._move(p, "candidate", "승인 취소")
        if pid in live._state["positions"] and live.S.get("enabled"):
            try:
                live.close_position(pid, live._state["positions"][pid]["entry"], "승인 취소")
            except Exception as e:  # noqa: BLE001
                live.log(f"⚠ 승인 취소 청산 실패: {e}")
    return live.view()


@app.post("/api/live/kill")
def live_kill():
    from . import live
    live.kill("사용자 비상 정지")
    return live.view()


class MLReq(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "1h"
    model: Literal["logreg", "mlp", "gbs", "dnn", "cnn"] = "logreg"
    horizon: int = 1
    bars: int = 3000
    train_bars: int = 1500
    test_bars: int = 250


@app.post("/api/ml/run")
def ml_run(req: MLReq):
    """머신러닝·딥러닝 방향 예측 — 롤링 재학습 표본 외 평가 (정확도·AUC·보정·단순 매매·특징 중요도·판정)."""
    from .quant import ml
    try:
        c = market.candles(symbols.resolve(req.symbol), req.interval, max(500, min(req.bars, 5000)))[0]
        res = ml.cached(c, model=req.model, horizon=req.horizon, train_bars=req.train_bars, test_bars=req.test_bars)
    except ValueError as e:
        _bad(e)
    out = {k: v for k, v in res.items() if k not in ("prob", "time")}
    out["recent"] = [{"time": t, "prob": p} for t, p in zip(res["time"][-300:], res["prob"][-300:]) if p is not None]
    out["summary"] = ml.text(res)
    out["symbol"], out["interval"] = req.symbol.upper(), req.interval
    return out


@app.get("/api/knowledge")
def knowledge_view(symbol: Optional[str] = None, interval: Optional[str] = None):
    """연구 카드(다른 세션 백테스트 결과) + 이 앱 AI 시그널 성적 학습 메모리."""
    from . import knowledge
    sym = symbol.upper() if symbol else None
    return {"enabled": knowledge.enabled(), "headline": knowledge.HEADLINE, "cards": knowledge.cards(),
            "relevant": [c["id"] for c in knowledge.relevant(sym, interval)], "lessons": knowledge.lessons(wait=True),
            "warnings": knowledge.warnings(interval), "prompt": knowledge.block(sym, interval)}


@app.get("/api/macro")
def macro():
    return sentiment.macro()


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
    return nl_strategy.from_text_safe(text, symbol, interval)


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


@app.get("/api/strategy/library")
def strategy_library(symbol: str = "BTCUSDT", interval: str = "1h"):
    """유명 매매법 모음 (전략 JSON)."""
    return {"items": library.items(symbols.resolve(symbol), interval)}


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


def _manual_off():
    """분석 전용: 수동 모의 주문은 꺼져 있다 (개발·테스트용으로만 MANUAL_PAPER=1)."""
    if not config.MANUAL_PAPER:
        raise HTTPException(410, "분석 전용 앱입니다 — 모의 주문 기능은 없습니다.")


@app.get("/api/paper/account")
def manual_account():
    return paper.manual.snapshot()


@app.post("/api/paper/order")
def manual_order(o: ManualOrder):
    _manual_off()
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
    _manual_off()
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
    _manual_off()
    try:
        res = paper.manual.close(symbol)
    except Exception as e:
        _bad(e)
    paper.save()
    return res


class ReduceReq(BaseModel):
    fraction: float = 0.5


@app.post("/api/paper/reduce/{symbol}")
def manual_reduce(symbol: str, req: ReduceReq):
    """포지션 일부 청산 (fraction 0~1)."""
    _manual_off()
    try:
        res = paper.manual.reduce(symbol.upper(), req.fraction)
    except ValueError as e:
        _bad(e)
    paper.save()
    return res


@app.post("/api/paper/reset")
def manual_reset(req: ResetReq):
    _manual_off()
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
    _manual_off()
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


# ------------------------------------------------------------------ AI 모델 (여러 모델 · 기능별/에이전트별 배정 · 대체 순서)
@app.get("/api/ai")
def ai_settings():
    from .team.roster import ROLES, TEAMS
    return {**ai_routes.view(), "roles_list": [{"id": r.rid, "name": r.name, "team": TEAMS[r.team][0], "tier": r.tier, "emoji": r.emoji} for r in ROLES],
            "defaults": {"nvidia": config.NVIDIA_MODEL, "nvidia_fast": config.NVIDIA_FAST_MODEL, "claude": config.CLAUDE_MODEL}}


@app.get("/api/ai/auto")
def ai_auto_status():
    """AI 자동 모드: 작업별 최근 결과 · 다음 실행 · 설정."""
    return ai_auto.status()


@app.post("/api/ai/auto/settings")
def ai_auto_settings(body: dict):
    try:
        return ai_auto.set_settings(body)
    except (TypeError, ValueError) as e:
        _bad(ValueError(f"설정 값이 잘못됐습니다: {e}"))


@app.post("/api/ai/auto/run/{job}")
def ai_auto_run(job: str):
    """작업 하나를 지금 바로 (결과가 나올 때까지 기다림)."""
    try:
        return ai_auto.run_job(job)
    except ValueError as e:
        _bad(e)
    except Exception as e:
        _bad(ValueError(f"{ai_auto.JOBS.get(job, (job,))[0]} 실패: {str(e)[:200]}"))


@app.post("/api/ai/routes")
def ai_save_routes(body: dict):
    return ai_routes.save(body)


@app.get("/api/ai/catalog")
def ai_catalog(provider: Literal["nvidia", "gemini", "claude"] = "nvidia", refresh: bool = False):
    """이 키로 쓸 수 있는 모델 목록."""
    try:
        if provider == "nvidia":
            from . import nvidia
            return {"provider": provider, "models": nvidia.catalog(refresh), "suggest": ai_routes.nvidia_suggest(),
                    "dead": sorted(nvidia.dead()), "auto": {"nvidia": nvidia.peek_auto(False), "nvidia_fast": nvidia.peek_auto(True)}}
        if provider == "gemini":
            from . import gemini
            return {"provider": provider, "models": ["auto", *gemini.models()]}
        return {"provider": provider, "models": [m for m in (config.CLAUDE_MODEL, config.CLAUDE_FAST_MODEL) if m]}
    except (LLMUnavailable, Exception) as e:
        _bad(ValueError(f"모델 목록을 불러오지 못했습니다: {str(e)[:200]}"))


class AiTest(BaseModel):
    route: str


@app.post("/api/ai/test")
def ai_test(req: AiTest):
    """모델 하나만 짧게 불러 보기 (대체 순서 없이)."""
    if len(ai_routes.split_routes(req.route)) > 1:
        _bad(ValueError("모델 이름 여러 개가 한 칸에 붙어 있습니다 — 'AI 모델' 창을 다시 열면 따로 나뉩니다. 하나씩 테스트하세요."))
    if not ai_routes.valid(req.route):
        _bad(ValueError("'공급자:모델' 형식이 아닙니다 (예: nvidia:auto, nvidia:deepseek-ai/deepseek-v3.1)."))
    if not ai_routes.key_ok(req.route.split(":", 1)[0]):
        _bad(ValueError("이 공급자의 API 키가 없습니다."))
    from . import nvidia
    t0 = time.time()
    tok = nvidia.strict.set(req.route.split(":", 1)[1] not in nvidia.AUTO)   # 이름을 찍은 모델은 대체 없이 그 모델만
    try:
        ans = llm.text("한국어로 한 문장만 답한다.", "코인 선물에서 높은 레버리지가 위험한 이유를 한 문장으로.", max_tokens=300, route=req.route)
        return {"ok": True, "route": req.route, "used": llm.last_used, "answer": ans.strip()[:400], "seconds": round(time.time() - t0, 1)}
    except LLMUnavailable as e:
        return {"ok": False, "route": req.route, "error": str(e)[:400], "seconds": round(time.time() - t0, 1),
                "dead": req.route.startswith("nvidia:") and nvidia.is_dead(req.route.split(":", 1)[1])}
    finally:
        nvidia.strict.reset(tok)


class AiKeys(BaseModel):
    nvidia: Optional[str] = None
    gemini: Optional[str] = None
    anthropic: Optional[str] = None
    provider: Optional[Literal["auto", "claude", "nvidia", "gemini"]] = None
    slot: int = 1                       # 2~9 = 추가 키 (팀·직원마다 다른 키를 쓸 때)


@app.post("/api/ai/keys")
def ai_keys(req: AiKeys):
    """화면에서 키를 넣으면 바로 적용하고 settings.txt 에도 저장 (빈 값은 그대로 둠, '-' 는 지움)."""
    import os
    from pathlib import Path
    from . import keyring
    if not 1 <= req.slot <= keyring.MAX_SLOTS:
        _bad(ValueError("키 번호는 1~9 입니다"))
    changed = {}
    for k, prov in (("nvidia", "nvidia"), ("gemini", "gemini"), ("anthropic", "claude")):
        v = getattr(req, k)
        if v is None or not v.strip():
            continue
        v = "" if v.strip() == "-" else v.strip()
        changed[keyring.set_key(prov, req.slot, v)] = v
    if req.provider:
        config.LLM_PROVIDER = req.provider
        changed["LLM_PROVIDER"] = req.provider
    llm.reset_client()
    from . import gemini, nvidia
    nvidia._catalog, gemini._models = None, None
    saved = False
    path = os.environ.get("SETTINGS_FILE")
    if path and changed:
        p = Path(path)
        try:
            lines = p.read_text(encoding="utf-8-sig").splitlines() if p.exists() else []
            for env, v in changed.items():
                for i, line in enumerate(lines):
                    if line.strip().startswith(env + "="):
                        lines[i] = f"{env}={v}"
                        break
                else:
                    lines.append(f"{env}={v}")
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            saved = True
        except OSError:
            pass
    return {"ok": True, "saved_to_file": saved, "keys": {p: ai_routes.key_ok(p) for p in ai_routes.PROVIDERS}, "primary": ai_routes.primary(),
            "key_slots": keyring.view()}


# ------------------------------------------------------------------ 오토파일럿 (상시: 차트 지표로 매매법 탐색 → 페이퍼 봇 → 시그널)
@app.get("/api/autopilot")
def autopilot_status():
    return autopilot.status()


class ApContext(BaseModel):
    symbol: str
    interval: str
    indicators: list[dict] = []
    watch: list[str] = []


@app.post("/api/autopilot/context")
def autopilot_context(req: ApContext):
    """화면이 지금 차트의 코인·봉·보조지표를 알려준다 (바뀔 때마다)."""
    try:
        sym = symbols.resolve(req.symbol)
    except ValueError as e:
        _bad(e)
    return autopilot.set_context(sym, req.interval, req.indicators, req.watch)


class ApSettings(BaseModel):
    enabled: Optional[bool] = None
    scope: Optional[Literal["chart", "chart+watch", "all"]] = None
    extra_interval: Optional[bool] = None
    max_bots: Optional[int] = None
    search_every_hours: Optional[float] = None
    observe_if_none: Optional[bool] = None
    team_review: Optional[bool] = None
    team_monitor_min: Optional[int] = None
    copilot_every_min: Optional[int] = None
    ai_candidates: Optional[bool] = None
    ai_candidate_targets: Optional[int] = None
    ai_signal_comment: Optional[bool] = None
    leverage: Optional[float] = None
    position_pct: Optional[float] = None


@app.post("/api/autopilot/settings")
def autopilot_settings(req: ApSettings):
    kw = req.model_dump()
    if kw.get("max_bots") is not None:
        kw["max_bots"] = max(0, min(30, kw["max_bots"]))
    if kw.get("search_every_hours") is not None:
        kw["search_every_hours"] = max(1, min(72, kw["search_every_hours"]))
    if kw.get("leverage") is not None:
        kw["leverage"] = max(1, min(50, kw["leverage"]))
    if kw.get("position_pct") is not None:
        kw["position_pct"] = max(1, min(100, kw["position_pct"]))
    return autopilot.set_settings(**kw)


@app.post("/api/autopilot/search")
def autopilot_search():
    return autopilot.search_now()


@app.get("/api/autopilot/signals")
def autopilot_signals(since: int = 0):
    return {"now": int(time.time()), "items": autopilot.recent_signals(since)[:100]}


@app.post("/api/autopilot/retire/{bot_id}")
def autopilot_retire(bot_id: str):
    if bot_id not in autopilot.state["bots"]:
        raise HTTPException(404, "오토파일럿 봇이 아닙니다.")
    autopilot.retire(bot_id, "사람이 정리")
    autopilot.save()
    return {"ok": True}


# ------------------------------------------------------------------ 에이전트 팀 (23명)
@app.get("/api/team/roster")
def team_roster():
    return {"roster": team.roster(), "teams": {k: {"name": v[0], "color": v[1]} for k, v in team.TEAMS.items()},
            "pipelines": {k: {"name": v[0], "flow": v[1], "stages": [list(s) for s in v[2]]} for k, v in team.PIPELINES.items()},
            "engine": llm.provider() or "rules", "settings": team.settings, "plan": team._state.get("plan"),
            "knowledge": {k: v[-20:] for k, v in team.knowledge().items()}}


class TeamRunReq(BaseModel):
    pipeline: Literal["morning", "evening", "weekly", "emergency", "briefing"]


@app.post("/api/team/run")
def team_run(req: TeamRunReq):
    if any(r.status == "running" for r in team.runs.values()):
        _bad(ValueError("이미 진행 중인 회의가 있습니다. 끝난 뒤에 다시 시작하세요."))
    return team.run_pipeline(req.pipeline).view()


@app.post("/api/team/chat")
def team_chat():
    return team.open_chat().view()


@app.get("/api/team/runs")
def team_runs():
    return {"items": [{"id": r.id, "title": r.title, "pipeline": r.pipeline, "status": r.status, "trigger": r.trigger,
                       "started": r.started, "messages": len(r.messages)} for r in sorted(team.runs.values(), key=lambda x: -x.started)][:40]}


@app.get("/api/team/runs/{run_id}")
def team_run_view(run_id: str, since: int = 0):
    r = team.runs.get(run_id)
    if not r:
        raise HTTPException(404, "대화방이 없습니다.")
    return r.view(max(0, since))


class SayReq(BaseModel):
    text: str


@app.post("/api/team/runs/{run_id}/say")
def team_say(run_id: str, req: SayReq):
    if not req.text.strip():
        _bad(ValueError("메시지를 입력하세요."))
    try:
        return team.human_say(run_id, req.text.strip()[:1000])
    except ValueError as e:
        _bad(e)


class TeamSettings(BaseModel):
    coins: Optional[list[str]] = None
    auto: Optional[dict] = None
    times: Optional[dict] = None
    bot_gate: Optional[bool] = None
    daily_call_limit: Optional[int] = None
    rules: Optional[dict] = None


@app.post("/api/team/settings")
def team_settings(req: TeamSettings):
    kw = req.model_dump()
    if kw.get("coins"):
        kw["coins"] = list(dict.fromkeys(symbols.resolve(s) for s in kw["coins"] if s.strip()))[:8]
    return team.save_settings(**kw)


class ApplyReq(BaseModel):
    kind: Literal["pause_all", "pause_bot", "resume_bot", "candidate", "hypothesis"]
    target: Optional[str] = None
    run_id: Optional[str] = None
    candidate: Optional[str] = None
    force: bool = False                 # 승인 안 된 가설도 관찰 봇으로 시험
    rule: Optional[str] = None
    symbol: Optional[str] = None
    interval: Optional[str] = None
    name: Optional[str] = None


@app.post("/api/team/apply")
def team_apply(req: ApplyReq):
    """사람이 최종 권한으로 적용 (리스크 조치 · 승인된 후보)."""
    try:
        return team.apply(req.kind, target=req.target, run_id=req.run_id, candidate=req.candidate, force=req.force,
                          rule=req.rule, symbol=req.symbol, interval=req.interval, name=req.name)
    except (ValueError, LLMUnavailable) as e:
        _bad(e)
    except Exception as e:                  # 예상 못 한 오류도 이유를 보여 준다
        _bad(ValueError(f"적용 실패: {type(e).__name__}: {str(e)[:200]}"))


# ------------------------------------------------------------------ 실시간 AI 상황 분석
@app.get("/api/copilot")
def copilot_live(symbol: str = "BTCUSDT", interval: str = "15m", force: bool = False, max_age: int = 300, ai: bool = True):
    """지금 시장 상황 + 내 포지션을 AI(키 없으면 규칙)가 분석. 새 봉·가격 급변·포지션 변경·새 경고·max_age 초 경과 때만 다시 분석."""
    try:
        return copilot.live(symbols.resolve(symbol), interval, force, max(60, min(max_age, 3600)), ai)
    except ValueError as e:
        _bad(e)


class AskReq(BaseModel):
    symbol: str = "BTCUSDT"
    interval: str = "15m"
    question: str
    history: list[dict] = []


@app.post("/api/copilot/ask")
def copilot_ask(req: AskReq):
    """지금 상황에 대해 AI 에게 질문."""
    if not req.question.strip():
        _bad(ValueError("질문을 입력하세요."))
    try:
        return copilot.ask(symbols.resolve(req.symbol), req.interval, req.question.strip()[:1000], req.history)
    except ValueError as e:
        _bad(e)


@app.get("/api/copilot/alerts")
def copilot_alerts(since: int = 0):
    """포지션 감시 경고 (손절·청산가 근접, 손절 미설정, 반대 판단·신호 …)."""
    return {"now": int(time.time()), "items": copilot.recent_alerts(since), "settings": copilot.SETTINGS}


class CopilotCfg(BaseModel):
    watch: Optional[bool] = None
    auto_ai: Optional[bool] = None
    interval: Optional[str] = None


@app.get("/api/copilot/signals")
def copilot_signals(symbol: Optional[str] = None, interval: Optional[str] = None, limit: int = 60):
    """AI 진입 시그널 (차트 'AI 시그널' 표시) + 결과(진입 대기·미체결·진행 중·익절·손절)와 적중률."""
    try:
        sym = symbols.resolve(symbol) if symbol else None
    except ValueError as e:
        _bad(e)
    return copilot.signals_for(sym, interval, max(1, min(limit, 300)))


@app.get("/api/aibot")
def aibot_view(symbol: Optional[str] = None, interval: Optional[str] = None):
    """AI 봇: AI 진입 시그널을 따라 모의 매매한 거래·포지션·수익률 (symbol 을 주면 그 코인만)."""
    from . import aibot
    try:
        sym = symbols.resolve(symbol) if symbol else None
    except ValueError as e:
        _bad(e)
    return aibot.view(sym, interval)


@app.post("/api/aibot/settings")
def aibot_settings(body: dict):
    from . import aibot
    try:
        return aibot.set_settings(body)
    except (TypeError, ValueError) as e:
        _bad(ValueError(f"설정 값이 잘못됐습니다: {e}"))


@app.post("/api/copilot/config")
def copilot_config(cfg: CopilotCfg):
    out = copilot.set_settings(**cfg.model_dump())
    if cfg.auto_ai is not None:                  # 'AI 자동 모드'의 포지션 위험 AI 설정과 같은 것
        ai_auto.SETTINGS["positions"] = bool(cfg.auto_ai)
        ai_auto.save()
    return out


@app.post("/api/copilot/watch")
def copilot_watch_now():
    return {"new": copilot.watch_once(), "items": copilot.recent_alerts(0)[:20]}


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


# 앱 창(설치형 웹앱): 브라우저 탭이 아니라 따로 된 창 · 바탕화면/시작 메뉴 아이콘
@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(config.FRONTEND_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(config.FRONTEND_DIR / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})
