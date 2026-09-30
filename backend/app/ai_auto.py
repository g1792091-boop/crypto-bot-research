"""AI 자동 모드 — 사람이 누르지 않아도 AI 가 앱의 기능들을 스스로 돌려 보고, 결과를 각 화면 카드와 알림으로 보여준다.

작업 (각각 켜고 끄기 · 간격 조절. AI 키가 없거나 하루 호출 상한을 넘으면 규칙 분석으로 대신):
  trade   : 차트 실시간 AI — 화면의 차트 코인·봉을 계속 분석 (새 봉·가격 급변·포지션 변경·최대 간격 때만 AI 호출).
            판단(롱/숏/중립)이 바뀌면 알림. 트레이드 화면의 'AI' 탭을 열지 않아도 돈다.
  market  : 마켓 브리핑 — 코인별 장세 · 공포·탐욕 · 도미넌스 · 펀딩·미결제약정·호가 · 뉴스 · 경제 일정 → 지금 시장 한 장 요약
  risk    : 포트폴리오 리스크 — 모의 계좌 + 봇 포지션 · VaR · BTC 급락 스트레스 · 노출 · 낙폭 → 위험 점검과 할 일
  bots    : 봇 코치 — 페이퍼 봇 성과를 보고 유지/주의/멈춤 권고. 거래가 쌓였는데 성과가 나쁜 봇은
            코드 관문(검증 구간에서 나아질 때만)으로 스스로 개선. '자동 멈춤'을 켜면 낙폭 큰 봇을 멈춘다 (코드 규칙).
  scanner : 스캐너 시그널 코멘트 — 강한 시그널(강도 2 이상)에 AI 가 근거·주의점 한 줄을 붙인다.
  (포지션 위험 경고가 뜨면 AI 분석을 붙이는 것은 copilot.SETTINGS["auto_ai"] — 'positions' 설정으로 켠다)

AI 는 판단·설명만 한다. 실제로 바뀌는 것은 모의(페이퍼) 봇의 코드 관문 통과 개선과, 켰을 때의 낙폭 규칙 멈춤뿐이다.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from . import config, llm

JOBS = {
    "trade": ("차트 실시간 AI", "화면 차트 코인·봉을 계속 분석하고 판단이 바뀌면 알림"),
    "market": ("마켓 브리핑", "장세·심리·펀딩·호가·뉴스·일정으로 지금 시장 요약"),
    "risk": ("포트폴리오 리스크", "모의 계좌 + 봇 포지션의 위험 점검과 할 일"),
    "bots": ("봇 코치", "페이퍼 봇 성과 점검 · 성과 나쁜 봇 코드 관문 개선"),
    "scanner": ("스캐너 시그널 코멘트", "강한 시그널마다 AI 근거·주의점 한 줄"),
}
SETTINGS = {
    "enabled": True,
    "every_min": {"trade": 3, "market": 30, "risk": 30, "bots": 120, "scanner": 1},   # 0 = 그 작업 끔
    "positions": True,             # 포지션 위험 경고가 뜨면 AI 분석을 붙임
    "bots_auto_improve": True,     # 거래 10건 이상 · 성과 나쁜 봇을 코드 관문 개선 (하루 한 번)
    "bots_auto_pause": False,      # 낙폭 35% 넘는 페이퍼 봇 자동 멈춤 (코드 규칙)
    "notify": True,                # 판단 변경·위험 수준 상승을 알림(오토파일럿 시그널)으로
    "daily_limit": 400,            # 이 모드가 하루에 부르는 AI 호출 상한 (넘으면 규칙 분석)
}
LEVELS = ("ok", "caution", "danger")

_paper = None
_lock = threading.RLock()
state: dict = {"insights": {}, "last": {}, "running": {}, "errors": {}, "calls": {"day": "", "n": 0},
               "scanner_seen": 0, "improved": {}, "bias": {}}
feed: deque[dict] = deque(maxlen=200)


class Insight(BaseModel):
    headline: str = Field(description="한 줄 요약 (60자 이내, 한국어)")
    level: Literal["ok", "caution", "danger"] = Field(description="ok=평소 · caution=주의 · danger=바로 볼 것")
    bias: Literal["long", "short", "neutral"] = Field("neutral", description="시장 방향 판단 (해당 없으면 neutral)")
    points: list[str] = Field(default_factory=list, description="근거 3~5개. 입력에 있는 숫자를 인용한다")
    actions: list[str] = Field(default_factory=list, description="지금 할 일 0~3개 (구체적으로)")
    watch: list[str] = Field(default_factory=list, description="앞으로 지켜볼 것 0~3개")


COMMON = ("너는 코인 선물 트레이더를 돕는 분석가다. 입력 JSON 에 있는 숫자·사실만 근거로 쓰고 지어내지 않는다. "
          "데이터가 없거나 오류인 항목은 무시하고, 확실하지 않으면 caution 으로 둔다. 모든 문장은 짧은 한국어. "
          "투자 조언이 아니라 모의 매매를 위한 참고 의견이다.")
PROMPTS = {
    "market": COMMON + " 지금 코인 시장을 한 장으로 요약한다: 코인별 장세(1h·4h·1d), 공포·탐욕, 도미넌스, 펀딩비·미결제약정·"
              "호가 쏠림, 뉴스 헤드라인, 가까운 경제 일정. bias 는 BTC 기준 방향. 큰 일정 직전·펀딩 과열·급변은 caution/danger.",
    "risk": COMMON + " 모의 계좌와 페이퍼 봇들의 포지션 위험을 점검한다: 청산가까지 거리, 손절 없는 포지션, 레버리지, 같은 방향 쏠림, "
            "VaR·BTC 급락 스트레스 손실, 계좌 낙폭. actions 에는 줄일 것·손절 둘 곳처럼 구체적인 조치를 쓴다. "
            "포지션이 없으면 level=ok 로 짧게.",
    "bots": COMMON + " 페이퍼 봇들의 성과(거래 수·승률·손익비·수익률·낙폭·최근 로그)를 보고 어떤 봇을 유지·주의·멈춤 할지 권고한다. "
            "거래가 20건 미만이면 판단을 미룬다(표본 부족). auto_actions 는 코드가 이미 한 일이니 그대로 요약에 포함한다.",
}


# ---------------------------------------------------------------- 공통
def bind(paper_manager) -> None:
    global _paper
    _paper = paper_manager
    saved = _load()
    for k, v in (saved.get("settings") or {}).items():
        if k == "every_min" and isinstance(v, dict):
            SETTINGS["every_min"].update({j: int(x) for j, x in v.items() if j in JOBS})
        elif k in SETTINGS:
            SETTINGS[k] = v
    state["insights"].update(saved.get("insights") or {})
    state["last"].update(saved.get("last") or {})
    _sync_positions()


def _path():
    return config.STATE_DIR / "ai_auto.json"


def _load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save() -> None:
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps({"settings": SETTINGS, "insights": state["insights"], "last": state["last"]},
                                      ensure_ascii=False, default=str), encoding="utf-8")
    except OSError:
        pass


def _sync_positions() -> None:
    from .quant import copilot
    copilot.SETTINGS["auto_ai"] = bool(SETTINGS["enabled"] and SETTINGS["positions"])


def set_settings(body: dict) -> dict:
    for k, v in body.items():
        if k == "every_min" and isinstance(v, dict):
            for j, x in v.items():
                if j in JOBS:
                    SETTINGS["every_min"][j] = max(0, min(int(x), 24 * 60))
        elif k == "daily_limit":
            SETTINGS[k] = max(0, min(int(v), 5000))
        elif k in SETTINGS and isinstance(SETTINGS[k], bool):
            SETTINGS[k] = bool(v)
    _sync_positions()
    save()
    return SETTINGS


def _budget_ok() -> bool:
    day = datetime.now().strftime("%Y-%m-%d")
    c = state["calls"]
    if c["day"] != day:
        c.update(day=day, n=0)
    return c["n"] < SETTINGS["daily_limit"]


def _spend() -> None:
    _budget_ok()
    state["calls"]["n"] += 1


def _notify(job: str, text: str, symbol: str = "", interval: str = "", level: str = "caution") -> None:
    item = {"created": int(time.time()), "job": job, "title": JOBS[job][0], "text": text, "level": level, "symbol": symbol}
    feed.appendleft(item)
    if not SETTINGS["notify"]:
        return
    try:
        from . import autopilot
        autopilot._signal({"type": "ai_auto", "symbol": symbol, "interval": interval, "status": "ai", "strategy": f"AI 자동 · {JOBS[job][0]}",
                           "text": text[:160]})
    except Exception:
        pass


def _coins() -> list[str]:
    from . import autopilot
    c = autopilot.context
    out = [c.get("symbol") or "BTCUSDT", "BTCUSDT", "ETHUSDT", *(c.get("watch") or [])]
    if _paper is not None:
        out += list(_paper.manual.positions)
    return list(dict.fromkeys(s for s in out if s))[:4]


def _ask(job: str, ctx: dict) -> tuple[Insight, str, str | None]:
    """AI 로 Insight 를 만든다 → (insight, 답한 모델 or 'rules', AI 실패 이유)."""
    err = None
    if config.llm_enabled() and _budget_ok():
        try:
            _spend()
            llm.last_used = None
            ins = llm.parse(PROMPTS[job], json.dumps(ctx, ensure_ascii=False, default=str)[:24000], Insight,
                            effort="low", max_tokens=2500, feature="auto")
            return _clip(ins), llm.last_used or llm.provider() or "ai", None
        except Exception as e:
            err = f"AI 실패 → 규칙 분석: {str(e)[:160]}"
    elif config.llm_enabled():
        err = f"오늘 AI 호출 상한({SETTINGS['daily_limit']}회)에 도달 → 규칙 분석"
    return _clip(RULES[job](ctx)), "rules", err


def _clip(ins: Insight) -> Insight:
    return ins.model_copy(update={"headline": ins.headline.strip()[:90], "points": [p for p in ins.points if p.strip()][:6],
                                  "actions": [p for p in ins.actions if p.strip()][:4], "watch": [p for p in ins.watch if p.strip()][:4]})


def _store(job: str, ins: Insight, engine: str, err: str | None, extra: dict | None = None) -> dict:
    prev = state["insights"].get(job)
    row = {**ins.model_dump(), "job": job, "title": JOBS[job][0], "at": int(time.time()), "engine": engine, "error": err, **(extra or {})}
    state["insights"][job] = row
    if prev and LEVELS.index(row["level"]) > LEVELS.index(prev.get("level", "ok")) and row["level"] != "ok":
        _notify(job, f"{'⚠ ' if row['level'] == 'danger' else ''}{row['headline']}", level=row["level"])
    return row


# ---------------------------------------------------------------- 작업: 차트 실시간 AI
def job_trade() -> dict:
    from . import autopilot
    from .quant import copilot
    sym, iv = autopilot.context.get("symbol") or "BTCUSDT", autopilot.context.get("interval") or "1h"
    before = (copilot._state.get((sym, iv)) or {}).get("time")
    r = copilot.live(sym, iv, max_age=max(60, SETTINGS["every_min"]["trade"] * 60), use_ai=_budget_ok())
    if r["analyzed_at"] != (int(before) if before else None) and r["engine"] != "rules":
        _spend()
    a = r["analysis"]
    key = f"{sym}:{iv}"
    prev = state["bias"].get(key)
    state["bias"][key] = a["bias"]
    name = {"long": "롱 우위", "short": "숏 우위", "neutral": "중립"}
    if prev and prev != a["bias"]:
        _notify("trade", f"AI 판단 변경: {name[prev]} → {name[a['bias']]} (확신 {a['confidence']}%) — {a['headline'][:90]}", sym, iv, "caution")
    urgent = [x for x in a.get("position_advice", []) if x.get("urgency") == "high"]
    lvl = "danger" if urgent or any(x["level"] == "high" for x in r["alerts"]) else "caution" if r["alerts"] else "ok"
    row = {"headline": a["headline"], "level": lvl, "bias": a["bias"], "points": [a["situation"]][:1] + a.get("risks", [])[:3],
           "actions": [f"{x['target']}: {x['reason']}" for x in urgent][:3], "watch": a.get("watch", [])[:3],
           "job": "trade", "title": JOBS["trade"][0], "at": r["analyzed_at"], "engine": r["engine"] if r["engine"] == "rules" else f"{r['engine']}:{r.get('model') or ''}",
           "error": r.get("error"), "symbol": sym, "interval": iv, "confidence": a["confidence"], "price": r["price"]}
    state["insights"]["trade"] = row
    return row


# ---------------------------------------------------------------- 작업: 마켓 브리핑
def ctx_market() -> dict:
    from .team import packets
    coins = _coins()
    ctx = {"now_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "coins": coins, "data_source": config.DATA_SOURCE}
    for k, fn in (("market", lambda: packets.market_section(coins)), ("flow", lambda: packets.flow_section(coins)),
                  ("macro", lambda: packets.macro_section(coins)), ("news", packets.news_section)):
        try:
            ctx[k] = fn()
        except Exception as e:
            ctx[k] = {"error": str(e)[:100]}
    return ctx


def rules_market(ctx: dict) -> Insight:
    pts, acts, watch = [], [], []
    score = 0.0
    for s, m in (ctx.get("market") or {}).items():
        if not isinstance(m, dict) or "regime" not in m:
            continue
        r = m["regime"]
        sc = sum((r.get(iv) or {}).get("score", 0) or 0 for iv in ("1h", "4h", "1d"))
        if s == "BTCUSDT":
            score = sc
        lab = " · ".join(f"{iv} {(r.get(iv) or {}).get('label', '-')}" for iv in ("1h", "4h", "1d") if r.get(iv))
        pts.append(f"{s.replace('USDT', '')} {m.get('change_24h_pct', 0):+.2f}% (24h) — {lab}")
    fg = ((ctx.get("macro") or {}).get("fear_greed") or {})
    if fg.get("value") is not None:
        pts.append(f"공포·탐욕 {fg['value']} ({fg.get('label') or '-'})")
        if int(fg["value"]) >= 80 or int(fg["value"]) <= 20:
            watch.append("심리가 극단 — 반대 방향 급변 주의")
    lvl = "ok"
    for s, f in (ctx.get("flow") or {}).items():
        fr = f.get("funding_pct") if isinstance(f, dict) else None
        if isinstance(fr, (int, float)) and abs(fr) >= 0.05:
            lvl = "caution"
            pts.append(f"{s.replace('USDT', '')} 펀딩비 {fr:+.3f}% — {'롱' if fr > 0 else '숏'} 과열")
    ev = [e for e in ((ctx.get("news") or {}).get("events") or []) if (e.get("in_hours") or 99) <= 6]
    if ev:
        lvl = "caution"
        acts.append(f"{ev[0]['title']} {ev[0]['in_hours']:.1f}시간 뒤 — 발표 전후 레버리지 줄이기")
    bias = "long" if score >= 2 else "short" if score <= -2 else "neutral"
    head = {"long": "BTC 여러 봉에서 상승 우위", "short": "BTC 여러 봉에서 하락 우위", "neutral": "BTC 방향 엇갈림 — 박스·관망 구간"}[bias]
    return Insight(headline=head, level=lvl, bias=bias, points=pts[:5], actions=acts, watch=watch)


# ---------------------------------------------------------------- 작업: 포트폴리오 리스크
def _positions_flat() -> list[dict]:
    pos = []
    if _paper is None:
        return pos
    for p in _paper.manual.snapshot()["positions"]:
        pos.append({"symbol": p["symbol"], "side": p["side"], "notional": p["qty"] * p["mark_price"], "leverage": p["leverage"], "who": "수동"})
    for b in _paper.bots.values():
        p = b.sim.position
        if p is not None:
            pos.append({"symbol": b.spec.symbol, "side": "long" if p.side == 1 else "short", "leverage": p.leverage,
                        "notional": p.qty * (b.last_price or p.entry_price), "who": f"봇 {b.spec.name}"})
    return pos


def ctx_risk() -> dict:
    from .quant import copilot, portfolio, risk
    from .team import packets
    ctx: dict = {}
    try:
        ctx["positions_detail"] = copilot.positions()
    except Exception as e:
        ctx["positions_detail"] = {"error": str(e)[:100]}
    flat = _positions_flat()
    ctx["positions"] = flat
    if flat:
        try:
            r = risk.portfolio(flat, "1d", shock_pct=-10.0)
            ctx["portfolio_risk"] = {k: v for k, v in r.items() if not isinstance(v, list) or len(v) <= 12}
        except Exception as e:
            ctx["portfolio_risk"] = {"error": str(e)[:100]}
        try:
            ctx["exposure"] = portfolio.exposures(flat)
        except Exception as e:
            ctx["exposure"] = {"error": str(e)[:100]}
    try:
        b = packets.book_section(_paper, whatif=False)
        ctx["account"] = {k: b[k] for k in ("equity", "initial_equity", "return_pct", "max_drawdown_pct", "free_margin", "today", "week")}
    except Exception:
        pass
    ctx["recent_alerts"] = [a["text"] for a in list(copilot.alerts_feed)[-8:] if time.time() - a["created"] < 3600]
    return ctx


def rules_risk(ctx: dict) -> Insight:
    det = ctx.get("positions_detail") if isinstance(ctx.get("positions_detail"), list) else []
    if not det:
        return Insight(headline="열린 포지션 없음 — 위험 노출 없음", level="ok", points=["모의 계좌와 봇에 열린 포지션이 없습니다."])
    pts, acts, lvl = [], [], "ok"
    for p in det:
        who = "내" if p.get("kind") == "manual" else p.get("target", "봇")
        pts.append(f"{who} {p['symbol'].replace('USDT', '')} {'롱' if p['side'] == 'long' else '숏'} {p['leverage']}x · ROE {p.get('roe_pct', 0):+.1f}% · 청산까지 {p.get('to_liq_pct', 0):.1f}%")
        if not p.get("stop"):
            lvl = max(lvl, "caution", key=LEVELS.index)
            acts.append(f"{p['symbol'].replace('USDT', '')} 손절 없음 — 손절 가격부터 정하기")
        if abs(p.get("to_liq_pct") or 99) < 5:
            lvl = "danger"
            acts.append(f"{p['symbol'].replace('USDT', '')} 청산가까지 {abs(p['to_liq_pct']):.1f}% — 포지션 줄이기")
    sides = {p["side"] for p in det}
    if len(det) >= 3 and len(sides) == 1:
        lvl = max(lvl, "caution", key=LEVELS.index)
        pts.append(f"포지션 {len(det)}개가 모두 {'롱' if 'long' in sides else '숏'} — 한 방향 쏠림")
    shock = (ctx.get("portfolio_risk") or {}).get("stress_pnl")
    if isinstance(shock, (int, float)):
        pts.append(f"BTC -10% 급락 가정 손익 약 {shock:+.0f}")
    head = {"ok": f"포지션 {len(det)}개 · 큰 위험 없음", "caution": f"포지션 {len(det)}개 · 주의할 점 있음", "danger": "청산 위험 포지션 있음 — 바로 확인"}[lvl]
    return Insight(headline=head, level=lvl, points=pts[:6], actions=acts[:3])


# ---------------------------------------------------------------- 작업: 봇 코치
def _bot_actions() -> list[str]:
    """코드 규칙으로 하는 일: 성과 나쁜 봇 관문 개선(하루 한 번) · 낙폭 큰 봇 멈춤(켰을 때)."""
    from .team import packets
    done = []
    if _paper is None:
        return done
    rows = packets.bots_section(_paper)
    now = time.time()
    for name, r in rows.items():
        b = _paper.bots.get(r["id"])
        if not b or not b.running:
            continue
        if SETTINGS["bots_auto_pause"] and (r.get("max_drawdown_pct") or 0) >= 35:
            b.running = False
            b._log("AI 자동 모드: 낙폭 35% 이상이라 멈춤 (코드 규칙)")
            done.append(f"{name}: 낙폭 {r['max_drawdown_pct']:.0f}% → 멈춤")
            continue
        pf = r.get("profit_factor")
        net = sum(t.pnl for t in b.sim.trades)
        bad = len(b.sim.trades) >= 10 and (net < 0 or (pf is not None and pf < 1))
        if SETTINGS["bots_auto_improve"] and bad and now - state["improved"].get(b.id, 0) > 86400:
            state["improved"][b.id] = now
            try:
                rep = b.maybe_improve(force=True)
                done.append(f"{name}: " + ("관문 통과 개선 적용 — " + " / ".join(rep["changes"])[:120] if rep and rep.get("applied")
                                           else "개선 검토 — 검증 구간에서 나아지는 변경 없음, 유지"))
            except Exception as e:
                done.append(f"{name}: 개선 실패 ({str(e)[:60]})")
    if done:
        _paper.save()
    return done


def ctx_bots() -> dict:
    from .team import packets
    auto = _bot_actions()
    ctx = {"bots": packets.bots_section(_paper) if _paper is not None else {}, "auto_actions": auto}
    try:
        from . import autopilot
        ctx["autopilot_bots"] = {m["rule"]: m["kind"] for m in autopilot._ap_bots().values()}
    except Exception:
        pass
    return ctx


def rules_bots(ctx: dict) -> Insight:
    bots = ctx.get("bots") or {}
    if not bots:
        return Insight(headline="돌고 있는 페이퍼 봇 없음", level="ok", points=["전략 · 백테스트나 오토파일럿에서 봇을 시작하면 여기서 점검합니다."],
                       actions=list(ctx.get("auto_actions") or []))
    pts, acts, lvl = [], list(ctx.get("auto_actions") or []), "ok"
    for n, b in sorted(bots.items(), key=lambda kv: -(kv[1].get("return_pct") or 0)):
        tag = "표본 부족" if (b.get("trades") or 0) < 20 else ("양호" if (b.get("return_pct") or 0) > 0 else "부진")
        pts.append(f"{n}: {b.get('trades', 0)}건 · 수익 {b.get('return_pct') or 0:+.2f}% · 낙폭 {b.get('max_drawdown_pct') or 0:.1f}% ({tag})")
        if (b.get("max_drawdown_pct") or 0) >= 25 and b.get("running"):
            lvl = "caution"
            acts.append(f"{n}: 낙폭 {b['max_drawdown_pct']:.0f}% — 멈춤 검토")
    good = sum((b.get("return_pct") or 0) > 0 for b in bots.values())
    return Insight(headline=f"봇 {len(bots)}개 중 {good}개 수익 중", level=lvl, points=pts[:6], actions=acts[:4])


RULES = {"market": rules_market, "risk": rules_risk, "bots": rules_bots}
CTX = {"market": ctx_market, "risk": ctx_risk, "bots": ctx_bots}


def job_insight(job: str) -> dict:
    ctx = CTX[job]()
    ins, engine, err = _ask(job, ctx)
    extra = {"auto_actions": ctx.get("auto_actions")} if job == "bots" else {}
    if job == "bots" and ctx.get("auto_actions"):
        _notify("bots", "봇 코치: " + " · ".join(ctx["auto_actions"])[:150], level="caution")
    return _store(job, ins, engine, err, extra)


# ---------------------------------------------------------------- 작업: 스캐너 시그널 코멘트
def job_scanner() -> dict:
    from .quant.scanner import scanner
    since = state["scanner_seen"] or int(time.time()) - 600
    new = [s for s in scanner.recent(since, 50) if s.get("strength", 1) >= 2 and not s.get("ai")]
    state["scanner_seen"] = max([since] + [s["created"] for s in scanner.recent(since, 200)])
    done = 0
    for s in new[:2]:                              # 한 번에 2개까지 (한도 보호)
        if not (config.llm_enabled() and _budget_ok()):
            break
        try:
            _spend()
            from .quant import copilot
            lt = copilot.light(s["symbol"], s["interval"])
            user = json.dumps({"signal": {k: s.get(k) for k in ("symbol", "interval", "label", "dir", "strength", "text", "price")},
                               "regime": lt["regime"], "atr_pct": round(lt["atr_pct"], 3), "price_now": lt["price"],
                               "derivatives": copilot._deriv(s["symbol"])}, ensure_ascii=False, default=str)
            s["ai"] = llm.text("너는 코인 선물 트레이더를 돕는 분석가다. 스캐너가 방금 낸 시그널을 주어진 데이터만으로 평가한다. "
                               "이 시그널을 믿을 근거 한 가지와 가장 큰 위험 한 가지를 한국어 두 문장 이내로. 숫자를 지어내지 않는다.",
                               user, effort="low", max_tokens=300, feature="auto").strip()[:300]
            done += 1
        except Exception as e:
            state["errors"]["scanner"] = str(e)[:160]
            break
    row = state["insights"].get("scanner") or {}
    if done:
        row = {"job": "scanner", "title": JOBS["scanner"][0], "at": int(time.time()), "engine": llm.last_used or "ai", "level": "ok",
               "headline": f"강한 시그널 {done}개에 AI 코멘트", "bias": "neutral", "points": [f"{s['symbol'].replace('USDT', '')} {s['interval']} {s['label']}: {s['ai']}" for s in new[:done]],
               "actions": [], "watch": [], "error": None}
        state["insights"]["scanner"] = row
    return row


# ---------------------------------------------------------------- 스케줄러
def run_job(job: str) -> dict:
    if job not in JOBS:
        raise ValueError(f"알 수 없는 작업: {job}")
    with _lock:
        if state["running"].get(job):
            return state["insights"].get(job) or {}
        state["running"][job] = True
    try:
        row = job_trade() if job == "trade" else job_scanner() if job == "scanner" else job_insight(job)
        state["errors"].pop(job, None)
        return row
    except Exception as e:
        state["errors"][job] = str(e)[:200]
        raise
    finally:
        state["last"][job] = time.time()
        state["running"][job] = False
        save()


def due(now: float | None = None) -> list[str]:
    now = now or time.time()
    if not SETTINGS["enabled"]:
        return []
    return [j for j, m in SETTINGS["every_min"].items() if m and not state["running"].get(j) and now - state["last"].get(j, 0) >= m * 60]


def tick() -> list[str]:
    started = due()
    for j in started:
        threading.Thread(target=_safe, args=(j,), daemon=True).start()
    return started


def _safe(job: str) -> None:
    try:
        run_job(job)
    except Exception:
        pass


def trade_active() -> bool:
    """오토파일럿의 실시간 AI 감시와 겹치지 않게 (이 모드가 켜져 있으면 이쪽이 맡는다)."""
    return bool(SETTINGS["enabled"] and SETTINGS["every_min"].get("trade"))


def status() -> dict:
    _budget_ok()
    now = time.time()
    jobs = {}
    for j, (title, desc) in JOBS.items():
        m = SETTINGS["every_min"].get(j, 0)
        last = state["last"].get(j)
        jobs[j] = {"title": title, "desc": desc, "every_min": m, "last": last, "running": bool(state["running"].get(j)),
                   "next": (last or now) + m * 60 if m and SETTINGS["enabled"] else None, "error": state["errors"].get(j),
                   "insight": state["insights"].get(j)}
    return {"settings": SETTINGS, "jobs": jobs, "calls_today": state["calls"]["n"], "llm": config.llm_enabled(),
            "feed": list(feed)[:30], "now": int(now)}


async def run_forever():
    await asyncio.sleep(8)
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:
            pass
        await asyncio.sleep(15)


_task = None


def start():
    global _task
    if _task is None:
        _task = asyncio.create_task(run_forever())
