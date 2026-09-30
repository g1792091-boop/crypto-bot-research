"""NVIDIA API (build.nvidia.com, 무료 개발자 키 nvapi-…) — OpenAI 호환 /v1/chat/completions.

- 키: https://build.nvidia.com 로그인 → 모델 페이지의 'Get API Key'. 무료 크레딧과 분당 약 40회 제한이 있다.
- 모델: NVIDIA_MODEL (기본 meta/llama-3.3-70b-instruct). 반복 분석용은 NVIDIA_FAST_MODEL (비우면 같은 모델).
- JSON 이 필요하면 response_format=json_object 를 요청하고(안 받는 모델이면 빼고 다시), 답에서 JSON 만 골라낸다.
- 생각 과정을 <think>…</think> 로 내는 추론 모델(DeepSeek-R1, Qwen3 등)은 그 부분을 지운다.
- 이 API 는 OpenAI 호환이라 NVIDIA_BASE_URL 만 바꾸면 다른 호환 서비스에도 쓸 수 있다.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from . import config
from .llm import LLMUnavailable

T = TypeVar("T", bound=BaseModel)

_lock = threading.Lock()
_calls: deque[float] = deque()
last_model: str | None = None
_no_json_mode: set[str] = set()          # response_format 을 거부한 모델


def _headers() -> dict:
    if not config.NVIDIA_API_KEY:
        raise LLMUnavailable("NVIDIA_API_KEY 가 설정되지 않았습니다.")
    return {"Authorization": f"Bearer {config.NVIDIA_API_KEY}", "Content-Type": "application/json", "Accept": "application/json"}


def _throttle() -> None:
    with _lock:
        now = time.monotonic()
        while _calls and now - _calls[0] > 60:
            _calls.popleft()
        if len(_calls) >= max(1, config.NVIDIA_RPM):
            time.sleep(max(0.0, 60 - (now - _calls[0])) + 0.3)
        _calls.append(time.monotonic())


def _err(r: httpx.Response) -> str:
    try:
        d = r.json()
        e = d.get("error") if isinstance(d, dict) else None
        msg = (e.get("message") if isinstance(e, dict) else e) or d.get("detail") or d.get("title") or ""
        return str(msg)[:200] or r.text[:200]
    except ValueError:
        return r.text[:200]


def model_for(tier: str = "opus") -> str:
    if tier != "opus" and config.NVIDIA_FAST_MODEL:
        return config.NVIDIA_FAST_MODEL
    return config.NVIDIA_MODEL


def strip_think(txt: str) -> str:
    txt = re.sub(r"<think>.*?</think>", "", txt or "", flags=re.S)
    if "</think>" in txt:                         # 여는 태그 없이 닫는 태그만 있는 경우
        txt = txt.split("</think>", 1)[1]
    return txt.strip()


def generate(system: str, user: str, json_mode: bool = False, max_tokens: int = 4096, model: str | None = None) -> str:
    global last_model
    model = model or config.NVIDIA_MODEL
    body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2, "top_p": 0.9, "max_tokens": min(max_tokens, config.NVIDIA_MAX_TOKENS), "stream": False}
    if json_mode and model not in _no_json_mode:
        body["response_format"] = {"type": "json_object"}
    url = config.NVIDIA_BASE_URL.rstrip("/") + "/chat/completions"
    for attempt in range(4):
        _throttle()
        try:
            r = httpx.post(url, headers=_headers(), json=body, timeout=180)
        except httpx.HTTPError as e:
            if attempt == 3:
                raise LLMUnavailable(f"NVIDIA API 연결 실패: {e}") from e
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 400 and "response_format" in body and ("response_format" in r.text or "json" in r.text.lower()):
            _no_json_mode.add(model)                 # 이 모델은 JSON 모드를 모름 → 빼고 다시
            body.pop("response_format")
            continue
        if r.status_code == 429:
            if attempt < 3:
                time.sleep(float(r.headers.get("retry-after") or 5 * (attempt + 1)))
                continue
            raise LLMUnavailable("NVIDIA 무료 사용 한도(분당 요청 수 또는 크레딧)에 걸렸습니다. 잠시 뒤 다시 시도하세요.")
        if r.status_code in (401, 403):
            raise LLMUnavailable(f"NVIDIA API 키를 확인하세요 ({r.status_code}: {_err(r)}). 키가 맞는데도 안 되면 build.nvidia.com 계정의 "
                                 "API 사용 권한(Public API Endpoints)이 켜져 있는지 확인하세요.")
        if r.status_code == 404:
            raise LLMUnavailable(f"NVIDIA 모델을 찾지 못했습니다: {model} — settings.txt 의 NVIDIA_MODEL 을 build.nvidia.com 모델 이름(예: meta/llama-3.3-70b-instruct)으로 바꾸세요.")
        if r.status_code >= 500 or r.status_code == 408:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code >= 400:
            raise LLMUnavailable(f"NVIDIA 오류 {r.status_code}: {_err(r)}")
        d = r.json()
        choices = d.get("choices") or []
        if not choices:
            raise LLMUnavailable("NVIDIA 빈 응답")
        msg = choices[0].get("message") or {}
        out = strip_think(msg.get("content") or "")
        if not out:
            raise LLMUnavailable(f"NVIDIA 빈 응답 (finish_reason={choices[0].get('finish_reason')})")
        last_model = model
        return out
    raise LLMUnavailable("NVIDIA 서버가 응답하지 않습니다 (잠시 뒤 다시 시도하세요).")


def clean_json(txt: str) -> str:
    txt = strip_think(txt)
    m = re.search(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m:
        txt = m.group(1).strip()
    if not txt.startswith("{"):
        a, b = txt.find("{"), txt.rfind("}")
        if a >= 0 and b > a:
            txt = txt[a:b + 1]
    return txt


def parse(system: str, user: str, schema_cls: type[T], max_tokens: int = 4096, model: str | None = None) -> T:
    from .gemini import inline_refs
    js = inline_refs(schema_cls.model_json_schema())
    sys2 = (f"{system}\n\n출력 형식: 아래 JSON 스키마에 맞는 JSON 객체 하나만 출력한다. 설명·마크다운·코드 블록 없이.\n"
            f"{json.dumps(js, ensure_ascii=False)}")
    msg = user
    for attempt in range(2):
        txt = generate(sys2, msg, json_mode=True, max_tokens=max_tokens, model=model)
        try:
            return schema_cls.model_validate_json(clean_json(txt))
        except ValidationError as e:
            if attempt:
                raise LLMUnavailable(f"NVIDIA 응답이 형식에 맞지 않습니다: {e.errors()[0].get('msg', '')}") from e
            msg = f"{user}\n\n(직전 응답이 스키마와 맞지 않았다: {str(e)[:600]}\n스키마에 정확히 맞는 JSON 만 다시 출력하라.)"
    raise LLMUnavailable("NVIDIA 응답 처리 실패")


def text(system: str, user: str, max_tokens: int = 4096, model: str | None = None) -> str:
    return generate(system, user, max_tokens=max_tokens, model=model)


_catalog: tuple[float, list[str]] | None = None


def catalog(force: bool = False) -> list[str]:
    """이 키로 쓸 수 있는 모델 이름 목록 (/v1/models). 임베딩·재순위 같은 채팅용이 아닌 모델은 뺀다."""
    global _catalog
    if _catalog and not force and time.time() - _catalog[0] < 3600:
        return _catalog[1]
    r = httpx.get(config.NVIDIA_BASE_URL.rstrip("/") + "/models", headers=_headers(), timeout=config.HTTP_TIMEOUT * 2)
    if r.status_code in (401, 403):
        raise LLMUnavailable(f"NVIDIA API 키를 확인하세요 ({_err(r)})")
    r.raise_for_status()
    skip = ("embed", "rerank", "reward", "clip", "parakeet", "whisper", "tts", "asr", "ocr", "retriever", "nemoretriever",
            "safety", "guard", "detector", "paddle", "stable-diffusion", "flux", "sdxl", "cosmos", "vista", "kosmos", "deplot", "neva", "fuyu")
    ids = sorted({m.get("id", "") for m in r.json().get("data", []) if m.get("id") and not any(k in m["id"].lower() for k in skip)})
    _catalog = (time.time(), ids)
    return ids
