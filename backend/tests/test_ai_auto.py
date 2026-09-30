"""AI 자동 모드: 키 없이 규칙 분석 · 가짜 AI 응답 · 하루 상한 · 스캐너 코멘트 · 봇 코치 자동 개선 · 설정 · 오토파일럿과 겹치지 않기."""
import time

import pytest
from fastapi.testclient import TestClient

from app import ai_auto, autopilot, config, llm
from app.main import app, paper
from app.quant.scanner import scanner

c = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    saved = {k: (dict(v) if isinstance(v, dict) else v) for k, v in ai_auto.SETTINGS.items()}
    ai_auto.state["calls"] = {"day": "", "n": 0}
    ai_auto.state["running"].clear()
    yield
    ai_auto.SETTINGS.update(saved)


def test_rules_without_key():
    for job in ("trade", "market", "risk", "bots"):
        r = c.post(f"/api/ai/auto/run/{job}").json()
        assert r["headline"] and r["level"] in ai_auto.LEVELS and r["job"] == job, r
        assert r["engine"] == "rules"
    s = c.get("/api/ai/auto").json()
    assert set(s["jobs"]) == set(ai_auto.JOBS) and all(s["jobs"][j]["insight"] for j in ("market", "risk", "bots"))
    assert c.post("/api/ai/auto/run/nope").status_code == 400


def test_ai_insight_and_daily_limit(monkeypatch):
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    seen = []

    def fake_parse(system, user, schema, **kw):
        seen.append(kw.get("feature"))
        llm.last_used = "nvidia:some/model"
        return schema(headline="AI 브리핑", level="caution", bias="long", points=["근거 " + str(i) for i in range(9)], actions=["할 일"], watch=[])
    monkeypatch.setattr(llm, "parse", fake_parse)
    r = ai_auto.run_job("market")
    assert r["headline"] == "AI 브리핑" and r["engine"] == "nvidia:some/model" and len(r["points"]) == 6 and seen == ["auto"]
    ai_auto.SETTINGS["daily_limit"] = 1                      # 이미 1회 씀 → 상한 → 규칙 분석
    r = ai_auto.run_job("risk")
    assert r["engine"] == "rules" and "상한" in r["error"]

    def boom(*a, **k):
        raise llm.LLMUnavailable("한도")
    monkeypatch.setattr(llm, "parse", boom)
    ai_auto.SETTINGS["daily_limit"] = 100
    r = ai_auto.run_job("bots")
    assert r["engine"] == "rules" and "AI 실패" in r["error"]


def test_level_rise_notifies(monkeypatch):
    ai_auto.state["insights"]["risk"] = {"level": "ok", "headline": "평소"}
    monkeypatch.setattr(ai_auto, "RULES", {**ai_auto.RULES, "risk": lambda ctx: ai_auto.Insight(headline="청산 위험", level="danger")})
    n = len(autopilot.signals)
    ai_auto.run_job("risk")
    assert len(autopilot.signals) == n + 1 and autopilot.signals[-1]["type"] == "ai_auto" and "청산 위험" in autopilot.signals[-1]["text"]
    assert ai_auto.feed[0]["level"] == "danger"


def test_scanner_comment(monkeypatch):
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(llm, "text", lambda *a, **k: "근거 한 줄. 위험 한 줄.")
    now = int(time.time())
    sig = {"id": "t:1", "symbol": "BTCUSDT", "interval": "1h", "type": "macd", "label": "MACD", "dir": "long", "strength": 3, "text": "교차",
           "price": 1, "created": now + 5}
    weak = {**sig, "id": "t:2", "strength": 1}
    scanner.signals.extend([sig, weak])
    ai_auto.state["scanner_seen"] = now - 1
    r = ai_auto.run_job("scanner")
    assert sig["ai"] == "근거 한 줄. 위험 한 줄." and "ai" not in weak and "코멘트" in r["headline"]
    assert ai_auto.state["scanner_seen"] >= sig["created"]


def test_bot_coach_auto_improve(monkeypatch):
    from app.strategy import StrategySpec
    from app.library import items
    spec = StrategySpec(**items("BTCUSDT", "1h")[0]["spec"])
    b = paper.add_bot(spec)
    from app.engine import Trade
    for i in range(12):
        b.sim.trades.append(Trade(side="long", entry_time=i, exit_time=i + 1, entry_price=100, exit_price=99, qty=1, leverage=1,
                                  pnl=-1.0, pnl_pct_on_margin=-1.0, fees=0.1, funding=0.0, entry_reason="t", exit_reason="stop_loss"))
    called = []
    monkeypatch.setattr(type(b), "maybe_improve", lambda self, force=False: called.append(force) or {"applied": False, "changes": []})
    ai_auto.state["improved"].pop(b.id, None)
    r = ai_auto.run_job("bots")
    assert called == [True] and any("개선 검토" in a for a in r["auto_actions"])
    r = ai_auto.run_job("bots")                               # 하루 한 번만
    assert called == [True]
    ai_auto.SETTINGS["bots_auto_pause"] = True
    monkeypatch.setattr("app.team.packets.bots_section", lambda p: {b.spec.name: {"id": b.id, "running": True, "max_drawdown_pct": 50, "trades": 12}})
    r = ai_auto.run_job("bots")
    assert not b.running and any("멈춤" in a for a in r["auto_actions"])
    paper.bots.pop(b.id, None)


