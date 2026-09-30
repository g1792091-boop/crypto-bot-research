"""환경 변수 기반 설정."""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# PyInstaller 로 묶은 실행 파일이면 번들 안에 풀린 임시 폴더에서 frontend 를 찾는다
ROOT_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR.parent))
FRONTEND_DIR = ROOT_DIR / "frontend"
STATE_DIR = Path(os.getenv("STATE_DIR", BASE_DIR / "state"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

# Google Gemini (무료 등급 키로도 사용 가능: https://aistudio.google.com/apikey)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")          # 비우면 키로 쓸 수 있는 최신 Flash 모델을 자동 선택
GEMINI_RPM = int(os.getenv("GEMINI_RPM", "10"))        # 분당 최대 요청 수 (무료 등급 한도에 맞춤)

# 어떤 AI 를 쓸지: auto(Claude 키가 있으면 Claude, 없으면 Gemini) / claude / gemini
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto").strip().lower()

COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY", "")

# auto: 바이낸스 선물 공개 API 시도 → 실패 시 합성 데이터
# binance: 바이낸스만 사용 (실패 시 에러)
# synthetic: 오프라인 데모용 합성 캔들
DATA_SOURCE = os.getenv("DATA_SOURCE", "auto")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "10"))
PAPER_POLL_SECONDS = float(os.getenv("PAPER_POLL_SECONDS", "15"))


def provider() -> str | None:
    """실제로 쓸 AI: 'claude' / 'gemini' / None(키 없음 → 규칙 기반)."""
    if LLM_PROVIDER == "gemini" and GEMINI_API_KEY:
        return "gemini"
    if LLM_PROVIDER == "claude" and ANTHROPIC_API_KEY:
        return "claude"
    if ANTHROPIC_API_KEY:
        return "claude"
    if GEMINI_API_KEY:
        return "gemini"
    return None


def llm_enabled() -> bool:
    return provider() is not None
