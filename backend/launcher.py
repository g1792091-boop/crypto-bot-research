"""더블클릭 실행용 런처.

- 실행 파일 옆의 settings.txt 에서 API 키 등을 읽는다 (없으면 템플릿 생성)
- 빈 포트를 골라 서버를 켜고, 브라우저가 아니라 자체 PC 앱 창(윈도우: WebView2 · 맥: WebKit)으로 연다
  (앱 창을 못 띄우는 PC 면 엣지·크롬 앱 창 → 기본 브라우저 순으로 대신 연다)
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
#   NVIDIA_MODEL 을 비우면 이 키로 쓸 수 있는 모델 중에서 자동으로 고르고, 모델이 종료되면 알아서 다른 모델로 바꿉니다.
#   특정 모델을 쓰려면 build.nvidia.com 의 모델 이름을 넣으세요 (그 모델이 종료되면 자동 선택으로 넘어감)
#   예) deepseek-ai/deepseek-v3.1 · qwen/qwen3-235b-a22b · moonshotai/kimi-k2-instruct · nvidia/llama-3.3-nemotron-super-49b-v1.5
#   NVIDIA_FAST_MODEL 은 에이전트 팀의 반복 분석용 가벼운 모델 (비우면 같은 모델, auto-fast 면 가벼운 모델 자동 선택)
NVIDIA_API_KEY=
NVIDIA_MODEL=
NVIDIA_FAST_MODEL=

# Claude API 키 (유료, https://console.anthropic.com)
ANTHROPIC_API_KEY=

# 여러 개 넣었을 때 강제로 고르려면: auto / claude / nvidia / gemini
LLM_PROVIDER=auto

# ── 키 여러 개 (AI 사무실 직원들이 나눠 쓰기) ──
# 무료 키는 분당 한도가 키마다 따로입니다. 2~9번 키를 넣고 'AI 사무실 → AI 배정' 에서 팀마다 nvidia#2:auto 처럼 고르거나
# '키 골고루 나누기' 를 누르면 팀마다 나눠 씁니다. (화면에서 넣어도 이 파일에 저장됩니다)
NVIDIA_API_KEY_2=
NVIDIA_API_KEY_3=
GEMINI_API_KEY_2=

# ── 실거래 (기본 꺼짐 · 기본 테스트넷) ──
# 바이낸스 USDT-M 선물 API 키. 'AI 사무실 → 실거래' 에서 직접 켜고, 매매법마다 승인해야 주문이 나갑니다.
# 반드시 '선물 거래' 권한만 주고 '출금' 권한은 절대 주지 마세요. 처음에는 테스트넷 키(testnet.binancefuture.com)로 시험하세요.
BINANCE_API_KEY=
BINANCE_API_SECRET=

# CoinGlass API 키 (https://www.coinglass.com/pricing) — OI/펀딩/롱숏/청산 데이터
COINGLASS_API_KEY=

# 데이터 소스: auto(바이낸스 → 바이비트 → OKX 실제 시세) / synthetic(오프라인 데모)
DATA_SOURCE=auto

# 사용할 포트 (이미 사용 중이면 자동으로 다른 포트를 고릅니다)
PORT=8000

# 1 = PC 앱 창으로 열기 (기본) / 0 = 평소 브라우저 탭으로 열기
APP_WINDOW=1

# ── 서버(클라우드)에서 24시간 돌릴 때 ──
# 접속 비밀번호. 서버 모드(launcher.py --server)에서는 꼭 넣어야 합니다. 브라우저가 물으면 아이디는 아무거나, 비밀번호는 이것.
APP_PASSWORD=
# 서버 모드에서 받을 주소 (0.0.0.0 = 모든 곳에서 접속 · 127.0.0.1 = 이 컴퓨터에서만)
HOST=0.0.0.0
"""


def app_dir() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent
    exe = Path(sys.executable).resolve()
    # 맥 앱 묶음(GHQuant.app/Contents/MacOS/GHQuant)이면 .app 이 있는 폴더에 settings.txt · state 를 둔다
    base = exe.parents[3] if exe.parent.name == "MacOS" and exe.parents[2].suffix == ".app" else exe.parent
    if not os.access(base, os.W_OK):            # 읽기 전용 위치(맥 격리 실행 등)면 사용자 폴더
        base = Path.home() / ("Library/Application Support/GHQuant" if sys.platform == "darwin" else "GHQuant")
        base.mkdir(parents=True, exist_ok=True)
    return base