def test_settings_and_overlap():
    s = c.post("/api/ai/auto/settings", json={"every_min": {"market": 7, "bad": 3}, "positions": False, "daily_limit": 99999}).json()
    assert s["every_min"]["market"] == 7 and "bad" not in s["every_min"] and s["daily_limit"] == 5000 and s["positions"] is False
    from app.quant import copilot
    assert copilot.SETTINGS["auto_ai"] is False
    c.post("/api/ai/auto/settings", json={"positions": True})
    assert copilot.SETTINGS["auto_ai"] is True
    c.post("/api/copilot/config", json={"auto_ai": False})     # AI 탭의 체크박스와 같은 설정
    assert ai_auto.SETTINGS["positions"] is False
    assert ai_auto.trade_active()
    ai_auto.SETTINGS["enabled"] = False
    assert not ai_auto.trade_active() and ai_auto.due() == []
    ai_auto.SETTINGS["enabled"] = True
    ai_auto.state["last"] = {}
    assert set(ai_auto.due()) == {j for j, m in ai_auto.SETTINGS["every_min"].items() if m}


def test_ai_signal_record_grade_and_notify():
    """사용자 요청: AI 진입 시그널을 차트에 — 롱/숏 아이디어를 기록하고 결과(익절·손절·미체결)를 매긴다."""
    from app.quant import copilot
    lt = {"symbol": "TESTUSDT", "interval": "1h", "bar_time": 1000, "price": 100, "atr": 2,
          "candles": [{"time": 0}, {"time": 1000}]}
    res = {"confidence": 70, "headline": "h", "entry_idea": {"action": "long", "entry": 100, "stop": 98, "take": 104, "trigger": "t", "reason": "r"}}
    n = len(autopilot.signals)
    s1 = copilot.record_signal(lt, res, "nvidia", "m")
    assert s1 and s1["side"] == "long" and autopilot.signals[-1]["type"] == "ai_entry" and len(autopilot.signals) == n + 1
    assert copilot.record_signal(lt, res, "nvidia", "m") is None                      # 같은 방향·비슷한 진입가 → 하나로
    assert copilot.record_signal(lt, {**res, "entry_idea": {**res["entry_idea"], "action": "wait"}}, "rules", None) is None
    bar = lambda t, lo, hi: {"time": t, "open": lo, "high": hi, "low": lo, "close": hi}
    assert copilot.grade(s1, [bar(1000, 101, 102), bar(2000, 99.5, 101), bar(3000, 101, 104.5)])["status"] == "take"
    assert copilot.grade(s1, [bar(1000, 99, 101), bar(2000, 97, 100)])["status"] == "stop"
    assert copilot.grade(s1, [bar(1000, 97.5, 104.5)])["status"] == "stop"              # 한 봉에 둘 다 → 보수적으로 손절
    assert copilot.grade(s1, [bar(1000 + i * 1000, 101, 102) for i in range(13)])["status"] == "expired"
    assert copilot.grade(s1, [bar(1000, 101, 102)])["status"] == "waiting"
    r = c.get("/api/copilot/signals?symbol=BTCUSDT&interval=1h").json()
    assert "items" in r and "stats" in r
    copilot.ai_signals.remove(s1)


def test_signals_job_rotates_all_coins(monkeypatch):
    from app.quant import copilot
    seen = []
    real = copilot.live
    monkeypatch.setattr(copilot, "live", lambda s, iv, **k: seen.append(s) or real(s, iv, use_ai=False))
    old = dict(autopilot.context)
    autopilot.context.update(symbol="BTCUSDT", interval="1h", watch=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ai_auto.state["rr"] = 0
    for _ in range(3):
        r = ai_auto.run_job("signals")
    assert seen == ["ETHUSDT", "SOLUSDT", "ETHUSDT"] and "순환 분석" in r["headline"]           # 차트 코인은 'trade' 작업이 맡음
    autopilot.context.update(old)


def test_team_briefing_job(monkeypatch):
    from app.team import engine as team
    team.save_settings(coins=["BTCUSDT", "ETHUSDT"])
    n = len(autopilot.signals)
    r = ai_auto.run_job("team")
    run = team.runs[r["run_id"]]
    assert run.pipeline == "briefing" and run.status == "done" and r["headline"]
    senders = {m["from"] for m in run.messages}
    assert {"chart", "flow", "macro", "news", "risk", "lead"} <= senders
    assert len(autopilot.signals) == n + 1 and "브리핑" in autopilot.signals[-1]["text"]
    assert ai_auto.team_active()
