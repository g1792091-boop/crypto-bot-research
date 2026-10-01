"""AI 모델 배정 — 여러 모델을 등록하고 기능·에이전트마다 다른 모델을 쓰며, 막히면 다음 모델로 넘어간다.

모델은 '공급자:모델 이름' 으로 적는다.
  nvidia:auto(자동 선택) · nvidia:deepseek-ai/deepseek-v3.1 · gemini:auto · gemini:gemini-2.5-flash · claude:claude-opus-5-5
설정 (state/ai_routes.json, 화면의 'AI 모델' 창에서 바꿈):
  models   : 내 모델 목록 (고르는 칸에 나옴)
  default  : 기본 모델 (비우면 키가 있는 공급자의 기본 모델)
  features : 기능별 모델 — copilot(실시간 AI) · autopilot(AI 매매법 제안·시그널 코멘트) · strategy(전략 대화·자연어 변환)
             · news(뉴스 요약) · analysis(차트 AI 코멘트·복기) · team_heavy(에이전트 팀 판단형) · team_light(에이전트 팀 반복 분석형)
             · auto(AI 자동 모드: 마켓 브리핑·리스크·봇 코치·스캐너 코멘트)
  roles    : 에이전트별 모델 (23명, 비우면 팀 등급 설정을 따름)
  fallback : 앞 모델이 한도·오류로 실패하면 차례로 시도할 모델들
"""
from __future__ import annotations

import json
import re

from . import config, nvidia

_SEP = re.compile(r"[\s,;|·•、]+")