def _log_to_file(base: Path) -> None:
    """콘솔 없는 앱 창 실행이면 출력·오류를 state/GHQuant.log 로 남긴다."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    (base / "state").mkdir(parents=True, exist_ok=True)
    f = open(base / "state" / "GHQuant.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = f


def message_box(title: str, text: str) -> None:
    """콘솔이 없을 때 오류·안내를 화면에 띄운다."""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["osascript", "-e", f"display dialog {text!r} with title {title!r} buttons {{\"확인\"}}"], check=False)
        else:
            print(f"{title}: {text}")
    except Exception:  # noqa: BLE001
        print(f"{title}: {text}")


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
    if path.exists() and "BINANCE_API_KEY" not in path.read_text(encoding="utf-8-sig"):
        # 키 여러 개 · 실거래 키 칸 (기존 값은 그대로)
        start = SETTINGS_TEMPLATE.index("# ── 키 여러 개")
        with path.open("a", encoding="utf-8") as f:
            f.write("\n" + SETTINGS_TEMPLATE[start:SETTINGS_TEMPLATE.index("# CoinGlass API 키")])
        print("설정 파일에 추가 AI 키 칸과 실거래 키 칸을 추가했습니다.")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (s.strip().strip('"').strip("'") for s in line.split("=", 1))
        if value and not os.environ.get(key):
            os.environ[key] = value


def _browsers() -> list[str]:
    """앱 창(--app)을 열 수 있는 크로미움 계열 브라우저 (Edge 는 윈도우에 기본으로 있음)."""
    if sys.platform == "win32":
        out = []
        for env in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData"):
            base = os.environ.get(env)
            if base:
                out += [str(Path(base, "Microsoft", "Edge", "Application", "msedge.exe")),
                        str(Path(base, "Google", "Chrome", "Application", "chrome.exe")),
                        str(Path(base, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"))]
        return [x for x in out if Path(x).exists()]
    if sys.platform == "darwin":
        apps = ["Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"]
        out = []
        for root in ("/Applications", str(Path.home() / "Applications")):
            out += [f"{root}/{a}.app/Contents/MacOS/{a}" for a in apps]
        return [x for x in out if Path(x).exists()]
    import shutil
    names = ["google-chrome", "google-chrome-stable", "microsoft-edge", "chromium", "chromium-browser", "brave-browser"]
    return [w for w in (shutil.which(n) for n in names) if w]


def open_app(url: str) -> None:
    """브라우저 탭(웹사이트)이 아니라 주소창 없는 따로 된 앱 창으로 연다. 크롬·엣지가 없으면 기본 브라우저."""
    import subprocess
    if os.environ.get("APP_WINDOW", "1") != "0":
        for exe in _browsers():
            try:
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                subprocess.Popen([exe, f"--app={url}", "--start-maximized", "--no-first-run"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
                return
            except OSError:
                continue
    webbrowser.open(url)


def _webview2_installed() -> bool:
    """윈도우에 WebView2(엣지 엔진) 런타임이 있나 — 없으면 옛 IE 엔진으로 열려 화면이 깨지므로 쓰지 않는다."""
    if sys.platform != "win32":
        return True
    import winreg
    guid = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
                      (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
                      (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{guid}")):
        try:
            with winreg.OpenKey(hive, key) as k:
                v, _ = winreg.QueryValueEx(k, "pv")
                if v and v != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def native_window(url: str, base: Path) -> bool:
    """브라우저 없이 PC 앱 창을 띄우고 창이 닫힐 때까지 기다린다. 띄울 수 없으면 False."""
    if os.environ.get("APP_WINDOW", "1") == "0" or not _webview2_installed():
        return False
    try:
        import webview
    except Exception:  # noqa: BLE001
        return False
    try:
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True       # 뉴스·유튜브 링크는 기본 브라우저로
        webview.settings["ALLOW_DOWNLOADS"] = True                      # 결과 파일 · ZIP 받기
        webview.create_window("GH Quant", url, width=1440, height=900, min_size=(1000, 640), maximized=True,
                              confirm_close=True, background_color="#0f1218", text_select=True, zoomable=True)
        store = base / "state" / "app-window"
        store.mkdir(parents=True, exist_ok=True)
        webview.start(gui="edgechromium" if sys.platform == "win32" else None, private_mode=False, storage_path=str(store),
                      localization={"global.quitConfirmation": "GH Quant 를 끌까요?\n끄면 AI 사무실 · 자동 분석도 멈춥니다. 계속 돌리려면 최소화(—)하세요.",
                                    "global.quit": "끄기", "global.cancel": "취소", "global.ok": "확인", "global.saveFile": "파일 저장"})
        return True
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return False


class _IdleExit:
    """앱 창 대신 브라우저로 열었을 때: 화면이 2분 동안 아무 요청도 안 하면(창을 닫으면) 프로그램도 끈다."""

    def __init__(self, app, on_idle) -> None:
        import time
        self.app, self.on_idle, self.last, self.seen, self.active = app, on_idle, time.time(), False, False
        threading.Thread(target=self._watch, daemon=True).start()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not scope["path"].startswith("/healthz"):
            import time
            self.last, self.seen = time.time(), True
        await self.app(scope, receive, send)

    def _watch(self) -> None:
        import time
        while True:
            time.sleep(10)
            # 창을 닫고 2분 · 또는 브라우저가 끝내 한 번도 안 열렸으면 5분 뒤 종료 (보이지 않는 프로그램이 남지 않게)
            if self.active and time.time() - self.last > (120 if self.seen else 300):
                self.on_idle()
                return


def running_here(port: int) -> bool:
    """이 포트에 GH Quant 가 이미 켜져 있나 (두 번 눌러도 프로그램이 둘이 되지 않게)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/manifest.webmanifest", timeout=1.5) as r:
            return b'"GH Quant"' in r.read(400)
    except Exception:  # noqa: BLE001
        return False


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
    _log_to_file(base)
    server = "--server" in sys.argv or os.environ.get("SERVER_MODE") == "1"   # 클라우드 서버: 창 없이 · 정해진 포트 · 비밀번호 필수
    settings = Path(os.environ.get("SETTINGS_FILE") or base / "settings.txt")
    load_settings(settings)
    os.environ["SETTINGS_FILE"] = str(settings)          # 화면에서 키를 넣으면 이 파일에 저장
    os.environ.setdefault("STATE_DIR", str(base / "state"))
    host = (os.environ.get("HOST") or "0.0.0.0") if server else "127.0.0.1"
    if host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("APP_PASSWORD", "").strip():
        print("=" * 56)
        print(" 서버 모드는 접속 비밀번호가 필요합니다.")
        print(f" {settings} 의 APP_PASSWORD= 뒤에 비밀번호를 넣고 다시 실행하세요.")
        print(" (비밀번호 없이 쓰려면 HOST=127.0.0.1 로 두고 SSH 터널로 접속)")
        print("=" * 56)
        sys.exit(2)
    want = int(os.environ.get("PORT") or 8000)
    if not server and not os.environ.get("NO_BROWSER") and running_here(want):
        print(f"GH Quant 가 이미 켜져 있어 창만 새로 엽니다: http://127.0.0.1:{want}")
        if not native_window(f"http://127.0.0.1:{want}", base):
            open_app(f"http://127.0.0.1:{want}")
        return
    port = want if server else pick_port(want)
    url = f"http://127.0.0.1:{port}" if not server else f"http://<서버 IP>:{port}"

    # 설정을 환경 변수에 올린 뒤에 앱을 불러와야 config 가 값을 읽는다
    import uvicorn
    from app.main import app

    print("=" * 56)
    print(" GH Quant 실행 중")
    print(f" 주소: {url}  (PC 앱 창으로 열립니다 · 앱 창을 닫으면 종료)")
    from app import config as _cfg
    ai = {"claude": "Claude", "nvidia": f"NVIDIA ({'자동 선택' if _cfg.NVIDIA_MODEL == 'auto' else _cfg.NVIDIA_MODEL})", "gemini": "Gemini"}.get(_cfg.provider() or "", "미설정 (규칙 기반)")
    print(f" AI: {ai}"
          f" / CoinGlass: {'연결' if os.environ.get('COINGLASS_API_KEY') else '미설정 (바이낸스 대체)'}")
    print(" 서버 모드 · 접속 비밀번호 켜짐" if server else " 종료하려면 앱 창을 닫으세요.")
    print("=" * 56)
    if os.environ.get("NO_BROWSER") or server:
        uvicorn.run(app, host=host, port=port, log_level="warning", proxy_headers=False)
        return
    # 서버는 뒤에서 돌리고, 앞에는 PC 앱 창을 띄운다 (창을 닫으면 프로그램 종료)
    holder: dict = {}

    def stop() -> None:
        if holder.get("server"):
            holder["server"].should_exit = True

    asgi = _IdleExit(app, stop)
    srv = uvicorn.Server(uvicorn.Config(asgi, host=host, port=port, log_level="warning", proxy_headers=False))
    holder["server"] = srv
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    import time
    for _ in range(150):                                       # 서버가 뜰 때까지 (최대 30초)
        if srv.started or not th.is_alive():
            break
        time.sleep(0.2)
    if not th.is_alive():
        message_box("GH Quant", "서버를 시작하지 못했습니다. state/GHQuant.log 를 확인하세요.")
        sys.exit(1)
    if native_window(url, base):
        stop()
        th.join(timeout=10)
        return
    # 앱 창을 못 띄우는 PC: 엣지·크롬 앱 창(없으면 기본 브라우저)으로 열고, 창을 닫은 뒤 2분이 지나면 끈다
    open_app(url)
    asgi.active = True
    th.join()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        # 더블클릭 실행 시 창이 바로 닫혀 오류를 못 보는 일을 막는다
        if getattr(sys, "frozen", False):
            message_box("GH Quant 오류", "실행 중 오류가 발생했습니다.\n" + traceback.format_exc()[-900:] + "\n\n자세한 내용: state/GHQuant.log")
        sys.exit(1)
