"""PyInstaller 로 단일 실행 파일을 만든다 (현재 OS 용).

    pip install -r backend/requirements.txt pyinstaller
    python packaging/build.py

결과: dist/CoinFuturesTerminal-<os>/  (실행 파일 + settings.txt + HOW-TO-RUN.txt)
Windows 용 .exe 는 Windows 에서, Mac 용은 Mac 에서 빌드해야 한다 (GitHub Actions 가 자동 처리).
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
NAME = "CoinFuturesTerminal"


def main() -> None:
    PyInstaller.__main__.run([
        str(ROOT / "backend" / "launcher.py"),
        "--name", NAME,
        "--onefile",
        "--console",
        "--noconfirm",
        "--clean",
        "--paths", str(ROOT / "backend"),
        "--add-data", f"{ROOT / 'frontend'}{os.pathsep}frontend",
        # uvicorn 은 루프/프로토콜 구현을 문자열로 동적 import 한다
        "--collect-submodules", "uvicorn",
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
    exe = NAME + (".exe" if os_name == "windows" else "")
    shutil.copy2(ROOT / "dist" / "bin" / exe, out / exe)
    shutil.copy2(ROOT / "packaging" / "HOW-TO-RUN.txt", out / "HOW-TO-RUN.txt")

    sys.path.insert(0, str(ROOT / "backend"))
    from launcher import SETTINGS_TEMPLATE
    (out / "settings.txt").write_text(SETTINGS_TEMPLATE, encoding="utf-8")
    print(f"\nDone: {out}")


if __name__ == "__main__":
    main()
