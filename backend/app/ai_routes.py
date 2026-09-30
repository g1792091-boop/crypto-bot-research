"""AI 모델 배정 — 여러 모델을 등록하고 기능·에이전트마다 다른 모델을 쓰며, 막히면 다음 모델로 넘어간다.

모델은 '공급자:모델 이름' 으로 적는다.
  nvidia:meta/llama-3.3-70b-instruct · nvidia:deepseek-ai/deepseek-v3.1 · gemini:auto · gemini:gemini-2.5-flash · claude:claude-opus-5-5
설정 (state/ai_routes.json, 화면의 'AI 모델' 창에서 바꿈):
  models   : 내 모델 목록 (고르는 칸에 나옴)
  default  : 기본 모델 (비우면 키가 있는 공급자의 기본 모델)
  features : 기능별 모델 — copilot(실시간 AI) · autopilot(AI 매매법 제안·시그널 코멘트) · strategy(전략 대화·자연어 변환)
             · news(뉴스 요약) · analysis(차트 AI 코멘트·복기) · team_heavy(에이전트 팀 판단형) · team_light(에이전트 팀 반복 분석형)
  roles    : 에이전트별 모델 (23명, 비우면 팀 등급 설정을 따름)
  fallback : 앞 모델이 한도·오류로 실패하면 차례로 시도할 모델들
"""
from __future__ import annotations

import json

from . import config

FEATURES = {
    "copilot": "실시간 AI (트레이드 오른쪽 AI 탭 · 포지션 감시)",
    "autopilot": "오토파일럿 (AI 매매법 제안 · 진입 시그널 코멘트)",
    "strategy": "전략 대화 · 자연어 → 전략 변환",
    "news": "뉴스 한 줄 요약",
    "analysis": "차트 AI 코멘트 · 복기 요약",
    "team_heavy": "에이전트 팀 — 판단형 (전략가·리스크·검증관·승인관 등 Opus 급)",
    "team_light": "에이전트 팀 — 반복 분석형 (시장분석·복기 등 Sonnet 급)",
}
PROVIDERS = ("claude", "nvidia", "gemini")
_state: dict | None = None


def _path():
    return config.STATE_DIR / "ai_routes.json"


def load() -> dict:
    global _state
    if _state is None:
        try:
            _state = json.loads(_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _state = {}
        _state.setdefault("models", [])
        _state.setdefault("default", "")
        _state.setdefault("features", {})
        _state.setdefault("roles", {})
        _state.setdefault("fallback", [])
    return _state


def save(new: dict) -> dict:
    st = load()
    for k in ("models", "fallback"):
        if isinstance(new.get(k), list):
            st[k] = [r for r in dict.fromkeys(x.strip() for x in new[k] if isinstance(x, str)) if valid(r)][:40]
    if isinstance(new.get("default"), str):
        st["default"] = new["default"].strip() if valid(new["default"].strip()) else ""
    for k in ("features", "roles"):
        if isinstance(new.get(k), dict):
            st[k] = {a: b.strip() for a, b in new[k].items() if isinstance(b, str) and b.strip() and valid(b.strip())}
    for r in [st["default"], *st["features"].values(), *st["roles"].values(), *st["fallback"]]:
        if r and r not in st["models"]:
            st["models"].append(r)
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return st


def reset_cache() -> None:
    global _state
    _state = None


def valid(route: str) -> bool:
    p, _, m = (route or "").partition(":")
    return p in PROVIDERS and bool(m.strip())


def key_ok(provider: str) -> bool:
    return bool({"claude": config.ANTHROPIC_API_KEY, "nvidia": config.NVIDIA_API_KEY, "gemini": config.GEMINI_API_KEY}.get(provider))


def available(route: str) -> bool:
    return valid(route) and key_ok(route.split(":", 1)[0])


def split(route: str) -> tuple[str, str]:
    p, _, m = route.partition(":")
    return p, m


def legacy(tier: str = "opus") -> str | None:
    """배정이 없을 때: 키가 있는 공급자의 기본 모델 (예전 동작과 같음)."""
    p = config.provider()
    if p == "claude":
        return "claude:" + (config.CLAUDE_MODEL if tier == "opus" or not config.CLAUDE_FAST_MODEL else config.CLAUDE_FAST_MODEL)
    if p == "nvidia":
        return "nvidia:" + (config.NVIDIA_FAST_MODEL if tier != "opus" and config.NVIDIA_FAST_MODEL else config.NVIDIA_MODEL)
    if p == "gemini":
        return "gemini:" + (config.GEMINI_MODEL or "auto")
    return None


def chain(feature: str | None = None, role: str | None = None, tier: str = "opus", route: str | None = None) -> list[str]:
    """이번 호출에서 차례로 시도할 모델들 (키가 있는 것만)."""
    st = load()
    first = route or (st["roles"].get(role) if role else None) or (st["features"].get(feature) if feature else None)
    if not first and feature in ("team_heavy", "team_light") and st["default"]:
        first = st["default"]
    first = first or st["default"] or legacy(tier)
    out = [r for r in dict.fromkeys([first, *([] if route else st["fallback"])]) if r and available(r)]
    if not out and not route:
        lg = legacy(tier)
        out = [lg] if lg else []
    return out


def primary() -> str | None:
    c = chain()
    return c[0] if c else None


def view() -> dict:
    st = load()
    return {**st, "features_desc": FEATURES, "keys": {p: key_ok(p) for p in PROVIDERS}, "primary": primary(),
            "suggest": {
                "nvidia": ["nvidia:meta/llama-3.3-70b-instruct", "nvidia:deepseek-ai/deepseek-v3.1", "nvidia:qwen/qwen3-235b-a22b",
                           "nvidia:moonshotai/kimi-k2-instruct", "nvidia:nvidia/llama-3.3-nemotron-super-49b-v1.5", "nvidia:meta/llama-3.1-8b-instruct"],
                "gemini": ["gemini:auto", "gemini:gemini-2.5-flash", "gemini:gemini-2.5-flash-lite"],
                "claude": [f"claude:{config.CLAUDE_MODEL}"] + ([f"claude:{config.CLAUDE_FAST_MODEL}"] if config.CLAUDE_FAST_MODEL else [])}}
