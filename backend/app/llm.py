"""Claude API 호출 래퍼."""
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


def client() -> anthropic.Anthropic:
    global _client
    if not config.llm_enabled():
        raise LLMUnavailable("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def parse(system: str, user: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000) -> T:
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
