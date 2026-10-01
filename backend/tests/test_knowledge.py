from fastapi.testclient import TestClient

from app import config, knowledge, llm
from app.main import app


def test_cards_load_and_relevance():
    cs = knowledge.cards()
    assert len(cs) >= 40 and {c["status"] for c in cs} == {"validated", "rejected", "hypothesis"}
    rel = knowledge.relevant("SOLUSDT", "15m")
    ids = [c["id"] for c in rel]
    assert "k01" in ids                                        # 단기 비용 카드는 15분봉에 꼭 들어간다
    assert any(c["status"] == "rejected" for c in rel) and any(c["status"] == "hypothesis" for c in rel)
    assert all(knowledge._applies(c, "SOLUSDT", "15m") or c["applies"].get("timeframes") == "all" for c in rel)
    daily = [c["id"] for c in knowledge.relevant("BTCUSDT", "1d")]
    assert "k10" in daily and "k01" not in daily


def test_inject_into_prompts(monkeypatch):
    s = knowledge.inject("SYS", '{"symbol": "ETHUSDT", "interval": "4h"}', "copilot")
    assert s.startswith("SYS") and "[연구 지식]" in s and "3,500" in s
    assert knowledge.inject(s, "", "copilot") == s             # 두 번 붙이지 않는다
    assert knowledge.inject("SYS", "x", "news") == "SYS"       # 뉴스 번역에는 안 붙인다
    seen = {}

    def fake(route, kind, system, user, *a, **k):
        seen["system"] = system
        return "ok"
    from app import ai_routes
    monkeypatch.setattr(llm, "_one", fake)
    monkeypatch.setattr(ai_routes, "chain", lambda *a, **k: ["gemini:x"])
    llm._run("text", "BASE", "BTCUSDT 15m 분석", 100)
    assert "[연구 지식]" in seen["system"] and "k01" in seen["system"]


def test_warnings_and_lessons_text(monkeypatch):
    w = knowledge.warnings("5m", 20, 0.5)
    assert len(w) == 3
    assert knowledge.warnings("4h") == []
    rows = [{"symbol": "BTCUSDT", "interval": "15m", "side": "long", "confidence": 72, "engine": "nvidia",
             "outcome": {"status": "stop" if i % 3 else "take", "r": -1.0 if i % 3 else 1.0}} for i in range(31)]
    from app import aibot
    monkeypatch.setattr(aibot, "compute", lambda force=False: {"signals": rows})
    knowledge._lessons.update(at=0.0, data=None, busy=False)
    d = knowledge.lessons(wait=True)
    o = d["overall"][0]
    assert d["total"] == 31 and o["n"] == 31 and o["pattern"] and o["win_rate"] == round(11 / 31 * 100, 1)
    t = knowledge.lessons_text("BTCUSDT", "15m")
    assert "31건" in t and "이 코인" in t and "손실인 조합" in t
    knowledge._lessons.update(at=0.0, data=None, busy=False)


def test_api_knowledge_macro_and_analysis_only(monkeypatch):
    c = TestClient(app)
    d = c.get("/api/knowledge?symbol=BTCUSDT&interval=5m").json()
    assert d["enabled"] and len(d["cards"]) >= 40 and d["relevant"] and d["warnings"] and "[" in d["prompt"]
    m = c.get("/api/macro").json()
    assert len(m["items"]) == 6 and all(len(x["history"]) > 30 for x in m["items"])
    h = c.get("/api/market/heatmap?limit=5").json()["items"]
    assert len(h) == 5 and h[0]["quote_volume"] >= h[-1]["quote_volume"]
    monkeypatch.setattr(config, "MANUAL_PAPER", False)          # 실제 앱: 수동 모의 주문은 없다
    r = c.post("/api/paper/order", json={"symbol": "BTCUSDT", "side": "long", "margin": 100, "leverage": 2})
    assert r.status_code == 410 and "분석 전용" in r.json()["detail"]
    assert c.post("/api/paper/close/BTCUSDT").status_code == 410