FEATURES = {
    "copilot": "실시간 AI (트레이드 오른쪽 AI 탭 · 포지션 감시)",
    "autopilot": "오토파일럿 (AI 매매법 제안 · 진입 시그널 코멘트)",
    "strategy": "전략 대화 · 자연어 → 전략 변환",
    "news": "뉴스 한 줄 요약",
    "analysis": "차트 AI 코멘트 · 복기 요약",
    "team_heavy": "에이전트 팀 — 판단형 (전략가·리스크·검증관·승인관 등 Opus 급)",
    "team_light": "에이전트 팀 — 반복 분석형 (시장분석·복기 등 Sonnet 급)",
    "auto": "AI 자동 모드 (마켓 브리핑 · 포트폴리오 리스크 · 봇 코치 · 스캐너 코멘트)",
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
        if _clean(_state):                        # 예전에 한 칸에 여러 모델을 붙여 넣은 설정 → 나눠서 다시 저장
            _write(_state)
    return _state


def _prov_ok(p: str) -> bool:
    from . import keyring
    return keyring.parse(p) is not None


def split_routes(text: str, provider: str | None = None) -> list[str]:
    """'a/b · c/d, gemini:auto' 처럼 여러 개가 한 칸에 들어와도 '공급자:모델' 여러 개로 나눈다."""
    out = []
    head, _, rest = (text or "").strip().partition(":")
    if _prov_ok(head):                          # 'nvidia:a/b · c/d' → 공급자는 앞의 것을 따름
        provider, text = head, rest
    for tok in _SEP.split(text or ""):
        tok = tok.strip().strip("'\"")
        if not tok:
            continue
        p, _, m = tok.partition(":")
        r = tok if _prov_ok(p) and m else f"{provider}:{tok}" if provider else ""
        if r and valid(r):
            out.append(r)
    return list(dict.fromkeys(out))


def _clean(st: dict) -> bool:
    """잘못 저장된 모델 칸(여러 이름이 붙은 것)을 고친다. 바뀌었으면 True."""
    changed = False
    for k in ("models", "fallback"):
        fixed = []
        for r in st.get(k) or []:
            parts = split_routes(r) if isinstance(r, str) else []
            changed |= parts != [r]
            fixed += parts
        st[k] = list(dict.fromkeys(fixed))
    extra = []
    for key in ("default",):
        r = st.get(key) or ""
        if r and not valid(r):
            parts = split_routes(r)
            st[key] = parts[0] if parts else ""
            extra += parts[1:]
            changed = True
    for k in ("features", "roles"):
        for a, r in list((st.get(k) or {}).items()):
            if not valid(r):
                parts = split_routes(r)
                if parts:
                    st[k][a] = parts[0]
                    extra += parts[1:]
                else:
                    st[k].pop(a)
                changed = True
    for r in extra:                                   # 뒤에 붙어 있던 모델은 대체 순서로
        if r not in st["fallback"]:
            st["fallback"].append(r)
    for r in [st.get("default"), *st["features"].values(), *st["roles"].values(), *st["fallback"]]:
        if r and r not in st["models"]:
            st["models"].append(r)
            changed = True
    return changed


def _write(st: dict) -> None:
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def save(new: dict) -> dict:
    st = load()
    for k in ("models", "fallback"):
        if isinstance(new.get(k), list):
            st[k] = list(dict.fromkeys(r for x in new[k] if isinstance(x, str) for r in split_routes(x)))[:40]
    if isinstance(new.get("default"), str):
        st["default"] = new["default"].strip()
    for k in ("features", "roles"):
        if isinstance(new.get(k), dict):
            st[k] = {a: b.strip() for a, b in new[k].items() if isinstance(b, str) and b.strip()}
    _clean(st)
    _write(st)
    return st


def reset_cache() -> None:
    global _state
    _state = None


def valid(route: str) -> bool:
    """'공급자:모델' 또는 '공급자#키번호:모델' 한 개. 모델 이름에 공백·구분 기호가 있으면(여러 개가 붙은 것) 안 됨."""
    from . import keyring
    p, _, m = (route or "").partition(":")
    return keyring.parse(p) is not None and bool(m.strip()) and not _SEP.search(m.strip())


def key_ok(provider: str) -> bool:
    """'nvidia' 또는 'nvidia#2' — 그 키가 들어 있나."""
    from . import keyring
    ps = keyring.parse(provider)
    return bool(ps and keyring.key(*ps))


def available(route: str) -> bool:
    return valid(route) and key_ok(route.split(":", 1)[0])


def split(route: str) -> tuple[str, str]:
    """('nvidia', '모델') — 키 번호는 slot_of() 로."""
    p, _, m = route.partition(":")
    return p.split("#", 1)[0], m


def slot_of(route: str) -> int:
    from . import keyring
    ps = keyring.parse(route.partition(":")[0])
    return ps[1] if ps else 1


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
    last = [] if route else [legacy(tier), *_auto_routes()]           # 마지막 수단: 키가 있는 공급자의 자동 선택
    out = [r for r in dict.fromkeys([first, *([] if route else st["fallback"]), *last]) if r and available(r)]
    return out


def _auto_routes() -> list[str]:
    return [r for r in ("nvidia:auto", "gemini:auto") if key_ok(r.split(":")[0])]


def primary() -> str | None:
    c = chain()
    return c[0] if c else None


def nvidia_suggest() -> list[str]:
    """이미 불러온 모델 목록이 있으면 거기서 우선순위대로, 없으면 잘 알려진 이름들 (종료된 것 제외)."""
    ranked = nvidia.rank(nvidia._catalog[1]) if nvidia._catalog else nvidia.rank(list(nvidia.STATIC))
    fast = nvidia.rank(nvidia._catalog[1], fast=True) if nvidia._catalog else []
    names = list(dict.fromkeys(ranked[:6] + fast[:2]))
    return ["nvidia:auto", "nvidia:auto-fast"] + ["nvidia:" + m for m in names]


def view() -> dict:
    st = load()
    from . import keyring
    return {**st, "features_desc": FEATURES, "keys": {p: key_ok(p) for p in PROVIDERS}, "key_slots": keyring.view(), "primary": primary(),
            "dead": {"nvidia:" + m: d for m, d in nvidia.dead().items()},
            "auto": {"nvidia": nvidia.peek_auto(False), "nvidia_fast": nvidia.peek_auto(True)},
            "suggest": {
                "nvidia": nvidia_suggest(),
                "gemini": ["gemini:auto", "gemini:gemini-2.5-flash", "gemini:gemini-2.5-flash-lite"],
                "claude": [f"claude:{config.CLAUDE_MODEL}"] + ([f"claude:{config.CLAUDE_FAST_MODEL}"] if config.CLAUDE_FAST_MODEL else [])}}
