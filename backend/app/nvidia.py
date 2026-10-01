"""NVIDIA API (build.nvidia.com, 무료 개발자 키 nvapi-…) — OpenAI 호환 /v1/chat/completions.

- 키: https://build.nvidia.com 로그인 → 모델 페이지의 'Get API Key'. 무료 크레딧과 분당 약 40회 제한이 있다.
- 모델: NVIDIA_MODEL (기본 auto = 이 키로 쓸 수 있는 모델 목록에서 자동 선택). 반복 분석용은 NVIDIA_FAST_MODEL
  (비우면 같은 모델, auto-fast = 가벼운 모델 자동 선택).
- NVIDIA 는 모델을 수시로 종료(410 end of life)하거나 내린다(404). 그런 모델은 '종료됨'으로 기억하고
  (state/nvidia_models.json) 목록에서 쓸 수 있는 다른 모델로 바로 바꿔 다시 부른다.
- JSON 이 필요하면 response_format=json_object 를 요청하고(안 받는 모델이면 빼고 다시), 답에서 JSON 만 골라낸다.
- 생각 과정을 <think>…</think> 로 내는 추론 모델(DeepSeek-R1, Qwen3 등)은 그 부분을 지운다.
- 이 API 는 OpenAI 호환이라 NVIDIA_BASE_URL 만 바꾸면 다른 호환 서비스에도 쓸 수 있다.
"""
from __future__ import annotations

import contextvars
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
_tl = threading.local()                   # 이 스레드에서 마지막으로 실제 답한 모델
strict = contextvars.ContextVar("nvidia_strict", default=False)   # True 면 종료된 모델을 다른 모델로 바꾸지 않고 오류 (모델 테스트용)

AUTO = ("", "auto", "auto-fast")
# 자동 선택 우선순위 (이름에 들어 있는 글자). 같은 계열이 여러 개면 이름이 뒤인 것(보통 최신)을 먼저.
# 계열 이름으로 적어서 새 버전(deepseek-v4 · qwen3.5 · kimi-k3 …)도 잡히게 한다
PREF_MAIN = ("deepseek-v", "qwen3-235b", "kimi-k", "gpt-oss-120b", "qwen3", "llama-4-maverick", "nemotron-super",
             "nemotron-ultra", "glm-", "mistral-large", "mistral-medium", "llama-3.1-405b", "qwen2.5-72b", "llama-3.3-70b", "llama-3.1-70b")
PREF_FAST = ("gpt-oss-20b", "llama-4-scout", "qwen3-30b", "qwen3-32b", "nemotron-nano", "mistral-small", "llama-3.1-8b",
             "gemma-3", "phi-4", "llama-3.2-3b")
# 목록을 못 불러올 때 시도할 이름들
STATIC = ("deepseek-ai/deepseek-v3.1", "qwen/qwen3-235b-a22b", "moonshotai/kimi-k2-instruct", "openai/gpt-oss-120b",
          "meta/llama-4-maverick-17b-128e-instruct", "nvidia/llama-3.3-nemotron-super-49b-v1.5", "openai/gpt-oss-20b",
          "meta/llama-4-scout-17b-16e-instruct", "meta/llama-3.1-8b-instruct")
_NOT_CHAT = ("vision", "-vl", "vlm", "coder", "code", "math", "-base", "guard", "embed", "translate", "reward", "audio")
_SMALL = ("flash", "lite", "mini", "nano", "-8b", "-3b", "-1b", "tiny", "small")      # 본 분석에는 뒤로
_ODD = ("diffusion",)                                                                  # 채팅 API 가 잘 안 맞는 계열 — 맨 뒤
_dead: dict[str, dict] | None = None      # 종료·삭제된 모델 → {code, msg, at}


def _headers() -> dict:
    from . import keyring
    k = keyring.active("nvidia")
    if not k:
        raise LLMUnavailable("NVIDIA_API_KEY 가 설정되지 않았습니다.")
    return {"Authorization": f"Bearer {k}", "Content-Type": "application/json", "Accept": "application/json"}


_slot_calls: dict = {}


def _throttle() -> None:
    """분당 호출 한도는 키마다 따로 센다 (키를 여러 개 넣으면 그만큼 더 많이 부를 수 있다)."""
    from collections import deque
    from . import keyring
    n = keyring.active_slot("nvidia")
    with _lock:
        calls = _calls if n == 1 else _slot_calls.setdefault(n, deque())
        now = time.monotonic()
        while calls and now - calls[0] > 60:
            calls.popleft()
        if len(calls) >= max(1, config.NVIDIA_RPM):
            time.sleep(max(0.0, 60 - (now - calls[0])) + 0.3)
        calls.append(time.monotonic())


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
    return config.NVIDIA_MODEL or "auto"


# ---------------------------------------------------------------- 종료된 모델 기억 · 자동 선택
def _dead_path():
    return config.STATE_DIR / "nvidia_models.json"


def dead() -> dict[str, dict]:
    """종료(410)는 계속, 못 찾음(404)은 하루 동안 '쓸 수 없음'으로 본다."""
    global _dead
    if _dead is None:
        try:
            _dead = json.loads(_dead_path().read_text(encoding="utf-8")).get("dead", {})
        except (OSError, ValueError, AttributeError):
            _dead = {}
    now = time.time()
    return {m: d for m, d in _dead.items() if d.get("code") == 410 or now - d.get("at", 0) < 86400}


def is_dead(model: str) -> bool:
    return model in dead()


