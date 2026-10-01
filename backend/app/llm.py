"""AI 호출 래퍼 — Claude(ANTHROPIC_API_KEY) · NVIDIA(NVIDIA_API_KEY, 무료 크레딧) · Gemini(GEMINI_API_KEY, 무료 등급)."""
from __future__ import annotations

from typing import TypeVar

import anthropic
import httpx
from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None

# 정책 분류기에 의해 거절되면 서버가 다른 모델로 자동 재시도 (server-side fallback)
_FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


class LLMUnavailable(RuntimeError):
    pass


def provider() -> str | None:
    """지금 기본으로 쓰는 공급자 (모델 배정의 첫 번째, 없으면 키가 있는 공급자)."""
    from . import ai_routes
    r = ai_routes.primary()
    return r.split(":", 1)[0] if r else config.provider()


def model_name() -> str | None:
    from . import ai_routes
    r = ai_routes.primary()
    if not r:
        return None
    p, m = ai_routes.split(r)
    if p == "gemini" and m == "auto":
        from . import gemini
        return gemini.last_model or config.GEMINI_MODEL or "Gemini Flash (자동 선택)"
    return m


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


def reset_client() -> None:
    global _client
    _client = None


# ---------------------------------------------------------------- 모델 하나 호출
def _claude(model, system, user, max_tokens, effort=None, schema=None):
    kw = {"output_config": {"effort": effort}} if effort else {}
    if schema is not None:
        resp = client().beta.messages.parse(model=model, max_tokens=max_tokens, system=system,
                                            messages=[{"role": "user", "content": user}], output_format=schema, **kw, **_FALLBACK)
        if resp.stop_reason == "refusal":
            raise LLMUnavailable("모델이 요청을 거절했습니다.")
        if resp.parsed_output is None:
            raise LLMUnavailable(f"구조화 출력 파싱 실패 (stop_reason={resp.stop_reason})")
        return resp.parsed_output
    resp = client().beta.messages.create(model=model, max_tokens=max_tokens, system=system,
                                         messages=[{"role": "user", "content": user}], **kw, **_FALLBACK)
    if resp.stop_reason == "refusal":
        raise LLMUnavailable("모델이 요청을 거절했습니다.")
    return "".join(b.text for b in resp.content if b.type == "text")


def _one(route: str, kind: str, system: str, user: str, max_tokens: int, effort=None, schema=None):
    from . import ai_routes
    p, m = ai_routes.split(route)
    if p == "nvidia":
        from . import nvidia
        mt = min(max_tokens, config.NVIDIA_MAX_TOKENS)
        if kind == "parse":
            return nvidia.parse(system, user, schema, max_tokens=mt, model=m)
        return nvidia.generate(system, user, json_mode=kind == "json", max_tokens=mt, model=m)
    if p == "gemini":
        from . import gemini
        if kind == "parse":
            return gemini.parse(system, user, schema, max_tokens=max_tokens, model=m)
        return gemini.generate(system, user, None, json_mode=kind == "json", max_tokens=max_tokens, model=m)
    if p == "claude":
        return _claude(m, system, user, max_tokens, effort if kind != "json" else None, schema if kind == "parse" else None)
    raise LLMUnavailable(f"알 수 없는 공급자: {p}")


last_used: str | None = None      # 마지막으로 실제로 답한 모델 (화면 표시용)


def _run(kind, system, user, max_tokens, effort=None, schema=None, feature=None, role=None, tier="opus", route=None):
    """배정된 모델부터 차례로 시도 (한도·오류면 다음 모델)."""
    global last_used
    from . import ai_routes
    routes = ai_routes.chain(feature, role, tier, route)
    if routes:
        from . import knowledge                       # 연구 카드 + 시그널 성적을 모든 매매 판단 호출에 붙인다
        system = knowledge.inject(system, user, feature)
    if not routes:
        raise LLMUnavailable("AI 키가 없습니다 (settings.txt 또는 'AI 모델' 창에서 키를 넣으세요).")
    errors = []
    for r in routes:
        try:
            out = _one(r, kind, system, user, max_tokens, effort, schema)
            if r.startswith("nvidia:"):                       # auto·종료 모델 대체 → 실제로 답한 모델 이름으로
                from . import nvidia
                r = "nvidia:" + (nvidia.used_model() or ai_routes.split(r)[1])
            last_used = r
            return out, r
        except (LLMUnavailable, anthropic.APIError, httpx.HTTPError, ValueError) as e:
            if r.startswith("nvidia:"):
                from . import nvidia
                m = nvidia.used_model()
                if m and m != ai_routes.split(r)[1]:
                    r = f"{r} → {m}"
            errors.append(f"{r[:70]}: {str(e)[:220]}")
    raise LLMUnavailable("모든 모델이 실패했습니다 — " + " / ".join(errors))


def parse(system: str, user: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000,
          feature: str | None = None, role: str | None = None, route: str | None = None) -> T:
    return _run("parse", system, user, max_tokens, effort, schema, feature, role, "opus", route)[0]


def text(system: str, user: str, effort: str = "medium", max_tokens: int = 16000,
         feature: str | None = None, role: str | None = None, route: str | None = None) -> str:
    return _run("text", system, user, max_tokens, effort, None, feature, role, "opus", route)[0]


def json_call(system: str, user: str, tier: str = "opus", max_tokens: int = 6000,
              feature: str | None = None, role: str | None = None, route: str | None = None) -> tuple[dict, str, str]:
    """JSON 객체 하나로 답하게 하고 dict 로 돌려준다 → (data, 원문, 답한 모델 '공급자:이름').
    tier: 'opus' = 판단형(에이전트 팀 team_heavy), 'sonnet' = 반복 분석형(team_light)."""
    import json as _json

    from .gemini import _clean_json
    from .nvidia import strip_think
    feature = feature or ("team_heavy" if tier == "opus" else "team_light")
    txt, r = _run("json", system, user, max_tokens, None, None, feature, role, tier, route)
    try:
        data = _json.loads(_clean_json(strip_think(txt)))
    except ValueError:
        data = None
    return data, txt, r
