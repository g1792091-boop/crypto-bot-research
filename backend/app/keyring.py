"""AI 키 여러 개 — 공급자마다 키를 9개까지 넣고 팀·직원마다 다른 키를 쓰게 한다.

모델 배정 형식: '공급자#번호:모델'  예) nvidia#2:auto  →  NVIDIA_API_KEY_2 로 auto 모델 호출. 번호가 없으면 1번(기본 키).
설정 파일(settings.txt) 이름: NVIDIA_API_KEY, NVIDIA_API_KEY_2 … NVIDIA_API_KEY_9 (GEMINI_API_KEY_n, ANTHROPIC_API_KEY_n 도 같다).
무료 키는 분당 호출 수 한도가 키마다 따로라서, 직원들이 키를 나눠 쓰면 한도에 덜 걸린다.
"""
from __future__ import annotations

import contextvars
import os
import re

from . import config

ENV = {"claude": "ANTHROPIC_API_KEY", "nvidia": "NVIDIA_API_KEY", "gemini": "GEMINI_API_KEY"}
MAX_SLOTS = 9
_slot: contextvars.ContextVar = contextvars.ContextVar("ai_key_slot", default={})
_ROUTE = re.compile(r"^(claude|nvidia|gemini)(?:#([1-9]))?$")


def env_name(provider: str, slot: int = 1) -> str:
    return ENV[provider] + ("" if slot == 1 else f"_{slot}")


def key(provider: str, slot: int = 1) -> str:
    if slot == 1:
        v = getattr(config, ENV[provider], "")
        if provider == "gemini" and not v:
            v = os.getenv("GOOGLE_API_KEY", "")
        return v or ""
    return os.getenv(env_name(provider, slot), "")


def slots(provider: str) -> list[int]:
    return [n for n in range(1, MAX_SLOTS + 1) if key(provider, n)]


def parse(provider_part: str) -> tuple[str, int] | None:
    """'nvidia#2' → ('nvidia', 2). 형식이 틀리면 None."""
    m = _ROUTE.match(provider_part or "")
    return (m.group(1), int(m.group(2) or 1)) if m else None


def active(provider: str) -> str:
    """지금 호출에 쓸 키 (use() 로 정한 번호, 없으면 1번)."""
    n = _slot.get().get(provider, 1)
    return key(provider, n) or key(provider, 1)


def active_slot(provider: str) -> int:
    n = _slot.get().get(provider, 1)
    return n if key(provider, n) else 1


class use:
    """with keyring.use('nvidia', 2): ... 이 안의 호출은 2번 키를 쓴다."""

    def __init__(self, provider: str, slot: int):
        self.p, self.n, self.tok = provider, slot, None

    def __enter__(self):
        self.tok = _slot.set({**_slot.get(), self.p: self.n})
        return self

    def __exit__(self, *a):
        _slot.reset(self.tok)


def mask(v: str) -> str:
    return (v[:6] + "…" + v[-4:]) if len(v) > 12 else ("설정됨" if v else "")


def view() -> dict:
    return {p: [{"slot": n, "env": env_name(p, n), "masked": mask(key(p, n))} for n in slots(p)] for p in ENV}


def set_key(provider: str, slot: int, value: str) -> str:
    """키를 넣는다(빈 문자열이면 지움). 바뀐 환경변수 이름을 돌려준다."""
    env = env_name(provider, slot)
    os.environ[env] = value
    if slot == 1:
        setattr(config, ENV[provider], value)
    return env
