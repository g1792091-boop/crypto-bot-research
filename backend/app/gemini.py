"""Google Gemini API (REST) 호출 — 무료 등급 키로도 동작한다.

- 모델 이름이 자주 바뀌므로, 키로 쓸 수 있는 모델 목록을 받아 가장 최신 Flash 를 고른다 (GEMINI_MODEL 로 고정 가능).
- 무료 등급은 분당·하루 요청 수가 적다. 분당 GEMINI_RPM 회를 넘지 않게 간격을 두고,
  한도(429)에 걸리면 잠깐 기다렸다 다시 시도하거나 같은 키의 다른 Flash 모델(한도가 따로 잡힘)로 넘어간다.
- 구조화 출력: JSON 스키마를 responseJsonSchema 로 넘기고 pydantic 으로 검증한다. 형식이 틀리면 한 번 더 요청.
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

BASE = "https://generativelanguage.googleapis.com/v1beta"
_SKIP = ("image", "tts", "audio", "live", "embedding", "robotics", "computer-use", "native", "exp")
FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]

_lock = threading.Lock()
_calls: deque[float] = deque()
_models: tuple[float, list[str]] | None = None
last_model: str | None = None


class _SchemaRejected(Exception):
    pass


def _headers() -> dict:
    if not config.GEMINI_API_KEY:
        raise LLMUnavailable("GEMINI_API_KEY 가 설정되지 않았습니다.")
    return {"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"}


def _rank(name: str) -> tuple:
    """최신·정식·일반(Flash) 모델이 앞으로. Flash-Lite 는 한도가 넉넉해서 예비로 뒤에 둔다."""
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    ver = float(m.group(1)) if m else 0.0
    return ("lite" in name, "preview" in name, -ver, len(name), name)


def pick_models(listing: list[dict]) -> list[str]:
    names = []
    for m in listing:
        n = m.get("name", "").removeprefix("models/")
        if ("generateContent" in m.get("supportedGenerationMethods", []) and n.startswith("gemini")
                and "flash" in n and not any(s in n for s in _SKIP)):
            names.append(n)
    return sorted(set(names), key=_rank)


def models() -> list[str]:
    """시도할 모델 순서."""
    global _models
    if _models is None or time.time() - _models[0] > 6 * 3600:
        found: list[str] = []
        try:
            token = ""
            for _ in range(5):
                r = httpx.get(f"{BASE}/models", params={"pageSize": 1000, **({"pageToken": token} if token else {})},
                              headers=_headers(), timeout=config.HTTP_TIMEOUT)
                if r.status_code in (400, 401, 403):
                    raise LLMUnavailable(f"Gemini API 키를 확인하세요 ({_err(r)})")
                r.raise_for_status()
                d = r.json()
                found += pick_models(d.get("models", []))
                token = d.get("nextPageToken", "")
                if not token:
                    break
        except httpx.HTTPError:
            found = []
        found = sorted(set(found), key=_rank) or FALLBACK_MODELS
        _models = (time.time(), found)
    out = list(_models[1])
    if config.GEMINI_MODEL:
        out = [config.GEMINI_MODEL] + [m for m in out if m != config.GEMINI_MODEL]
    # 하나의 모델이 막혀도 넘어갈 곳이 있도록: 일반 Flash 2개 + Lite 1개 정도만 시도
    flash = [m for m in out if "lite" not in m][:2]
    lite = [m for m in out if "lite" in m][:1]
    return (flash + lite) or out[:3]


def _throttle() -> None:
    with _lock:
        now = time.monotonic()
        while _calls and now - _calls[0] > 60:
            _calls.popleft()
        if len(_calls) >= max(1, config.GEMINI_RPM):
            time.sleep(max(0.0, 60 - (now - _calls[0])) + 0.3)
        _calls.append(time.monotonic())


def _err(r: httpx.Response) -> str:
    try:
        return r.json().get("error", {}).get("message", "")[:200] or r.text[:200]
    except ValueError:
        return r.text[:200]


def _retry_delay(r: httpx.Response) -> float:
    try:
        for d in r.json().get("error", {}).get("details", []):
            if "retryDelay" in d:
                return float(str(d["retryDelay"]).rstrip("s"))
    except (ValueError, TypeError):
        pass
    return 10.0


def generate(system: str, user: str, schema: dict | None = None, json_mode: bool = False, max_tokens: int = 16000) -> str:
    global last_model
    gen: dict = {"maxOutputTokens": max_tokens}
    if schema is not None or json_mode:
        gen["responseMimeType"] = "application/json"
    if schema is not None:
        gen["responseJsonSchema"] = schema
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": gen}
    limited = False
    for model in models():
        for attempt in range(3):
            _throttle()
            try:
                r = httpx.post(f"{BASE}/models/{model}:generateContent", headers=_headers(), json=body, timeout=180)
            except httpx.HTTPError as e:
                if attempt == 2:
                    raise LLMUnavailable(f"Gemini 연결 실패: {e}") from e
                time.sleep(2)
                continue
            if r.status_code == 429:
                limited = True
                wait = _retry_delay(r)
                if attempt == 0 and wait <= 30:
                    time.sleep(wait + 0.5)
                    continue
                break                                   # 이 모델은 한도 초과 → 다음 모델
            if r.status_code == 404:
                break                                   # 없어진 모델 → 다음 모델
            if r.status_code == 400 and schema is not None and "schema" in r.text.lower():
                raise _SchemaRejected(_err(r))
            if r.status_code in (400, 401, 403) and ("key" in r.text.lower() or r.status_code != 400):
                raise LLMUnavailable(f"Gemini API 키를 확인하세요 ({_err(r)})")
            if r.status_code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise LLMUnavailable(f"Gemini 오류 {r.status_code}: {_err(r)}")
            d = r.json()
            cands = d.get("candidates") or []
            if not cands:
                raise LLMUnavailable(f"Gemini 가 응답을 거부했습니다 ({d.get('promptFeedback', {}).get('blockReason', '이유 없음')})")
            parts = (cands[0].get("content") or {}).get("parts") or []
            out = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            if not out.strip():
                raise LLMUnavailable(f"Gemini 빈 응답 (finishReason={cands[0].get('finishReason')})")
            last_model = model
            return out
    if limited:
        raise LLMUnavailable("Gemini 무료 사용 한도에 걸렸습니다. 1분쯤 뒤에 다시 시도하세요 "
                             "(무료 등급은 분당·하루 요청 수 제한이 있습니다).")
    raise LLMUnavailable("사용할 수 있는 Gemini 모델을 찾지 못했습니다. settings.txt 의 GEMINI_MODEL 을 비워 두세요.")


def inline_refs(schema: dict) -> dict:
    """pydantic 스키마의 $ref 를 풀어 한 덩어리로 (API 가 $defs 를 못 읽는 경우 대비)."""
    defs = schema.get("$defs", {})

    def walk(x, depth=0):
        if isinstance(x, dict):
            if "$ref" in x and depth < 20:
                name = x["$ref"].split("/")[-1]
                rest = {k: v for k, v in x.items() if k != "$ref"}
                return walk({**defs.get(name, {}), **rest}, depth + 1)
            return {k: walk(v, depth) for k, v in x.items() if k != "$defs"}
        if isinstance(x, list):
            return [walk(v, depth) for v in x]
        return x
    return walk(schema)


def _clean_json(txt: str) -> str:
    txt = txt.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m:
        txt = m.group(1).strip()
    if not txt.startswith("{"):
        a, b = txt.find("{"), txt.rfind("}")
        if a >= 0 and b > a:
            txt = txt[a:b + 1]
    return txt


def parse(system: str, user: str, schema_cls: type[T], max_tokens: int = 16000) -> T:
    js = inline_refs(schema_cls.model_json_schema())
    sys2 = (f"{system}\n\n출력 형식: 아래 JSON 스키마에 맞는 JSON 객체 하나만 출력한다. 설명이나 코드 블록은 붙이지 않는다.\n"
            f"{json.dumps(js, ensure_ascii=False)}")
    use_schema: dict | None = js
    msg = user
    for attempt in range(2):
        try:
            txt = generate(sys2, msg, use_schema, json_mode=True, max_tokens=max_tokens)
        except _SchemaRejected:
            use_schema = None
            txt = generate(sys2, msg, None, json_mode=True, max_tokens=max_tokens)
        try:
            return schema_cls.model_validate_json(_clean_json(txt))
        except ValidationError as e:
            if attempt:
                raise LLMUnavailable(f"Gemini 응답이 형식에 맞지 않습니다: {e.errors()[0].get('msg', '')}") from e
            msg = f"{user}\n\n(직전 응답이 스키마와 맞지 않았다: {str(e)[:600]}\n스키마에 정확히 맞는 JSON 만 다시 출력하라.)"
    raise LLMUnavailable("Gemini 응답 처리 실패")


def text(system: str, user: str, max_tokens: int = 16000) -> str:
    return generate(system, user, None, max_tokens=max_tokens)
