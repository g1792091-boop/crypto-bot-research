"""실시간 AI 상황 분석: 포지션 경고 · 규칙 분석 · 다시 분석 조건 · AI 결과 검증 · 일부 청산 · 포지션 감시."""
from fastapi.testclient import TestClient

from app import config, llm
from app.main import app, paper
from app.quant import copilot

c = TestClient(app)


def _fresh():
    c.post("/api/paper/reset", json={"initial_equity": 10000})
    copilot._state.clear()
    copilot._alert_seen.clear()
    copilot.alerts_feed.clear()


def test_rules_analysis_with_position_and_alerts():
    _fresh()
    assert c.post("/api/paper/order", json={"symbol": "BTCUSDT", "side": "long", "margin": 1000, "leverage": 20}).status_code == 200
    r = c.get("/api/copilot", params={"symbol": "BTC", "interval": "15m"}).json()
    assert r["engine"] == "rules" and r["refresh_reason"] == "처음 분석" and r["llm_available"] is False
    pos = [p for p in r["positions"] if p["kind"] == "manual"]
    assert pos and pos[0]["symbol"] == "BTCUSDT" and pos[0]["to_liq_pct"] > 0 and pos[0]["atr"] > 0
    assert any(a["key"].startswith("nostop:") for a in r["alerts"])                  # 손절 없음 경고
    adv = [a for a in r["analysis"]["position_advice"] if a["symbol"] == "BTCUSDT"]
    assert adv and adv[0]["action"] == "move_stop"
    st = adv[0]["new_stop"]
    assert pos[0]["liq"] < st < pos[0]["mark"]                                          # 롱 손절은 청산가와 현재가 사이
    assert r["analysis"]["entry_idea"] is None                                          # 이미 포지션이 있으면 진입 아이디어 없음
    # 같은 상황이면 저장된 분석을 돌려준다 → 포지션이 바뀌면 다시 분석
    assert c.get("/api/copilot", params={"symbol": "BTC", "interval": "15m"}).json()["analyzed_at"] == r["analyzed_at"]
    assert c.post("/api/paper/position/BTCUSDT", json={"stop": st}).status_code == 200
    r2 = c.get("/api/copilot", params={"symbol": "BTC", "interval": "15m"}).json()
    assert r2["refresh_reason"] == "포지션 변경" and not any(a["key"].startswith("nostop:") for a in r2["alerts"])
    assert len(r2["history"]) == 2


def test_no_position_gives_entry_idea():
    _fresh()
    r = c.get("/api/copilot", params={"symbol": "ETHUSDT", "interval": "1h"}).json()
    e = r["analysis"]["entry_idea"]
    assert e and e["action"] in ("long", "short", "wait") and e["trigger"]
    assert r["analysis"]["key_levels"] and r["analysis"]["watch"]


def test_reduce_partial_close():
    _fresh()
    c.post("/api/paper/order", json={"symbol": "SOLUSDT", "side": "short", "margin": 800, "leverage": 5})
    a = c.post("/api/paper/reduce/SOLUSDT", json={"fraction": 0.25}).json()
    p = next(x for x in a["positions"] if x["symbol"] == "SOLUSDT")
    assert abs(p["margin"] - 600) < 1e-6 and a["trades"][-1]["exit_reason"] == "partial_25"
    a = c.post("/api/paper/reduce/SOLUSDT", json={"fraction": 1}).json()
    assert not any(x["symbol"] == "SOLUSDT" for x in a["positions"])


def test_ai_path_sanitizes_bad_prices(monkeypatch):
    _fresh()
    c.post("/api/paper/order", json={"symbol": "BTCUSDT", "side": "long", "margin": 500, "leverage": 10})
    seen = {}

    def fake_parse(system, user, schema, **kw):
        seen["user"] = user
        return copilot.LiveAnalysis(
            headline="테스트", situation="상황", bias="short", confidence=140, changes="",
            position_advice=[copilot.PositionAdvice(target="내 포지션 BTCUSDT", symbol="BTCUSDT", action="move_stop", urgency="high",
                                                    new_stop=10 ** 9, reason="말이 안 되는 손절"),
                             copilot.PositionAdvice(target="내 포지션 BTCUSDT", symbol="BTCUSDT", action="reduce", urgency="medium",
                                                    fraction=3, reason="비율")],
            entry_idea=None, key_levels=[], risks=[], watch=[])
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(config, "provider", lambda: "gemini")
    monkeypatch.setattr(llm, "parse", fake_parse)
    r = c.get("/api/copilot", params={"symbol": "BTCUSDT", "interval": "15m"}).json()
    assert r["engine"] == "gemini" and r["analysis"]["confidence"] == 100
    a0, a1 = r["analysis"]["position_advice"]
    assert a0["new_stop"] is None and "제외" in a0["reason"]                           # 롱인데 현재가 위 손절 → 제거
    assert a1["fraction"] == 1.0
    assert '"positions"' in seen["user"] and "alerts" in seen["user"]                    # AI 에 포지션·경고를 넘김


def test_ai_failure_falls_back_to_rules(monkeypatch):
    _fresh()

    def boom(*a, **k):
        raise llm.LLMUnavailable("429 한도 초과")
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(llm, "parse", boom)
    r = c.get("/api/copilot", params={"symbol": "XRPUSDT", "interval": "1h"}).json()
    assert r["engine"] == "rules" and "429" in r["error"] and r["analysis"]["headline"]


def test_watcher_alerts_and_dedupe():
    _fresh()
    c.post("/api/paper/order", json={"symbol": "DOGEUSDT", "side": "short", "margin": 500, "leverage": 50})
    first = c.post("/api/copilot/watch").json()
    assert first["new"] >= 1 and any("손절이 없습니다" in a["text"] for a in first["items"])
    assert c.post("/api/copilot/watch").json()["new"] == 0                              # 같은 경고는 30분에 한 번
    got = c.get("/api/copilot/alerts", params={"since": 0}).json()
    assert got["items"] and got["settings"]["watch"] is True
    c.post("/api/paper/reset", json={"initial_equity": 10000})


def test_ask_without_key():
    r = c.post("/api/copilot/ask", json={"symbol": "BTCUSDT", "question": "지금 롱 버텨도 돼?"}).json()
    assert r["engine"] == "rules" and "키" in r["answer"]
