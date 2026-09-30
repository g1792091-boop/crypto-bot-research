"""더블클릭 실행용 런처.

- 실행 파일 옆의 settings.txt 에서 API 키 등을 읽는다 (없으면 템플릿 생성)
- 빈 포트를 골라 서버를 켜고 브라우저를 자동으로 연다
- 페이퍼 계좌/봇 상태는 실행 파일 옆 state 폴더에 저장

개발 중에는 `python launcher.py` 로도 똑같이 실행된다.
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import traceback
import webbrowser
from pathlib import Path

SETTINGS_TEMPLATE = """\
# GH Quant 설정 파일
# 이 파일을 메모장으로 열어 '=' 뒤에 값을 넣고 저장한 뒤, 프로그램을 다시 실행하세요.
# 비워 두어도 동작합니다 (AI는 규칙 기반, 파생 데이터는 바이낸스 무료 데이터 사용).

# ── AI 키 (하나만 넣어도 됩니다. 여러 개면 Claude → NVIDIA → Gemini 순서로 씁니다) ──
# 자연어 전략 변환 · 전략 대화 수정 · AI 에이전트 팀 · 뉴스 한 줄 요약 · 차트 AI 코멘트에 쓰입니다.

# Gemini API 키 — 무료 (구글 계정으로 https://aistudio.google.com/apikey 에서 "Create API key")
#   무료 등급은 분당 약 10회·하루 수백 회 제한이 있어 AI 기능이 조금 느릴 수 있습니다.
#   무료 등급에서는 입력한 내용이 구글의 서비스 개선에 쓰일 수 있습니다.
GEMINI_API_KEY=

# NVIDIA API 키 — 무료 (https://build.nvidia.com 로그인 → 아무 모델 페이지에서 "Get API Key", nvapi- 로 시작)
#   가입 크레딧과 분당 약 40회 제한이 있습니다. OpenAI 호환 API 입니다.
#   NVIDIA_MODEL 에 build.nvidia.com 의 모델 이름을 넣으면 그 모델을 씁니다 (비우면 meta/llama-3.3-70b-instruct)
#   예) deepseek-ai/deepseek-v3.1 · qwen/qwen3-235b-a22b · moonshotai/kimi-k2-instruct · nvidia/llama-3.3-nemotron-super-49b-v1.5
#   NVIDIA_FAST_MODEL 은 에이전트 팀의 반복 분석용 가벼운 모델 (비우면 같은 모델)
NVIDIA_API_KEY=
NVIDIA_MODEL=
NVIDIA_FAST_MODEL=

# Claude API 키 (유료, https://console.anthropic.com)
ANTHROPIC_API_KEY=

# 여러 개 넣었을 때 강제로 고르려면: auto / claude / nvidia / gemini
LLM_PROVIDER=auto

# CoinGlass API 키 (https://www.coinglass.com/pricing) — OI/펀딩/롱숏/청산 데이터
COINGLASS_API_KEY=

# 데이터 소스: auto(바이낸스, 실패 시 합성 데이터) / binance / synthetic(오프라인 데모)
DATA_SOURCE=auto

# 사용할 포트 (이미 사용 중이면 자동으로 다른 포트를 고릅니다)
PORT=8000
"""


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_settings(path: Path) -> None:
    if not path.exists():
        path.write_text(SETTINGS_TEMPLATE, encoding="utf-8")
        print(f"설정 파일을 만들었습니다: {path}")
    elif "GEMINI_API_KEY" not in path.read_text(encoding="utf-8-sig"):
        # 예전 버전의 설정 파일이면 무료 Gemini 키 칸을 덧붙여 준다 (기존 값은 그대로)
        start = SETTINGS_TEMPLATE.index("# Gemini API 키")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n" + SETTINGS_TEMPLATE[start:SETTINGS_TEMPLATE.index("# Claude API 키")])
        print("설정 파일에 무료 Gemini 키 칸(GEMINI_API_KEY)을 추가했습니다.")
    if path.exists() and "NVIDIA_API_KEY" not in path.read_text(encoding="utf-8-sig"):
        # 예전 설정 파일이면 무료 NVIDIA 키 칸을 덧붙인다 (기존 값은 그대로)
        start = SETTINGS_TEMPLATE.index("# NVIDIA API 키")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n" + SETTINGS_TEMPLATE[start:SETTINGS_TEMPLATE.index("# Claude API 키")])
        print("설정 파일에 무료 NVIDIA 키 칸(NVIDIA_API_KEY)을 추가했습니다.")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (s.strip().strip('"').strip("'") for s in line.split("=", 1))
        if value and not os.environ.get(key):
            os.environ[key] = value


def pick_port(preferred: int) -> int:
    for port in [preferred, *range(preferred + 1, preferred + 20)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    # 창/파일 어디로 출력되든 한글이 깨지거나 늦게 보이지 않게
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True, errors="replace")
    base = app_dir()
    load_settings(base / "settings.txt")
    os.environ["SETTINGS_FILE"] = str(base / "settings.txt")   # 화면에서 키를 넣으면 이 파일에 저장
    os.environ.setdefault("STATE_DIR", str(base / "state"))
    port = pick_port(int(os.environ.get("PORT") or 8000))
    url = f"http://127.0.0.1:{port}"

    # 설정을 환경 변수에 올린 뒤에 앱을 불러와야 config 가 값을 읽는다
    import uvicorn
    from app.main import app

    print("=" * 56)
    print(" GH Quant 실행 중")
    print(f" 브라우저 주소: {url}")
    from app import config as _cfg
    ai = {"claude": "Claude", "nvidia": f"NVIDIA ({_cfg.NVIDIA_MODEL})", "gemini": "Gemini"}.get(_cfg.provider() or "", "미설정 (규칙 기반)")
    print(f" AI: {ai}"
          f" / CoinGlass: {'연결' if os.environ.get('COINGLASS_API_KEY') else '미설정 (바이낸스 대체)'}")
    print(" 종료하려면 이 창을 닫거나 Ctrl+C 를 누르세요.")
    print("=" * 56)
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.5, webbrowser.open, [url]).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        # 더블클릭 실행 시 창이 바로 닫혀 오류를 못 보는 일을 막는다
        if getattr(sys, "frozen", False):
            input("\n오류가 발생했습니다. 위 내용을 복사해 두고 Enter 를 누르면 종료합니다.")
        sys.exit(1)
