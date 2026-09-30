"""환경 변수 기반 설정."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
STATE_DIR = Path(os.getenv("STATE_DIR", BASE_DIR / "state"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY", "")

# auto: 바이낸스 선물 공개 API 시도 → 실패 시 합성 데이터
# binance: 바이낸스만 사용 (실패 시 에러)
# synthetic: 오프라인 데모용 합성 캔들
DATA_SOURCE = os.getenv("DATA_SOURCE", "auto")

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "10"))
PAPER_POLL_SECONDS = float(os.getenv("PAPER_POLL_SECONDS", "15"))


def llm_enabled() -> bool:
    return bool(ANTHROPIC_API_KEY)
