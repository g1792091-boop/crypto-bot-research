"""Gemini 경로를 실제 호출 없이 검증 (httpx 를 가짜 응답으로 대체)."""
import json

import httpx
import pytest

from app import config, gemini, llm
from app.agents import AnalystReport
from app.llm import LLMUnavailable
from app.strategy import StrategySpec

LISTING = {"models": [
    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent", "countTokens"]},
    {"name": "models/gemini-3.8-flash-lite", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.9-flash-preview-10-2026", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.8-flash-image", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-3.8-flash-tts", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gemini-3.8-pro", "supportedGenerationMethods": ["generateContent"]},
]}


def _resp(code, body):
    return httpx.Response(code, json=body, request=httpx.Request("POST", "https://x"))


def _answer(obj):
    return _resp(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(obj, ensure_ascii=False)}]}, "finishReason": "STOP"}]})


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "LLM_PROVIDER", "auto")
    monkeypatch.setattr(config, "GEMINI_MODEL", "")
    monkeypatch.setattr(config, "GEMINI_RPM", 1000)
    monkeypatch.setattr(gemini, "_models", None)
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    monkeypatch.setattr(gemini.httpx, "get", lambda *a, **k: _resp(200, LISTING))
    calls, replies = [], []

    def post(url, headers=None, json=None, timeout=None):
        calls.append((url.split("/models/")[1].split(":")[0], json))
        return replies.pop(0)
    monkeypatch.setattr(gemini.httpx, "post", post)
    return calls, replies


def test_provider_choice(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "auto")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    assert config.provider() is None and not config.llm_enabled()
    monkeypatch.setattr(config, "GEMINI_API_KEY", "g")
    assert config.provider() == "gemini"
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "a")
    assert config.provider() == "claude"               # 둘 다 있으면 Claude
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    assert config.provider() == "gemini"


def test_picks_newest_stable_flash_then_lite(fake):
    assert gemini.pick_models(LISTING["models"])[:2] == ["gemini-3.8-flash", "gemini-2.5-flash"]
    assert gemini.models() == ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-3.8-flash-lite"]


def test_structured_output_sends_inlined_schema(fake):
    calls, replies = fake
    replies.append(_answer({"stance": "bullish", "confidence": 70, "key_points": ["a"], "summary": "s"}))
    r = llm.parse("sys", "user", AnalystReport)
    assert isinstance(r, AnalystReport) and r.stance == "bullish"
    model, body = calls[0]
    assert model == "gemini-3.8-flash"
    gen = body["generationConfig"]
    assert gen["responseMimeType"] == "application/json" and "$ref" not in json.dumps(gen["responseJsonSchema"])
    # 복잡한 스키마(StrategySpec)도 $ref 없이 펼쳐진다
    assert "$ref" not in json.dumps(gemini.inline_refs(StrategySpec.model_json_schema()))


def test_rate_limit_moves_to_next_model(fake):
    calls, replies = fake
    limit = _resp(429, {"error": {"message": "quota", "details": [{"retryDelay": "59s"}]}})
    replies += [limit, _answer({"stance": "neutral", "confidence": 10, "key_points": [], "summary": "x"})]
    assert llm.parse("s", "u", AnalystReport).stance == "neutral"
    assert [c[0] for c in calls] == ["gemini-3.8-flash", "gemini-2.5-flash"]
    assert gemini.last_model == "gemini-2.5-flash"


def test_all_models_limited_raises_friendly_error(fake):
    _, replies = fake
    replies += [_resp(429, {"error": {"message": "quota", "details": [{"retryDelay": "59s"}]}})] * 3
    with pytest.raises(LLMUnavailable, match="한도"):
        llm.text("s", "u")


def test_bad_json_is_retried_once(fake):
    calls, replies = fake
    replies += [_resp(200, {"candidates": [{"content": {"parts": [{"text": "```json\n{\"stance\": 1}\n```"}]}}]}),
                _answer({"stance": "bearish", "confidence": 55, "key_points": ["k"], "summary": "ok"})]
    assert llm.parse("s", "u", AnalystReport).stance == "bearish"
    assert "스키마와 맞지 않았다" in calls[1][1]["contents"][0]["parts"][0]["text"]


def test_schema_rejected_falls_back_to_prompt_only(fake):
    calls, replies = fake
    replies += [_resp(400, {"error": {"message": 'Invalid JSON payload received. Unknown name "responseJsonSchema"'}}),
                _answer({"stance": "neutral", "confidence": 1, "key_points": [], "summary": "p"})]
    assert llm.parse("s", "u", AnalystReport).summary == "p"
    assert "responseJsonSchema" not in calls[1][1]["generationConfig"]


def test_invalid_key(fake):
    _, replies = fake
    replies.append(_resp(400, {"error": {"message": "API key not valid. Please pass a valid API key."}}))
    with pytest.raises(LLMUnavailable, match="키"):
        llm.text("s", "u")


def test_ai_failure_falls_back_to_rules(monkeypatch):
    from fastapi.testclient import TestClient

    from app import agents
    from app.main import app

    def boom(*a, **k):
        raise LLMUnavailable("Gemini 무료 사용 한도에 걸렸습니다.")
    monkeypatch.setattr(config, "provider", lambda: "gemini")
    monkeypatch.setattr(llm, "parse", boom)
    c = TestClient(app)
    r = c.post("/api/strategy/auto", json={"text": "EMA 20/50 골든크로스 롱, 손절 2% 익절 4%", "symbol": "ETHUSDT", "bars": 500}).json()
    assert r["engine"] == "rules" and "한도" in r["ai_error"] and r["spec"]["symbol"] == "ETHUSDT"
    r = c.post("/api/strategy/refine", json={"spec": r["spec"], "message": "손절 3%로", "bars": 500}).json()
    assert r["engine"] == "rules" and r["ai_error"] and r["spec"]["risk"]["stop_loss_pct"] == 3
    out = agents.run_team("BTCUSDT")
    assert out["decision"]["action"] in ("long", "short", "stay_flat") and "trader" in out["errors"] and len(out["errors"]) == 4
