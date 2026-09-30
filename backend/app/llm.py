"""AI 호출 래퍼 — Claude(ANTHROPIC_API_KEY) · NVIDIA(NVIDIA_API_KEY, 무료 크레딧) · Gemini(GEMINI_API_KEY, 무료 등급)."""
from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None

# 정책 분류기에 의해 거절되면 서버가 다른 모델로 자동 재시도 (server-side fallback)
_FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


class LLMUnavailable(RuntimeError):
    pass


def provider() -> str | None:
    return config.provider()


def model_name() -> str | None:
    p = provider()
    if p == "gemini":
        from . import gemini
        return gemini.last_model or config.GEMINI_MODEL or "Gemini Flash (자동 선택)"
    if p == "nvidia":
        from . import nvidia
        return nvidia.last_model or config.NVIDIA_MODEL
    return config.CLAUDE_MODEL if p == "claude" else None


def label() -> str:
    """화면 표시용 이름."""
    return {"claude": "Claude", "gemini": "Gemini", "nvidia": "NVIDIA"}.get(provider() or "", "기본 분석기")


def client() -> anthropic.Anthropic:
    global _client
    if not config.ANTHROPIC_API_KEY:
        raise LLMUnavailable("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def parse(system: str, user: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000) -> T:
    if provider() == "nvidia":
        from . import nvidia
        return nvidia.parse(system, user, schema, max_tokens=min(max_tokens, config.NVIDIA_MAX_TOKENS))
    if provider() == "gemini":
        from . import gemini
        return gemini.parse(system, user, schema, max_tokens=max_tokens)
    resp = client().beta.messages.parse(
        model=config.CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
        output_config={"effort": effort},
        **_FALLBACK,
    )
    if resp.stop_reason == "refusal":
        raise LLMUnavailable("모델이 요청을 거절했습니다.")
    if resp.parsed_output is None:
        raise LLMUnavailable(f"구조화 출력 파싱 실패 (stop_reason={resp.stop_reason})")
    return resp.parsed_output


def text(system: str, user: str, effort: str = "medium", max_tokens: int = 16000) -> str:
    if provider() == "nvidia":
        from . import nvidia
        return nvidia.text(system, user, max_tokens=min(max_tokens, config.NVIDIA_MAX_TOKENS))
    if provider() == "gemini":
        from . import gemini
        return gemini.text(system, user, max_tokens=max_tokens)
    resp = client().beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort},
        **_FALLBACK,
    )
    if resp.stop_reason == "refusal":
        raise LLMUnavailable("모델이 요청을 거절했습니다.")
    return "".join(b.text for b in resp.content if b.type == "text")


def json_call(system: str, user: str, tier: str = "opus", max_tokens: int = 6000) -> tuple[dict, str, str]:
    """JSON 객체 하나로 답하게 하고 dict 로 돌려준다 → (data, 원문, 모델 이름).
    tier: 'opus' = 판단 책임이 큰 역할(CLAUDE_MODEL), 'sonnet' = 반복 분석(CLAUDE_FAST_MODEL). Gemini 는 같은 모델."""
    import json as _json

    from .gemini import _clean_json
    if provider() == "nvidia":
        from . import nvidia
        model = nvidia.model_for(tier)
        txt = nvidia.generate(system, user, json_mode=True, max_tokens=max_tokens, model=model)
        txt = nvidia.clean_json(txt)
    elif provider() == "gemini":
        from . import gemini
        txt = gemini.generate(system, user, None, json_mode=True, max_tokens=max_tokens)
        model = gemini.last_model or "gemini"
    else:
        model = config.CLAUDE_MODEL if tier == "opus" or not config.CLAUDE_FAST_MODEL else config.CLAUDE_FAST_MODEL
        resp = client().beta.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}], **_FALLBACK)
        if resp.stop_reason == "refusal":
            raise LLMUnavailable("모델이 요청을 거절했습니다.")
        txt = "".join(b.text for b in resp.content if b.type == "text")
    try:
        data = _json.loads(_clean_json(txt))
    except ValueError:
        data = None
    return data, txt, model
