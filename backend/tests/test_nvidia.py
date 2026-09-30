"""NVIDIA API (OpenAI 호환) 연결: 공급자 선택, JSON 추출, 추론 태그 제거, JSON 모드 미지원·한도·키 오류 처리."""
import json

import httpx
import pytest
from pydantic import BaseModel

from app import config, llm, nvidia


class Resp:
    def __init__(self, code, data=None, text=""):
        self.status_code, self._d, self.headers = code, data, {}
        self.text = text or json.dumps(data or {})

    def json(self):
        if self._d is None:
            raise ValueError
        return self._d


def _ok(content):
    return Resp(200, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


@pytest.fixture
def nv(monkeypatch):
    monkeypatch.setattr(config, "NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "LLM_PROVIDER", "auto")
    monkeypatch.setattr(config, "NVIDIA_RPM", 1000)
    monkeypatch.setattr(nvidia.time, "sleep", lambda s: None)
    monkeypatch.setattr(nvidia, "_catalog", (nvidia.time.time(), ["meta/llama-3.1-8b-instruct", "deepseek-ai/deepseek-v3.1", "nvidia/nv-embedqa-e5-v5"]))
    monkeypatch.setattr(nvidia, "_dead", {})
    calls = []

    def install(responses):
        it = iter(responses)

        def post(url, headers=None, json=None, timeout=None):
            calls.append({"url": url, "headers": headers, "json": json})
            return next(it)
        monkeypatch.setattr(nvidia.httpx, "post", post)
    return install, calls


def test_provider_selection(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "g")
    monkeypatch.setattr(config, "NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setattr(config, "LLM_PROVIDER", "auto")
    assert config.provider() == "nvidia" and llm.label() == "NVIDIA"
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    assert config.provider() == "gemini"
    monkeypatch.setattr(config, "LLM_PROVIDER", "nvidia")
    monkeypatch.setattr(config, "NVIDIA_API_KEY", "")
    assert config.provider() == "gemini"                      # 키가 없으면 있는 것으로


def test_json_call_strips_think_and_fences(nv):
    install, calls = nv
    install([_ok('<think>생각 중…</think>\n```json\n{"message": "안녕", "n": 3}\n```')])
    data, txt, model = llm.json_call("sys", "user", "sonnet")
    assert data == {"message": "안녕", "n": 3} and model == "nvidia:deepseek-ai/deepseek-v3.1"      # auto → 목록에서 고른 모델
    assert calls[0]["json"]["model"] == "deepseek-ai/deepseek-v3.1"
    c = calls[0]
    assert c["url"].endswith("/v1/chat/completions") and c["headers"]["Authorization"] == "Bearer nvapi-test"
    assert c["json"]["response_format"] == {"type": "json_object"} and c["json"]["messages"][0]["role"] == "system"


def test_json_mode_rejected_then_retry_without(nv):
    install, calls = nv
    install([Resp(400, {"error": {"message": "response_format is not supported"}}), _ok('{"a": 1}')])
    model = "some/model-without-json"
    out = nvidia.generate("s", "u", json_mode=True, model=model)
    assert out == '{"a": 1}' and "response_format" not in calls[1]["json"] and model in nvidia._no_json_mode


def test_parse_validates_and_retries(nv):
    class M(BaseModel):
        x: int
        y: str
    install, calls = nv
    install([_ok('{"x": "숫자아님"}'), _ok('결과: {"x": 5, "y": "ok"} 끝')])
    m = llm.parse("s", "u", M)
    assert m.x == 5 and m.y == "ok" and "스키마" in calls[1]["json"]["messages"][1]["content"]


def test_rate_limit_and_auth_errors(nv):
    install, _ = nv
    install([Resp(429, {}), _ok("두 번째에 성공")])
    assert llm.text("s", "u") == "두 번째에 성공"
    install([Resp(401, {"detail": "Unauthorized"})])
    with pytest.raises(llm.LLMUnavailable) as e:
        llm.text("s", "u")
    assert "키" in str(e.value)
    install([httpx.ConnectError("x")] * 0 + [Resp(429, {})] * 4)
    with pytest.raises(llm.LLMUnavailable) as e:
        llm.text("s", "u")
    assert "한도" in str(e.value)


def test_status_and_team_use_nvidia(nv, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.team import engine as team
    install, _ = nv
    monkeypatch.setattr(config, "NVIDIA_FAST_MODEL", "fast/model")
    st = TestClient(app).get("/api/status").json()
    assert st["llm_provider"] == "nvidia" and st["llm_label"] == "NVIDIA"
    assert team._model_label("opus") == "deepseek-ai/deepseek-v3.1" and team._model_label("sonnet") == "fast/model"


def test_auto_pick_ranking(nv):
    cat = ["meta/llama-3.1-8b-instruct", "deepseek-ai/deepseek-v3.1", "deepseek-ai/deepseek-v3.2", "qwen/qwen2.5-coder-32b-instruct",
           "openai/gpt-oss-20b", "nvidia/llama-3.2-nv-embedqa-1b-v2", "some/unknown-chat"]
    assert nvidia.rank(cat)[:2] == ["deepseek-ai/deepseek-v3.2", "deepseek-ai/deepseek-v3.1"]
    assert nvidia.rank(cat, fast=True)[0] == "openai/gpt-oss-20b" and "qwen/qwen2.5-coder-32b-instruct" not in nvidia.rank(cat)
    nvidia.mark_dead("deepseek-ai/deepseek-v3.2", 410, "end of life")
    assert nvidia.rank(cat)[0] == "deepseek-ai/deepseek-v3.1"


def test_retired_model_switches_and_is_remembered(nv, monkeypatch):
    """사용자 보고: 'meta/llama-3.3-70b-instruct has reached its end of life' (410) → 다른 모델로 바꿔 바로 답하고, 기억한다."""
    from app import ai_routes
    install, calls = nv
    ai_routes.reset_cache()
    ai_routes.save({"default": "nvidia:meta/llama-3.3-70b-instruct", "fallback": [], "features": {}, "roles": {}})
    eol = Resp(410, {"status": 410, "title": "Gone", "detail": "The model 'meta/llama-3.3-70b-instruct' has reached its end of life on 2026-08-26T09:00:00Z"})
    install([eol, _ok('{"message": "대체 모델 답"}')])
    data, _, used = llm.json_call("sys", "user", "opus", role="leader")
    assert data["message"] == "대체 모델 답" and used == "nvidia:deepseek-ai/deepseek-v3.1" and llm.last_used == used
    assert [c["json"]["model"] for c in calls] == ["meta/llama-3.3-70b-instruct", "deepseek-ai/deepseek-v3.1"]
    assert nvidia.is_dead("meta/llama-3.3-70b-instruct")
    assert "meta/llama-3.3-70b-instruct" in (config.STATE_DIR / "nvidia_models.json").read_text(encoding="utf-8")
    # 다음 호출부터는 종료된 모델을 부르지 않는다
    install([_ok("바로 대체 모델")])
    assert llm.text("s", "u") == "바로 대체 모델" and calls[-1]["json"]["model"] == "deepseek-ai/deepseek-v3.1"
    # 목록에 없는 모델(404)도 다른 모델로
    install([Resp(404, {"detail": "Function not found"}), _ok("ok")])
    assert nvidia.generate("s", "u", model="gone/model") == "ok" and nvidia.is_dead("gone/model")
    # 'AI 모델' 창의 테스트는 대체 없이 그 모델만 → 종료됐다고 알려 준다
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    t = c.post("/api/ai/test", json={"route": "nvidia:meta/llama-3.3-70b-instruct"}).json()
    assert not t["ok"] and t["dead"] and "종료" in t["error"]
    install([_ok("자동 테스트")])
    t = c.post("/api/ai/test", json={"route": "nvidia:auto"}).json()
    assert t["ok"] and t["used"] == "nvidia:deepseek-ai/deepseek-v3.1"
    v = c.get("/api/ai").json()
    assert "nvidia:meta/llama-3.3-70b-instruct" in v["dead"] and "nvidia:meta/llama-3.3-70b-instruct" not in v["suggest"]["nvidia"]
    assert v["suggest"]["nvidia"][0] == "nvidia:auto" and v["auto"]["nvidia"] == "deepseek-ai/deepseek-v3.1"
    ai_routes.save({"default": "", "fallback": [], "features": {}, "roles": {}, "models": []})


def test_all_candidates_retired(nv, monkeypatch):
    install, _ = nv
    monkeypatch.setattr(nvidia, "_catalog", (nvidia.time.time(), ["only/one-instruct"]))
    monkeypatch.setattr(nvidia, "STATIC", ())
    install([Resp(410, {"detail": "end of life"})])
    with pytest.raises(llm.LLMUnavailable) as e:
        nvidia.generate("s", "u", model="auto")
    assert "종료" in str(e.value)