def mark_dead(model: str, code: int, msg: str) -> None:
    dead()
    _dead[model] = {"code": code, "msg": msg[:200], "at": time.time()}
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        _dead_path().write_text(json.dumps({"dead": _dead}, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def rank(models: list[str], fast: bool = False) -> list[str]:
    """채팅용 모델을 우선순위대로 (종료된 것 제외)."""
    gone = dead()
    ok = [m for m in models if m not in gone and not any(k in m.lower() for k in _NOT_CHAT)]
    out: list[str] = []
    small = lambda m: any(k in m.lower() for k in _SMALL)
    odd = lambda m: any(k in m.lower() for k in _ODD)
    for pref in (PREF_FAST + PREF_MAIN) if fast else PREF_MAIN:
        fam = sorted((m for m in ok if pref in m.lower() and m not in out and not odd(m)), reverse=True)   # 같은 계열은 새 버전 먼저
        out += fam if fast else sorted(fam, key=small)                                                   # 본 분석은 큰 모델 먼저
    rest = [m for m in ok if m not in out and not odd(m)]
    out += sorted(rest, key=lambda m: not ("instruct" in m.lower() or "chat" in m.lower()))
    out += [m for m in ok if m not in out]
    return out


def auto_model(fast: bool = False, exclude: tuple = ()) -> str | None:
    try:
        models = catalog()
    except Exception:                                  # 목록을 못 불러오면 잘 알려진 이름들로
        models = []
    picks = [m for m in rank(models, fast) if m not in exclude] or [m for m in rank(list(STATIC), fast) if m not in exclude]
    return picks[0] if picks else None


def peek_auto(fast: bool = False) -> str | None:
    """네트워크 없이 (이미 불러온 목록이 있을 때만) 자동 선택될 모델."""
    if not _catalog:
        return None
    picks = rank(_catalog[1], fast)
    return picks[0] if picks else None


def resolve(model: str | None) -> str:
    """'auto'·'auto-fast'·종료된 모델 → 지금 쓸 수 있는 모델 이름."""
    want = (model if model is not None else config.NVIDIA_MODEL or "auto").strip()
    if re.search(r"[\s,;|·•]", want):                  # 여러 모델 이름이 한 칸에 붙은 것 → 앞에서부터 쓸 수 있는 것
        parts = [x[7:] if x.startswith("nvidia:") else x for x in re.split(r"[\s,;|·•]+", want) if x]
        want = next((x for x in parts if not is_dead(x)), "auto")
    if want in AUTO:
        m = auto_model(fast=want == "auto-fast")
        if not m:
            raise LLMUnavailable("이 NVIDIA 키로 쓸 수 있는 채팅 모델을 찾지 못했습니다 ('AI 모델' 창 → 모델 목록 불러오기).")
        return m
    if is_dead(want):
        if strict.get():
            raise LLMUnavailable(_dead_msg(want))
        m = auto_model(fast=False)
        if not m:
            raise LLMUnavailable(_dead_msg(want))
        return m
    return want


def _dead_msg(model: str) -> str:
    d = dead().get(model, {})
    what = "NVIDIA 에서 종료된 모델" if d.get("code") == 410 else "NVIDIA 에서 찾을 수 없는 모델"
    return f"{model}: {what}입니다 — 'AI 모델' 창의 목록에서 빼고 다른 모델(또는 nvidia:auto)을 쓰세요. ({d.get('msg', '')})"


def used_model() -> str | None:
    """이 스레드에서 방금 실제로 답한(또는 마지막으로 시도한) 모델."""
    return getattr(_tl, "model", None)


def strip_think(txt: str) -> str:
    txt = re.sub(r"<think>.*?</think>", "", txt or "", flags=re.S)
    if "</think>" in txt:                         # 여는 태그 없이 닫는 태그만 있는 경우
        txt = txt.split("</think>", 1)[1]
    return txt.strip()


def generate(system: str, user: str, json_mode: bool = False, max_tokens: int = 4096, model: str | None = None) -> str:
    """모델이 종료·삭제됐으면 기억해 두고 쓸 수 있는 다른 모델로 바꿔 다시 부른다 (최대 3번)."""
    tried: list[str] = []
    _tl.model = None
    m = resolve(model)
    for _ in range(4):
        _tl.model = m                                   # 실패해도 어느 모델이었는지 남긴다
        try:
            return _generate(system, user, json_mode, max_tokens, m)
        except _Gone as g:
            mark_dead(m, g.code, g.msg)
            tried.append(m)
            if strict.get():
                raise LLMUnavailable(_dead_msg(m)) from None
            nxt = auto_model(fast=(model or "").strip() == "auto-fast", exclude=tuple(tried))
            if not nxt:
                raise LLMUnavailable(f"NVIDIA 모델 {m} 이(가) 종료되었고 바꿔 쓸 모델을 찾지 못했습니다: {g.msg}") from None
            m = nxt
    raise LLMUnavailable("NVIDIA 모델이 계속 종료·삭제 응답을 줍니다: " + ", ".join(tried))


class _Gone(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


def _generate(system: str, user: str, json_mode: bool, max_tokens: int, model: str) -> str:
    global last_model
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
        low = r.text.lower()
        unknown = r.status_code in (400, 422) and "model" in low and any(k in low for k in (
            "not found", "does not exist", "unknown model", "invalid model", "no such model", "not available", "unsupported model", "is not supported"))
        if unknown:                                  # 없는 모델 이름 (오타 · 여러 이름이 붙은 것 등) → 다른 모델로
            raise _Gone(404, _err(r))
        if r.status_code in (404, 410) or (r.status_code >= 400 and "end of life" in r.text.lower()):
            raise _Gone(410 if r.status_code == 410 or "end of life" in r.text.lower() else 404, _err(r))
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
        last_model = _tl.model = model
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
