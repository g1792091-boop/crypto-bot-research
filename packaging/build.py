"""PyInstaller 로 단일 실행 파일을 만든다 (현재 OS 용).

    pip install -r backend/requirements.txt -r packaging/requirements-desktop.txt
    python packaging/build.py

결과: dist/GHQuant-<os>/  (실행 파일 + settings.txt + HOW-TO-RUN.txt)
Windows 용 .exe 는 Windows 에서, Mac 용은 Mac 에서 빌드해야 한다 (GitHub Actions 가 자동 처리).
"""
from __future__ import annotations

import os
import time
import platform
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
NAME = "GHQuant"


def main() -> None:
    mac = platform.system() == "Darwin"
    extra = []
    try:                                    # PC 앱 창 (pywebview: 윈도우 WebView2 · 맥 WebKit)
        import webview  # noqa: F401
        extra += ["--collect-all", "webview"]
        if platform.system() == "Windows":
            extra += ["--collect-all", "clr_loader", "--collect-all", "pythonnet", "--hidden-import", "clr"]
    except ImportError:
        print("pywebview 가 없어 앱 창 없이(브라우저로 여는) 빌드합니다: pip install pywebview")
    icon = ROOT / "frontend" / "icons" / ("icon-512.png")
    # 빌드 번호 (화면 위쪽 GH QUANT 옆에 표시 — 새 버전이 실행 중인지 확인용)
    sha = (os.environ.get("GITHUB_SHA") or "local")[:7]
    (ROOT / "frontend" / "build.txt").write_text(f"{sha} · {time.strftime('%Y-%m-%d')}", encoding="utf-8")
    PyInstaller.__main__.run([
        str(ROOT / "backend" / "launcher.py"),
        "--name", NAME,
        # 윈도우: exe 하나 · 맥: GHQuant.app 묶음 (콘솔 창 없이 앱 창만)
        "--onedir" if mac else "--onefile",
        "--windowed",
        "--icon", str(icon),
        "--osx-bundle-identifier", "com.ghquant.app",
        *extra,
        "--noconfirm",
        "--clean",
        "--paths", str(ROOT / "backend"),
        "--add-data", f"{ROOT / 'frontend'}{os.pathsep}frontend",
        # 연구 지식 카드 (app/knowledge/__init__.py 가 자기 폴더에서 읽는다)
        "--add-data", f"{ROOT / 'backend' / 'app' / 'knowledge' / 'cards.json'}{os.pathsep}app/knowledge",
        "--add-data", f"{ROOT / 'backend' / 'app' / 'knowledge' / 'research-summary.md'}{os.pathsep}app/knowledge",
        # uvicorn 은 루프/프로토콜 구현을 문자열로 동적 import 한다
        "--collect-submodules", "uvicorn",
        # 함수 안에서 불러오는 모듈 (Gemini 등)도 빠짐없이 넣는다
        "--collect-submodules", "app",
        "--distpath", str(ROOT / "dist" / "bin"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ])

    os_name = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")
    arch = platform.machine().lower().replace("amd64", "x64").replace("x86_64", "x64")
    out = ROOT / "dist" / f"{NAME}-{os_name}-{arch}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    if mac:
        shutil.copytree(ROOT / "dist" / "bin" / f"{NAME}.app", out / f"{NAME}.app", symlinks=True)
    else:
        exe = NAME + (".exe" if os_name == "windows" else "")
        shutil.copy2(ROOT / "dist" / "bin" / exe, out / exe)
    shutil.copy2(ROOT / "packaging" / "HOW-TO-RUN.txt", out / "HOW-TO-RUN.txt")

    sys.path.insert(0, str(ROOT / "backend"))
    from launcher import SETTINGS_TEMPLATE
    (out / "settings.txt").write_text(SETTINGS_TEMPLATE, encoding="utf-8")
    print(f"\nDone: {out}")


if __name__ == "__main__":
    main()
