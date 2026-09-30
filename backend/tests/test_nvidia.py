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
    assert data == {"message": "안녕", "n": 3} and model == config.NVIDIA_MODEL
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
    install([Resp(404, {"detail": "not found"})])
    with pytest.raises(llm.LLMUnavailable) as e:
        llm.text("s", "u")
    assert "NVIDIA_MODEL" in str(e.value)
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
    assert team._model_label("opus") == config.NVIDIA_MODEL and team._model_label("sonnet") == "fast/model"
