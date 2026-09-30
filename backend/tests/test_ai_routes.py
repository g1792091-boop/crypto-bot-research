"""여러 AI 모델: 배정(기본·기능별·에이전트별), 대체 순서, 화면 API, 오토파일럿의 AI 매매법 제안·진입 코멘트."""
import pytest
from fastapi.testclient import TestClient

from app import ai_routes, autopilot, config, llm, nvidia
from app.main import app
from app.strategy import StrategySpec

c = TestClient(app)


@pytest.fixture
def routes(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setattr(config, "LLM_PROVIDER", "auto")
    ai_routes.reset_cache()
    ai_routes.save({"models": [], "default": "", "fallback": [], "features": {}, "roles": {}})
    calls = []

    def gen(system, user, json_mode=False, max_tokens=4096, model=None):
        calls.append(model)
        if model and model.startswith("bad/"):
            raise llm.LLMUnavailable("한도 초과")
        return '{"message": "ok", "headline": "h", "findings": []}' if json_mode else f"답:{model}"
    monkeypatch.setattr(nvidia, "generate", gen)
    yield calls
    ai_routes.save({"models": [], "default": "", "fallback": [], "features": {}, "roles": {}})


def test_chain_order_and_availability(routes):
    assert ai_routes.chain() == ["nvidia:" + config.NVIDIA_MODEL]                      # 배정 없으면 예전과 같음
    ai_routes.save({"default": "nvidia:big/model", "fallback": ["gemini:auto", "nvidia:small/model"],
                    "features": {"copilot": "nvidia:fast/model"}, "roles": {"strategist": "nvidia:judge/model"}})
    assert ai_routes.chain() == ["nvidia:big/model", "nvidia:small/model"]            # 키 없는 gemini 는 건너뜀
    assert ai_routes.chain(feature="copilot")[0] == "nvidia:fast/model"
    assert ai_routes.chain(feature="team_heavy", role="strategist")[0] == "nvidia:judge/model"
    assert ai_routes.chain(feature="team_light", role="chart")[0] == "nvidia:big/model"
    assert ai_routes.chain(route="nvidia:only/this") == ["nvidia:only/this"]            # 테스트는 대체 없이
    assert set(ai_routes.load()["models"]) >= {"nvidia:big/model", "nvidia:fast/model", "nvidia:judge/model"}
    assert not ai_routes.valid("nvidia") and not ai_routes.valid("foo:bar")


def test_fallback_to_next_model(routes):
    ai_routes.save({"default": "nvidia:bad/one", "fallback": ["nvidia:good/two"]})
    assert llm.text("s", "u") == "답:good/two" and routes == ["bad/one", "good/two"]
    assert llm.last_used == "nvidia:good/two"
    ai_routes.save({"default": "nvidia:bad/one", "fallback": []})
    with pytest.raises(llm.LLMUnavailable) as e:
        llm.text("s", "u")
    assert "모든 모델이 실패" in str(e.value)


def test_team_role_gets_its_model(routes):
    ai_routes.save({"roles": {"risk": "nvidia:judge/model"}, "features": {"team_light": "nvidia:light/model"}})
    data, _, used = llm.json_call("s", "u", "opus", role="risk")
    assert used == "nvidia:judge/model" and data["message"] == "ok"
    _, _, used = llm.json_call("s", "u", "sonnet", role="chart")
    assert used == "nvidia:light/model"
    from app.team import engine as team
    ro = {r["id"]: r["model"] for r in team.roster()}
    assert ro["risk"] == "judge/model" and ro["chart"] == "light/model"


def test_ai_endpoints(routes, monkeypatch, tmp_path):
    v = c.get("/api/ai").json()
    assert v["keys"]["nvidia"] and len(v["roles_list"]) == 23 and "copilot" in v["features_desc"]
    s = c.post("/api/ai/routes", json={"models": ["nvidia:a/b", "nope"], "default": "nvidia:a/b", "features": {"news": "bad"}}).json()
    assert s["models"] == ["nvidia:a/b"] and s["default"] == "nvidia:a/b" and s["features"] == {}
    t = c.post("/api/ai/test", json={"route": "nvidia:x/y"}).json()
    assert t["ok"] and t["answer"] == "답:x/y"
    assert c.post("/api/ai/test", json={"route": "gemini:auto"}).status_code == 400              # 키 없음
    f = tmp_path / "settings.txt"
    f.write_text("GEMINI_API_KEY=\nNVIDIA_API_KEY=old\n", encoding="utf-8")
    monkeypatch.setenv("SETTINGS_FILE", str(f))
    monkeypatch.setenv("GEMINI_API_KEY", "")          # 끝나면 원래대로 (엔드포인트가 환경 변수도 바꿈)
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    r = c.post("/api/ai/keys", json={"gemini": "AIza-new", "provider": "nvidia"}).json()
    assert r["saved_to_file"] and r["keys"]["gemini"] and config.GEMINI_API_KEY == "AIza-new"
    txt = f.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=AIza-new" in txt and "NVIDIA_API_KEY=old" in txt and "LLM_PROVIDER=nvidia" in txt


def test_autopilot_ai_candidates_and_comment(routes, monkeypatch):
    good = StrategySpec(name="EMA 눌림", symbol="X", interval="4h", indicators=[{"id": "e", "type": "ema", "length": 50}],
                        long_entry={"conditions": [{"left": "close", "op": "crosses_above", "right": "e"}]})
    bad = StrategySpec(name="틀림", long_entry={"conditions": [{"left": "nope", "op": ">", "right": "1"}]})
    seen = {}

    def fake_parse(system, user, schema, **kw):
        seen["feature"] = kw.get("feature")
        return schema(ideas=[good, bad])
    monkeypatch.setattr(llm, "parse", fake_parse)
    r = autopilot.evaluate("BTCUSDT", "1h", [{"key": "ema", "params": {"length": 50}}])
    assert seen["feature"] == "autopilot" and r["ai"]["proposed"] == 1
    names = [x["name"] for x in r["top_train"] + r["passed"] + r["observe"]]
    assert r["tried"] >= 2
    specs, note = autopilot.ai_candidates("ETHUSDT", "1h", [], __import__("app.data.market", fromlist=["x"]).candles("ETHUSDT", "1h", 300)[0])
    assert specs[0].symbol == "ETHUSDT" and specs[0].name.startswith("🤖 AI · ") and specs[0].risk.leverage == autopilot.SETTINGS["leverage"]
    assert autopilot._family(specs[0].name) == specs[0].name
    monkeypatch.setattr(llm, "text", lambda *a, **k: "RSI 반등이 근거, 손절 이탈이 위험.")
    before = len(autopilot.signals)
    autopilot._ai_comment({"id": "s1", "symbol": "BTCUSDT", "interval": "1h", "side": "long", "entry": 1.0, "strategy": "t", "status": "pass"})
    note = list(autopilot.signals)[before:]
    assert note and note[0]["type"] == "ai_note" and note[0]["text"].startswith("AI 코멘트") and note[0]["ref"] == "s1"
    assert isinstance(names, list)
